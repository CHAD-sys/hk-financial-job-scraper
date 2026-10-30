"""EY, Zurich and Swiss Re (SAP SuccessFactors RMK) fetchers, against pages recorded 30 Oct 2026."""

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from hk_jobs.adapters import direct_sf_rmk as sf
from hk_jobs.adapters.direct_sf_rmk import SITE_FETCHERS

FIXTURES = Path(__file__).parent / "fixtures" / "direct_sites"
MULTI_ID = "1448887333"  # EY posting listed as "London +26 more"; Hong Kong only on its detail page


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(sf.time, "sleep", lambda _s: None)


def _read(name: str) -> str:
    return (FIXTURES / name).read_text()


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _site(listing_pages: dict[int, str], detail_for, hits: list | None = None):
    """Listing keyed by startrow; detail_for(job_id) -> html."""

    def handler(request: httpx.Request) -> httpx.Response:
        if hits is not None:
            hits.append(request.url)
        if "/search/" in request.url.path:
            assert request.url.params["locationsearch"] == "Hong Kong"
            start = int(request.url.params.get("startrow", "0"))
            return httpx.Response(200, text=listing_pages.get(start, _empty()))
        return httpx.Response(200, text=detail_for(request.url.path.strip("/").split("/")[-1]))

    return handler


def _empty() -> str:
    return '<html><body><table></table><span class="paginationLabel">No results</span></body></html>'


def _ey_handler(hits=None, detail_for=None):
    def default_detail(job_id):
        return _read("ey_detail_multi.html" if job_id == MULTI_ID else "ey_detail.html")

    return _site(
        {0: _read("ey_list_p1.html"), 25: _read("ey_list_p2.html")}, detail_for or default_detail, hits
    )


def test_registered_slugs():
    assert set(SITE_FETCHERS) == {"ey", "zurich-hk", "swiss-re"}


# -- listing / detail parsers --------------------------------------------------------------

def test_ey_listing_dedupes_desktop_and_phone_anchors():
    rows = sf.parse_listing(_read("ey_list_p1.html"))
    assert len(rows) == 25 and len({r["id"] for r in rows}) == 25
    assert sf.parse_total(_read("ey_list_p1.html")) == 47
    first = rows[0]
    assert first["id"] == "716952601" and first["location"].startswith("Hong Kong")
    assert first["href"].startswith("/ey/job/")


def test_listing_multi_location_flag_and_cleaned_text():
    rows = {r["id"]: r for r in sf.parse_listing(_read("ey_list_p1.html")) + sf.parse_listing(_read("ey_list_p2.html"))}
    multi = rows[MULTI_ID]
    assert multi["has_more_locations"] and multi["location"] == "London, GB, SE1 2AF"
    assert not sf.is_hong_kong_text(multi["location"])


def test_zurich_listing_fields():
    rows = sf.parse_listing(_read("zurich-hk_list.html"))
    assert len(rows) == 14 and sf.parse_total(_read("zurich-hk_list.html")) == 14
    by_id = {r["id"]: r for r in rows}
    claims = by_id["804536702"]
    assert claims["department"] == "Claims" and claims["location"] == "Hong Kong, HK"
    assert claims["has_more_locations"] and claims["date"] == "Oct 28, 2026"


def test_detail_parse_ey_multi_lists_every_office():
    detail = sf.parse_detail(_read("ey_detail_multi.html"))
    assert "Hong Kong" in detail["locations"] and "London" in " ".join(detail["locations"])
    assert detail["posted_at"] == datetime(2026, 10, 19, tzinfo=UTC)
    assert detail["description"].startswith("<") or "EY" in detail["description"]


def test_detail_parse_zurich_and_swiss_re():
    zurich = sf.parse_detail(_read("zurich-hk_detail.html"))
    assert zurich["locations"] == ["Hong Kong"] and zurich["posted_at"] == datetime(2026, 10, 12, 2, tzinfo=UTC)
    swiss = sf.parse_detail(_read("swiss-re_detail.html"))
    assert swiss["locations"] == ["Hong Kong"] and swiss["segment"].startswith("Claims")
    assert swiss["posted_at"] == datetime(2026, 10, 14, 2, tzinfo=UTC)


def test_detail_date_garbage_is_none():
    assert sf.parse_detail_date("not a date") is None and sf.parse_detail_date(None) is None


# -- fetchers ----------------------------------------------------------------------------

def test_ey_fetch_paginates_to_47_and_keeps_the_hidden_hong_kong_posting():
    hits: list = []
    jobs = SITE_FETCHERS["ey"](_client(_ey_handler(hits)), "EY", "ey")
    assert len(jobs) == 47 and len({j.source_id for j in jobs}) == 47
    searches = [u for u in hits if "/search/" in u.path]
    assert [u.params["startrow"] for u in searches] == ["0", "25"]
    job = next(j for j in jobs if j.source_id == "ey:716952601")
    assert job.source == "direct_site" and job.company_slug == job.scraped_under_slug == "ey"
    assert job.url == "https://careers.ey.com" + sf.parse_listing(_read("ey_list_p1.html"))[0]["href"]
    assert job.locations == ["Hong Kong"] and job.posted_at.tzinfo is not None
    assert job.description_raw and job.description_clean and "<" not in job.description_clean
    assert job.department is None
    multi = next(j for j in jobs if j.source_id == f"ey:{MULTI_ID}")
    assert multi.locations[0] == "Hong Kong" and len(multi.locations) > 5


def test_ey_multi_location_posting_without_hong_kong_is_dropped():
    def detail(job_id):
        page = _read("ey_detail_multi.html" if job_id == MULTI_ID else "ey_detail.html")
        return page.replace('content="Hong Kong"', 'content="Singapore"') if job_id == MULTI_ID else page

    jobs = SITE_FETCHERS["ey"](_client(_ey_handler(detail_for=detail)), "EY", "ey")
    assert len(jobs) == 46 and f"ey:{MULTI_ID}" not in {j.source_id for j in jobs}


def test_zurich_fetch_maps_department_and_host():
    handler = _site({0: _read("zurich-hk_list.html")}, lambda _i: _read("zurich-hk_detail.html"))
    jobs = SITE_FETCHERS["zurich-hk"](_client(handler), "Zurich Hong Kong", "zurich-hk")
    assert len(jobs) == 14
    claims = next(j for j in jobs if j.source_id == "zurich-hk:804536702")
    assert claims.department == "Claims" and claims.url.startswith("https://www.careers.zurich.com/job/")
    assert claims.locations == ["Hong Kong"] and claims.posted_at == datetime(2026, 10, 12, 2, tzinfo=UTC)


def test_swiss_re_fetch_uses_job_segment_as_department_and_keeps_raw_urls():
    handler = _site({0: _read("swiss-re_list.html")}, lambda _i: _read("swiss-re_detail.html"))
    jobs = SITE_FETCHERS["swiss-re"](_client(handler), "Swiss Re", "swiss-re")
    assert {j.source_id for j in jobs} == {f"swiss-re:{i}" for i in ("1426823533", "1437798733", "1445034233", "1435197933")}
    assert all(j.url.startswith("https://careers.swissre.com/job/") and j.department.startswith("Claims") for j in jobs)
    assert any("L&H" in j.title for j in jobs)


def test_empty_result_returns_no_jobs():
    handler = _site({0: _empty()}, lambda _i: pytest.fail("no detail expected"))
    assert SITE_FETCHERS["swiss-re"](_client(handler), "Swiss Re", "swiss-re") == []


def test_duplicate_rows_across_pages_collapse_and_repeated_page_stops():
    page = _read("swiss-re_list.html")  # 4 rows, label says 4
    doubled = page.replace("</tbody>", "</tbody>").replace(
        "<tbody>", "<tbody>" + page.split("<tbody>")[1].split("</tbody>")[0]
    )
    handler = _site({0: doubled}, lambda _i: _read("swiss-re_detail.html"))
    jobs = SITE_FETCHERS["swiss-re"](_client(handler), "Swiss Re", "swiss-re")
    assert len(jobs) == 4


def test_repeating_page_stops_paging():
    page = _read("ey_list_p1.html")  # claims 47 but every page is the same 25 rows
    hits: list = []
    handler = _site({0: page, 25: page, 50: page}, lambda _i: _read("ey_detail.html"), hits)
    with pytest.raises(ValueError, match="incomplete"):
        SITE_FETCHERS["ey"](_client(handler), "EY", "ey")
    assert len([u for u in hits if "/search/" in u.path]) == 2  # stopped at the repeat


def test_inconsistent_total_raises():
    page = _read("zurich-hk_list.html").replace("of <b>14</b>", "of <b>20</b>")
    handler = _site({0: page}, lambda _i: _read("zurich-hk_detail.html"))
    with pytest.raises(ValueError, match="incomplete"):
        SITE_FETCHERS["zurich-hk"](_client(handler), "Zurich Hong Kong", "zurich-hk")


def test_http_error_propagates():
    client = _client(lambda _r: httpx.Response(503))
    with pytest.raises(httpx.HTTPStatusError):
        SITE_FETCHERS["ey"](client, "EY", "ey")
