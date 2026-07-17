"""
Tests for the LinkedIn guest-jobs fallback adapter.

All HTTP is intercepted by monkeypatching _fetch_url — no network calls are made.
Fixture HTML fragments (guest-search card lists) live in tests/fixtures/linkedin/.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from hk_jobs.adapters.linkedin import (
    LinkedInAdapter,
    _is_authwall,
    _parse_cards,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "linkedin"


# ── fixtures & fetch mock ─────────────────────────────────────────────────────

@pytest.fixture
def page1_html():
    return (FIXTURE_DIR / "listing_page1.html").read_text()


@pytest.fixture
def page2_html():
    return (FIXTURE_DIR / "listing_page2.html").read_text()


@pytest.fixture
def adapter(page1_html, monkeypatch):
    """Single-page adapter serving the page-1 fixture for every fetch."""
    monkeypatch.setattr("hk_jobs.adapters.linkedin.time.sleep", lambda *a, **k: None)

    calls: list[str] = []

    def _mock_fetch_url(self, url: str) -> tuple[int, str]:
        calls.append(url)
        return 200, page1_html

    monkeypatch.setattr(LinkedInAdapter, "_fetch_url", _mock_fetch_url)

    a = LinkedInAdapter(
        company="Goldman Sachs", company_slug="goldman-sachs",
        linkedin_company_id="1382", max_pages=1,
    )
    a._calls = calls
    return a


# ── _parse_cards ──────────────────────────────────────────────────────────────

def test_parse_cards_returns_three(page1_html):
    assert len(_parse_cards(page1_html)) == 3


def test_parse_card_fields(page1_html):
    cards = _parse_cards(page1_html)
    assert cards[0]["job_id"] == "111"
    assert cards[0]["title"] == "Vice President, Risk"
    assert cards[0]["company"] == "Goldman Sachs"
    assert cards[0]["location"] == "Hong Kong"
    assert cards[1]["location"] == "Kowloon, Hong Kong SAR"


def test_parse_card_url_stripped_of_tracking(page1_html):
    cards = _parse_cards(page1_html)
    # page1 card 0 href carries ?refId=...&trackingId=... — must be stripped.
    assert cards[0]["url"] == "https://www.linkedin.com/jobs/view/vice-president-risk-at-goldman-sachs-111"


def test_parse_card_posted_at(page1_html):
    cards = _parse_cards(page1_html)
    assert isinstance(cards[0]["posted_at"], datetime)
    assert cards[0]["posted_at"].tzinfo is UTC
    # Third card has no <time> element → posted_at is None, not an error.
    assert cards[2]["posted_at"] is None


def test_parse_cards_job_id_from_link_when_urn_absent():
    """Fallback: extract the numeric id from the /jobs/view/ link if urn is missing."""
    html = (
        '<div class="base-card">'
        '<a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/analyst-role-987654?x=1"></a>'
        '<h3 class="base-search-card__title">Analyst</h3>'
        '</div>'
    )
    cards = _parse_cards(html)
    assert len(cards) == 1
    assert cards[0]["job_id"] == "987654"


def test_parse_cards_skips_card_without_id():
    html = '<div class="base-card"><h3 class="base-search-card__title">No id here</h3></div>'
    assert _parse_cards(html) == []


def test_parse_cards_empty_html():
    assert _parse_cards("<html><body>nothing</body></html>") == []


# ── _is_authwall ──────────────────────────────────────────────────────────────

def test_authwall_on_block_statuses():
    assert _is_authwall(999, "")   # LinkedIn's automated-traffic block code
    assert _is_authwall(429, "")
    assert _is_authwall(403, "")


def test_authwall_on_signin_text():
    wall = (FIXTURE_DIR / "authwall.html").read_text()
    assert _is_authwall(200, wall)


def test_authwall_false_on_content(page1_html):
    assert not _is_authwall(200, page1_html)


# ── full adapter fetch ────────────────────────────────────────────────────────

def test_fetch_jobs_returns_three(adapter):
    assert len(adapter.fetch_jobs()) == 3


def test_fetch_jobs_source_fields(adapter):
    for job in adapter.fetch_jobs():
        assert job.source == "linkedin"
        assert job.company == "Goldman Sachs"
        assert job.company_slug == "goldman-sachs"
        assert job.scraped_under_slug == "goldman-sachs"


def test_fetch_jobs_url_and_ids(adapter):
    jobs = adapter.fetch_jobs()
    assert jobs[0].source_id == "111"
    assert jobs[0].url == "https://www.linkedin.com/jobs/view/vice-president-risk-at-goldman-sachs-111"


def test_fetch_jobs_descriptions_empty(adapter):
    for job in adapter.fetch_jobs():
        assert job.description_raw == ""
        assert job.description_clean == ""


def test_fetch_jobs_listing_only_single_call(adapter):
    adapter.fetch_jobs()
    assert len(adapter._calls) == 1
    assert "f_C=1382" in adapter._calls[0]
    assert "start=0" in adapter._calls[0]


# ── pagination & dedup ────────────────────────────────────────────────────────

def test_pagination_dedups_by_job_id(page1_html, page2_html, monkeypatch):
    """Page 2 repeats card 333 — output must be 4 unique jobs, not 5."""
    monkeypatch.setattr("hk_jobs.adapters.linkedin.time.sleep", lambda *a, **k: None)

    def _serve(self, url):
        return (200, page2_html) if "start=10" in url else (200, page1_html)

    monkeypatch.setattr(LinkedInAdapter, "_fetch_url", _serve)
    a = LinkedInAdapter(company="Goldman Sachs", company_slug="goldman-sachs",
                        linkedin_company_id="1382", max_pages=2)
    jobs = a.fetch_jobs()
    ids = [j.source_id for j in jobs]
    assert len(jobs) == 4
    assert len(set(ids)) == 4
    assert ids.count("333") == 1


def test_pagination_second_page_uses_start_10(page1_html, page2_html, monkeypatch):
    monkeypatch.setattr("hk_jobs.adapters.linkedin.time.sleep", lambda *a, **k: None)
    calls: list[str] = []

    def _serve(self, url):
        calls.append(url)
        return (200, page2_html) if "start=10" in url else (200, page1_html)

    monkeypatch.setattr(LinkedInAdapter, "_fetch_url", _serve)
    a = LinkedInAdapter(company="Goldman Sachs", company_slug="goldman-sachs",
                        linkedin_company_id="1382", max_pages=2)
    a.fetch_jobs()
    assert "start=10" in calls[1]


def test_pagination_stops_when_all_seen(page1_html, monkeypatch):
    monkeypatch.setattr("hk_jobs.adapters.linkedin.time.sleep", lambda *a, **k: None)
    calls: list[str] = []

    def _same(self, url):
        calls.append(url)
        return 200, page1_html

    monkeypatch.setattr(LinkedInAdapter, "_fetch_url", _same)
    a = LinkedInAdapter(company="Goldman Sachs", company_slug="goldman-sachs",
                        linkedin_company_id="1382", max_pages=5)
    jobs = a.fetch_jobs()
    assert len(jobs) == 3       # only the 3 unique cards
    assert len(calls) == 2      # page 1 (new) + page 2 (all seen → stop)


def test_geo_id_included_in_url(monkeypatch):
    a = LinkedInAdapter(company="X", company_slug="x", linkedin_company_id="9",
                        geo_id="103291313")
    url = a._page_url(0)
    assert "geoId=103291313" in url
    assert "f_C=9" in url


# ── anti-bot / authwall handling ──────────────────────────────────────────────

def test_authwall_returns_empty_list(monkeypatch):
    monkeypatch.setattr("hk_jobs.adapters.linkedin.time.sleep", lambda *a, **k: None)
    wall = (FIXTURE_DIR / "authwall.html").read_text()
    monkeypatch.setattr(LinkedInAdapter, "_fetch_url", lambda self, url: (200, wall))
    a = LinkedInAdapter(company="X", company_slug="x", linkedin_company_id="9")
    assert a.fetch_jobs() == []


def test_block_status_returns_empty_list(monkeypatch):
    monkeypatch.setattr("hk_jobs.adapters.linkedin.time.sleep", lambda *a, **k: None)
    monkeypatch.setattr(LinkedInAdapter, "_fetch_url", lambda self, url: (999, ""))
    a = LinkedInAdapter(company="X", company_slug="x", linkedin_company_id="9")
    assert a.fetch_jobs() == []


# ── transient-failure retry / partial results ─────────────────────────────────

def test_network_exception_retried_then_succeeds(monkeypatch, page1_html):
    monkeypatch.setattr("hk_jobs.adapters.linkedin.time.sleep", lambda *a, **k: None)
    attempts = {"n": 0}

    def _flaky(self, url):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise TimeoutError("read timeout")
        return 200, page1_html

    monkeypatch.setattr(LinkedInAdapter, "_fetch_url", _flaky)
    a = LinkedInAdapter(company="X", company_slug="x", linkedin_company_id="9", max_pages=1)
    jobs = a.fetch_jobs()
    assert attempts["n"] == 2
    assert len(jobs) == 3


def test_partial_results_preserved_when_later_page_fails(monkeypatch, page1_html):
    monkeypatch.setattr("hk_jobs.adapters.linkedin.time.sleep", lambda *a, **k: None)

    def _p1_ok_then_fail(self, url):
        if "start=10" in url:
            raise TimeoutError("network dropped")
        return 200, page1_html

    monkeypatch.setattr(LinkedInAdapter, "_fetch_url", _p1_ok_then_fail)
    a = LinkedInAdapter(company="X", company_slug="x", linkedin_company_id="9", max_pages=3)
    assert len(a.fetch_jobs()) == 3  # page-1 results kept despite page-2 failure


# ── registry & config ─────────────────────────────────────────────────────────

def test_linkedin_registered():
    from hk_jobs.adapters import ADAPTERS

    assert "linkedin" in ADAPTERS
    assert ADAPTERS["linkedin"] is LinkedInAdapter


def test_config_requires_company_id():
    from hk_jobs.config import _REQUIRED_CONFIG_KEYS

    assert _REQUIRED_CONFIG_KEYS["linkedin"] == ["linkedin_company_id"]
