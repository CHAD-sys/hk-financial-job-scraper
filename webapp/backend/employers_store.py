"""
Employer persistence — the /data/employers.db layer.

Opens the gate ADR 0001 left ajar on purpose: "Employers get their own table
when they arrive." This is that table — a separate SQLite file, a separate
aggregate, never a `role` column bolted onto seekers.db. See
docs/adr/0001-accounts-are-seeker-only-employers-are-a-separate-aggregate.md
before touching the shape of this module; that ADR is what this file is
consciously reopening, not routing around.

Deliberately smaller than seekers_store.py. What ships here is identity only —
register, sign in, sign out, know who you are, delete your account. No email
verification, no password-reset flow, no provider identities (Google/LinkedIn),
no saved-anything. Each of those is either genuinely deferred (self-serve,
billing, seat management — PLAN_FRONT_PAGE decision 20's own 20-25 day
estimate) or a deliberate v1 cut to avoid the exact bug this session's audit
found on the Seeker side: an email flow that mints a link nothing ever
consumes. Add verify/reset here only alongside the endpoint AND the frontend
page that completes it, in the same change.

Same storage conventions as seekers_store.py, and for the same reasons:
  - stdlib sqlite3, hand-written SQL, no ORM (ADR 0004).
  - Datetimes are ISO 8601 UTC text.
  - `employer_id` is a uuid4 string — opaque, permanent, never the email.

Nothing in this module knows about HTTP, FastAPI or cookies. auth.py's
password/session functions are reused as-is: they take a plain store and plain
values, and this store implements the same method names
(insert_session/get_session/extend_session/delete_session/
delete_sessions_for_seeker) so auth.issue_session()/verify_session() work
against an EmployerStore exactly as they do against a SeekerStore, with zero
changes to auth.py.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)

_BUSY_TIMEOUT_SECONDS = 5.0


class EmailAlreadyRegistered(Exception):
    """Raised by create_employer() when the address already has an account."""


# ── Where the file lives ──────────────────────────────────────────────────────


def _repo_data_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "data"


def resolve_employers_db_path() -> Path:
    """
    Decide which file is employers.db, and refuse to return jobs.db or
    seekers.db — the same guard seekers_store.py applies to itself, extended
    to cover the sibling store too, since the two must never collide.

    Resolution order:
      1. `EMPLOYERS_DB_PATH` if set.
      2. Otherwise, `employers.db` next to wherever jobs.db resolves — same
         co-location rule as seekers.db, so it lands on the Railway volume
         automatically wherever JOBS_DB_PATH points.
    """
    override = os.environ.get("EMPLOYERS_DB_PATH", "").strip()
    if override:
        path = Path(override).expanduser().resolve()
    else:
        jobs_db = Path(
            os.environ.get("JOBS_DB_PATH", str(_repo_data_dir() / "jobs.db"))
        ).expanduser().resolve()
        path = jobs_db.parent / "employers.db"

    if path.name in ("jobs.db", "seekers.db"):
        raise ValueError(
            f"Refusing to use {path} for Employer data: it must be its own file, "
            "never jobs.db (scraper-owned) or seekers.db (a different aggregate, "
            "ADR 0001). Set EMPLOYERS_DB_PATH to a different file."
        )
    return path


# ── Schema ─────────────────────────────────────────────────────────────────────

_EMPLOYERS_DDL = """
CREATE TABLE IF NOT EXISTS employers (
    id             TEXT PRIMARY KEY,
    email          TEXT NOT NULL UNIQUE,
    password_hash  TEXT NOT NULL,
    company_name   TEXT NOT NULL,
    contact_name   TEXT,
    created_at     TEXT NOT NULL,
    last_login_at  TEXT
);
"""

_EMPLOYER_SESSIONS_DDL = """
CREATE TABLE IF NOT EXISTS employer_sessions (
    token_hash   TEXT PRIMARY KEY,
    employer_id  TEXT NOT NULL REFERENCES employers (id) ON DELETE CASCADE,
    created_at   TEXT NOT NULL,
    expires_at   TEXT NOT NULL,
    user_agent   TEXT
);
"""

_EVENTS_DDL = """
CREATE TABLE IF NOT EXISTS employer_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    employer_id  TEXT,
    created_at   TEXT NOT NULL
);
"""

_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_employer_sessions_employer ON employer_sessions (employer_id);",
    "CREATE INDEX IF NOT EXISTS idx_employer_sessions_expires  ON employer_sessions (expires_at);",
    "CREATE INDEX IF NOT EXISTS idx_employer_events_name       ON employer_events (name, created_at);",
]


def migrate_to_phase_1(conn: sqlite3.Connection) -> None:
    """Create the three v1 tables: employers, employer_sessions, employer_events."""
    conn.execute(_EMPLOYERS_DDL)
    conn.execute(_EMPLOYER_SESSIONS_DDL)
    conn.execute(_EVENTS_DDL)
    for statement in _INDEXES:
        conn.execute(statement)


# One phase today. A phase 2 (email verification, password reset, provider
# identities) appends here — same rule as seekers_store.py: never edit phase 1.
_MIGRATIONS = (migrate_to_phase_1,)


# ── Time / normalisation helpers — identical contract to seekers_store.py ──────


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat()


def from_iso(text: str) -> datetime:
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def normalise_email(email: str) -> str:
    return email.strip().lower()


def new_employer_id() -> str:
    return str(uuid.uuid4())


# ── The store ─────────────────────────────────────────────────────────────────


class EmployerStore:
    """
    A writable connection to employers.db. Same connection-handling contract as
    SeekerStore (one connection per thread, WAL, explicit BEGIN IMMEDIATE
    transactions, a process-wide write lock) — see that class's docstring for
    the reasoning; it is not repeated here because it does not change.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = (
            Path(db_path).expanduser().resolve() if db_path else resolve_employers_db_path()
        )
        if self.db_path.name in ("jobs.db", "seekers.db"):
            raise ValueError(f"Refusing to use {self.db_path} for Employer data")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._write_lock = threading.Lock()
        self.migrate()

    def _conn(self) -> sqlite3.Connection:
        conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(
                self.db_path, timeout=_BUSY_TIMEOUT_SECONDS, isolation_level=None,
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute(f"PRAGMA busy_timeout={int(_BUSY_TIMEOUT_SECONDS * 1000)}")
            self._local.conn = conn
        return conn

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
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
        with self._write() as conn:
            for migration in _MIGRATIONS:
                migration(conn)

    def close(self) -> None:
        conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    # -- employers -------------------------------------------------------------

    def create_employer(
        self,
        email: str,
        *,
        password_hash: str,
        company_name: str,
        contact_name: str | None = None,
        now: datetime | None = None,
    ) -> str:
        """Insert an Employer and return its uuid4 id. Raises EmailAlreadyRegistered
        if the address is taken — the UNIQUE constraint is the arbiter."""
        employer_id = new_employer_id()
        created_at = to_iso(now or utcnow())
        try:
            with self._write() as conn:
                conn.execute(
                    """
                    INSERT INTO employers
                        (id, email, password_hash, company_name, contact_name, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (employer_id, normalise_email(email), password_hash, company_name,
                     contact_name, created_at),
                )
        except sqlite3.IntegrityError as exc:
            raise EmailAlreadyRegistered(normalise_email(email)) from exc
        return employer_id

    def get_employer(self, employer_id: str) -> dict[str, Any] | None:
        row = self._conn().execute(
            "SELECT * FROM employers WHERE id = ?", (employer_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_employer_by_email(self, email: str) -> dict[str, Any] | None:
        row = self._conn().execute(
            "SELECT * FROM employers WHERE email = ?", (normalise_email(email),)
        ).fetchone()
        return dict(row) if row else None

    def touch_last_login(self, employer_id: str, *, now: datetime | None = None) -> None:
        with self._write() as conn:
            conn.execute(
                "UPDATE employers SET last_login_at = ? WHERE id = ?",
                (to_iso(now or utcnow()), employer_id),
            )

    # -- sessions ----------------------------------------------------------
    # Method names match SeekerStore exactly — this is the seam that lets
    # auth.issue_session()/verify_session()/revoke_session() work unmodified
    # against either store.

    def insert_session(
        self,
        token_hash: str,
        employer_id: str,
        expires_at: datetime,
        *,
        user_agent: str | None = None,
        now: datetime | None = None,
    ) -> None:
        with self._write() as conn:
            conn.execute(
                """
                INSERT INTO employer_sessions
                    (token_hash, employer_id, created_at, expires_at, user_agent)
                VALUES (?, ?, ?, ?, ?)
                """,
                (token_hash, employer_id, to_iso(now or utcnow()), to_iso(expires_at),
                 (user_agent or "")[:256] or None),
            )

    def get_session(self, token_hash: str) -> dict[str, Any] | None:
        row = self._conn().execute(
            "SELECT *, employer_id AS seeker_id FROM employer_sessions WHERE token_hash = ?",
            (token_hash,),
        ).fetchone()
        return dict(row) if row else None

    def extend_session(self, token_hash: str, expires_at: datetime) -> None:
        with self._write() as conn:
            conn.execute(
                "UPDATE employer_sessions SET expires_at = ? WHERE token_hash = ?",
                (to_iso(expires_at), token_hash),
            )

    def delete_session(self, token_hash: str) -> bool:
        with self._write() as conn:
            cursor = conn.execute(
                "DELETE FROM employer_sessions WHERE token_hash = ?", (token_hash,)
            )
            return cursor.rowcount > 0

    def delete_sessions_for_seeker(self, employer_id: str) -> int:
        """Named to match SeekerStore's method, not the vocabulary (CONTEXT.md:
        an Employer is never a Seeker) — this is what makes auth.revoke_all_
        sessions() callable against either store without a branch."""
        with self._write() as conn:
            cursor = conn.execute(
                "DELETE FROM employer_sessions WHERE employer_id = ?", (employer_id,)
            )
            return cursor.rowcount

    def purge_expired_sessions(self, *, now: datetime | None = None) -> int:
        with self._write() as conn:
            cursor = conn.execute(
                "DELETE FROM employer_sessions WHERE expires_at <= ?", (to_iso(now or utcnow()),)
            )
            return cursor.rowcount

    # -- events --------------------------------------------------------------

    def log_event(
        self, name: str, employer_id: str | None = None, *, now: datetime | None = None
    ) -> None:
        with self._write() as conn:
            conn.execute(
                "INSERT INTO employer_events (name, employer_id, created_at) VALUES (?, ?, ?)",
                (name, employer_id, to_iso(now or utcnow())),
            )

    # -- deletion --------------------------------------------------------------

    def delete_employer(self, employer_id: str, *, now: datetime | None = None) -> bool:
        """Real delete, same posture as SeekerStore.delete_seeker (ADR 0007's
        reasoning applies here too: an Employer's own account is not a Role,
        CLAUDE.md's soft-delete rule does not cover it)."""
        with self._write() as conn:
            exists = conn.execute(
                "SELECT 1 FROM employers WHERE id = ?", (employer_id,)
            ).fetchone()
            if exists is None:
                return False
            conn.execute("DELETE FROM employer_sessions WHERE employer_id = ?", (employer_id,))
            conn.execute("DELETE FROM employers WHERE id = ?", (employer_id,))
            conn.execute(
                "INSERT INTO employer_events (name, employer_id, created_at) VALUES (?, ?, ?)",
                ("employer.deleted", employer_id, to_iso(now or utcnow())),
            )
        logger.info("Deleted employer %s (rows removed, sessions revoked, event logged)", employer_id)
        return True


# ── Process-wide instance ─────────────────────────────────────────────────────

_store: EmployerStore | None = None
_store_lock = threading.Lock()


def get_store() -> EmployerStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = EmployerStore()
            logger.info("Employer store ready at %s", _store.db_path)
        return _store


def reset_store() -> None:
    """Drop the cached store. For tests and for a config reload."""
    global _store
    with _store_lock:
        if _store is not None:
            _store.close()
        _store = None
