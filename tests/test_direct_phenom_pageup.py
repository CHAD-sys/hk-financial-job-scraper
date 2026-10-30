"""Allianz / QBE (Phenom), BOCHK (PageUp) and Amundi HK (Talentsoft), against recorded feeds."""

import copy
import json
from pathlib import Path

import httpx
import pytest

from hk_jobs.adapters import direct_phenom_pageup as mod
from hk_jobs.adapters.direct_phenom_pageup import (
    SITE_FETCHERS,
    fetch_allianz,
    fetch_amundi,
    fetch_bochk,
    fetch_qbe,
    parse_amundi_rss,
    parse_bochk_departments,
    parse_bochk_rss,
    parse_phenom_detail,
    phenom_is_hong_kong,
)

FIXTURES = Path(__file__).parent / "fixtures" / "direct_sites"


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)


def _read(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def _listing(name):
    return json.loads(_read(name))


def _widgets(rows, total=None):
    return {"refineSearch": {"status": 200, "hits": len(rows),
                             "totalHits": len(rows) if total is None else total,
                             "data": {"jobs": rows}}}


def test_all_four_registered():
    assert set(SITE_FETCHERS) == {"allianz", "qbe", "bochk", "amundi-hk"}


# ── Phenom: Allianz ───────────────────────────────────────────────────────────

def _phenom_client(listing_pages, details, seen=None):
    """listing_pages: list of widgets payloads served in order by `from` offset."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            body = json.loads(request.content)
            if seen is not None:
                seen.append(body)
            size = len(listing_pages[0]["refineSearch"]["data"]["jobs"]) or 1
            index = body["from"] // size if body["from"] else 0
            if index >= len(listing_pages):
                return httpx.Response(200, json=_widgets([], total=0))
            return httpx.Response(200, json=listing_pages[index])
        job_id = request.url.path.split("/job/")[1]
        page = details.get(job_id)
        return httpx.Response(200, text=page) if page else httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_allianz_maps_fields_and_keeps_multi_location_roles():
    seen = []
    client = _phenom_client(
        [_listing("allianz_widgets_hk.json")], {"108904": _read("allianz_detail_108904.html")}, seen
    )
    jobs = {j.source_id: j for j in fetch_allianz(client, "Allianz", "allianz")}
    assert len(jobs) == 4
    assert seen[0]["selected_fields"] == {"country": ["Hong Kong, China"]}
    multi = jobs["allianz:108904"]  # primary city is Frankfurt, Hong Kong is one of four offices
    assert multi.source == "direct_site" and multi.scraped_under_slug == "allianz"
    assert multi.url == "https://careers.allianz.com/global/en/job/108904"
    assert multi.title == "Data Product Owner (f/m/d) - Vendor Market Data"
    assert multi.locations[0] == "Hong Kong" and "Singapore, Singapore" not in multi.locations
    assert multi.department == "Data & AI" and multi.employment_type == "full-time"
    assert multi.posted_at.isoformat() == "2026-10-27T13:46:28+00:00"  # postedDate, not JSON-LD
    assert "&lt;" not in multi.description_raw and "<" in multi.description_raw
    assert "Investment Data Area" in multi.description_clean and "<p>" not in multi.description_clean
    blank_city = jobs["allianz:108426"]  # primary location is blank
    assert blank_city.locations[0] == "Hong Kong"


def test_allianz_detail_failure_falls_back_to_teaser():
    jobs = fetch_allianz(_phenom_client([_listing("allianz_widgets_hk.json")], {}), "Allianz", "allianz")
    assert len(jobs) == 4 and all(j.description_raw for j in jobs)


def test_phenom_detail_parser_handles_missing_json_ld():
    assert parse_phenom_detail("<html></html>") == {}
    assert parse_phenom_detail('<script type="application/ld+json">{oops</script>') == {}
    detail = parse_phenom_detail(_read("qbe_detail_364000.html"))
    assert detail["title"] == "Specialist Underwriting Governance"


def test_allianz_empty_result():
    client = _phenom_client([_widgets([])], {})
    assert fetch_allianz(client, "Allianz", "allianz") == []


def test_phenom_pagination_ends_and_duplicates_collapse():
    rows = _listing("allianz_widgets_hk.json")["refineSearch"]["data"]["jobs"]
    page1 = _widgets(rows[:2], total=4)
    page2 = _widgets(rows[2:] + [copy.deepcopy(rows[2])], total=4)  # duplicate id inside a page
    seen = []
    jobs = fetch_allianz(_phenom_client([page1, page2], {}, seen), "Allianz", "allianz")
    assert sorted(j.source_id for j in jobs) == sorted(f"allianz:{r['jobId']}" for r in rows)
    assert [b["from"] for b in seen] == [0, 2]


def test_phenom_repeated_page_stops_and_inconsistent_total_raises():
    rows = _listing("allianz_widgets_hk.json")["refineSearch"]["data"]["jobs"]
    page = _widgets(rows[:2], total=9)  # claims 9, keeps serving the same 2
    client = _phenom_client([page, page, page], {})
    with pytest.raises(ValueError, match="incomplete"):
        fetch_allianz(client, "Allianz", "allianz")


# ── Phenom: QBE ───────────────────────────────────────────────────────────────

def test_qbe_sweep_filters_on_country_not_facet():
    hk = _listing("qbe_widgets_hk.json")["refineSearch"]["data"]["jobs"][0]
    macau = {**copy.deepcopy(hk), "jobId": "362859", "country": "Macao", "location": "Macau",
             "multi_location": ["Macau"], "city": "Macau"}
    other = {**copy.deepcopy(hk), "jobId": "1", "country": "Australia", "location": "Sydney, Australia",
             "multi_location": ["Sydney, Australia"]}
    seen = []
    client = _phenom_client([_widgets([macau, hk, other])], {"364000": _read("qbe_detail_364000.html")}, seen)
    jobs = fetch_qbe(client, "QBE", "qbe")
    assert seen[0]["selected_fields"] == {} and seen[0]["lang"] == "en_gb"
    assert [j.source_id for j in jobs] == ["qbe:364000"]
    job = jobs[0]
    assert job.url == "https://careers.qbe.com/gb/en/job/364000"
    assert job.locations == ["Quarry Bay, Hong Kong"] and job.department == "Underwriting"
    assert job.posted_at.isoformat() == "2026-10-28T00:00:00+00:00"
    assert job.employment_type == "full-time"
    assert "Primary Details" in job.description_clean


def test_phenom_hong_kong_predicate():
    assert phenom_is_hong_kong({"country": "Hong Kong"})
    assert phenom_is_hong_kong({"country": "", "multi_location": ["Frankfurt, Germany", "Hong Kong, China"]})
    assert not phenom_is_hong_kong({"country": "Macao", "location": "Macau", "multi_location": ["Macau"]})
    assert not phenom_is_hong_kong({})


# ── BOCHK: PageUp RSS ─────────────────────────────────────────────────────────

def test_bochk_rss_mapping():
    jobs = parse_bochk_rss(_read("bochk_rss.xml").encode(), "Bank of China (Hong Kong)", "bochk")
    assert len(jobs) == 8
    assert all(j.source == "direct_site" and j.locations == ["Hong Kong"] for j in jobs)
    assert all(j.url == f"https://careers.pageuppeople.com/798/cw/en/job/{j.source_id.split(':')[1]}"
               for j in jobs)
    by_id = {j.source_id: j for j in jobs}
    boc_life = by_id["bochk:500192"]
    assert boc_life.board_signals["entity"] == "BOC Life"
    job = jobs[0]
    assert job.posted_at is not None and job.posted_at.tzinfo is not None
    assert job.description_raw.lstrip().startswith("<") and "&lt;" not in job.description_raw
    assert len(job.description_clean) > 100 and "<" not in job.description_clean
    assert job.department  # job function when the listing is not consulted
    types = {j.employment_type for j in jobs}
    assert "full-time" in types and None in types  # "Contract,Full time" is ambiguous -> None


def test_bochk_filters_non_hong_kong_and_duplicate_ids():
    xml = _read("bochk_rss.xml")
    first = xml[xml.index("<item>"): xml.index("</item>") + 7]
    elsewhere = first.replace("<job:location>Hong Kong</job:location>",
                              "<job:location>Singapore</job:location>").replace(
        "<job:refNo>", "<job:refNo>9")
    doubled = xml.replace("</channel>", first + elsewhere + "</channel>")
    jobs = parse_bochk_rss(doubled.encode(), "B", "bochk")
    assert len(jobs) == 8  # duplicate id collapsed, Singapore row dropped
    assert not [j for j in jobs if j.source_id.startswith("bochk:9")]


def test_bochk_empty_feed():
    empty = '<?xml version="1.0"?><rss version="2.0"><channel><title/></channel></rss>'
    assert parse_bochk_rss(empty.encode(), "B", "bochk") == []


def test_bochk_listing_departments_and_more_link():
    found, more = parse_bochk_departments(_read("bochk_listing.html"))
    assert len(found) == 2 and not more
    assert all(v for v in found.values())
    _, more = parse_bochk_departments(
        '<table><tbody id="recent-jobs-content"></tbody></table><a class="more-link" href="x">'
    )
    assert more


def test_bochk_fetch_enriches_department_and_survives_listing_failure():
    def make(listing_status):
        def handler(request):
            if request.url.path.endswith("/rss"):
                return httpx.Response(200, content=_read("bochk_rss.xml").encode())
            return httpx.Response(listing_status, text=_read("bochk_listing.html"))
        return httpx.Client(transport=httpx.MockTransport(handler))

    jobs = fetch_bochk(make(200), "B", "bochk")
    depts = parse_bochk_departments(_read("bochk_listing.html"))[0]
    for job in jobs:
        key = job.source_id.split(":")[1]
        if key in depts:
            assert job.department == depts[key]
    assert sum(1 for j in jobs if j.source_id.split(":")[1] in depts) == 2
    assert len(fetch_bochk(make(500), "B", "bochk")) == 8


# ── Amundi: Talentsoft RSS ────────────────────────────────────────────────────

def test_amundi_mapping_leaves_posted_at_none():
    jobs = parse_amundi_rss(_read("amundi_hk_rss.xml").encode(), "Amundi Hong Kong", "amundi-hk")
    assert len(jobs) == 1
    job = jobs[0]
    assert job.source_id == "amundi-hk:109979"
    assert job.title == "Asia Global Fixed Income Investment Specialist H/F"
    assert job.url.startswith("https://jobs.amundi.com/Pages/Offre/detailoffre.aspx?idOffre=109979")
    assert job.locations == ["Hong Kong"] and job.posted_at is None
    assert job.department == "Gestion d'Actifs" and job.employment_type == "full-time"
    assert "<b>" in job.description_raw and "Key Responsibilities" in job.description_clean


def test_amundi_drops_other_countries_and_collapses_duplicates():
    xml = _read("amundi_hk_rss.xml")
    item = xml[xml.index("<item>"): xml.index("</item>") + 7]
    tokyo = item.replace("<category>Hong-Kong</category>", "<category>Japon</category>").replace(
        "idOffre=109979", "idOffre=5")
    doubled = xml.replace("</channel>", item + tokyo + "</channel>")
    jobs = parse_amundi_rss(doubled.encode(), "A", "amundi-hk")
    assert [j.source_id for j in jobs] == ["amundi-hk:109979"]


def test_amundi_empty_and_cap_guard():
    empty = '<?xml version="1.0"?><rss version="2.0"><channel><title/></channel></rss>'
    assert parse_amundi_rss(empty.encode(), "A", "amundi-hk") == []
    xml = _read("amundi_hk_rss.xml")
    item = xml[xml.index("<item>"): xml.index("</item>") + 7]
    full = xml.replace("</channel>", item * 20 + "</channel>")
    with pytest.raises(ValueError, match="cap"):
        parse_amundi_rss(full.encode(), "A", "amundi-hk")


def test_amundi_fetch_sends_country_filter():
    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        return httpx.Response(200, content=_read("amundi_hk_rss.xml").encode())

    jobs = fetch_amundi(httpx.Client(transport=httpx.MockTransport(handler)), "A", "amundi-hk")
    assert len(jobs) == 1 and seen[0]["Rss_JobCountry"] == "1693"
