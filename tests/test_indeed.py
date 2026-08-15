"""
Tests for the Indeed fallback adapter.

All HTTP is intercepted by monkeypatching _fetch_url — no Scrapling browser is
launched and no network calls are made. Fixture HTML files (with realistic embedded
mosaic JSON) live in tests/fixtures/indeed/.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from hk_jobs.adapters.indeed import (
    IndeedAdapter,
    _epoch_ms_to_dt,
    _extract_mosaic_json,
    _is_challenge,
    _is_login_wall,
    _parse_listing_json,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "indeed"


# ── fixtures & fetch mock ─────────────────────────────────────────────────────

@pytest.fixture
def page1_html():
    return (FIXTURE_DIR / "listing_page1.html").read_text()


@pytest.fixture
def page2_html():
    return (FIXTURE_DIR / "listing_page2.html").read_text()


@pytest.fixture
def adapter(page1_html, monkeypatch):
    """Single-page adapter serving page-1 fixture for every fetch."""
    monkeypatch.setattr("hk_jobs.adapters.indeed.time.sleep", lambda *a, **k: None)

    calls: list[str] = []

    def _mock_fetch_url(self, url: str) -> tuple[int, str]:
        calls.append(url)
        return 200, page1_html

    monkeypatch.setattr(IndeedAdapter, "_fetch_url", _mock_fetch_url)

    a = IndeedAdapter(
        company="DBS", company_slug="dbs", indeed_slug="Dbs-Bank", max_pages=1,
    )
    a._calls = calls
    return a


# ── _extract_mosaic_json ──────────────────────────────────────────────────────

def test_extract_mosaic_json_returns_model(page1_html):
    data = _extract_mosaic_json(page1_html)
    assert data is not None
    results = data["metaData"]["mosaicProviderJobCardsModel"]["results"]
    assert len(results) == 3


def test_extract_mosaic_json_absent_returns_none():
    assert _extract_mosaic_json("<html><body>no mosaic here</body></html>") is None


def test_extract_mosaic_json_malformed_returns_none():
    bad = 'window.mosaic.providerData["mosaic-provider-jobcards"] = {not valid json;'
    assert _extract_mosaic_json(bad) is None


def test_extract_mosaic_json_brace_match_survives_nested_braces():
    """The brace-matcher must not stop at a nested '}' inside the object."""
    blob = 'window.mosaic.providerData["mosaic-provider-jobcards"] = {"a": {"b": 1}, "c": 2};'
    data = _extract_mosaic_json(blob)
    assert data == {"a": {"b": 1}, "c": 2}


# ── _parse_listing_json ───────────────────────────────────────────────────────

def test_listing_parses_three_cards(page1_html):
    assert len(_parse_listing_json(page1_html)) == 3


def test_listing_card_fields(page1_html):
    cards = _parse_listing_json(page1_html)
    assert cards[0]["title"] == "Specialist, Know Your Customer, SME Banking"
    assert cards[0]["jobkey"] == "aaa111"
    assert cards[0]["location"] == "Hong Kong"
    assert cards[2]["location"] == "Kwun Tong, Kowloon"


def test_listing_card_company_blank_on_employer_page(page1_html):
    """Employer-scoped /cmp/ pages leave each card's company blank."""
    cards = _parse_listing_json(page1_html)
    assert all(c["company"] == "" for c in cards)


def test_listing_card_posted_at_parsed(page1_html):
    cards = _parse_listing_json(page1_html)
    assert isinstance(cards[0]["posted_at"], datetime)


def test_parse_listing_json_no_mosaic_returns_empty():
    assert _parse_listing_json("<html><body>nothing</body></html>") == []


# ── _epoch_ms_to_dt ───────────────────────────────────────────────────────────

def test_epoch_ms_to_dt_valid():
    dt = _epoch_ms_to_dt(1781413200000)
    assert dt is not None and dt.tzinfo is UTC


def test_epoch_ms_to_dt_zero_or_bad():
    assert _epoch_ms_to_dt(0) is None
    assert _epoch_ms_to_dt(None) is None
    assert _epoch_ms_to_dt("not a number") is None


# ── _is_challenge / _is_login_wall ────────────────────────────────────────────

def test_is_challenge_on_403():
    assert _is_challenge(403, "Forbidden")


def test_is_challenge_on_short_challenge_page():
    assert _is_challenge(200, "<html>Just a moment... checking your browser</html>")


def test_is_challenge_false_on_large_content_page(page1_html):
    # Real content page is huge → challenge phrases (if any) must not false-positive.
    assert not _is_challenge(200, page1_html)


def test_login_wall_detected():
    assert _is_login_wall("<html>Please verify you are human</html>")
    assert _is_login_wall("<html>Additional Verification Required</html>")


def test_login_wall_not_triggered_by_signin_link(page1_html):
    """The benign header 'Sign in' link (secure.indeed.com) must NOT read as a wall."""
    assert "secure.indeed.com" in page1_html
    assert not _is_login_wall(page1_html)


# ── full adapter fetch ────────────────────────────────────────────────────────

def test_fetch_jobs_returns_three(adapter):
    assert len(adapter.fetch_jobs()) == 3


def test_fetch_jobs_source_fields(adapter):
    for job in adapter.fetch_jobs():
        assert job.source == "indeed"
        assert job.company_slug == "dbs"
        assert job.scraped_under_slug == "dbs"


def test_fetch_jobs_company_stamped_from_config(adapter):
    """Card company is blank on employer pages → stamp the configured company name."""
    for job in adapter.fetch_jobs():
        assert job.company == "DBS"


def test_fetch_jobs_url_built_from_jobkey(adapter):
    jobs = adapter.fetch_jobs()
    assert jobs[0].url == "https://hk.indeed.com/viewjob?jk=aaa111"


def test_fetch_jobs_descriptions_empty(adapter):
    for job in adapter.fetch_jobs():
        assert job.description_raw == ""
        assert job.description_clean == ""


def test_fetch_jobs_no_detail_fetch(adapter):
    """Listing-only: exactly one URL fetched (the page-1 listing)."""
    adapter.fetch_jobs()
    assert len(adapter._calls) == 1
    assert adapter._calls[0] == "https://hk.indeed.com/cmp/Dbs-Bank/jobs"


# ── pagination & jobkey dedup ─────────────────────────────────────────────────

def test_pagination_dedups_by_jobkey(page1_html, page2_html, monkeypatch):
    """Page 2 repeats one card (ccc333) — output must contain 5 unique jobs, not 6."""
    monkeypatch.setattr("hk_jobs.adapters.indeed.time.sleep", lambda *a, **k: None)

    def _serve(self, url):
        return (200, page2_html) if "start=20" in url else (200, page1_html)

    monkeypatch.setattr(IndeedAdapter, "_fetch_url", _serve)
    a = IndeedAdapter(company="DBS", company_slug="dbs", indeed_slug="Dbs-Bank", max_pages=2)
    jobs = a.fetch_jobs()
    keys = [j.source_id for j in jobs]
    assert len(jobs) == 5
    assert len(set(keys)) == 5           # no duplicate jobkeys
    assert keys.count("ccc333") == 1     # the cross-page repeat kept exactly once


def test_pagination_second_page_uses_start_20(page1_html, page2_html, monkeypatch):
    monkeypatch.setattr("hk_jobs.adapters.indeed.time.sleep", lambda *a, **k: None)
    calls: list[str] = []

    def _serve(self, url):
        calls.append(url)
        return (200, page2_html) if "start=20" in url else (200, page1_html)

    monkeypatch.setattr(IndeedAdapter, "_fetch_url", _serve)
    a = IndeedAdapter(company="DBS", company_slug="dbs", indeed_slug="Dbs-Bank", max_pages=2)
    a.fetch_jobs()
    assert calls[1] == "https://hk.indeed.com/cmp/Dbs-Bank/jobs?start=20"


def test_pagination_stops_when_all_cards_already_seen(page1_html, monkeypatch):
    """If a page returns only jobs we've seen, pagination stops (no spin to max_pages)."""
    monkeypatch.setattr("hk_jobs.adapters.indeed.time.sleep", lambda *a, **k: None)
    calls: list[str] = []

    def _same_page(self, url):
        calls.append(url)
        return 200, page1_html  # every page identical

    monkeypatch.setattr(IndeedAdapter, "_fetch_url", _same_page)
    a = IndeedAdapter(company="DBS", company_slug="dbs", indeed_slug="Dbs-Bank", max_pages=5)
    jobs = a.fetch_jobs()
    assert len(jobs) == 3          # only the 3 unique cards
    assert len(calls) == 2         # page 1 (new) + page 2 (all seen → stop)


def test_page_url_stepping():
    a = IndeedAdapter(company="X", company_slug="x", indeed_slug="X-Co")
    assert a._page_url(1) == "https://hk.indeed.com/cmp/X-Co/jobs"
    assert a._page_url(2) == "https://hk.indeed.com/cmp/X-Co/jobs?start=20"
    assert a._page_url(3) == "https://hk.indeed.com/cmp/X-Co/jobs?start=40"


# ── anti-bot challenge & login-wall handling ──────────────────────────────────

def test_challenge_returns_empty_list(monkeypatch):
    monkeypatch.setattr("hk_jobs.adapters.indeed.time.sleep", lambda *a, **k: None)
    challenge = (FIXTURE_DIR / "challenge.html").read_text()
    monkeypatch.setattr(IndeedAdapter, "_fetch_url", lambda self, url: (200, challenge))
    a = IndeedAdapter(company="DBS", company_slug="dbs", indeed_slug="Dbs-Bank")
    assert a.fetch_jobs() == []


def test_403_returns_empty_list(monkeypatch):
    monkeypatch.setattr("hk_jobs.adapters.indeed.time.sleep", lambda *a, **k: None)
    monkeypatch.setattr(IndeedAdapter, "_fetch_url", lambda self, url: (403, "Forbidden"))
    a = IndeedAdapter(company="DBS", company_slug="dbs", indeed_slug="Dbs-Bank")
    assert a.fetch_jobs() == []


def test_login_wall_skipped_gracefully(monkeypatch):
    """A login/verify wall must yield [] and never raise — we do not cross it."""
    monkeypatch.setattr("hk_jobs.adapters.indeed.time.sleep", lambda *a, **k: None)
    wall = (FIXTURE_DIR / "login_wall.html").read_text()
    monkeypatch.setattr(IndeedAdapter, "_fetch_url", lambda self, url: (200, wall))
    a = IndeedAdapter(company="DBS", company_slug="dbs", indeed_slug="Dbs-Bank")
    assert a.fetch_jobs() == []


# ── transient-failure retry / partial results ─────────────────────────────────

def test_network_exception_is_retried_then_succeeds(monkeypatch, page1_html):
    monkeypatch.setattr("hk_jobs.adapters.indeed.time.sleep", lambda *a, **k: None)
    attempts = {"n": 0}

    def _flaky(self, url):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise TimeoutError("Page.goto: Timeout 60000ms exceeded")
        return 200, page1_html

    monkeypatch.setattr(IndeedAdapter, "_fetch_url", _flaky)
    a = IndeedAdapter(company="DBS", company_slug="dbs", indeed_slug="Dbs-Bank", max_pages=1)
    jobs = a.fetch_jobs()
    assert attempts["n"] == 2
    assert len(jobs) == 3


def test_partial_results_preserved_when_later_page_fails(monkeypatch, page1_html):
    monkeypatch.setattr("hk_jobs.adapters.indeed.time.sleep", lambda *a, **k: None)

    def _page1_ok_then_fail(self, url):
        if "start=20" in url:
            raise TimeoutError("network dropped")
        return 200, page1_html

    monkeypatch.setattr(IndeedAdapter, "_fetch_url", _page1_ok_then_fail)
    a = IndeedAdapter(company="DBS", company_slug="dbs", indeed_slug="Dbs-Bank", max_pages=3)
    assert len(a.fetch_jobs()) == 3  # page-1 results kept despite page-2 failure


# ── registry ──────────────────────────────────────────────────────────────────

def test_indeed_registered():
    from hk_jobs.adapters import ADAPTERS

    assert "indeed" in ADAPTERS
    assert ADAPTERS["indeed"] is IndeedAdapter


# ── per-company wall-clock budget ─────────────────────────────────────────────

def test_company_budget_stops_pagination_when_pages_are_slow(monkeypatch, page1_html):
    """
    A Cloudflare-blocked employer must not spend its whole pipeline slot.

    Scrapling's solver can burn 5-20 minutes on ONE page (measured in CI:
    333 s, 492 s, 671 s, 1170 s) and nothing inside it is bounded. The adapter
    can at least refuse to start further pages once the budget is spent.
    """
    monkeypatch.setattr("hk_jobs.adapters.indeed.time.sleep", lambda *a, **k: None)
    monkeypatch.setattr("hk_jobs.adapters.indeed._COMPANY_BUDGET_SECS", 100.0)

    clock = {"t": 0.0}
    monkeypatch.setattr("hk_jobs.adapters.indeed.time.monotonic", lambda: clock["t"])

    pages_served = {"n": 0}

    def _slow(self, url):
        pages_served["n"] += 1
        clock["t"] += 60.0          # each page costs 60 s of the 100 s budget
        # Fresh jobkeys every page: without this the dedup guard ends pagination
        # on its own and the test would pass even with the budget removed.
        return 200, page1_html.replace('jobkey": "', f'jobkey": "s{pages_served["n"]}_')

    monkeypatch.setattr(IndeedAdapter, "_fetch_url", _slow)
    adapter = IndeedAdapter(
        company="Goldman Sachs", company_slug="goldman-sachs",
        indeed_slug="Goldman-Sachs", max_pages=10,
    )

    adapter.fetch_jobs()

    # page 1 (t=60) then page 2 (t=120) — by page 3 the budget is spent.
    assert pages_served["n"] == 2, pages_served["n"]


def test_company_budget_does_not_stop_a_healthy_company(monkeypatch, page1_html):
    """A fast employer must still paginate normally — the budget is a backstop."""
    monkeypatch.setattr("hk_jobs.adapters.indeed.time.sleep", lambda *a, **k: None)
    monkeypatch.setattr("hk_jobs.adapters.indeed._COMPANY_BUDGET_SECS", 300.0)

    clock = {"t": 0.0}
    monkeypatch.setattr("hk_jobs.adapters.indeed.time.monotonic", lambda: clock["t"])

    served = {"n": 0}

    def _fast(self, url):
        served["n"] += 1
        clock["t"] += 2.0
        # Serve fresh jobkeys each page so dedup doesn't end pagination early
        # — this test is about the budget, not about dedup.
        return 200, page1_html.replace('jobkey": "', f'jobkey": "p{served["n"]}_')

    monkeypatch.setattr(IndeedAdapter, "_fetch_url", _fast)
    adapter = IndeedAdapter(
        company="Goldman Sachs", company_slug="goldman-sachs",
        indeed_slug="Goldman-Sachs", max_pages=4,
    )

    adapter.fetch_jobs()

    assert served["n"] == 4, "budget must not cut a healthy company short"
