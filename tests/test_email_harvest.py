"""Tests for hk_jobs/posts/email_harvest.py."""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from hk_jobs.migrations import migrate_to_phase_26, migrate_to_phase_27, migrate_to_phase_28
from hk_jobs.posts import budget
from hk_jobs.posts.email_harvest import (
    REFRESH_INTERVAL_DAYS,
    _best_email,
    run_email_harvest,
)
from hk_jobs.posts.promote import run_promotion
from hk_jobs.posts.store import PostStore, RawPost
from hk_jobs.posts.vendor_client import ApifyClient
from hk_jobs.storage import JobStore


@pytest.fixture
def db(tmp_path: Path) -> str:
    path = str(tmp_path / "test.db")
    migrate_to_phase_26(path)
    migrate_to_phase_27(path)
    migrate_to_phase_28(path)
    JobStore(path).close()
    return path


def _write_recruiters_yaml(path: Path, entries: list[dict]) -> None:
    path.write_text(yaml.dump({"recruiters": entries}), encoding="utf-8")


ONE_RECRUITER = {
    "name": "Gillian Lam", "slug": "gillian-lam", "tier": "agency_recruiter",
    "profile_url": "https://hk.linkedin.com/in/lamgillian", "enabled": True,
}

EMAIL_ITEM = {
    "id": "x", "publicIdentifier": "lamgillian",
    "emails": [{"email": "gillian.lam@selbyjennings.com", "deliverable": True, "qualityScore": 90}],
}
NO_EMAIL_ITEM = {"id": "y", "publicIdentifier": "nobody", "emails": []}


# ── _best_email ranking ──────────────────────────────────────────────────────

def test_best_email_prefers_deliverable_then_quality_score():
    item = {
        "emails": [
            {"email": "low@x.com", "deliverable": True, "qualityScore": 40},
            {"email": "undeliverable@x.com", "deliverable": False, "qualityScore": 99},
            {"email": "best@x.com", "deliverable": True, "qualityScore": 90},
        ]
    }
    assert _best_email(item) == "best@x.com"


def test_best_email_none_when_empty():
    assert _best_email({"emails": []}) is None
    assert _best_email({}) is None


# ── run_email_harvest ────────────────────────────────────────────────────────

def test_harvest_one_recruiter_success(db, tmp_path, monkeypatch):
    yaml_path = tmp_path / "recruiters.yaml"
    _write_recruiters_yaml(yaml_path, [ONE_RECRUITER])
    monkeypatch.setattr("hk_jobs.recruiters_config._DEFAULT_YAML", yaml_path)

    client = ApifyClient(api_token="fake")
    monkeypatch.setattr(
        ApifyClient, "_call_actor", lambda self, actor, payload, **kw: [EMAIL_ITEM]
    )

    summary = run_email_harvest(db, client=client)
    assert summary.harvested == 1
    assert summary.no_email_found == 0
    assert summary.cost_usd == pytest.approx(0.01)

    assert PostStore(db).all_recruiter_emails() == {"gillian-lam": "gillian.lam@selbyjennings.com"}


def test_harvest_no_email_found_still_records_fetch(db, tmp_path, monkeypatch):
    yaml_path = tmp_path / "recruiters.yaml"
    _write_recruiters_yaml(yaml_path, [ONE_RECRUITER])
    monkeypatch.setattr("hk_jobs.recruiters_config._DEFAULT_YAML", yaml_path)

    client = ApifyClient(api_token="fake")
    monkeypatch.setattr(
        ApifyClient, "_call_actor", lambda self, actor, payload, **kw: [NO_EMAIL_ITEM]
    )

    summary = run_email_harvest(db, client=client)
    assert summary.no_email_found == 1
    assert summary.harvested == 0
    # Recorded (with fetched_at set) so it isn't retried every run at $0.01 each.
    assert PostStore(db).get_email_fetched_at("gillian-lam") is not None


def test_fresh_email_is_skipped_without_calling_vendor(db, tmp_path, monkeypatch):
    yaml_path = tmp_path / "recruiters.yaml"
    _write_recruiters_yaml(yaml_path, [ONE_RECRUITER])
    monkeypatch.setattr("hk_jobs.recruiters_config._DEFAULT_YAML", yaml_path)
    PostStore(db).record_email("gillian-lam", "already@known.com")

    client = ApifyClient(api_token="fake")
    calls = {"n": 0}

    def _mock_call_actor(self, actor, payload, **kw):
        calls["n"] += 1
        return [EMAIL_ITEM]

    monkeypatch.setattr(ApifyClient, "_call_actor", _mock_call_actor)

    summary = run_email_harvest(db, client=client)
    assert summary.skipped_fresh == 1
    assert calls["n"] == 0
    assert PostStore(db).all_recruiter_emails() == {"gillian-lam": "already@known.com"}


def test_stale_email_is_refetched(db, tmp_path, monkeypatch):
    yaml_path = tmp_path / "recruiters.yaml"
    _write_recruiters_yaml(yaml_path, [ONE_RECRUITER])
    monkeypatch.setattr("hk_jobs.recruiters_config._DEFAULT_YAML", yaml_path)
    PostStore(db).record_email("gillian-lam", "old@known.com")
    stale = (datetime.now(UTC) - timedelta(days=REFRESH_INTERVAL_DAYS + 1)).isoformat()
    conn = sqlite3.connect(db)
    with conn:
        conn.execute(
            "UPDATE recruiter_fetch_state SET email_fetched_at = ? WHERE slug = 'gillian-lam'",
            (stale,),
        )
    conn.close()

    client = ApifyClient(api_token="fake")
    monkeypatch.setattr(
        ApifyClient, "_call_actor", lambda self, actor, payload, **kw: [EMAIL_ITEM]
    )

    summary = run_email_harvest(db, client=client)
    assert summary.harvested == 1
    assert PostStore(db).all_recruiter_emails()["gillian-lam"] == "gillian.lam@selbyjennings.com"


def test_force_refresh_ignores_freshness(db, tmp_path, monkeypatch):
    yaml_path = tmp_path / "recruiters.yaml"
    _write_recruiters_yaml(yaml_path, [ONE_RECRUITER])
    monkeypatch.setattr("hk_jobs.recruiters_config._DEFAULT_YAML", yaml_path)
    PostStore(db).record_email("gillian-lam", "already@known.com")

    client = ApifyClient(api_token="fake")
    monkeypatch.setattr(
        ApifyClient, "_call_actor", lambda self, actor, payload, **kw: [EMAIL_ITEM]
    )

    summary = run_email_harvest(db, force=True, client=client)
    assert summary.harvested == 1
    assert summary.skipped_fresh == 0


def test_one_bad_recruiter_does_not_stop_others(db, tmp_path, monkeypatch):
    yaml_path = tmp_path / "recruiters.yaml"
    _write_recruiters_yaml(yaml_path, [
        {"name": "Broken", "slug": "broken", "tier": "agency_recruiter",
         "profile_url": "https://x/broken", "enabled": True},
        ONE_RECRUITER,
    ])
    monkeypatch.setattr("hk_jobs.recruiters_config._DEFAULT_YAML", yaml_path)

    client = ApifyClient(api_token="fake")

    def _mock_call_actor(self, actor, payload, **kw):
        if "broken" in payload["queries"][0]:
            raise RuntimeError("simulated vendor failure")
        return [EMAIL_ITEM]

    monkeypatch.setattr(ApifyClient, "_call_actor", _mock_call_actor)
    summary = run_email_harvest(db, client=client)
    assert summary.failed == 1
    assert summary.harvested == 1


def test_budget_blocked_stops_harvest(db, tmp_path, monkeypatch):
    yaml_path = tmp_path / "recruiters.yaml"
    _write_recruiters_yaml(yaml_path, [ONE_RECRUITER])
    monkeypatch.setattr("hk_jobs.recruiters_config._DEFAULT_YAML", yaml_path)
    budget.record_cost(db, vendor="apify", actor="x", run_kind="watchlist", items=1, cost_usd=30.0)

    client = ApifyClient(api_token="fake")
    monkeypatch.setattr(
        ApifyClient, "_call_actor", lambda self, actor, payload, **kw: [EMAIL_ITEM]
    )

    summary = run_email_harvest(db, client=client)
    assert summary.budget_blocked is True
    assert summary.harvested == 0


# ── backfill of already-promoted jobs ───────────────────────────────────────

def test_backfills_email_into_already_promoted_jobs(db, tmp_path, monkeypatch):
    yaml_path = tmp_path / "recruiters.yaml"
    _write_recruiters_yaml(yaml_path, [ONE_RECRUITER])
    monkeypatch.setattr("hk_jobs.recruiters_config._DEFAULT_YAML", yaml_path)

    # Promote a post BEFORE any email is known (mirrors real timeline: LP-3 ran first).
    PostStore(db).upsert_posts([RawPost(
        post_urn="urn-1", recruiter_slug="gillian-lam", source_run="watchlist",
        author_name="Gillian Lam", author_profile_url="https://linkedin.com/in/gillian",
        post_text="Hiring an Analyst", post_url="https://linkedin.com/posts/1",
        posted_at="2026-07-01T00:00:00+00:00", engagement_likes=1, engagement_comments=0,
        vendor_payload={"id": "urn-1"},
    )])
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

    with JobStore(db) as store:
        row = store._conn.execute(
            "SELECT board_signals FROM jobs WHERE source='linkedin_posts'"
        ).fetchone()
    assert json.loads(row["board_signals"])["recruiter_email"] is None

    # Now harvest the email — the already-promoted job should get backfilled.
    client = ApifyClient(api_token="fake")
    monkeypatch.setattr(
        ApifyClient, "_call_actor", lambda self, actor, payload, **kw: [EMAIL_ITEM]
    )
    summary = run_email_harvest(db, client=client)
    assert summary.backfilled_jobs == 1

    with JobStore(db) as store:
        row = store._conn.execute(
            "SELECT board_signals FROM jobs WHERE source='linkedin_posts'"
        ).fetchone()
    assert json.loads(row["board_signals"])["recruiter_email"] == "gillian.lam@selbyjennings.com"


def test_backfill_is_idempotent_second_run_updates_zero(db, tmp_path, monkeypatch):
    yaml_path = tmp_path / "recruiters.yaml"
    _write_recruiters_yaml(yaml_path, [ONE_RECRUITER])
    monkeypatch.setattr("hk_jobs.recruiters_config._DEFAULT_YAML", yaml_path)
    PostStore(db).upsert_posts([RawPost(
        post_urn="urn-1", recruiter_slug="gillian-lam", source_run="watchlist",
        author_name="Gillian Lam", author_profile_url="https://linkedin.com/in/gillian",
        post_text="Hiring an Analyst", post_url="https://linkedin.com/posts/1",
        posted_at="2026-07-01T00:00:00+00:00", engagement_likes=1, engagement_comments=0,
        vendor_payload={"id": "urn-1"},
    )])
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

    client = ApifyClient(api_token="fake")
    monkeypatch.setattr(
        ApifyClient, "_call_actor", lambda self, actor, payload, **kw: [EMAIL_ITEM]
    )
    run_email_harvest(db, client=client)

    # Second run: email already fresh (skipped) AND already backfilled -> 0 updates.
    summary2 = run_email_harvest(db, client=client)
    assert summary2.skipped_fresh == 1
    assert summary2.backfilled_jobs == 0
