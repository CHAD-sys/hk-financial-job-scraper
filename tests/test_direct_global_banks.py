"""Goldman Sachs, Bank of America and Barclays fetchers, against responses recorded 30 Oct 2026."""

import json
from datetime import UTC, date
from pathlib import Path

import httpx
import pytest

from hk_jobs.adapters import direct_global_banks as gb

FIXTURES = Path(__file__).parent / "fixtures" / "direct_sites"


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(gb, "_SLEEP", 0)


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_registered_under_target_slugs():
    assert set(gb.SITE_FETCHERS) == {"goldman-sachs", "bank-of-america", "barclays"}


# ── Goldman Sachs ─────────────────────────────────────────────────────────────

_GS_LIST = json.loads((FIXTURES / "goldman_sachs_list.json").read_text())
_GS_ITEMS = _GS_LIST["data"]["roleSearch"]["items"]
_GS_DETAILS = {
    d["data"]["role"]["externalSource"]["sourceId"]: d
    for d in (json.loads((FIXTURES / f"goldman_sachs_detail{n}.json").read_text()) for n in (0, 1))
}


def _gs_item(i: int, country: str = "Hong Kong", sid: str | None = None) -> dict:
    return {"roleId": f"{i}_GS_MID_CAREER", "corporateTitle": "Associate", "jobTitle": f"Role {i}",
            "jobFunction": "Sales", "division": "Risk", "status": "POSTED",
            "locations": [{"primary": True, "state": None, "country": country, "city": None}],
            "externalSource": {"sourceId": sid or str(i)}}


def _gs_handler(items: list[dict], total: int | None = None, page_size: int = 20):
    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["operationName"] == "GetRoles":
            n = body["variables"]["searchQueryInput"]["page"]["pageNumber"]
            page = items[n * page_size:(n + 1) * page_size]
            return httpx.Response(200, json={"data": {"roleSearch": {"totalCount": total if total is not None else len(items), "items": page}}})
        sid = body["variables"]["externalSourceId"]
        if sid in _GS_DETAILS:
            return httpx.Response(200, json=_GS_DETAILS[sid])
        return httpx.Response(200, json={"data": {"role": {"roleId": sid, "descriptionHtml": "<p>Body</p>"}}})

    return handle


def test_gs_maps_recorded_roles():
    items = _GS_ITEMS[:2]
    jobs = gb.fetch_goldman_sachs(_client(_gs_handler(items)), "Goldman Sachs", "goldman-sachs")
    assert len(jobs) == 2
    j = jobs[0]
    assert j.source == "direct_site" and j.source_id == "goldman-sachs:187978_GS_MID_CAREER"
    assert j.url == "https://higher.gs.com/roles/187978" and j.scraped_under_slug == "goldman-sachs"
    assert j.title == "Global Banking & Markets, Futures Sales Trading, Associate, Hong Kong"
    assert j.department == "Global Banking & Markets" and j.locations == ["Hong Kong"]
    assert j.posted_at is None and "Goldman Sachs" in j.description_clean and "<" not in j.description_clean
    assert j.description_raw.startswith("<p>")


def test_gs_filters_non_hong_kong_and_collapses_duplicates():
    items = [_gs_item(1), _gs_item(1), _gs_item(2, "Singapore")]
    jobs = gb.fetch_goldman_sachs(_client(_gs_handler(items, total=2)), "GS", "goldman-sachs")
    assert [j.source_id for j in jobs] == ["goldman-sachs:1_GS_MID_CAREER"]


def test_gs_multi_location_keeps_hong_kong_first():
    item = _gs_item(3)
    item["locations"] = [{"primary": False, "state": None, "country": "Singapore", "city": "Singapore"},
                         {"primary": True, "state": "Hong Kong", "country": "Hong Kong", "city": None}]
    (job,) = gb.fetch_goldman_sachs(_client(_gs_handler([item])), "GS", "goldman-sachs")
    assert job.locations == ["Hong Kong", "Singapore"]


def test_gs_paginates_to_the_end():
    items = [_gs_item(i) for i in range(45)]  # pages of 20/20/5
    jobs = gb.fetch_goldman_sachs(_client(_gs_handler(items)), "GS", "goldman-sachs")
    assert len(jobs) == 45


def test_gs_empty_result():
    assert gb.fetch_goldman_sachs(_client(_gs_handler([])), "GS", "goldman-sachs") == []


def test_gs_incomplete_listing_and_graphql_errors_raise():
    with pytest.raises(ValueError):
        gb.fetch_goldman_sachs(_client(_gs_handler([_gs_item(1)], total=5)), "GS", "goldman-sachs")
    bad = _client(lambda r: httpx.Response(200, json={"errors": [{"message": "ValidationError"}]}))
    with pytest.raises(ValueError):
        gb.fetch_goldman_sachs(bad, "GS", "goldman-sachs")


# ── Bank of America ───────────────────────────────────────────────────────────

_BOA_LIST = json.loads((FIXTURES / "bank_of_america_list.json").read_text())
_BOA_DETAIL = (FIXTURES / "bank_of_america_detail.html").read_text()


def _boa_handler(rows: list[dict], total: int | None = None):
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/services/jobssearchservlet":
            p = request.url.params
            assert p["search"] == "jobsByCountry" and p["country"] == "Hong Kong"
            start, size = int(p["start"]), int(p["rows"])
            return httpx.Response(200, json={"totalMatches": total if total is not None else len(rows),
                                             "jobsList": rows[start:start + size]})
        return httpx.Response(200, text=_BOA_DETAIL)

    return handle


def _boa_row(i: int, country: str = "Hong Kong") -> dict:
    return {**_BOA_LIST["jobsList"][1], "jobRequisitionId": str(i), "country": country,
            "jcrURL": f"/en-us/job-detail/{i}/x"}


def test_boa_maps_recorded_rows():
    rows = _BOA_LIST["jobsList"]
    jobs = gb.fetch_bank_of_america(_client(_boa_handler(rows)), "Bank of America", "bank-of-america")
    assert len(jobs) == 4
    j = jobs[0]
    assert j.source_id == "bank-of-america:26040036" and j.scraped_under_slug == "bank-of-america"
    assert j.url.startswith("https://careers.bankofamerica.com/en-us/job-detail/26040036/")
    assert j.title.endswith("Singapore/Hong Kong") and j.department == "Global Payments Solutions"
    assert j.posted_at.date() == date(2026, 10, 29) and j.posted_at.tzinfo is UTC
    assert j.locations == ["Hong Kong", "Singapore"]
    assert jobs[3].locations == ["Hong Kong"]  # extra office is another HK address
    assert "Bank of America" in j.description_clean and "<" not in j.description_clean


def test_boa_paginates_and_collapses_duplicates():
    rows = [_boa_row(i) for i in range(60)] + [_boa_row(5)]
    jobs = gb.fetch_bank_of_america(_client(_boa_handler(rows)), "BoA", "bank-of-america")
    assert len(jobs) == 60 and len({j.source_id for j in jobs}) == 60


def test_boa_drops_non_hong_kong_rows_but_refuses_an_ignored_filter():
    mixed = [_boa_row(1), _boa_row(2, "Singapore")]
    assert [j.source_id for j in gb.fetch_bank_of_america(_client(_boa_handler(mixed)), "B", "bank-of-america")] == ["bank-of-america:1"]
    everything = [_boa_row(i, "United States") for i in range(3)]
    with pytest.raises(ValueError):
        gb.fetch_bank_of_america(_client(_boa_handler(everything)), "B", "bank-of-america")


def test_boa_empty_result():
    assert gb.fetch_bank_of_america(_client(_boa_handler([])), "B", "bank-of-america") == []


def test_boa_helpers():
    assert gb.parse_us_date("10/27/2026").date() == date(2026, 10, 27) and gb.parse_us_date("") is None
    assert gb._unescape_once("&lt;p&gt;x&lt;/p&gt;") == "<p>x</p>" and gb._unescape_once("<p>&lt;</p>") == "<p>&lt;</p>"
    row = {**_boa_row(1), "postingTitle": "​Analyst "}
    assert gb.boa_map_row(row, "<html></html>", "B", "b").title == "Analyst"


# ── Barclays ──────────────────────────────────────────────────────────────────

_BAR_LIST = (FIXTURES / "barclays_list.html").read_text()
_BAR_DETAIL = (FIXTURES / "barclays_detail.html").read_text()


def _bar_handler(listing: str):
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/search-jobs/"):
            assert request.url.path.endswith("/13015/2/1819730/22/114/2/2")
            return httpx.Response(200, text=listing)
        return httpx.Response(200, text=_BAR_DETAIL)

    return handle


def test_barclays_listing_ignores_the_recommended_block():
    cards, total, pages = gb.parse_barclays_listing(_BAR_LIST)
    assert (total, pages) == (7, 1)
    assert len(cards) == 3 and all("/job/hong-kong/" in c["url"] for c in cards)
    assert cards[0]["id"] == "99388015584" and cards[0]["location"] == "Hong Kong, Hong Kong China"
    assert "–" in cards[0]["title"]  # entity decoded


def test_barclays_maps_a_job_from_json_ld():
    listing = _BAR_LIST.replace('data-total-job-results="7"', 'data-total-job-results="3"')
    jobs = gb.fetch_barclays(_client(_bar_handler(listing)), "Barclays", "barclays")
    assert len(jobs) == 3
    j = jobs[0]
    assert j.source_id == "barclays:99388015584" and j.scraped_under_slug == "barclays"
    assert j.url == "https://search.jobs.barclays/job/hong-kong/liquid-financing-vp-full-stack-developer/13015/99388015584"
    assert j.locations == ["Hong Kong"] and j.department == "Markets Pre Trade"
    assert j.posted_at.date() == date(2026, 8, 18) and j.posted_at.tzinfo is UTC
    assert j.description_raw.startswith("<p>") and "Barclays" in j.description_clean


def test_barclays_inconsistent_counter_raises():
    with pytest.raises(ValueError):  # page says 7 results but carries 3 cards
        gb.fetch_barclays(_client(_bar_handler(_BAR_LIST)), "Barclays", "barclays")


def test_barclays_pages_until_total_pages_and_collapses_duplicates():
    one = _BAR_LIST.replace('data-total-job-results="7"', 'data-total-job-results="3"').replace(
        'data-total-pages="1"', 'data-total-pages="2"')
    seen = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/search-jobs/"):
            seen.append(request.url.params.get("p"))
            return httpx.Response(200, text=one)  # page 2 repeats page 1: must stop, not loop
        return httpx.Response(200, text=_BAR_DETAIL)

    assert len(gb.fetch_barclays(_client(handle), "B", "barclays")) == 3
    assert seen == [None, "2"]


def test_barclays_empty_result_and_missing_counters():
    empty = ('<div data-total-results="0" data-total-job-results="0" data-total-pages="0"></div>'
             '<section id="search-results-list"></section>')
    assert gb.fetch_barclays(_client(_bar_handler(empty)), "B", "barclays") == []
    with pytest.raises(ValueError):
        gb.fetch_barclays(_client(_bar_handler("<html></html>")), "B", "barclays")


def test_barclays_hong_kong_filter_and_multi_location():
    assert gb.barclays_is_hong_kong({"location": "Hong Kong, Hong Kong China"})
    assert not gb.barclays_is_hong_kong({"location": "London, United Kingdom"})
    assert gb.barclays_locations("Hong Kong, Hong Kong China; Singapore, Singapore") == ["Hong Kong", "Singapore, Singapore"]
