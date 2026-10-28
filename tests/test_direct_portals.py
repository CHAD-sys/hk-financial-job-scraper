"""Recorded first-party portal structures, without live network calls."""

import json
from datetime import date
from pathlib import Path

import httpx

from hk_jobs.adapters.direct_hkmca import parse_hkmca
from hk_jobs.adapters.direct_towngas import fetch_towngas

FIXTURES = Path(__file__).parent / "fixtures"


def test_hkmca_extracts_each_role_without_navigation_or_group_title():
    jobs = parse_hkmca(
        (FIXTURES / "direct_hkmca.html").read_text(),
        "HKMC Annuity Limited",
        "hkmc-annuity",
        today=date(2026, 10, 28),
    )
    assert len(jobs) == 2
    assert [j.title for j in jobs] == [
        "Senior Manager (Information Technology Risk Management)",
        "Assistant Manager (Complaint Handling)",
    ]
    assert jobs[0].department == "Actuarial"
    assert jobs[1].department == "Business Development and Operations"
    assert "Minimum 8 years" in jobs[0].description_clean
    assert jobs[0].source == "direct_site"
    assert jobs[0].url == "https://www.hkmca.hk/eng/about_us/careers.html"
    assert (
        jobs[0].source_id
        == parse_hkmca(
            (FIXTURES / "direct_hkmca.html").read_text(),
            "HKMC Annuity Limited",
            "hkmc-annuity",
            today=date(2026, 10, 28),
        )[0].source_id
    )


def test_hkmca_skips_expired_roles():
    jobs = parse_hkmca(
        (FIXTURES / "direct_hkmca.html").read_text(),
        "HKMC Annuity Limited",
        "hkmc-annuity",
        today=date(2026, 10, 29),
    )
    assert jobs == []


def test_towngas_fetches_first_party_details_and_skips_other_group_company():
    listing = json.loads((FIXTURES / "direct_towngas_list.json").read_text())
    detail = json.loads((FIXTURES / "direct_towngas_detail.json").read_text())
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("getJobList"):
            assert json.loads(request.content)["pageSize"] == 100
            return httpx.Response(200, json=listing)
        if request.url.path.endswith("getJobDefinition"):
            assert request.url.params["jobId"] == "981"
            return httpx.Response(200, json=detail)
        raise AssertionError(request.url)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        jobs = fetch_towngas(client, "Towngas", "towngas")
    assert len(jobs) == 1
    job = jobs[0]
    assert job.source_id == "towngas:981"
    assert job.url.endswith("Job-Details?jobID=981")
    assert job.department == "Engineering"
    assert job.posted_at.date() == date(2026, 10, 12)
    assert job.employment_type == "full-time"
    assert "Higher Diploma" in job.description_clean
    assert "<div>" in job.description_raw
    assert len(requests) == 2
