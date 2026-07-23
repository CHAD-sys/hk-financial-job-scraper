"""
LP-3 daily metrics (PLAN_LINKEDIN_POSTS.md §7) — computed on every run,
permanently. The LP-4 pilot go/no-go decision uses only the pilot window's
numbers (decision #12), but the computation itself runs forever.

Three metrics:
  1. Promoted jobs — cumulative active count from source='linkedin_posts'
  2. % truly hidden — promoted post-jobs with cross_posted=False / all promoted
     (cross_posted is computed by JobStore.reconcile_cross_posted(); a post-job
     with no cross-source match is exactly the "hidden market" signal)
  3. Precision proxy — share of active promoted jobs with
     extraction_confidence >= CONFIDENCE_THRESHOLD. The plan's fuller version
     ("classifier/extractor agreement") doesn't apply as written here since
     LP-3 combines classify+extract into one DeepSeek call (see extractor.py
     module docstring) rather than two independent stages to cross-check —
     this proxy is a simplification of that, not the two-model agreement
     check. The plan's real precision number comes from the MANUAL spot-check
     during the LP-4 pilot, not from this automated proxy.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from hk_jobs.posts.promote import SOURCE

CONFIDENCE_THRESHOLD = 0.7


@dataclass
class PostsMetrics:
    promoted_active: int
    truly_hidden: int
    pct_truly_hidden: float
    high_confidence: int
    pct_high_confidence: float


def compute_metrics(db_path: str) -> PostsMetrics:
    conn = sqlite3.connect(db_path)
    try:
        promoted_active = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE source = ? AND is_active = 1", (SOURCE,)
        ).fetchone()[0]

        truly_hidden = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE source = ? AND is_active = 1 AND cross_posted = 0",
            (SOURCE,),
        ).fetchone()[0]

        high_confidence = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE source = ? AND is_active = 1 "
            "AND extraction_confidence >= ?",
            (SOURCE, CONFIDENCE_THRESHOLD),
        ).fetchone()[0]
    finally:
        conn.close()

    pct_hidden = (truly_hidden / promoted_active * 100) if promoted_active else 0.0
    pct_conf = (high_confidence / promoted_active * 100) if promoted_active else 0.0

    return PostsMetrics(
        promoted_active=promoted_active,
        truly_hidden=truly_hidden,
        pct_truly_hidden=round(pct_hidden, 1),
        high_confidence=high_confidence,
        pct_high_confidence=round(pct_conf, 1),
    )


def format_metrics(m: PostsMetrics) -> str:
    return (
        f"Secret Market: {m.promoted_active} active promoted jobs | "
        f"{m.truly_hidden} truly hidden ({m.pct_truly_hidden}%) | "
        f"{m.high_confidence} high-confidence >= {CONFIDENCE_THRESHOLD} ({m.pct_high_confidence}%)"
    )
