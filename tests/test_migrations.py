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
