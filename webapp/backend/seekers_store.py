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
from collections import Counter
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# How long a query waits for a writer to finish before giving up with
# "database is locked". The Railway volume is network-backed, so a write can be
# slower than on local disk; five seconds is generous for a single-writer app
# with a handful of Seekers and still fails fast enough to surface a real
# deadlock rather than hanging a request forever.
_BUSY_TIMEOUT_SECONDS = 5.0

VALID_TOKEN_PURPOSES = ("verify", "reset")
RECOMMENDATION_FEEDBACK_ACTIONS = ("more_like", "not_interested", "wrong_reason")
#: Admin-facing day buckets read in the timezone the admin desk itself uses
#: (see admin_intelligence._hong_kong_today) so "today" agrees across sections.
_HONG_KONG = ZoneInfo("Asia/Hong_Kong")


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


def migrate_to_phase_8(conn: sqlite3.Connection) -> None:
    """Count anonymous board traffic without identifying anyone.

    `visitor_hash` is SHA-256 of an opaque cookie value (auth.hash_token — same
    treatment as a session token), never the raw cookie and never an IP or user
    agent. One row per visitor per Hong-Kong calendar day: the UNIQUE constraint
    IS the "did we already count this visitor today" check, so recording a visit
    twice in one day is a no-op, not a double-count. There is deliberately no
    link to a seeker_id — a signed-in Seeker's activity is already counted by
    `sessions`, and this table's whole purpose is to cover everyone who is NOT
    in that table.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS anonymous_visits (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            visitor_hash  TEXT NOT NULL,
            visit_date    TEXT NOT NULL,
            created_at    TEXT NOT NULL,
            UNIQUE (visitor_hash, visit_date)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_anonymous_visits_date "
        "ON anonymous_visits (visit_date)"
    )


def migrate_to_phase_9(conn: sqlite3.Connection) -> None:
    """Add Alerts: an opt-in weekly email of newly-recommended Roles.

    `alert_settings` holds one row per Seeker who has ever touched the toggle.
    `opted_in` gates whether the weekly job considers them at all — default OFF,
    since Alerts is opt-in only, never on by default (it reads as direct
    marketing under PDPO Part 6A, and PrivacyNotice.tsx clause 5 already
    promises nobody is added to a mailing list without being asked first).
    `last_sent_at` is what the weekly job compares against to run a rolling
    per-Seeker cadence (at least 7 days since last send) rather than a fixed
    calendar day for everyone.

    `alerted_roles` is the permanent per-Seeker "already sent" list — same
    shape as `saved_roles` (a bare (source, source_id) reference, never a copy
    of the Role, joined against jobs.db at read time) so a Role stays correctly
    represented even after it closes. A Role is eligible for at most one Alert
    email per Seeker, ever; this table is what makes that a database invariant
    instead of something the weekly job has to remember on its own.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS alert_settings (
            seeker_id     TEXT PRIMARY KEY REFERENCES seekers (id) ON DELETE CASCADE,
            opted_in      INTEGER NOT NULL DEFAULT 0,
            last_sent_at  TEXT,
            updated_at    TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS alerted_roles (
            seeker_id  TEXT NOT NULL REFERENCES seekers (id) ON DELETE CASCADE,
            source     TEXT NOT NULL,
            source_id  TEXT NOT NULL,
            sent_at    TEXT NOT NULL,
            PRIMARY KEY (seeker_id, source, source_id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_alerted_roles_seeker ON alerted_roles (seeker_id)"
    )


def migrate_to_phase_10(conn: sqlite3.Connection) -> None:
    """Record every time an Ultimate Admin downloads a Seeker's resume file.

    The resume is the most sensitive thing this database holds, and until now
    the only way to read the bytes was `railway ssh` into the volume — access
    that leaves no trace anywhere. Putting the download behind an admin route
    is a net privacy improvement only if the route is *more* accountable than
    the shell was, so the log is written in the same request that serves the
    file and a failure to write it fails the download.

    Deliberately NOT `ON DELETE CASCADE` on seeker_id, unlike every other table
    here: this is the one row that must outlive the account. A Seeker deleting
    themselves (docs/adr/0007) must not also erase the record of who looked at
    their resume — that would let an admin delete the evidence by deleting the
    subject. seeker_id is kept as a plain TEXT column, not a foreign key, so
    the row survives; `seeker_email` is denormalised for the same reason, since
    after deletion there is nothing left to join against.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS seeker_resume_downloads (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            seeker_id      TEXT NOT NULL,
            seeker_email   TEXT NOT NULL,
            admin_id       TEXT NOT NULL,
            admin_email    TEXT NOT NULL,
            filename       TEXT NOT NULL,
            size_bytes     INTEGER NOT NULL,
            reason         TEXT,
            downloaded_at  TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_resume_downloads_seeker "
        "ON seeker_resume_downloads (seeker_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_resume_downloads_at "
        "ON seeker_resume_downloads (downloaded_at DESC)"
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
    migrate_to_phase_8,
    migrate_to_phase_9,
    migrate_to_phase_10,
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


def _bucket_returning(
    active_days_by_id: dict[str, set[date]],
) -> tuple[dict[date, int], dict[date, int], set[str]]:
    """Shared by Seeker and anonymous-visitor activity: given each id's set of
    active days within an observed window, return (count active per day, count
    returning per day, ids that returned at least once). An id is "returning"
    on any active day that is not its earliest active day in the window."""
    by_day: dict[date, int] = {}
    returning_by_day: dict[date, int] = {}
    returning_ids: set[str] = set()
    for key, active_days in active_days_by_id.items():
        ordered = sorted(active_days)
        first_active_day = ordered[0]
        for d in ordered:
            by_day[d] = by_day.get(d, 0) + 1
            if d != first_active_day:
                returning_by_day[d] = returning_by_day.get(d, 0) + 1
                returning_ids.add(key)
    return by_day, returning_by_day, returning_ids


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

    def list_accounts(self, *, limit: int = 500) -> list[dict[str, Any]]:
        """Every Seeker account, newest-first, for the Ultimate Admin directory.

        `password_hash` is never selected — there is no admin use case for it,
        hashed or not, and leaving it out of the query is a stronger guarantee
        than trusting every caller to strip it from the row after the fact.

        `has_resume` is a LEFT JOIN, not a per-row lookup: the directory needs
        it for every row at once to decide which rows offer a download, and one
        join stays a single query. That is a different shape from
        `interests_for_seeker`, which is lazy precisely because it would
        otherwise fan out into several reads per Seeker.
        """
        rows = self._conn().execute(
            """
            SELECT s.id, s.email, s.display_name, s.username, s.email_verified,
                   s.is_admin, s.is_super_admin, s.created_at, s.last_login_at,
                   (r.seeker_id IS NOT NULL) AS has_resume
            FROM seekers s
            LEFT JOIN seeker_resumes r ON r.seeker_id = s.id
            ORDER BY s.created_at DESC LIMIT ?
            """,
            (max(1, min(int(limit), 2000)),),
        )
        # SQLite has no boolean type — these come back 0/1. A raw dict(row)
        # would hand the API layer an int where the wire contract promises a
        # bool; coerce here rather than trusting every caller to remember.
        return [
            {
                **dict(row),
                "email_verified": bool(row["email_verified"]),
                "is_admin": bool(row["is_admin"]),
                "is_super_admin": bool(row["is_super_admin"]),
                "has_resume": bool(row["has_resume"]),
            }
            for row in rows
        ]

    def interests_for_seeker(self, seeker_id: str) -> dict[str, Any]:
        """What this Seeker appears interested in, from first-party signals
        already on file — never a guess, only what they actually did.

        Three sources, each cheap because it is scoped to one seeker_id
        rather than joined across the whole table (see list_accounts, which
        deliberately stays a flat query for exactly that reason): the resume
        analysis (skills/sectors/role families extracted by
        resume_intelligence.analyse_resume), the sectors/skills/seniority
        they have actually searched for (seeker_discovery_events.filters_json
        — see main.py's DiscoveryFiltersIn), and how many Roles they have
        saved. Deliberately does NOT resolve saved Roles against jobs.db:
        ADR 0006 forbids attaching Seeker-owned state to the catalogue
        connection, and a per-seeker count answers "are they engaged" without
        needing that join.
        """
        conn = self._conn()
        resume_row = conn.execute(
            "SELECT analysis_json FROM seeker_resumes WHERE seeker_id = ?", (seeker_id,)
        ).fetchone()
        resume_analysis = json.loads(resume_row["analysis_json"]) if resume_row else {}

        discovery_rows = conn.execute(
            """
            SELECT search_query, filters_json FROM seeker_discovery_events
            WHERE seeker_id = ? ORDER BY id DESC LIMIT 50
            """,
            (seeker_id,),
        ).fetchall()
        sector_counts: Counter[str] = Counter()
        skill_counts: Counter[str] = Counter()
        seniority_counts: Counter[str] = Counter()
        recent_terms: list[str] = []
        for row in discovery_rows:
            filters = json.loads(row["filters_json"])
            sector_counts.update(filters.get("sectors") or [])
            skill_counts.update(filters.get("skills") or [])
            seniority_counts.update(filters.get("seniority") or [])
            if row["search_query"] and row["search_query"] not in recent_terms:
                recent_terms.append(row["search_query"])

        saved_roles_count = conn.execute(
            "SELECT COUNT(*) FROM saved_roles WHERE seeker_id = ?", (seeker_id,)
        ).fetchone()[0]

        return {
            "resume_skills": resume_analysis.get("skills", []),
            "resume_role_families": resume_analysis.get("role_families", []),
            "resume_sectors": resume_analysis.get("sectors", []),
            "resume_seniority": resume_analysis.get("seniority"),
            "searched_sectors": [name for name, _ in sector_counts.most_common(8)],
            "searched_skills": [name for name, _ in skill_counts.most_common(8)],
            "searched_seniority": [name for name, _ in seniority_counts.most_common(4)],
            "recent_search_terms": recent_terms[:8],
            "saved_roles_count": saved_roles_count,
        }

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

    def recommendation_health(self) -> dict[str, object]:
        """Aggregate product-learning signals for the admin operations desk."""
        conn = self._conn()
        total_seekers = conn.execute("SELECT COUNT(*) FROM seekers").fetchone()[0]
        impressions = conn.execute(
            "SELECT COUNT(*) FROM recommendation_impressions"
        ).fetchone()[0]
        clicked = conn.execute(
            "SELECT COUNT(*) FROM recommendation_impressions WHERE clicked_at IS NOT NULL"
        ).fetchone()[0]
        reached = conn.execute(
            "SELECT COUNT(DISTINCT seeker_id) FROM recommendation_impressions"
        ).fetchone()[0]
        window = conn.execute(
            "SELECT MIN(created_at), MAX(created_at) FROM recommendation_impressions"
        ).fetchone()
        feedback = {
            row[0]: row[1]
            for row in conn.execute(
                "SELECT action, COUNT(*) FROM recommendation_feedback GROUP BY action"
            )
        }
        recommendation_saves = conn.execute(
            """
            SELECT COUNT(*) FROM saved_roles s
            WHERE EXISTS (
                SELECT 1 FROM recommendation_impressions i
                WHERE i.seeker_id=s.seeker_id AND i.source=s.source
                  AND i.source_id=s.source_id
            )
            """
        ).fetchone()[0]
        return {
            "impressions": impressions,
            "clicks": clicked,
            "click_through_pct": round(100.0 * clicked / impressions, 1) if impressions else 0.0,
            "saves": recommendation_saves,
            "more_like": int(feedback.get("more_like", 0)),
            "dismissals": int(feedback.get("not_interested", 0)),
            "wrong_reason": int(feedback.get("wrong_reason", 0)),
            "seekers_reached": reached,
            "eligible_seekers": total_seekers,
            "coverage_pct": round(100.0 * reached / total_seekers, 1) if total_seekers else 0.0,
            "tracking_available": True,
            "window_started_at": window[0],
            "window_ended_at": window[1],
        }

    def record_visit(self, visitor_hash: str, *, now: datetime | None = None) -> None:
        """Count one anonymous board visit. A no-op if this visitor was already
        counted today — UNIQUE(visitor_hash, visit_date) does the dedup, so the
        caller (main.py's /api/visit) can fire this on every page load without
        inflating the count."""
        moment = now or utcnow()
        visit_date = moment.astimezone(_HONG_KONG).date().isoformat()
        with self._write() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO anonymous_visits (visitor_hash, visit_date, created_at) "
                "VALUES (?, ?, ?)",
                (visitor_hash, visit_date, to_iso(moment)),
            )

    def user_activity_overview(
        self, *, days: int = 30, now: datetime | None = None
    ) -> dict[str, Any]:
        """Seeker AND anonymous board activity, bucketed by Hong Kong calendar day.

        Two independent, non-overlapping populations, reported side by side
        rather than summed into one "visitors" number:

        - Seeker activity comes from `sessions` — a row is issued on every
          sign-in path (register, login, a post-reset re-login, Google/LinkedIn).
        - Anonymous activity comes from `anonymous_visits` — one row per visitor
          per day, keyed by a hashed opaque cookie (main.py's /api/visit skips
          this entirely for a request that already carries a valid Seeker
          session, so the two tables cannot double-count the same visit).

        A member of either population is "returning" on the first day, within
        the window, that is NOT their earliest active day in that same window —
        i.e. they showed up again after already being counted once.
        """
        days = max(1, min(int(days), 365))
        today = (now or datetime.now(timezone.utc)).astimezone(_HONG_KONG).date()
        start_day = today - timedelta(days=days - 1)
        window_start_iso = to_iso(
            datetime(start_day.year, start_day.month, start_day.day, tzinfo=_HONG_KONG)
        )

        conn = self._conn()
        total_seekers = conn.execute("SELECT COUNT(*) FROM seekers").fetchone()[0]
        signup_rows = conn.execute(
            "SELECT created_at FROM seekers WHERE created_at >= ?", (window_start_iso,)
        ).fetchall()
        session_rows = conn.execute(
            "SELECT seeker_id, created_at FROM sessions "
            "WHERE created_at >= ? AND seeker_id IS NOT NULL",
            (window_start_iso,),
        ).fetchall()
        visit_rows = conn.execute(
            "SELECT visitor_hash, visit_date FROM anonymous_visits WHERE visit_date >= ?",
            (start_day.isoformat(),),
        ).fetchall()

        def hk_date(iso_value: str) -> date:
            return from_iso(iso_value).astimezone(_HONG_KONG).date()

        signups_by_day: dict[date, int] = {}
        for row in signup_rows:
            d = hk_date(row["created_at"])
            signups_by_day[d] = signups_by_day.get(d, 0) + 1

        active_days_by_seeker: dict[str, set[date]] = {}
        for row in session_rows:
            active_days_by_seeker.setdefault(row["seeker_id"], set()).add(
                hk_date(row["created_at"])
            )
        active_by_day, returning_by_day, returning_seeker_ids = _bucket_returning(
            active_days_by_seeker
        )

        visit_days_by_visitor: dict[str, set[date]] = {}
        for row in visit_rows:
            visit_days_by_visitor.setdefault(row["visitor_hash"], set()).add(
                date.fromisoformat(row["visit_date"])
            )
        visits_by_day, returning_visits_by_day, returning_visitor_hashes = _bucket_returning(
            visit_days_by_visitor
        )

        active_seekers = len(active_days_by_seeker)
        returning_seekers = len(returning_seeker_ids)
        unique_visitors = len(visit_days_by_visitor)
        returning_visitors = len(returning_visitor_hashes)

        points = []
        anonymous_points = []
        cursor = start_day
        while cursor <= today:
            points.append(
                {
                    "date": cursor.isoformat(),
                    "new_signups": signups_by_day.get(cursor, 0),
                    "active_seekers": active_by_day.get(cursor, 0),
                    "returning_seekers": returning_by_day.get(cursor, 0),
                }
            )
            anonymous_points.append(
                {
                    "date": cursor.isoformat(),
                    "unique_visitors": visits_by_day.get(cursor, 0),
                    "returning_visitors": returning_visits_by_day.get(cursor, 0),
                }
            )
            cursor += timedelta(days=1)

        return {
            "days": days,
            "window_started_on": start_day.isoformat(),
            "window_ended_on": today.isoformat(),
            "total_seekers": total_seekers,
            "new_signups": len(signup_rows),
            "active_seekers": active_seekers,
            "returning_seekers": returning_seekers,
            "repeat_visit_rate_pct": (
                round(100.0 * returning_seekers / active_seekers, 1) if active_seekers else 0.0
            ),
            "points": points,
            "tracking_available": True,
            "anonymous": {
                "unique_visitors": unique_visitors,
                "returning_visitors": returning_visitors,
                "repeat_visit_rate_pct": (
                    round(100.0 * returning_visitors / unique_visitors, 1)
                    if unique_visitors
                    else 0.0
                ),
                "points": anonymous_points,
            },
        }

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

    def record_resume_download(
        self,
        *,
        seeker_id: str,
        seeker_email: str,
        admin_id: str,
        admin_email: str,
        filename: str,
        size_bytes: int,
        reason: str | None = None,
        now: datetime | None = None,
    ) -> None:
        """Write one audit row for an Ultimate Admin reading a resume file.

        The caller writes this BEFORE handing over the bytes, so a failure here
        aborts the download rather than serving an unlogged copy — see
        migrate_to_phase_10 for why the trail has to outlive the account.
        """
        with self._write() as conn:
            conn.execute(
                """
                INSERT INTO seeker_resume_downloads
                    (seeker_id, seeker_email, admin_id, admin_email,
                     filename, size_bytes, reason, downloaded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    seeker_id, seeker_email, admin_id, admin_email,
                    filename, int(size_bytes), reason or None,
                    (now or utcnow()).isoformat(),
                ),
            )

    def list_resume_downloads(self, *, limit: int = 200) -> list[dict[str, Any]]:
        """The download log, newest first — what makes the route accountable."""
        rows = self._conn().execute(
            """
            SELECT seeker_id, seeker_email, admin_id, admin_email,
                   filename, size_bytes, reason, downloaded_at
            FROM seeker_resume_downloads
            ORDER BY downloaded_at DESC LIMIT ?
            """,
            (max(1, min(int(limit), 1000)),),
        )
        return [dict(row) for row in rows]

    def delete_resume(self, seeker_id: str) -> bool:
        with self._write() as conn:
            cursor = conn.execute(
                "DELETE FROM seeker_resumes WHERE seeker_id = ?", (seeker_id,)
            )
        return cursor.rowcount == 1

    # -- alerts (opt-in weekly email of newly-recommended Roles) ------------

    def get_alert_opt_in(self, seeker_id: str) -> bool:
        """Whether this Seeker has turned Alerts on. No row means never asked — False."""
        row = self._conn().execute(
            "SELECT opted_in FROM alert_settings WHERE seeker_id = ?", (seeker_id,)
        ).fetchone()
        return bool(row["opted_in"]) if row is not None else False

    def set_alert_opt_in(
        self, seeker_id: str, opted_in: bool, *, now: datetime | None = None
    ) -> bool:
        """Turn Alerts on or off. Returns the resolved state."""
        stamp = to_iso(now or utcnow())
        with self._write() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO alert_settings (seeker_id, opted_in, updated_at) "
                "VALUES (?, 0, ?)",
                (seeker_id, stamp),
            )
            conn.execute(
                "UPDATE alert_settings SET opted_in = ?, updated_at = ? WHERE seeker_id = ?",
                (int(bool(opted_in)), stamp, seeker_id),
            )
        return bool(opted_in)

    def seekers_due_for_alert(self, *, cutoff: datetime) -> list[str]:
        """
        Seeker ids opted into Alerts and due to be considered this run: never
        sent an Alert before, or last sent on or before `cutoff`.

        The weekly Alerts job owns the actual cadence policy (currently: at
        least 7 days since the last send) and passes in the cutoff it computed
        — that interval is a decision made where the job runs, not a constant
        buried in storage.
        """
        rows = self._conn().execute(
            "SELECT seeker_id FROM alert_settings "
            "WHERE opted_in = 1 AND (last_sent_at IS NULL OR last_sent_at <= ?)",
            (to_iso(cutoff),),
        ).fetchall()
        return [row["seeker_id"] for row in rows]

    def mark_alert_sent(self, seeker_id: str, *, now: datetime | None = None) -> None:
        """Record that this Seeker's weekly Alert email went out just now."""
        stamp = to_iso(now or utcnow())
        with self._write() as conn:
            conn.execute(
                "UPDATE alert_settings SET last_sent_at = ?, updated_at = ? WHERE seeker_id = ?",
                (stamp, stamp, seeker_id),
            )

    def list_alerted_role_ids(self, seeker_id: str) -> set[tuple[str, str]]:
        """Every (source, source_id) already sent to this Seeker in an Alert, ever.

        This is the "new-to-you" filter from the feature's own spec: a Role is
        excluded from consideration once it has been sent, regardless of how
        long it has been on the board or whether the Seeker acted on it.
        """
        rows = self._conn().execute(
            "SELECT source, source_id FROM alerted_roles WHERE seeker_id = ?", (seeker_id,)
        ).fetchall()
        return {(row["source"], row["source_id"]) for row in rows}

    def record_alerted_roles(
        self,
        seeker_id: str,
        references: Iterable[tuple[str, str]],
        *,
        now: datetime | None = None,
    ) -> None:
        """Mark a batch of Roles as sent to this Seeker in an Alert. Idempotent."""
        stamp = to_iso(now or utcnow())
        with self._write() as conn:
            conn.executemany(
                """
                INSERT OR IGNORE INTO alerted_roles (seeker_id, source, source_id, sent_at)
                VALUES (?, ?, ?, ?)
                """,
                [(seeker_id, source, source_id, stamp) for source, source_id in references],
            )

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
            conn.execute("DELETE FROM alerted_roles WHERE seeker_id = ?", (seeker_id,))
            conn.execute("DELETE FROM alert_settings WHERE seeker_id = ?", (seeker_id,))
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
