"""
Shared builders for the backend tests.

WHY THIS FILE EXISTS
--------------------
`_make_db`, `_make_bundle` and `_import_main` used to live in
`test_single_origin.py`, and `test_auth_endpoints.py` imported them *from that
test module* — so one test file's collection order silently affected another's.
There was no `conftest.py` to put them in.

They live here rather than in `conftest.py` because pytest treats `conftest.py`
as a plugin, not a library: importing helpers out of it works but is a known
smell, and it stops the helpers being usable from a plain `python -c` when you
are debugging a fixture by hand.

`conftest.py` next door turns these into fixtures. Tests should normally ask for
the fixture; reach for these directly only when a test needs to build something
the fixtures do not cover (a second database, an odd bundle layout).
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Iterable

BACKEND = Path(__file__).resolve().parent.parent / "webapp" / "backend"

INDEX_MARKER = "<!-- test index.html -->"

# The one row every pre-existing test asserts on. Kept as the default seed so
# `make_jobs_db(path)` with no arguments behaves exactly as the old `_make_db`.
DEFAULT_JOB: dict[str, Any] = {
    "source": "workday",
    "source_id": "J1",
    "company": "HSBC",
    "url": "https://example.test/j1",
    "title": "Credit Risk Analyst",
    "description_clean": "Analyse credit risk.",
    "locations": '["Hong Kong"]',
    "posted_at": "2026-07-01T00:00:00+00:00",
}

# Column defaults for a jobs row, so a test only states what it cares about.
_JOB_DEFAULTS: dict[str, Any] = {
    "source": "workday",
    "source_id": "X",
    "company": "HSBC",
    "url": "https://example.test/x",
    "title": "Analyst",
    "description_clean": "",
    "locations": "[]",
    "posted_at": None,
    "is_active": 1,
    "closed_at": None,
    "is_primary": 1,
    "cross_posted": 0,
    "apply_url": "",
    "source_tier": "mainstream",
    "board_signals": "{}",
    "grp_new": None,
    "grp_urgent": None,
    "grp_applicants": None,
}

_ENRICHMENT_DEFAULTS: dict[str, Any] = {
    "source": "workday",
    "source_id": "X",
    "seniority": None,
    "job_category": None,
    "remote_type": None,
    "required_skills": None,
    "salary_hkd_min": None,
    "salary_hkd_max": None,
    "salary_estimated_min": None,
    "salary_estimated_max": None,
    "salary_estimated_confidence": None,
    "years_experience_required": None,
    "description_summary": None,
    "title_en": None,
}

_JOBS_DDL = """
CREATE TABLE jobs (
    source          TEXT NOT NULL,
    source_id       TEXT NOT NULL,
    company         TEXT NOT NULL,
    url             TEXT NOT NULL,
    title           TEXT NOT NULL,
    description_clean TEXT NOT NULL DEFAULT '',
    locations       TEXT NOT NULL DEFAULT '[]',
    posted_at       TEXT,
    is_active       INTEGER NOT NULL DEFAULT 1,
    closed_at       TEXT,
    is_primary      INTEGER NOT NULL DEFAULT 1,
    cross_posted    INTEGER NOT NULL DEFAULT 0,
    apply_url       TEXT NOT NULL DEFAULT '',
    source_tier     TEXT NOT NULL DEFAULT 'mainstream',
    board_signals   TEXT NOT NULL DEFAULT '{}',
    grp_new         INTEGER,
    grp_urgent      INTEGER,
    grp_applicants  INTEGER,
    PRIMARY KEY (source, source_id)
);
"""

_ENRICHMENTS_DDL = """
CREATE TABLE job_enrichments (
    source          TEXT NOT NULL,
    source_id       TEXT NOT NULL,
    seniority       TEXT,
    job_category    TEXT,
    remote_type     TEXT,
    required_skills TEXT,
    salary_hkd_min  INTEGER,
    salary_hkd_max  INTEGER,
    salary_estimated_min INTEGER,
    salary_estimated_max INTEGER,
    salary_estimated_confidence TEXT,
    years_experience_required INTEGER,
    description_summary TEXT,
    title_en        TEXT,
    PRIMARY KEY (source, source_id)
);
"""


def job(**over: Any) -> dict[str, Any]:
    """A jobs row: defaults, overridden by whatever the test states."""
    return {**_JOB_DEFAULTS, **over}


def enrichment(**over: Any) -> dict[str, Any]:
    """A job_enrichments row: defaults, overridden by whatever the test states."""
    return {**_ENRICHMENT_DEFAULTS, **over}


def signals(**fields: Any) -> str:
    """
    A row's own `board_signals` JSON, e.g. `signals(urgently_hiring=True)`.

    Flat, NOT namespaced by source: the column holds only this row's board's
    signals, and the read path namespaces it under the row's `source` on the way
    out. Seeding `{"indeed": {...}}` here would produce `{"indeed": {"indeed": …}}`
    on the wire.
    """
    return json.dumps(fields)


def _insert(conn: sqlite3.Connection, table: str, rows: Iterable[dict[str, Any]]) -> None:
    for row in rows:
        cols = ", ".join(row)
        marks = ", ".join("?" * len(row))
        conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", list(row.values()))


def make_jobs_db(
    path: Path,
    jobs: Iterable[dict[str, Any]] | None = None,
    enrichments: Iterable[dict[str, Any]] | None = None,
) -> None:
    """
    A stand-in jobs.db holding exactly the columns the read path touches.

    A two-table stand-in rather than the real 116 MB jobs.db, so every test that
    uses it is hermetic and runs anywhere. Pass `jobs=` to seed your own rows;
    the default is the single row the older tests already assert on.

    Also builds the search index (jobs_fts / search_vocab), same as migration
    phase 32 — a real jobs.db always has it by the time the webapp reads it, so
    a hermetic stand-in missing it would make every `search=` test exercise a
    database shape that cannot occur outside a test.
    """
    from hk_jobs.search_index import rebuild_search_index

    conn = sqlite3.connect(path)
    with conn:
        conn.execute(_JOBS_DDL)
        conn.execute(_ENRICHMENTS_DDL)
        _insert(conn, "jobs", jobs if jobs is not None else [job(**DEFAULT_JOB)])
        _insert(conn, "job_enrichments", enrichments or [])
    rebuild_search_index(conn)
    conn.close()


def make_bundle(dist: Path) -> None:
    """A fake `npm run build` output: index.html, a hashed asset, a root file."""
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(
        f"<html><body>{INDEX_MARKER}<div id='root'></div></body></html>", encoding="utf-8"
    )
    (dist / "assets" / "index-abc123.js").write_text("console.log('app')", encoding="utf-8")
    (dist / "favicon.svg").write_text("<svg/>", encoding="utf-8")


if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def make_app(db: Path, dist: Path | None = None, submissions: Path | None = None, **over):
    """
    An app configured for one test.

    This used to delete `main` and `mailer` from `sys.modules` and re-import
    them, because every piece of configuration was read from the environment
    while the module was being imported — so a re-import was the only way to
    exercise a different database. It also re-ran a network download and a
    64 MiB Argon2 hash on every call.

    It is a function call now. `create_app` takes the configuration; nothing is
    global, so two apps with two different databases can exist at once and a
    test never touches `os.environ` at all.

    Outbound Seeker mail goes to a RecordingSender unless a test says otherwise,
    so nothing in the suite can reach a real SMTP server. Reach it through
    `client.app.state.sender` to assert on what was sent.
    """
    from main import create_app  # imported here so a collection-time import cannot fail
    from sender import RecordingSender
    from settings import Settings

    sender = over.pop("sender", None) or RecordingSender()
    return create_app(
        Settings(
            jobs_db=db,
            frontend_dist=dist if dist is not None else Path("/nonexistent/dist"),
            submissions_dir=submissions,
            **over,
        ),
        sender=sender,
    )
