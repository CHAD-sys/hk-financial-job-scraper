"""Jane Street, Optiver and Two Sigma extractors, against pages recorded 28 Oct 2026."""

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from hk_jobs.adapters import direct_optiver, direct_twosigma
from hk_jobs.adapters.direct_janestreet import clean_title, fetch_janestreet, parse_janestreet_feed
from hk_jobs.adapters.direct_optiver import fetch_optiver, parse_date_posted, parse_description
from hk_jobs.adapters.direct_site import SITE_FETCHERS
from hk_jobs.adapters.direct_twosigma import (
    fetch_twosigma,
    is_hong_kong,
    parse_description as ts_description,
    parse_listing,
)

FIXTURES = Path(__file__).parent / "fixtures" / "direct_sites"


def test_all_three_are_registered():
    assert {"janestreet", "optiver", "twosigma"} <= set(SITE_FETCHERS)


# ── Jane Street ───────────────────────────────────────────────────────────────

def _js_rows():
    return json.loads((FIXTURES / "janestreet_main.json").read_text())


def test_janestreet_keeps_only_hong_kong_rows():
    rows = _js_rows()
    jobs = parse_janestreet_feed(rows, "Jane Street", "jane-street")
    assert len(rows) == 5 and len(jobs) == 4  # the NYC row is dropped
    assert all(j.source == "direct_site" and j.locations == ["Hong Kong"] for j in jobs)
    assert all(j.source_id.startswith("jane-street:") for j in jobs)


def test_janestreet_repairs_the_lookalike_title():
    assert clean_title("ꓟachine ꓡearning ꓣesearcher") == "Machine Learning Researcher"
    titles = [j.title for j in parse_janestreet_feed(_js_rows(), "Jane Street", "jane-street")]
    assert "Machine Learning Researcher" in titles


def test_janestreet_multi_city_value_and_robots_exclusion():
    base = {"position": "Trader", "overview": "<p>x</p>"}
    rows = [
        {**base, "id": 1, "city": "NYC/HKG"},
        {**base, "id": 2, "city": "LDN"},
        {**base, "id": 7304961002, "city": "HKG"},  # robots.txt disallows this page
    ]
    assert [j.source_id for j in parse_janestreet_feed(rows, "J", "j")] == ["j:1"]


def test_janestreet_internship_and_missing_date():
    jobs = parse_janestreet_feed(_js_rows(), "Jane Street", "jane-street")
    intern = [j for j in jobs if j.employment_type == "internship"]
    assert intern and all(j.posted_at is None for j in jobs)


def test_janestreet_fetch_rejects_a_changed_feed_shape():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"jobs": []})))
    with pytest.raises(ValueError):
        fetch_janestreet(client, "Jane Street", "jane-street")


# ── Optiver ───────────────────────────────────────────────────────────────────

_OPT_PAGE = (FIXTURES / "optiver_detail.html").read_text()


def test_optiver_reads_description_and_date_from_the_vacancy_page():
    assert "<p>" in parse_description(_OPT_PAGE) and len(parse_description(_OPT_PAGE)) > 1000
    assert parse_date_posted(_OPT_PAGE).date() == date(2026, 9, 29)
    assert parse_description("<html></html>") == "" and parse_date_posted("<html></html>") is None


def _optiver_client(items: list[dict], total: int | None = None) -> httpx.Client:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/v1/jobs"):
            start = int(request.url.params.get("from", 0))
            return httpx.Response(200, json={"items": items[start:start + 16], "totalCount": total or len(items)})
        return httpx.Response(200, text=_OPT_PAGE)

    return httpx.Client(transport=httpx.MockTransport(handle))


def _item(i: int, location: str, slug: str) -> dict:
    return {"title": f"Role {i}", "location": location, "experience": "Experienced",
            "domain": "Trading", "href": f"/join-us/jobs/trading/{slug}/role-{i}/", "componentID": i}


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(direct_optiver, "_SLEEP", 0)
    monkeypatch.setattr(direct_twosigma, "_SLEEP", 0)


def test_optiver_returns_nothing_when_there_is_no_hong_kong_role():
    items = [_item(i, "Amsterdam", "amsterdam") for i in range(20)]  # two pages
    assert fetch_optiver(_optiver_client(items), "Optiver", "optiver") == []


def test_optiver_maps_a_hong_kong_role():
    items = [_item(1, "Amsterdam", "amsterdam"), _item(2, "Hong Kong", "hong-kong")]
    (job,) = fetch_optiver(_optiver_client(items), "Optiver", "optiver")
    assert job.source_id == "optiver:2" and job.locations == ["Hong Kong"]
    assert job.url == "https://www.optiver.com/join-us/jobs/trading/hong-kong/role-2/"
    assert job.posted_at is not None and job.description_clean


def test_optiver_fails_loudly_on_an_incomplete_listing():
    with pytest.raises(ValueError):
        fetch_optiver(_optiver_client([_item(1, "Amsterdam", "amsterdam")], total=5), "Optiver", "optiver")


def test_optiver_stops_when_a_page_repeats():
    """An ignored `from` returns page 1 forever; that must not loop."""
    items = [_item(i, "Amsterdam", "amsterdam") for i in range(16)]
    client = httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"items": items, "totalCount": 99})))
    with pytest.raises(ValueError):
        fetch_optiver(client, "Optiver", "optiver")


# ── Two Sigma ─────────────────────────────────────────────────────────────────

_TS_LIST = (FIXTURES / "twosigma_list.html").read_text()
_TS_DETAIL = (FIXTURES / "twosigma_detail.html").read_text()


def test_twosigma_listing_parses_ids_titles_and_locations():
    rows = parse_listing(_TS_LIST)
    assert len(rows) == 10 and len({r["id"] for r in rows}) == 10
    assert rows[0]["id"] == "14291" and rows[0]["location"] == "United States - NY New York"
    assert not any(is_hong_kong(r) for r in rows)


def test_twosigma_description_comes_from_the_section_with_the_list():
    assert "quantitative investment manag" in ts_description(_TS_DETAIL)
    assert ts_description("<html></html>") == ""


def test_twosigma_hong_kong_filter_accepts_location_or_slug():
    assert is_hong_kong({"location": "Hong Kong - Hong Kong", "url": "https://x/JobDetail/a/1"})
    assert is_hong_kong({"location": "", "url": "https://x/JobDetail/Hong-Kong-Analyst/1"})


def test_twosigma_crawls_until_a_page_has_no_vacancies_and_maps_hong_kong():
    hk = _TS_LIST.replace("United States - NY New York", "Hong Kong - Hong Kong", 1)

    def handle(request: httpx.Request) -> httpx.Response:
        if "JobDetail" in request.url.path:
            return httpx.Response(200, text=_TS_DETAIL)
        offset = int(request.url.params["jobOffset"])
        return httpx.Response(200, text=hk if offset == 0 else "<html></html>")

    client = httpx.Client(transport=httpx.MockTransport(handle))
    (job,) = fetch_twosigma(client, "Two Sigma", "two-sigma")
    assert job.source_id == "two-sigma:14291" and job.locations == ["Hong Kong"]
    assert job.department == "Engineering" and job.posted_at is None and job.description_clean
