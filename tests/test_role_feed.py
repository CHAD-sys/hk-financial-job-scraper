"""Behavior contract for the deep Roles-for-a-Seeker module."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import job_read
import role_feed
import seekers_store

from .support import enrichment, job, make_jobs_db

NOW = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)


def _jobs_database(tmp_path):
    path = tmp_path / "jobs.db"
    make_jobs_db(
        path,
        jobs=[
            job(
                source="workday",
                source_id="SAVED",
                company="HSBC",
                title="Credit Risk Analyst",
                posted_at="2026-08-10T00:00:00+00:00",
            ),
            job(
                source="workday",
                source_id="RISK",
                company="Hang Seng Bank",
                title="Senior Credit Risk Manager",
                posted_at="2026-08-09T00:00:00+00:00",
            ),
            job(
                source="eightfold",
                source_id="ACTUARY",
                company="AIA",
                title="Actuarial Manager",
                posted_at="2026-08-08T00:00:00+00:00",
            ),
        ],
        enrichments=[
            enrichment(
                source="workday",
                source_id="SAVED",
                seniority="mid",
                required_skills='["credit risk", "sql"]',
            ),
            enrichment(
                source="workday",
                source_id="RISK",
                seniority="mid",
                required_skills='["credit risk", "sql"]',
            ),
            enrichment(
                source="eightfold",
                source_id="ACTUARY",
                seniority="senior",
                required_skills='["actuarial modelling"]',
            ),
        ],
    )
    connection = sqlite3.connect(path)
    job_read.prepare(connection)
    return connection


def _store(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEKERS_DB_PATH", str(tmp_path / "seekers.db"))
    seekers_store.reset_store()
    return seekers_store.get_store()


def test_anonymous_feed_is_market_based_and_has_no_seeker_side_effect(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    with _jobs_database(tmp_path) as jobs:
        feed = role_feed.roles_for_seeker(
            jobs,
            seeker_id=None,
            page=1,
            page_size=2,
            now=NOW,
        )

    assert feed.personalized is False
    assert feed.personalization_enabled is False
    assert feed.batch_id is None
    assert len(feed.items) == 2
    assert store.list_recommendation_impressions("missing") == []

    with sqlite3.connect(tmp_path / "jobs.db") as jobs:
        job_read.prepare(jobs)
        bounded = role_feed.roles_for_seeker(
            jobs,
            seeker_id=None,
            page=999,
            page_size=0,
            now=NOW,
        )
    assert (bounded.page, bounded.page_size) == (10, 1)


def test_feed_assembles_signals_exclusions_feedback_and_impressions(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    seeker_id = store.create_seeker("ada@example.com", now=NOW)
    store.save_role(seeker_id, "workday", "SAVED", now=NOW)
    store.record_discovery(
        seeker_id,
        search_query="credit risk",
        filters={"seniority": ["mid"]},
        result_count=2,
        now=NOW,
    )
    store.record_recommendation_feedback(
        seeker_id,
        "workday",
        "RISK",
        action="more_like",
        now=NOW,
    )
    store.record_recommendation_feedback(
        seeker_id,
        "eightfold",
        "ACTUARY",
        action="not_interested",
        now=NOW,
    )

    with _jobs_database(tmp_path) as jobs:
        feed = role_feed.roles_for_seeker(
            jobs,
            seeker_id=seeker_id,
            page=1,
            page_size=3,
            now=NOW,
        )

    assert feed.personalized is True
    assert feed.saved_role_count == 1
    assert feed.activity_count == 1
    assert [item.job.source_id for item in feed.items] == ["RISK"]
    assert feed.items[0].feedback == ("more_like",)
    assert feed.batch_id
    impressions = store.list_recommendation_impressions(seeker_id)
    assert len(impressions) == 1
    assert impressions[0]["batch_id"] == feed.batch_id
    assert impressions[0]["source_id"] == "RISK"
    health = store.recommendation_health()
    assert health["window_started_at"] == NOW.isoformat()
    assert health["window_ended_at"] == NOW.isoformat()


def test_resume_is_a_bounded_personalization_signal_in_the_role_feed(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    seeker_id = store.create_seeker("actuary@example.com", now=NOW)
    content = b"resume"
    store.replace_resume(
        seeker_id,
        filename="resume.pdf",
        media_type="application/pdf",
        size_bytes=len(content),
        content_sha256="b" * 64,
        file_content=content,
        text_content="Actuarial manager with insurance modelling experience",
        analysis={
            "skills": ["actuarial modelling"],
            "role_families": ["actuarial"],
            "sectors": ["insurance"],
            "years_experience": 8,
            "seniority": "senior",
        },
        now=NOW,
    )

    with _jobs_database(tmp_path) as jobs:
        feed = role_feed.roles_for_seeker(
            jobs,
            seeker_id=seeker_id,
            page=1,
            page_size=3,
            now=NOW,
        )

    assert feed.personalized is True
    assert feed.signal_count == 1
    assert feed.items[0].job.source_id == "ACTUARY"
    assert any("resume" in reason.lower() for reason in feed.items[0].reasons)


def test_resume_matches_share_candidate_policy_but_do_not_write_impressions(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    seeker_id = store.create_seeker("resume@example.com", now=NOW)
    jobs = _jobs_database(tmp_path)

    with jobs:
        empty = role_feed.resume_matches_for_seeker(
            jobs,
            seeker_id=seeker_id,
            limit=2,
        )
    assert empty.has_resume is False

    content = b"resume"
    store.replace_resume(
        seeker_id,
        filename="resume.pdf",
        media_type="application/pdf",
        size_bytes=len(content),
        content_sha256="a" * 64,
        file_content=content,
        text_content="Senior credit risk manager with SQL experience",
        analysis={
            "skills": ["credit risk", "sql"],
            "role_families": ["credit risk"],
            "sectors": ["banking"],
            "years_experience": 7,
            "seniority": "senior",
        },
        now=NOW,
    )

    jobs = sqlite3.connect(tmp_path / "jobs.db")
    job_read.prepare(jobs)
    with jobs:
        result = role_feed.resume_matches_for_seeker(
            jobs,
            seeker_id=seeker_id,
            limit=2,
        )

    assert result.has_resume is True
    assert "RISK" in {item.job.source_id for item in result.items}
    assert result.items[0].match_score >= 40
    assert store.list_recommendation_impressions(seeker_id) == []
