"""
Tests for the JobsDB fallback adapter.

All HTTP is intercepted; no network calls are made.
Fixture HTML files live in tests/fixtures/jobsdb/.
"""

from pathlib import Path

import httpx
import pytest

from hk_jobs.adapters.jobsdb import (
    JobsDBAdapter,
    _extract_source_id,
    _map_employment_type,
    _parse_detail_html,
    _parse_listing_html,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "jobsdb"


# ── fixtures & mock transport ─────────────────────────────────────────────────

@pytest.fixture
def listing_html():
    return (FIXTURE_DIR / "listing.html").read_text()


@pytest.fixture
def detail_html():
    return (FIXTURE_DIR / "detail.html").read_text()


class _MockTransport(httpx.BaseTransport):
    """Returns listing HTML for the company URL, detail HTML for anything else."""

    def __init__(self, listing_html: str, detail_html: str) -> None:
        self.listing_html = listing_html
        self.detail_html = detail_html
        self.calls: list[str] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.calls.append(url)
        # Company listing page — identified by the "-jobs" slug pattern
        if url.endswith("-jobs") or "-jobs?" in url:
            return httpx.Response(
                200, text=self.listing_html, headers={"content-type": "text/html"}
            )
        # Everything else (detail pages)
        return httpx.Response(200, text=self.detail_html, headers={"content-type": "text/html"})


@pytest.fixture
def adapter(listing_html, detail_html, monkeypatch):
    transport = _MockTransport(listing_html, detail_html)
    monkeypatch.setattr("hk_jobs.adapters.jobsdb._REQUEST_SLEEP", 0)

    def _mock_client(self, timeout=20.0):
        return httpx.Client(transport=transport, follow_redirects=True)

    monkeypatch.setattr(JobsDBAdapter, "_client", _mock_client)
    a = JobsDBAdapter(
        company="Bank of China (HK)",
        company_slug="bank-of-china-hk",
        jobsdb_company_slug="bank-of-china-hong-kong",
        max_pages=1,
    )
    a._transport = transport
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


# ── _parse_detail_html ────────────────────────────────────────────────────────

def test_detail_extracts_description(detail_html):
    raw, location, emp_type = _parse_detail_html(detail_html)
    assert "<p>" in raw or "<ul>" in raw
    assert "Credit Risk Analyst" in raw


def test_detail_extracts_location(detail_html):
    _, location, _ = _parse_detail_html(detail_html)
    assert location == "Hong Kong"


def test_detail_extracts_employment_type(detail_html):
    _, _, emp_type = _parse_detail_html(detail_html)
    assert emp_type == "Full time"


def test_detail_decodes_html_entities(detail_html):
    raw, _, _ = _parse_detail_html(detail_html)
    from hk_jobs.adapters.workday import _strip_html
    clean = _strip_html(raw)
    assert "&" in clean            # &amp; decoded
    assert "’" in clean       # &rsquo; → right single quotation mark
    assert "–" in clean            # &ndash; decoded


# ── _extract_source_id ────────────────────────────────────────────────────────

def test_extract_source_id_numeric_suffix():
    url = "https://hk.jobsdb.com/hk/en/job/credit-risk-analyst-100003456789"
    assert _extract_source_id(url) == "100003456789"


def test_extract_source_id_no_number_falls_back():
    url = "https://hk.jobsdb.com/hk/en/job/some-role"
    assert _extract_source_id(url) == url


# ── _map_employment_type ──────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Full time", "full-time"),
        ("Full-time", "full-time"),
        ("Part time", "part-time"),
        ("Contract", "contract"),
        ("Internship", "internship"),
        ("Unknown", None),
    ],
)
def test_map_employment_type(raw, expected):
    assert _map_employment_type(raw) == expected


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


def test_fetch_jobs_has_description(adapter):
    jobs = adapter.fetch_jobs()
    for job in jobs:
        assert job.description_raw != ""
        assert "<" not in job.description_clean
        assert job.description_clean != ""


def test_fetch_jobs_employment_type_mapped(adapter):
    jobs = adapter.fetch_jobs()
    # detail fixture says "Full time" → should map to "full-time"
    for job in jobs:
        assert job.employment_type == "full-time"


def test_fetch_jobs_location_from_detail(adapter):
    jobs = adapter.fetch_jobs()
    # detail fixture has location "Hong Kong"
    assert jobs[0].locations == ["Hong Kong"]


def test_fetch_jobs_source_id_extracted(adapter):
    jobs = adapter.fetch_jobs()
    first = jobs[0]
    # URL ends in a numeric ID
    assert first.source_id.isdigit()


def test_request_count_listing_plus_details(adapter):
    adapter.fetch_jobs()
    # 1 listing GET + 3 detail GETs = 4 total
    assert len(adapter._transport.calls) == 4


# ── anti-bot challenge handling ───────────────────────────────────────────────

def test_403_returns_empty_list(monkeypatch):
    class _BlockTransport(httpx.BaseTransport):
        def handle_request(self, request):
            return httpx.Response(403, text="Forbidden")

    monkeypatch.setattr("hk_jobs.adapters.jobsdb._REQUEST_SLEEP", 0)

    def _mock_client(self, timeout=20.0):
        return httpx.Client(transport=_BlockTransport(), follow_redirects=True)

    monkeypatch.setattr(JobsDBAdapter, "_client", _mock_client)
    adapter = JobsDBAdapter(
        company="BOCHK",
        company_slug="bochk",
        jobsdb_company_slug="bank-of-china-hong-kong",
    )
    jobs = adapter.fetch_jobs()
    assert jobs == []


def test_captcha_body_returns_empty_list(monkeypatch):
    class _CaptchaTransport(httpx.BaseTransport):
        def handle_request(self, request):
            return httpx.Response(
                200,
                text="<html><body>Please complete the captcha to continue.</body></html>",
                headers={"content-type": "text/html"},
            )

    monkeypatch.setattr("hk_jobs.adapters.jobsdb._REQUEST_SLEEP", 0)

    def _mock_client(self, timeout=20.0):
        return httpx.Client(transport=_CaptchaTransport(), follow_redirects=True)

    monkeypatch.setattr(JobsDBAdapter, "_client", _mock_client)
    adapter = JobsDBAdapter(
        company="BOCHK",
        company_slug="bochk",
        jobsdb_company_slug="bank-of-china-hong-kong",
    )
    jobs = adapter.fetch_jobs()
    assert jobs == []


# ── registry ──────────────────────────────────────────────────────────────────

def test_jobsdb_registered():
    from hk_jobs.adapters import ADAPTERS

    assert "jobsdb" in ADAPTERS
    assert ADAPTERS["jobsdb"] is JobsDBAdapter
