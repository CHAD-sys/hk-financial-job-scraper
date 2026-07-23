"""Tests for hk_jobs/posts/pilot_report.py."""

from pathlib import Path

import pytest

from hk_jobs.migrations import migrate_to_phase_26, migrate_to_phase_27, migrate_to_phase_28
from hk_jobs.posts import budget
from hk_jobs.posts.pilot_report import format_report, generate_pilot_report
from hk_jobs.posts.promote import run_promotion
from hk_jobs.posts.store import PostStore, RawPost
from hk_jobs.storage import JobStore


@pytest.fixture
def db(tmp_path: Path) -> str:
    path = str(tmp_path / "test.db")
    migrate_to_phase_26(path)
    migrate_to_phase_27(path)
    migrate_to_phase_28(path)
    JobStore(path).close()
    return path


def test_report_on_empty_db_has_zeroed_numbers(db):
    r = generate_pilot_report(db)
    assert r.promoted_total == 0
    assert r.apify_cost_to_date == 0
    assert r.deepseek_calls_this_window == 0
    assert r.spot_check_sample == []
    text = format_report(r)
    assert "Secret Market" in text


def test_report_reflects_real_promoted_data_and_cost(db, monkeypatch):
    PostStore(db).upsert_posts([RawPost(
        post_urn="urn-1", recruiter_slug="gillian-lam", source_run="watchlist",
        author_name="Gillian Lam", author_profile_url="https://linkedin.com/in/gillian",
        post_text="Hiring an Analyst", post_url="https://linkedin.com/posts/1",
        posted_at="2026-07-01T00:00:00+00:00", engagement_likes=5, engagement_comments=1,
        vendor_payload={"id": "urn-1"},
    )])
    budget.record_cost(db, vendor="apify", actor="x", run_kind="watchlist", items=1, cost_usd=0.5)

    from hk_jobs.posts.extractor import ExtractionResult
    monkeypatch.setattr(
        "hk_jobs.posts.promote.extract_post",
        lambda text: ExtractionResult(
            is_job_post=True, confidence=0.9, title="Analyst", employer_named=False,
            employer_hint="a bank", location="Hong Kong", hk_plausible=True,
            seniority="mid", skills=[], raw={},
        ),
    )
    run_promotion(db)

    r = generate_pilot_report(db)
    assert r.promoted_total == 1
    assert r.truly_hidden == 1
    assert r.apify_cost_to_date == 0.5
    assert r.deepseek_calls_this_window == 1
    assert len(r.spot_check_sample) == 1
    assert r.spot_check_sample[0]["title"] == "Analyst"

    text = format_report(r)
    assert "Analyst" in text
    assert "$0.5" in text
