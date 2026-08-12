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
