"""
ADR 0035 — the board shows at most BOARD_COMPANY_CAP Roles per employer,
newest first.

The board had drifted to ~3,250 Roles, more than the nightly DeepSeek run
enriches, so the freshest and most-viewed Roles sat on the board with no
salary figure. A handful of mega-posters (Bank of China ~300, HKEX ~220)
drove most of that volume. `board_visible_sql()` now caps every employer at
the same number; `job_read.BOARD_WHERE` and `enrichment._fetch_unenriched`
both read it, so browse and estimation shrink together.

This file pins the predicate at the SQL level, `jobs` aliased `j`, no web app.
"""

from __future__ import annotations

import sqlite3

from hk_jobs import board_visibility
from hk_jobs.board_visibility import BOARD_COMPANY_CAP, board_visible_sql

_SCHEMA = """
CREATE TABLE jobs (
    source TEXT, source_id TEXT, company TEXT, company_slug TEXT,
    title TEXT, is_active INTEGER DEFAULT 1, is_primary INTEGER DEFAULT 1,
    admin_hidden INTEGER DEFAULT 0, posted_at TEXT
);
"""


def _db(rows):
    """Rows: (source_id, company_slug, title, is_primary, admin_hidden, age).
    `age` is a SQLite datetime modifier relative to now (e.g. '-5 minutes').
    Ages are kept inside the 1-month window on purpose — this file tests the
    per-company cap, not the posting-age window (that has its own tests). Use
    minutes/hours so >60 Roles per employer still fit inside the month."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.executemany(
        "INSERT INTO jobs (source_id, company_slug, title, is_primary, "
        "admin_hidden, posted_at) VALUES (?, ?, ?, ?, ?, datetime('now', ?))",
        rows,
    )
    conn.commit()
    return conn


def _board_ids(conn, *, with_hidden=False):
    sql = f"SELECT source_id FROM jobs j WHERE {board_visible_sql(with_hidden=with_hidden)}"
    return {r["source_id"] for r in conn.execute(sql)}


def test_an_employer_over_the_cap_keeps_only_its_freshest():
    rows = [
        (f"boc{i:03d}", "bochk", f"Role {i}", 1, 0, f"-{i + 1} minutes")
        for i in range(BOARD_COMPANY_CAP + 4)
    ]
    conn = _db(rows)
    on_board = _board_ids(conn)
    assert len(on_board) == BOARD_COMPANY_CAP
    # boc000 is the newest (posted 1 minute ago); the 4 oldest fall off.
    assert on_board == {f"boc{i:03d}" for i in range(BOARD_COMPANY_CAP)}


def test_a_small_employer_is_untouched_by_the_cap():
    rows = [(f"tiny{i}", "tiny-boutique", f"Role {i}", 1, 0, f"-{i + 1} minutes") for i in range(3)]
    conn = _db(rows)
    assert _board_ids(conn) == {"tiny0", "tiny1", "tiny2"}


def test_the_cap_is_per_employer_not_global():
    rows = [
        (f"a{i:03d}", "employer-a", f"A {i}", 1, 0, f"-{i + 1} minutes")
        for i in range(BOARD_COMPANY_CAP + 3)
    ]
    rows += [
        (f"b{i:03d}", "employer-b", f"B {i}", 1, 0, f"-{i + 1} minutes")
        for i in range(BOARD_COMPANY_CAP + 3)
    ]
    conn = _db(rows)
    on_board = _board_ids(conn)
    assert sum(i.startswith("a") for i in on_board) == BOARD_COMPANY_CAP
    assert sum(i.startswith("b") for i in on_board) == BOARD_COMPANY_CAP


def test_a_capped_out_role_still_has_a_verifiable_recent_posting_date():
    """A Role dropped by the cap is fresh and open — it is off the *browse*
    board, not Closed. Nothing here sets is_active = 0."""
    rows = [
        (f"boc{i:03d}", "bochk", f"Role {i}", 1, 0, f"-{i + 1} minutes")
        for i in range(BOARD_COMPANY_CAP + 2)
    ]
    conn = _db(rows)
    dropped = {f"boc{i:03d}" for i in range(BOARD_COMPANY_CAP, BOARD_COMPANY_CAP + 2)}
    still_active = {
        r["source_id"] for r in conn.execute("SELECT source_id FROM jobs WHERE is_active = 1")
    }
    assert dropped <= still_active
    assert dropped.isdisjoint(_board_ids(conn))


def test_admin_hidden_roles_rank_in_only_under_with_hidden():
    rows = [
        (f"boc{i:03d}", "bochk", f"Role {i}", 1, 0, f"-{i + 30} minutes")
        for i in range(BOARD_COMPANY_CAP)
    ]
    # Two hidden Roles, both newer than every visible one.
    rows += [
        ("hidden-new-1", "bochk", "Hidden A", 1, 1, "-1 minutes"),
        ("hidden-new-2", "bochk", "Hidden B", 1, 1, "-2 minutes"),
    ]
    conn = _db(rows)

    assert "hidden-new-1" not in _board_ids(conn)  # public board: hidden excluded
    with_hidden = _board_ids(conn, with_hidden=True)
    # with_hidden ranks them in and, being freshest, they displace the 2 oldest.
    assert {"hidden-new-1", "hidden-new-2"} <= with_hidden
    assert len(with_hidden) == BOARD_COMPANY_CAP


def test_a_role_with_no_posting_date_is_off_the_board_and_unrankable():
    conn = _db([("dated", "bochk", "Dated", 1, 0, "-2 minutes")])
    conn.execute(
        "INSERT INTO jobs (source_id, company_slug, title, is_primary, "
        "admin_hidden, posted_at) VALUES ('undated', 'bochk', 'Undated', 1, 0, NULL)"
    )
    conn.commit()
    assert _board_ids(conn) == {"dated"}


def test_non_primary_and_inactive_rows_never_reach_the_board():
    conn = _db(
        [
            ("primary", "bochk", "Primary", 1, 0, "-1 minutes"),
            ("secondary", "bochk", "Secondary", 0, 0, "-1 minutes"),
            ("closed", "bochk", "Closed", 1, 0, "-3 minutes"),
        ]
    )
    conn.execute("UPDATE jobs SET is_active = 0 WHERE source_id = 'closed'")
    conn.commit()
    assert _board_ids(conn) == {"primary"}


def test_the_cap_is_a_single_knob():
    """One module-level constant, no per-employer override — raising it widens
    every employer equally (the ADR's stated design)."""
    rows = [
        (f"x{i:03d}", "employer-x", f"X {i}", 1, 0, f"-{i + 1} minutes")
        for i in range(BOARD_COMPANY_CAP + 10)
    ]
    conn = _db(rows)
    assert len(_board_ids(conn)) == BOARD_COMPANY_CAP

    original = board_visibility.BOARD_COMPANY_CAP
    try:
        board_visibility.BOARD_COMPANY_CAP = original + 5
        assert len(_board_ids(conn)) == original + 5
    finally:
        board_visibility.BOARD_COMPANY_CAP = original
