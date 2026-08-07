"""
Tests for webapp/backend/job_edit.py — Ultimate Admin's direct write onto a
job's row and its enrichment.

Uses the REAL schema (hk_jobs.migrations.migrate), not a hand-rolled stand-in:
this module writes into job_enrichments and the phase-33 admin_edits table,
and the point of half these tests is that manually_edited_at actually lands
where hk_jobs/enrichment.py and hk_jobs/salary_audit.py look for it.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

from .support import BACKEND

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import job_edit  # noqa: E402

from hk_jobs.migrations import migrate  # noqa: E402


@pytest.fixture()
def db(tmp_path: Path) -> Path:
    path = tmp_path / "jobs.db"
    migrate(str(path))
    return path


@pytest.fixture()
def conn(db: Path) -> sqlite3.Connection:
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    c.execute(
        """
        INSERT INTO jobs (
            source, source_id, company, company_slug, url, dedup_hash, title,
            description_clean, locations, employment_type, apply_url,
            fetched_at, is_active, seniority, remote_type
        ) VALUES (
            'workday', 'W1', 'HSBC', 'hsbc', 'https://x.test/w1', 'abc123', 'Credit Analyst',
            'Analyse credit risk.', '["Hong Kong"]', 'Full-time', 'https://x.test/apply',
            '2026-08-06T00:00:00+00:00', 1, 'junior', 'onsite'
        )
        """
    )
    c.commit()
    return c


# ── get_job_for_edit ───────────────────────────────────────────────────────────


def test_get_job_for_edit_returns_the_row(conn):
    job = job_edit.get_job_for_edit(conn, "workday", "W1")
    assert job["title"] == "Credit Analyst"
    assert job["company"] == "HSBC"


def test_get_job_for_edit_raises_for_unknown_job(conn):
    with pytest.raises(job_edit.JobNotFound):
        job_edit.get_job_for_edit(conn, "workday", "not-a-real-id")


def test_job_and_enrichment_seniority_are_kept_separate(conn):
    """jobs.seniority and job_enrichments.seniority are different columns —
    the row's own 'junior' must not be shadowed once an enrichment exists."""
    conn.execute(
        "INSERT INTO job_enrichments (source, source_id, seniority) VALUES (?, ?, ?)",
        ("workday", "W1", "senior"),
    )
    conn.commit()

    job = job_edit.get_job_for_edit(conn, "workday", "W1")
    assert job["seniority"] == "junior"       # jobs.seniority, untouched
    assert job["e_seniority"] == "senior"      # job_enrichments.seniority


def test_get_job_for_edit_works_with_no_enrichment_row_yet(conn):
    job = job_edit.get_job_for_edit(conn, "workday", "W1")
    assert job["e_seniority"] is None
    assert job["salary_estimated_min"] is None
    assert job["manually_edited_at"] is None


def test_get_job_for_edit_self_heals_an_older_deployment_schema(conn):
    """The backend-only Railway upload must work against a pre-phase-33 volume."""
    conn.execute("DROP TABLE admin_edits")
    conn.execute("ALTER TABLE job_enrichments DROP COLUMN manually_edited_at")
    conn.commit()

    job = job_edit.get_job_for_edit(conn, "workday", "W1")

    assert job["title"] == "Credit Analyst"
    assert "manually_edited_at" in {
        row[1] for row in conn.execute("PRAGMA table_info(job_enrichments)")
    }
    assert conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='admin_edits'"
    ).fetchone()


# ── apply_edit: validation ────────────────────────────────────────────────────


def test_unknown_job_field_is_refused(conn):
    with pytest.raises(ValueError, match="not an editable field"):
        job_edit.apply_edit(conn, "workday", "W1", "admin-1", job_changes={"source_id": "X"})


def test_unknown_enrichment_field_is_refused(conn):
    with pytest.raises(ValueError, match="not an editable field"):
        job_edit.apply_edit(
            conn, "workday", "W1", "admin-1", enrichment_changes={"enriched_at": "now"}
        )


def test_apply_edit_raises_for_unknown_job(conn):
    with pytest.raises(job_edit.JobNotFound):
        job_edit.apply_edit(conn, "workday", "nope", "admin-1", job_changes={"title": "X"})


# ── apply_edit: writing `jobs` fields ─────────────────────────────────────────


def test_edit_a_job_field_updates_the_row(conn):
    updated = job_edit.apply_edit(
        conn, "workday", "W1", "admin-1", job_changes={"title": "Senior Credit Analyst"}
    )
    assert updated["title"] == "Senior Credit Analyst"
    assert conn.execute(
        "SELECT title FROM jobs WHERE source='workday' AND source_id='W1'"
    ).fetchone()[0] == "Senior Credit Analyst"


def test_editing_a_job_field_never_touches_manually_edited_at(conn):
    job_edit.apply_edit(conn, "workday", "W1", "admin-1", job_changes={"title": "New Title"})
    row = conn.execute(
        "SELECT manually_edited_at FROM job_enrichments WHERE source='workday' AND source_id='W1'"
    ).fetchone()
    assert row is None  # no enrichment field touched -> no enrichment row created at all


def test_locations_json_field_round_trips_a_list(conn):
    job_edit.apply_edit(
        conn, "workday", "W1", "admin-1",
        job_changes={"locations": ["Central", "Admiralty"]},
    )
    raw = conn.execute(
        "SELECT locations FROM jobs WHERE source='workday' AND source_id='W1'"
    ).fetchone()[0]
    assert json.loads(raw) == ["Central", "Admiralty"]


def test_is_active_bool_round_trips_to_integer(conn):
    job_edit.apply_edit(conn, "workday", "W1", "admin-1", job_changes={"is_active": False})
    assert conn.execute(
        "SELECT is_active FROM jobs WHERE source='workday' AND source_id='W1'"
    ).fetchone()[0] == 0


# ── apply_edit: writing `job_enrichments` fields ─────────────────────────────


def test_edit_an_enrichment_field_with_no_existing_row_creates_one(conn):
    updated = job_edit.apply_edit(
        conn, "workday", "W1", "admin-1",
        enrichment_changes={"salary_estimated_min": 40000, "salary_estimated_max": 60000},
    )
    assert updated["salary_estimated_min"] == 40000
    assert updated["salary_estimated_max"] == 60000
    assert updated["manually_edited_at"] is not None


def test_edit_an_enrichment_field_on_an_existing_row_updates_only_that_field(conn):
    conn.execute(
        "INSERT INTO job_enrichments (source, source_id, salary_estimated_min, "
        "salary_estimated_max, job_category) VALUES ('workday', 'W1', 40000, 60000, 'Banking')"
    )
    conn.commit()

    updated = job_edit.apply_edit(
        conn, "workday", "W1", "admin-1", enrichment_changes={"salary_estimated_min": 55000}
    )
    assert updated["salary_estimated_min"] == 55000
    assert updated["salary_estimated_max"] == 60000  # untouched
    assert updated["job_category"] == "Banking"       # untouched


def test_editing_enrichment_sets_manually_edited_at(conn):
    job_edit.apply_edit(
        conn, "workday", "W1", "admin-1", enrichment_changes={"salary_estimated_max": 60000}
    )
    row = conn.execute(
        "SELECT manually_edited_at FROM job_enrichments WHERE source='workday' AND source_id='W1'"
    ).fetchone()
    assert row[0] is not None


def test_resending_the_same_value_writes_nothing_and_leaves_no_audit_row(conn):
    conn.execute(
        "INSERT INTO job_enrichments (source, source_id, salary_estimated_min) "
        "VALUES ('workday', 'W1', 40000)"
    )
    conn.commit()

    job_edit.apply_edit(
        conn, "workday", "W1", "admin-1", enrichment_changes={"salary_estimated_min": 40000}
    )

    row = conn.execute(
        "SELECT manually_edited_at FROM job_enrichments WHERE source='workday' AND source_id='W1'"
    ).fetchone()
    assert row[0] is None  # nothing actually changed -> no lock, no write
    count = conn.execute("SELECT COUNT(*) FROM admin_edits").fetchone()[0]
    assert count == 0


def test_a_no_op_enrichment_resend_does_not_lock_a_row_changed_elsewhere(conn):
    """
    A form that posts its whole state (title changed, salary untouched) must
    not accidentally freeze the untouched salary against future automation —
    manually_edited_at should only ever mean "a human touched THIS value."
    """
    conn.execute(
        "INSERT INTO job_enrichments (source, source_id, salary_estimated_min) "
        "VALUES ('workday', 'W1', 40000)"
    )
    conn.commit()

    job_edit.apply_edit(
        conn, "workday", "W1", "admin-1",
        job_changes={"title": "Updated Title"},
        enrichment_changes={"salary_estimated_min": 40000},  # unchanged
    )

    row = conn.execute(
        "SELECT manually_edited_at FROM job_enrichments WHERE source='workday' AND source_id='W1'"
    ).fetchone()
    assert row[0] is None


# ── apply_edit: audit trail ───────────────────────────────────────────────────


def test_edit_is_logged_to_admin_edits_with_old_and_new_values(conn):
    job_edit.apply_edit(
        conn, "workday", "W1", "admin-seeker-id", job_changes={"title": "New Title"}
    )
    row = conn.execute(
        "SELECT source, source_id, seeker_id, field, old_value, new_value "
        "FROM admin_edits"
    ).fetchone()
    assert tuple(row) == ("workday", "W1", "admin-seeker-id", "job.title",
                           "Credit Analyst", "New Title")


def test_enrichment_edit_is_logged_with_the_enrichment_prefix(conn):
    job_edit.apply_edit(
        conn, "workday", "W1", "admin-1", enrichment_changes={"salary_estimated_min": 40000}
    )
    field = conn.execute("SELECT field FROM admin_edits").fetchone()[0]
    assert field == "enrichment.salary_estimated_min"


def test_multiple_fields_in_one_call_produce_one_audit_row_each(conn):
    job_edit.apply_edit(
        conn, "workday", "W1", "admin-1",
        job_changes={"title": "New Title", "company": "New Co"},
    )
    fields = {r[0] for r in conn.execute("SELECT field FROM admin_edits")}
    assert fields == {"job.title", "job.company"}
