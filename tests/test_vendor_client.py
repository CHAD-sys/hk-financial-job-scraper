"""
Tests for hk_jobs/posts/vendor_client.py.

_call_actor is the single mockable seam (same pattern as
LinkedInAdapter._fetch_url — see tests/test_linkedin.py) — no real network
call is ever made here.
"""

import json
from pathlib import Path

import httpx
import pytest

from hk_jobs.posts.vendor_client import (
    EMAIL_SEARCH_COST_PER_PROFILE_USD,
    POST_SEARCH_ACTOR,
    PROFILE_POSTS_ACTOR,
    PROFILE_SCRAPER_ACTOR,
    ApifyAuthError,
    ApifyClient,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "apify"


@pytest.fixture
def profile_posts_items():
    return json.loads((FIXTURE_DIR / "profile_posts_sample.json").read_text())


@pytest.fixture
def profile_scraper_email_items():
    return json.loads((FIXTURE_DIR / "profile_scraper_email_sample.json").read_text())


@pytest.fixture
def post_search_items():
    return json.loads((FIXTURE_DIR / "post_search_sample.json").read_text())


@pytest.fixture
def client():
    return ApifyClient(api_token="fake-token-for-tests")


def test_missing_token_raises_auth_error(monkeypatch):
    monkeypatch.delenv("APIFY_API_TOKEN", raising=False)
    with pytest.raises(ApifyAuthError):
        ApifyClient()


def test_fetch_profile_posts_returns_items(client, profile_posts_items, monkeypatch):
    calls = []

    def _mock_call_actor(self, actor, payload, *, max_items=None):
        calls.append((actor, payload))
        return profile_posts_items

    monkeypatch.setattr(ApifyClient, "_call_actor", _mock_call_actor)
    result = client.fetch_profile_posts(
        "https://hk.linkedin.com/in/lamgillian", since_date="2026-07-01"
    )

    assert result.actor == PROFILE_POSTS_ACTOR
    assert len(result.items) == len(profile_posts_items)
    assert calls[0][0] == PROFILE_POSTS_ACTOR
    assert calls[0][1]["targetUrls"] == ["https://hk.linkedin.com/in/lamgillian"]
    assert calls[0][1]["postedLimitDate"] == "2026-07-01"


def test_fetch_profile_posts_cost(client, profile_posts_items, monkeypatch):
    monkeypatch.setattr(
        ApifyClient, "_call_actor", lambda self, actor, payload, **kw: profile_posts_items
    )
    result = client.fetch_profile_posts("https://x")
    assert result.cost_usd == pytest.approx(len(profile_posts_items) * 2 / 1000)


def test_search_posts_uses_search_queries_field_not_queries(client, post_search_items, monkeypatch):
    """
    Regression test for the LP-0 bake-off gotcha: the actor's input field is
    `searchQueries`, not `queries` — the wrong name silently returns 0 results
    with no error, so this must never regress.
    """
    calls = []

    def _mock_call_actor(self, actor, payload, *, max_items=None):
        calls.append(payload)
        return post_search_items

    monkeypatch.setattr(ApifyClient, "_call_actor", _mock_call_actor)
    result = client.search_posts("hiring Hong Kong compliance private bank")

    assert result.actor == POST_SEARCH_ACTOR
    assert "searchQueries" in calls[0]
    assert "queries" not in calls[0]
    assert calls[0]["searchQueries"] == ["hiring Hong Kong compliance private bank"]


def test_call_actor_retries_transient_then_succeeds(client, monkeypatch):
    import hk_jobs.http_utils as http_utils
    monkeypatch.setattr(http_utils.time, "sleep", lambda *a, **k: None)

    attempts = {"n": 0}

    class _FakeResponse:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return [{"id": "1"}]

    def _mock_post(url, params, json, timeout):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise httpx.TimeoutException("timed out")
        return _FakeResponse()

    monkeypatch.setattr("hk_jobs.posts.vendor_client.httpx.post", _mock_post)
    items = client._call_actor(PROFILE_POSTS_ACTOR, {"targetUrls": ["https://x"]})
    assert attempts["n"] == 2
    assert items == [{"id": "1"}]


def test_call_actor_does_not_retry_clean_4xx(client, monkeypatch):
    attempts = {"n": 0}

    class _FakeResponse:
        status_code = 400

        def raise_for_status(self):
            raise httpx.HTTPStatusError("bad request", request=None, response=self)

        def json(self):
            return []

    def _mock_post(url, params, json, timeout):
        attempts["n"] += 1
        return _FakeResponse()

    monkeypatch.setattr("hk_jobs.posts.vendor_client.httpx.post", _mock_post)
    with pytest.raises(httpx.HTTPStatusError):
        client._call_actor(PROFILE_POSTS_ACTOR, {"targetUrls": ["https://x"]})
    assert attempts["n"] == 1  # not retried


def test_call_actor_raises_auth_error_on_401(client, monkeypatch):
    class _FakeResponse:
        status_code = 401

        def raise_for_status(self):
            pass

        def json(self):
            return []

    monkeypatch.setattr(
        "hk_jobs.posts.vendor_client.httpx.post",
        lambda url, params, json, timeout: _FakeResponse(),
    )
    with pytest.raises(ApifyAuthError):
        client._call_actor(PROFILE_POSTS_ACTOR, {"targetUrls": ["https://x"]})


def test_fetch_profile_email_uses_queries_field_and_email_search_mode(
    client, profile_scraper_email_items, monkeypatch
):
    """
    Regression test: this actor's profile-URL field is `queries`, NOT
    `targetUrls` (the profile-posts actor's field) — and profileScraperMode
    must be the exact email-search string or it silently runs the cheaper
    no-email mode. Both confirmed live 2026-07-22.
    """
    calls = []

    def _mock_call_actor(self, actor, payload, *, max_items=None):
        calls.append((actor, payload))
        return profile_scraper_email_items

    monkeypatch.setattr(ApifyClient, "_call_actor", _mock_call_actor)
    result = client.fetch_profile_email("https://hk.linkedin.com/in/lamgillian")

    assert result.actor == PROFILE_SCRAPER_ACTOR
    assert calls[0][0] == PROFILE_SCRAPER_ACTOR
    assert calls[0][1]["queries"] == ["https://hk.linkedin.com/in/lamgillian"]
    assert "targetUrls" not in calls[0][1]
    assert calls[0][1]["profileScraperMode"] == "Profile details + email search ($10 per 1k)"


def test_fetch_profile_email_cost_uses_email_search_rate_not_post_rate(
    client, profile_scraper_email_items, monkeypatch
):
    """$10/1k email rate differs from the $2/1k post rate — must not be conflated."""
    monkeypatch.setattr(
        ApifyClient, "_call_actor",
        lambda self, actor, payload, **kw: profile_scraper_email_items,
    )
    result = client.fetch_profile_email("https://x")
    expected = len(profile_scraper_email_items) * EMAIL_SEARCH_COST_PER_PROFILE_USD
    assert result.cost_usd == pytest.approx(expected)
    assert result.cost_usd == pytest.approx(0.01)  # 1 item at $10/1000
