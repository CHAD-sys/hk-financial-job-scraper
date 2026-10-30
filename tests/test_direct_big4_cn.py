"""Deloitte China and KPMG China (Hong Kong) fetchers, against responses recorded 30 Oct 2026."""

import copy
import json
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from hk_jobs.adapters import direct_big4_cn as m

FIXTURES = Path(__file__).parent / "fixtures" / "direct_sites"


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(m.time, "sleep", lambda _s: None)


def _load(name):
    return json.loads((FIXTURES / name).read_text())


def test_registered_slugs():
    assert set(m.SITE_FETCHERS) == {"deloitte", "kpmg"}


# ── AES ───────────────────────────────────────────────────────────────────────

def test_aes_matches_fips_197_vector():
    key = bytes(range(16))
    cipher = bytes.fromhex("69c4e0d86a7b0430d8cdb78070b4c55a")
    block = m._decrypt_block(cipher, m._expand_key(key))
    assert block.hex() == "00112233445566778899aabbccddeeff"


def test_aes_rejects_wrong_key():
    payload = _load("kpmg_jobs_last.json")
    import base64

    with pytest.raises(ValueError):
        m.aes128_cbc_decrypt(base64.b64decode(payload["data"]), b"0" * 16, b"1" * 16)


# ── Deloitte ──────────────────────────────────────────────────────────────────

def _deloitte_client(list_pages, details, calls=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(request.url))
        form = dict(x.split("=", 1) for x in request.content.decode().split("&"))
        if "/listPosition/" in request.url.path:
            assert form["workPlaceCode"].replace("%2F", "/") == m.DELOITTE_HK_CODE
            return httpx.Response(200, json=list_pages[int(form["currentPage"]) - 1])
        return httpx.Response(200, json=details[form["postId"]])

    return httpx.Client(transport=httpx.MockTransport(handler))


def _deloitte_fixture():
    listing = _load("deloitte_list.json")
    rows = listing["data"]["pageForm"]["pageData"]
    details = {r["postId"]: d for r, d in zip(rows, _load("deloitte_details.json"))}
    return listing, rows, details


def test_deloitte_maps_fields():
    listing, rows, details = _deloitte_fixture()
    jobs = m.fetch_deloitte(_deloitte_client([listing], details), "Deloitte", "deloitte")
    assert len(jobs) == 3
    job = jobs[0]
    assert job.source == "direct_site" and job.company_slug == "deloitte"
    assert job.scraped_under_slug == "deloitte"
    assert job.source_id == f"deloitte:{rows[0]['postId']}"
    assert job.url == (
        f"https://ehjobs.deloitte.com.cn/SU649e304a6a9f0ef690533e9a/pb/posDetail.html?postId={rows[0]['postId']}&postType=society"
    )
    assert job.title == rows[0]["postName"].strip()
    assert job.locations == ["Hong Kong"]
    assert job.department == rows[0]["postTypeName"]
    assert "<" in job.description_raw and "<" not in job.description_clean
    assert len(job.description_clean) > 500
    assert job.posted_at.utcoffset() == timedelta(hours=8)
    assert (job.posted_at.year, job.posted_at.month, job.posted_at.day) == (2026, 10, 29)


def test_deloitte_drops_non_hong_kong_workplace():
    listing, rows, details = _deloitte_fixture()
    details = copy.deepcopy(details)
    details[rows[1]["postId"]]["data"]["workPlaceList"] = [{"code": "0/4/596/538137608", "name": "Macao"}]
    jobs = m.fetch_deloitte(_deloitte_client([listing], details), "Deloitte", "deloitte")
    assert [j.source_id.split(":")[1] for j in jobs] == [rows[0]["postId"], rows[2]["postId"]]


def test_deloitte_hk_check_prefers_code_over_label():
    assert m.deloitte_is_hong_kong({"workPlaceStr": "Hong Kong"})
    assert not m.deloitte_is_hong_kong({"workPlaceStr": "All Regions"})
    assert m.deloitte_is_hong_kong(
        {"workPlaceStr": "All Regions"}, {"workPlaceList": [{"code": m.DELOITTE_HK_CODE, "name": "Hong Kong"}]}
    )
    assert m.deloitte_is_hong_kong(
        {}, {"workPlaceList": json.dumps([{"code": m.DELOITTE_HK_CODE, "name": "Hong Kong"}])}
    )


def test_deloitte_paginates_until_last_page_and_collapses_duplicates():
    listing, rows, details = _deloitte_fixture()
    page1 = copy.deepcopy(listing)
    page2 = copy.deepcopy(listing)
    page1["data"]["pageForm"].update(totalPage=2, dataCount=3, pageData=rows[:2])
    page2["data"]["pageForm"].update(totalPage=2, currentPage=2, dataCount=3, pageData=[rows[1], rows[2]])
    calls = []
    jobs = m.fetch_deloitte(_deloitte_client([page1, page2], details, calls), "Deloitte", "deloitte")
    assert len({j.source_id for j in jobs}) == len(jobs) == 3
    assert sum("/listPosition/" in c for c in calls) == 2


def test_deloitte_inconsistent_listing_raises():
    listing, rows, details = _deloitte_fixture()
    bad = copy.deepcopy(listing)
    bad["data"]["pageForm"].update(totalPage=1, dataCount=9)
    with pytest.raises(ValueError):
        m.fetch_deloitte(_deloitte_client([bad], details), "Deloitte", "deloitte")


def test_deloitte_empty_result():
    empty = {"data": {"pageForm": {"totalPage": 0, "pageSize": 50, "currentPage": 1, "dataCount": 0, "pageData": []}}}
    assert m.fetch_deloitte(_deloitte_client([empty], {}), "Deloitte", "deloitte") == []


# ── KPMG ──────────────────────────────────────────────────────────────────────

def _kpmg_client(job_pages, facets=None, iv_html=None):
    """job_pages: list of response bodies indexed by offset // 15."""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, text=iv_html or (FIXTURES / "kpmg_site.html").read_text())
        body = json.loads(request.content)
        seen.append(body)
        if request.url.path.endswith("filterFieldsAggregations"):
            return httpx.Response(200, json=facets or _load("kpmg_facets.json"))
        assert body["limit"] == 15
        idx = body["offset"] // 15
        return httpx.Response(200, json=job_pages[idx] if idx < len(job_pages) else {"data": {"jobs": []}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    client.seen = seen
    return client


def test_kpmg_decrypts_real_response_and_maps_fields():
    client = _kpmg_client([_load("kpmg_jobs_last.json")])
    jobs = m.fetch_kpmg(client, "KPMG", "kpmg")
    assert len(jobs) == 2  # a 2-row page ends pagination
    job = jobs[0]
    assert job.source == "direct_site" and job.company_slug == "kpmg" and job.scraped_under_slug == "kpmg"
    assert job.source_id.startswith("kpmg:") and job.url.endswith("#/job/" + job.source_id.split(":", 1)[1])
    assert job.url.startswith("https://app.mokahr.com/social-recruitment/kpmg/74216#/job/")
    assert job.title == job.title.strip() and job.title
    assert job.locations == ["Hong Kong"]
    assert "<" in job.description_raw and "<" not in job.description_clean
    assert job.posted_at is not None and job.posted_at.tzinfo is not None
    assert job.department is None
    # the request used the Hong Kong location facet, not a hard-coded id list
    assert client.seen[-1]["locationIds"] == [310042, 312430, 374002, 384413]


def _plain_pages(n_full, tail):
    jobs = _load("kpmg_jobs_plain.json")["jobs"]
    pages = []
    for p in range(n_full):
        rows = []
        for i in range(15):
            row = copy.deepcopy(jobs[i % 3])
            row["id"] = f"job-{p}-{i}"
            rows.append(row)
        pages.append({"data": {"jobs": rows}})
    pages.append({"data": {"jobs": [dict(copy.deepcopy(jobs[0]), id=f"tail-{i}") for i in range(tail)]}})
    return pages


@pytest.fixture
def plain_unwrap(monkeypatch):
    monkeypatch.setattr(m, "moka_unwrap", lambda payload, iv: payload["data"])


def test_kpmg_paginates_until_short_page(plain_unwrap):
    client = _kpmg_client(_plain_pages(2, 4), facets={"data": _load("kpmg_facets.json")["data"]})
    jobs = m.fetch_kpmg(client, "KPMG", "kpmg")
    assert len(jobs) == 34
    assert [b["offset"] for b in client.seen if "limit" in b] == [0, 15, 30]


def test_kpmg_duplicate_ids_collapse_and_repeat_page_stops(plain_unwrap):
    page = _plain_pages(1, 0)[0]
    page["data"]["jobs"].append(copy.deepcopy(page["data"]["jobs"][0]))  # duplicate id in one page
    page["data"]["jobs"].pop(1)
    client = _kpmg_client([page, page, page, page])
    jobs = m.fetch_kpmg(client, "KPMG", "kpmg")
    assert len(jobs) == len({j.source_id for j in jobs}) == 14
    assert len([b for b in client.seen if "limit" in b]) == 2  # second page repeated -> stop


def test_kpmg_filters_non_hong_kong_locations(plain_unwrap):
    page = _plain_pages(0, 3)[0]
    page["data"]["jobs"][1]["locations"] = [{"country": "China", "provinceName": "Guangdong", "cityName": "Foshan", "cityId": 440600}]
    jobs = m.fetch_kpmg(_kpmg_client([page]), "KPMG", "kpmg")
    assert len(jobs) == 2
    assert m.kpmg_is_hong_kong({"locations": [{"cityId": 810000}]})
    assert not m.kpmg_is_hong_kong({"locations": []})


def test_kpmg_empty_result(plain_unwrap):
    assert m.fetch_kpmg(_kpmg_client([{"data": {"jobs": []}}]), "KPMG", "kpmg") == []


def test_kpmg_no_hong_kong_facet_returns_nothing():
    facets = {"data": {"systemFieldsAggregations": {"locationAggregation": {"locationList": []}}}}
    assert m.fetch_kpmg(_kpmg_client([], facets=facets), "KPMG", "kpmg") == []


def test_kpmg_missing_iv_raises():
    with pytest.raises(ValueError):
        m.fetch_kpmg(_kpmg_client([], iv_html="<html></html>"), "KPMG", "kpmg")
