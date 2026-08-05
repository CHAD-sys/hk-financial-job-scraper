"""
Salary audit re-selection must not re-bill an unchanged estimate.

Before this, `_select_outliers` had no memory of past audits: it re-selected every
active job matching the outlier heuristic (>=120k, cluster outlier, ambiguous title)
on every run, regardless of whether that exact estimate had already been judged "ok"
the night before. Real production numbers: ~550-590 jobs flagged every single night,
with only ~50-80/night actually corrected — the rest was pure re-verification spend on
listings whose salary hadn't changed since they were last cleared.

The fix: log every verdict (not just corrections) with a timestamp, and skip a job
whose last audit already happened at-or-after its current `enriched_at` — nothing
about that estimate could have changed since, so re-judging it would only reproduce
the same verdict. A re-enrichment (new prompt_version, reactivated listing) bumps
`enriched_at` and makes the job eligible again on its own.
"""

import sqlite3
from pathlib import Path

import pytest

from hk_jobs import salary_audit

_SCHEMA = """
CREATE TABLE jobs (
    source TEXT, source_id TEXT, title TEXT, company TEXT, company_slug TEXT,
    source_tier TEXT, description_clean TEXT, is_active INTEGER DEFAULT 1
);
CREATE TABLE job_enrichments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT, source_id TEXT, seniority TEXT, job_category TEXT,
    salary_tier TEXT, salary_role TEXT,
    salary_estimated_min INTEGER, salary_estimated_max INTEGER,
    enriched_at TEXT,
    UNIQUE (source, source_id)
);
CREATE TABLE salary_audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT NOT NULL,
    source_id   TEXT NOT NULL,
    audited_at  TEXT NOT NULL,
    old_min     INTEGER,
    old_max     INTEGER,
    new_min     INTEGER,
    new_max     INTEGER,
    action      TEXT NOT NULL,
    reason      TEXT
);
"""


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "jobs.db"


@pytest.fixture
def conn(db_path: Path) -> sqlite3.Connection:
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    c.executescript(_SCHEMA)
    c.execute(
        "INSERT INTO jobs (source, source_id, title, company, company_slug, "
        "source_tier, description_clean, is_active) VALUES "
        "('jobsdb', 'J-1', 'Team Head, Client Relationship Management', 'HSBC', "
        "'hsbc', 'tier1', '', 1)"
    )
    c.execute(
        "INSERT INTO job_enrichments (source, source_id, seniority, job_category, "
        "salary_tier, salary_role, salary_estimated_min, salary_estimated_max, enriched_at) "
        "VALUES ('jobsdb', 'J-1', 'lead', 'Finance', 'front_office', 'private_banking_rm', "
        "100000, 150000, '2026-08-01T00:00:00+00:00')"
    )
    c.commit()
    return c


def test_flagged_by_heuristic_when_never_audited(conn):
    flagged = salary_audit._select_outliers(conn)
    assert [r["source_id"] for r in flagged] == ["J-1"]


def test_skipped_after_being_audited_ok(conn):
    conn.execute(
        "INSERT INTO salary_audit_log (source, source_id, audited_at, old_min, "
        "old_max, action, reason) VALUES "
        "('jobsdb', 'J-1', '2026-08-02T00:00:00+00:00', 100000, 150000, 'ok', 'band is right')"
    )
    conn.commit()

    flagged = salary_audit._select_outliers(conn)

    assert flagged == []


def test_reselected_after_reenrichment_bumps_past_last_audit(conn):
    conn.execute(
        "INSERT INTO salary_audit_log (source, source_id, audited_at, old_min, "
        "old_max, action, reason) VALUES "
        "('jobsdb', 'J-1', '2026-08-02T00:00:00+00:00', 100000, 150000, 'ok', 'band is right')"
    )
    # A later re-enrichment (e.g. prompt_version bump) rewrites enriched_at.
    conn.execute(
        "UPDATE job_enrichments SET enriched_at = '2026-08-03T00:00:00+00:00' "
        "WHERE source='jobsdb' AND source_id='J-1'"
    )
    conn.commit()

    flagged = salary_audit._select_outliers(conn)

    assert [r["source_id"] for r in flagged] == ["J-1"]


def test_full_mode_ignores_audit_history(conn):
    conn.execute(
        "INSERT INTO salary_audit_log (source, source_id, audited_at, old_min, "
        "old_max, action, reason) VALUES "
        "('jobsdb', 'J-1', '2026-08-02T00:00:00+00:00', 100000, 150000, 'ok', 'band is right')"
    )
    conn.commit()

    flagged = salary_audit._select_outliers(conn, full=True)

    assert [r["source_id"] for r in flagged] == ["J-1"]


def test_run_audit_logs_ok_verdict_and_next_selection_skips_it(conn, db_path, monkeypatch):
    monkeypatch.setattr(
        salary_audit,
        "_judge",
        lambda _enricher, _row: {"verdict": "ok", "reason": "band is right"},
    )

    salary_audit.run_audit(db_path=str(db_path), api_key="test-key")

    logged = conn.execute("SELECT action FROM salary_audit_log WHERE source_id='J-1'").fetchall()
    assert [r["action"] for r in logged] == ["ok"]

    # A second run against the same (unchanged) estimate should find nothing to do.
    flagged = salary_audit._select_outliers(conn)
    assert flagged == []
