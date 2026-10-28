"""Recorded public Taleo responses from 2026-10-28; no live calls in tests."""

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from hk_jobs.adapters.direct_hkairport import fetch_hkairport, parse_airport_listing
from hk_jobs.adapters.direct_mtr import fetch_mtr, parse_mtr_listing, parse_taleo_detail

FIXTURES = Path(__file__).parent / "fixtures" / "direct_taleo"


def _read(name):
    return (FIXTURES / name).read_text()


def test_mtr_listing_is_script_data_not_visible_rows():
    total, first_page = parse_mtr_listing(_read("mtr_listing.html"))
    assert total == 49
    assert len(first_page) == 25
    assert first_page[0] == {
        "id": "103643",
        "title": "Sales Officer II (Ref No.: 260000XY)",
        "requisition": "260000XY",
        "location": "Hong Kong",
        "schedule": "Full-time",
        "posted": "23/Oct/26",
        "closes": "05/Nov/26",
    }


def test_mtr_100_per_page_captures_all_postings():
    total, rows = parse_mtr_listing(_read("mtr_listing_100.html"))
    assert total == 49
    assert len(rows) == total
    assert len({row["id"] for row in rows}) == total
    assert any("AI & Digital Solutions" in row["title"] for row in rows)


def test_mtr_unrecognized_page_fails_instead_of_closing_all_jobs():
    with pytest.raises(ValueError, match="total count"):
        parse_mtr_listing("<html><body>Temporary service page</body></html>")


def test_mtr_detail_is_decoded_from_taleo_data():
    raw, clean = parse_taleo_detail(_read("mtr_detail.html"))
    assert "<p>" in raw
    assert "%3Cp" not in raw
    assert "Responsibilities" in clean
    assert "Requirements" in clean
    assert "<" not in clean


def test_airport_json_pagination_shape():
    first_total, first = parse_airport_listing(json.loads(_read("airport_page1.json")))
    last_total, last = parse_airport_listing(json.loads(_read("airport_page2.json")))
    assert first_total == last_total == 27
    assert len(first) == 25
    assert len(last) == 2
    assert first[0] == {
        "id": "47210",
        "requisition": "263013",
        "title": "Manager, IT (Portfolio Management)",
        "closes": "2026-11-08",
    }


def test_airport_detail_is_decoded_from_taleo_data():
    raw, clean = parse_taleo_detail(_read("airport_detail.html"))
    assert "<p>" in raw
    assert "Responsibilities" in clean
    assert "%3Cp" not in raw


@pytest.mark.parametrize("site", ["mtr", "airport"])
def test_fetches_complete_company_and_namespaces_ids(monkeypatch, site):
    monkeypatch.setattr("hk_jobs.adapters.direct_mtr.time.sleep", lambda _: None)
    monkeypatch.setattr("hk_jobs.adapters.direct_hkairport.time.sleep", lambda _: None)
    calls = []

    def respond(request):
        calls.append(request)
        path = request.url.path
        if site == "mtr":
            if path.endswith("joblist.ftl"):
                name = "mtr_listing.html" if request.method == "GET" else "mtr_listing_100.html"
                return httpx.Response(200, text=_read(name))
            return httpx.Response(200, text=_read("mtr_detail.html"))
        if path.endswith("jobsearch.ftl"):
            return httpx.Response(200, text=_read("airport_search.html"))
        if path.endswith("searchjobs"):
            page = json.loads(request.content)["pageNo"]
            return httpx.Response(200, text=_read(f"airport_page{page}.json"))
        return httpx.Response(200, text=_read("airport_detail.html"))

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        if site == "mtr":
            jobs = fetch_mtr(client, "MTR", "mtr")
            assert len(jobs) == 49
        else:
            jobs = fetch_hkairport(client, "Airport Authority", "airport-authority")
            assert len(jobs) == 27
            assert len([c for c in calls if c.url.path.endswith("searchjobs")]) == 2
            assert jobs[0].posted_at == datetime(2026, 10, 26, tzinfo=UTC)
    assert all(job.source == "direct_site" for job in jobs)
    assert all(job.source_id.startswith(jobs[0].company_slug + ":") for job in jobs)
    assert all(job.description_clean for job in jobs)
    assert len({job.source_id for job in jobs}) == len(jobs)
