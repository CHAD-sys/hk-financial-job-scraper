"""CMB Wing Lung, Ping An and CCB (Asia) fetchers, against responses recorded 30 Oct 2026."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from hk_jobs.adapters import direct_cn_banks_a as m

FIXTURES = Path(__file__).parent / "fixtures" / "direct_sites"
HKT = timezone(timedelta(hours=8))


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(m, "_SLEEP", 0)


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_registered_slugs():
    assert set(m.SITE_FETCHERS) == {"cmb-wing-lung", "china-merchants-bank", "ping-an", "ccb-asia"}
    assert m.SITE_FETCHERS["china-merchants-bank"] is m.SITE_FETCHERS["cmb-wing-lung"]


# ── CMB ──────────────────────────────────────────────────────────────────────

def _cmb():
    data = json.loads((FIXTURES / "cmb-wing-lung_list.json").read_text())
    data["Result"]["total"] = len(data["Result"]["list"])  # fixture is a trimmed single page
    return data


def test_cmb_field_mapping():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_cmb(), headers={"X-Csrf-Token": "tok"})

    jobs = m.fetch_cmb(_client(handler), "CMB Wing Lung Bank", "cmb-wing-lung")
    rows = _cmb()["Result"]["list"]
    assert len(jobs) == 3 and seen["body"]["pageIndex"] == 1
    j = jobs[0]
    assert j.source == "direct_site" and j.scraped_under_slug == "cmb-wing-lung"
    assert j.source_id == f"cmb-wing-lung:{rows[0]['publishId']}"
    assert j.title == rows[0]["positionDisplay"].strip()
    assert j.locations == ["Hong Kong"] and j.department == rows[0]["deptName"]
    assert j.url.endswith(f"publishId={rows[0]['publishId']}")
    assert "<" not in j.description_clean and j.description_clean and "<" in j.description_raw
    assert j.posted_at == datetime.strptime(rows[0]["publishTime"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=HKT)
    assert j.employment_type in {"full-time", "contract"}


def test_cmb_echoes_csrf_token_and_retries_after_a_bounce():
    calls = []

    def handler(request):
        calls.append(request.headers.get("x-csrf-token"))
        if len(calls) == 1:
            return httpx.Response(302, headers={"Location": "https://x/", "X-Csrf-Token": "abc"})
        return httpx.Response(200, json=_cmb())

    jobs = m.fetch_cmb(_client(handler), "C", "cmb-wing-lung")
    assert calls == [None, "abc"] and len(jobs) == 3


def test_cmb_pagination_ends_and_duplicates_collapse():
    rows = _cmb()["Result"]["list"]
    pages = {1: rows[:2], 2: [rows[1], rows[2]], 3: []}

    def handler(request):
        page = json.loads(request.content)["pageIndex"]
        return httpx.Response(200, json={"Result": {"total": 3, "list": pages[page]}})

    jobs = m.fetch_cmb(_client(handler), "C", "c")
    assert [j.source_id.split(":")[1] for j in jobs] == [r["publishId"] for r in rows]


def test_cmb_stops_when_a_page_repeats():
    rows = _cmb()["Result"]["list"]
    n = []

    def handler(request):
        n.append(1)
        return httpx.Response(200, json={"Result": {"total": 99, "list": rows}})

    assert len(m.fetch_cmb(_client(handler), "C", "c")) == 3 and len(n) == 2


def test_cmb_empty_and_inconsistent():
    ok = _client(lambda r: httpx.Response(200, json={"Result": {"total": 0, "list": []}}))
    assert m.fetch_cmb(ok, "C", "c") == []
    bad = _client(lambda r: httpx.Response(200, json={"Result": {"total": 5, "list": []}}))
    with pytest.raises(ValueError):
        m.fetch_cmb(bad, "C", "c")
    shape = _client(lambda r: httpx.Response(200, json={"Code": 500}))
    with pytest.raises(ValueError):
        m.fetch_cmb(shape, "C", "c")


# ── Ping An ──────────────────────────────────────────────────────────────────

def _pa():
    return json.loads((FIXTURES / "ping-an_list.json").read_text())


def test_pingan_mapping_and_hk_filter():
    data = _pa()
    macau = dict(data["data"]["list"][0], positionId="MACAU1", addressCode="0/4/1/2", addressName="澳门")
    data["data"]["list"].append(macau)
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=data)

    jobs = m.fetch_pingan(_client(handler), "Ping An", "ping-an")
    first = _pa()["data"]["list"][0]
    assert seen["body"]["addressCode"] == m.PINGAN_HK_CODE
    assert len(jobs) == 3 and "ping-an:MACAU1" not in {j.source_id for j in jobs}
    j = jobs[0]
    assert j.source_id == f"ping-an:{first['positionId']}" and j.title == first["positionShowName"].strip()
    assert j.locations == ["Hong Kong"] and j.posted_at is None
    assert j.department == f"{first['businessUnitName']} / {first['structureShowName']}"
    assert first["duty"].split("\n")[0] in j.description_clean
    assert j.url.endswith(f"positionId={first['positionId']}")


def test_pingan_pagination_end_and_duplicates():
    rows = _pa()["data"]["list"]

    def handler(request):
        n = json.loads(request.content)["pageNum"]
        page = {1: rows[:2], 2: [rows[1], rows[2]]}.get(n, [])
        return httpx.Response(200, json={"data": {"totalPage": 2, "totalCount": 3, "list": page}})

    jobs = m.fetch_pingan(_client(handler), "P", "ping-an")
    assert [j.source_id for j in jobs] == [f"ping-an:{r['positionId']}" for r in rows]


def test_pingan_empty_and_bad_shape():
    empty = _client(lambda r: httpx.Response(200, json={"data": {"totalPage": 0, "list": []}}))
    assert m.fetch_pingan(empty, "P", "ping-an") == []
    with pytest.raises(ValueError):
        m.fetch_pingan(_client(lambda r: httpx.Response(200, json={"data": None})), "P", "ping-an")


# ── CCB (Asia) ───────────────────────────────────────────────────────────────

def _ccb_handler(listing=None, missing=()):
    listing = listing or (FIXTURES / "ccb-asia_list.html").read_text()
    details = {
        "CB/WM/PA": (FIXTURES / "ccb-asia_detail_cbwmpa.html").read_text(),
        "TM AM": (FIXTURES / "ccb-asia_detail_tmam.html").read_text(),
    }
    requested = []

    def handler(request):
        if request.url.path.endswith("CareerOpportunityController.jpf"):
            return httpx.Response(200, text=listing)
        ref = request.url.params["posno"]
        requested.append(ref)
        if ref in missing or ref not in details:
            return httpx.Response(404)
        return httpx.Response(200, text=details[ref])

    return handler, requested


def test_ccb_listing_parse():
    rows = m.parse_ccb_listing((FIXTURES / "ccb-asia_list.html").read_text())
    assert [r["ref"] for r in rows] == ["CMB/SRM", "CB/WM/PA", "TM AM"]
    assert rows[1] == {
        "ref": "CB/WM/PA", "title": "Portfolio Advisor", "department": "Consumer Banking",
        "location": "Hong Kong", "status": "F",
    }


def test_ccb_fetch_mapping():
    handler, requested = _ccb_handler()
    jobs = m.fetch_ccb(_client(handler), "CCB (Asia)", "ccb-asia")
    by_id = {j.source_id: j for j in jobs}
    assert set(by_id) == {"ccb-asia:CB/WM/PA", "ccb-asia:TM AM"}  # CMB/SRM detail 404s and is skipped
    assert "TM AM" in requested  # refs are passed through params, verbatim
    j = by_id["ccb-asia:CB/WM/PA"]
    assert j.title == "Portfolio Advisor" and j.department == "Consumer Banking"
    assert j.employment_type == "full-time" and j.locations == ["Hong Kong"]
    assert j.posted_at == datetime(2025, 12, 30, tzinfo=HKT)
    assert "posno=CB%2FWM%2FPA" in j.url or "posno=CB/WM/PA" in j.url
    assert "Drive sales activities" in j.description_clean and "recruithk@asia.ccb.com" in j.description_clean
    assert "Applicants who are not contacted" not in j.description_clean
    assert "<br>" in j.description_raw.lower()


def test_ccb_filters_non_hk_and_collapses_duplicates():
    listing = (FIXTURES / "ccb-asia_list.html").read_text()
    # relabel the TM AM row as Macau, and repeat the CB/WM/PA row
    start = listing.index("OpenDetailWindow('TM AM')")
    listing = listing[:start] + listing[start:].replace('DisplayValue("Hong Kong")', 'DisplayValue("Macau")', 1)
    row_start = listing.rindex("<tr>", 0, listing.index("OpenDetailWindow('CB/WM/PA')"))
    row_end = listing.index("</tr>", row_start) + 5
    listing = listing.replace("</table>", listing[row_start:row_end] + "</table>")
    handler, requested = _ccb_handler(listing)
    jobs = m.fetch_ccb(_client(handler), "CCB", "ccb-asia")
    assert [j.source_id for j in jobs] == ["ccb-asia:CB/WM/PA"]
    assert requested.count("CB/WM/PA") == 1 and "TM AM" not in requested


def test_ccb_empty_listing():
    handler, requested = _ccb_handler("<html><body><div id='main'></div></body></html>")
    assert m.fetch_ccb(_client(handler), "CCB", "ccb-asia") == [] and requested == []
