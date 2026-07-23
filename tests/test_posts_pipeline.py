"""
Tests for hk_jobs/posts/store.py, budget.py, and fetcher.py.

No real Apify calls: ApifyClient is passed in with its _call_actor seam
monkeypatched, same pattern as test_vendor_client.py.
"""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from hk_jobs.migrations import migrate_to_phase_26
from hk_jobs.posts import budget
from hk_jobs.posts.fetcher import (
    _discovery_slug,
    _parse_vendor_item,
    _resolve_since,
    fetch_discovery,
    fetch_watchlist,
)
from hk_jobs.posts.store import CATCHUP_FLOOR_HOURS, PostStore, RawPost
from hk_jobs.posts.vendor_client import ApifyClient

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "apify"


@pytest.fixture
def db(tmp_path: Path) -> str:
    path = str(tmp_path / "test.db")
    migrate_to_phase_26(path)
    return path


@pytest.fixture
def profile_posts_items():
    return json.loads((FIXTURE_DIR / "profile_posts_sample.json").read_text())


def _raw_post(urn="urn-1", slug="jane-doe", **overrides):
    defaults = dict(
        post_urn=urn, recruiter_slug=slug, source_run="watchlist",
        author_name="Jane Doe", author_profile_url="https://linkedin.com/in/jane",
        post_text="Hiring an Analyst", post_url="https://linkedin.com/posts/1",
        posted_at="2026-07-01T00:00:00Z", engagement_likes=1, engagement_comments=0,
        vendor_payload={"id": urn},
    )
    defaults.update(overrides)
    return RawPost(**defaults)


# ── PostStore ────────────────────────────────────────────────────────────────

def test_upsert_new_posts(db):
    store = PostStore(db)
    inserted, updated = store.upsert_posts([_raw_post("urn-1"), _raw_post("urn-2")])
    assert (inserted, updated) == (2, 0)

    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT post_urn, extraction_status FROM linkedin_posts ORDER BY post_urn"
    ).fetchall()
    assert rows == [("urn-1", "pending"), ("urn-2", "pending")]


def test_upsert_repeat_post_refreshes_engagement_only(db):
    store = PostStore(db)
    store.upsert_posts([_raw_post("urn-1", engagement_likes=1, post_text="original text")])

    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE linkedin_posts SET extraction_status = 'promoted' WHERE post_urn = 'urn-1'"
    )
    conn.commit()
    conn.close()

    inserted, updated = store.upsert_posts(
        [_raw_post(
            "urn-1", engagement_likes=99,
            post_text="a different text — should NOT overwrite",
        )]
    )
    assert (inserted, updated) == (0, 1)

    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT engagement_likes, post_text, extraction_status "
        "FROM linkedin_posts WHERE post_urn = 'urn-1'"
    ).fetchone()
    assert row[0] == 99  # engagement refreshed
    assert row[1] == "original text"  # text untouched
    assert row[2] == "promoted"  # extraction_status not reset to pending


def test_recruiter_fetch_state_round_trip(db):
    store = PostStore(db)
    assert store.get_last_fetched_at("jane-doe") is None

    store.record_fetch_result("jane-doe", status="ok")
    ts = store.get_last_fetched_at("jane-doe")
    assert ts is not None

    # A failed attempt does NOT advance the watermark.
    store.record_fetch_result("jane-doe", status="error", error="boom")
    assert store.get_last_fetched_at("jane-doe") == ts


# ── budget ───────────────────────────────────────────────────────────────────

def test_budget_status_under_threshold(db):
    status = budget.check_budget(db)
    assert status.month_to_date_usd == 0
    assert not status.warn
    assert not status.blocked


def test_budget_warn_and_block_thresholds(db):
    now = datetime.now(UTC)
    budget.record_cost(db, vendor="apify", actor="x", run_kind="watchlist", items=1, cost_usd=26.0)
    status = budget.check_budget(db, as_of=now)
    assert status.warn
    assert not status.blocked

    budget.record_cost(db, vendor="apify", actor="x", run_kind="watchlist", items=1, cost_usd=5.0)
    status = budget.check_budget(db, as_of=now)
    assert status.blocked


def test_budget_only_counts_current_month(db):
    conn = sqlite3.connect(db)
    with conn:
        conn.execute(
            "INSERT INTO vendor_costs (logged_at, vendor, actor, run_kind, items, cost_usd) "
            "VALUES (?, 'apify', 'x', 'watchlist', 1, 100.0)",
            ((datetime.now(UTC) - timedelta(days=45)).isoformat(),),
        )
    conn.close()
    status = budget.check_budget(db)
    assert status.month_to_date_usd == 0  # last month's spend doesn't carry over


# ── fetcher: parsing ─────────────────────────────────────────────────────────

def test_parse_vendor_item(profile_posts_items):
    item = profile_posts_items[0]
    post = _parse_vendor_item(item, recruiter_slug="gillian-lam", source_run="watchlist")
    assert post is not None
    assert post.post_urn == item["id"]
    assert post.recruiter_slug == "gillian-lam"
    assert post.author_name == "Gillian Lam"
    assert post.post_text == item["content"]
    assert post.engagement_likes == item["engagement"]["likes"]


def test_parse_vendor_item_missing_id_returns_none():
    item = {"content": "no id here"}
    assert _parse_vendor_item(item, recruiter_slug="x", source_run="watchlist") is None


def test_discovery_slug_is_prefixed_and_never_collides_with_watchlist():
    item = {"author": {"publicIdentifier": "pinesearch"}}
    slug = _discovery_slug(item)
    assert slug == "disc-pinesearch"
    assert slug.startswith("disc-")


# ── fetcher: since-date resolution (cron slippage) ──────────────────────────

def test_resolve_since_no_prior_fetch_uses_catchup_floor():
    since = _resolve_since(None)
    floor = (datetime.now(UTC) - timedelta(hours=CATCHUP_FLOOR_HOURS)).date().isoformat()
    assert since == floor


def test_resolve_since_recent_fetch_uses_that_watermark():
    recent = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    since = _resolve_since(recent)
    assert since == datetime.now(UTC).date().isoformat()


def test_resolve_since_stale_fetch_capped_at_catchup_floor():
    """A last_fetched_at from a multi-day-old outage shouldn't ask for full history."""
    stale = (datetime.now(UTC) - timedelta(days=10)).isoformat()
    since = _resolve_since(stale)
    floor = (datetime.now(UTC) - timedelta(hours=CATCHUP_FLOOR_HOURS)).date().isoformat()
    assert since == floor


# ── fetcher: watchlist orchestration ────────────────────────────────────────

def _write_recruiters_yaml(path: Path, entries: list[dict]) -> None:
    path.write_text(yaml.dump({"recruiters": entries}), encoding="utf-8")


def test_fetch_watchlist_one_recruiter_success(db, tmp_path, monkeypatch, profile_posts_items):
    yaml_path = tmp_path / "recruiters.yaml"
    _write_recruiters_yaml(yaml_path, [{
        "name": "Gillian Lam", "slug": "gillian-lam", "tier": "agency_recruiter",
        "agency": "Selby Jennings", "profile_url": "https://hk.linkedin.com/in/lamgillian",
        "enabled": True, "added_by": "roster",
    }])
    monkeypatch.setattr("hk_jobs.recruiters_config._DEFAULT_YAML", yaml_path)

    client = ApifyClient(api_token="fake")
    monkeypatch.setattr(
        ApifyClient, "_call_actor", lambda self, actor, payload, **kw: profile_posts_items
    )

    summary = fetch_watchlist(db, client=client)
    assert summary.recruiters_polled == 1
    assert summary.recruiters_failed == 0
    assert summary.posts_inserted == len(profile_posts_items)
    assert summary.cost_usd == pytest.approx(len(profile_posts_items) * 2 / 1000)

    store = PostStore(db)
    assert store.get_last_fetched_at("gillian-lam") is not None


def test_fetch_watchlist_one_recruiter_failure_does_not_stop_others(
    db, tmp_path, monkeypatch, profile_posts_items
):
    yaml_path = tmp_path / "recruiters.yaml"
    _write_recruiters_yaml(yaml_path, [
        {"name": "Broken", "slug": "broken", "tier": "agency_recruiter",
         "profile_url": "https://x/broken", "enabled": True},
        {"name": "Gillian Lam", "slug": "gillian-lam", "tier": "agency_recruiter",
         "profile_url": "https://x/gillian", "enabled": True},
    ])
    monkeypatch.setattr("hk_jobs.recruiters_config._DEFAULT_YAML", yaml_path)

    client = ApifyClient(api_token="fake")

    def _mock_call_actor(self, actor, payload, **kw):
        if "broken" in payload["targetUrls"][0]:
            raise RuntimeError("simulated vendor failure")
        return profile_posts_items

    monkeypatch.setattr(ApifyClient, "_call_actor", _mock_call_actor)

    summary = fetch_watchlist(db, client=client)
    assert summary.recruiters_polled == 1
    assert summary.recruiters_failed == 1
    assert summary.posts_inserted == len(profile_posts_items)

    store = PostStore(db)
    assert store.get_last_fetched_at("broken") is None  # never succeeded
    assert store.get_last_fetched_at("gillian-lam") is not None


def test_fetch_watchlist_stops_when_budget_blocked(db, tmp_path, monkeypatch, profile_posts_items):
    yaml_path = tmp_path / "recruiters.yaml"
    _write_recruiters_yaml(yaml_path, [
        {"name": "A", "slug": "a", "tier": "agency_recruiter",
         "profile_url": "https://x/a", "enabled": True},
        {"name": "B", "slug": "b", "tier": "agency_recruiter",
         "profile_url": "https://x/b", "enabled": True},
    ])
    monkeypatch.setattr("hk_jobs.recruiters_config._DEFAULT_YAML", yaml_path)
    budget.record_cost(db, vendor="apify", actor="x", run_kind="watchlist", items=1, cost_usd=30.0)

    client = ApifyClient(api_token="fake")
    monkeypatch.setattr(
        ApifyClient, "_call_actor", lambda self, actor, payload, **kw: profile_posts_items
    )

    summary = fetch_watchlist(db, client=client)
    assert summary.budget_blocked is True
    assert summary.recruiters_polled == 0  # blocked before the first call


def test_fetch_discovery_runs_seed_queries(db, monkeypatch, tmp_path):
    search_items = json.loads((FIXTURE_DIR / "post_search_sample.json").read_text())
    client = ApifyClient(api_token="fake")
    monkeypatch.setattr(ApifyClient, "_call_actor", lambda self, actor, payload, **kw: search_items)

    summary = fetch_discovery(
        db, queries=["hiring Hong Kong compliance private bank"], client=client
    )
    assert summary.recruiters_polled == 1  # one query run
    assert summary.posts_inserted == len(search_items)

    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT DISTINCT source_run FROM linkedin_posts").fetchall()
    assert rows == [("discovery",)]


def test_fetch_watchlist_backfill_omits_since_date(db, tmp_path, monkeypatch, profile_posts_items):
    """
    Regression test for the bug where EVERY fetch (including a recruiter's
    very first) was silently scoped to the 48h catch-up floor, making
    max_posts never the real constraint on volume. backfill=True must pass
    since_date=None so the vendor call is unrestricted by date.
    """
    yaml_path = tmp_path / "recruiters.yaml"
    _write_recruiters_yaml(yaml_path, [{
        "name": "Gillian Lam", "slug": "gillian-lam", "tier": "agency_recruiter",
        "profile_url": "https://hk.linkedin.com/in/lamgillian", "enabled": True,
    }])
    monkeypatch.setattr("hk_jobs.recruiters_config._DEFAULT_YAML", yaml_path)

    calls = []
    client = ApifyClient(api_token="fake")

    def _mock_call_actor(self, actor, payload, **kw):
        calls.append(payload)
        return profile_posts_items

    monkeypatch.setattr(ApifyClient, "_call_actor", _mock_call_actor)

    summary = fetch_watchlist(db, client=client, backfill=True)
    assert summary.recruiters_polled == 1
    assert "postedLimitDate" not in calls[0]


def test_fetch_watchlist_normal_mode_still_scopes_by_date(
    db, tmp_path, monkeypatch, profile_posts_items
):
    """Confirms backfill=False (the default, used by --fetch-posts) is unchanged."""
    yaml_path = tmp_path / "recruiters.yaml"
    _write_recruiters_yaml(yaml_path, [{
        "name": "Gillian Lam", "slug": "gillian-lam", "tier": "agency_recruiter",
        "profile_url": "https://hk.linkedin.com/in/lamgillian", "enabled": True,
    }])
    monkeypatch.setattr("hk_jobs.recruiters_config._DEFAULT_YAML", yaml_path)

    calls = []
    client = ApifyClient(api_token="fake")

    def _mock_call_actor(self, actor, payload, **kw):
        calls.append(payload)
        return profile_posts_items

    monkeypatch.setattr(ApifyClient, "_call_actor", _mock_call_actor)

    fetch_watchlist(db, client=client)  # backfill defaults to False
    assert "postedLimitDate" in calls[0]
