"""
Resolving conflicting seniority across a cross-posted vacancy's copies.

WHY THIS EXISTS
----------------
Each copy of a cross-posted vacancy is enriched independently by DeepSeek,
and the model runs at temperature=0.2 (not 0) — so near-identical
description text across copies of the SAME real vacancy can genuinely
produce different seniority answers. Measured on the live board (2026-08):
14% of cross-posted vacancy clusters disagreed across their copies, and
roughly half of those had a PRIMARY copy — the only one a Seeker or the
seniority filter ever sees — that contradicted every sibling copy of the
identical job. A live example: an HSBC "Relationship Manager, China Team"
vacancy, same vacancy_id and apply_url, scraped from eightfold/linkedin/
indeed, came back mid/senior/senior/senior/mid across its five copies.

`JobStore.refresh_seniority_consensus` settles this the same way phase 22's
`refresh_signal_flags` settles grp_new/grp_urgent/grp_applicants: one
canonical value per cross-posted cluster, written to `jobs.grp_seniority`,
which `job_read.py` reads via COALESCE ahead of the primary row's own
(possibly outvoted) `job_enrichments.seniority`.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from hk_jobs.migrations import migrate
from hk_jobs.schema import Job
from hk_jobs.storage import JobStore, _seniority_consensus


def job(source: str, source_id: str, *, title: str = "Relationship Manager",
        slug: str = "hsbc-hk") -> Job:
    return Job(
        source=source, source_id=source_id, company=slug, company_slug=slug,
        url=f"https://example.com/{source}/{source_id}", title=title,
        locations=["Hong Kong"], fetched_at=datetime.now(UTC),
    )


def _set_seniority(db: str, source: str, source_id: str, seniority: str,
                    *, manually_edited: bool = False) -> None:
    conn = sqlite3.connect(db)
    with conn:
        conn.execute(
            "INSERT INTO job_enrichments (source, source_id, seniority, manually_edited_at)"
            " VALUES (?, ?, ?, ?)"
            " ON CONFLICT (source, source_id) DO UPDATE SET"
            "   seniority = excluded.seniority,"
            "   manually_edited_at = excluded.manually_edited_at",
            (source, source_id, seniority,
             datetime.now(UTC).isoformat() if manually_edited else None),
        )
    conn.close()


def _grp_seniority(db: str, source: str, source_id: str) -> str | None:
    conn = sqlite3.connect(db)
    try:
        row = conn.execute(
            "SELECT grp_seniority FROM jobs WHERE source = ? AND source_id = ?",
            (source, source_id),
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


@pytest.fixture()
def db(tmp_path: Path) -> str:
    path = str(tmp_path / "jobs.db")
    migrate(path)  # job_enrichments (phase 12) and grp_seniority (phase 40)
    return path


# ── The consensus function itself ───────────────────────────────────────────

def test_clear_majority_wins():
    assert _seniority_consensus(["mid", "senior", "senior", "senior", "mid"], "mid") == "senior"


def test_tie_keeps_the_primarys_own_value_when_it_is_among_the_tied():
    assert _seniority_consensus(["mid", "senior"], "mid") == "mid"
    assert _seniority_consensus(["mid", "senior"], "senior") == "senior"


def test_tie_falls_back_to_the_lowest_ranked_tied_value_when_primary_is_outside_it():
    # Not reachable from refresh_seniority_consensus (the primary's own value
    # is always one of the votes) but the function's contract must still be
    # correct and conservative if called with an inconsistent primary value.
    assert _seniority_consensus(["mid", "senior"], "lead") == "mid"


def test_three_way_tie_keeps_the_primary():
    assert _seniority_consensus(["junior", "mid", "senior"], "mid") == "mid"


# ── refresh_seniority_consensus, through JobStore ───────────────────────────

def test_a_real_disagreement_resolves_to_the_majority_on_the_primary_row(db: str):
    """The HSBC RM case: primary's own answer is outvoted 3-2 by its siblings."""
    with JobStore(db) as store:
        store.upsert_many([
            job("eightfold", "A", title="Relationship Manager, China Team"),
            job("eightfold", "B", title="Relationship Manager, China Team"),
            job("linkedin", "C", title="Relationship Manager, China Team"),
            job("linkedin", "D", title="Relationship Manager, China Team"),
            job("indeed", "E", title="Relationship Manager, China Team"),
        ])
    _set_seniority(db, "eightfold", "A", "mid")
    _set_seniority(db, "eightfold", "B", "senior")
    _set_seniority(db, "linkedin", "C", "senior")
    _set_seniority(db, "linkedin", "D", "senior")
    _set_seniority(db, "indeed", "E", "mid")

    with JobStore(db) as store:
        store.reconcile_cross_posted()
        primary_source, primary_id = next(
            (r["source"], r["source_id"])
            for r in store._conn.execute(
                "SELECT source, source_id FROM jobs WHERE is_active=1 AND is_primary=1"
            )
        )
        overridden = store.refresh_seniority_consensus()

    assert overridden == 1
    assert _grp_seniority(db, primary_source, primary_id) == "senior"


def test_an_already_consistent_cluster_is_left_alone(db: str):
    with JobStore(db) as store:
        store.upsert_many([
            job("eightfold", "A", title="Compliance Officer"),
            job("linkedin", "B", title="Compliance Officer"),
        ])
    _set_seniority(db, "eightfold", "A", "mid")
    _set_seniority(db, "linkedin", "B", "mid")

    with JobStore(db) as store:
        store.reconcile_cross_posted()
        overridden = store.refresh_seniority_consensus()

    assert overridden == 0
    assert _grp_seniority(db, "eightfold", "A") is None
    assert _grp_seniority(db, "linkedin", "B") is None


def test_a_singleton_job_is_never_touched(db: str):
    with JobStore(db) as store:
        store.upsert_many([job("eightfold", "SOLO", title="Unique Role")])
    _set_seniority(db, "eightfold", "SOLO", "senior")

    with JobStore(db) as store:
        store.reconcile_cross_posted()
        overridden = store.refresh_seniority_consensus()

    assert overridden == 0
    assert _grp_seniority(db, "eightfold", "SOLO") is None


def test_a_manually_corrected_primary_is_never_overridden(db: str):
    """
    Phase 33's rule, reapplied here: a human's deliberate correction is not a
    vote to be outnumbered by its own siblings. Three siblings say "senior";
    Ultimate Admin corrected the primary to "junior" by hand — that stays.
    """
    with JobStore(db) as store:
        store.upsert_many([
            job("eightfold", "A", title="Product Manager"),
            job("linkedin", "B", title="Product Manager"),
            job("linkedin", "C", title="Product Manager"),
        ])
    _set_seniority(db, "eightfold", "A", "junior", manually_edited=True)
    _set_seniority(db, "linkedin", "B", "senior")
    _set_seniority(db, "linkedin", "C", "senior")

    with JobStore(db) as store:
        store.reconcile_cross_posted()
        primary_source, primary_id = next(
            (r["source"], r["source_id"])
            for r in store._conn.execute(
                "SELECT source, source_id FROM jobs WHERE is_active=1 AND is_primary=1"
            )
        )
        overridden = store.refresh_seniority_consensus()

    assert primary_source == "eightfold" and primary_id == "A", (
        "test assumes eightfold wins the primary election — see sources.DISPLAY_ORDER"
    )
    assert overridden == 0
    assert _grp_seniority(db, "eightfold", "A") is None


def test_a_resolved_disagreement_clears_on_the_next_pass(db: str):
    """
    A stale sibling gets re-enriched to match the rest — the earlier
    override must not keep serving a run that no longer applies.
    """
    with JobStore(db) as store:
        store.upsert_many([
            job("eightfold", "A", title="Risk Manager"),
            job("linkedin", "B", title="Risk Manager"),
            job("linkedin", "C", title="Risk Manager"),
        ])
    _set_seniority(db, "eightfold", "A", "mid")
    _set_seniority(db, "linkedin", "B", "senior")
    _set_seniority(db, "linkedin", "C", "senior")

    with JobStore(db) as store:
        store.reconcile_cross_posted()
        primary_source, primary_id = next(
            (r["source"], r["source_id"])
            for r in store._conn.execute(
                "SELECT source, source_id FROM jobs WHERE is_active=1 AND is_primary=1"
            )
        )
        store.refresh_seniority_consensus()

    assert _grp_seniority(db, primary_source, primary_id) == "senior"

    # The primary itself gets re-enriched to agree with its siblings.
    _set_seniority(db, primary_source, primary_id, "senior")
    with JobStore(db) as store:
        store.reconcile_cross_posted()

    assert _grp_seniority(db, primary_source, primary_id) is None


def test_idempotent(db: str):
    with JobStore(db) as store:
        store.upsert_many([
            job("eightfold", "A", title="Operations Lead"),
            job("linkedin", "B", title="Operations Lead"),
            job("linkedin", "C", title="Operations Lead"),
        ])
    _set_seniority(db, "eightfold", "A", "mid")
    _set_seniority(db, "linkedin", "B", "senior")
    _set_seniority(db, "linkedin", "C", "senior")

    with JobStore(db) as store:
        store.reconcile_cross_posted()
        first = store.refresh_seniority_consensus()
        second = store.refresh_seniority_consensus()

    assert first == second == 1
