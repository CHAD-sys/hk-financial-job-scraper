"""
A priced Role with a description but no card summary must not be stranded.

`_fetch_unenriched`'s first three arms (no enrichment row, stale prompt
version, no salary figure) cannot see this shape: the row is priced, sits on
the current prompt version, and carries a full description — so nothing ever
offered it to the model again. 35 board Roles were showing a card with no
summary line, some enriched the night before, because the model had returned
"" for description_summary while answering seniority, category and salary
normally.

The employer's own text is not publishable (job_read.PUBLISHABLE_DESCRIPTION),
so the card cannot fall back to an excerpt. Another model call is the only
repair — spaced by SUMMARY_RETRY_DAYS, because arm (3) already proved that a
candidate rule with no floor re-enriches the same unfixable rows every night.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

from hk_jobs.enrichment import SUMMARY_RETRY_DAYS, EnrichmentPipeline

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


def _db(tmp_path, *, summary, enriched_days_ago, description="Lead the credit risk team."):
    from hk_jobs.enrichers.deepseek import PROMPT_VERSION

    path = tmp_path / "jobs.db"
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    posted = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    enriched = (datetime.now(UTC) - timedelta(days=enriched_days_ago)).isoformat()
    conn.execute(
        "INSERT INTO jobs (source, source_id, title, company, company_slug, source_tier,"
        " description_clean, is_active, is_primary, admin_hidden, posted_at)"
        " VALUES ('workday','W1','Credit Risk Lead','HSBC','hsbc','mainstream',?,1,1,0,?)",
        (description, posted),
    )
    # Priced, current prompt version: invisible to arms (1), (2) and (3).
    conn.execute(
        "INSERT INTO job_enrichments (source, source_id, salary_estimated_min,"
        " salary_estimated_max, description_summary, prompt_version, enriched_at)"
        " VALUES ('workday','W1',40000,60000,?,?,?)",
        (summary, PROMPT_VERSION, enriched),
    )
    conn.commit()
    return path, conn


def _selected(path, conn):
    pipeline = EnrichmentPipeline(db_path=str(path))
    conn.row_factory = sqlite3.Row
    return [(r["source"], r["source_id"]) for r in pipeline._fetch_unenriched(conn, None)]


def test_a_priced_role_with_no_summary_is_offered_to_the_model_again(tmp_path):
    """RED before arm (4): priced, current version, full description — the
    selector saw nothing to do and the card stayed blank indefinitely."""
    path, conn = _db(tmp_path, summary="", enriched_days_ago=SUMMARY_RETRY_DAYS + 1)

    assert ("workday", "W1") in _selected(path, conn)


def test_a_role_that_already_has_a_summary_is_left_alone(tmp_path):
    path, conn = _db(tmp_path, summary="Leads the credit risk team.", enriched_days_ago=99)

    assert _selected(path, conn) == []


def test_the_retry_is_spaced_so_an_unsummarisable_role_is_not_billed_nightly(tmp_path):
    """The trap arm (3) fell into with internships: a row that can never satisfy
    the rule matches it forever. A Role retried yesterday waits its week."""
    path, conn = _db(tmp_path, summary="", enriched_days_ago=1)

    assert _selected(path, conn) == []


def test_a_role_with_no_description_is_never_a_summary_candidate(tmp_path):
    """Listing-only sources (Indeed) have no text to summarise. An empty summary
    there is correct and permanent, not a defect to retry — CLAUDE.md: the
    summary is an empty string, never hallucinated."""
    path, conn = _db(tmp_path, summary="", enriched_days_ago=99, description="")

    assert _selected(path, conn) == []
