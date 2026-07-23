"""
Age-based expiry for Secret Market jobs.

Why this exists: --fetch-posts-backfill (see fetcher.py) deliberately pulls
each recruiter's full available post history with no date filter, so it can
promote posts from months or years ago as if they were current openings.
A LinkedIn post from 2022 is not a currently-open mandate — mainstream/
boutique jobs don't have this problem (they're refreshed daily and
soft-deleted via JobStore.mark_inactive_for_run when they disappear from
the source), so this is scoped to source='linkedin_posts' only.

Soft-delete only, per CLAUDE.md's repo-wide convention (is_active=0, never
DELETE) — a member may have already reached out to a recruiter about a job
that's since aged out; hard-deleting would lose that context.

Uses posted_at (the post's actual date, extracted from the vendor payload),
NOT fetched_at (when we scraped it) — a post fetched today via backfill can
easily have been posted a year ago, which is exactly the case this exists
to catch. Jobs with posted_at IS NULL are left untouched: we can't determine
their age, and deactivating them on missing data risks hiding a genuinely
fresh listing that just failed to parse a date.
"""

from __future__ import annotations

import logging
import sqlite3

from hk_jobs.posts.promote import SOURCE

logger = logging.getLogger(__name__)

DEFAULT_MAX_AGE_DAYS = 90


def deactivate_stale_jobs(db_path: str, *, max_age_days: int = DEFAULT_MAX_AGE_DAYS) -> int:
    """
    Soft-delete active linkedin_posts jobs whose posted_at is older than
    max_age_days. Returns the number of rows deactivated.
    """
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            cur = conn.execute(
                """
                UPDATE jobs SET is_active = 0
                WHERE source = ?
                  AND is_active = 1
                  AND posted_at IS NOT NULL
                  AND date(posted_at) < date('now', ? || ' days')
                """,
                (SOURCE, f"-{max_age_days}"),
            )
            count = cur.rowcount
    finally:
        conn.close()
    logger.info(
        "Deactivated %d linkedin_posts job(s) older than %d days", count, max_age_days
    )
    return count
