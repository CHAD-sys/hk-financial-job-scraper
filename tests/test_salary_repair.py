"""Tests for the deterministic salary repairs (hk_jobs.salary_repair).

These write to the live catalogue via the `repair` Daily Run profile, so the two
properties that make that safe — idempotent, and down-only — are tested directly rather
than assumed.
"""
import sqlite3

import pytest

from hk_jobs.salary_clamp import INTERNSHIP_MAX_MONTHLY_HKD
from hk_jobs.salary_repair import repair_internship_salaries


def _db(tmp_path, rows):
    """A minimal jobs+job_enrichments pair. rows: (title, seniority, mn, mx, active)."""
    path = tmp_path / "jobs.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE jobs (
            source TEXT, source_id TEXT, title TEXT,
            is_active INTEGER DEFAULT 1, is_primary INTEGER DEFAULT 1
        );
        CREATE TABLE job_enrichments (
            source TEXT, source_id TEXT, seniority TEXT,
            salary_estimated_min INTEGER, salary_estimated_max INTEGER
        );
        """
    )
    for i, (title, seniority, mn, mx, active) in enumerate(rows):
        conn.execute(
            "INSERT INTO jobs VALUES (?,?,?,?,1)", ("linkedin", str(i), title, active)
        )
        conn.execute(
            "INSERT INTO job_enrichments VALUES (?,?,?,?,?)",
            ("linkedin", str(i), seniority, mn, mx),
        )
    conn.commit()
    conn.close()
    return str(path)


def _stored(path):
    conn = sqlite3.connect(path)
    out = conn.execute(
        "SELECT salary_estimated_min, salary_estimated_max FROM job_enrichments"
        " ORDER BY source_id"
    ).fetchall()
    conn.close()
    return out


def test_dry_run_reports_without_writing(tmp_path):
    path = _db(tmp_path, [("Summer Analyst 2027", "junior", 41_500, 83_500, 1)])
    summary = repair_internship_salaries(path)
    assert summary.repaired == 1
    assert _stored(path) == [(41_500, 83_500)], "dry run must not write"


def test_apply_lowers_the_internship_to_the_cap(tmp_path):
    path = _db(tmp_path, [("Summer Analyst 2027", "junior", 41_500, 83_500, 1)])
    repair_internship_salaries(path, dry_run=False)
    (mn, mx), = _stored(path)
    assert mx == INTERNSHIP_MAX_MONTHLY_HKD
    assert mn < mx, "must never store a flat point"


def test_a_second_run_changes_nothing(tmp_path):
    # Idempotence: this runs on demand against a database it does not own.
    path = _db(tmp_path, [("Global Banking Intern Hong Kong 2027", "junior", 41_500, 83_500, 1)])
    repair_internship_salaries(path, dry_run=False)
    after_first = _stored(path)
    second = repair_internship_salaries(path, dry_run=False)
    assert second.repaired == 0
    assert _stored(path) == after_first


def test_a_full_time_role_is_never_touched(tmp_path):
    path = _db(tmp_path, [("Director, Internal Audit", "lead", 90_000, 160_000, 1)])
    summary = repair_internship_salaries(path, dry_run=False)
    assert summary.matched == 0
    assert _stored(path) == [(90_000, 160_000)]


def test_an_internship_already_under_the_cap_is_left_alone(tmp_path):
    # Down-only: the repair is a ceiling, never a correction toward some target.
    path = _db(tmp_path, [("Summer Intern", "junior", 8_000, 12_000, 1)])
    summary = repair_internship_salaries(path, dry_run=False)
    assert summary.matched == 1 and summary.repaired == 0
    assert _stored(path) == [(8_000, 12_000)]


def test_only_the_live_board_is_repaired_by_default(tmp_path):
    path = _db(tmp_path, [("Summer Analyst 2027", "junior", 41_500, 83_500, 0)])
    assert repair_internship_salaries(path, dry_run=False).repaired == 0
    assert repair_internship_salaries(
        path, dry_run=False, live_board_only=False
    ).repaired == 1


def test_a_match_that_is_not_junior_is_surfaced_for_review(tmp_path):
    # The signal that the title pattern has started catching full-time roles.
    path = _db(tmp_path, [("Trainee Desk Head", "lead", 90_000, 160_000, 1)])
    summary = repair_internship_salaries(path)
    assert summary.suspicious and "lead" in summary.suspicious[0]


@pytest.mark.parametrize("mx", [None, 15_000, 14_999])
def test_nothing_at_or_below_the_cap_is_rewritten(tmp_path, mx):
    path = _db(tmp_path, [("Summer Analyst", "junior", 10_000, mx, 1)])
    assert repair_internship_salaries(path, dry_run=False).repaired == 0


def test_a_compound_manager_slash_intern_listing_is_skipped_not_capped(tmp_path):
    """One listing advertising two roles. Real production row, found the night the cap
    shipped: "Weath Management Manager / Wealth Management Intern", stored as `mid`.
    The title matches the internship pattern, but capping it would be wrong for the
    Manager half — so two signals must agree, and this one is reported instead."""
    path = _db(tmp_path, [
        ("Weath Management Manager / Wealth Management Intern 财富管理實習生", "mid", 40_000, 60_000, 1),
    ])
    summary = repair_internship_salaries(path, dry_run=False)
    assert summary.matched == 1
    assert summary.repaired == 0, "an ambiguous compound title must never be written"
    assert summary.suspicious
    assert _stored(path) == [(40_000, 60_000)]
