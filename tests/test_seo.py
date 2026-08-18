"""
Tests for the public SEO surface: robots.txt, sitemap.xml, and per-Role teaser
pages.

WHY THESE EXIST
---------------
This surface is a deliberate, narrow exception to ADR 0018's "no enumerable
catalogue, no ungated detail read" rule — made specifically so search engines
can index Roles job-by-job. That makes it the one place in the codebase where
getting the boundary wrong in either direction is bad: too loose and it leaks
`description_clean` or an apply link with no session; too strict and boutique/
social-tier Roles (which the product decision explicitly wants indexable, see
the teaser design) silently stay invisible to Google.

These tests pin both edges: every tier is reachable with NO session and NO
Role-access grant, but only the teaser fields ever appear in the response.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from .support import enrichment, job, make_app, make_bundle, make_jobs_db


@pytest.fixture()
def client(tmp_path):
    jobs = [
        job(source="workday", source_id="MAIN", company="HSBC",
            title="Credit Risk Analyst", posted_at="2026-07-01",
            description_clean="SECRET FULL DESCRIPTION mainstream."),
        job(source="longtail", source_id="BOUT", company="Harbour Capital",
            title="Treasury Analyst", source_tier="boutique",
            posted_at="2026-07-02", description_clean="SECRET FULL DESCRIPTION boutique."),
        job(source="linkedin_posts", source_id="SOC", company="Confidential",
            title="Risk Manager", source_tier="social",
            posted_at="2026-07-03", description_clean="SECRET FULL DESCRIPTION social."),
        job(source="workday", source_id="GONE", company="HSBC",
            title="Closed Role", is_active=0, posted_at="2026-06-01"),
        job(source="workday", source_id="HIDDEN", company="HSBC",
            title="Secondary Copy", is_primary=0, posted_at="2026-06-02"),
    ]
    enrichments = [
        enrichment(source="workday", source_id="MAIN",
                   description_summary="Analyse credit risk at HSBC.",
                   salary_hkd_min=40_000, salary_hkd_max=60_000),
        enrichment(source="longtail", source_id="BOUT",
                   description_summary="Manage treasury operations."),
        enrichment(source="linkedin_posts", source_id="SOC",
                   description_summary="Lead risk management."),
    ]
    db = tmp_path / "jobs.db"
    make_jobs_db(db, jobs=jobs, enrichments=enrichments)
    dist = tmp_path / "dist"
    make_bundle(dist)
    return TestClient(make_app(db, dist, tmp_path, cookie_secure=False))


def test_robots_txt_points_at_sitemap(client):
    resp = client.get("/robots.txt")
    assert resp.status_code == 200
    assert "Sitemap:" in resp.text
    assert "/sitemap.xml" in resp.text
    assert "Disallow: /api/" in resp.text


def test_sitemap_lists_static_pages(client):
    body = client.get("/sitemap.xml").text
    assert "<loc>" in body
    assert "/about</loc>" in body
    assert "<loc>http://testserver/jobs</loc>" in body
    # And the thirteen discipline pages it links to, each carrying a query so
    # each answers a signed-out crawler with real Roles.
    assert "/jobs?q=" in body.replace("&amp;", "&")


def test_sitemap_includes_every_tier_with_no_session(client):
    body = client.get("/sitemap.xml").text
    assert "/jobs/workday/MAIN/" in body
    assert "/jobs/longtail/BOUT/" in body
    assert "/jobs/linkedin_posts/SOC/" in body


def test_sitemap_excludes_inactive_and_secondary_copies(client):
    body = client.get("/sitemap.xml").text
    assert "/GONE/" not in body
    assert "/HIDDEN/" not in body


def test_mainstream_teaser_loads_with_no_session(client):
    resp = client.get("/jobs/workday/MAIN/credit-risk-analyst-hsbc")
    assert resp.status_code == 200
    assert "Credit Risk Analyst" in resp.text
    assert "HSBC" in resp.text


def test_boutique_teaser_loads_with_no_session(client):
    """The whole point of the teaser tier: boutique is gated in the API, not here."""
    resp = client.get("/jobs/longtail/BOUT/treasury-analyst-harbour-capital")
    assert resp.status_code == 200
    assert "Treasury Analyst" in resp.text


def test_social_recruiter_post_teaser_loads_with_no_session(client):
    resp = client.get("/jobs/linkedin_posts/SOC/risk-manager-confidential")
    assert resp.status_code == 200
    assert "Risk Manager" in resp.text


def test_teaser_never_leaks_the_full_description(client):
    resp = client.get("/jobs/workday/MAIN/credit-risk-analyst-hsbc")
    assert "SECRET FULL DESCRIPTION" not in resp.text
    assert "Analyse credit risk at HSBC." in resp.text  # the summary is fine


def test_teaser_has_jobposting_structured_data(client):
    resp = client.get("/jobs/workday/MAIN/credit-risk-analyst-hsbc")
    assert '"@type": "JobPosting"' in resp.text
    assert '"hiringOrganization"' in resp.text


def test_teaser_omits_estimated_salary_from_structured_data(client):
    """Only a DISCLOSED salary is a claim about the posting; an AI estimate is not."""
    resp = client.get("/jobs/longtail/BOUT/treasury-analyst-harbour-capital")
    assert '"baseSalary"' not in resp.text


def test_teaser_ctas_to_sign_in_not_to_a_bare_catalogue(client):
    resp = client.get("/jobs/workday/MAIN/credit-risk-analyst-hsbc")
    assert 'href="/get-started"' in resp.text


def test_teaser_wrong_slug_redirects_to_canonical(client):
    resp = client.get("/jobs/workday/MAIN/totally-wrong-slug", follow_redirects=False)
    assert resp.status_code == 301
    assert resp.headers["location"] == "/jobs/workday/MAIN/credit-risk-analyst-hsbc"


def test_teaser_bare_reference_redirects_to_slug(client):
    resp = client.get("/jobs/workday/MAIN", follow_redirects=False)
    assert resp.status_code == 301
    assert resp.headers["location"] == "/jobs/workday/MAIN/credit-risk-analyst-hsbc"


def test_teaser_missing_job_404s(client):
    resp = client.get("/jobs/workday/NOPE/anything")
    assert resp.status_code == 404


def test_closed_job_teaser_is_noindex_with_no_structured_data(client):
    """
    A closed Role's page still resolves (an already-indexed link should not
    404), but must not keep asking Google to rank it — and must not present
    JobPosting data as if it were still open.
    """
    resp = client.get("/jobs/workday/GONE/closed-role-hsbc")
    assert resp.status_code == 200
    assert 'name="robots" content="noindex' in resp.text
    assert '"@type": "JobPosting"' not in resp.text
    assert "closed" in resp.text.lower()
