"""Tests for hk_jobs/storage.py — SQLite persistence layer."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from hk_jobs.schema import Job
from hk_jobs.storage import JobStore

# ── helpers ───────────────────────────────────────────────────────────────────

def _job(source_id: str = "J-001", company_slug: str = "hsbc", **overrides) -> Job:
    now = datetime.now(UTC)
    defaults = dict(
        source="workday",
        source_id=source_id,
        company="HSBC",
        company_slug=company_slug,
        url=f"https://example.com/jobs/{source_id}",
        title="Software Engineer",
        locations=["Hong Kong"],
        fetched_at=now,
    )
    defaults.update(overrides)
    return Job(**defaults)


@pytest.fixture
def store(tmp_path: Path):
    db = str(tmp_path / "test.db")
    s = JobStore(db)
    yield s
    s.close()


@pytest.fixture
def migrated_store(tmp_path: Path):
    # grp_new/grp_urgent/grp_applicants are Phase-22 columns — JobStore's own
    # ensure_schema() only creates the base table, so refresh_signal_flags()
    # tests need the real migration ledger applied first (same pattern as
    # tests/test_job_edit.py).
    from hk_jobs.migrations import migrate

    db = str(tmp_path / "migrated.db")
    migrate(db)
    s = JobStore(db)
    yield s
    s.close()


# ── schema creation ───────────────────────────────────────────────────────────

def test_store_creates_table(tmp_path):
    import sqlite3

    db = str(tmp_path / "new.db")
    with JobStore(db):
        conn = sqlite3.connect(db)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
    assert "jobs" in tables


def test_store_creates_indexes(tmp_path):
    import sqlite3

    db = str(tmp_path / "idx.db")
    with JobStore(db):
        conn = sqlite3.connect(db)
        indexes = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
        }
        conn.close()
    assert "idx_jobs_company_slug" in indexes
    assert "idx_jobs_dedup_hash" in indexes
    assert "idx_jobs_is_active" in indexes
    assert "idx_jobs_seniority" in indexes


# ── upsert_many ───────────────────────────────────────────────────────────────

def test_insert_two_new_jobs(store):
    jobs = [_job("J-001"), _job("J-002")]
    inserted, updated = store.upsert_many(jobs)
    assert inserted == 2
    assert updated == 0


def test_update_same_two_jobs(store):
    jobs = [_job("J-001"), _job("J-002")]
    store.upsert_many(jobs)
    inserted, updated = store.upsert_many(jobs)
    assert inserted == 0
    assert updated == 2


def test_no_duplicates_after_re_insert(store):
    store.upsert_many([_job("J-001")])
    store.upsert_many([_job("J-001")])
    count = store._conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE source_id='J-001'"
    ).fetchone()[0]
    assert count == 1


def test_empty_list_returns_zeros(store):
    assert store.upsert_many([]) == (0, 0)


def test_upsert_refreshes_title(store):
    store.upsert_many([_job("J-001", title="Old Title")])
    store.upsert_many([_job("J-001", title="New Title")])
    row = store._conn.execute("SELECT title FROM jobs WHERE source_id='J-001'").fetchone()
    assert row["title"] == "New Title"


def test_upsert_stores_json_lists(store):
    import json

    job = _job("J-001", locations=["Hong Kong", "Singapore"],
               skills_required=["python", "sql"])
    store.upsert_many([job])
    row = store._conn.execute("SELECT locations, skills_required FROM jobs").fetchone()
    assert json.loads(row["locations"]) == ["Hong Kong", "Singapore"]
    assert json.loads(row["skills_required"]) == ["python", "sql"]


def test_upsert_stores_datetimes_as_iso(store):
    fixed = datetime(2024, 6, 1, 9, 0, 0, tzinfo=UTC)
    job = _job("J-001", fetched_at=fixed, posted_at=fixed)
    store.upsert_many([job])
    row = store._conn.execute("SELECT fetched_at, posted_at FROM jobs").fetchone()
    assert "2024-06-01" in row["fetched_at"]
    assert "2024-06-01" in row["posted_at"]


def test_upsert_sets_is_active_1(store):
    store.upsert_many([_job("J-001")])
    row = store._conn.execute("SELECT is_active FROM jobs").fetchone()
    assert row["is_active"] == 1


def test_upsert_reactivates_previously_inactive(store):
    store.upsert_many([_job("J-001")])
    store._conn.execute("UPDATE jobs SET is_active=0 WHERE source_id='J-001'")
    store._conn.commit()
    store.upsert_many([_job("J-001")])
    row = store._conn.execute("SELECT is_active FROM jobs WHERE source_id='J-001'").fetchone()
    assert row["is_active"] == 1


def test_upsert_stores_dedup_hash(store):
    job = _job("J-001")
    store.upsert_many([job])
    row = store._conn.execute("SELECT dedup_hash FROM jobs").fetchone()
    assert row["dedup_hash"] == job.dedup_hash()
    assert len(row["dedup_hash"]) == 12


# ── mark_inactive_for_run ─────────────────────────────────────────────────────

def test_mark_inactive_deactivates_stale_rows(store):
    run_time = datetime.now(UTC)
    old_time = run_time - timedelta(hours=1)

    # One job fetched in this run, one that's older (stale)
    store.upsert_many([
        _job("J-001", fetched_at=run_time),
        _job("J-002", fetched_at=old_time),
    ])
    deactivated = store.mark_inactive_for_run("hsbc", run_time)

    assert deactivated == 1
    row = store._conn.execute("SELECT is_active FROM jobs WHERE source_id='J-002'").fetchone()
    assert row["is_active"] == 0


def test_mark_inactive_leaves_current_rows_active(store):
    run_time = datetime.now(UTC)
    store.upsert_many([_job("J-001", fetched_at=run_time)])
    store.mark_inactive_for_run("hsbc", run_time)
    row = store._conn.execute("SELECT is_active FROM jobs WHERE source_id='J-001'").fetchone()
    assert row["is_active"] == 1


def test_mark_inactive_only_affects_target_company(store):
    run_time = datetime.now(UTC)
    old_time = run_time - timedelta(hours=1)

    store.upsert_many([
        _job("J-001", company_slug="hsbc", fetched_at=old_time),
        _job("J-002", company_slug="aia",  fetched_at=old_time),
    ])
    store.mark_inactive_for_run("hsbc", run_time)

    hsbc_row = store._conn.execute(
        "SELECT is_active FROM jobs WHERE source_id='J-001'"
    ).fetchone()
    aia_row = store._conn.execute(
        "SELECT is_active FROM jobs WHERE source_id='J-002'"
    ).fetchone()
    assert hsbc_row["is_active"] == 0
    assert aia_row["is_active"] == 1  # not touched


def test_mark_inactive_returns_count(store):
    run_time = datetime.now(UTC)
    old_time = run_time - timedelta(hours=1)
    store.upsert_many([
        _job("J-001", fetched_at=old_time),
        _job("J-002", fetched_at=old_time),
        _job("J-003", fetched_at=run_time),
    ])
    count = store.mark_inactive_for_run("hsbc", run_time)
    assert count == 2


# ── stats ─────────────────────────────────────────────────────────────────────

def test_stats_empty_store(store):
    s = store.stats()
    assert s["total"] == 0
    assert s["active"] == 0
    assert s["by_company"] == {}


def test_stats_after_inserts(store):
    store.upsert_many([_job("J-001"), _job("J-002"), _job("J-003")])
    s = store.stats()
    assert s["total"] == 3
    assert s["active"] == 3
    assert s["by_company"]["hsbc"] == 3


def test_stats_after_soft_delete(store):
    run_time = datetime.now(UTC)
    old_time = run_time - timedelta(hours=1)
    store.upsert_many([
        _job("J-001", fetched_at=run_time),
        _job("J-002", fetched_at=old_time),
    ])
    store.mark_inactive_for_run("hsbc", run_time)
    s = store.stats()
    assert s["total"] == 2
    assert s["active"] == 1
    assert s["by_company"]["hsbc"] == 1


def test_stats_multi_company(store):
    store.upsert_many([
        _job("J-001", company_slug="hsbc"),
        _job("J-002", company_slug="hsbc"),
        _job("J-003", company_slug="aia"),
    ])
    s = store.stats()
    assert s["by_company"]["hsbc"] == 2
    assert s["by_company"]["aia"] == 1


# ── context manager ───────────────────────────────────────────────────────────

def test_context_manager(tmp_path):
    db = str(tmp_path / "ctx.db")
    with JobStore(db) as store:
        store.upsert_many([_job("J-001")])
    # Connection should be closed; further queries should raise
    with pytest.raises(Exception):
        store._conn.execute("SELECT 1")


# ── refresh_signal_flags: the "New" badge's 14-day cap ────────────────────────
# A source's own new_job badge is a one-time snapshot (set by the adapter at
# scrape time) that never expires on its own — a job that ages off a source's
# listing pages before the badge does stops being re-scraped, so board_signals
# is never refreshed again and new_job stays true forever. These prove
# refresh_signal_flags() caps it by posted_at instead, for both the grp_new
# filter column AND the raw board_signals a job card reads directly.

def _board_signals(store, source_id="J-001"):
    import json
    row = store._conn.execute(
        "SELECT board_signals FROM jobs WHERE source_id=?", (source_id,)
    ).fetchone()
    return json.loads(row["board_signals"])


def _grp(store, column, source_id="J-001"):
    row = store._conn.execute(
        f"SELECT {column} FROM jobs WHERE source_id=?", (source_id,)
    ).fetchone()
    return row[column]


def test_refresh_signal_flags_keeps_a_recent_new_job(migrated_store):
    posted = datetime.now(UTC) - timedelta(days=3)
    job = _job("J-001", posted_at=posted, board_signals={"new_job": True})
    migrated_store.upsert_many([job])
    migrated_store.refresh_signal_flags()
    assert _grp(migrated_store, "grp_new") == 1
    assert _board_signals(migrated_store)["new_job"] is True


def test_refresh_signal_flags_expires_new_job_past_the_cap(migrated_store):
    # Posted well beyond _NEW_BADGE_MAX_AGE_DAYS (14) — the exact bug reported:
    # a job the source itself stopped calling "new" months ago, frozen at
    # new_job=True because it was never re-scraped after its first listing.
    posted = datetime.now(UTC) - timedelta(days=60)
    job = _job("J-001", posted_at=posted, board_signals={"new_job": True})
    migrated_store.upsert_many([job])
    migrated_store.refresh_signal_flags()
    assert _grp(migrated_store, "grp_new") == 0
    # Not just the filter column — the per-card badge reads board_signals
    # directly, so the stale key must be gone, not merely falsy.
    assert "new_job" not in _board_signals(migrated_store)


def test_refresh_signal_flags_expires_new_job_with_no_posted_at(migrated_store):
    # Fails closed: no posted_at means the age can't be verified, so it must
    # not be trusted as new either.
    job = _job("J-001", posted_at=None, board_signals={"new_job": True})
    migrated_store.upsert_many([job])
    migrated_store.refresh_signal_flags()
    assert _grp(migrated_store, "grp_new") == 0
    assert "new_job" not in _board_signals(migrated_store)


def test_refresh_signal_flags_leaves_other_signals_untouched_by_the_cap(migrated_store):
    # The age cap is specific to new_job — urgently_hiring has no such source-side
    # expiry problem and must not be collaterally stripped or zeroed.
    posted = datetime.now(UTC) - timedelta(days=60)
    job = _job(
        "J-001", posted_at=posted,
        board_signals={"new_job": True, "urgently_hiring": True},
    )
    migrated_store.upsert_many([job])
    migrated_store.refresh_signal_flags()
    assert _grp(migrated_store, "grp_urgent") == 1
    assert _board_signals(migrated_store)["urgently_hiring"] is True
