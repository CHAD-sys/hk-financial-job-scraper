"""HashKey, Hong Kong Life Insurance and Wizpresso fetchers against pages recorded 29-30 Oct 2026."""

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from hk_jobs.adapters import direct_small_hk as m

FIXTURES = Path(__file__).parent / "fixtures" / "direct_sites"


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(m, "_SLEEP", 0)
    monkeypatch.setattr(m, "_WIZ_SLEEP", 0)


def fx(name: str) -> str:
    return (FIXTURES / name).read_text()


def client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def test_registered_slugs():
    assert set(m.SITE_FETCHERS) == {"hashkey", "hong-kong-life-insurance-limited", "wizpresso"}


# ── HashKey ───────────────────────────────────────────────────────────────────

def _hashkey_handler(requests=None, pages=("p1", "p2", "p3")):
    def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(str(request.url))
        path = request.url.path
        if path == "/en/category/roles/":
            return httpx.Response(200, text=fx("hashkey_list_p1.html"))
        for n in (2, 3):
            if path == f"/en/category/roles/page/{n}/":
                return httpx.Response(200, text=fx(f"hashkey_list_p{n}.html"))
        if path.startswith("/en/category/roles/page/"):
            return httpx.Response(404)
        return httpx.Response(200, text=fx("hashkey_detail.html"))
    return handler


def test_hashkey_listing_fields():
    rows = m.parse_hashkey_listing(fx("hashkey_list_p1.html"))
    assert [r["id"] for r in rows] == ["15434", "14859", "11903"]
    assert rows[1] == {
        "id": "14859", "department": "Exchange BG", "location": "Hong Kong", "type": "Full-time",
        "title": "Margin Business Owner", "url": "https://group.hashkey.com/en/margin-business-owner/",
    }
    assert [m.is_hashkey_hong_kong(r) for r in rows] == [True, True, False]  # Dubai dropped


def test_hashkey_fetch_filters_maps_and_ends_on_404():
    seen: list[str] = []
    jobs = m.fetch_hashkey(client(_hashkey_handler(seen)), "HashKey Group", "hashkey")
    # p1: 2 HK (Dubai dropped), p2: 1 HK (Malaysia dropped), p3: 1 HK
    assert [j.source_id for j in jobs] == ["hashkey:15434", "hashkey:14859", "hashkey:11901", "hashkey:11891"]
    j = jobs[1]
    assert (j.source, j.company, j.company_slug, j.scraped_under_slug) == ("direct_site", "HashKey Group", "hashkey", "hashkey")
    assert j.url == "https://group.hashkey.com/en/margin-business-owner/"
    assert j.title == "Margin Business Owner" and j.department == "Exchange BG"
    assert j.locations == ["Hong Kong"] and j.posted_at is None
    assert "HashKey Exchange" in j.description_clean and "<" not in j.description_clean
    assert j.description_raw.startswith("<div")
    assert seen.count("https://group.hashkey.com/en/category/roles/page/4/") == 1


def test_hashkey_empty_result():
    def handler(request):
        if request.url.path == "/en/category/roles/":
            return httpx.Response(200, text="<html><body></body></html>")
        return httpx.Response(404)
    assert m.fetch_hashkey(client(handler), "HashKey Group", "hashkey") == []


def test_hashkey_repeated_page_stops_and_duplicates_collapse():
    calls = []
    def handler(request):
        calls.append(request.url.path)
        if "/roles/" in request.url.path and "category" in request.url.path:
            return httpx.Response(200, text=fx("hashkey_list_p1.html"))  # every page identical
        return httpx.Response(200, text=fx("hashkey_detail.html"))
    jobs = m.fetch_hashkey(client(handler), "HashKey Group", "hashkey")
    assert [j.source_id for j in jobs] == ["hashkey:15434", "hashkey:14859"]
    assert calls.count("/en/category/roles/page/2/") == 1


def test_hashkey_description_missing_is_empty():
    assert m.parse_hashkey_description("<html><h3>Other</h3></html>") == ""


def test_hashkey_bad_card_raises():
    with pytest.raises(ValueError):
        m.parse_hashkey_listing('<div class="e-loop-item post-1"></div>')


# ── Hong Kong Life Insurance ──────────────────────────────────────────────────

def _hklife_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("index.html"):
        return httpx.Response(200, text=fx("hong-kong-life-insurance-limited_list.html"))
    return httpx.Response(200, text=fx("hong-kong-life-insurance-limited_detail.html"))


def test_hklife_listing_parse():
    rows = m.parse_hklife_listing(fx("hong-kong-life-insurance-limited_list.html"))
    assert len(rows) == 10
    first = rows[0]
    assert first["id"] == "1170" and first["department"] == "Business Development Department"
    assert first["url"] == "https://www.hklife.com.hk/en/join-us/index-id-1170.html"
    assert first["date"] == "07-01-2025"


def test_hklife_date_parse():
    assert m.parse_hklife_date("19-08-2026") == datetime(2026, 8, 19, tzinfo=UTC)
    assert m.parse_hklife_date("garbage") is None


def test_hklife_fetch_maps_fields():
    jobs = m.fetch_hklife(client(_hklife_handler), "Hong Kong Life Insurance", "hong-kong-life-insurance-limited")
    assert len(jobs) == 10
    j = next(x for x in jobs if x.source_id.endswith(":1255"))
    assert j.source_id == "hong-kong-life-insurance-limited:1255"
    assert j.title == "Contract Analyst Programmer" and j.department == "IT Department"
    assert j.locations == ["Hong Kong"]
    assert j.posted_at == datetime(2026, 8, 19, tzinfo=UTC) and j.posted_at.tzinfo is not None
    assert "Responsibilities" in j.description_clean and "Apply Now" not in j.description_clean
    assert "Share this job" not in j.description_raw and "<h2>" not in j.description_raw


def test_hklife_duplicate_ids_collapse():
    page = fx("hong-kong-life-insurance-limited_list.html")
    doubled = page.replace('<div class="accordionItem">', '<div class="accordionItem">', 1)
    rows = m.parse_hklife_listing(doubled + doubled)
    assert len({r["id"] for r in rows}) == 10 and len(rows) >= 10
    def handler(request):
        if request.url.path.endswith("index.html"):
            return httpx.Response(200, text=page.replace("1262", "1255"))  # 1262 now duplicates 1255
        return _hklife_handler(request)
    jobs = m.fetch_hklife(client(handler), "H", "hong-kong-life-insurance-limited")
    assert len(jobs) == 9


def test_hklife_empty_list_and_changed_template():
    empty = '<html><div id="joinUsJobs"></div></html>'
    assert m.fetch_hklife(client(lambda r: httpx.Response(200, text=empty)), "H", "h") == []
    with pytest.raises(ValueError):
        m.fetch_hklife(client(lambda r: httpx.Response(200, text="<html></html>")), "H", "h")


# ── Wizpresso ─────────────────────────────────────────────────────────────────

def _wizpresso_handler(requests=None, p1=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(str(request.url))
        if request.url.path == "/":
            page = request.url.params.get("page", "1")
            if page == "1":
                return httpx.Response(200, text=p1 or fx("wizpresso_list_p1.html"))
            if page == "2":
                return httpx.Response(200, text=fx("wizpresso_list_p2.html"))
            return httpx.Response(200, text="<html><body></body></html>")
        return httpx.Response(200, text=fx("wizpresso_detail.html"))
    return handler


def test_wizpresso_listing_parse():
    rows = m.parse_wizpresso_listing(fx("wizpresso_list_p1.html"))
    assert len(rows) == 10
    assert rows[0]["id"] == "50074e65-3702-48ae-9336-934110b666f6"
    assert rows[0]["title"] == "DevOps and Site Reliability Engineer"
    assert rows[0]["url"] == "https://wizpresso.careers-page.com/jobs/50074e65-3702-48ae-9336-934110b666f6"
    assert all(m.is_wizpresso_hong_kong(r) for r in rows)


def test_wizpresso_fetch_paginates_to_the_last_page():
    seen: list[str] = []
    jobs = m.fetch_wizpresso(client(_wizpresso_handler(seen)), "Wizpresso", "wizpresso")
    assert len(jobs) == 11 and len({j.source_id for j in jobs}) == 11
    assert sum(1 for u in seen if "page=" in u) == 2  # stops at "Page 2 of 2"
    j = jobs[0]
    assert j.source_id == "wizpresso:50074e65-3702-48ae-9336-934110b666f6"
    assert j.locations == ["Hong Kong"] and j.posted_at is None and j.department is None
    assert j.description_raw and "<" not in j.description_clean and j.description_clean


def test_wizpresso_non_hong_kong_filtered():
    p1 = fx("wizpresso_list_p1.html").replace('data-job-country="Hong Kong"', 'data-job-country="Singapore"', 1)
    p1 = p1.replace('data-job-city="Hong Kong"', 'data-job-city="Singapore"', 1)
    jobs = m.fetch_wizpresso(client(_wizpresso_handler(p1=p1)), "Wizpresso", "wizpresso")
    assert len(jobs) == 10


def test_wizpresso_empty_board():
    empty = "<html><body><p>0 Open Positions</p></body></html>"
    assert m.fetch_wizpresso(client(lambda r: httpx.Response(200, text=empty)), "W", "wizpresso") == []


def test_wizpresso_duplicate_ids_collapse_and_inconsistent_total_raises():
    def handler(request):
        if request.url.path == "/":
            return httpx.Response(200, text=fx("wizpresso_list_p1.html").replace("Page 1 of 2", ""))
        return httpx.Response(200, text=fx("wizpresso_detail.html"))
    # every page repeats page 1: it must stop, then notice 10 collected != 11 advertised
    with pytest.raises(ValueError):
        m.fetch_wizpresso(client(handler), "W", "wizpresso")


def test_get_backs_off_on_429_then_succeeds():
    calls = []
    def handler(request):
        calls.append(1)
        return httpx.Response(429, headers={"retry-after": "1"}) if len(calls) == 1 else httpx.Response(200, text="ok")
    assert m._get(client(handler), "https://example.com/").text == "ok" and len(calls) == 2
