"""Deterministic repairs to salary estimates already in the database.

A clamp change only affects estimates written *after* it. That is deliberate — the
alternative, folding every clamp constant into `salary.version()`, marks ~13,000 stored
rows stale and re-pays DeepSeek for all of them (see `salary.py`'s own reasoning about
what the fingerprint deliberately does and does not cover). But it leaves the rows already
published carrying the number the old clamp allowed.

This module closes that gap for repairs that need no model call: the answer is a pure
function of the row, so it can be recomputed for free, as many times as you like.

The one repair here today is the internship ceiling. The 2026-08-18 estimator audit
(`docs/SALARY_ESTIMATOR_AUDIT.html`) found 58 of 153 live internship listings priced above
the HK$15,000 cap the enricher's own prompt sets for them — the worst a 2027
investment-banking summer analyst at HK$41,500-83,500, 5.6x the cap.

Every repair here must be **idempotent and down-only**: it runs on a schedule against a
database it does not own, so running it twice must change nothing the second time, and it
must never be able to raise a published salary.
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field

from hk_jobs.salary_clamp import (
    INTERNSHIP_MAX_MONTHLY_HKD,
    SINGLE_VALUE_MIN_FRACTION,
    is_internship,
)

logger = logging.getLogger(__name__)


@dataclass
class RepairSummary:
    """What a repair pass found and (if applying) wrote."""

    examined: int = 0
    matched: int = 0
    repaired: int = 0
    #: Rows whose title matched but whose stored seniority is not "junior". Empty in every
    #: run so far; a non-empty list is the signal that the title pattern has started
    #: catching full-time roles and wants a human before the write is trusted.
    suspicious: list[str] = field(default_factory=list)
    #: (title, old_max, new_max), largest reduction first — for the run log.
    examples: list[tuple[str, int, int]] = field(default_factory=list)


def _capped(est_min: int | None, est_max: int | None) -> tuple[int | None, int | None]:
    """The internship ceiling alone, with `salary_clamp`'s own single-value rule.

    Deliberately not a call to `clamp_salary`: this runs against rows written by many
    older clamp versions, and re-running the *whole* clamp would also apply every other
    ceiling that has moved since, silently rewriting thousands of estimates nobody
    reviewed. One repair, one class of change.
    """
    if est_max is None or est_max <= INTERNSHIP_MAX_MONTHLY_HKD:
        return est_min, est_max
    new_max = INTERNSHIP_MAX_MONTHLY_HKD
    new_min = est_min
    if new_min is None or new_min >= new_max:
        new_min = round(new_max * SINGLE_VALUE_MIN_FRACTION)
    return new_min, new_max


def repair_internship_salaries(
    db_path: str,
    *,
    dry_run: bool = True,
    live_board_only: bool = True,
) -> RepairSummary:
    """Clamp published internship estimates down to the internship ceiling.

    Idempotent: a second run finds nothing to change. Down-only: `_capped` can only lower
    a maximum, so a repeat run — or a bug in the title pattern — can never inflate a
    published salary.
    """
    summary = RepairSummary()
    board = "AND j.is_active = 1 AND j.is_primary = 1" if live_board_only else ""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            f"""SELECT j.title, e.source, e.source_id, e.seniority,
                       e.salary_estimated_min AS mn, e.salary_estimated_max AS mx
                  FROM jobs j JOIN job_enrichments e
                    ON j.source = e.source AND j.source_id = e.source_id
                 WHERE e.salary_estimated_max IS NOT NULL {board}""",
        ).fetchall()
        summary.examined = len(rows)

        pending: list[tuple[int | None, int, str, str]] = []
        for row in rows:
            if not is_internship(row["title"]):
                continue
            summary.matched += 1
            if row["seniority"] not in (None, "junior"):
                summary.suspicious.append(f"[{row['seniority']}] {row['title']}")
            new_min, new_max = _capped(row["mn"], row["mx"])
            if (new_min, new_max) == (row["mn"], row["mx"]):
                continue
            pending.append((new_min, new_max, row["source"], row["source_id"]))
            summary.examples.append((row["title"], row["mx"], new_max))

        summary.repaired = len(pending)
        summary.examples.sort(key=lambda e: e[1], reverse=True)
        del summary.examples[10:]

        if summary.suspicious:
            logger.warning(
                "%d internship-matched rows are not stored as 'junior' — review before "
                "trusting this write: %s",
                len(summary.suspicious), "; ".join(summary.suspicious[:5]),
            )

        if pending and not dry_run:
            with conn:
                conn.executemany(
                    """UPDATE job_enrichments
                          SET salary_estimated_min = ?, salary_estimated_max = ?
                        WHERE source = ? AND source_id = ?""",
                    pending,
                )
            logger.info("Repaired %d internship salary estimates", summary.repaired)
    finally:
        conn.close()
    return summary
