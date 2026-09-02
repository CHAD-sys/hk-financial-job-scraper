"""
ADR 0036 — WE NEVER DESTROY AN EXISTING SALARY ESTIMATE.

On 2026-09-02 a backlog run re-priced the board under the coordinate-only gate
and **blanked the salary on 336 Roles that already had a perfectly good one**
(+385 gained, -336 lost, net +49 for $13.42). Every one of those had been
priced by an earlier prompt version; the model simply declined to name a
`(tier, role, grade)` coordinate on the re-run, and the write path replaced a
real figure with NULL without a murmur.

An enrichment run may replace a figure with another figure. It may fill a
blank. It may NEVER turn a figure into a blank. This file pins that at the
write path, where it cannot be argued around by a change of selection or
prompt.

The sibling half of the rule — an unpriced Role is always a candidate again,
regardless of prompt_version — lives in test_prompt_version_grandfathering.py.
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
    fetched_at TEXT DEFAULT '2026-09-02T00:00:00'
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

#: The model comes back with a usable answer but NO salary at all — no
#: coordinate, no band. Exactly the shape that blanked 336 Roles.
_ANSWER_WITH_NO_SALARY = {
    "title_en": "Analyst", "seniority": "mid", "years_experience": 4,
    "skills": ["Excel"], "remote_type": "on-site",
    "salary_hkd_min": None, "salary_hkd_max": None, "job_category": "Operations",
    "salary_estimated_min": None, "salary_estimated_max": None,
    "salary_estimated_confidence": None,
    "salary_tier": None, "salary_role": None, "salary_grade": None,
    "description_summary": "A freshly written summary.",
}


class _StubEnricher:
    answer: dict = _ANSWER_WITH_NO_SALARY

    def __init__(self, *_a, **_k) -> None:
        pass

    def _enrich_with_retry(self, *_a, **_k):
        return dict(type(self).answer)


@pytest.fixture
def db(tmp_path: Path, monkeypatch) -> Path:
    path = tmp_path / "jobs.db"
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    posted = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    conn.execute(
        "INSERT INTO jobs (source, source_id, title, company, company_slug, source_tier, "
        "description_clean, posted_at) VALUES ('jobsdb','PRICED','Compliance Manager',"
        "'A Bank','a-bank','mainstream','A real description.',?)",
        (posted,),
    )
    # Already priced by an earlier run, on an older prompt version.
    conn.execute(
        "INSERT INTO job_enrichments (source, source_id, salary_estimated_min, "
        "salary_estimated_max, salary_estimated_confidence, salary_tier, salary_role, "
        "salary_grade, description_summary, prompt_version) "
        "VALUES ('jobsdb','PRICED',35000,48000,'medium','middle_office','compliance',"
        "'Manager','An older summary.','some-older-version')"
    )
    conn.commit()
    conn.close()
    _StubEnricher.answer = _ANSWER_WITH_NO_SALARY
    monkeypatch.setattr(enrichment_module, "DeepSeekEnricher", _StubEnricher)
    return path


def _row(db_path: Path) -> sqlite3.Row:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            "SELECT * FROM job_enrichments WHERE source_id = 'PRICED'"
        ).fetchone()
    finally:
        conn.close()


def test_a_run_that_cannot_price_a_role_leaves_the_existing_estimate_intact(db: Path):
    """THE rule. RED before ADR 0036: this stored NULL over 35,000-48,000."""
    EnrichmentPipeline(db_path=str(db), api_key="test").run()
    row = _row(db)
    assert row["salary_estimated_min"] == 35_000
    assert row["salary_estimated_max"] == 48_000


def test_the_kept_estimate_keeps_the_coordinate_that_produced_it(db: Path):
    """min/max/confidence/tier/role/grade move as one block — a kept figure must
    not end up described by a coordinate that did not produce it."""
    EnrichmentPipeline(db_path=str(db), api_key="test").run()
    row = _row(db)
    assert row["salary_tier"] == "middle_office"
    assert row["salary_role"] == "compliance"
    assert row["salary_grade"] == "Manager"
    assert row["salary_estimated_confidence"] == "medium"


def test_the_rest_of_the_enrichment_is_still_refreshed(db: Path):
    """Preserving the salary must not freeze the whole row — the summary,
    seniority and prompt_version are the reason the run touched it at all."""
    EnrichmentPipeline(db_path=str(db), api_key="test").run()
    row = _row(db)
    assert row["description_summary"] == "A freshly written summary."
    assert row["seniority"] == "mid"
    assert row["prompt_version"] != "some-older-version"


def test_a_figure_may_still_be_replaced_by_another_figure(db: Path):
    """Not a freeze: a run that CAN price the Role still updates it. Otherwise a
    genuine recalibration could never land."""
    _StubEnricher.answer = {
        **_ANSWER_WITH_NO_SALARY,
        "salary_estimated_min": 42_000, "salary_estimated_max": 55_000,
        "salary_estimated_confidence": "medium",
        "salary_tier": "middle_office", "salary_role": "compliance",
        "salary_grade": "Senior Manager",
    }
    EnrichmentPipeline(db_path=str(db), api_key="test").run()
    row = _row(db)
    assert row["salary_estimated_min"] is not None
    assert row["salary_estimated_min"] != 35_000 or row["salary_estimated_max"] != 48_000
    assert row["salary_grade"] == "Senior Manager"


def test_a_role_that_never_had_an_estimate_simply_stays_blank(db: Path):
    """The guard preserves; it does not invent."""
    conn = sqlite3.connect(db)
    posted = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    conn.execute(
        "INSERT INTO jobs (source, source_id, title, company, company_slug, source_tier, "
        "description_clean, posted_at) VALUES ('jobsdb','BLANK','Analyst','A Bank',"
        "'a-bank','mainstream','A real description.',?)",
        (posted,),
    )
    conn.commit()
    conn.close()

    EnrichmentPipeline(db_path=str(db), api_key="test").run()
    conn = sqlite3.connect(db)
    try:
        got = conn.execute(
            "SELECT salary_estimated_min FROM job_enrichments WHERE source_id='BLANK'"
        ).fetchone()
    finally:
        conn.close()
    assert got is not None and got[0] is None
