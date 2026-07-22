"""
LP-3 promotion: run the extractor over pending linkedin_posts rows and
promote the ones that clear the gate into the canonical `jobs` table.

Promotion gate (PLAN_LINKEDIN_POSTS.md decision #8): concrete title +
HK-plausible location + stored confidence. Both must hold — a post with no
identifiable title, or one whose location can't be pinned to Hong Kong, stays
in linkedin_posts (extraction_status='rejected') and is never surfaced.

Confidential employers (decision #7): NEVER guess. If the extractor found no
named employer, company is set to "Confidential via {recruiter}" and the slug
is recruiter-based (confidential-{recruiter-slug}) — this means dedup_hash()
can only ever collapse a recruiter's own reposts of the SAME text, never
different confidential mandates, and never a real board listing. Named
employers get a best-effort slug from the company name so dedup_hash() CAN
match an existing board listing and trigger cross_posted (the "hidden"
signal) — but this is best-effort only: there's no runtime lookup from a
free-text employer name to an existing companies.yaml slug in this codebase
(confirmed: no such utility exists, only offline one-off resolver scripts
like scripts/resolve_indeed_slugs.py). A naive slugify that happens not to
match an existing slug just means this particular post-job doesn't get
flagged cross_posted — it's still promoted and shown, just without the dedup
credit. Never a promotion-blocking failure.

The "hidden" flag itself is NOT a stored column — it falls out of calling
JobStore.reconcile_cross_posted() after promotion: source='linkedin_posts'
AND cross_posted=False on the resulting Job means genuinely no cross-source
match was found (PLAN_LINKEDIN_POSTS.md §4, §7).
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime

from hk_jobs.posts.extractor import (
    PROMPT_VERSION,
    ExtractionResult,
    ExtractorAuthError,
    extract_post,
)
from hk_jobs.schema import Job
from hk_jobs.storage import JobStore

logger = logging.getLogger(__name__)

SOURCE = "linkedin_posts"
SOURCE_TIER = "social"


@dataclass
class PromotionSummary:
    processed: int = 0
    promoted: int = 0
    rejected: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


def run_promotion(db_path: str, *, limit: int | None = None) -> PromotionSummary:
    """
    Extract + promote every linkedin_posts row still in extraction_status='pending'.

    One bad post (extraction failure, malformed row) is logged and skipped —
    same per-item isolation convention as fetcher.py and BaseAdapter._safe_fetch.
    reconcile_cross_posted() is called once at the end of the whole pass, not
    per-post, matching how it's already called once per daily pipeline run for
    the ATS sources (storage.py's own convention — it re-derives cross_posted/
    apply_url/is_primary globally, not incrementally).
    """
    summary = PromotionSummary()
    rows = _fetch_pending(db_path, limit=limit)
    if not rows:
        logger.info("No pending posts to promote")
        return summary

    promoted_jobs: list[Job] = []
    conn = sqlite3.connect(db_path)
    try:
        for row in rows:
            summary.processed += 1
            try:
                if not row["post_text"] or not row["post_text"].strip():
                    # Empty content (seen in real discovery-search results — e.g. a
                    # company post with no body text). extract_post() would also
                    # return None for this, but leaving the row 'pending' would
                    # retry it forever for zero chance of ever succeeding. Reject
                    # immediately instead.
                    summary.rejected += 1
                    _set_status(conn, row["post_urn"], "rejected")
                    continue

                result = extract_post(row["post_text"])
                _store_extraction_result(conn, row["post_urn"], result)

                if result is None:
                    summary.failed += 1
                    continue

                if not _passes_gate(result):
                    summary.rejected += 1
                    _set_status(conn, row["post_urn"], "rejected")
                    continue

                job = _build_job(row, result)
                promoted_jobs.append(job)
                summary.promoted += 1
                _set_status(conn, row["post_urn"], "promoted")
            except ExtractorAuthError:
                # A bad/missing key affects every remaining post identically —
                # no point looping through the rest just to fail the same way.
                logger.error("DeepSeek auth failed — aborting promotion run entirely")
                summary.errors.append("DeepSeek auth failed")
                summary.failed += 1
                break
            except Exception as exc:  # noqa: BLE001 - one bad post must not stop the rest
                logger.exception("Post %s: promotion failed", row["post_urn"])
                summary.failed += 1
                summary.errors.append(f"{row['post_urn']}: {exc}")
    finally:
        conn.close()

    if promoted_jobs:
        with JobStore(db_path) as store:
            inserted, updated = store.upsert_many(promoted_jobs)
            groups, rows_updated = store.reconcile_cross_posted()
        logger.info(
            "Promoted %d jobs (%d inserted, %d updated). Cross-source: %d groups, %d rows updated.",
            len(promoted_jobs), inserted, updated, groups, rows_updated,
        )

    logger.info(
        "Promotion run done: %d processed, %d promoted, %d rejected, %d failed",
        summary.processed, summary.promoted, summary.rejected, summary.failed,
    )
    return summary


def _fetch_pending(db_path: str, *, limit: int | None) -> list[sqlite3.Row]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        sql = "SELECT * FROM linkedin_posts WHERE extraction_status = 'pending' ORDER BY fetched_at"
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def _passes_gate(result: ExtractionResult) -> bool:
    return (
        result.is_job_post
        and bool(result.title and result.title.strip())
        and result.hk_plausible
    )


def _build_job(row: sqlite3.Row, result: ExtractionResult) -> Job:
    recruiter_slug = row["recruiter_slug"]
    author_name = row["author_name"] or recruiter_slug

    if result.employer_named and result.employer_hint:
        company = result.employer_hint
        company_slug = _slugify(result.employer_hint)
    else:
        company = f"Confidential via {author_name}"
        company_slug = f"confidential-{recruiter_slug}"

    board_signals = {
        "recruiter_name": author_name,
        "recruiter_profile_url": row["author_profile_url"],
        "employer_hint": result.employer_hint if not result.employer_named else None,
        "engagement": {
            "likes": row["engagement_likes"],
            "comments": row["engagement_comments"],
        },
        "post_created_at": row["posted_at"],
    }

    return Job(
        source=SOURCE,
        source_id=row["post_urn"],
        company=company,
        company_slug=company_slug,
        url=row["post_url"] or "",
        title=result.title.strip(),
        description_clean=row["post_text"] or "",
        locations=[result.location] if result.location else [],
        seniority=result.seniority if result.seniority in _VALID_SENIORITY else None,
        salary_min=result.salary_min,
        salary_max=result.salary_max,
        salary_currency=result.salary_currency,
        skills_required=result.skills,
        posted_at=_parse_posted_at(row["posted_at"]),
        fetched_at=datetime.now(UTC),
        board_signals=board_signals,
        source_tier=SOURCE_TIER,
        extraction_confidence=result.confidence,
    )


_VALID_SENIORITY = {"intern", "junior", "mid", "senior", "lead", "executive"}


def _parse_posted_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _slugify(name: str) -> str:
    """
    Best-effort slug from a free-text employer name. NOT guaranteed to match
    an existing companies.yaml slug — see module docstring. Good enough for
    a stable, readable company_slug even when it doesn't dedup-match.
    """
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-") or "unknown"


def _store_extraction_result(
    conn: sqlite3.Connection, post_urn: str, result: ExtractionResult | None
) -> None:
    with conn:
        conn.execute(
            "UPDATE linkedin_posts SET extraction_result_json = ?, extraction_confidence = ?, "
            "extraction_prompt_version = ? WHERE post_urn = ?",
            (
                json.dumps(result.raw, ensure_ascii=False) if result else None,
                result.confidence if result else None,
                PROMPT_VERSION,
                post_urn,
            ),
        )


def _set_status(conn: sqlite3.Connection, post_urn: str, status: str) -> None:
    with conn:
        conn.execute(
            "UPDATE linkedin_posts SET extraction_status = ? WHERE post_urn = ?",
            (status, post_urn),
        )
