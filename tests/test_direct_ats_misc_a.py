"""AXA (Jibe), Morgan Stanley (Eightfold PCSX) and WeLab Bank (BambooHR) fetchers, offline."""

import copy
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from hk_jobs.adapters import direct_ats_misc_a as m

FIXTURES = Path(__file__).parent / "fixtures" / "direct_sites"


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(m.time, "sleep", lambda *_: None)


def _load(name):
    return json.loads((FIXTURES / name).read_text())


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_registry():
    assert set(m.SITE_FETCHERS) == {"axa-hk", "morgan-stanley", "welab-bank"}


# ── AXA ───────────────────────────────────────────────────────────────────────

def _axa_pages(rows, size=40, total=None):
    total = len(rows) if total is None else total

    def handler(request):
        page = int(request.url.params["page"])
        chunk = rows[(page - 1) * size : page * size]
        return httpx.Response(200, json={"jobs": chunk, "totalCount": total})

    return handler


def test_axa_maps_fields_and_keeps_only_hk():
    data = _load("axa-hk_jobs.json")
    foreign = copy.deepcopy(data["jobs"][0])
    foreign["data"].update(req_id="999", country_code="SG", country="Singapore")
    rows = data["jobs"] + [foreign]
    jobs = m.fetch_axa(_client(_axa_pages(rows)), "AXA Hong Kong", "axa-hk", delay=0)
    assert len(jobs) == 3 and "axa-hk:999" not in {j.source_id for j in jobs}
    job = jobs[0]
    assert job.source == "direct_site" and job.source_id == "axa-hk:23760"
    assert job.url == "https://careers.axa.com/jobs/23760?lang=en-us"
    assert job.title == "Assistant Business Development Manager (Agency Force)"
    assert job.locations == ["Hong Kong"] and job.department == "SALES AND DISTRIBUTION"
    assert job.posted_at == datetime(2026, 7, 13, 7, 30, tzinfo=UTC)
    assert job.description_clean.startswith("Responsibilities:")
    assert job.scraped_under_slug == "axa-hk"
    assert not any("redacted" in str(v) for v in job.model_dump().values())


def test_axa_paginates_until_total_and_collapses_duplicates():
    base = _load("axa-hk_jobs.json")["jobs"][0]
    rows = []
    for i in range(5):
        r = copy.deepcopy(base)
        r["data"]["req_id"] = str(100 + i)
        rows.append(r)
    seen = []

    def handler(request):
        seen.append(int(request.url.params["page"]))
        return _axa_pages(rows, size=2)(request)

    jobs = m.fetch_axa(_client(handler), "AXA Hong Kong", "axa-hk", delay=0)
    assert seen == [1, 2, 3] and len(jobs) == 5

    dup = [rows[0], copy.deepcopy(rows[0])]
    jobs = m.fetch_axa(_client(_axa_pages(dup, size=1, total=1)), "AXA", "axa-hk", delay=0)
    assert len(jobs) == 1


def test_axa_empty_and_inconsistent():
    assert m.fetch_axa(_client(_axa_pages([])), "AXA", "axa-hk", delay=0) == []
    row = _load("axa-hk_jobs.json")["jobs"][:1]
    with pytest.raises(ValueError):
        m.fetch_axa(_client(_axa_pages(row, total=5)), "AXA", "axa-hk", delay=0)


# ── Morgan Stanley ────────────────────────────────────────────────────────────

def _ms_handler(positions, detail, total=None):
    total = len(positions) if total is None else total

    def handler(request):
        if request.url.path.endswith("/search"):
            start = int(request.url.params["start"])
            page = positions[start : start + 10]
            return httpx.Response(200, json={"status": 200, "data": {"positions": page, "count": total}})
        assert request.url.path.endswith("/position_details")
        d = copy.deepcopy(detail["data"])
        d["id"] = int(request.url.params["position_id"])
        return httpx.Response(200, json={"status": 200, "data": d})

    return handler


def test_morgan_stanley_maps_and_filters_hk():
    positions = _load("morgan-stanley_search.json")["data"]["positions"]
    detail = _load("morgan-stanley_detail.json")
    sg = copy.deepcopy(positions[0])
    sg.update(id=1, standardizedLocations=["SG"], locations=["Singapore, Singapore"])
    multi = copy.deepcopy(positions[1])
    multi.update(id=2, locations=["Hong Kong, Hong Kong", "Tokyo, Japan"], standardizedLocations=["HK", "JP"])
    allp = positions + [sg, multi]
    jobs = m.fetch_morgan_stanley(_client(_ms_handler(allp, detail)), "Morgan Stanley", "morgan-stanley")
    assert len(jobs) == len(positions) + 1
    first = jobs[0]
    assert first.source_id == "morgan-stanley:PT-JR045340"
    assert first.url.startswith("https://morganstanley.eightfold.ai/careers/job/")
    assert first.posted_at == datetime.fromtimestamp(1791763200, UTC)
    assert first.department == "Financial Planning & Analysis" and first.locations == ["Hong Kong"]
    assert "<" not in first.description_clean and first.description_raw.startswith("<p>")
    assert ["Hong Kong", "Tokyo, Japan"] in [j.locations for j in jobs]


def test_morgan_stanley_pagination_over_pages():
    positions = _load("morgan-stanley_search.json")["data"]["positions"]
    detail = _load("morgan-stanley_detail.json")
    many = []
    for i in range(23):
        p = copy.deepcopy(positions[i % 3])
        p.update(id=1000 + i, displayJobId=f"PT-JR{i}")
        many.append(p)
    starts = []

    def handler(request):
        if request.url.path.endswith("/search"):
            starts.append(int(request.url.params["start"]))
        return _ms_handler(many, detail)(request)

    jobs = m.fetch_morgan_stanley(_client(handler), "Morgan Stanley", "morgan-stanley")
    assert starts == [0, 10, 20] and len(jobs) == 23


def test_morgan_stanley_duplicates_empty_inconsistent():
    positions = _load("morgan-stanley_search.json")["data"]["positions"]
    detail = _load("morgan-stanley_detail.json")
    dups = [positions[0], copy.deepcopy(positions[0])]
    jobs = m.fetch_morgan_stanley(_client(_ms_handler(dups, detail, total=1)), "MS", "morgan-stanley")
    assert len(jobs) == 1
    assert m.fetch_morgan_stanley(_client(_ms_handler([], detail)), "MS", "morgan-stanley") == []
    with pytest.raises(ValueError):
        m.fetch_morgan_stanley(_client(_ms_handler(positions, detail, total=9)), "MS", "morgan-stanley")


# ── WeLab Bank ────────────────────────────────────────────────────────────────

def _welab_fixture():
    return _load("welab-bank_list.json"), _load("welab-bank_details.json")


def _welab_handler(listing, details):
    def handler(request):
        path = request.url.path
        if path == "/careers/list":
            return httpx.Response(200, json=listing)
        job_id = path.split("/")[2]
        return httpx.Response(200, json=details[job_id])

    return handler


def test_welab_maps_fields_and_filters():
    listing, details = _welab_fixture()
    other = {
        "id": "7",
        "jobOpeningName": "Engineer",
        "departmentLabel": "Tech",
        "location": {"city": "Jakarta", "state": "Jakarta"},
    }
    listing["result"].append(other)
    listing["meta"]["totalCount"] += 1
    jobs = m.fetch_welab(_client(_welab_handler(listing, details)), "WeLab Bank", "welab-bank")
    ids = {j.source_id for j in jobs}
    assert ids == {"welab-bank:799", "welab-bank:935", "welab-bank:841"}
    job = next(j for j in jobs if j.source_id == "welab-bank:799")
    assert job.title == "Senior Officer, Account Operations"  # prefix stripped
    assert job.url == "https://welab.bamboohr.com/careers/799"
    assert job.posted_at == datetime(2025, 8, 14, tzinfo=UTC)
    assert job.department == "Ops" and job.locations == ["Hong Kong"]
    assert "<" not in job.description_clean and job.description_raw.startswith("<p>")
    # the unprefixed title and the "HK" state label are both kept
    assert next(j for j in jobs if j.source_id == "welab-bank:935").title.startswith("Assistant Manager")


def test_welab_empty_duplicates_and_inconsistent():
    listing, details = _welab_fixture()
    assert m.fetch_welab(_client(_welab_handler({"meta": {"totalCount": 0}, "result": []}, {})), "W", "welab-bank") == []
    dup = copy.deepcopy(listing)
    dup["result"] = dup["result"] + [dup["result"][0]]
    dup["meta"]["totalCount"] = len(dup["result"])
    jobs = m.fetch_welab(_client(_welab_handler(dup, details)), "W", "welab-bank")
    assert len([j for j in jobs if j.source_id == "welab-bank:799"]) == 1
    bad = copy.deepcopy(listing)
    bad["meta"]["totalCount"] = 99
    with pytest.raises(ValueError):
        m.fetch_welab(_client(_welab_handler(bad, details)), "W", "welab-bank")


def test_welab_detail_country_mismatch_dropped():
    listing, details = _welab_fixture()
    details = copy.deepcopy(details)
    details["799"]["result"]["jobOpening"]["location"]["addressCountry"] = "Indonesia"
    jobs = m.fetch_welab(_client(_welab_handler(listing, details)), "W", "welab-bank")
    assert "welab-bank:799" not in {j.source_id for j in jobs}


def test_welab_pagination_end_is_single_page():
    """BambooHR returns everything in one response: exactly 1 list call + 1 detail per HK job."""
    listing, details = _welab_fixture()
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return _welab_handler(listing, details)(request)

    jobs = m.fetch_welab(_client(handler), "W", "welab-bank")
    assert calls.count("/careers/list") == 1 and len(calls) == 1 + len(jobs)
