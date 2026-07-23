"""Tests for hk_jobs/posts/expiry.py."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from hk_jobs.posts.expiry import DEFAULT_MAX_AGE_DAYS, deactivate_stale_jobs
from hk_jobs.schema import Job
from hk_jobs.storage import JobStore


@pytest.fixture
def db(tmp_path: Path) -> str:
    return str(tmp_path / "test.db")


def _post_job(source_id: str, posted_at, source="linkedin_posts") -> Job:
    return Job(
        source=source, source_id=source_id, company="Confidential via X",
        company_slug=f"confidential-x-{source_id}", url="https://linkedin.com/posts/1",
        title="Analyst", locations=["Hong Kong"], fetched_at=datetime.now(UTC),
        posted_at=posted_at, source_tier="social",
    )


def test_deactivates_only_posts_older_than_cutoff(db):
    now = datetime.now(UTC)
    with JobStore(db) as store:
        store.upsert_many([
            _post_job("recent", now - timedelta(days=10)),
            _post_job("borderline", now - timedelta(days=89)),
            _post_job("stale", now - timedelta(days=100)),
            _post_job("very-stale", now - timedelta(days=900)),
        ])

    count = deactivate_stale_jobs(db, max_age_days=90)
    assert count == 2  # stale + very-stale

    with JobStore(db) as store:
        rows = {
            r["source_id"]: r["is_active"]
            for r in store._conn.execute("SELECT source_id, is_active FROM jobs").fetchall()
        }
    assert rows["recent"] == 1
    assert rows["borderline"] == 1
    assert rows["stale"] == 0
    assert rows["very-stale"] == 0


def test_leaves_null_posted_at_untouched(db):
    with JobStore(db) as store:
        store.upsert_many([_post_job("no-date", None)])

    count = deactivate_stale_jobs(db, max_age_days=90)
    assert count == 0

    with JobStore(db) as store:
        row = store._conn.execute("SELECT is_active FROM jobs WHERE source_id='no-date'").fetchone()
    assert row["is_active"] == 1


def test_scoped_to_linkedin_posts_only(db):
    now = datetime.now(UTC)
    with JobStore(db) as store:
        store.upsert_many([
            _post_job("old-social", now - timedelta(days=200), source="linkedin_posts"),
            _post_job("old-mainstream", now - timedelta(days=200), source="workday"),
        ])

    count = deactivate_stale_jobs(db, max_age_days=90)
    assert count == 1

    with JobStore(db) as store:
        rows = {
            r["source_id"]: r["is_active"]
            for r in store._conn.execute("SELECT source_id, is_active FROM jobs").fetchall()
        }
    assert rows["old-social"] == 0
    assert rows["old-mainstream"] == 1  # untouched -- not linkedin_posts


def test_already_inactive_job_not_double_counted(db):
    now = datetime.now(UTC)
    with JobStore(db) as store:
        store.upsert_many([_post_job("stale", now - timedelta(days=200))])
        store._conn.execute("UPDATE jobs SET is_active = 0 WHERE source_id = 'stale'")
        store._conn.commit()

    count = deactivate_stale_jobs(db, max_age_days=90)
    assert count == 0  # already inactive, not re-counted


def test_default_max_age_is_90_days(db):
    now = datetime.now(UTC)
    with JobStore(db) as store:
        store.upsert_many([_post_job("stale", now - timedelta(days=100))])

    count = deactivate_stale_jobs(db)
    assert count == 1
    assert DEFAULT_MAX_AGE_DAYS == 90
