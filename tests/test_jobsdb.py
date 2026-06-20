"""
Tests for the JobsDB fallback adapter.

All HTTP is intercepted via monkeypatching _fetch_url — no Scrapling
browser is launched and no network calls are made.
Fixture HTML files live in tests/fixtures/jobsdb/.
"""

from pathlib import Path

import pytest

from hk_jobs.adapters.jobsdb import (
    JobsDBAdapter,
    _extract_source_id,
    _parse_listing_date,
    _parse_listing_html,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "jobsdb"


# ── fixtures & fetch mock ─────────────────────────────────────────────────────

@pytest.fixture
def listing_html():
    return (FIXTURE_DIR / "listing.html").read_text()


@pytest.fixture
def adapter(listing_html, monkeypatch):
    # Neutralise all delays (page gaps + retry back-offs) so tests run instantly.
    monkeypatch.setattr("hk_jobs.adapters.jobsdb.time.sleep", lambda *a, **k: None)

    calls: list[str] = []

    def _mock_fetch_url(self, url: str) -> tuple[int, str]:
        calls.append(url)
        return 200, listing_html

    monkeypatch.setattr(JobsDBAdapter, "_fetch_url", _mock_fetch_url)

    a = JobsDBAdapter(
        company="Bank of China (HK)",
        company_slug="bank-of-china-hk",
        jobsdb_slug="bank-of-china-hong-kong",
        max_pages=1,
    )
    a._calls = calls
    return a


# ── _parse_listing_html ───────────────────────────────────────────────────────

def test_listing_parses_three_cards(listing_html):
    cards = _parse_listing_html(listing_html)
    assert len(cards) == 3


def test_listing_card_title(listing_html):
    cards = _parse_listing_html(listing_html)
    assert cards[0]["title"] == "Credit Risk Analyst"
    assert cards[1]["title"] == "Relationship Manager, Corporate Banking"


def test_listing_card_url_is_absolute(listing_html):
    cards = _parse_listing_html(listing_html)
    for card in cards:
        assert card["url"].startswith("https://hk.jobsdb.com")


def test_listing_card_location(listing_html):
    cards = _parse_listing_html(listing_html)
    assert cards[0]["location"] == "Hong Kong"
    assert cards[1]["location"] == "Kowloon"


def test_listing_card_teaser(listing_html):
    cards = _parse_listing_html(listing_html)
    assert "credit" in cards[0]["teaser"].lower()


# ── _parse_listing_date ───────────────────────────────────────────────────────

def test_parse_listing_date_today():
    from datetime import UTC, datetime
    result = _parse_listing_date("Posted today")
    assert result is not None
    assert abs((result - datetime.now(UTC)).total_seconds()) < 5


def test_parse_listing_date_days_ago():
    from datetime import UTC, datetime, timedelta
    result = _parse_listing_date("Posted 3 days ago")
    expected = datetime.now(UTC) - timedelta(days=3)
    assert result is not None
    assert abs((result - expected).total_seconds()) < 5


def test_parse_listing_date_hours_ago():
    from datetime import UTC, datetime, timedelta
    result = _parse_listing_date("Posted 2 hours ago")
    expected = datetime.now(UTC) - timedelta(hours=2)
    assert result is not None
    assert abs((result - expected).total_seconds()) < 5


def test_parse_listing_date_empty():
    assert _parse_listing_date("") is None


def test_parse_listing_date_unrecognised():
    assert _parse_listing_date("Be an early applicant") is None


# ── _extract_source_id ────────────────────────────────────────────────────────

def test_extract_source_id_modern_url():
    # Modern format: /job/NUMERIC_ID?type=standard&...
    url = "https://hk.jobsdb.com/job/92249354?type=standard&ref=search-standalone"
    assert _extract_source_id(url) == "92249354"


def test_extract_source_id_legacy_suffix():
    url = "https://hk.jobsdb.com/hk/en/job/credit-risk-analyst-100003456789"
    assert _extract_source_id(url) == "100003456789"


def test_extract_source_id_no_number_falls_back():
    url = "https://hk.jobsdb.com/hk/en/job/some-role"
    assert _extract_source_id(url) == url


# ── full adapter fetch ────────────────────────────────────────────────────────

def test_fetch_jobs_returns_three(adapter):
    jobs = adapter.fetch_jobs()
    assert len(jobs) == 3


def test_fetch_jobs_source_fields(adapter):
    jobs = adapter.fetch_jobs()
    for job in jobs:
        assert job.source == "jobsdb"
        assert job.company == "Bank of China (HK)"
        assert job.company_slug == "bank-of-china-hk"


def test_fetch_jobs_titles(adapter):
    jobs = adapter.fetch_jobs()
    titles = {j.title for j in jobs}
    assert "Credit Risk Analyst" in titles


def test_fetch_jobs_location(adapter):
    jobs = adapter.fetch_jobs()
    assert jobs[0].locations == ["Hong Kong"]


def test_fetch_jobs_source_id_extracted(adapter):
    jobs = adapter.fetch_jobs()
    assert jobs[0].source_id.isdigit()


def test_fetch_jobs_no_detail_fetch(adapter):
    """Listing-only: only 1 URL should be fetched (the listing page)."""
    adapter.fetch_jobs()
    assert len(adapter._calls) == 1


def test_fetch_jobs_descriptions_empty(adapter):
    """Without detail pages, descriptions are empty strings — expected."""
    jobs = adapter.fetch_jobs()
    for job in jobs:
        assert job.description_raw == ""
        assert job.description_clean == ""


# ── anti-bot challenge handling ───────────────────────────────────────────────

def test_403_returns_empty_list(monkeypatch):
    # Neutralise all delays (page gaps + retry back-offs) so tests run instantly.
    monkeypatch.setattr("hk_jobs.adapters.jobsdb.time.sleep", lambda *a, **k: None)

    def _blocked(self, url):
        return 403, "Forbidden"

    monkeypatch.setattr(JobsDBAdapter, "_fetch_url", _blocked)
    adapter = JobsDBAdapter(
        company="BOCHK", company_slug="bochk", jobsdb_slug="bank-of-china-hong-kong",
    )
    assert adapter.fetch_jobs() == []


def test_captcha_body_returns_empty_list(monkeypatch):
    # Neutralise all delays (page gaps + retry back-offs) so tests run instantly.
    monkeypatch.setattr("hk_jobs.adapters.jobsdb.time.sleep", lambda *a, **k: None)

    def _captcha(self, url):
        # Short page containing challenge signal → triggers _is_challenge
        return 200, "<html><body>Please complete the captcha to continue.</body></html>"

    monkeypatch.setattr(JobsDBAdapter, "_fetch_url", _captcha)
    adapter = JobsDBAdapter(
        company="BOCHK", company_slug="bochk", jobsdb_slug="bank-of-china-hong-kong",
    )
    assert adapter.fetch_jobs() == []


# ── transient-failure retry / partial results ─────────────────────────────────

def test_network_exception_is_retried_then_succeeds(monkeypatch, listing_html):
    """A network blip on the first attempt should be retried, not fatal."""
    monkeypatch.setattr("hk_jobs.adapters.jobsdb.time.sleep", lambda *a, **k: None)

    attempts = {"n": 0}

    def _flaky(self, url):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise TimeoutError("Page.goto: Timeout 60000ms exceeded")
        return 200, listing_html

    monkeypatch.setattr(JobsDBAdapter, "_fetch_url", _flaky)
    adapter = JobsDBAdapter(
        company="BOCHK", company_slug="bochk", jobsdb_slug="bank-of-china-hong-kong",
        max_pages=1,
    )
    jobs = adapter.fetch_jobs()
    assert attempts["n"] == 2          # retried once
    assert len(jobs) == 3              # then parsed the fixture successfully


def test_partial_results_preserved_when_later_page_fails(monkeypatch, listing_html):
    """If page 2 keeps failing, page-1 jobs must still be returned."""
    monkeypatch.setattr("hk_jobs.adapters.jobsdb.time.sleep", lambda *a, **k: None)

    def _page1_ok_then_fail(self, url):
        if "page=2" in url:
            raise TimeoutError("network dropped")
        return 200, listing_html

    monkeypatch.setattr(JobsDBAdapter, "_fetch_url", _page1_ok_then_fail)
    adapter = JobsDBAdapter(
        company="BOCHK", company_slug="bochk", jobsdb_slug="bank-of-china-hong-kong",
        max_pages=3,
    )
    jobs = adapter.fetch_jobs()
    assert len(jobs) == 3              # page-1 results kept despite page-2 failure


# ── registry ──────────────────────────────────────────────────────────────────

def test_jobsdb_registered():
    from hk_jobs.adapters import ADAPTERS

    assert "jobsdb" in ADAPTERS
    assert ADAPTERS["jobsdb"] is JobsDBAdapter
