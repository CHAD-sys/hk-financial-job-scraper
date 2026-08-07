"""
What EnrichmentPipeline stores, per source.

The case that matters here: a recruiter post (`source = 'linkedin_posts'`) used
to have its salary estimate thrown away between the model answering and the row
being written — the model produced a figure, and the pipeline nulled it. That is
reversed (owner decision, 2026-08-05), and this pins the reversal, because the
old behaviour had no test at all: it was a four-line branch that any refactor
could have reintroduced or removed without a single assertion moving.
"""

import sqlite3
from pathlib import Path

import pytest

from hk_jobs import enrichment as enrichment_module
from hk_jobs.enrichment import EnrichmentPipeline

_SCHEMA = """
CREATE TABLE jobs (
    source TEXT, source_id TEXT, title TEXT, company TEXT, company_slug TEXT,
    source_tier TEXT, description_clean TEXT, category TEXT,
    is_active INTEGER DEFAULT 1, fetched_at TEXT DEFAULT '2026-08-05T00:00:00'
);
CREATE TABLE job_enrichments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT, source_id TEXT, seniority TEXT,
    years_experience_required INTEGER, required_skills TEXT, remote_type TEXT,
    salary_hkd_min INTEGER, salary_hkd_max INTEGER, job_category TEXT,
    enriched_at TEXT, model_used TEXT,
    salary_estimated_min INTEGER, salary_estimated_max INTEGER,
    salary_estimated_confidence TEXT, description_summary TEXT, title_en TEXT,
    prompt_version TEXT, salary_tier TEXT, salary_role TEXT, manually_edited_at TEXT,
    UNIQUE (source, source_id)
);
"""

# A plausible mid-office answer: high enough to survive the magnitude fix, and
# carrying the tier/role/seniority the clamp needs to keep it.
_MODEL_ANSWER = {
    "title_en": "Compliance Manager",
    "seniority": "mid",
    "years_experience": 6,
    "skills": ["Compliance", "AML"],
    "remote_type": "on-site",
    "salary_hkd_min": None,
    "salary_hkd_max": None,
    "job_category": "Operations",
    "salary_estimated_min": 480_000,
    "salary_estimated_max": 720_000,
    "salary_estimated_confidence": "medium",
    "salary_tier": "middle_office",
    "salary_role": None,
    "description_summary": "A compliance role.",
}


class _StubEnricher:
    """Stands in for DeepSeek: same answer for every job, no network."""

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def _enrich_with_retry(self, _title, _company, _description):
        return dict(_MODEL_ANSWER)


@pytest.fixture
def db(tmp_path: Path, monkeypatch) -> Path:
    path = tmp_path / "jobs.db"
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    conn.executemany(
        "INSERT INTO jobs (source, source_id, title, company, company_slug, "
        "source_tier, description_clean) VALUES (?,?,?,?,?,?,?)",
        [
            ("linkedin_posts", "P-1", "Compliance Manager", "Confidential",
             "confidential", "social", ""),
            ("jobsdb", "J-1", "Compliance Manager", "HSBC",
             "hsbc", "mainstream", "A compliance role."),
        ],
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(enrichment_module, "DeepSeekEnricher", _StubEnricher)
    return path


def _estimate(db_path: Path, source: str) -> tuple:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT salary_estimated_min, salary_estimated_max, "
            "salary_estimated_confidence FROM job_enrichments WHERE source = ?",
            (source,),
        ).fetchone()
    finally:
        conn.close()


def test_recruiter_post_keeps_its_salary_estimate(db: Path):
    # The regression this file exists for. Goes red against the old branch,
    # which set est_min/est_max/confidence to None for this source alone.
    EnrichmentPipeline(db_path=str(db), api_key="test").run()

    est_min, est_max, confidence = _estimate(db, "linkedin_posts")
    assert est_min is not None, "recruiter post stored no salary estimate"
    assert est_max is not None
    assert confidence == "medium"


def test_recruiter_post_is_estimated_like_any_other_source(db: Path):
    # Not merely non-null: the SAME model answer must survive to the same
    # numbers it would for a job board, so the reversal did not leave recruiter
    # posts on some quietly different path through salary.finalise().
    EnrichmentPipeline(db_path=str(db), api_key="test").run()

    assert _estimate(db, "linkedin_posts") == _estimate(db, "jobsdb")


def test_manually_edited_row_survives_even_a_forced_re_enrich(db: Path):
    """
    Ultimate Admin's correction (webapp/backend/job_edit.py, manually_edited_at)
    must not be the thing `--re-enrich` erases. `--re-enrich` exists to force
    everything ELSE to be reconsidered — a human's decision on this one row is
    not "everything else."
    """
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO job_enrichments (source, source_id, salary_estimated_min, "
        "salary_estimated_max, salary_estimated_confidence, manually_edited_at) "
        "VALUES ('jobsdb', 'J-1', 55000, 65000, 'high', '2026-08-06T00:00:00+00:00')"
    )
    conn.commit()
    conn.close()

    EnrichmentPipeline(db_path=str(db), api_key="test").run(re_enrich=True)

    assert _estimate(db, "jobsdb") == (55000, 65000, "high")
