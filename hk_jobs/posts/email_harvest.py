"""
LP-5 recruiter email harvest (PLAN_LINKEDIN_POSTS.md decision #10): a
one-time-per-recruiter (then quarterly-refresh) pull of each watchlist
recruiter's email via harvestapi/linkedin-profile-scraper's $10/1k
email-search mode, so cards/detail views can show a direct contact rather
than only the "DM on LinkedIn" CTA.

Privacy posture (plan §3): harvested emails are personal data. Mitigations
already in place elsewhere in this pipeline apply here too — internal
boss-facing board only, attribution always links back to the recruiter's own
public profile, purpose limited to contacting them about mandates they
publicly advertised.

Two-part run:
  1. Harvest — one email-search call per recruiter that doesn't already have
     a fresh-enough email (REFRESH_INTERVAL_DAYS), budget-checked and
     per-recruiter isolated like fetcher.py.
  2. Backfill — push freshly-harvested emails into board_signals on every
     ALREADY-promoted linkedin_posts job. Without this, only jobs promoted
     AFTER the harvest would ever show an email — promote.py only re-touches
     rows with extraction_status='pending', so existing promoted rows would
     otherwise carry a stale/absent recruiter_email forever.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from hk_jobs.posts import budget
from hk_jobs.posts.store import PostStore
from hk_jobs.posts.vendor_client import ApifyAuthError, ApifyClient
from hk_jobs.recruiters_config import load_recruiters

logger = logging.getLogger(__name__)

# "Refresh quarterly" (plan §5 LP-6) — a recruiter with an email harvested
# more recently than this is skipped rather than re-charged $0.01 every run.
REFRESH_INTERVAL_DAYS = 90


@dataclass
class EmailHarvestSummary:
    checked: int = 0
    harvested: int = 0
    skipped_fresh: int = 0
    no_email_found: int = 0
    failed: int = 0
    cost_usd: float = 0.0
    budget_blocked: bool = False
    backfilled_jobs: int = 0
    errors: list[str] = field(default_factory=list)


def run_email_harvest(
    db_path: str, *, force: bool = False, client: ApifyClient | None = None
) -> EmailHarvestSummary:
    summary = EmailHarvestSummary()
    store = PostStore(db_path)
    client = client or ApifyClient()

    try:
        recruiters = load_recruiters()
    except (OSError, ValueError) as exc:
        logger.error("Could not load recruiters.yaml — aborting email harvest: %s", exc)
        summary.errors.append(str(exc))
        return summary

    for recruiter in recruiters:
        summary.checked += 1

        if not force and _is_fresh(store.get_email_fetched_at(recruiter.slug)):
            summary.skipped_fresh += 1
            continue

        status = budget.check_budget(db_path)
        if status.blocked:
            summary.budget_blocked = True
            logger.error(
                "Budget cap hit ($%.2f) — stopping email harvest with %d/%d recruiters left",
                status.month_to_date_usd, len(recruiters) - summary.checked + 1, len(recruiters),
            )
            break

        try:
            result = client.fetch_profile_email(recruiter.profile_url)
            if result.items:
                budget.record_cost(
                    db_path, vendor="apify", actor=result.actor,
                    run_kind="email_harvest", items=len(result.items), cost_usd=result.cost_usd,
                )
                summary.cost_usd += result.cost_usd

            email = _best_email(result.items[0]) if result.items else None
            store.record_email(recruiter.slug, email)
            if email:
                summary.harvested += 1
                logger.info("%s (%s): harvested %s", recruiter.name, recruiter.slug, email)
            else:
                summary.no_email_found += 1
                logger.info("%s (%s): no email found", recruiter.name, recruiter.slug)
        except ApifyAuthError:
            logger.error("Apify auth failed — aborting email harvest entirely")
            summary.errors.append("Apify auth failed")
            summary.failed += 1
            break
        except Exception as exc:  # noqa: BLE001 - one bad recruiter must not stop the rest
            logger.exception("Recruiter %r: email harvest failed", recruiter.name)
            summary.failed += 1
            summary.errors.append(f"{recruiter.name}: {exc}")

    summary.backfilled_jobs = _backfill_promoted_jobs(db_path)

    logger.info(
        "Email harvest done: %d checked, %d harvested, %d skipped (fresh), "
        "%d no email, %d failed, $%.4f spent, %d jobs backfilled",
        summary.checked, summary.harvested, summary.skipped_fresh,
        summary.no_email_found, summary.failed, summary.cost_usd, summary.backfilled_jobs,
    )
    return summary


def _is_fresh(email_fetched_at: str | None) -> bool:
    if not email_fetched_at:
        return False
    try:
        fetched = datetime.fromisoformat(email_fetched_at)
    except ValueError:
        return False
    return datetime.now(UTC) - fetched < timedelta(days=REFRESH_INTERVAL_DAYS)


def _best_email(item: dict) -> str | None:
    """
    Pick the best candidate from the actor's `emails` array: prefer
    deliverable=True, then highest qualityScore. Confirmed field shape via
    the 2026-07-22 live probe (see vendor_client.py) — each entry has
    email/deliverable/qualityScore/status.
    """
    emails = item.get("emails") or []
    if not emails:
        return None
    ranked = sorted(
        emails,
        key=lambda e: (bool(e.get("deliverable")), e.get("qualityScore") or 0),
        reverse=True,
    )
    return ranked[0].get("email")


def _backfill_promoted_jobs(db_path: str) -> int:
    """
    Push every recruiter's current harvested email into board_signals for
    already-promoted linkedin_posts jobs. promote.py only sets
    recruiter_email at promotion time (extraction_status='pending' -> once)
    — without this pass, a job promoted before its recruiter's email was
    harvested would carry a stale/absent value forever.
    """
    store = PostStore(db_path)
    emails = store.all_recruiter_emails()
    if not emails:
        return 0

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    updated = 0
    try:
        rows = conn.execute(
            """
            SELECT jobs.source_id, jobs.board_signals, linkedin_posts.recruiter_slug
            FROM jobs
            JOIN linkedin_posts ON linkedin_posts.post_urn = jobs.source_id
            WHERE jobs.source = 'linkedin_posts'
            """
        ).fetchall()
        with conn:
            for row in rows:
                email = emails.get(row["recruiter_slug"])
                if not email:
                    continue
                signals = json.loads(row["board_signals"] or "{}")
                if signals.get("recruiter_email") == email:
                    continue
                signals["recruiter_email"] = email
                conn.execute(
                    "UPDATE jobs SET board_signals = ? "
                    "WHERE source = 'linkedin_posts' AND source_id = ?",
                    (json.dumps(signals, ensure_ascii=False), row["source_id"]),
                )
                updated += 1
    finally:
        conn.close()
    return updated
