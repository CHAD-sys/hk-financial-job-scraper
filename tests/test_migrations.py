"""
The migration ledger: what has run, and what still needs to.

Before this existed, "is this database up to date?" was answered by reading
`pipeline.main()`'s import list and comparing it against the `def`s in
`migrations.py` by eye. Two of these tests are the two ways that failed in
practice — a phase that was never added to the list (27, 28), and a database
that could not be built from nothing at all.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from hk_jobs import migrations
from hk_jobs.migrations import (
    LATEST_PHASE,
    MIGRATIONS,
    applied_phases,
    migrate,
    migrate_to_phase_34,
)


def _db(tmp_path: Path) -> str:
    return str(tmp_path / "jobs.db")


def _tables(db_path: str) -> set[str]:
    conn = sqlite3.connect(db_path)
    try:
        return {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        conn.close()


def _columns(db_path: str, table: str) -> set[str]:
    conn = sqlite3.connect(db_path)
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    finally:
        conn.close()


# ── The list is the registry ──────────────────────────────────────────────────

def test_every_migration_function_is_registered():
    """
    THE regression this module exists for.

    Phases 27 and 28 were written, and never added to the startup path. They ran
    only inside `--promote-posts` and `--harvest-recruiter-emails`, so a database
    that had never been asked to do either silently lacked their columns. There
    was nothing to notice it — the list of migrations to run and the list of
    migrations that exist were two hand-maintained lists in different files.
    """
    defined = {
        int(name.rsplit("_", 1)[1])
        for name in dir(migrations)
        if name.startswith("migrate_to_phase_")
    }
    registered = {phase for phase, _ in MIGRATIONS}
    assert defined == registered, (
        f"unregistered migration(s): {sorted(defined - registered)} — "
        "append them to MIGRATIONS"
    )


def test_migrations_are_ordered_and_unique():
    """
    Order is load-bearing: 10 creates `jobs` before the seven phases that alter
    it, 26 creates `linkedin_posts` before 27 adds columns to it.
    """
    phases = [phase for phase, _ in MIGRATIONS]
    assert phases == sorted(phases)
    assert len(phases) == len(set(phases))


def test_latest_phase_is_the_last_entry():
    assert LATEST_PHASE == MIGRATIONS[-1][0]


# ── Bootstrapping ─────────────────────────────────────────────────────────────

def test_a_database_can_be_built_from_nothing(tmp_path: Path):
    """
    It could not be, before phase 10.

    Seven migrations `ALTER TABLE jobs`, but `jobs` was created by
    `JobStore.__init__` — which `main()` did not reach until after the
    migrations had already raised `no such table: jobs`. Anyone pointing the
    pipeline at a new `--db` path hit it immediately.
    """
    db = _db(tmp_path)
    applied = migrate(db)

    assert applied == [phase for phase, _ in MIGRATIONS]
    assert "jobs" in _tables(db)


def test_every_table_the_phases_promise_exists_after_one_migrate(tmp_path: Path):
    db = _db(tmp_path)
    migrate(db)

    assert {
        "jobs",
        "job_history",
        "company_metrics",
        "job_enrichments",
        "linkedin_posts",
        "recruiter_fetch_state",
        "vendor_costs",
        "salary_audit_log",
    } <= _tables(db)


def test_the_unregistered_phases_columns_are_present(tmp_path: Path):
    """The concrete cost of the drift: these columns were the ones missing."""
    db = _db(tmp_path)
    migrate(db)

    assert "extraction_result_json" in _columns(db, "linkedin_posts")       # phase 27
    assert "email_fetched_at" in _columns(db, "recruiter_fetch_state")      # phase 28


# ── The ledger ────────────────────────────────────────────────────────────────

def test_migrate_is_a_no_op_the_second_time(tmp_path: Path):
    db = _db(tmp_path)
    migrate(db)
    assert migrate(db) == []


def test_applied_phases_reports_what_ran(tmp_path: Path):
    db = _db(tmp_path)
    migrate(db)
    assert applied_phases(db) == {phase for phase, _ in MIGRATIONS}


def test_an_applied_phase_does_not_run_again(tmp_path: Path, monkeypatch):
    """The ledger is a gate, not a log — that is the whole reason it is here."""
    db = _db(tmp_path)
    migrate(db)

    calls: list[int] = []
    patched = tuple(
        (phase, lambda _p, n=phase: calls.append(n)) for phase, _ in MIGRATIONS
    )
    monkeypatch.setattr(migrations, "MIGRATIONS", patched)

    assert migrate(db) == []
    assert calls == []


def test_only_the_new_phase_runs_when_one_is_appended(tmp_path: Path, monkeypatch):
    """Adding a phase costs one function call, not nineteen."""
    db = _db(tmp_path)
    migrate(db)

    calls: list[int] = []
    monkeypatch.setattr(
        migrations,
        "MIGRATIONS",
        (*MIGRATIONS, (999, lambda _p: calls.append(999))),
    )

    assert migrate(db) == [999]
    assert calls == [999]
    assert 999 in applied_phases(db)


def test_a_failing_phase_leaves_the_earlier_ones_recorded(tmp_path: Path, monkeypatch):
    """
    A run that dies halfway resumes where it stopped rather than starting over.
    """
    db = _db(tmp_path)

    def boom(_path: str) -> None:
        raise RuntimeError("phase exploded")

    monkeypatch.setattr(migrations, "MIGRATIONS", (*MIGRATIONS, (999, boom)))

    with pytest.raises(RuntimeError, match="phase exploded"):
        migrate(db)

    recorded = applied_phases(db)
    assert {phase for phase, _ in MIGRATIONS} <= recorded
    assert 999 not in recorded


def test_a_pre_ledger_database_converges_without_re_running_anything_twice(tmp_path: Path):
    """
    The live database's own case: every migration applied, no ledger.

    It is indistinguishable from a database that has never been migrated, which
    is safe only because every migration is idempotent. The first `migrate()`
    re-applies all of them as no-ops and records them; the second does nothing.
    """
    db = _db(tmp_path)
    for _phase, fn in MIGRATIONS:
        fn(db)                       # migrated the old way — no ledger written

    conn = sqlite3.connect(db)
    try:
        assert "schema_migrations" not in _tables(db)
        before = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    finally:
        conn.close()

    assert migrate(db) == [phase for phase, _ in MIGRATIONS]
    assert migrate(db) == []

    conn = sqlite3.connect(db)
    try:
        after = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name != 'schema_migrations'"
            " ORDER BY name"
        ).fetchall()
    finally:
        conn.close()
    assert after == before, "converging on a ledger must not change the schema"


# ── Phase 30: when a Listing closed ───────────────────────────────────────────

def _closed_at(db_path: str, source_id: str) -> str | None:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT closed_at FROM jobs WHERE source_id = ?", (source_id,)
        ).fetchone()[0]
    finally:
        conn.close()


def _seed_undated(db_path: str) -> None:
    """Rows as they look on a database that has never seen phase 30."""
    conn = sqlite3.connect(db_path)
    with conn:
        for source_id, is_active, fetched in (
            ("OPEN", 1, "2026-08-04T09:00:00+00:00"),
            ("CLOSED", 0, "2026-06-11T09:00:00+00:00"),
        ):
            conn.execute(
                "INSERT INTO jobs (source, source_id, company, company_slug, url, dedup_hash,"
                " title, fetched_at, is_active) VALUES ('workday', ?, 'X', 'x',"
                " 'https://e.test', 'h', 'T', ?, ?)",
                (source_id, fetched, is_active),
            )
        conn.execute("UPDATE jobs SET closed_at = NULL")
    conn.close()


def test_phase_30_adds_the_column(tmp_path: Path):
    db = _db(tmp_path)
    migrate(db)
    assert "closed_at" in _columns(db, "jobs")


def test_phase_30_dates_already_closed_listings_from_fetched_at(tmp_path: Path):
    """
    The backfill, and the reason it is `fetched_at`: it is the last time a
    Listing was seen alive, and deactivation happens on the first run that does
    not see it. Approximate on purpose — the alternative was leaving 10,126 rows
    NULL, which hands every long-dead Saved Role a fresh fortnight starting from
    whenever the migration happened to run.
    """
    db = _db(tmp_path)
    migrate(db)
    _seed_undated(db)

    migrations.migrate_to_phase_30(db)

    assert _closed_at(db, "CLOSED") == "2026-06-11T09:00:00+00:00"
    assert _closed_at(db, "OPEN") is None, "an open Listing has no closure date"


def test_phase_30_never_overwrites_a_date_it_already_has(tmp_path: Path):
    """
    Idempotent in the way that matters: re-running must not push a real
    deactivate() timestamp back to the row's older fetched_at, which would age a
    Saved Role by however long the Listing had been stale before it closed.
    """
    db = _db(tmp_path)
    migrate(db)
    _seed_undated(db)
    conn = sqlite3.connect(db)
    with conn:
        conn.execute("UPDATE jobs SET closed_at = '2026-07-30T00:00:00+00:00'"
                     " WHERE source_id = 'CLOSED'")
    conn.close()

    migrations.migrate_to_phase_30(db)

    assert _closed_at(db, "CLOSED") == "2026-07-30T00:00:00+00:00"


def test_phase_30_clears_a_date_left_on_a_reopened_listing(tmp_path: Path):
    """
    A live Role claiming to have closed is the failure that empties a Seeker's
    Saved Roles for no reason. Only reachable on a database migrated mid-flight,
    which is exactly the database this runs against.
    """
    db = _db(tmp_path)
    migrate(db)
    _seed_undated(db)
    conn = sqlite3.connect(db)
    with conn:
        conn.execute("UPDATE jobs SET closed_at = '2026-05-01T00:00:00+00:00'"
                     " WHERE source_id = 'OPEN'")
    conn.close()

    migrations.migrate_to_phase_30(db)

    assert _closed_at(db, "OPEN") is None


def test_phase_33_adds_the_column_and_the_audit_table(tmp_path: Path):
    db = _db(tmp_path)
    migrate(db)
    assert "manually_edited_at" in _columns(db, "job_enrichments")
    assert "admin_edits" in _tables(db)
    assert {"source", "source_id", "seeker_id", "field", "old_value", "new_value", "edited_at"} \
        <= _columns(db, "admin_edits")


def test_phase_33_is_idempotent_on_a_database_that_already_has_the_column(tmp_path: Path):
    db = _db(tmp_path)
    migrate(db)
    migrations.migrate_to_phase_33(db)  # explicit re-run must not raise
    assert "manually_edited_at" in _columns(db, "job_enrichments")


# ── Phase 35: one company can run under several sources ───────────────────────

def _company_run(conn, *, source, slug, status="success", run="r1", day="2026-08-18"):
    conn.execute(
        "INSERT OR REPLACE INTO pipeline_company_runs (run_id, scraped_date, source,"
        " company_slug, company_name, status, jobs_found, recorded_at)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (run, day, source, slug, slug.upper(), status, 1, "2026-08-18T00:00:00Z"),
    )


def test_phase_35_keeps_one_company_that_runs_under_several_sources(tmp_path: Path):
    """Cross-posting is deliberate — citibank-hk is configured on efinancialcareers,
    jobsdb AND linkedin. The old key was (run_id, company_slug), so the second and
    third writes REPLACED the first and the source-health table under-counted
    every source whose companies overlap another's: jobsdb showed 19 companies of
    65 configured, and its success rate was computed on that arbitrary subset."""
    db = str(tmp_path / "jobs.db")
    migrate(db)
    conn = sqlite3.connect(db)
    with conn:
        for source in ("efinancialcareers", "jobsdb", "linkedin"):
            _company_run(conn, source=source, slug="citibank-hk")
    rows = conn.execute(
        "SELECT source FROM pipeline_company_runs WHERE company_slug='citibank-hk'"
    ).fetchall()
    conn.close()
    assert sorted(r[0] for r in rows) == ["efinancialcareers", "jobsdb", "linkedin"]


def test_phase_35_still_collapses_a_repeat_of_the_same_company_and_source(tmp_path: Path):
    """The key still has to dedupe a genuine retry — one company, one source, one
    run is still one row, so a re-run does not double-count it."""
    db = str(tmp_path / "jobs.db")
    migrate(db)
    conn = sqlite3.connect(db)
    with conn:
        _company_run(conn, source="jobsdb", slug="citibank-hk", status="zero")
        _company_run(conn, source="jobsdb", slug="citibank-hk", status="success")
    rows = conn.execute(
        "SELECT status FROM pipeline_company_runs WHERE company_slug='citibank-hk'"
    ).fetchall()
    conn.close()
    assert [r[0] for r in rows] == ["success"]


def test_phase_35_preserves_rows_written_under_the_old_key(tmp_path: Path):
    """The table is rebuilt, so anything already recorded has to survive it."""
    db = str(tmp_path / "jobs.db")
    migrate_to_phase_34(db)
    conn = sqlite3.connect(db)
    with conn:
        _company_run(conn, source="workday", slug="hsbc-hk", day="2026-08-01")
    conn.close()
    migrate(db)
    conn = sqlite3.connect(db)
    kept = conn.execute(
        "SELECT source, scraped_date FROM pipeline_company_runs WHERE company_slug='hsbc-hk'"
    ).fetchone()
    conn.close()
    assert tuple(kept) == ("workday", "2026-08-01")


# ── Phase 39: undoing the retired tech-role filter ────────────────────────────

def _seed_job(db_path: str, source_id: str, *, title: str, is_active: int) -> None:
    conn = sqlite3.connect(db_path)
    with conn:
        conn.execute(
            "INSERT INTO jobs (source, source_id, company, company_slug, url,"
            " dedup_hash, title, fetched_at, is_active) VALUES"
            " ('jobsdb', ?, 'X', 'x', ?, ?, ?, '2026-08-01T00:00:00+00:00', ?)",
            (source_id, f"https://e.test/{source_id}", source_id, title, is_active),
        )
    conn.close()


def _seed_tech_verdict(db_path: str, title: str, is_tech: int) -> None:
    conn = sqlite3.connect(db_path)
    with conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS tech_title_cache"
            " (title TEXT PRIMARY KEY, is_tech INTEGER NOT NULL)"
        )
        conn.execute(
            "INSERT OR REPLACE INTO tech_title_cache (title, is_tech) VALUES (?, ?)",
            (title, is_tech),
        )
    conn.close()


def test_phase_39_reactivates_a_role_the_filter_removed(tmp_path: Path):
    db = _db(tmp_path)
    migrate(db)
    _seed_job(db, "TECH", title="Data Engineer", is_active=0)
    _seed_tech_verdict(db, "Data Engineer", is_tech=1)

    migrations.migrate_to_phase_39(db)

    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT is_active, closed_at FROM jobs WHERE source_id = 'TECH'"
    ).fetchone()
    conn.close()
    assert row == (1, None)


def test_phase_39_leaves_a_non_tech_verdict_alone(tmp_path: Path):
    """The filter kept this title (NOT TECH) — it was never removed, so there's nothing to undo."""
    db = _db(tmp_path)
    migrate(db)
    _seed_job(db, "QUANT", title="Quantitative Analyst", is_active=0)
    _seed_tech_verdict(db, "Quantitative Analyst", is_tech=0)

    migrations.migrate_to_phase_39(db)

    conn = sqlite3.connect(db)
    is_active = conn.execute(
        "SELECT is_active FROM jobs WHERE source_id = 'QUANT'"
    ).fetchone()[0]
    conn.close()
    assert is_active == 0, "not a tech verdict — this migration must not touch it"


def test_phase_39_leaves_an_already_active_tech_titled_role_alone(tmp_path: Path):
    """Only currently-inactive rows are candidates; nothing to reactivate here."""
    db = _db(tmp_path)
    migrate(db)
    _seed_job(db, "LIVE", title="Software Engineer", is_active=1)
    _seed_tech_verdict(db, "Software Engineer", is_tech=1)

    migrations.migrate_to_phase_39(db)

    conn = sqlite3.connect(db)
    is_active = conn.execute(
        "SELECT is_active FROM jobs WHERE source_id = 'LIVE'"
    ).fetchone()[0]
    conn.close()
    assert is_active == 1


def test_phase_39_is_a_no_op_with_no_tech_title_cache(tmp_path: Path):
    """A database the filter never ran on has no cache table at all — must not raise."""
    db = _db(tmp_path)
    migrate(db)  # includes phase 39; must not fail on a cache-less database
    assert "tech_title_cache" not in _tables(db)


def test_phase_39_is_idempotent(tmp_path: Path):
    db = _db(tmp_path)
    migrate(db)
    _seed_job(db, "TECH", title="Data Engineer", is_active=0)
    _seed_tech_verdict(db, "Data Engineer", is_tech=1)

    migrations.migrate_to_phase_39(db)
    migrations.migrate_to_phase_39(db)  # must not raise or double-count

    conn = sqlite3.connect(db)
    is_active = conn.execute(
        "SELECT is_active FROM jobs WHERE source_id = 'TECH'"
    ).fetchone()[0]
    conn.close()
    assert is_active == 1


# ── Phase 40: jobs.grp_seniority ─────────────────────────────────────────────
# Cross-post seniority consensus (see tests/test_seniority_consensus.py for the
# actual voting logic) — this only checks the migration adds the column.

def test_phase_40_adds_the_column(tmp_path: Path):
    db = _db(tmp_path)
    migrate(db)
    assert "grp_seniority" in _columns(db, "jobs")


def test_phase_40_is_idempotent(tmp_path: Path):
    db = _db(tmp_path)
    migrate(db)
    migrations.migrate_to_phase_40(db)  # must not raise on a column that already exists
    assert "grp_seniority" in _columns(db, "jobs")


# ── Phase 41: jobs.admin_hidden ─────────────────────────────────────────────
# The admin-only Hidden state (ADR 0032): removes a Role from the public board
# without closing or deleting it. This only checks the migration adds the
# column and leaves existing rows visible; the read-path filtering lives in
# tests/test_job_read.py.

def test_phase_41_adds_the_column(tmp_path: Path):
    db = _db(tmp_path)
    migrate(db)
    assert "admin_hidden" in _columns(db, "jobs")


def test_phase_41_is_idempotent(tmp_path: Path):
    db = _db(tmp_path)
    migrate(db)
    migrations.migrate_to_phase_41(db)  # must not raise on a column that already exists
    assert "admin_hidden" in _columns(db, "jobs")


def test_phase_41_defaults_existing_rows_to_visible(tmp_path: Path):
    """A Role that pre-dates the column must not vanish from the board — the
    ADD COLUMN default is 0 (not hidden), and it applies to every existing row."""
    db = _db(tmp_path)
    migrate(db)
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "INSERT INTO jobs (source, source_id, company, company_slug, url,"
            " dedup_hash, title, fetched_at, is_active)"
            " VALUES ('workday', 'j1', 'X', 'x', 'https://e.test', 'h', 'T',"
            " '2026-06-01T00:00:00+00:00', 1)"
        )
        conn.commit()
        # Re-running the phase on a DB that already has rows must leave them visible.
        migrations.migrate_to_phase_41(db)
        val = conn.execute("SELECT admin_hidden FROM jobs WHERE source_id = 'j1'").fetchone()[0]
        assert val == 0
    finally:
        conn.close()
