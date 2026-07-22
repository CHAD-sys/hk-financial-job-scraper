"""
Tests for hk_jobs/posts/promote.py and hk_jobs/posts/metrics.py.

extract_post is monkeypatched at the promote module's import site — no real
DeepSeek call is made.
"""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from hk_jobs.migrations import migrate_to_phase_26, migrate_to_phase_27
from hk_jobs.posts.extractor import ExtractionResult
from hk_jobs.posts.metrics import compute_metrics
from hk_jobs.posts.promote import run_promotion
from hk_jobs.posts.store import PostStore, RawPost
from hk_jobs.storage import JobStore


@pytest.fixture
def db(tmp_path: Path) -> str:
    path = str(tmp_path / "test.db")
    migrate_to_phase_26(path)
    migrate_to_phase_27(path)
    return path


def _seed_post(
    db_path: str, urn="urn-1", slug="gillian-lam", text="Hiring an Analyst", **overrides
):
    defaults = dict(
        post_urn=urn, recruiter_slug=slug, source_run="watchlist",
        author_name="Gillian Lam", author_profile_url="https://linkedin.com/in/gillian",
        post_text=text, post_url="https://linkedin.com/posts/1",
        posted_at="2026-07-01T00:00:00+00:00", engagement_likes=5, engagement_comments=1,
        vendor_payload={"id": urn},
    )
    defaults.update(overrides)
    PostStore(db_path).upsert_posts([RawPost(**defaults)])


def _good_result(**overrides):
    defaults = dict(
        is_job_post=True, confidence=0.9, title="Assistant Relationship Manager",
        employer_named=False, employer_hint="international private bank",
        location="Hong Kong", hk_plausible=True, seniority="mid",
        salary_min=None, salary_max=None, salary_currency=None,
        skills=["private banking"], raw={"is_job_post": True},
    )
    defaults.update(overrides)
    return ExtractionResult(**defaults)


# ── promotion gate ───────────────────────────────────────────────────────────

def test_promotes_post_that_passes_gate(db, monkeypatch):
    _seed_post(db)
    monkeypatch.setattr("hk_jobs.posts.promote.extract_post", lambda text: _good_result())

    summary = run_promotion(db)
    assert summary.promoted == 1
    assert summary.rejected == 0

    with JobStore(db) as store:
        rows = store._conn.execute("SELECT * FROM jobs WHERE source='linkedin_posts'").fetchall()
    assert len(rows) == 1
    assert rows[0]["title"] == "Assistant Relationship Manager"


def test_rejects_non_job_post(db, monkeypatch):
    _seed_post(db)
    monkeypatch.setattr(
        "hk_jobs.posts.promote.extract_post", lambda text: _good_result(is_job_post=False)
    )
    summary = run_promotion(db)
    assert summary.promoted == 0
    assert summary.rejected == 1

    conn = sqlite3.connect(db)
    status = conn.execute(
        "SELECT extraction_status FROM linkedin_posts WHERE post_urn='urn-1'"
    ).fetchone()[0]
    assert status == "rejected"


def test_rejects_missing_title(db, monkeypatch):
    _seed_post(db)
    monkeypatch.setattr("hk_jobs.posts.promote.extract_post", lambda text: _good_result(title=None))
    summary = run_promotion(db)
    assert summary.promoted == 0
    assert summary.rejected == 1


def test_rejects_not_hk_plausible(db, monkeypatch):
    _seed_post(db)
    monkeypatch.setattr(
        "hk_jobs.posts.promote.extract_post", lambda text: _good_result(hk_plausible=False)
    )
    summary = run_promotion(db)
    assert summary.promoted == 0
    assert summary.rejected == 1


def test_empty_post_text_is_rejected_immediately_not_retried_forever(db, monkeypatch):
    _seed_post(db, text="")
    calls = {"n": 0}
    monkeypatch.setattr(
        "hk_jobs.posts.promote.extract_post",
        lambda text: (calls.__setitem__("n", calls["n"] + 1), None)[1],
    )
    summary = run_promotion(db)
    assert summary.rejected == 1
    assert summary.failed == 0
    assert calls["n"] == 0  # never even called the extractor

    conn = sqlite3.connect(db)
    status = conn.execute(
        "SELECT extraction_status FROM linkedin_posts WHERE post_urn='urn-1'"
    ).fetchone()[0]
    assert status == "rejected"


def test_failed_extraction_counts_as_failed_not_rejected(db, monkeypatch):
    _seed_post(db)
    monkeypatch.setattr("hk_jobs.posts.promote.extract_post", lambda text: None)
    summary = run_promotion(db)
    assert summary.failed == 1
    assert summary.promoted == 0
    assert summary.rejected == 0


def test_one_bad_post_does_not_stop_the_rest(db, monkeypatch):
    _seed_post(db, urn="urn-bad", text="bad")
    _seed_post(db, urn="urn-good", slug="grace-su", text="good")

    def _mock_extract(text):
        if text == "bad":
            raise RuntimeError("simulated extraction crash")
        return _good_result()

    monkeypatch.setattr("hk_jobs.posts.promote.extract_post", _mock_extract)
    summary = run_promotion(db)
    assert summary.promoted == 1
    assert summary.failed == 1


# ── confidential employer construction ──────────────────────────────────────

def test_confidential_employer_when_not_named(db, monkeypatch):
    _seed_post(db, slug="gillian-lam")
    monkeypatch.setattr(
        "hk_jobs.posts.promote.extract_post",
        lambda text: _good_result(employer_named=False, employer_hint="a private bank"),
    )
    run_promotion(db)

    with JobStore(db) as store:
        row = store._conn.execute("SELECT * FROM jobs WHERE source='linkedin_posts'").fetchone()
    assert row["company"] == "Confidential via Gillian Lam"
    assert row["company_slug"] == "confidential-gillian-lam"


def test_named_employer_uses_real_company_and_slug(db, monkeypatch):
    _seed_post(db)
    monkeypatch.setattr(
        "hk_jobs.posts.promote.extract_post",
        lambda text: _good_result(employer_named=True, employer_hint="HSBC"),
    )
    run_promotion(db)

    with JobStore(db) as store:
        row = store._conn.execute("SELECT * FROM jobs WHERE source='linkedin_posts'").fetchone()
    assert row["company"] == "HSBC"
    assert row["company_slug"] == "hsbc"


def test_source_tier_is_social(db, monkeypatch):
    _seed_post(db)
    monkeypatch.setattr("hk_jobs.posts.promote.extract_post", lambda text: _good_result())
    run_promotion(db)
    with JobStore(db) as store:
        row = store._conn.execute(
            "SELECT source_tier FROM jobs WHERE source='linkedin_posts'"
        ).fetchone()
    assert row["source_tier"] == "social"


# ── hidden flag via reconcile_cross_posted ──────────────────────────────────

def test_confidential_post_never_cross_posted(db, monkeypatch):
    """A confidential post can never cluster with a real board listing -> stays 'hidden'."""
    _seed_post(db)
    monkeypatch.setattr(
        "hk_jobs.posts.promote.extract_post",
        lambda text: _good_result(employer_named=False),
    )
    run_promotion(db)

    metrics = compute_metrics(db)
    assert metrics.promoted_active == 1
    assert metrics.truly_hidden == 1
    assert metrics.pct_truly_hidden == 100.0


def test_named_employer_matching_existing_board_job_is_cross_posted(db, monkeypatch):
    """Same company_slug + fuzzy-matching title as an existing board job -> cross_posted."""
    with JobStore(db) as store:
        from hk_jobs.schema import Job
        store.upsert_many([Job(
            source="workday", source_id="W-1", company="HSBC", company_slug="hsbc",
            url="https://hsbc.com/jobs/1", title="Relationship Manager",
            locations=["Hong Kong"], fetched_at=datetime.now(UTC),
        )])

    _seed_post(db)
    monkeypatch.setattr(
        "hk_jobs.posts.promote.extract_post",
        lambda text: _good_result(
            employer_named=True, employer_hint="HSBC", title="Relationship Manager"
        ),
    )
    run_promotion(db)

    metrics = compute_metrics(db)
    assert metrics.promoted_active == 1
    assert metrics.truly_hidden == 0  # matched the board listing -> not hidden


# ── metrics on empty state ──────────────────────────────────────────────────

def test_metrics_on_empty_db(db):
    JobStore(db).close()  # jobs table is created here in production (migrate_to_phase_11)
    m = compute_metrics(db)
    assert m.promoted_active == 0
    assert m.pct_truly_hidden == 0.0
    assert m.pct_high_confidence == 0.0
