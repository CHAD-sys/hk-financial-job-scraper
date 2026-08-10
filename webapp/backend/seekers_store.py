"""
Seeker persistence — the /data/seekers.db layer.

This is the FIRST place in the backend that WRITES to a database. Everything the
API does today is either a read against jobs.db (which is opened with
`PRAGMA query_only=ON`, see main.py) or an append to a JSONL queue. That makes a
few things worth stating up front, because they are not obvious from the code:

  - **This file is NEVER jobs.db.** Seeker data lives in its own SQLite file with
    its own writable connection (ADR 0006). jobs.db is rewritten nightly by the
    scraper, copied wholesale by backup.py, and may be replaced outright by
    `_seed_db_if_missing()`. Any of those would destroy accounts. The path
    resolver below refuses to open a file called jobs.db, on purpose.

  - **Deletion here is a REAL delete.** CLAUDE.md's "soft-delete only" rule
    governs *Roles* — a Seeker may want to revisit a vacancy that has closed.
    It does not extend to *Seekers*: when someone deletes their account the rows
    are actually removed and every session is revoked (ADR 0007). The only thing
    that survives is an `events` row recording that a deletion happened, so the
    obligation can be honoured retroactively by the CV/personalisation component
    when its contract exists.

  - **`seeker_id` is a uuid4 string.** Opaque, permanent, never reused, and never
    the email address. Email is mutable; anything downstream that keys off email
    breaks the day someone changes theirs (ADR 0006).

Conventions inherited from hk_jobs/storage.py:
  - stdlib sqlite3, hand-written SQL, no ORM (ADR 0004 rejected FastAPI-Users
    for exactly this reason).
  - Datetimes are ISO 8601 UTC text. SQLite has no datetime type; ISO text sorts
    correctly, round-trips through datetime.fromisoformat(), and survives a
    Postgres migration.
  - SQL is kept Postgres-compatible where it costs nothing. SQLite-only choices
    are marked "# SQLite:".

Nothing in this module knows about HTTP, FastAPI, cookies or email. It is a
storage layer; policy lives in auth.py and in the route handlers above it.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

logger = logging.getLogger(__name__)

# How long a query waits for a writer to finish before giving up with
# "database is locked". The Railway volume is network-backed, so a write can be
# slower than on local disk; five seconds is generous for a single-writer app
# with a handful of Seekers and still fails fast enough to surface a real
# deadlock rather than hanging a request forever.
_BUSY_TIMEOUT_SECONDS = 5.0

VALID_TOKEN_PURPOSES = ("verify", "reset")
RECOMMENDATION_FEEDBACK_ACTIONS = ("more_like", "not_interested", "wrong_reason")


class EmailAlreadyRegistered(Exception):
    """
    Raised by create_seeker() when the address already has an account.

    Deliberately an exception rather than a returned None: the *endpoint* must
    decide what to say, and per decision 15 the honest answer ("that address is
    taken") is exactly what an account-enumeration probe is looking for. The
    store's job is to make the collision impossible to miss; the route's job is
    to respond indistinguishably from a successful registration.
    """


# ── Where the file lives ──────────────────────────────────────────────────────


def _repo_data_dir() -> Path:
    """The repo's local data/ directory — the development default, as in main.py."""
    return Path(__file__).resolve().parent.parent.parent / "data"


def resolve_seekers_db_path() -> Path:
    """
    Decide which file is seekers.db, and refuse to return jobs.db.

    Resolution order:
      1. `SEEKERS_DB_PATH` if set — an explicit operator/test override.
      2. Otherwise, `seekers.db` **next to** wherever jobs.db resolves. main.py
         reads `JOBS_DB_PATH` (defaulting to <repo>/data/jobs.db), so on Railway
         where `JOBS_DB_PATH=/data/jobs.db` this lands on `/data/seekers.db` — the
         mounted volume — with no second environment variable to forget. Locally
         it lands in the repo's data/ directory alongside jobs.db.

    Read at call time, never at import time, so tests and a reload can change it.

    The guard at the bottom is not paranoia for its own sake. jobs.db is deleted
    and re-seeded by `_seed_db_if_missing()` and rewritten nightly by the
    pipeline; a misconfiguration that pointed Seeker accounts at it would not
    fail loudly, it would quietly lose every account on the next scrape.
    """
    override = os.environ.get("SEEKERS_DB_PATH", "").strip()
    if override:
        path = Path(override).expanduser().resolve()
    else:
        jobs_db = Path(
            os.environ.get("JOBS_DB_PATH", str(_repo_data_dir() / "jobs.db"))
        ).expanduser().resolve()
        path = jobs_db.parent / "seekers.db"

    if path.name == "jobs.db":
        raise ValueError(
            f"Refusing to use {path} for Seeker data: jobs.db is owned by the "
            "scraper and may be replaced wholesale (ADR 0006). Set SEEKERS_DB_PATH "
            "to a different file."
        )
    return path


# ── Schema, in phases, each one idempotent ────────────────────────────────────
#
# Same shape as hk_jobs/migrations.py: one function per phase, every function
# safe to run on every startup, and a new phase is a new function rather than an
# edit to an old one. That matters more here than in jobs.db, because jobs.db can
# be rebuilt from the pipeline and seekers.db cannot — it has no second copy
# anywhere (ADR 0006), so a destructive migration is unrecoverable.

_SEEKERS_DDL = """
CREATE TABLE IF NOT EXISTS seekers (
    -- uuid4 string. Opaque and permanent: it is the only identifier any other
    -- component (including the future CV/personalisation work) may key off.
    id              TEXT PRIMARY KEY,
    -- Always stored lowercased and stripped; normalise_email() below is the only
    -- way an address should reach this column. UNIQUE is what makes "one account
    -- per address" a database invariant rather than a hope.
    email           TEXT NOT NULL UNIQUE,
    -- NULL for a Seeker who has only ever signed in with Google: there is no
    -- password, as opposed to an empty or unusable one. Keeping it NULL means
    -- "set a password" and "change a password" are the same code path later.
    password_hash   TEXT,
    display_name    TEXT,
    -- 1 once the address is proven. Per decision 10 this gates outbound MAIL,
    -- not access: an unverified Seeker has a full account.
    email_verified  INTEGER NOT NULL DEFAULT 0,   -- SQLite: 1/0 for boolean
    created_at      TEXT NOT NULL,                -- ISO 8601 UTC
    last_login_at   TEXT                          -- ISO 8601 UTC, NULL until first login
);
"""

_SEEKER_IDENTITIES_DDL = """
CREATE TABLE IF NOT EXISTS seeker_identities (
    seeker_id     TEXT NOT NULL REFERENCES seekers (id) ON DELETE CASCADE,
    -- 'google' now, 'linkedin' when the fast-follow lands. A generic provider
    -- column is what lets a third provider be configuration rather than schema.
    provider      TEXT NOT NULL,
    -- The provider's own immutable subject id (OIDC `sub`). NOT the email:
    -- an email can be reassigned by its domain owner, `sub` cannot.
    provider_sub  TEXT NOT NULL,
    linked_at     TEXT NOT NULL,
    -- One provider identity maps to exactly one Seeker. A Seeker may hold
    -- several identities (Google today, LinkedIn later) — hence the PK is on the
    -- provider side, not on seeker_id.
    PRIMARY KEY (provider, provider_sub)
);
"""

_SESSIONS_DDL = """
CREATE TABLE IF NOT EXISTS sessions (
    -- SHA-256 hex of the opaque session token. The RAW token is never written
    -- here or anywhere else on the server (decision 11): it exists once, in the
    -- response that sets the cookie. A leaked seekers.db therefore leaks no live
    -- session, only useless digests.
    token_hash  TEXT PRIMARY KEY,
    seeker_id   TEXT NOT NULL REFERENCES seekers (id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL,   -- ISO 8601 UTC
    -- Rolling: refreshed forward on use (see auth.verify_session).
    expires_at  TEXT NOT NULL,   -- ISO 8601 UTC
    -- Recorded so a Seeker (or we, over `railway ssh`) can tell one device from
    -- another. Truncated by the caller; never trusted, never parsed.
    user_agent  TEXT
);
"""

_EMAIL_TOKENS_DDL = """
CREATE TABLE IF NOT EXISTS email_tokens (
    -- Hashed at rest for the same reason as sessions: the raw token travels in a
    -- link in an email and must not also be sitting in the database.
    token_hash  TEXT PRIMARY KEY,
    seeker_id   TEXT NOT NULL REFERENCES seekers (id) ON DELETE CASCADE,
    purpose     TEXT NOT NULL CHECK (purpose IN ('verify', 'reset')),
    created_at  TEXT NOT NULL,   -- ISO 8601 UTC
    expires_at  TEXT NOT NULL,   -- ISO 8601 UTC, <= 1 hour after created_at
    -- Non-NULL means spent. Single-use is enforced by an UPDATE ... WHERE
    -- used_at IS NULL, so two simultaneous clicks on the same link cannot both
    -- win (see claim_email_token).
    used_at     TEXT
);
"""

_SAVED_ROLES_DDL = """
CREATE TABLE IF NOT EXISTS saved_roles (
    seeker_id  TEXT NOT NULL REFERENCES seekers (id) ON DELETE CASCADE,
    -- A REFERENCE to a Role, never a copy of one. The job fields are joined from
    -- jobs.db at read time via ATTACH (phase 5), which is what makes a Saved Role
    -- show as closed once the Role is gone — the bug the localStorage version
    -- has today, where whole Job objects are frozen into the browser.
    source     TEXT NOT NULL,
    source_id  TEXT NOT NULL,
    saved_at   TEXT NOT NULL,   -- ISO 8601 UTC
    PRIMARY KEY (seeker_id, source, source_id)
);
"""

_EVENTS_DDL = """
CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    -- e.g. 'signup.completed', 'login.succeeded', 'role.saved', 'seeker.deleted'.
    name       TEXT NOT NULL,
    -- NOTE the deliberate absence of a FOREIGN KEY, and the absence of any
    -- cascade: an event must OUTLIVE the Seeker it refers to. ADR 0007 requires
    -- a deletion to be logged even though the personal data goes, and a foreign
    -- key would either block the delete or take the evidence with it. The uuid
    -- left behind is pseudonymous and no longer resolves to a person.
    seeker_id  TEXT,
    created_at TEXT NOT NULL   -- ISO 8601 UTC
);
"""

_INDEXES = [
    # Revoking every session on logout-everywhere, password reset and deletion.
    "CREATE INDEX IF NOT EXISTS idx_sessions_seeker  ON sessions (seeker_id);",
    # Sweeping expired sessions without a table scan.
    "CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions (expires_at);",
    "CREATE INDEX IF NOT EXISTS idx_email_tokens_seeker ON email_tokens (seeker_id);",
    "CREATE INDEX IF NOT EXISTS idx_saved_roles_seeker  ON saved_roles (seeker_id);",
    # Counting first-party events by name over a window (decision 19).
    "CREATE INDEX IF NOT EXISTS idx_events_name ON events (name, created_at);",
    "CREATE INDEX IF NOT EXISTS idx_identities_seeker ON seeker_identities (seeker_id);",
]


def migrate_to_phase_1(conn: sqlite3.Connection) -> None:
    """
    Create the six account tables: seekers, seeker_identities, sessions,
    email_tokens, saved_roles, events.

    Safe to call on every startup — every statement is CREATE ... IF NOT EXISTS,
    so the second and subsequent runs do nothing.
    """
    existing = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    conn.execute(_SEEKERS_DDL)
    conn.execute(_SEEKER_IDENTITIES_DDL)
    conn.execute(_SESSIONS_DDL)
    conn.execute(_EMAIL_TOKENS_DDL)
    conn.execute(_SAVED_ROLES_DDL)
    conn.execute(_EVENTS_DDL)
    for statement in _INDEXES:
        conn.execute(statement)

    wanted = (
        "seekers",
        "seeker_identities",
        "sessions",
        "email_tokens",
        "saved_roles",
        "events",
    )
    created = [t for t in wanted if t not in existing]
    if created:
        logger.info("seekers.db phase 1 migration: created tables: %s", ", ".join(created))
    else:
        logger.debug("seekers.db phase 1 migration: tables already exist")


def migrate_to_phase_2(conn: sqlite3.Connection) -> None:
    """
    Add `seekers.is_admin` — a privilege flag, not a new account type.

    Admin Mode reuses the ordinary Seeker sign-in (same email/password, same
    session cookie); the only difference is this one column. That is
    deliberately NOT the same shape as Employer (ADR 0001's separate aggregate):
    an Employer is a different kind of accountholder with its own required
    fields (company_name) and its own table. An admin is the same kind of
    accountholder with one extra bit of trust — a column fits, a second table
    or a `role` enum would not.

    `ALTER TABLE ... ADD COLUMN` is not idempotent on its own (it errors if the
    column already exists), unlike every DDL statement in phase 1, so this
    checks `PRAGMA table_info` first rather than relying on IF NOT EXISTS,
    which SQLite's ALTER TABLE does not support.
    """
    columns = {row[1] for row in conn.execute("PRAGMA table_info(seekers)").fetchall()}
    if "is_admin" not in columns:
        conn.execute("ALTER TABLE seekers ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
        logger.info("seekers.db phase 2 migration: added seekers.is_admin")
    else:
        logger.debug("seekers.db phase 2 migration: is_admin already present")


def migrate_to_phase_3(conn: sqlite3.Connection) -> None:
    """
    Add `seekers.username` — a short alternate login handle, alongside email.

    Built for Admin Mode: the five accounts scripts/create_admin.py creates get
    one ("kenson", not "kenson@finexclub.org") so signing in does not require
    remembering an email address for an account that was never given one to
    receive mail at. Nothing stops an ordinary Seeker having one too, but
    nothing offers it to them either — there is no self-serve way to set this
    column, on purpose, until there is an actual feature asking for one.

    A plain nullable column, not UNIQUE at the column level: SQLite's
    `ALTER TABLE ADD COLUMN` cannot carry a UNIQUE constraint on an existing
    table, only a fresh CREATE TABLE can — so uniqueness is a separate index,
    same two-step every other constraint this file has ever added takes.
    SQLite treats every NULL in a UNIQUE index as distinct from every other
    NULL, which is exactly right here: the near-totality of Seekers with no
    username must never collide with each other.
    """
    columns = {row[1] for row in conn.execute("PRAGMA table_info(seekers)").fetchall()}
    if "username" not in columns:
        conn.execute("ALTER TABLE seekers ADD COLUMN username TEXT")
        logger.info("seekers.db phase 3 migration: added seekers.username")
    else:
        logger.debug("seekers.db phase 3 migration: username already present")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_seekers_username ON seekers (username)")


def migrate_to_phase_4(conn: sqlite3.Connection) -> None:
    """
    Add `seekers.is_super_admin` — Ultimate Admin's one privilege beyond
    ordinary Admin Mode.

    Deliberately a SEPARATE bit from `is_admin` (phase 2), not a wider value on
    the same column: every super-admin is also an admin (Ultimate Admin still
    sees the same dashboard the other four do), but the reverse must never be
    true by construction. A single `role` column with an "ultimate" value would
    make that guarantee something every caller has to remember to check
    correctly; two independent booleans make "admin but not super-admin" the
    default shape of the other four rows, not a rule someone has to enforce.

    is_super_admin is what `webapp/backend/job_edit.py` requires: the direct
    read/write path onto a job's own row and its enrichment — the one place
    this backend lets a human overwrite what the pipeline computed, everything
    from the title to the AI's salary estimate. See its module docstring for
    why that write needs its own privilege bit rather than riding on is_admin.
    """
    columns = {row[1] for row in conn.execute("PRAGMA table_info(seekers)").fetchall()}
    if "is_super_admin" not in columns:
        conn.execute("ALTER TABLE seekers ADD COLUMN is_super_admin INTEGER NOT NULL DEFAULT 0")
        logger.info("seekers.db phase 4 migration: added seekers.is_super_admin")
    else:
        logger.debug("seekers.db phase 4 migration: is_super_admin already present")


def migrate_to_phase_5(conn: sqlite3.Connection) -> None:
    """Persist the first-party signals behind explainable Role recommendations.

    `seeker_discovery_events` is the settled intent trail: one search/filter
    state after the results came back, never keystrokes and never anonymous
    browsing. `recommendation_impressions` is the audit/evaluation trail: the
    Role references shown, their scores and human-readable reasons, plus an
    optional click timestamp. Neither table copies a Role from jobs.db.

    Both tables cascade with the Seeker and are also named explicitly in
    `delete_seeker`; recommendations are useful product data, not an exception
    to the account's deletion promise.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS seeker_discovery_events (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            seeker_id     TEXT NOT NULL REFERENCES seekers (id) ON DELETE CASCADE,
            search_query  TEXT NOT NULL,
            filters_json  TEXT NOT NULL,
            result_count  INTEGER NOT NULL,
            created_at    TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS recommendation_impressions (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id      TEXT NOT NULL,
            seeker_id     TEXT NOT NULL REFERENCES seekers (id) ON DELETE CASCADE,
            source        TEXT NOT NULL,
            source_id     TEXT NOT NULL,
            score         REAL NOT NULL,
            reasons_json  TEXT NOT NULL,
            model_version TEXT NOT NULL,
            position      INTEGER NOT NULL,
            created_at    TEXT NOT NULL,
            clicked_at    TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_discovery_seeker_recent "
        "ON seeker_discovery_events (seeker_id, created_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_impressions_seeker_recent "
        "ON recommendation_impressions (seeker_id, created_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_impressions_role "
        "ON recommendation_impressions (seeker_id, source, source_id, id DESC)"
    )


def migrate_to_phase_6(conn: sqlite3.Connection) -> None:
    """Add Seeker-controlled recommendation preferences and feedback.

    Phase 5 records implicit first-party signals. This phase gives the Seeker
    explicit control over those signals: they can ask for similar Roles,
    dismiss a Role, correct an explanation, hide an employer, disable an input,
    or reset the recommendation profile without deleting Saved Roles.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS recommendation_feedback (
            seeker_id   TEXT NOT NULL REFERENCES seekers (id) ON DELETE CASCADE,
            source      TEXT NOT NULL,
            source_id   TEXT NOT NULL,
            action      TEXT NOT NULL CHECK (
                action IN ('more_like', 'not_interested', 'wrong_reason')
            ),
            detail      TEXT,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL,
            PRIMARY KEY (seeker_id, source, source_id, action)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS recommendation_settings (
            seeker_id                TEXT PRIMARY KEY REFERENCES seekers (id) ON DELETE CASCADE,
            personalization_enabled  INTEGER NOT NULL DEFAULT 1,
            use_saved_roles          INTEGER NOT NULL DEFAULT 1,
            use_discovery            INTEGER NOT NULL DEFAULT 1,
            use_clicks               INTEGER NOT NULL DEFAULT 1,
            updated_at               TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS recommendation_hidden_employers (
            seeker_id     TEXT NOT NULL REFERENCES seekers (id) ON DELETE CASCADE,
            employer_key  TEXT NOT NULL,
            employer_name TEXT NOT NULL,
            hidden_at     TEXT NOT NULL,
            PRIMARY KEY (seeker_id, employer_key)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_recommendation_feedback_seeker "
        "ON recommendation_feedback (seeker_id, updated_at DESC)"
    )


def migrate_to_phase_7(conn: sqlite3.Connection) -> None:
    """Store exactly one private resume and its derived evidence per Seeker.

    The Seeker id is the primary key, so replacement is a database invariant,
    not cleanup a route might forget. The source document and every derived
    field cascade with the account and are also named in `delete_seeker`.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS seeker_resumes (
            seeker_id       TEXT PRIMARY KEY REFERENCES seekers (id) ON DELETE CASCADE,
            filename        TEXT NOT NULL,
            media_type      TEXT NOT NULL CHECK (media_type IN (
                'application/pdf',
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            )),
            size_bytes      INTEGER NOT NULL CHECK (size_bytes > 0 AND size_bytes <= 5242880),
            content_sha256  TEXT NOT NULL,
            file_content    BLOB NOT NULL,
            text_content    TEXT NOT NULL,
            analysis_json   TEXT NOT NULL DEFAULT '{}',
            uploaded_at     TEXT NOT NULL
        )
        """
    )


# Every phase, in order. A future phase appends here; it never edits an applied
# phase because seekers.db is irreplaceable first-party account data.
_MIGRATIONS = (
    migrate_to_phase_1,
    migrate_to_phase_2,
    migrate_to_phase_3,
    migrate_to_phase_4,
    migrate_to_phase_5,
    migrate_to_phase_6,
    migrate_to_phase_7,
)


# ── Time helpers ──────────────────────────────────────────────────────────────
#
# One source of "now" for the whole module, so tests can pass an explicit
# timestamp instead of sleeping, and so every stored timestamp is UTC. A naive
# local-time string here would compare wrongly against a UTC one and silently
# expire sessions early or late depending on where the server ran.


def utcnow() -> datetime:
    """Timezone-aware UTC now. The only clock this module reads."""
    return datetime.now(timezone.utc)


def to_iso(moment: datetime) -> str:
    """Serialise to the ISO 8601 UTC text the schema stores."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat()


def from_iso(text: str) -> datetime:
    """Parse a stored timestamp back to an aware UTC datetime."""
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def normalise_email(email: str) -> str:
    """
    Lowercase and strip — the only form an address is ever stored or looked up in.

    Without this, `Alice@Example.com` and `alice@example.com` are two accounts as
    far as the UNIQUE constraint is concerned, which is both a duplicate-account
    bug and an account-takeover shape (register the "other" casing of someone's
    address and receive their password-reset mail).

    Deliberately NOT doing provider-specific canonicalisation (stripping Gmail
    dots or +tags): those rules differ per provider, change without notice, and
    getting one wrong merges two people's accounts — a far worse failure than
    letting one person hold two.
    """
    return email.strip().lower()


def normalise_username(username: str) -> str:
    """Lowercase and strip — same rule as normalise_email(), same reason:
    the UNIQUE index is case-sensitive at the SQLite level, so "Kenson" and
    "kenson" must be stored (and looked up) as one canonical form or the
    constraint stops meaning what it looks like it means."""
    return username.strip().lower()


def new_seeker_id() -> str:
    """A fresh uuid4 string. See the module docstring for why it is not the email."""
    return str(uuid.uuid4())


# ── The store ─────────────────────────────────────────────────────────────────


class SeekerStore:
    """
    A writable connection to seekers.db, safe to share across request threads.

    Connection handling, spelled out because this is the backend's first writer:

      - **One connection per thread**, held in `threading.local()`. uvicorn runs
        sync endpoints on a thread pool, and a sqlite3 connection is not safe to
        share across threads. Per-thread connections mean we never need
        `check_same_thread=False` (main.py needs it only because it hands one
        read-only connection around).

      - **WAL journal mode**, set once and persisted in the file header. Readers
        do not block the writer and the writer does not block readers, which is
        what keeps a slow write on the network-backed Railway volume from
        stalling every in-flight GET.

      - **`isolation_level=None`** — sqlite3's implicit transaction management is
        turned OFF so that transactions are explicit and visible in this file.
        Writes go through `_write()`, which issues `BEGIN IMMEDIATE`: the write
        lock is taken up front rather than half way through, so a write can never
        fail with SQLITE_BUSY after having already read.

      - **A process-wide write lock.** SQLite allows exactly one writer; without
        an in-process lock, concurrent request threads would collide and burn
        the busy timeout retrying. Serialising writes in Python is cheaper and
        makes lock ordering trivially correct. It is NOT a substitute for the
        busy timeout, which still covers other processes (a `railway ssh` shell
        running sqlite3, or a second replica).
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = (
            Path(db_path).expanduser().resolve() if db_path else resolve_seekers_db_path()
        )
        if self.db_path.name == "jobs.db":
            raise ValueError(f"Refusing to use {self.db_path} for Seeker data (ADR 0006)")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._write_lock = threading.Lock()
        self.migrate()

    # -- plumbing ------------------------------------------------------------

    def _conn(self) -> sqlite3.Connection:
        conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(
                self.db_path,
                timeout=_BUSY_TIMEOUT_SECONDS,
                isolation_level=None,  # explicit transactions only — see class docstring
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")       # SQLite: persisted in the file
            conn.execute("PRAGMA synchronous=NORMAL")     # SQLite: the WAL-appropriate setting
            conn.execute("PRAGMA foreign_keys=ON")        # SQLite: OFF by default, per connection
            conn.execute(f"PRAGMA busy_timeout={int(_BUSY_TIMEOUT_SECONDS * 1000)}")
            self._local.conn = conn
        return conn

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        """A serialised, explicitly-begun write transaction. Rolls back on any error."""
        conn = self._conn()
        with self._write_lock:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.rollback()
                raise
            conn.commit()

    def migrate(self) -> None:
        """Run every migration phase in order. Idempotent; called from __init__."""
        with self._write() as conn:
            for migration in _MIGRATIONS:
                migration(conn)

    def close(self) -> None:
        """Close this thread's connection. Mainly for tests and shutdown hooks."""
        conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    # -- seekers -------------------------------------------------------------

    def create_seeker(
        self,
        email: str,
        *,
        password_hash: str | None = None,
        display_name: str | None = None,
        email_verified: bool = False,
        now: datetime | None = None,
    ) -> str:
        """
        Insert a Seeker and return its uuid4 id.

        `password_hash` is already-hashed by auth.hash_password(); a plaintext
        password must never reach this layer. It is None for a Google-only
        Seeker.

        Raises EmailAlreadyRegistered if the address is taken — the UNIQUE
        constraint is the arbiter, not a prior SELECT, so two simultaneous
        registrations for the same address cannot both succeed.
        """
        seeker_id = new_seeker_id()
        created_at = to_iso(now or utcnow())
        try:
            with self._write() as conn:
                conn.execute(
                    """
                    INSERT INTO seekers
                        (id, email, password_hash, display_name, email_verified, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        seeker_id,
                        normalise_email(email),
                        password_hash,
                        display_name,
                        1 if email_verified else 0,
                        created_at,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise EmailAlreadyRegistered(normalise_email(email)) from exc
        return seeker_id

    def get_seeker(self, seeker_id: str) -> dict[str, Any] | None:
        row = self._conn().execute("SELECT * FROM seekers WHERE id = ?", (seeker_id,)).fetchone()
        return dict(row) if row else None

    def get_seeker_by_email(self, email: str) -> dict[str, Any] | None:
        row = (
            self._conn()
            .execute("SELECT * FROM seekers WHERE email = ?", (normalise_email(email),))
            .fetchone()
        )
        return dict(row) if row else None

    def get_seeker_by_username(self, username: str) -> dict[str, Any] | None:
        """
        None for the near-totality of Seekers, who have no username at all —
        see migrate_to_phase_3. `username IS NOT NULL` is not needed in the
        WHERE clause: an empty/None `username` argument would only match a row
        whose username is also NULL by `=` semantics in standard SQL, except
        SQLite's `=` against NULL is never true for ANY value including NULL
        itself, so a blank identifier here simply matches nothing — the caller
        does not need to special-case it.
        """
        row = (
            self._conn()
            .execute(
                "SELECT * FROM seekers WHERE username = ?", (normalise_username(username),)
            )
            .fetchone()
        )
        return dict(row) if row else None

    def set_username(self, seeker_id: str, username: str | None) -> None:
        """
        Set or clear a Seeker's login username. Raises `sqlite3.IntegrityError`
        if another account already holds it — the UNIQUE index is the arbiter,
        same pattern as create_seeker() and the email UNIQUE constraint.
        """
        with self._write() as conn:
            conn.execute(
                "UPDATE seekers SET username = ? WHERE id = ?",
                (normalise_username(username) if username else None, seeker_id),
            )

    def set_password_hash(self, seeker_id: str, password_hash: str | None) -> None:
        """
        Store a new password hash (or None to clear it).

        The caller is responsible for revoking sessions afterwards on a reset —
        that is a policy decision (auth.revoke_all_sessions), not a storage one.
        """
        with self._write() as conn:
            conn.execute(
                "UPDATE seekers SET password_hash = ? WHERE id = ?", (password_hash, seeker_id)
            )

    def set_email_verified(self, seeker_id: str, verified: bool = True) -> None:
        with self._write() as conn:
            conn.execute(
                "UPDATE seekers SET email_verified = ? WHERE id = ?",
                (1 if verified else 0, seeker_id),
            )

    def set_admin(self, seeker_id: str, is_admin: bool = True) -> None:
        """
        Grant or revoke Admin Mode for a Seeker. Ordinary ops, not a self-serve
        endpoint — the only caller today is scripts/create_admin.py, run by hand.
        """
        with self._write() as conn:
            conn.execute(
                "UPDATE seekers SET is_admin = ? WHERE id = ?",
                (1 if is_admin else 0, seeker_id),
            )

    def set_super_admin(self, seeker_id: str, is_super_admin: bool = True) -> None:
        """
        Grant or revoke Ultimate Admin's direct-edit privilege. Same caller and
        the same "by hand, not self-serve" rule as set_admin() — see phase 4's
        docstring for why this is its own bit rather than a wider is_admin.
        """
        with self._write() as conn:
            conn.execute(
                "UPDATE seekers SET is_super_admin = ? WHERE id = ?",
                (1 if is_super_admin else 0, seeker_id),
            )

    def touch_last_login(self, seeker_id: str, *, now: datetime | None = None) -> None:
        with self._write() as conn:
            conn.execute(
                "UPDATE seekers SET last_login_at = ? WHERE id = ?",
                (to_iso(now or utcnow()), seeker_id),
            )

    # -- provider identities -------------------------------------------------

    def get_identity(self, provider: str, provider_sub: str) -> dict[str, Any] | None:
        row = (
            self._conn()
            .execute(
                "SELECT * FROM seeker_identities WHERE provider = ? AND provider_sub = ?",
                (provider, provider_sub),
            )
            .fetchone()
        )
        return dict(row) if row else None

    def link_identity(
        self,
        seeker_id: str,
        provider: str,
        provider_sub: str,
        *,
        now: datetime | None = None,
    ) -> None:
        """
        Attach a provider identity to a Seeker.

        This is the raw storage operation and applies no policy. The rule that a
        provider identity may only be attached to an EXISTING Seeker when the
        provider asserts the email is verified lives in
        auth.link_or_create_seeker(), which is what route handlers must call.
        """
        with self._write() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO seeker_identities
                    (seeker_id, provider, provider_sub, linked_at)
                VALUES (?, ?, ?, ?)
                """,
                (seeker_id, provider, provider_sub, to_iso(now or utcnow())),
            )

    def list_identities(self, seeker_id: str) -> list[dict[str, Any]]:
        rows = self._conn().execute(
            "SELECT * FROM seeker_identities WHERE seeker_id = ? ORDER BY linked_at",
            (seeker_id,),
        )
        return [dict(row) for row in rows]

    # -- sessions ------------------------------------------------------------

    def insert_session(
        self,
        token_hash: str,
        seeker_id: str,
        expires_at: datetime,
        *,
        user_agent: str | None = None,
        now: datetime | None = None,
    ) -> None:
        """Store a session by its HASH. The raw token never reaches this layer."""
        with self._write() as conn:
            conn.execute(
                """
                INSERT INTO sessions (token_hash, seeker_id, created_at, expires_at, user_agent)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    token_hash,
                    seeker_id,
                    to_iso(now or utcnow()),
                    to_iso(expires_at),
                    (user_agent or "")[:256] or None,
                ),
            )

    def get_session(self, token_hash: str) -> dict[str, Any] | None:
        row = (
            self._conn()
            .execute("SELECT * FROM sessions WHERE token_hash = ?", (token_hash,))
            .fetchone()
        )
        return dict(row) if row else None

    def extend_session(self, token_hash: str, expires_at: datetime) -> None:
        """Push a session's expiry forward — the write half of the rolling window."""
        with self._write() as conn:
            conn.execute(
                "UPDATE sessions SET expires_at = ? WHERE token_hash = ?",
                (to_iso(expires_at), token_hash),
            )

    def delete_session(self, token_hash: str) -> bool:
        """Revoke one session (logout). Returns whether a row was actually removed."""
        with self._write() as conn:
            cursor = conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
            return cursor.rowcount > 0

    def delete_sessions_for_seeker(self, seeker_id: str) -> int:
        """Revoke every session for a Seeker — password change, reset, deletion."""
        with self._write() as conn:
            cursor = conn.execute("DELETE FROM sessions WHERE seeker_id = ?", (seeker_id,))
            return cursor.rowcount

    def count_sessions(self, seeker_id: str) -> int:
        row = self._conn().execute(
            "SELECT COUNT(*) FROM sessions WHERE seeker_id = ?", (seeker_id,)
        ).fetchone()
        return int(row[0])

    def purge_expired_sessions(self, *, now: datetime | None = None) -> int:
        """
        Drop sessions past their expiry.

        Expired sessions are already rejected on read (auth.verify_session checks
        the timestamp), so this is housekeeping, not a security control — it
        stops the table growing without bound. Safe to call on startup or from a
        periodic task.
        """
        with self._write() as conn:
            cursor = conn.execute(
                "DELETE FROM sessions WHERE expires_at <= ?", (to_iso(now or utcnow()),)
            )
            return cursor.rowcount

    # -- single-use email tokens --------------------------------------------

    def insert_email_token(
        self,
        token_hash: str,
        seeker_id: str,
        purpose: str,
        expires_at: datetime,
        *,
        now: datetime | None = None,
    ) -> None:
        if purpose not in VALID_TOKEN_PURPOSES:
            raise ValueError(f"unknown token purpose {purpose!r}")
        with self._write() as conn:
            conn.execute(
                """
                INSERT INTO email_tokens
                    (token_hash, seeker_id, purpose, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (token_hash, seeker_id, purpose, to_iso(now or utcnow()), to_iso(expires_at)),
            )

    def get_email_token(self, token_hash: str) -> dict[str, Any] | None:
        row = (
            self._conn()
            .execute("SELECT * FROM email_tokens WHERE token_hash = ?", (token_hash,))
            .fetchone()
        )
        return dict(row) if row else None

    def claim_email_token(self, token_hash: str, *, now: datetime | None = None) -> bool:
        """
        Atomically mark a token spent. True only for the caller that won it.

        Single-use has to be enforced HERE rather than by a read-then-write in
        auth.py: two clicks on the same reset link land on two request threads,
        both read `used_at IS NULL`, and both proceed. The conditional UPDATE
        makes SQLite the arbiter — exactly one of them gets rowcount 1.
        """
        with self._write() as conn:
            cursor = conn.execute(
                "UPDATE email_tokens SET used_at = ? WHERE token_hash = ? AND used_at IS NULL",
                (to_iso(now or utcnow()), token_hash),
            )
            return cursor.rowcount == 1

    def delete_email_tokens(self, seeker_id: str, purpose: str | None = None) -> int:
        """
        Drop a Seeker's outstanding tokens.

        Used when issuing a fresh one (so an old reset link stops working the
        moment a new one is requested) and on deletion.
        """
        with self._write() as conn:
            if purpose is None:
                cursor = conn.execute(
                    "DELETE FROM email_tokens WHERE seeker_id = ?", (seeker_id,)
                )
            else:
                cursor = conn.execute(
                    "DELETE FROM email_tokens WHERE seeker_id = ? AND purpose = ?",
                    (seeker_id, purpose),
                )
            return cursor.rowcount

    # -- saved roles ---------------------------------------------------------

    def save_role(
        self, seeker_id: str, source: str, source_id: str, *, now: datetime | None = None
    ) -> None:
        """
        Record that a Seeker saved a Role. Idempotent — saving twice is one row.

        Only the (source, source_id) REFERENCE is stored. Nothing about the Role
        itself is copied here; the job fields are joined from jobs.db at read
        time (phase 5, via ATTACH), which is what keeps a Saved Role honest when
        the Role closes.
        """
        with self._write() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO saved_roles (seeker_id, source, source_id, saved_at)
                VALUES (?, ?, ?, ?)
                """,
                (seeker_id, source, source_id, to_iso(now or utcnow())),
            )

    def unsave_role(self, seeker_id: str, source: str, source_id: str) -> bool:
        with self._write() as conn:
            cursor = conn.execute(
                "DELETE FROM saved_roles WHERE seeker_id = ? AND source = ? AND source_id = ?",
                (seeker_id, source, source_id),
            )
            return cursor.rowcount > 0

    def list_saved_roles(self, seeker_id: str) -> list[dict[str, Any]]:
        """
        The Seeker's saved (source, source_id) references, newest first.

        Deliberately returns references only. The ATTACH join that turns these
        into displayable Roles is phase 5 and belongs next to the job queries in
        main.py, not here — this file must not know jobs.db's schema.
        """
        rows = self._conn().execute(
            "SELECT * FROM saved_roles WHERE seeker_id = ? "
            "ORDER BY saved_at DESC, source, source_id",
            (seeker_id,),
        )
        return [dict(row) for row in rows]

    def merge_saved_roles(
        self,
        seeker_id: str,
        references: Iterable[tuple[str, str]],
        *,
        now: datetime | None = None,
    ) -> int:
        """
        Union-merge a batch of (source, source_id) references into the account.

        This is the storage half of decision 14 — first sign-in lifts the
        browser's localStorage saves into the account. A union, never a replace:
        a Seeker who saved on two devices keeps both sets. Idempotent by
        construction (INSERT OR IGNORE on the primary key), so re-running it is
        harmless. Returns the number of references that were genuinely new.
        """
        saved_at = to_iso(now or utcnow())
        with self._write() as conn:
            before = conn.execute(
                "SELECT COUNT(*) FROM saved_roles WHERE seeker_id = ?", (seeker_id,)
            ).fetchone()[0]
            conn.executemany(
                """
                INSERT OR IGNORE INTO saved_roles (seeker_id, source, source_id, saved_at)
                VALUES (?, ?, ?, ?)
                """,
                [(seeker_id, source, source_id, saved_at) for source, source_id in references],
            )
            after = conn.execute(
                "SELECT COUNT(*) FROM saved_roles WHERE seeker_id = ?", (seeker_id,)
            ).fetchone()[0]
        return int(after - before)

    # -- recommendation signals --------------------------------------------

    def record_discovery(
        self,
        seeker_id: str,
        *,
        search_query: str,
        filters: dict[str, Any],
        result_count: int,
        now: datetime | None = None,
    ) -> bool:
        """Store one settled search/filter state; return whether it was new.

        A browser refresh repeats the same `/api/jobs` read. Treating that as a
        second preference signal makes refresh-heavy users look artificially
        certain, so an exact repeat inside five minutes is suppressed. A real
        change of query or filter remains a separate event immediately.
        """
        moment = now or utcnow()
        query = " ".join(search_query.strip().lower().split())[:200]
        filters_json = json.dumps(
            filters, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        if len(filters_json) > 4_000:
            raise ValueError("Discovery filters are too large")

        with self._write() as conn:
            latest = conn.execute(
                """
                SELECT search_query, filters_json, created_at
                FROM seeker_discovery_events
                WHERE seeker_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (seeker_id,),
            ).fetchone()
            if (
                latest
                and latest["search_query"] == query
                and latest["filters_json"] == filters_json
                and from_iso(latest["created_at"]) >= moment - timedelta(minutes=5)
            ):
                return False

            conn.execute(
                """
                INSERT INTO seeker_discovery_events
                    (seeker_id, search_query, filters_json, result_count, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (seeker_id, query, filters_json, max(0, int(result_count)), to_iso(moment)),
            )
        return True

    def list_discovery_events(self, seeker_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._conn().execute(
            """
            SELECT * FROM seeker_discovery_events
            WHERE seeker_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (seeker_id, max(1, min(int(limit), 500))),
        )
        return [dict(row) for row in rows]

    def record_recommendation_impressions(
        self,
        seeker_id: str,
        items: Iterable[dict[str, Any]],
        *,
        model_version: str,
        now: datetime | None = None,
    ) -> str:
        """Append one recommendation batch and return its opaque batch id."""
        batch_id = str(uuid.uuid4())
        created_at = to_iso(now or utcnow())
        rows = []
        for item in items:
            reasons_json = json.dumps(
                list(item.get("reasons") or []),
                ensure_ascii=False,
                separators=(",", ":"),
            )
            rows.append(
                (
                    batch_id,
                    seeker_id,
                    str(item["source"]),
                    str(item["source_id"]),
                    float(item["score"]),
                    reasons_json,
                    model_version,
                    int(item["position"]),
                    created_at,
                )
            )
        if len(rows) > 100:
            raise ValueError("A recommendation batch cannot exceed 100 Roles")
        if rows:
            with self._write() as conn:
                conn.executemany(
                    """
                    INSERT INTO recommendation_impressions
                        (batch_id, seeker_id, source, source_id, score, reasons_json,
                         model_version, position, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
        return batch_id

    def list_recommendation_impressions(
        self, seeker_id: str, *, limit: int = 100
    ) -> list[dict[str, Any]]:
        rows = self._conn().execute(
            """
            SELECT * FROM recommendation_impressions
            WHERE seeker_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (seeker_id, max(1, min(int(limit), 500))),
        )
        return [dict(row) for row in rows]

    def mark_recommendation_clicked(
        self,
        seeker_id: str,
        source: str,
        source_id: str,
        *,
        now: datetime | None = None,
    ) -> bool:
        """Mark the newest matching impression clicked, idempotently."""
        with self._write() as conn:
            cursor = conn.execute(
                """
                UPDATE recommendation_impressions
                SET clicked_at = COALESCE(clicked_at, ?)
                WHERE id = (
                    SELECT id FROM recommendation_impressions
                    WHERE seeker_id = ? AND source = ? AND source_id = ?
                    ORDER BY id DESC
                    LIMIT 1
                )
                """,
                (to_iso(now or utcnow()), seeker_id, source, source_id),
            )
            return cursor.rowcount == 1

    def list_clicked_recommendation_refs(
        self, seeker_id: str, *, limit: int = 100
    ) -> list[dict[str, str]]:
        """Return recently opened Role references, newest first and deduplicated."""
        rows = self._conn().execute(
            """
            SELECT source, source_id, MAX(clicked_at) AS latest_click
            FROM recommendation_impressions
            WHERE seeker_id = ? AND clicked_at IS NOT NULL
            GROUP BY source, source_id
            ORDER BY latest_click DESC
            LIMIT ?
            """,
            (seeker_id, max(1, min(int(limit), 500))),
        )
        return [
            {"source": str(row["source"]), "source_id": str(row["source_id"])}
            for row in rows
        ]

    def get_recommendation_settings(self, seeker_id: str) -> dict[str, bool]:
        """Return the Seeker's controls, or privacy-friendly product defaults."""
        row = self._conn().execute(
            """
            SELECT personalization_enabled, use_saved_roles, use_discovery, use_clicks
            FROM recommendation_settings
            WHERE seeker_id = ?
            """,
            (seeker_id,),
        ).fetchone()
        if row is None:
            return {
                "personalization_enabled": True,
                "use_saved_roles": True,
                "use_discovery": True,
                "use_clicks": True,
            }
        return {key: bool(row[key]) for key in row.keys()}

    def update_recommendation_settings(
        self,
        seeker_id: str,
        *,
        personalization_enabled: bool | None = None,
        use_saved_roles: bool | None = None,
        use_discovery: bool | None = None,
        use_clicks: bool | None = None,
        now: datetime | None = None,
    ) -> dict[str, bool]:
        """Partially update recommendation controls and return the resolved state."""
        updates = {
            "personalization_enabled": personalization_enabled,
            "use_saved_roles": use_saved_roles,
            "use_discovery": use_discovery,
            "use_clicks": use_clicks,
        }
        stamp = to_iso(now or utcnow())
        with self._write() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO recommendation_settings
                    (seeker_id, personalization_enabled, use_saved_roles,
                     use_discovery, use_clicks, updated_at)
                VALUES (?, 1, 1, 1, 1, ?)
                """,
                (seeker_id, stamp),
            )
            changed = [(key, value) for key, value in updates.items() if value is not None]
            if changed:
                assignments = ", ".join(f"{key} = ?" for key, _ in changed)
                conn.execute(
                    f"UPDATE recommendation_settings SET {assignments}, updated_at = ? "
                    "WHERE seeker_id = ?",
                    [*(int(bool(value)) for _, value in changed), stamp, seeker_id],
                )
        return self.get_recommendation_settings(seeker_id)

    def record_recommendation_feedback(
        self,
        seeker_id: str,
        source: str,
        source_id: str,
        *,
        action: str,
        detail: str | None = None,
        now: datetime | None = None,
    ) -> None:
        """Upsert one explicit label; positive and negative intent replace each other."""
        if action not in RECOMMENDATION_FEEDBACK_ACTIONS:
            raise ValueError(f"unknown recommendation feedback action {action!r}")
        clean_detail = " ".join((detail or "").split())[:300] or None
        stamp = to_iso(now or utcnow())
        with self._write() as conn:
            if action in {"more_like", "not_interested"}:
                opposite = "not_interested" if action == "more_like" else "more_like"
                conn.execute(
                    """
                    DELETE FROM recommendation_feedback
                    WHERE seeker_id = ? AND source = ? AND source_id = ? AND action = ?
                    """,
                    (seeker_id, source, source_id, opposite),
                )
            conn.execute(
                """
                INSERT INTO recommendation_feedback
                    (seeker_id, source, source_id, action, detail, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (seeker_id, source, source_id, action) DO UPDATE SET
                    detail = excluded.detail,
                    updated_at = excluded.updated_at
                """,
                (seeker_id, source, source_id, action, clean_detail, stamp, stamp),
            )

    def delete_recommendation_feedback(
        self, seeker_id: str, source: str, source_id: str, action: str
    ) -> bool:
        if action not in RECOMMENDATION_FEEDBACK_ACTIONS:
            raise ValueError(f"unknown recommendation feedback action {action!r}")
        with self._write() as conn:
            cursor = conn.execute(
                """
                DELETE FROM recommendation_feedback
                WHERE seeker_id = ? AND source = ? AND source_id = ? AND action = ?
                """,
                (seeker_id, source, source_id, action),
            )
            return cursor.rowcount > 0

    def list_recommendation_feedback(
        self, seeker_id: str, *, limit: int = 500
    ) -> list[dict[str, Any]]:
        rows = self._conn().execute(
            """
            SELECT seeker_id, source, source_id, action, detail, created_at, updated_at
            FROM recommendation_feedback
            WHERE seeker_id = ?
            ORDER BY updated_at DESC, source, source_id, action
            LIMIT ?
            """,
            (seeker_id, max(1, min(int(limit), 2_000))),
        )
        return [dict(row) for row in rows]

    def hide_recommendation_employer(
        self,
        seeker_id: str,
        employer_key: str,
        employer_name: str,
        *,
        now: datetime | None = None,
    ) -> None:
        key = " ".join(employer_key.strip().lower().split())[:200]
        name = " ".join(employer_name.strip().split())[:200]
        if not key or not name:
            raise ValueError("Employer key and name are required")
        with self._write() as conn:
            conn.execute(
                """
                INSERT INTO recommendation_hidden_employers
                    (seeker_id, employer_key, employer_name, hidden_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (seeker_id, employer_key) DO UPDATE SET
                    employer_name = excluded.employer_name,
                    hidden_at = excluded.hidden_at
                """,
                (seeker_id, key, name, to_iso(now or utcnow())),
            )

    def unhide_recommendation_employer(self, seeker_id: str, employer_key: str) -> bool:
        with self._write() as conn:
            cursor = conn.execute(
                """
                DELETE FROM recommendation_hidden_employers
                WHERE seeker_id = ? AND employer_key = ?
                """,
                (seeker_id, employer_key),
            )
            return cursor.rowcount > 0

    def list_hidden_recommendation_employers(
        self, seeker_id: str
    ) -> list[dict[str, str]]:
        rows = self._conn().execute(
            """
            SELECT employer_key, employer_name
            FROM recommendation_hidden_employers
            WHERE seeker_id = ?
            ORDER BY employer_name COLLATE NOCASE, employer_key
            """,
            (seeker_id,),
        )
        return [dict(row) for row in rows]

    def recommendation_profile_counts(self, seeker_id: str) -> dict[str, int]:
        conn = self._conn()
        recent_searches = int(
            conn.execute(
                "SELECT COUNT(*) FROM seeker_discovery_events WHERE seeker_id = ?",
                (seeker_id,),
            ).fetchone()[0]
        )
        opened_roles = int(
            conn.execute(
                """
                SELECT COUNT(*) FROM (
                    SELECT source, source_id FROM recommendation_impressions
                    WHERE seeker_id = ? AND clicked_at IS NOT NULL
                    GROUP BY source, source_id
                )
                """,
                (seeker_id,),
            ).fetchone()[0]
        )
        feedback_counts = {action: 0 for action in RECOMMENDATION_FEEDBACK_ACTIONS}
        rows = conn.execute(
            """
            SELECT action, COUNT(*) AS count
            FROM recommendation_feedback
            WHERE seeker_id = ?
            GROUP BY action
            """,
            (seeker_id,),
        )
        for row in rows:
            feedback_counts[str(row["action"])] = int(row["count"])
        return {
            "recent_searches": recent_searches,
            "opened_roles": opened_roles,
            **feedback_counts,
        }

    def reset_recommendation_profile(self, seeker_id: str) -> None:
        """Delete learned recommendation data while preserving account and Saved Roles."""
        with self._write() as conn:
            conn.execute(
                "DELETE FROM recommendation_settings WHERE seeker_id = ?", (seeker_id,)
            )
            conn.execute(
                "DELETE FROM recommendation_feedback WHERE seeker_id = ?", (seeker_id,)
            )
            conn.execute(
                "DELETE FROM recommendation_hidden_employers WHERE seeker_id = ?",
                (seeker_id,),
            )
            conn.execute(
                "DELETE FROM recommendation_impressions WHERE seeker_id = ?", (seeker_id,)
            )
            conn.execute(
                "DELETE FROM seeker_discovery_events WHERE seeker_id = ?", (seeker_id,)
            )

    # -- private resume -----------------------------------------------------

    def replace_resume(
        self,
        seeker_id: str,
        *,
        filename: str,
        media_type: str,
        size_bytes: int,
        content_sha256: str,
        file_content: bytes,
        text_content: str,
        analysis: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> bool:
        """Atomically store one resume; return True when an older one was replaced."""
        if not 0 < size_bytes <= 5 * 1024 * 1024 or len(file_content) != size_bytes:
            raise ValueError("Resume content size is invalid")
        analysis_json = json.dumps(
            analysis or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        uploaded_at = to_iso(now or utcnow())
        with self._write() as conn:
            existed = conn.execute(
                "SELECT 1 FROM seeker_resumes WHERE seeker_id = ?", (seeker_id,)
            ).fetchone() is not None
            conn.execute(
                """
                INSERT INTO seeker_resumes
                    (seeker_id, filename, media_type, size_bytes, content_sha256,
                     file_content, text_content, analysis_json, uploaded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(seeker_id) DO UPDATE SET
                    filename = excluded.filename,
                    media_type = excluded.media_type,
                    size_bytes = excluded.size_bytes,
                    content_sha256 = excluded.content_sha256,
                    file_content = excluded.file_content,
                    text_content = excluded.text_content,
                    analysis_json = excluded.analysis_json,
                    uploaded_at = excluded.uploaded_at
                """,
                (
                    seeker_id,
                    filename,
                    media_type,
                    size_bytes,
                    content_sha256,
                    file_content,
                    text_content,
                    analysis_json,
                    uploaded_at,
                ),
            )
        return existed

    def get_resume(
        self, seeker_id: str, *, include_document: bool = False
    ) -> dict[str, Any] | None:
        columns = "*" if include_document else (
            "seeker_id, filename, media_type, size_bytes, content_sha256, "
            "analysis_json, uploaded_at"
        )
        row = self._conn().execute(
            f"SELECT {columns} FROM seeker_resumes WHERE seeker_id = ?",
            (seeker_id,),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        try:
            result["analysis"] = json.loads(result.pop("analysis_json"))
        except (TypeError, ValueError):
            result.pop("analysis_json", None)
            result["analysis"] = {}
        return result

    def delete_resume(self, seeker_id: str) -> bool:
        with self._write() as conn:
            cursor = conn.execute(
                "DELETE FROM seeker_resumes WHERE seeker_id = ?", (seeker_id,)
            )
        return cursor.rowcount == 1

    # -- events (first-party analytics, decision 19) -------------------------

    def log_event(
        self, name: str, seeker_id: str | None = None, *, now: datetime | None = None
    ) -> None:
        """
        Record one server-side event: a name, an optional Seeker, a timestamp.

        Deliberately that and nothing else. No IP, no user-agent, no cookie, no
        third-party script — which is what keeps PrivacyNotice.tsx's "no
        third-party trackers" claim literally true. If a future question needs a
        property, add a named event rather than a properties blob; a blob is how
        analytics tables quietly become personal-data stores.
        """
        with self._write() as conn:
            conn.execute(
                "INSERT INTO events (name, seeker_id, created_at) VALUES (?, ?, ?)",
                (name, seeker_id, to_iso(now or utcnow())),
            )

    def count_events(self, name: str | None = None, *, seeker_id: str | None = None) -> int:
        sql = "SELECT COUNT(*) FROM events WHERE 1=1"
        params: list[Any] = []
        if name is not None:
            sql += " AND name = ?"
            params.append(name)
        if seeker_id is not None:
            sql += " AND seeker_id = ?"
            params.append(seeker_id)
        return int(self._conn().execute(sql, params).fetchone()[0])

    def list_events(self, seeker_id: str) -> list[dict[str, Any]]:
        rows = self._conn().execute(
            "SELECT * FROM events WHERE seeker_id = ? ORDER BY id", (seeker_id,)
        )
        return [dict(row) for row in rows]

    # -- deletion ------------------------------------------------------------

    def delete_seeker(self, seeker_id: str, *, now: datetime | None = None) -> bool:
        """
        Really delete a Seeker: rows gone, every session revoked. Returns whether
        the Seeker existed.

        This is the explicit carve-out from CLAUDE.md's soft-delete rule (ADR
        0007). That rule protects a Seeker's view of Roles that have closed; it
        has nothing to say about the Seeker's own account. Flipping a flag and
        telling someone their data is gone turns an ordinary privacy question
        into a serious complaint.

        One row survives, on purpose: an `events` entry named 'seeker.deleted'
        carrying the (now pseudonymous) uuid and the timestamp. ADR 0007 requires
        it so that a deletion can be honoured retroactively by the
        CV/personalisation component once that contract exists — you cannot
        forward a deletion you have no record of.

        The child deletes are written out explicitly rather than left to
        ON DELETE CASCADE. The cascade is real (foreign_keys=ON is set on every
        connection) and would do the same job, but a deletion promise this
        load-bearing should not depend on a per-connection pragma that a future
        refactor could drop without any test failing.
        """
        with self._write() as conn:
            exists = conn.execute("SELECT 1 FROM seekers WHERE id = ?", (seeker_id,)).fetchone()
            if exists is None:
                return False
            conn.execute("DELETE FROM sessions WHERE seeker_id = ?", (seeker_id,))
            conn.execute("DELETE FROM email_tokens WHERE seeker_id = ?", (seeker_id,))
            conn.execute("DELETE FROM saved_roles WHERE seeker_id = ?", (seeker_id,))
            conn.execute(
                "DELETE FROM seeker_discovery_events WHERE seeker_id = ?", (seeker_id,)
            )
            conn.execute(
                "DELETE FROM recommendation_impressions WHERE seeker_id = ?", (seeker_id,)
            )
            conn.execute(
                "DELETE FROM recommendation_feedback WHERE seeker_id = ?", (seeker_id,)
            )
            conn.execute(
                "DELETE FROM recommendation_hidden_employers WHERE seeker_id = ?",
                (seeker_id,),
            )
            conn.execute(
                "DELETE FROM recommendation_settings WHERE seeker_id = ?", (seeker_id,)
            )
            conn.execute("DELETE FROM seeker_resumes WHERE seeker_id = ?", (seeker_id,))
            conn.execute("DELETE FROM seeker_identities WHERE seeker_id = ?", (seeker_id,))
            conn.execute("DELETE FROM seekers WHERE id = ?", (seeker_id,))
            conn.execute(
                "INSERT INTO events (name, seeker_id, created_at) VALUES (?, ?, ?)",
                ("seeker.deleted", seeker_id, to_iso(now or utcnow())),
            )
        logger.info("Deleted seeker %s (rows removed, sessions revoked, event logged)", seeker_id)
        return True


# ── Process-wide instance ─────────────────────────────────────────────────────
#
# main.py wants one store for the app's lifetime; tests want a throwaway one per
# tmp_path. get_store() serves the first case, the constructor serves the second.

_store: SeekerStore | None = None
_store_lock = threading.Lock()


def get_store() -> SeekerStore:
    """The process-wide SeekerStore, created (and migrated) on first use."""
    global _store
    with _store_lock:
        if _store is None:
            _store = SeekerStore()
            logger.info("Seeker store ready at %s", _store.db_path)
        return _store


def reset_store() -> None:
    """Drop the cached store. For tests and for a config reload; not for request code."""
    global _store
    with _store_lock:
        if _store is not None:
            _store.close()
        _store = None
