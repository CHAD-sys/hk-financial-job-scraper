"""ZA Bank (Feishu), Mox Bank (Pinpoint) and Macquarie (Avature) readers, against responses recorded 30 Oct 2026."""

import json
from pathlib import Path

import httpx
import pytest

from hk_jobs.adapters import direct_ats_misc_c as m
from hk_jobs.adapters.direct_ats_misc_c import (
    SITE_FETCHERS,
    fetch_macquarie,
    fetch_mox_bank,
    fetch_za_bank,
    is_macquarie_hong_kong,
    is_za_bank_role,
    parse_macquarie_detail,
    parse_macquarie_listing,
    parse_mox_feed,
)

FIXTURES = Path(__file__).parent / "fixtures" / "direct_sites"


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(m.time, "sleep", lambda s: None)


def _json(name):
    return json.loads((FIXTURES / name).read_text())


def test_registered_slugs():
    assert set(SITE_FETCHERS) == {"za-bank", "mox-bank", "macquarie"}


# ── ZA Bank ───────────────────────────────────────────────────────────────────

def _za_client(rows, page_log=None):
    """Mock the Feishu endpoint: honours limit/offset over `rows`, ignoring the location filter."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert request.headers["website-path"] == "246012"
        if page_log is not None:
            page_log.append((body["offset"], body["limit"]))
        chunk = rows[body["offset"] : body["offset"] + body["limit"]]
        return httpx.Response(200, json={"code": 0, "data": {"count": len(rows), "job_post_list": chunk}})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_za_keeps_hong_kong_bank_roles_and_maps_fields():
    rows = _json("za-bank_search.json")["data"]["job_post_list"]
    jobs = fetch_za_bank(_za_client(rows), "ZA Bank", "za-bank")
    ids = {j.source_id for j in jobs}
    assert len(rows) == 7 and len(jobs) == 4
    assert "za-bank:7636307855372454198" not in ids  # insurance-side Head of Sales
    assert "za-bank:7701162106284149035" not in ids  # Shenzhen
    job = next(j for j in jobs if j.source_id == "za-bank:7698935251846383914")
    assert job.title == "Manager, Finance Business Partner"
    assert job.url == "https://zaglobal.jobs.feishu.cn/246012/position/7698935251846383914/detail"
    assert job.locations == ["Hong Kong"] and job.department == "Banking"
    assert job.source == "direct_site" and job.scraped_under_slug == "za-bank"
    assert job.posted_at.year == 2026 and job.posted_at.tzinfo is not None
    assert len(job.description_clean) > 500 and job.description_raw


def test_za_entity_heuristic():
    assert not is_za_bank_role({"title": "Head of Sales", "description": "insurance broker RO", "requirement": ""})
    assert is_za_bank_role({"title": "Product Manager", "description": "retail banking and insurance", "requirement": None})
    assert is_za_bank_role({"title": "Brand Manager", "description": "marketing", "requirement": None})


def test_za_paginates_to_the_end_and_dedupes():
    base = _json("za-bank_search.json")["data"]["job_post_list"][0]
    rows = [{**base, "id": str(1000 + i), "title": f"Role {i}"} for i in range(120)]
    log = []
    jobs = fetch_za_bank(_za_client(rows, log), "ZA Bank", "za-bank")
    assert len(jobs) == 120 and log == [(0, 50), (50, 50), (100, 50)]

    dupes = [dict(base, id="1"), dict(base, id="1")]
    assert len(fetch_za_bank(_za_client(dupes), "ZA Bank", "za-bank")) == 1


def test_za_empty_and_bad_responses():
    assert fetch_za_bank(_za_client([]), "ZA Bank", "za-bank") == []
    bad = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"code": 10001, "data": None})))
    with pytest.raises(ValueError):
        fetch_za_bank(bad, "ZA Bank", "za-bank")


def test_za_repeated_page_stops():
    base = _json("za-bank_search.json")["data"]["job_post_list"][0]
    page = [dict(base, id=str(i)) for i in range(3)]
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json={"code": 0, "data": {"count": 999, "job_post_list": page}})

    jobs = fetch_za_bank(httpx.Client(transport=httpx.MockTransport(handler)), "ZA Bank", "za-bank")
    assert len(jobs) == 3 and len(calls) == 2


# ── Mox Bank ──────────────────────────────────────────────────────────────────

def test_mox_maps_fields_and_cleans_blocks():
    payload = _json("mox-bank_postings.json")
    jobs = parse_mox_feed(payload, "Mox Bank", "mox-bank")
    assert len(payload["data"]) == 4 and len(jobs) == 4
    job = jobs[0]
    assert job.source_id == "mox-bank:402472" and job.title == "Senior Customer Care Officer (INV)"
    assert job.url.startswith("https://moxbank.pinpointhq.com/en/postings/")
    assert job.department == "Customer Service" and job.employment_type == "full-time"
    assert job.locations == ["Hong Kong"] and job.posted_at is None
    assert "<!--block-->" not in job.description_raw
    assert "Responsibilities" in job.description_clean and "HKSI" in job.description_clean


def test_mox_filters_non_hong_kong_and_collapses_duplicates():
    rows = _json("mox-bank_postings.json")["data"]
    london = {**rows[0], "id": "999", "location": {"name": "London", "city": "London", "province": "England"}}
    nolocation = {**rows[0], "id": "998", "location": None}
    payload = {"data": [rows[0], rows[0], london, nolocation]}
    jobs = parse_mox_feed(payload, "Mox Bank", "mox-bank")
    assert [j.source_id for j in jobs] == ["mox-bank:402472"]


def test_mox_empty_and_changed_shape():
    assert parse_mox_feed({"data": []}, "Mox Bank", "mox-bank") == []
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"postings": []})))
    with pytest.raises(ValueError):
        fetch_mox_bank(client, "Mox Bank", "mox-bank")


def test_mox_fetch_end_to_end():
    payload = _json("mox-bank_postings.json")
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload)))
    assert len(fetch_mox_bank(client, "Mox Bank", "mox-bank")) == 4


# ── Macquarie ─────────────────────────────────────────────────────────────────

_LIST0 = (FIXTURES / "macquarie_list_0.html").read_text()
_LIST9 = (FIXTURES / "macquarie_list_9.html").read_text()
_DETAIL = (FIXTURES / "macquarie_detail.html").read_text()


def test_macquarie_listing_parse_and_hk_filter():
    rows = parse_macquarie_listing(_LIST0) + parse_macquarie_listing(_LIST9)
    assert len(rows) == 14
    hk = [r for r in rows if is_macquarie_hong_kong(r)]
    assert len(hk) == 11  # Sydney, Gurugram, Houston keyword leaks dropped
    first = rows[0]
    assert first["id"] == "24773" and first["title"] == "Analyst - Control Room Compliance"
    assert first["offices"] == ["Hong Kong"] and first["posted"] == "28 Oct 2026"
    assert first["category"] == "Compliance & Regulatory"
    multi = [r for r in rows if len(r["offices"]) > 1]
    assert multi and "Hong Kong" in multi[0]["offices"]


def test_macquarie_detail_description_excludes_metadata():
    raw, term = parse_macquarie_detail(_DETAIL)
    assert term == "Permanent - Full time"
    assert "What role will you play?" in raw and "Relevant industry experience" in raw
    assert "28-Oct-2026" not in raw and "Additional office locations" not in raw


def _mq_client(pages, redirect_after=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("JobDetail"):
            return httpx.Response(200, text=_DETAIL)
        offset = int(request.url.params["jobOffset"])
        idx = offset // 9
        if idx < len(pages):
            return httpx.Response(200, text=pages[idx])
        return httpx.Response(302, headers={"location": "https://recruitment.macquarie.com/en_US/careers/Error"})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_macquarie_fetch_filters_maps_and_ends_on_short_page():
    jobs = fetch_macquarie(_mq_client([_LIST0, _LIST9]), "Macquarie Group", "macquarie")
    assert len(jobs) == 11
    job = next(j for j in jobs if j.source_id == "macquarie:24773")
    assert job.url == "https://recruitment.macquarie.com/en_US/careers/JobDetail?jobId=24773"
    assert job.posted_at.date().isoformat() == "2026-10-28" and job.posted_at.tzinfo is not None
    assert job.department == "Compliance & Regulatory" and job.employment_type == "full-time"
    assert job.locations == ["Hong Kong"] and job.scraped_under_slug == "macquarie"
    assert len(job.description_clean) > 500
    assert any(j.locations == ["Hong Kong", "Shanghai"] for j in jobs)


def test_macquarie_ends_on_redirect_past_the_last_page():
    # Both pages full (9 rows) so the loop must rely on the redirect to stop.
    jobs = fetch_macquarie(_mq_client([_LIST0, _LIST0.replace("jobId=", "jobId=1")]), "Macquarie Group", "macquarie")
    assert len(jobs) >= 9


def test_macquarie_repeated_page_stops_and_duplicates_collapse():
    jobs = fetch_macquarie(_mq_client([_LIST0, _LIST0, _LIST0]), "Macquarie Group", "macquarie")
    ids = [j.source_id for j in jobs]
    assert len(ids) == len(set(ids)) == 9


def test_macquarie_empty_result():
    assert fetch_macquarie(_mq_client([]), "Macquarie Group", "macquarie") == []
    assert fetch_macquarie(_mq_client(["<html><body>none</body></html>"]), "Macquarie Group", "macquarie") == []
