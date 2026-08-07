"""
Tests for webapp/backend/submissions.py — the recruiter-submission queue shared
by scripts/review_submissions.py and Admin Mode's /api/admin/submissions.

approve_submission() is tested against the REAL jobs table (hk_jobs.storage.
ensure_schema), not tests/support.py's reduced read-path stand-in — that stand-in
is missing columns (company_slug, description_raw, extraction_confidence) this
write path needs, on purpose (support.py: "exactly the columns the read path
touches"). Crossing into hk_jobs here is fine: this is the test suite, which
runs from the repo root, not the deployed server (see submissions.py's
module docstring for why the server itself never does this).
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

from .support import BACKEND

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import submissions as subs  # noqa: E402


def _row(**over) -> dict:
    base = {
        "contact_name": "Jane Recruiter",
        "contact_email": "jane@example.com",
        "company": "Acme Capital",
        "title": "Credit Analyst",
        "location": "Central, Hong Kong",
        "employment_type": "Full-time",
        "salary_range": "",
        "description": "Analyse credit risk.",
        "apply_url": "https://example.test/apply",
        "received_at": "2026-08-05T09:00:00+00:00",
        "status": "pending",
    }
    base.update(over)
    return base


# ── queue file ──────────────────────────────────────────────────────────────


def test_load_queue_missing_file_returns_empty(tmp_path: Path) -> None:
    assert subs.load_queue(tmp_path / "nope.jsonl") == []


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "submitted_roles.jsonl"
    rows = [_row(title="Analyst"), _row(title="Associate")]
    subs.save_queue(path, rows)
    assert subs.load_queue(path) == rows


def test_save_queue_is_atomic_no_tmp_file_left_behind(tmp_path: Path) -> None:
    path = tmp_path / "submitted_roles.jsonl"
    subs.save_queue(path, [_row()])
    assert not path.with_suffix(".jsonl.tmp").exists()
    assert path.exists()


# ── stable ids ────────────────────────────────────────────────────────────────


def test_source_id_for_is_stable_for_identical_content() -> None:
    a = subs.source_id_for(_row())
    b = subs.source_id_for(_row())
    assert a == b


def test_source_id_for_differs_when_content_differs() -> None:
    a = subs.source_id_for(_row(title="Analyst"))
    b = subs.source_id_for(_row(title="Associate"))
    assert a != b


def test_find_by_source_id_locates_the_right_row() -> None:
    rows = [_row(title="Analyst"), _row(title="Associate"), _row(title="VP")]
    target = subs.source_id_for(rows[1])
    assert subs.find_by_source_id(rows, target) == 1


def test_find_by_source_id_returns_none_when_absent() -> None:
    rows = [_row(title="Analyst")]
    assert subs.find_by_source_id(rows, "not-a-real-id") is None


# ── approval writes into jobs.db ──────────────────────────────────────────────


@pytest.fixture()
def real_jobs_db(tmp_path: Path) -> Path:
    from hk_jobs.storage import ensure_schema

    path = tmp_path / "jobs.db"
    ensure_schema(str(path))
    return path


def test_approve_submission_inserts_a_visible_active_row(real_jobs_db: Path) -> None:
    row = _row()
    sid = subs.approve_submission(real_jobs_db, row)

    conn = sqlite3.connect(real_jobs_db)
    conn.row_factory = sqlite3.Row
    inserted = conn.execute(
        "SELECT * FROM jobs WHERE source = ? AND source_id = ?", (subs.SOURCE, sid)
    ).fetchone()
    conn.close()

    assert inserted is not None
    assert inserted["company"] == "Acme Capital"
    assert inserted["title"] == "Credit Analyst"
    assert inserted["is_active"] == 1
    assert inserted["is_primary"] == 1
    assert inserted["source_tier"] == "boutique"
    assert inserted["dedup_hash"]  # NOT NULL, no default — must be populated


def test_approving_the_same_submission_twice_does_not_raise(real_jobs_db: Path) -> None:
    row = _row()
    first = subs.approve_submission(real_jobs_db, row)
    second = subs.approve_submission(real_jobs_db, row)  # re-approval, e.g. a double click
    assert first == second

    conn = sqlite3.connect(real_jobs_db)
    count = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE source = ? AND source_id = ?", (subs.SOURCE, first)
    ).fetchone()[0]
    conn.close()
    assert count == 1


# ── status stamping ────────────────────────────────────────────────────────────


def test_mark_approved_does_not_mutate_the_input() -> None:
    row = _row()
    updated = subs.mark_approved(row, "abc123")
    assert row["status"] == "pending"
    assert updated["status"] == "approved"
    assert updated["source_id"] == "abc123"
    assert "decided_at" in updated


def test_mark_rejected_records_a_reason_without_mutating_the_input() -> None:
    row = _row()
    updated = subs.mark_rejected(row, reason="duplicate")
    assert row["status"] == "pending"
    assert updated["status"] == "rejected"
    assert updated["reason"] == "duplicate"


def test_mark_rejected_omits_reason_key_when_none_given() -> None:
    updated = subs.mark_rejected(_row())
    assert "reason" not in updated
