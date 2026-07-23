"""
Tests for hk_jobs/posts/ghost_check.py.

_call_deepseek is monkeypatched at the ghost_check module's import site — no
real DeepSeek call is made.
"""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from hk_jobs.posts import ghost_check
from hk_jobs.posts.ghost_check import (
    GhostCheckAuthError,
    find_candidates,
    run_ghost_check,
)
from hk_jobs.schema import Job
from hk_jobs.storage import JobStore


@pytest.fixture
def db(tmp_path: Path) -> str:
    return str(tmp_path / "test.db")


def _sm_job(source_id="sm-1", title="Senior Credit Risk Manager", desc="") -> Job:
    return Job(
        source="linkedin_posts", source_id=source_id,
        company=f"Confidential via Recruiter ({source_id})",
        company_slug=f"confidential-recruiter-{source_id}",
        url="https://linkedin.com/posts/1", title=title,
        description_clean=desc, locations=["Hong Kong"],
        fetched_at=datetime.now(UTC), posted_at=datetime.now(UTC),
        source_tier="social",
    )


def _board_job(
    source_id="board-1", title="Senior Credit Risk Manager", company="HSBC",
    source="workday", source_tier="mainstream", desc="",
) -> Job:
    return Job(
        source=source, source_id=source_id, company=company,
        company_slug=company.lower().replace(" ", "-"),
        url="https://example.com/job", title=title,
        description_clean=desc, locations=["Hong Kong"],
        fetched_at=datetime.now(UTC), posted_at=datetime.now(UTC),
        source_tier=source_tier,
    )


def test_find_candidates_matches_similar_title_same_seniority(db):
    with JobStore(db) as store:
        store.upsert_many([
            _sm_job("sm-1", "Senior Credit Risk Manager"),
            _board_job("board-1", "Senior Credit Risk Manager", company="HSBC"),
        ])

    candidates = find_candidates(db)
    assert "sm-1" in candidates
    assert candidates["sm-1"][0][0]["source_id"] == "board-1"


def test_find_candidates_excludes_different_seniority(db):
    with JobStore(db) as store:
        store.upsert_many([
            _sm_job("sm-1", "Senior Credit Risk Manager"),
            _board_job("board-1", "Junior Credit Risk Manager", company="HSBC"),
        ])

    candidates = find_candidates(db)
    assert "sm-1" not in candidates


def test_find_candidates_excludes_unrelated_title(db):
    with JobStore(db) as store:
        store.upsert_many([
            _sm_job("sm-1", "Senior Credit Risk Manager"),
            _board_job("board-1", "Junior Marketing Executive", company="HSBC"),
        ])

    candidates = find_candidates(db)
    assert "sm-1" not in candidates


def test_run_ghost_check_flags_confirmed_match(db, monkeypatch):
    with JobStore(db) as store:
        store.upsert_many([
            _sm_job("sm-1", "Senior Credit Risk Manager"),
            _board_job("board-1", "Senior Credit Risk Manager", company="HSBC"),
        ])

    monkeypatch.setattr(
        ghost_check, "_call_deepseek",
        lambda *a, **k: json.dumps({"match_index": 0, "confidence": 0.9}),
    )

    summary = run_ghost_check(db, api_key="fake-key")
    assert summary.checked == 1
    assert summary.with_candidates == 1
    assert summary.ai_calls == 1
    assert summary.matched == 1

    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT board_signals FROM jobs WHERE source_id = 'sm-1'"
    ).fetchone()
    conn.close()
    signals = json.loads(row[0])
    assert signals["not_a_ghost_job"] is True


def test_run_ghost_check_skips_low_confidence(db, monkeypatch):
    with JobStore(db) as store:
        store.upsert_many([
            _sm_job("sm-1", "Senior Credit Risk Manager"),
            _board_job("board-1", "Senior Credit Risk Manager", company="HSBC"),
        ])

    monkeypatch.setattr(
        ghost_check, "_call_deepseek",
        lambda *a, **k: json.dumps({"match_index": 0, "confidence": 0.2}),
    )

    summary = run_ghost_check(db, api_key="fake-key")
    assert summary.matched == 0

    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT board_signals FROM jobs WHERE source_id = 'sm-1'"
    ).fetchone()
    conn.close()
    signals = json.loads(row[0])
    assert "not_a_ghost_job" not in signals


def test_run_ghost_check_skips_null_match(db, monkeypatch):
    with JobStore(db) as store:
        store.upsert_many([
            _sm_job("sm-1", "Senior Credit Risk Manager"),
            _board_job("board-1", "Senior Credit Risk Manager", company="HSBC"),
        ])

    monkeypatch.setattr(
        ghost_check, "_call_deepseek",
        lambda *a, **k: json.dumps({"match_index": None, "confidence": 0.95}),
    )

    summary = run_ghost_check(db, api_key="fake-key")
    assert summary.ai_calls == 1
    assert summary.matched == 0


def test_run_ghost_check_no_candidates_makes_no_ai_call(db, monkeypatch):
    with JobStore(db) as store:
        store.upsert_many([_sm_job("sm-1", "Senior Credit Risk Manager")])

    called = []
    monkeypatch.setattr(
        ghost_check, "_call_deepseek",
        lambda *a, **k: called.append(1) or json.dumps({"match_index": None, "confidence": 0.0}),
    )

    summary = run_ghost_check(db, api_key="fake-key")
    assert summary.ai_calls == 0
    assert summary.with_candidates == 0
    assert not called


def test_run_ghost_check_requires_api_key(db, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(GhostCheckAuthError):
        run_ghost_check(db, api_key=None)


def test_run_ghost_check_never_persists_matched_job_identity(db, monkeypatch):
    """
    board_signals is served to the client verbatim -- the matched board
    job's source/source_id/company/title must never end up in it, only the
    boolean flag, or a confirmed match would de-anonymize a confidential post.
    """
    with JobStore(db) as store:
        store.upsert_many([
            _sm_job("sm-1", "Senior Credit Risk Manager"),
            _board_job("board-1", "Senior Credit Risk Manager", company="HSBC"),
        ])

    monkeypatch.setattr(
        ghost_check, "_call_deepseek",
        lambda *a, **k: json.dumps({"match_index": 0, "confidence": 0.9}),
    )
    run_ghost_check(db, api_key="fake-key")

    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT board_signals FROM jobs WHERE source_id = 'sm-1'"
    ).fetchone()
    conn.close()
    signals = json.loads(row[0])
    assert set(signals.keys()) == {"not_a_ghost_job"}
    assert "HSBC" not in row[0]
    assert "board-1" not in row[0]
