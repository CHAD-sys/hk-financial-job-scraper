"""The MT page's live feed is a dedicated discovery path over jobs.db."""

from fastapi.testclient import TestClient

from .support import days_ago, job, make_app, make_bundle, make_jobs_db


def test_mt_roles_endpoint_only_returns_strict_watchlist_backed_mt_roles(tmp_path):
    db = tmp_path / "jobs.db"
    make_jobs_db(db, jobs=[
        job(source_id="MT", title="2027 Management Trainee Programme", company="Bank Of China (Hong Kong) Limited", posted_at=days_ago(90)),
        job(source="jobsdb", source_id="HKMA_JOBSDB", title="Manager Trainee (2027 Intake)", company="Hong Kong Monetary Authority", posted_at=days_ago(4)),
        job(source="linkedin", source_id="HKMA_LINKEDIN", title="Manager Trainee (2027 Intake)", company="Hong Kong Monetary Authority (HKMA)", posted_at=days_ago(3)),
        job(source_id="WEALTH", title="Wealth Management Trainee Programme", company="Bank Of China (Hong Kong) Limited", posted_at=days_ago(1)),
        job(source_id="GRAD", title="Graduate Analyst Program — Markets", company="EY", posted_at=days_ago(3)),
        job(source_id="KPMG_GRAD", title="Audit Graduate Programme", company="KPMG", posted_at=days_ago(2)),
        job(source_id="HYBRID", title="Management Trainee & Graduate Trainee Programme", company="Hang Seng Bank", posted_at=days_ago(1)),
        job(source_id="NOT_ON_WATCHLIST", title="Management Trainee Programme", company="Bank A", posted_at=days_ago(3)),
        job(source_id="INTERN", title="Management Trainee Internship", company="Hang Seng Bank", posted_at=days_ago(3)),
        job(source_id="VAGUE", title="Early Careers Programme", company="Hang Seng Bank", posted_at=days_ago(3)),
        job(source_id="PLAIN", title="Programme Manager", company="Bank C", posted_at=days_ago(1)),
        job(source_id="CLOSED", title="Graduate Trainee", company="Hang Seng Bank", is_active=0, posted_at=days_ago(1)),
        job(source_id="HIDDEN", title="Management Trainee", company="Hang Seng Bank", admin_hidden=1, posted_at=days_ago(1)),
        job(source_id="SECRET", title="Management Trainee", company="Hang Seng Bank", source_tier="social", posted_at=days_ago(1)),
    ])
    dist = tmp_path / "dist"
    make_bundle(dist)
    client = TestClient(make_app(db, dist, tmp_path, cookie_secure=False))

    response = client.get("/api/management-trainee/roles")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 3
    assert [role["source_id"] for role in body["jobs"]] == ["HKMA_LINKEDIN", "MT", "WEALTH"]
    by_id = {role["source_id"]: role for role in body["jobs"]}
    assert by_id["HKMA_LINKEDIN"]["url"] == "https://www.hkma.gov.hk/eng/about-us/join-us/current-vacancies/"
    assert by_id["HKMA_LINKEDIN"]["application_label"] == "View HKMA vacancies"
    assert by_id["MT"]["application_destination"] == "employer_role"
    assert by_id["MT"]["url"] == "https://www.bochk.com/en/career/ustudentprogramme/mgttrainee.html"
    assert by_id["WEALTH"]["application_destination"] == "employer_vacancies"
    assert by_id["WEALTH"]["url"] == "https://www.bochk.com/en/career/opportunities.html"
