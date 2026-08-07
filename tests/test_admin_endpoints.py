"""
Tests for Admin Mode: the /api/admin/* surface in webapp/backend/admin.py.

Three things this file has to prove that no other test file does:

  1. The gate. An anonymous caller gets 401, an ordinary signed-in Seeker gets
     403, and only a Seeker with `is_admin` set gets through — the whole point
     of the phase-2 migration (seekers_store.py) and `_require_admin` (main.py).
  2. Submission moderation reaches the real `jobs` table with the real INSERT
     (webapp/backend/submissions.py), not a mock of it.
  3. The analytics/run-status queries degrade gracefully — never a 500 — against
     a database that has no job_history table at all, which is exactly what
     tests/support.py's stand-in jobs.db looks like and what a fresh production
     database looks like before its first non-dry-run pipeline run.
"""

from __future__ import annotations

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from .support import enrichment, job, make_app, make_bundle, make_jobs_db

ADMIN = {"email": "admin@example.com", "password": "correct-horse-battery", "display_name": "Root"}
SEEKER = {"email": "seeker@example.com", "password": "correct-horse-battery", "display_name": "Ada"}


@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "jobs.db"
    make_jobs_db(
        path,
        jobs=[
            # "HSBC" matches none of job_read.py's named-sector term lists, so
            # SECTOR_SQL's ELSE clause buckets it as Banking; "Manulife" is in
            # _INS_TERMS. There is no `category` column in this stand-in schema
            # (tests/support.py's own comment: "exactly the columns the read
            # path touches") — sector comes from the company name, not a column.
            job(source="workday", source_id="W1", company="HSBC", title="Credit Risk Analyst",
                is_active=1, is_primary=1),
            job(source="jobsdb", source_id="J1", company="HSBC", title="Credit Risk Analyst",
                is_active=1, is_primary=0, cross_posted=1),
            job(source="linkedin", source_id="L1", company="Manulife", title="Actuarial Analyst",
                is_active=1, is_primary=1),
        ],
        enrichments=[
            enrichment(source="workday", source_id="W1", seniority="mid", remote_type="onsite",
                       salary_estimated_min=40000, salary_estimated_max=60000,
                       salary_estimated_confidence="high"),
            enrichment(source="linkedin", source_id="L1", seniority="junior", remote_type="hybrid",
                       salary_estimated_min=20000, salary_estimated_max=30000,
                       salary_estimated_confidence="medium"),
        ],
    )
    return path


@pytest.fixture()
def dist(tmp_path):
    d = tmp_path / "dist"
    make_bundle(d)
    return d


@pytest.fixture()
def _seekers_env(tmp_path, monkeypatch):
    """
    Point the process-wide SeekerStore at a scratch file for this test.

    `seekers_store.get_store()` is a module-level singleton, not scoped to any
    one FastAPI app — so every TestClient built in this file against the same
    tmp_path shares one seekers.db, which is what lets `admin_client` and
    `seeker_client` be two INDEPENDENT clients (own cookie jars) that still see
    each other's accounts, the same way two browsers would against one backend.
    """
    import seekers_store

    monkeypatch.setenv("SEEKERS_DB_PATH", str(tmp_path / "seekers.db"))
    seekers_store.reset_store()


@pytest.fixture()
def client(db, dist, tmp_path, _seekers_env):
    return TestClient(make_app(db, dist, tmp_path, cookie_secure=False))


def _promote_to_admin(email: str) -> None:
    import seekers_store

    store = seekers_store.get_store()
    row = store.get_seeker_by_email(email)
    store.set_admin(row["id"], True)


@pytest.fixture()
def admin_client(db, dist, tmp_path, _seekers_env):
    """
    Its OWN TestClient/app — never `client` reused. Two fixtures that both
    called `client.post("/api/auth/register", ...)` on the SAME TestClient
    would overwrite each other's session cookie (register signs the caller
    straight in), so a test asking for both `admin_client` and `seeker_client`
    would silently get one account acting as both.
    """
    c = TestClient(make_app(db, dist, tmp_path, cookie_secure=False))
    c.post("/api/auth/register", json=ADMIN)
    _promote_to_admin(ADMIN["email"])
    return c


@pytest.fixture()
def seeker_client(db, dist, tmp_path, _seekers_env):
    c = TestClient(make_app(db, dist, tmp_path, cookie_secure=False))
    c.post("/api/auth/register", json=SEEKER)
    return c


# ── The gate ──────────────────────────────────────────────────────────────────


def test_anonymous_gets_401(client):
    r = client.get("/api/admin/run/today")
    assert r.status_code == 401


def test_ordinary_seeker_gets_403(seeker_client):
    r = seeker_client.get("/api/admin/run/today")
    assert r.status_code == 403


def test_admin_gets_200(admin_client):
    r = admin_client.get("/api/admin/run/today")
    assert r.status_code == 200


def test_is_admin_appears_on_whoami(admin_client, seeker_client):
    assert admin_client.get("/api/auth/me").json()["is_admin"] is True
    assert seeker_client.get("/api/auth/me").json()["is_admin"] is False


def test_admin_gate_applies_to_every_admin_route(seeker_client):
    for path in (
        "/api/admin/submissions",
        "/api/admin/run/today",
        "/api/admin/run/history",
        "/api/admin/analytics/overview",
    ):
        assert seeker_client.get(path).status_code == 403


# ── Submissions ───────────────────────────────────────────────────────────────


def _submission(**over):
    base = {
        "contact_name": "Jane Recruiter", "contact_email": "jane@example.com",
        "company": "Acme Capital", "title": "Credit Analyst", "location": "Central, Hong Kong",
        "employment_type": "Full-time", "salary_range": "", "description": "Analyse credit risk.",
        "apply_url": "https://example.test/apply", "received_at": "2026-08-05T09:00:00+00:00",
        "status": "pending",
    }
    base.update(over)
    return base


def _write_queue(tmp_path, rows):
    path = tmp_path / "submitted_roles.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


@pytest.fixture()
def real_jobs_db(tmp_path):
    """
    The REAL `jobs` schema (hk_jobs.storage.ensure_schema), not tests/support.py's
    reduced read-path stand-in. `approve_submission`'s INSERT names columns
    (company_slug, description_raw, extraction_confidence) the stand-in leaves
    out on purpose — a genuine gap between "what /api/jobs reads" and "what
    approving a submission writes" that the two approve tests below exist to
    cross correctly.
    """
    from hk_jobs.storage import ensure_schema

    path = tmp_path / "real_jobs.db"
    ensure_schema(str(path))
    return path


@pytest.fixture()
def admin_client_real_db(real_jobs_db, dist, tmp_path, _seekers_env):
    c = TestClient(make_app(real_jobs_db, dist, tmp_path, cookie_secure=False))
    c.post("/api/auth/register", json=ADMIN)
    _promote_to_admin(ADMIN["email"])
    return c


@pytest.fixture()
def migrated_jobs_db(tmp_path):
    """
    The FULLY migrated schema (hk_jobs.migrations.migrate) — jobs,
    job_enrichments, admin_edits, manually_edited_at. `real_jobs_db` above
    only builds `jobs` (hk_jobs.storage.ensure_schema); the job-edit tests
    below need job_enrichments and the phase-33 admin_edits table too, since
    that is exactly what webapp/backend/job_edit.py writes.
    """
    from hk_jobs.migrations import migrate

    path = tmp_path / "migrated_jobs.db"
    migrate(str(path))
    conn = sqlite3.connect(path)
    conn.execute(
        """
        INSERT INTO jobs (
            source, source_id, company, company_slug, url, dedup_hash, title,
            description_clean, locations, employment_type, apply_url,
            fetched_at, is_active
        ) VALUES (
            'workday', 'W1', 'HSBC', 'hsbc', 'https://x.test/w1', 'abc123', 'Credit Analyst',
            'Analyse credit risk.', '["Hong Kong"]', 'Full-time', 'https://x.test/apply',
            '2026-08-06T00:00:00+00:00', 1
        )
        """
    )
    conn.commit()
    conn.close()
    return path


def _promote_to_super_admin(email: str) -> None:
    import seekers_store

    store = seekers_store.get_store()
    row = store.get_seeker_by_email(email)
    store.set_admin(row["id"], True)
    store.set_super_admin(row["id"], True)


@pytest.fixture()
def super_admin_client(migrated_jobs_db, dist, tmp_path, _seekers_env):
    c = TestClient(make_app(migrated_jobs_db, dist, tmp_path, cookie_secure=False))
    c.post("/api/auth/register", json=ADMIN)
    _promote_to_super_admin(ADMIN["email"])
    return c


@pytest.fixture()
def admin_client_migrated_db(migrated_jobs_db, dist, tmp_path, _seekers_env):
    """An ordinary admin (is_admin, NOT is_super_admin) against the same db —
    for proving the job-edit routes are gated on the stricter bit."""
    c = TestClient(make_app(migrated_jobs_db, dist, tmp_path, cookie_secure=False))
    c.post("/api/auth/register", json=SEEKER)
    _promote_to_admin(SEEKER["email"])
    return c


def test_list_submissions_defaults_to_pending(admin_client, tmp_path):
    _write_queue(tmp_path, [_submission(title="A"), _submission(title="B", status="approved")])
    r = admin_client.get("/api/admin/submissions")
    assert r.status_code == 200
    titles = [row["title"] for row in r.json()]
    assert titles == ["A"]


def test_list_submissions_all_returns_every_status(admin_client, tmp_path):
    _write_queue(tmp_path, [_submission(title="A"), _submission(title="B", status="approved")])
    r = admin_client.get("/api/admin/submissions", params={"status": "all"})
    assert {row["title"] for row in r.json()} == {"A", "B"}


def test_approve_publishes_to_jobs_table(admin_client_real_db, tmp_path, real_jobs_db):
    _write_queue(tmp_path, [_submission()])
    listing = admin_client_real_db.get("/api/admin/submissions").json()
    submission_id = listing[0]["id"]

    r = admin_client_real_db.post(f"/api/admin/submissions/{submission_id}/approve")
    assert r.status_code == 200
    assert r.json()["status"] == "approved"

    conn = sqlite3.connect(real_jobs_db)
    row = conn.execute(
        "SELECT company, title, is_active FROM jobs WHERE source='direct'"
    ).fetchone()
    conn.close()
    assert row == ("Acme Capital", "Credit Analyst", 1)

    # The queue file itself now shows it decided.
    remaining = admin_client_real_db.get("/api/admin/submissions", params={"status": "all"}).json()
    assert remaining[0]["status"] == "approved"


def test_approving_twice_does_not_duplicate_or_error(admin_client_real_db, tmp_path, real_jobs_db):
    _write_queue(tmp_path, [_submission()])
    submission_id = admin_client_real_db.get("/api/admin/submissions").json()[0]["id"]
    admin_client_real_db.post(f"/api/admin/submissions/{submission_id}/approve")
    r = admin_client_real_db.post(f"/api/admin/submissions/{submission_id}/approve")
    assert r.status_code == 200

    conn = sqlite3.connect(real_jobs_db)
    count = conn.execute("SELECT COUNT(*) FROM jobs WHERE source='direct'").fetchone()[0]
    conn.close()
    assert count == 1


def test_reject_records_a_reason_and_never_touches_jobs_table(admin_client, tmp_path, db):
    _write_queue(tmp_path, [_submission()])
    submission_id = admin_client.get("/api/admin/submissions").json()[0]["id"]

    r = admin_client.post(
        f"/api/admin/submissions/{submission_id}/reject", json={"reason": "duplicate"}
    )
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"
    assert r.json()["reason"] == "duplicate"

    conn = sqlite3.connect(db)
    count = conn.execute("SELECT COUNT(*) FROM jobs WHERE source='direct'").fetchone()[0]
    conn.close()
    assert count == 0


def test_acting_on_an_unknown_submission_id_is_404(admin_client, tmp_path):
    _write_queue(tmp_path, [_submission()])
    r = admin_client.post("/api/admin/submissions/not-a-real-id/approve")
    assert r.status_code == 404


# ── Today's run / history — graceful degradation without job_history ─────────


def test_run_today_never_500s_without_a_job_history_table(admin_client):
    r = admin_client.get("/api/admin/run/today")
    assert r.status_code == 200
    body = r.json()
    assert body["ran_today"] is False
    assert body["companies_scraped_today"] == 0
    assert body["zero_companies"] == []
    # The board-level counts DO come from `jobs`, which always exists.
    assert body["active_jobs"] == 3


def test_run_today_reflects_a_seeded_job_history_table(admin_client, db):
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE job_history (company_id TEXT, company_name TEXT, job_count INTEGER, "
        "scraped_date TEXT, jobs_added INTEGER, jobs_removed INTEGER)"
    )
    conn.execute(
        "INSERT INTO job_history VALUES ('hsbc', 'HSBC', 10, DATE('now'), 2, 1)"
    )
    conn.execute(
        "INSERT INTO job_history VALUES ('dead-co', 'Dead Co', 0, DATE('now'), 0, 0)"
    )
    conn.commit()
    conn.close()

    body = admin_client.get("/api/admin/run/today").json()
    assert body["ran_today"] is True
    assert body["companies_scraped_today"] == 2
    assert body["companies_zero_today"] == 1
    assert body["zero_companies"] == ["Dead Co"]
    assert body["jobs_added_today"] == 2
    assert body["jobs_removed_today"] == 1


def test_run_history_returns_empty_points_without_a_job_history_table(admin_client):
    r = admin_client.get("/api/admin/run/history")
    assert r.status_code == 200
    assert r.json()["points"] == []


# ── Analytics ─────────────────────────────────────────────────────────────────


def test_analytics_overview_shape_and_board_counts(admin_client):
    r = admin_client.get("/api/admin/analytics/overview")
    assert r.status_code == 200
    body = r.json()

    # 3 active rows, but the JobsDB copy of the HSBC role is a suppressed
    # cross-posted duplicate — the board (and BOARD_WHERE) sees only 2.
    assert body["total_active_rows"] == 3
    assert body["total_board_roles"] == 2
    assert body["cross_posting_rate_pct"] == pytest.approx(33.3, abs=0.1)
    assert body["duplicate_rows_suppressed"] == 1

    assert body["by_source"] == {"workday": 1, "jobsdb": 1, "linkedin": 1}
    assert body["by_board_source"] == {"workday": 1, "linkedin": 1}
    assert body["by_sector"] == {"Banking": 1, "Insurance": 1}
    assert body["by_seniority"] == {"mid": 1, "junior": 1}
    assert body["by_remote_type"] == {"onsite": 1, "hybrid": 1}

    assert body["salary_confidence"] == {"high": 1, "medium": 1}
    # midpoints: (40000+60000)/2=50000 -> "40-60k"; (20000+30000)/2=25000 -> "20-40k"
    assert body["salary_distribution"] == {"40-60k": 1, "20-40k": 1}
    assert body["salary_median_hkd"] == 37500
    assert body["salary_p25_hkd"] == 31250
    assert body["salary_p75_hkd"] == 43750
    assert body["salary_sample_size"] == 2
    assert body["dominant_sector"] == {"name": "Banking", "count": 1, "share_pct": 50.0}
    assert body["remote_friendly_pct"] == 50.0
    assert body["data_quality"]["salary_coverage_pct"] == 100.0
    assert body["data_quality"]["high_confidence_salary_pct"] == 50.0
    assert body["market_movers"]["gainers"] == []

    names = {c["name"] for c in body["top_companies"]}
    assert names == {"HSBC", "Manulife"}
    assert body["company_concentration_hhi"] > 0
    assert body["company_concentration_label"] == "concentrated"
    assert body["company_entity_count"] == 2


def test_analytics_market_movers_compare_two_well_covered_days(admin_client, db):
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE job_history (company_id TEXT, company_name TEXT, job_count INTEGER, "
        "scraped_date TEXT, jobs_added INTEGER, jobs_removed INTEGER)"
    )
    conn.executemany(
        "INSERT INTO job_history VALUES (?, ?, ?, ?, 0, 0)",
        [
            ("hsbc", "HSBC", 8, "2000-01-01"),
            ("manulife", "Manulife", 5, "2000-01-01"),
            ("hsbc", "HSBC", 12, "2000-01-02"),
            ("manulife", "Manulife", 3, "2000-01-02"),
        ],
    )
    conn.commit()
    conn.close()

    movers = admin_client.get("/api/admin/analytics/overview").json()["market_movers"]
    assert movers["current_date"] == "2000-01-02"
    assert movers["comparison_date"] == "2000-01-01"
    assert movers["gainers"][0] == {
        "name": "HSBC", "current": 12, "previous": 8, "change": 4, "change_pct": 50.0,
    }
    assert movers["decliners"][0]["name"] == "Manulife"
    assert movers["decliners"][0]["change"] == -2


def test_salary_confidence_uses_the_same_complete_range_sample(admin_client, db):
    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE job_enrichments SET salary_estimated_max=NULL, "
        "salary_estimated_confidence='high' WHERE source='linkedin'"
    )
    conn.commit()
    conn.close()

    body = admin_client.get("/api/admin/analytics/overview").json()
    assert body["salary_sample_size"] == 1
    assert body["salary_confidence"] == {"high": 1}
    assert body["data_quality"]["high_confidence_salary_pct"] == 100.0


# ── Ultimate Admin: direct job edit ───────────────────────────────────────────


def test_job_edit_gate_anonymous_401(client):
    r = client.get("/api/admin/jobs/workday/W1")
    assert r.status_code == 401


def test_job_edit_gate_ordinary_seeker_403(seeker_client):
    r = seeker_client.get("/api/admin/jobs/workday/W1")
    assert r.status_code == 403


def test_job_edit_gate_ordinary_admin_403(admin_client_migrated_db):
    """is_admin alone is not enough — only is_super_admin reaches this route."""
    r = admin_client_migrated_db.get("/api/admin/jobs/workday/W1")
    assert r.status_code == 403
    r = admin_client_migrated_db.patch("/api/admin/jobs/workday/W1", json={"job": {"title": "X"}})
    assert r.status_code == 403


def test_super_admin_can_read_a_job(super_admin_client):
    r = super_admin_client.get("/api/admin/jobs/workday/W1")
    assert r.status_code == 200
    assert r.json()["title"] == "Credit Analyst"


def test_reading_an_unknown_job_is_404(super_admin_client):
    r = super_admin_client.get("/api/admin/jobs/workday/not-a-real-id")
    assert r.status_code == 404


def test_super_admin_can_edit_a_job_field(super_admin_client, migrated_jobs_db):
    r = super_admin_client.patch(
        "/api/admin/jobs/workday/W1", json={"job": {"title": "Senior Credit Analyst"}}
    )
    assert r.status_code == 200
    assert r.json()["title"] == "Senior Credit Analyst"

    conn = sqlite3.connect(migrated_jobs_db)
    title = conn.execute("SELECT title FROM jobs WHERE source_id='W1'").fetchone()[0]
    conn.close()
    assert title == "Senior Credit Analyst"


def test_super_admin_can_edit_the_ai_salary_estimate(super_admin_client, migrated_jobs_db):
    """The flagship case this feature exists for."""
    r = super_admin_client.patch(
        "/api/admin/jobs/workday/W1",
        json={"enrichment": {"salary_estimated_min": 45000, "salary_estimated_max": 65000}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["salary_estimated_min"] == 45000
    assert body["salary_estimated_max"] == 65000
    assert body["manually_edited_at"] is not None

    conn = sqlite3.connect(migrated_jobs_db)
    row = conn.execute(
        "SELECT salary_estimated_min, salary_estimated_max, manually_edited_at "
        "FROM job_enrichments WHERE source_id='W1'"
    ).fetchone()
    conn.close()
    assert row[0] == 45000 and row[1] == 65000 and row[2] is not None


def test_editing_an_unknown_field_is_400(super_admin_client):
    r = super_admin_client.patch(
        "/api/admin/jobs/workday/W1", json={"job": {"source_id": "hijack"}}
    )
    assert r.status_code == 400


def test_editing_an_unknown_job_is_404(super_admin_client):
    r = super_admin_client.patch(
        "/api/admin/jobs/workday/not-a-real-id", json={"job": {"title": "X"}}
    )
    assert r.status_code == 404


def test_edit_is_recorded_in_admin_edits_with_the_actors_seeker_id(
    super_admin_client, migrated_jobs_db,
):
    super_admin_client.patch("/api/admin/jobs/workday/W1", json={"job": {"title": "New Title"}})

    me = super_admin_client.get("/api/auth/me").json()
    conn = sqlite3.connect(migrated_jobs_db)
    row = conn.execute(
        "SELECT seeker_id, field, old_value, new_value FROM admin_edits"
    ).fetchone()
    conn.close()
    assert row[0] == me["id"]
    assert row[1] == "job.title"
    assert row[2] == "Credit Analyst"
    assert row[3] == "New Title"
