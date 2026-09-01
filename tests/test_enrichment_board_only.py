"""
ADR 0034 — WE DO NOT ESTIMATE THE SALARY OF A ROLE THAT IS NOT ON THE BOARD.

A bulk enrichment run once spent $5.24 on 1,164 Roles, and 66% of them —
duplicate copies of a cross-posted vacancy, postings over a month old, rows
with no posting date — could never have been shown to a Seeker. The cause was
structural: `_fetch_unenriched` selected on `is_active = 1` alone, with no
notion of what "on the board" (`webapp/backend/job_read.BOARD_WHERE`) means.

`hk_jobs.board_visibility.board_visible_sql()` is now the one predicate both
sides share (see that module's docstring). This file pins the write side:
`_fetch_unenriched` must select ONLY board-visible Roles, unconditionally —
`--re-enrich` and `--enrich-boutique` included, since ADR 0034 has no carve-out.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from hk_jobs import enrichment as enrichment_module
from hk_jobs.enrichment import EnrichmentPipeline

_SCHEMA = """
CREATE TABLE jobs (
    source TEXT, source_id TEXT, title TEXT, company TEXT, company_slug TEXT,
    source_tier TEXT, description_clean TEXT, category TEXT,
    is_active INTEGER DEFAULT 1, is_primary INTEGER DEFAULT 1,
    admin_hidden INTEGER DEFAULT 0, posted_at TEXT,
    fetched_at TEXT DEFAULT '2026-08-05T00:00:00'
);
CREATE TABLE job_enrichments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT, source_id TEXT, seniority TEXT,
    years_experience_required INTEGER, required_skills TEXT, remote_type TEXT,
    salary_hkd_min INTEGER, salary_hkd_max INTEGER, job_category TEXT,
    enriched_at TEXT, model_used TEXT,
    salary_estimated_min INTEGER, salary_estimated_max INTEGER,
    salary_estimated_confidence TEXT, description_summary TEXT, title_en TEXT,
    prompt_version TEXT, salary_tier TEXT, salary_role TEXT, salary_grade TEXT,
    manually_edited_at TEXT,
    UNIQUE (source, source_id)
);
"""

_MODEL_ANSWER = {
    "title_en": "Analyst", "seniority": "mid", "years_experience": 4,
    "skills": ["Excel"], "remote_type": "on-site",
    "salary_hkd_min": None, "salary_hkd_max": None, "job_category": "Operations",
    "salary_estimated_min": 30_000, "salary_estimated_max": 40_000,
    "salary_estimated_confidence": "low", "salary_tier": None,
    "salary_role": None, "salary_grade": None,
    "description_summary": "An analyst role.",
}


class _StubEnricher:
    """Same answer for every Role, no network — records what it was asked to price."""

    calls: list[tuple[str, str]] = []

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def _enrich_with_retry(self, title, company, _description, seniority=None,
                            company_slug=None):
        _StubEnricher.calls.append((title, company))
        return dict(_MODEL_ANSWER)


def _within_month(days_ago: int = 1) -> str:
    return (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()


def _outside_month(days_ago: int = 45) -> str:
    return (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()


ROWS = [
    # (source_id, is_primary, admin_hidden, posted_at) — ON_BOARD is the control.
    ("ON_BOARD", 1, 0, _within_month()),
    ("DUPLICATE_COPY", 0, 0, _within_month()),      # is_primary = 0
    ("POSTED_TOO_LONG_AGO", 1, 0, _outside_month()),  # outside the 1-month window
    ("NO_POSTING_DATE", 1, 0, None),                 # fails closed
    ("ADMIN_HIDDEN", 1, 1, _within_month()),          # ADR 0032 hidden
]


@pytest.fixture
def db(tmp_path: Path, monkeypatch) -> Path:
    path = tmp_path / "jobs.db"
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    conn.executemany(
        "INSERT INTO jobs (source, source_id, title, company, company_slug, "
        "source_tier, description_clean, is_primary, admin_hidden, posted_at) "
        "VALUES ('jobsdb', ?, 'Analyst', 'HSBC', 'hsbc', 'mainstream', "
        "'A role.', ?, ?, ?)",
        ROWS,
    )
    conn.commit()
    conn.close()
    _StubEnricher.calls = []
    monkeypatch.setattr(enrichment_module, "DeepSeekEnricher", _StubEnricher)
    return path


def _enriched_ids(db_path: Path) -> set[str]:
    """Which Roles a run actually sent to the estimator. A `job_enrichments`
    row exists iff `_fetch_unenriched` selected it and the enrich loop ran —
    whether the resulting figure survived `salary.finalise()` is a separate
    question this file does not care about."""
    conn = sqlite3.connect(db_path)
    try:
        return {r[0] for r in conn.execute("SELECT source_id FROM job_enrichments")}
    finally:
        conn.close()


def test_a_regular_run_estimates_only_the_board_visible_role(db: Path):
    EnrichmentPipeline(db_path=str(db), api_key="test").run()
    assert _enriched_ids(db) == {"ON_BOARD"}


def test_a_duplicate_copy_of_a_cross_posted_vacancy_is_never_priced(db: Path):
    """is_primary = 0: a Seeker never sees this row, only the primary copy."""
    EnrichmentPipeline(db_path=str(db), api_key="test").run()
    assert "DUPLICATE_COPY" not in _enriched_ids(db)


def test_a_posting_over_a_month_old_is_never_priced(db: Path):
    EnrichmentPipeline(db_path=str(db), api_key="test").run()
    assert "POSTED_TOO_LONG_AGO" not in _enriched_ids(db)


def test_a_role_with_no_posting_date_is_never_priced(db: Path):
    """Fails closed, same as the board itself — an unverifiable age is not
    "on the board" any more than a verified stale one is."""
    EnrichmentPipeline(db_path=str(db), api_key="test").run()
    assert "NO_POSTING_DATE" not in _enriched_ids(db)


def test_an_admin_hidden_role_is_never_priced(db: Path):
    """ADR 0032's Hidden state is off the public board, so ADR 0034 excludes
    it from estimation too — hiding a Role does not put it in a special queue."""
    EnrichmentPipeline(db_path=str(db), api_key="test").run()
    assert "ADMIN_HIDDEN" not in _enriched_ids(db)


def test_re_enrich_still_obeys_the_board_only_rule(db: Path):
    """ADR 0034 has no carve-out: --re-enrich reprocesses everything ELSE, not
    everything, full stop."""
    EnrichmentPipeline(db_path=str(db), api_key="test").run(re_enrich=True)
    assert _enriched_ids(db) == {"ON_BOARD"}


def test_enrich_boutique_still_obeys_the_board_only_rule(db: Path):
    conn = sqlite3.connect(db)
    conn.execute("UPDATE jobs SET category = 'Boutique'")
    conn.commit()
    conn.close()

    EnrichmentPipeline(db_path=str(db), api_key="test").run(boutique_only=True)
    assert _enriched_ids(db) == {"ON_BOARD"}
