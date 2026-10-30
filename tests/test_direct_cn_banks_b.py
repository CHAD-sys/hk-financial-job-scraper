"""Bank of Communications (HK) and Minsheng Bank extractors, on pages recorded 30 Oct 2026."""

import json
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from hk_jobs.adapters import direct_cn_banks_b as mod
from hk_jobs.adapters.direct_cn_banks_b import (
    SITE_FETCHERS,
    fetch_bocom,
    fetch_minsheng,
    is_hong_kong_region,
    parse_bocom_page,
)

FIXTURES = Path(__file__).parent / "fixtures" / "direct_sites"


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)


def test_registered_under_target_slugs():
    assert set(SITE_FETCHERS) == {"bank-of-communications", "minsheng-bank"}


# ── Bank of Communications ────────────────────────────────────────────────────

_RETAIL = (FIXTURES / "bank-of-communications_retail.html").read_text()
_EMPTY = (FIXTURES / "bank-of-communications_empty.html").read_text()


def test_bocom_maps_fields():
    jobs = parse_bocom_page(_RETAIL, "2005784", "Retail Banking", "Bank of Communications", "bank-of-communications")
    assert [j.title for j in jobs][0] == "Branch Operations Manager"
    assert len(jobs) == 3
    j = jobs[0]
    assert j.source == "direct_site" and j.source_id == "bank-of-communications:2005784:J_001"
    assert j.url.endswith("/2005784/list.shtml#J001")
    assert j.locations == ["Hong Kong"] and j.department == "Retail Banking"
    assert j.posted_at is None and j.scraped_under_slug == "bank-of-communications"
    assert "Duties" in j.description_clean and "<" not in j.description_clean


def test_bocom_inconsistent_page_raises():
    broken = _RETAIL.replace('id="J_003"', 'id="J_099"')
    with pytest.raises(ValueError):
        parse_bocom_page(broken, "2005784", "Retail Banking", "B", "b")


def test_bocom_fetch_all_departments_and_empty_pages():
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(200, text=_RETAIL if "/2005784/" in request.url.path else _EMPTY)

    jobs = fetch_bocom(httpx.Client(transport=httpx.MockTransport(handler)), "Bank of Communications", "bank-of-communications")
    assert len(seen) == 7 and len(jobs) == 3


def test_bocom_duplicate_ids_collapse():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=_RETAIL)))
    # the same page served for every department -> channel is part of the id, so 7 x 3
    assert len(fetch_bocom(client, "B", "b")) == 21
    dup = _RETAIL.replace("</table>", "</table>")  # same ids repeated inside one page collapse
    two = dup.replace("<body>", "<body>" + _RETAIL.split("<body>")[1].split("</body>")[0])
    assert len(parse_bocom_page(two, "1", "d", "B", "b")) == 3


def test_bocom_http_error_propagates():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403)))
    with pytest.raises(httpx.HTTPStatusError):
        fetch_bocom(client, "B", "b")


# ── Minsheng ──────────────────────────────────────────────────────────────────

_LIST = json.loads((FIXTURES / "minsheng-bank_list.json").read_text())
_DETAILS = json.loads((FIXTURES / "minsheng-bank_details.json").read_text())
_ITEMS = _LIST["data"]["items"]
_HK = [i for i in _ITEMS if is_hong_kong_region(i)]


def _handler(pages=None, calls=None):
    pages = pages or [_LIST]

    def handler(request):
        if calls is not None:
            calls.append((request.method, request.url.path))
        if request.method == "POST":
            form = dict(p.split("=") for p in request.content.decode().split("&"))
            assert form["view"] == "careerRecruitmentList"
            return httpx.Response(200, json=pages[min(int(form["pageNo"]), len(pages)) - 1])
        job_id = request.url.path.rsplit("/", 1)[1].removesuffix(".view")
        assert request.url.params["view"] == "careerRecruitmentView"
        return httpx.Response(200, json=_DETAILS.get(job_id, next(iter(_DETAILS.values()))))

    return handler


def test_minsheng_region_filter():
    assert len(_ITEMS) > len(_HK) > 0
    assert is_hong_kong_region({"careerRecruitment_regions_name": "香港"})
    assert not is_hong_kong_region({"careerRecruitment_regions_name": "宝鸡,西安"})
    assert is_hong_kong_region({"careerRecruitment_regions_name": "深圳,香港"})
    assert not is_hong_kong_region({})


def test_minsheng_maps_fields():
    client = httpx.Client(transport=httpx.MockTransport(_handler()))
    jobs = fetch_minsheng(client, "China Minsheng Bank", "minsheng-bank")
    assert len(jobs) == len(_HK)
    j = next(j for j in jobs if j.source_id.endswith("cb34b901-cf79-4e27-adf3-ad9be304cc32"))
    assert j.source == "direct_site" and j.source_id.startswith("minsheng-bank:")
    assert j.url.endswith("/recruitmentview/cb34b901-cf79-4e27-adf3-ad9be304cc32")
    assert j.title == "运营支持岗-财富管理部" and j.locations == ["Hong Kong"]
    assert j.department == "运营合规管理" and j.scraped_under_slug == "minsheng-bank"
    assert j.posted_at.utcoffset() == timedelta(hours=8) and j.posted_at.date().isoformat() == "2026-09-21"
    assert "Operations Support" in j.description_clean and "<" not in j.description_clean


def test_minsheng_paginates_until_last_page_and_dedups():
    page1 = {**_LIST, "data": {**_LIST["data"], "items": _ITEMS[:5], "pageCount": 2}}
    page2 = {**_LIST, "data": {**_LIST["data"], "items": _ITEMS[3:], "pageCount": 2}}  # overlaps page 1
    calls = []
    jobs = fetch_minsheng(httpx.Client(transport=httpx.MockTransport(_handler([page1, page2], calls))), "M", "m")
    assert len(jobs) == len(_HK) and len({j.source_id for j in jobs}) == len(jobs)
    assert sum(m == "POST" for m, _ in calls) == 2


def test_minsheng_stops_on_repeated_page():
    page = {**_LIST, "data": {**_LIST["data"], "pageCount": 99}}
    calls = []
    fetch_minsheng(httpx.Client(transport=httpx.MockTransport(_handler([page], calls))), "M", "m")
    assert sum(m == "POST" for m, _ in calls) == 2  # page 2 repeats page 1 -> stop


def test_minsheng_empty_and_non_hk_only():
    empty = {**_LIST, "data": {**_LIST["data"], "items": []}}
    assert fetch_minsheng(httpx.Client(transport=httpx.MockTransport(_handler([empty]))), "M", "m") == []
    non_hk = {**_LIST, "data": {**_LIST["data"], "items": [i for i in _ITEMS if i not in _HK]}}
    assert fetch_minsheng(httpx.Client(transport=httpx.MockTransport(_handler([non_hk]))), "M", "m") == []


def test_minsheng_api_error_raises():
    client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"success": False, "messages": ["必须指定视图ID"]}))
    )
    with pytest.raises(ValueError):
        fetch_minsheng(client, "M", "m")
