"""Write-once weekly Role selections for the landing-page promotion rail.

The public board is intentionally live: Roles can close, become a secondary
cross-post, fall beyond an employer cap, or be hidden by an administrator. A
weekly promotion is different. Once FinEx presents a Role as one of the week's
picks, changing that list halfway through the week makes the landing page and
Sunday email disagree and leaves visitors chasing a moving target.

This module stores references, not copies of Role content. The reference list
is write-once for a Monday-to-Sunday Hong Kong week; the API resolves those
references with ADDRESSABLE visibility, so a Role that closes on Wednesday is
still shown through Sunday with its truthful ``closed`` state.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True, slots=True)
class WeeklyHighlightRef:
    source: str
    source_id: str
    related_search: str
    position: int = 0


def week_bounds(as_of: date) -> tuple[date, date]:
    """Return the Monday and Sunday containing ``as_of``."""
    monday = as_of - timedelta(days=as_of.weekday())
    return monday, monday + timedelta(days=6)


def _read_week(conn: sqlite3.Connection, week_start: date) -> list[WeeklyHighlightRef]:
    rows = conn.execute(
        """
        SELECT source, source_id, related_search, position
        FROM weekly_highlight_roles
        WHERE week_start = ?
        ORDER BY position
        """,
        (week_start.isoformat(),),
    ).fetchall()
    return [
        WeeklyHighlightRef(
            source=row[0],
            source_id=row[1],
            related_search=row[2],
            position=int(row[3]),
        )
        for row in rows
    ]


def lock_weekly_highlights(
    db_path: str | Path,
    refs: Iterable[WeeklyHighlightRef],
    *,
    week_start: date,
) -> list[WeeklyHighlightRef]:
    """Lock one week's ordered refs, returning the original set on every rerun.

    ``BEGIN IMMEDIATE`` serializes two Sunday processes before either checks the
    marker row. The separate week marker is important: an empty selection is a
    deliberate locked result too and cannot silently fill later in the week.
    """
    if week_start.weekday() != 0:
        raise ValueError("week_start must be a Monday")
    week_end = week_start + timedelta(days=6)
    requested = [
        WeeklyHighlightRef(ref.source, ref.source_id, ref.related_search, position)
        for position, ref in enumerate(refs)
    ]

    conn = sqlite3.connect(str(db_path), timeout=30)
    try:
        conn.execute("BEGIN IMMEDIATE")
        locked = conn.execute(
            "SELECT 1 FROM weekly_highlight_weeks WHERE week_start = ?",
            (week_start.isoformat(),),
        ).fetchone()
        if locked:
            existing = _read_week(conn, week_start)
            conn.commit()
            return existing

        conn.execute(
            """
            INSERT INTO weekly_highlight_weeks (week_start, week_end)
            VALUES (?, ?)
            """,
            (week_start.isoformat(), week_end.isoformat()),
        )
        conn.executemany(
            """
            INSERT INTO weekly_highlight_roles
                (week_start, position, source, source_id, related_search)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    week_start.isoformat(),
                    ref.position,
                    ref.source,
                    ref.source_id,
                    ref.related_search,
                )
                for ref in requested
            ],
        )
        conn.commit()
        return requested
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def current_weekly_highlights(
    conn: sqlite3.Connection,
    *,
    as_of: date,
) -> list[WeeklyHighlightRef]:
    """Read the immutable selection for the week containing ``as_of``."""
    week_start, _ = week_bounds(as_of)
    return _read_week(conn, week_start)


def is_current_weekly_highlight(
    conn: sqlite3.Connection,
    source: str,
    source_id: str,
    *,
    as_of: date,
) -> bool:
    """Whether an exact Role reference belongs to this week's locked set."""
    week_start, _ = week_bounds(as_of)
    return conn.execute(
        """
        SELECT 1
        FROM weekly_highlight_roles
        WHERE week_start = ? AND source = ? AND source_id = ?
        """,
        (week_start.isoformat(), source, source_id),
    ).fetchone() is not None
