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
    """A minimal jobs+job_enrichments pair.

    rows: (title, seniority, mn, mx, active) — or the same with three more fields
    (confidence, disclosed_min, disclosed_max) for the disclosed-figure cases.
    """
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
            salary_estimated_min INTEGER, salary_estimated_max INTEGER,
            salary_estimated_confidence TEXT,
            salary_hkd_min INTEGER, salary_hkd_max INTEGER,
            manually_edited_at TEXT
        );
        """
    )
    for i, row in enumerate(rows):
        title, seniority, mn, mx, active = row[:5]
        conf, hkd_mn, hkd_mx, pinned = (list(row[5:]) + [None, None, None, None])[:4]
        conn.execute(
            "INSERT INTO jobs VALUES (?,?,?,?,1)", ("linkedin", str(i), title, active)
        )
        conn.execute(
            "INSERT INTO job_enrichments VALUES (?,?,?,?,?,?,?,?,?)",
            ("linkedin", str(i), seniority, mn, mx, conf, hkd_mn, hkd_mx, pinned),
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


def test_a_disclosed_salary_is_never_overwritten(tmp_path):
    """The employer's own figure outranks any estimate, including this repair's.

    Found live on 2026-08-19: "Business Analyst/ Junior/Trainee Analyst" matched the
    title pattern and was stored as junior, so the repair rewrote its estimate to the
    internship cap — even though the posting DISCLOSED HK$25,000-32,000 and the
    enrichment recorded confidence "high", meaning the figure was read out of the text
    rather than guessed. Nine such rows had already been overwritten in production.
    """
    path = _db(
        tmp_path,
        [("Business Analyst / Junior / Trainee Analyst", "junior", 25_000, 32_000, 1,
          "high", 25_000, 32_000)],
    )
    summary = repair_internship_salaries(path, dry_run=False)

    assert summary.repaired == 0, "a disclosed figure must not be rewritten"
    assert _stored(path) == [(25_000, 32_000)]
    assert summary.disclosed, "the skip must be reported, not silent"


def test_a_disclosed_figure_is_skipped_even_without_high_confidence(tmp_path):
    """salary_hkd_* being present is itself the signal — it is an extracted figure."""
    path = _db(
        tmp_path,
        [("Management Trainee Programme", "junior", 30_000, 45_000, 1,
          "medium", 30_000, 45_000)],
    )
    summary = repair_internship_salaries(path, dry_run=False)

    assert summary.repaired == 0
    assert _stored(path) == [(30_000, 45_000)]


def test_a_high_confidence_estimate_without_a_disclosed_figure_is_still_skipped(tmp_path):
    """confidence="high" alone means the number came from the text. Leave it."""
    path = _db(
        tmp_path,
        [("Summer Internship Programme", "junior", 20_000, 40_000, 1, "high", None, None)],
    )
    summary = repair_internship_salaries(path, dry_run=False)

    assert summary.repaired == 0
    assert _stored(path) == [(20_000, 40_000)]


def test_an_ordinary_estimated_internship_is_still_capped(tmp_path):
    """The guard must not disarm the repair for rows that were genuinely estimated."""
    path = _db(
        tmp_path,
        [("Summer Analyst 2027", "junior", 41_500, 83_500, 1, "medium", None, None)],
    )
    summary = repair_internship_salaries(path, dry_run=False)

    assert summary.repaired == 1
    assert _stored(path) == [(7_500, INTERNSHIP_MAX_MONTHLY_HKD)]


# ── the title-grade ceiling, re-applied to published rows ─────────────────────
from hk_jobs.salary_repair import repair_grade_ceiling_salaries  # noqa: E402


def _db2(tmp_path, rows):
    """rows: (title, slug, tier, seniority, mn, mx, conf, hkd_max)."""
    path = tmp_path / "jobs.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE jobs (
            source TEXT, source_id TEXT, title TEXT, company_slug TEXT,
            is_active INTEGER DEFAULT 1, is_primary INTEGER DEFAULT 1
        );
        CREATE TABLE job_enrichments (
            source TEXT, source_id TEXT, salary_tier TEXT, seniority TEXT,
            salary_estimated_min INTEGER, salary_estimated_max INTEGER,
            salary_estimated_confidence TEXT, salary_hkd_max INTEGER,
            manually_edited_at TEXT
        );
        """
    )
    for i, row in enumerate(rows):
        title, slug, tier, sen, mn, mx, conf, hkd = row[:8]
        pinned = row[8] if len(row) > 8 else None
        conn.execute("INSERT INTO jobs VALUES (?,?,?,?,1,1)", ("linkedin", str(i), title, slug))
        conn.execute("INSERT INTO job_enrichments VALUES (?,?,?,?,?,?,?,?,?)",
                     ("linkedin", str(i), tier, sen, mn, mx, conf, hkd, pinned))
    conn.commit(); conn.close()
    return str(path)


def _maxes(path):
    conn = sqlite3.connect(path)
    out = [r[0] for r in conn.execute(
        "SELECT salary_estimated_max FROM job_enrichments ORDER BY source_id")]
    conn.close()
    return out


def test_a_support_function_row_above_its_grade_ceiling_is_lowered(tmp_path):
    path = _db2(tmp_path, [
        ("Senior Manager, Credit Risk", "dbs-hk", "middle_office", "senior",
         75_000, 100_000, "medium", None)])
    summary = repair_grade_ceiling_salaries(path, dry_run=False)
    assert summary.repaired == 1
    assert _maxes(path) == [70_000]


def test_a_front_office_row_is_exempt(tmp_path):
    """Mirrors clamp_salary's own exemption — the two must never disagree."""
    path = _db2(tmp_path, [
        ("Global Banking & Markets, SPG Basis Trading, Vice President", "goldman-sachs",
         "front_office", "senior", 105_000, 163_500, "medium", None)])
    summary = repair_grade_ceiling_salaries(path, dry_run=False)
    assert summary.repaired == 0
    assert _maxes(path) == [163_500]


def test_a_disclosed_figure_is_never_overwritten_here_either(tmp_path):
    path = _db2(tmp_path, [
        ("Vice President, Operations", "citibank-hk", "middle_office", "senior",
         90_000, 120_000, "high", 120_000)])
    summary = repair_grade_ceiling_salaries(path, dry_run=False)
    assert summary.repaired == 0
    assert summary.disclosed
    assert _maxes(path) == [120_000]


def test_a_row_already_under_its_ceiling_is_untouched(tmp_path):
    path = _db2(tmp_path, [
        ("Vice President, Operations", "citibank-hk", "middle_office", "senior",
         40_000, 60_000, "medium", None)])
    assert repair_grade_ceiling_salaries(path, dry_run=False).repaired == 0
    assert _maxes(path) == [60_000]


def test_grade_ceiling_repair_is_idempotent(tmp_path):
    path = _db2(tmp_path, [
        ("Senior Manager, Credit Risk", "dbs-hk", "middle_office", "senior",
         75_000, 100_000, "medium", None)])
    repair_grade_ceiling_salaries(path, dry_run=False)
    first = _maxes(path)
    assert repair_grade_ceiling_salaries(path, dry_run=False).repaired == 0
    assert _maxes(path) == first


def test_grade_ceiling_repair_is_down_only(tmp_path):
    """An unrecognised employer has no ceiling; nothing may be raised."""
    path = _db2(tmp_path, [
        ("Vice President, Trading", "some-boutique", "middle_office", "senior",
         20_000, 30_000, "medium", None)])
    assert repair_grade_ceiling_salaries(path, dry_run=False).repaired == 0
    assert _maxes(path) == [30_000]


# ── an Ultimate Admin's correction outranks every repair ──────────────────────
# `manually_edited_at` (migrations phase 33) is what makes a hand-correction stick.
# enrichment.py and salary_audit.py already exclude a pinned row unconditionally.
# These repairs did not, so a pinned salary was re-clamped every night and only
# survived because pipeline_publish replays the admin_edits ledger afterwards —
# the pin held by being undone downstream, not by being respected here.

PINNED = "2026-08-19T12:00:00+00:00"


def test_internship_repair_skips_a_manually_pinned_row(tmp_path):
    path = _db(tmp_path, [
        ("Summer Analyst 2027", "junior", 41_500, 83_500, 1, "medium", None, None, PINNED)])
    summary = repair_internship_salaries(path, dry_run=False)
    assert summary.repaired == 0
    assert _stored(path) == [(41_500, 83_500)]
    assert summary.pinned, "the skip must be reported, not silent"


def test_grade_ceiling_repair_skips_a_manually_pinned_row(tmp_path):
    path = _db2(tmp_path, [
        ("Senior Manager, Credit Risk", "dbs-hk", "middle_office", "senior",
         75_000, 100_000, "medium", None, PINNED)])
    summary = repair_grade_ceiling_salaries(path, dry_run=False)
    assert summary.repaired == 0
    assert _maxes(path) == [100_000]
    assert summary.pinned


def test_an_unpinned_row_is_still_repaired(tmp_path):
    """The guard must not disarm the repairs for ordinary rows."""
    path = _db2(tmp_path, [
        ("Senior Manager, Credit Risk", "dbs-hk", "middle_office", "senior",
         75_000, 100_000, "medium", None, None)])
    assert repair_grade_ceiling_salaries(path, dry_run=False).repaired == 1
    assert _maxes(path) == [70_000]
