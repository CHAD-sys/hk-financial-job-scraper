"""The weekly rail is curated explicitly, not inferred from a live board query."""

from __future__ import annotations

import sqlite3
from datetime import date

from fastapi.testclient import TestClient

from hk_jobs.migrations import migrate_to_phase_42
from hk_jobs.weekly_highlights import (
    WeeklyHighlightRef,
    current_weekly_highlights,
    save_weekly_highlights,
    week_bounds,
)
from tests.support import enrichment, job, make_app, make_jobs_db


def _make_highlight_client(tmp_path):
    db = tmp_path / "jobs.db"
    make_jobs_db(
        db,
        jobs=[
            job(
                source="workday",
                source_id="FEATURED",
                company="HSBC",
                title="Featured Risk Director",
                is_active=0,
                closed_at=date.today().isoformat(),
            ),
            job(
                source="workday",
                source_id="OTHER",
                company="Citi",
                title="Other Risk Director",
            ),
        ],
        enrichments=[
            enrichment(
                source="workday",
                source_id="FEATURED",
                job_category="Risk",
                seniority="Director",
                salary_estimated_min=90_000,
                salary_estimated_max=120_000,
                description_summary="Lead a regional risk function.",
            ),
            enrichment(
                source="workday",
                source_id="OTHER",
                job_category="Risk",
                seniority="Director",
                salary_estimated_min=90_000,
                salary_estimated_max=120_000,
            ),
        ],
    )
    migrate_to_phase_42(str(db))
    start, _ = week_bounds(date.today())
    save_weekly_highlights(
        db,
        [WeeklyHighlightRef("workday", "FEATURED", "Risk")],
        week_start=start,
    )
    return db, TestClient(make_app(db, cookie_secure=False))


def test_weekly_selection_can_be_replaced_after_the_first_save(tmp_path):
    db = tmp_path / "jobs.db"
    make_jobs_db(
        db,
        jobs=[
            job(source="workday", source_id="FIRST"),
            job(source="workday", source_id="SECOND"),
        ],
    )
    migrate_to_phase_42(str(db))
    start, _ = week_bounds(date.today())

    first = save_weekly_highlights(
        db,
        [WeeklyHighlightRef("workday", "FIRST", "Risk")],
        week_start=start,
    )
    second = save_weekly_highlights(
        db,
        [WeeklyHighlightRef("workday", "SECOND", "Markets")],
        week_start=start,
    )

    assert second != first
    with sqlite3.connect(db) as conn:
        assert current_weekly_highlights(conn, as_of=date.today()) == second


def test_weekly_selection_can_be_cleared_after_it_was_saved(tmp_path):
    db = tmp_path / "jobs.db"
    make_jobs_db(db, jobs=[job(source="workday", source_id="FIRST")])
    migrate_to_phase_42(str(db))
    start, _ = week_bounds(date.today())
    save_weekly_highlights(
        db,
        [WeeklyHighlightRef("workday", "FIRST", "Risk")],
        week_start=start,
    )

    saved = save_weekly_highlights(db, [], week_start=start)

    assert saved == []
    with sqlite3.connect(db) as conn:
        assert current_weekly_highlights(conn, as_of=date.today()) == []


def test_highlight_feed_never_advertises_a_closed_role_on_the_homepage(tmp_path):
    _, client = _make_highlight_client(tmp_path)

    response = client.get("/api/highlights")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["roles"] == []


def test_exact_highlight_resolver_grants_only_this_weeks_pinned_roles(tmp_path):
    _, client = _make_highlight_client(tmp_path)

    featured = client.get("/api/highlights/roles/workday/FEATURED")
    arbitrary = client.get("/api/highlights/roles/workday/OTHER")

    assert featured.status_code == 200, featured.text
    assert featured.json()["access_token"]
    assert arbitrary.status_code == 404
