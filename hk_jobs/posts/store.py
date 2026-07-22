"""
SQLite persistence for the raw linkedin_posts tier and per-recruiter fetch
state. Mirrors storage.py's upsert-via-ON-CONFLICT convention, scaled down
to what this table actually needs.

Dedup: post_urn is the primary key. A post can legitimately be seen twice
(daily watchlist poll + weekly discovery search, or two watchlist polls
before it scrolls out of the vendor's "last N posts" window). On a repeat
sighting we refresh only engagement counts + fetched_at — post_text,
posted_at, source_run, and extraction_status are left untouched so a post
that already went through LP-3 classification isn't silently reset to
'pending' by a later re-sighting.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# Fallback lookback when a recruiter has no recorded last_fetched_at (new
# entry) or it's stale beyond this — prevents asking the vendor for a
# profile's entire history after a multi-day outage. See fetcher.py.
CATCHUP_FLOOR_HOURS = 48


@dataclass
class RawPost:
    post_urn: str
    recruiter_slug: str
    source_run: str  # "watchlist" | "discovery"
    author_name: str | None
    author_profile_url: str | None
    post_text: str
    post_url: str | None
    posted_at: str | None
    engagement_likes: int
    engagement_comments: int
    vendor_payload: dict[str, Any]


class PostStore:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def upsert_posts(self, posts: list[RawPost]) -> tuple[int, int]:
        """Insert new posts / refresh engagement on repeats. Returns (inserted, updated)."""
        if not posts:
            return (0, 0)
        conn = sqlite3.connect(self.db_path)
        inserted = updated = 0
        now = datetime.now(UTC).isoformat()
        try:
            with conn:
                for p in posts:
                    existing = conn.execute(
                        "SELECT 1 FROM linkedin_posts WHERE post_urn = ?", (p.post_urn,)
                    ).fetchone()
                    conn.execute(
                        """
                        INSERT INTO linkedin_posts (
                            post_urn, recruiter_slug, source_run, author_name,
                            author_profile_url, post_text, post_url, posted_at,
                            engagement_likes, engagement_comments, fetched_at,
                            vendor_payload_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(post_urn) DO UPDATE SET
                            engagement_likes = excluded.engagement_likes,
                            engagement_comments = excluded.engagement_comments,
                            fetched_at = excluded.fetched_at
                        """,
                        (
                            p.post_urn, p.recruiter_slug, p.source_run, p.author_name,
                            p.author_profile_url, p.post_text, p.post_url, p.posted_at,
                            p.engagement_likes, p.engagement_comments, now,
                            json.dumps(p.vendor_payload, ensure_ascii=False),
                        ),
                    )
                    if existing:
                        updated += 1
                    else:
                        inserted += 1
        finally:
            conn.close()
        return (inserted, updated)

    def get_last_fetched_at(self, slug: str) -> str | None:
        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT last_fetched_at FROM recruiter_fetch_state WHERE slug = ?", (slug,)
            ).fetchone()
            return row[0] if row else None
        finally:
            conn.close()

    def record_fetch_result(
        self, slug: str, *, status: str, error: str | None = None
    ) -> None:
        """
        Update recruiter_fetch_state after an attempt. last_fetched_at is only
        advanced on success — a failed attempt should be retried from the same
        watermark next run, not silently skip the gap it failed to cover.
        """
        conn = sqlite3.connect(self.db_path)
        now = datetime.now(UTC).isoformat()
        try:
            with conn:
                if status == "ok":
                    conn.execute(
                        """
                        INSERT INTO recruiter_fetch_state
                            (slug, last_fetched_at, last_status, last_error)
                        VALUES (?, ?, 'ok', NULL)
                        ON CONFLICT(slug) DO UPDATE SET
                            last_fetched_at = excluded.last_fetched_at,
                            last_status = 'ok',
                            last_error = NULL
                        """,
                        (slug, now),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO recruiter_fetch_state
                            (slug, last_fetched_at, last_status, last_error)
                        VALUES (?, NULL, 'error', ?)
                        ON CONFLICT(slug) DO UPDATE SET
                            last_status = 'error',
                            last_error = excluded.last_error
                        """,
                        (slug, error),
                    )
        finally:
            conn.close()
