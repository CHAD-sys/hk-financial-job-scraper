"""
Tests for hk_jobs/salary_corrections.py — admin corrections as calibration.

Two properties carry the weight here, and both are about restraint rather than
capability:

  1. A Role with nothing relevant must produce an EMPTY block, so its prompt is
     byte-identical to the one it produced before this feature existed. Anything
     else costs input tokens on every one of ~6,000 nightly calls to say nothing.
  2. Relevance is about the SHAPE of a role, not its rung. "Every mid-level job"
     is not a shape, and scoring it as one fills the block with unrelated work.

Uses the real schema (hk_jobs.migrations.migrate), not a stand-in: the query in
`load()` is what has to keep working against phase 36's actual table.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from hk_jobs import salary_corrections
from hk_jobs.migrations import migrate


@pytest.fixture()
def conn(tmp_path: Path) -> sqlite3.Connection:
    path = tmp_path / "jobs.db"
    migrate(str(path))
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    return c


def _add(
    conn: sqlite3.Connection,
    *,
    source_id: str = "W1",
    title: str = "Credit Analyst",
    company: str = "Industrial Bank",
    seniority: str | None = "mid",
    new_min: int | None = 42000,
    new_max: int | None = 68000,
    old_min: int | None = 35000,
    old_max: int | None = 60000,
    age_days: int = 0,
) -> None:
    conn.execute(
        """
        INSERT INTO admin_salary_corrections (
            source, source_id, title, company, seniority,
            old_min, old_max, new_min, new_max, seeker_id, corrected_at
        ) VALUES ('jobsdb', ?, ?, ?, ?, ?, ?, ?, ?, 'admin-1',
                  datetime('now', ?))
        """,
        (source_id, title, company, seniority, old_min, old_max, new_min, new_max,
         f"-{age_days} days"),
    )
    conn.commit()


# ── Loading ───────────────────────────────────────────────────────────────────

def test_load_returns_nothing_on_a_database_without_the_table(tmp_path: Path):
    """A pre-phase-36 database must estimate WITHOUT corrections, not crash the
    nightly run. The hint is an enhancement; the run is not."""
    bare = sqlite3.connect(tmp_path / "bare.db")
    assert salary_corrections.load(bare) == []


def test_load_reads_a_correction_back(conn):
    _add(conn)
    loaded = salary_corrections.load(conn)
    assert len(loaded) == 1
    assert (loaded[0].new_min, loaded[0].new_max) == (42000, 68000)


def test_only_the_latest_correction_per_role_is_kept(conn):
    """An admin who corrects the same posting twice changed their mind. The
    superseded figure must not go on being offered as evidence."""
    _add(conn, source_id="W1", new_max=68000, age_days=2)
    _add(conn, source_id="W1", new_max=55000, age_days=0)
    loaded = salary_corrections.load(conn)
    assert len(loaded) == 1
    assert loaded[0].new_max == 55000


def test_stale_corrections_drop_out(conn):
    """The table is append-only. Without a horizon it would grow into the prompt
    forever, and a judgement about 2024 pay is not evidence about today's."""
    _add(conn, age_days=800)
    assert salary_corrections.load(conn) == []


def test_a_correction_with_no_figures_is_not_evidence(conn):
    _add(conn, new_min=None, new_max=None)
    assert salary_corrections.load(conn) == []


# ── Relevance ─────────────────────────────────────────────────────────────────

def test_nothing_relevant_produces_an_empty_block(conn):
    _add(conn, title="Credit Analyst")
    block = salary_corrections.evidence_for(
        salary_corrections.load(conn), title="Marine Biologist",
    )
    assert block == ""


def test_no_corrections_at_all_produces_an_empty_block(conn):
    assert salary_corrections.evidence_for([], title="Credit Analyst") == ""


def test_a_similar_role_is_offered_as_evidence(conn):
    _add(conn, title="Credit Analyst", new_min=42000, new_max=68000)
    block = salary_corrections.evidence_for(
        salary_corrections.load(conn), title="Senior Credit Analyst, Corporate Banking",
    )
    assert "HUMAN CORRECTIONS" in block
    assert "HK$42,000-68,000" in block


def test_the_superseded_figure_is_shown_beside_the_corrected_one(conn):
    """"We said 35-60k and a human said 42-68k" tells the model the direction and
    size of the error. The corrected figure alone does not."""
    _add(conn, title="Credit Analyst", old_min=35000, old_max=60000)
    block = salary_corrections.evidence_for(
        salary_corrections.load(conn), title="Credit Analyst",
    )
    assert "estimator had said HK$35,000-60,000" in block


def test_seniority_alone_does_not_make_a_role_relevant(conn):
    """Sharing a rung is not sharing a shape. Scoring it as one would put every
    mid-level correction in front of every mid-level Role."""
    _add(conn, title="Compliance Officer", seniority="mid")
    block = salary_corrections.evidence_for(
        salary_corrections.load(conn), title="Equity Research Analyst", seniority="mid",
    )
    assert block == ""


def test_a_matching_seniority_breaks_the_tie_between_similar_titles(conn):
    _add(conn, source_id="A", title="Credit Analyst", seniority="lead", new_max=90000)
    _add(conn, source_id="B", title="Credit Analyst", seniority="mid", new_max=68000)
    block = salary_corrections.evidence_for(
        salary_corrections.load(conn), title="Credit Analyst", seniority="mid", limit=1,
    )
    assert "68,000" in block
    assert "90,000" not in block


def test_generic_title_words_do_not_create_relevance(conn):
    """"Senior" and "Manager" appear in half the catalogue. Matching on them
    would make almost everything relevant to almost everything."""
    _add(conn, title="Senior Manager, Actuarial Reserving")
    block = salary_corrections.evidence_for(
        salary_corrections.load(conn), title="Senior Manager, Trade Finance Operations",
    )
    assert block == ""


def test_the_block_is_capped(conn):
    for n in range(12):
        _add(conn, source_id=f"W{n}", title="Credit Analyst", new_max=60000 + n)
    block = salary_corrections.evidence_for(
        salary_corrections.load(conn), title="Credit Analyst", limit=3,
    )
    assert block.count("\n- ") == 3
