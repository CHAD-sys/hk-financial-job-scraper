"""UBS (BrassRing), CICC (Beisen) and ICBC (Asia) readers, against responses recorded 28-30 Oct 2026."""

import copy
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from hk_jobs.adapters import direct_ats_misc_b as m

FIXTURES = Path(__file__).parent / "fixtures" / "direct_sites"


def _json(name):
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(m.time, "sleep", lambda s: None)


def test_registry_keys():
    assert set(m.SITE_FETCHERS) == {"ubs-am-hk", "cicc", "icbc-asia"}


# ── UBS ───────────────────────────────────────────────────────────────────────

def _ubs_client(search=None, detail_ids=("352057",), calls=None):
    search = search if search is not None else _json("ubs_am_hk_search.json")
    home = (FIXTURES / "ubs_am_hk_home.html").read_text()

    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request.url.path)
        path = request.url.path
        if path.endswith("/HomeWithPreLoad"):
            return httpx.Response(200, text=home)
        assert request.headers["RFT"]  # the CSRF header is required on every POST
        body = json.loads(request.content)
        if path.endswith("/MatchedJobs"):
            sel = body["FacetFilterFields"]["Facet"][0]["Options"][0]
            assert sel["OptionValue"] == "Hong Kong" and sel["Selected"] is True
            return httpx.Response(200, json=search if body["SiteId"] == "5012" else {"JobsCount": 0, "Jobs": {"Job": []}})
        if path.endswith("/JobDetails"):
            if body["jobid"] in detail_ids:
                return httpx.Response(200, json=_json("ubs_am_hk_detail.json"))
            return httpx.Response(500)
        raise AssertionError(path)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_ubs_maps_hong_kong_rows_and_tags_division():
    jobs = m.fetch_ubs(_ubs_client(), "UBS", "ubs-am-hk")
    assert [j.source_id for j in jobs] == [
        f"ubs-am-hk:{i}" for i in ("352057", "351098", "349894", "346450", "339847")
    ]
    first = jobs[0]
    assert first.source == "direct_site" and first.scraped_under_slug == "ubs-am-hk"
    assert first.title == "Integrated Middle Office Specialist"
    assert first.department == "Group Functions"
    assert first.locations == ["Hong Kong"]
    assert first.url.endswith("siteid=5012&PageType=JobDetails&jobid=352057")
    assert first.posted_at is None  # "last updated" is not a posting date
    assert first.board_signals == {"function": "Operations"}
    assert {j.department for j in jobs} == {"Group Functions", "Investment Bank", "Global Wealth Management"}
    assert not any(j.department == "Asset Management" for j in jobs)  # none in HK today


def test_ubs_multi_location_and_full_description_fallback():
    jobs = {j.source_id.split(":")[1]: j for j in m.fetch_ubs(_ubs_client(), "UBS", "ubs-am-hk")}
    assert jobs["351098"].locations == ["Hong Kong", "Singapore"]
    # 352057 got the full sections; the others fall back to the search summary after a detail 500.
    assert "<h3>Your skills and experience</h3>" in jobs["352057"].description_raw
    assert "Your skills and experience" in jobs["352057"].description_clean
    assert "<h3>" not in jobs["351098"].description_raw and jobs["351098"].description_clean


def test_ubs_drops_non_hong_kong_rows_and_collapses_duplicate_ids():
    rows = copy.deepcopy(_json("ubs_am_hk_search.json")["Jobs"]["Job"])
    singapore = copy.deepcopy(rows[0])
    for q in singapore["Questions"]:
        if q["QuestionName"] == "formtext23":
            q["Value"] = "Singapore "
        if q["QuestionName"] == "reqid":
            q["Value"] = "999"
    jobs = m.parse_ubs_jobs(rows + [singapore, copy.deepcopy(rows[0])], "UBS", "ubs-am-hk")
    assert len(jobs) == 5 and "ubs-am-hk:999" not in {j.source_id for j in jobs}


def test_ubs_empty_result():
    empty = {"JobsCount": 0, "Jobs": {"Job": []}}
    assert m.fetch_ubs(_ubs_client(search=empty), "UBS", "ubs-am-hk") == []


def test_ubs_full_page_or_inconsistent_count_raises():
    search = _json("ubs_am_hk_search.json")
    search["JobsCount"] = 34  # more matches than rows returned
    with pytest.raises(ValueError):
        m.fetch_ubs(_ubs_client(search=search), "UBS", "ubs-am-hk")


def test_ubs_bootstrap_change_raises():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html></html>")))
    with pytest.raises(ValueError):
        m.fetch_ubs(client, "UBS", "ubs-am-hk")


# ── CICC ──────────────────────────────────────────────────────────────────────

def _cicc_client(rows, count_override=None):
    by_cat = {c: [r for r in rows if r["CategoryId"] == str(c)] for c in (1, 3)}
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["PortalId"] == m.CICC_PORTAL and "LocId" in body["DisplayFields"]
        seen.append((body["Category"], body["PageIndex"]))
        pool = by_cat[body["Category"]]
        start = body["PageIndex"] * body["PageSize"]
        page = pool[start : start + body["PageSize"]]
        return httpx.Response(
            200, json={"Code": 200, "Count": count_override or len(pool), "Data": page}
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    client.seen = seen
    return client


def test_cicc_filters_on_the_location_field_not_text():
    rows = _json("cicc_list.json")
    assert len(rows) == 7
    jobs = m.parse_cicc_jobs(rows, "CICC", "cicc")
    assert [j.source_id for j in jobs] == [
        "cicc:151247969", "cicc:151261933", "cicc:151163851", "cicc:150981553",
    ]
    # No row is kept because a description mentions Hong Kong: the location array decides.
    assert all("香港特别行政区" in r["LocNames"] for r in rows if f"cicc:{r['JobAdId']}" in {j.source_id for j in jobs})


def test_cicc_field_mapping():
    jobs = {j.source_id: j for j in m.parse_cicc_jobs(_json("cicc_list.json"), "CICC", "cicc")}
    etf = jobs["cicc:151261933"]
    assert etf.title == "ETF Capital Markets Specialist"  # requisition code removed from the title
    assert etf.board_signals == {"requisition": "J19802"}
    assert etf.url == "https://cicc.zhiye.com/social/detail?jobAdId=" + _json("cicc_list.json")[1]["Id"]
    assert etf.locations == ["Hong Kong"] and etf.department == "资产管理部"
    assert etf.employment_type == "full-time"
    # Portal timestamps are Beijing time: 10:27:03 CST is 02:27:03 UTC.
    assert etf.posted_at == datetime(2026, 10, 12, 2, 27, 3, tzinfo=UTC)
    assert etf.description_clean and etf.description_raw.startswith(_json("cicc_list.json")[1]["Duty"].strip()[:20])
    multi = jobs["cicc:151163851"]
    assert multi.locations[0] == "Hong Kong" and "Beijing" in multi.locations
    intern = jobs["cicc:150981553"]
    assert intern.employment_type == "internship" and "/intern/detail?jobAdId=" in intern.url


def test_cicc_unset_or_future_dates_are_none():
    row = copy.deepcopy(_json("cicc_list.json")[0])
    row["PostDate"] = "0001-01-01T00:00:00"
    assert m.parse_cicc_jobs([row], "CICC", "cicc")[0].posted_at is None
    row["PostDate"] = "2999-01-01T00:00:00"
    assert m.parse_cicc_jobs([row], "CICC", "cicc")[0].posted_at is None


def test_cicc_pagination_covers_both_categories_and_dedupes(monkeypatch):
    monkeypatch.setattr(m, "CICC_PAGE", 2)
    rows = _json("cicc_list.json")
    client = _cicc_client(rows + [copy.deepcopy(rows[0])])  # duplicate Id inside category 1
    # the repeated row makes the portal's Count (6) exceed the distinct rows (5)
    with pytest.raises(ValueError):
        m.fetch_cicc(client, "CICC", "cicc")
    client = _cicc_client(rows)
    jobs = m.fetch_cicc(client, "CICC", "cicc")
    assert len(jobs) == 4
    assert {c for c, _ in client.seen} == {1, 3}
    assert max(p for c, p in client.seen if c == 1) == 2  # 5 social rows, 2 per page -> 3 pages


def test_cicc_empty_result_and_api_error():
    assert m.fetch_cicc(_cicc_client([]), "CICC", "cicc") == []
    bad = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"Code": 500})))
    with pytest.raises(ValueError):
        m.fetch_cicc(bad, "CICC", "cicc")


# ── ICBC (Asia) ───────────────────────────────────────────────────────────────

def test_icbc_maps_a_category_and_ids_are_stable_across_parses():
    data = _json("icbc_asia_financial_technology.json")
    first = m.parse_icbc_category(data, "financial_technology", "ICBC (Asia)", "icbc-asia")
    again = m.parse_icbc_category(json.loads(json.dumps(data)), "financial_technology", "ICBC (Asia)", "icbc-asia")
    assert [j.source_id for j in first] == [j.source_id for j in again]
    assert len(first) == 11 and len({j.source_id for j in first}) == 11
    job = next(j for j in first if j.title == "Programmer / Analyst Programmer")
    assert job.source_id == "icbc-asia:p014:programmer-analyst-programmer"
    assert job.source == "direct_site" and job.locations == ["Hong Kong"]
    assert job.department == "Financial Technology Department"
    assert job.url == "https://www.icbcasia.com/hk/en/about-us/career-opportunities/financial-technology.html"
    assert job.posted_at is None
    assert "Job Responsibilities" in job.description_clean and "hrd@icbcasia.com" in job.description_clean


def test_icbc_repeated_titles_get_a_body_hash_and_empty_titles_are_skipped():
    data = {
        "items": [
            {
                "id": "p9",
                "name": "Dept",
                "children": [
                    {"name": "Senior Officer", "ans": "<p>A</p>"},
                    {"name": "Senior Officer ", "ans": "<p>B</p>"},
                    {"name": "Senior Officer", "ans": "<p>A</p>"},  # exact duplicate: one vacancy
                    {"name": "", "ans": "<p>nameless</p>"},
                    {"name": "Fund &amp; Risk", "ans": "<p>C</p>"},
                ],
            }
        ]
    }
    jobs = m.parse_icbc_category(data, "operations", "ICBC (Asia)", "icbc-asia")
    ids = [j.source_id for j in jobs]
    assert len(jobs) == 3 and len(set(ids)) == 3
    assert sum(i.startswith("icbc-asia:p9:senior-officer#") for i in ids) == 2
    assert "icbc-asia:p9:fund-risk" in ids
    assert [j.title for j in jobs if j.source_id.endswith("fund-risk")] == ["Fund & Risk"]


def test_icbc_nested_children_and_bad_shape():
    nested = {"items": [{"id": "p1", "name": "D", "children": [
        {"name": "Group", "children": [{"name": "Deep Job", "ans": "<p>x</p>"}]}]}]}
    assert [j.title for j in m.parse_icbc_category(nested, "branches", "I", "icbc-asia")] == ["Deep Job"]
    with pytest.raises(ValueError):
        m.parse_icbc_category({"nope": 1}, "branches", "I", "icbc-asia")


def test_icbc_fetch_reads_all_categories_and_raises_when_all_empty():
    branches, fintech = _json("icbc_asia_branches.json"), _json("icbc_asia_financial_technology.json")
    requested = []

    def handler(request):
        cat = request.url.path.rsplit("/", 1)[1][:-5]
        requested.append(cat)
        return httpx.Response(200, json=fintech if cat == "financial_technology" else branches)

    jobs = m.fetch_icbc(httpx.Client(transport=httpx.MockTransport(handler)), "ICBC (Asia)", "icbc-asia")
    assert requested == list(m.ICBC_CATEGORIES)
    # six of the seven categories return the "branches" file, so their ids repeat across categories
    assert len(jobs) == len({j.source_id for j in jobs}) and len(jobs) >= 11
    empty = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"items": []})))
    with pytest.raises(ValueError):
        m.fetch_icbc(empty, "ICBC (Asia)", "icbc-asia")
