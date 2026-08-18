"""Behavioural tests for the Admin Intelligence read-model interface."""

# ruff: noqa: E402, I001

from __future__ import annotations

import sqlite3
from datetime import date

from .support import make_jobs_db

import admin_intelligence


class _RecommendationStore:
    def recommendation_health(self):
        return {
            "impressions": 5,
            "clicks": 2,
            "click_through_pct": 40.0,
            "saves": 1,
            "more_like": 1,
            "dismissals": 0,
            "wrong_reason": 0,
            "seekers_reached": 2,
            "eligible_seekers": 3,
            "coverage_pct": 66.7,
            "tracking_available": True,
            "window_started_at": "2026-08-01T00:00:00+00:00",
            "window_ended_at": "2026-08-11T00:00:00+00:00",
        }

    def user_activity_overview(self, *, days: int = 30, now=None):
        return {
            "days": days,
            "window_started_on": "2026-08-01",
            "window_ended_on": "2026-08-11",
            "total_seekers": 3,
            "new_signups": 1,
            "active_seekers": 2,
            "returning_seekers": 1,
            "repeat_visit_rate_pct": 50.0,
            "points": [],
            "tracking_available": True,
            "anonymous": {
                "unique_visitors": 5,
                "returning_visitors": 2,
                "repeat_visit_rate_pct": 40.0,
                "points": [],
            },
        }


def _connection(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def test_snapshot_distinguishes_missing_evidence_from_zero(tmp_path, monkeypatch):
    db = tmp_path / "jobs.db"
    make_jobs_db(db)
    monkeypatch.setattr(
        admin_intelligence.seekers_store,
        "get_store",
        lambda: _RecommendationStore(),
    )

    with _connection(db) as conn:
        snapshot = admin_intelligence.build_admin_intelligence(
            conn,
            history_days=30,
            operating_day=date(2026, 8, 11),
        )

    assert snapshot["schema_version"] == 1
    assert snapshot["generated_at"] == snapshot["operations"]["generated_at"]
    assert snapshot["availability"] == {
        "catalogue": True,
        "history": False,
        "daily_run": False,
        "source_health": False,
        "ai_usage": False,
        "publication": False,
        # False here reflects "not shown to this admin", not "no data exists" —
        # this call defaults to is_super_admin=False. See the gating test below.
        "recommendations": False,
    }
    assert snapshot["today"]["companies_scraped_today"] == 0
    assert snapshot["today"]["tracking_available"] is False
    assert snapshot["history"]["points"] == []
    assert snapshot["history"]["tracking_available"] is False
    # Ultimate-Admin-only sections: an ordinary admin gets no field at all.
    assert snapshot["operations"]["ai_cost"] is None
    assert snapshot["operations"]["source_health"] is None
    assert snapshot["operations"]["publication"] is None
    assert snapshot["operations"]["recommendations"] is None
    assert snapshot["user_activity"]["active_seekers"] == 2


def test_ultimate_admin_only_sections_are_withheld_from_ordinary_admins(
    tmp_path, monkeypatch
):
    db = tmp_path / "jobs.db"
    make_jobs_db(db)
    monkeypatch.setattr(
        admin_intelligence.seekers_store,
        "get_store",
        lambda: _RecommendationStore(),
    )

    with _connection(db) as conn:
        ordinary = admin_intelligence.build_admin_intelligence(
            conn, operating_day=date(2026, 8, 11), is_super_admin=False
        )
    with _connection(db) as conn:
        ultimate = admin_intelligence.build_admin_intelligence(
            conn, operating_day=date(2026, 8, 11), is_super_admin=True
        )

    for section in ("ai_cost", "source_health", "publication", "recommendations"):
        assert ordinary["operations"][section] is None, section
    # source_health, ai_cost and recommendations always resolve to *something*
    # once is_super_admin is True — a fallback list, a zeroed dict, the fake
    # store's data — regardless of whether the underlying table exists.
    # publication is excluded here: it legitimately stays None for BOTH admin
    # levels in this stand-in DB, which has no pipeline_catalog_sync row at
    # all — see test_pipeline_operations_telemetry_... for its gating proof.
    for section in ("ai_cost", "source_health", "recommendations"):
        assert ultimate["operations"][section] is not None, section
    assert ultimate["operations"]["ai_cost"]["tracking_available"] is False  # no ai_usage table
    assert ultimate["operations"]["recommendations"]["tracking_available"] is True
    # Quality-gate and pipeline-phase alerts stay visible to every admin; only
    # the source-health-derived alert (a per-source breakdown) is withheld.
    assert not any("source health" in alert["title"] for alert in ordinary["operations"]["alerts"])


def test_snapshot_uses_one_operating_day_for_today_and_history(tmp_path, monkeypatch):
    db = tmp_path / "jobs.db"
    make_jobs_db(db)
    monkeypatch.setattr(
        admin_intelligence.seekers_store,
        "get_store",
        lambda: _RecommendationStore(),
    )
    with _connection(db) as conn:
        conn.execute(
            """CREATE TABLE job_history (
                   company_id TEXT, company_name TEXT, job_count INTEGER,
                   scraped_date TEXT, jobs_added INTEGER, jobs_removed INTEGER
               )"""
        )
        conn.executemany(
            "INSERT INTO job_history VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("hsbc", "HSBC", 10, "2026-08-10", 1, 0),
                ("hsbc", "HSBC", 12, "2026-08-11", 2, 0),
            ],
        )
        snapshot = admin_intelligence.build_admin_intelligence(
            conn,
            history_days=1,
            operating_day=date(2026, 8, 11),
        )

    assert snapshot["operating_date"] == "2026-08-11"
    assert snapshot["today"]["date"] == "2026-08-11"
    assert snapshot["today"]["listings_collected_today"] == 12
    assert snapshot["history"]["days"] == 1
    assert [point["scraped_date"] for point in snapshot["history"]["points"]] == [
        "2026-08-10",
        "2026-08-11",
    ]


# ── Source health states what actually went wrong ─────────────────────────────
# The old rule was `successful / companies`, where a company is success, zero or
# failed — and `zero` means the adapter worked perfectly and the employer had no
# vacancies that day. Scoring a quiet employer identically to a crash put "failed"
# on the dashboard for a pipeline in which nothing had failed: Boutique sites read
# 47.8% failed because 36 of 69 small HK asset managers were not hiring, which is
# their normal state. Health now follows failures, and "not hiring" is reported
# separately instead of being punished.

def _seed_company_runs(db, rows, day="2026-08-18"):
    # Build the table with the real migration rather than a hand-written copy, so
    # this fixture cannot drift from the shape production actually has.
    from hk_jobs.migrations import migrate_to_phase_35

    migrate_to_phase_35(str(db))
    conn = sqlite3.connect(db)
    with conn:
        for source, slug, status, found in rows:
            conn.execute(
                "INSERT OR REPLACE INTO pipeline_company_runs (run_id, scraped_date,"
                " source, company_slug, company_name, status, jobs_found, recorded_at)"
                " VALUES ('r1',?,?,?,?,?,?,?)",
                (day, source, slug, slug, status, found, f"{day}T00:00:00Z"),
            )
    conn.close()


def _health(db, monkeypatch):
    monkeypatch.setattr(
        admin_intelligence.seekers_store, "get_store", lambda: _RecommendationStore()
    )
    with _connection(db) as conn:
        snap = admin_intelligence.build_admin_intelligence(
            conn, operating_day=date(2026, 8, 18), is_super_admin=True
        )
    return {row["source"]: row for row in snap["operations"]["source_health"]}


def test_a_source_where_nothing_failed_is_healthy_however_few_are_hiring(tmp_path, monkeypatch):
    """69 boutiques ran, 36 had no openings, none errored. That is a healthy
    source and a quiet market, not a failure."""
    db = tmp_path / "jobs.db"
    make_jobs_db(db)
    rows = [("longtail", f"boutique-{i}", "success", 2) for i in range(33)]
    rows += [("longtail", f"quiet-{i}", "zero", 0) for i in range(36)]
    _seed_company_runs(db, rows)

    got = _health(db, monkeypatch)["longtail"]
    assert got["failed"] == 0
    assert got["status"] == "healthy"
    assert got["zero_results"] == 36
    assert got["failure_rate_pct"] == 0.0


def test_not_hiring_is_reported_separately_from_failing(tmp_path, monkeypatch):
    """The number that was being shown as a success rate is still available — it
    is just no longer what decides the badge."""
    db = tmp_path / "jobs.db"
    make_jobs_db(db)
    _seed_company_runs(db, [("jobsdb", "a", "success", 5), ("jobsdb", "b", "zero", 0)])

    got = _health(db, monkeypatch)["jobsdb"]
    assert got["hiring_rate_pct"] == 50.0
    assert got["status"] == "healthy"


def test_real_failures_downgrade_the_source(tmp_path, monkeypatch):
    db = tmp_path / "jobs.db"
    make_jobs_db(db)
    rows = [("linkedin", f"ok-{i}", "success", 3) for i in range(9)]
    rows += [("linkedin", "broken", "failed", 0)]
    _seed_company_runs(db, rows)

    got = _health(db, monkeypatch)["linkedin"]
    assert got["failure_rate_pct"] == 10.0
    assert got["status"] == "warning"


def test_many_failures_are_a_failed_source(tmp_path, monkeypatch):
    db = tmp_path / "jobs.db"
    make_jobs_db(db)
    rows = [("workday", f"ok-{i}", "success", 3) for i in range(6)]
    rows += [("workday", f"broken-{i}", "failed", 0) for i in range(4)]
    _seed_company_runs(db, rows)

    assert _health(db, monkeypatch)["workday"]["status"] == "failed"


def test_a_source_that_returned_nothing_at_all_is_failed_even_with_no_errors(
    tmp_path, monkeypatch
):
    """The signal the old rule DID catch by accident, and the one that matters:
    every company 'succeeded' in the sense of not raising, and the source still
    produced zero Roles. That is what a silently broken adapter looks like — it is
    how Indeed behaved before it was disabled — so it must not read as healthy."""
    db = tmp_path / "jobs.db"
    make_jobs_db(db)
    _seed_company_runs(db, [("indeed", f"c-{i}", "zero", 0) for i in range(8)])

    got = _health(db, monkeypatch)["indeed"]
    assert got["failed"] == 0
    assert got["roles_found"] == 0
    assert got["status"] == "failed"
