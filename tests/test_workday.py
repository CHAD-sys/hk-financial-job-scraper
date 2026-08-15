"""
Tests for the Workday adapter.

All HTTP is intercepted by a custom httpx transport that serves JSON
from tests/fixtures/workday/. No network calls are made.
"""

import json
from pathlib import Path

import httpx
import pytest

from hk_jobs.adapters.workday import WorkdayAdapter, _map_time_type, _parse_locations, _strip_html

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "workday"


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def listing_data():
    return json.loads((FIXTURE_DIR / "listing.json").read_text())


@pytest.fixture
def detail_data():
    return {
        "JR-001": json.loads((FIXTURE_DIR / "detail_jr001.json").read_text()),
        "JR-002": json.loads((FIXTURE_DIR / "detail_jr002.json").read_text()),
    }


class _MockTransport(httpx.BaseTransport):
    """Serves fixture data without touching the network."""

    def __init__(self, listing_json: dict, detail_by_id: dict[str, dict]) -> None:
        self.listing_json = listing_json
        self.detail_by_id = detail_by_id
        self.post_calls: list[dict] = []
        self.get_calls: list[str] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            self.post_calls.append(json.loads(request.content))
            return httpx.Response(200, json=self.listing_json)
        # GET — detail endpoint; route by job ID in the URL path
        url_path = str(request.url)
        self.get_calls.append(url_path)
        for job_id, data in self.detail_by_id.items():
            if job_id in url_path:
                return httpx.Response(200, json=data)
        return httpx.Response(404, json={})


@pytest.fixture
def adapter(listing_data, detail_data, monkeypatch):
    """WorkdayAdapter wired to mock transport; detail sleep removed."""
    transport = _MockTransport(listing_data, detail_data)
    monkeypatch.setattr("hk_jobs.adapters.workday._DETAIL_SLEEP", 0)

    def _mock_client(self, timeout=20.0):
        return httpx.Client(transport=transport, follow_redirects=True)

    monkeypatch.setattr(WorkdayAdapter, "_client", _mock_client)
    adapter_obj = WorkdayAdapter(
        company="AIA",
        company_slug="aia",
        tenant="aia",
        site="External",
    )
    adapter_obj._transport = transport  # expose for call-count assertions
    return adapter_obj


# ── _strip_html ───────────────────────────────────────────────────────────────

def test_strip_html_removes_tags():
    assert _strip_html("<p>Hello</p>") == "Hello"


def test_strip_html_block_tags_become_newlines():
    result = _strip_html("<p>Line one</p><p>Line two</p>")
    assert "Line one" in result
    assert "Line two" in result
    assert "\n" in result


def test_strip_html_decodes_entities():
    assert "&" in _strip_html("&amp; &lt;test&gt;")
    assert "–" in _strip_html("Asia&ndash;Pacific")


def test_strip_html_empty_string():
    assert _strip_html("") == ""


def test_strip_html_plain_text_unchanged():
    assert _strip_html("No HTML here") == "No HTML here"


# ── _parse_locations ──────────────────────────────────────────────────────────

def test_parse_locations_single():
    assert _parse_locations("Hong Kong") == ["Hong Kong"]


def test_parse_locations_pipe_separated():
    result = _parse_locations("Hong Kong | Singapore")
    assert result == ["Hong Kong", "Singapore"]


def test_parse_locations_empty():
    assert _parse_locations("") == []


# ── _map_time_type ────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Full time", "full-time"),
        ("FULL TIME", "full-time"),
        ("Part time", "part-time"),
        ("Contract", "contract"),
        ("Intern", "internship"),
        ("Internship", "internship"),
        ("Unknown", None),
        ("", None),
    ],
)
def test_map_time_type(raw, expected):
    assert _map_time_type(raw) == expected


# ── adapter — full fetch with details ─────────────────────────────────────────

def test_fetch_jobs_returns_two_jobs(adapter):
    jobs = adapter.fetch_jobs()
    assert len(jobs) == 2


def test_fetch_jobs_job_identity(adapter):
    jobs = adapter.fetch_jobs()
    jr001 = next(j for j in jobs if j.source_id == "JR-001")
    assert jr001.company == "AIA"
    assert jr001.company_slug == "aia"
    assert jr001.source == "workday"
    assert "aia.wd3.myworkdayjobs.com" in jr001.url


def test_fetch_jobs_title_mapped(adapter):
    jobs = adapter.fetch_jobs()
    titles = {j.title for j in jobs}
    assert "Software Engineer, Hong Kong" in titles
    assert "Business Analyst" in titles


def test_fetch_jobs_description_raw_is_html(adapter):
    jobs = adapter.fetch_jobs()
    jr001 = next(j for j in jobs if j.source_id == "JR-001")
    assert "<p>" in jr001.description_raw or "<ul>" in jr001.description_raw


def test_fetch_jobs_description_clean_has_no_tags(adapter):
    jobs = adapter.fetch_jobs()
    jr001 = next(j for j in jobs if j.source_id == "JR-001")
    assert "<" not in jr001.description_clean
    assert "Software Engineer" in jr001.description_clean


def test_fetch_jobs_employment_type_mapped(adapter):
    jobs = adapter.fetch_jobs()
    for job in jobs:
        assert job.employment_type == "full-time"


def test_fetch_jobs_posted_at_parsed(adapter):
    from datetime import timezone

    jobs = adapter.fetch_jobs()
    jr001 = next(j for j in jobs if j.source_id == "JR-001")
    assert jr001.posted_at is not None
    assert jr001.posted_at.year == 2024
    assert jr001.posted_at.tzinfo == timezone.utc


def test_fetch_jobs_locations_jr001(adapter):
    jobs = adapter.fetch_jobs()
    jr001 = next(j for j in jobs if j.source_id == "JR-001")
    # detail has location="Hong Kong", additionalLocations=[]
    assert jr001.locations == ["Hong Kong"]


def test_fetch_jobs_locations_jr002_deduped(adapter):
    jobs = adapter.fetch_jobs()
    jr002 = next(j for j in jobs if j.source_id == "JR-002")
    # detail has location="Hong Kong", additionalLocations=["Singapore"]
    assert "Hong Kong" in jr002.locations
    assert "Singapore" in jr002.locations
    assert jr002.locations.count("Hong Kong") == 1  # no duplicate


def test_detail_calls_made_per_job(adapter):
    adapter.fetch_jobs()
    assert len(adapter._transport.get_calls) == 2


# ── adapter — no detail fetch ─────────────────────────────────────────────────

def test_no_detail_fetch_skips_get(monkeypatch, listing_data):
    transport = _MockTransport(listing_data, {})
    monkeypatch.setattr("hk_jobs.adapters.workday._DETAIL_SLEEP", 0)

    def _mock_client(self, timeout=20.0):
        return httpx.Client(transport=transport, follow_redirects=True)

    monkeypatch.setattr(WorkdayAdapter, "_client", _mock_client)

    adapter = WorkdayAdapter(
        company="AIA",
        company_slug="aia",
        tenant="aia",
        site="External",
        fetch_details=False,
    )
    jobs = adapter.fetch_jobs()
    assert len(jobs) == 2
    assert transport.get_calls == []
    # Without detail fetch, descriptions are empty (listing has none)
    assert jobs[0].description_raw == ""


# ── adapter — registry ────────────────────────────────────────────────────────

def test_workday_registered_in_adapters():
    from hk_jobs.adapters import ADAPTERS

    assert "workday" in ADAPTERS
    assert ADAPTERS["workday"] is WorkdayAdapter


# ── pagination: `total` only arrives on the first page ────────────────────────

class _PagingTransport(httpx.BaseTransport):
    """
    Mimics Workday's real paging contract.

    Workday reports `total` ONLY on the first response; every later page comes
    back with total=0 while still carrying postings. An adapter that re-reads
    `total` each page therefore sees `offset >= 0` immediately and stops after
    two pages — which is exactly how every Workday tenant here got truncated to
    40 jobs (DBS returned 40 of 294, AIA 40 of 160, FWD 40 of 193).
    """

    def __init__(self, total: int, page_size: int = 20) -> None:
        self.total = total
        self.page_size = page_size
        self.offsets: list[int] = []
        self.bodies: list[dict] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.bodies.append(body)
        offset = body["offset"]
        self.offsets.append(offset)
        remaining = max(0, self.total - offset)
        n = min(self.page_size, remaining)
        postings = [
            {"title": f"Job {offset + i}", "externalPath": f"/job/x_{offset + i}",
             "jobReqId": f"JR-{offset + i}", "locationsText": "Hong Kong"}
            for i in range(n)
        ]
        return httpx.Response(
            200,
            json={"total": self.total if offset == 0 else 0, "jobPostings": postings},
        )


def _paging_adapter(monkeypatch, transport, **kwargs):
    monkeypatch.setattr("hk_jobs.adapters.workday._DETAIL_SLEEP", 0)
    monkeypatch.setattr(
        WorkdayAdapter, "_client",
        lambda self, timeout=20.0: httpx.Client(transport=transport, follow_redirects=True),
    )
    return WorkdayAdapter(
        company="DBS", company_slug="dbs-hk", tenant="dbs", site="DBS_Careers",
        fetch_details=False, **kwargs,
    )


def test_pagination_survives_total_being_zero_on_later_pages(monkeypatch):
    """The bug: 294 available, only 40 collected."""
    transport = _PagingTransport(total=294)
    adapter = _paging_adapter(monkeypatch, transport)

    jobs = adapter.fetch_jobs()

    assert len(jobs) == 294


def test_pagination_stops_at_the_end_rather_than_looping(monkeypatch):
    """Must not keep requesting pages once the last posting has been read."""
    transport = _PagingTransport(total=45)
    adapter = _paging_adapter(monkeypatch, transport)

    jobs = adapter.fetch_jobs()

    assert len(jobs) == 45
    assert transport.offsets == [0, 20, 40], transport.offsets


# ── appliedFacets ─────────────────────────────────────────────────────────────

def test_applied_facets_are_sent_and_replace_search_text(monkeypatch):
    """
    A facet is the precise filter; searchText is a keyword match.

    Sending both ANDs them and re-truncates the facet's results (DBS: the
    locationCountry facet finds 294, the "Hong Kong" keyword only 40), so a
    configured facet must clear searchText.
    """
    transport = _PagingTransport(total=20)
    facets = {"locationCountry": ["d4afdeb461d446e4babd204bd102dba8"]}
    adapter = _paging_adapter(monkeypatch, transport, applied_facets=facets)

    adapter.fetch_jobs()

    sent = transport.bodies[0]
    assert sent["appliedFacets"] == facets
    assert sent["searchText"] == ""


def test_without_facets_search_text_is_still_used(monkeypatch):
    """Tenants with no facet configured keep the original keyword behaviour."""
    transport = _PagingTransport(total=20)
    adapter = _paging_adapter(monkeypatch, transport, location_filter="Hong Kong")

    adapter.fetch_jobs()

    sent = transport.bodies[0]
    assert sent["appliedFacets"] == {}
    assert sent["searchText"] == "Hong Kong"
