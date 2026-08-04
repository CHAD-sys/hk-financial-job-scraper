"""
Tests for the Eightfold adapter.

All HTTP is intercepted by a custom transport that serves JSON from
tests/fixtures/eightfold/. No network calls are made.
"""

import json
from datetime import timezone
from pathlib import Path

import httpx
import pytest

from hk_jobs.adapters.eightfold import EightfoldAdapter

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "eightfold"


# ── fixtures & mock transport ─────────────────────────────────────────────────

@pytest.fixture
def page0():
    return json.loads((FIXTURE_DIR / "page0.json").read_text())


@pytest.fixture
def page1():
    return json.loads((FIXTURE_DIR / "page1.json").read_text())


class _MockTransport(httpx.BaseTransport):
    """Serves paginated fixture data by inspecting the 'start' query param."""

    def __init__(self, pages: list[dict]) -> None:
        self.pages = pages
        self.calls: list[dict] = []  # record query params for assertions

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        self.calls.append(params)
        start = int(params.get("start", 0))
        page_size = int(params.get("num", 10))
        page_index = start // page_size
        if page_index < len(self.pages):
            return httpx.Response(200, json=self.pages[page_index])
        # Past last page — return empty positions with the same total count
        total = self.pages[0].get("count", 0) if self.pages else 0
        return httpx.Response(200, json={"count": total, "positions": []})


@pytest.fixture
def adapter(page0, page1, monkeypatch):
    transport = _MockTransport([page0, page1])
    # Force page size to 2 so pagination actually triggers across our two
    # fixture files (count=3 → page0 has 2 jobs, page1 has 1 job).
    monkeypatch.setattr("hk_jobs.adapters.eightfold._PAGE_SIZE", 2)
    monkeypatch.setattr("hk_jobs.adapters.eightfold._PAGE_SLEEP", 0)

    def _mock_client(self, timeout=20.0):
        return httpx.Client(transport=transport, follow_redirects=True)

    monkeypatch.setattr(EightfoldAdapter, "_client", _mock_client)
    a = EightfoldAdapter(
        company="HSBC",
        company_slug="hsbc",
        tenant="hsbc",
        domain="hsbc.com",
    )
    a._transport = transport
    return a


# ── basic fetch ───────────────────────────────────────────────────────────────

def test_fetch_jobs_returns_all_three(adapter):
    jobs = adapter.fetch_jobs()
    assert len(jobs) == 3


def test_fetch_jobs_source_name(adapter):
    jobs = adapter.fetch_jobs()
    assert all(j.source == "eightfold" for j in jobs)


def test_fetch_jobs_company_fields(adapter):
    jobs = adapter.fetch_jobs()
    assert all(j.company == "HSBC" for j in jobs)
    assert all(j.company_slug == "hsbc" for j in jobs)


# ── field mapping ─────────────────────────────────────────────────────────────

def test_source_id_mapped_from_id(adapter):
    jobs = adapter.fetch_jobs()
    ids = {j.source_id for j in jobs}
    assert "100000000000001" in ids
    assert "100000000000002" in ids
    assert "100000000000003" in ids


def test_title_mapped_from_name(adapter):
    jobs = adapter.fetch_jobs()
    titles = {j.title for j in jobs}
    assert "Vice President, Risk Analytics" in titles
    assert "Associate, Compliance Advisory" in titles


def test_department_mapped(adapter):
    jobs = adapter.fetch_jobs()
    vp = next(j for j in jobs if j.source_id == "100000000000001")
    assert vp.department == "Risk Management"


def test_locations_mapped_single(adapter):
    jobs = adapter.fetch_jobs()
    vp = next(j for j in jobs if j.source_id == "100000000000001")
    assert vp.locations == ["Hong Kong"]


def test_locations_mapped_multiple(adapter):
    jobs = adapter.fetch_jobs()
    assoc = next(j for j in jobs if j.source_id == "100000000000002")
    assert "Hong Kong" in assoc.locations
    assert "Singapore" in assoc.locations


def test_url_mapped_from_canonical(adapter):
    jobs = adapter.fetch_jobs()
    vp = next(j for j in jobs if j.source_id == "100000000000001")
    assert vp.url == "https://hsbc.eightfold.ai/careers?pid=100000000000001"


def test_description_raw_is_html(adapter):
    jobs = adapter.fetch_jobs()
    vp = next(j for j in jobs if j.source_id == "100000000000001")
    assert "<p>" in vp.description_raw


def test_description_clean_has_no_tags(adapter):
    jobs = adapter.fetch_jobs()
    vp = next(j for j in jobs if j.source_id == "100000000000001")
    assert "<" not in vp.description_clean
    assert "Vice President" in vp.description_clean


def test_description_clean_decodes_entities(adapter):
    jobs = adapter.fetch_jobs()
    assoc = next(j for j in jobs if j.source_id == "100000000000002")
    assert "&" in assoc.description_clean  # &amp; decoded


def test_posted_at_parsed_from_unix_seconds(adapter):
    """
    t_create is Unix SECONDS, not milliseconds.

    The fixture used to carry millisecond values, which no live response has
    ever contained — every one of the 619 Eightfold rows in the production
    database has a sane date, and a millisecond value fed to
    `datetime.fromtimestamp` raises before it can produce one. The old name of
    this test enshrined the mistake.
    """
    jobs = adapter.fetch_jobs()
    vp = next(j for j in jobs if j.source_id == "100000000000001")
    assert vp.posted_at is not None
    assert vp.posted_at.tzinfo == timezone.utc
    assert vp.posted_at.year == 2024


# ── pagination ────────────────────────────────────────────────────────────────

def test_two_pages_fetched(adapter):
    adapter.fetch_jobs()
    # count=3, page_size=2 → page 0 returns 2 jobs (start=0),
    # page 1 returns 1 job (start=2), then start=4 >= count=3 stops.
    assert len(adapter._transport.calls) == 2


def test_page_params_correct(adapter):
    adapter.fetch_jobs()
    first_call = adapter._transport.calls[0]
    assert first_call["domain"] == "hsbc.com"
    assert first_call["start"] == "0"
    assert first_call["num"] == "2"  # monkeypatched _PAGE_SIZE
    assert first_call["location"] == "Hong Kong"

    second_call = adapter._transport.calls[1]
    assert second_call["start"] == "2"


# ── registry ──────────────────────────────────────────────────────────────────

def test_eightfold_registered():
    from hk_jobs.adapters import ADAPTERS

    assert "eightfold" in ADAPTERS
    assert ADAPTERS["eightfold"] is EightfoldAdapter
