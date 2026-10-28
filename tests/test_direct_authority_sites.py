"""Recorded public employer page structures from 28 October 2026."""

from pathlib import Path

import httpx

from hk_jobs.adapters.direct_hkma import fetch_hkma, parse_hkma_openings
from hk_jobs.adapters.direct_hkmc import fetch_hkmc, parse_hkmc_openings

FIXTURES = Path(__file__).parent / "fixtures" / "direct_sites"


def test_hkma_table_maps_stable_ids_and_closing_dates():
    html = (FIXTURES / "hkma_openings.html").read_text()
    jobs = parse_hkma_openings(html, "Hong Kong Monetary Authority", "hkma")
    assert len(jobs) == 12
    officer = next(job for job in jobs if job.source_id == "hkma:recruit-20261023-1")
    assert officer.title == "Officer (Risk Management and Compliance)"
    assert officer.board_signals["closing_date"] == "2026-11-07"
    assert officer.posted_at is None  # closing date must not be mislabelled as posting date
    assert officer.source == "direct_site"
    assert officer.url.endswith("/recruit-20261023-1/")


def test_hkma_ignores_unrelated_links_and_duplicate_rows():
    html = """<table class="small-table">
    <tr><td><a href="/eng/about-us/join-us/current-vacancies/recruit-1/">Good</a></td>
    <td>7 November 2026</td></tr>
    <tr><td><a href="/eng/about-us/join-us/current-vacancies/recruit-1/">Good</a></td>
    <td>7 November 2026</td></tr>
    <tr><td><a href="https://evil.example/eng/about-us/join-us/current-vacancies/recruit-2/">Bad</a></td></tr>
    </table>"""
    jobs = parse_hkma_openings(html, "HKMA", "hkma")
    assert [job.source_id for job in jobs] == ["hkma:recruit-1"]


def test_hkma_fetches_detail_and_preserves_description(monkeypatch):
    listing = (FIXTURES / "hkma_openings.html").read_text()
    detail = (FIXTURES / "hkma_detail.html").read_text()
    calls = []

    def handle(req):
        calls.append(str(req.url))
        return httpx.Response(200, text=listing if len(calls) == 1 else detail)

    monkeypatch.setattr("hk_jobs.adapters.direct_hkma.time.sleep", lambda _: None)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        jobs = fetch_hkma(client, "Hong Kong Monetary Authority", "hkma")
    assert len(jobs) == 12
    assert len(calls) == 13
    assert "Key Responsibilities" in jobs[0].description_clean
    assert "Key Responsibilities" in jobs[0].description_raw


def test_hkmc_each_opening_has_own_apply_url_and_description():
    html = (FIXTURES / "hkmc_openings.html").read_text()
    jobs = parse_hkmc_openings(html, "The Hong Kong Mortgage Corporation Limited", "hkmc")
    assert len(jobs) == 2
    assert {j.source_id for j in jobs} == {
        "hkmc:6ad02be11c8c223b7595b210",
        "hkmc:6ad1d3831c8c223b7595b4b1",
    }
    assert jobs[0].url.startswith("https://careers.hkmc.com.hk/")
    assert "risk management framework" in jobs[0].description_clean
    assert jobs[0].department == "Infrastructure Financing and Securitisation"
    assert jobs[1].department == "HKMC Insurance Limited"
    assert all(j.source == "direct_site" for j in jobs)


def test_hkmc_fetches_single_public_page():
    html = (FIXTURES / "hkmc_openings.html").read_text()
    calls = []

    def handle(req):
        calls.append(str(req.url))
        return httpx.Response(200, text=html)

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        jobs = fetch_hkmc(client, "HKMC", "hkmc")
    assert len(calls) == 1
    assert len(jobs) == 2
