"""Tests for hk_jobs/schema.py — the canonical Job model."""

import tempfile
from datetime import UTC, datetime

import pytest

from hk_jobs.schema import Job, jobs_from_jsonl, jobs_to_jsonl


def _make_job(**overrides) -> Job:
    """Return a minimal valid Job, with optional field overrides."""
    defaults = dict(
        source="workday",
        source_id="REQ-001",
        company="HSBC",
        company_slug="hsbc",
        url="https://example.com/jobs/1",
        title="Software Engineer",
        locations=["Hong Kong"],
    )
    defaults.update(overrides)
    return Job(**defaults)


# ── Defaults ──────────────────────────────────────────────────────────────────

def test_defaults():
    job = _make_job()
    assert job.description_raw == ""
    assert job.description_clean == ""
    assert job.locations == ["Hong Kong"]
    assert job.remote_type is None
    assert job.department is None
    assert job.seniority is None
    assert job.employment_type is None
    assert job.salary_min is None
    assert job.salary_max is None
    assert job.salary_currency is None
    assert job.skills_required == []
    assert job.skills_preferred == []
    assert job.years_experience_min is None
    assert job.posted_at is None
    assert job.is_active is True
    # fetched_at is auto-set to a recent UTC datetime
    assert isinstance(job.fetched_at, datetime)
    assert job.fetched_at.tzinfo is not None  # timezone-aware


def test_optional_fields_accepted():
    job = _make_job(
        seniority="senior",
        employment_type="full-time",
        remote_type="hybrid",
        salary_min=80000,
        salary_max=120000,
        salary_currency="HKD",
        skills_required=["Python", "SQL"],
        skills_preferred=["Spark"],
        years_experience_min=5,
    )
    assert job.seniority == "senior"
    assert job.employment_type == "full-time"
    assert job.remote_type == "hybrid"
    assert job.salary_min == 80000
    assert job.salary_currency == "HKD"
    assert job.skills_required == ["Python", "SQL"]
    assert job.years_experience_min == 5


def test_invalid_seniority_rejected():
    with pytest.raises(Exception):
        _make_job(seniority="god-tier")


def test_invalid_employment_type_rejected():
    with pytest.raises(Exception):
        _make_job(employment_type="gig")


# ── dedup_hash ────────────────────────────────────────────────────────────────

def test_dedup_hash_is_stable():
    """Same inputs must always produce the same hash (deterministic)."""
    job_a = _make_job()
    job_b = _make_job()
    assert job_a.dedup_hash() == job_b.dedup_hash()


def test_dedup_hash_differs_on_title():
    job_a = _make_job(title="Software Engineer")
    job_b = _make_job(title="Product Manager")
    assert job_a.dedup_hash() != job_b.dedup_hash()


def test_dedup_hash_case_insensitive_title():
    """Title casing must not affect the hash."""
    job_a = _make_job(title="Software Engineer")
    job_b = _make_job(title="SOFTWARE ENGINEER")
    assert job_a.dedup_hash() == job_b.dedup_hash()


def test_dedup_hash_differs_on_company():
    job_a = _make_job(company_slug="hsbc")
    job_b = _make_job(company_slug="aia")
    assert job_a.dedup_hash() != job_b.dedup_hash()


def test_dedup_hash_no_locations():
    """Jobs with no locations listed must still return a valid hash."""
    job = _make_job(locations=[])
    h = job.dedup_hash()
    assert isinstance(h, str) and len(h) == 12


def test_dedup_hash_length():
    assert len(_make_job().dedup_hash()) == 12


# ── jobs_to_jsonl / jobs_from_jsonl round-trip ────────────────────────────────

def test_jsonl_round_trip():
    jobs = [
        _make_job(source_id="REQ-001", title="Analyst"),
        _make_job(source_id="REQ-002", title="Developer", skills_required=["Go"]),
    ]

    with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
        path = f.name

    jobs_to_jsonl(jobs, path)
    loaded = jobs_from_jsonl(path)

    assert len(loaded) == 2
    assert loaded[0].source_id == "REQ-001"
    assert loaded[1].title == "Developer"
    assert loaded[1].skills_required == ["Go"]


def test_jsonl_datetimes_survive_round_trip():
    """Datetimes must come back as datetime objects (not strings) after JSONL round-trip."""
    fixed_time = datetime(2024, 6, 1, 9, 0, 0, tzinfo=UTC)
    job = _make_job(posted_at=fixed_time, fetched_at=fixed_time)

    with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
        path = f.name

    jobs_to_jsonl([job], path)
    loaded = jobs_from_jsonl(path)

    assert loaded[0].posted_at == fixed_time
    assert loaded[0].fetched_at == fixed_time


def test_jsonl_empty_list():
    with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
        path = f.name

    jobs_to_jsonl([], path)
    assert jobs_from_jsonl(path) == []
