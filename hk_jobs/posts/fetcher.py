"""
Fetcher: polls the recruiters.yaml watchlist for new posts, and runs the
weekly keyword discovery search. Both feed the same raw linkedin_posts
table (PLAN_LINKEDIN_POSTS.md §4 architecture) — discovery doesn't yet grow
the watchlist automatically (that candidate-review-queue step is LP-6); for
now its results are just another raw-tier input for LP-3 extraction.

Cron-slippage handling (watchlist poll): rather than a fixed "last 24h"
window, each recruiter's fetch is scoped to `since = max(last_fetched_at,
now - CATCHUP_FLOOR_HOURS)`. A fixed window would silently create a gap if
a run is missed or delayed — e.g. daily_run.sh fails one day, and "last 24h"
on the next run never covers the skipped day. The floor exists so a missing
or very stale watermark (new recruiter, multi-day outage) doesn't ask the
vendor for a profile's entire history.

Per-recruiter isolation: one recruiter's failure (deleted profile, vendor
hiccup) never stops the rest of the watchlist — same convention as
BaseAdapter._safe_fetch for the company adapters.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from hk_jobs.posts import budget
from hk_jobs.posts.store import CATCHUP_FLOOR_HOURS, PostStore, RawPost
from hk_jobs.posts.vendor_client import ApifyAuthError, ApifyClient, VendorResult
from hk_jobs.recruiters_config import RecruiterConfig, load_recruiters

logger = logging.getLogger(__name__)

# Seed discovery queries — the same three validated in the LP-0 bake-off
# (docs/BAKEOFF_RESULTS.md), which found ~65-70% manual-read precision.
# Not yet configurable; revisit once LP-6's candidate-review-queue exists.
DEFAULT_DISCOVERY_QUERIES = [
    "hiring Hong Kong compliance private bank",
    "confidential mandate Hong Kong relationship manager",
    "hiring Hong Kong hedge fund analyst",
]


@dataclass
class FetchRunSummary:
    recruiters_polled: int = 0
    recruiters_failed: int = 0
    posts_inserted: int = 0
    posts_updated: int = 0
    cost_usd: float = 0.0
    budget_blocked: bool = False
    errors: list[str] = field(default_factory=list)


def fetch_watchlist(db_path: str, *, client: ApifyClient | None = None) -> FetchRunSummary:
    """Poll every enabled recruiters.yaml entry for new posts since last success."""
    summary = FetchRunSummary()
    store = PostStore(db_path)
    client = client or ApifyClient()

    try:
        recruiters = load_recruiters()
    except (OSError, ValueError) as exc:
        logger.error("Could not load recruiters.yaml — aborting watchlist poll: %s", exc)
        summary.errors.append(str(exc))
        return summary

    for recruiter in recruiters:
        status = budget.check_budget(db_path)
        if status.blocked:
            summary.budget_blocked = True
            logger.error(
                "Budget cap hit ($%.2f) — stopping watchlist poll with %d/%d recruiters left",
                status.month_to_date_usd,
                len(recruiters) - summary.recruiters_polled,
                len(recruiters),
            )
            break

        try:
            _poll_one_recruiter(recruiter, client=client, store=store, summary=summary)
            summary.recruiters_polled += 1
        except ApifyAuthError:
            # Bad/expired token affects every remaining recruiter identically —
            # no point burning through the rest of the watchlist one-by-one.
            logger.error("Apify auth failed — aborting watchlist poll entirely")
            summary.errors.append("Apify auth failed")
            store.record_fetch_result(recruiter.slug, status="error", error="auth failed")
            summary.recruiters_failed += 1
            break
        except Exception as exc:  # noqa: BLE001 - one bad recruiter must not stop the rest
            logger.exception("Recruiter %r: fetch failed", recruiter.name)
            store.record_fetch_result(recruiter.slug, status="error", error=str(exc))
            summary.recruiters_failed += 1
            summary.errors.append(f"{recruiter.name}: {exc}")

    logger.info(
        "Watchlist poll done: %d/%d recruiters ok, %d failed, %d posts inserted, "
        "%d updated, $%.4f spent",
        summary.recruiters_polled, len(recruiters), summary.recruiters_failed,
        summary.posts_inserted, summary.posts_updated, summary.cost_usd,
    )
    return summary


def _poll_one_recruiter(
    recruiter: RecruiterConfig, *, client: ApifyClient, store: PostStore, summary: FetchRunSummary
) -> None:
    last_fetched_at = store.get_last_fetched_at(recruiter.slug)
    since = _resolve_since(last_fetched_at)

    result = client.fetch_profile_posts(recruiter.profile_url, since_date=since)
    _record_result_cost(store.db_path, result, run_kind="watchlist")
    summary.cost_usd += result.cost_usd

    posts = [
        _parse_vendor_item(item, recruiter_slug=recruiter.slug, source_run="watchlist")
        for item in result.items
    ]
    posts = [p for p in posts if p is not None]
    inserted, updated = store.upsert_posts(posts)
    summary.posts_inserted += inserted
    summary.posts_updated += updated
    store.record_fetch_result(recruiter.slug, status="ok")

    logger.info(
        "%s (%s): %d posts fetched (%d new, %d refreshed) since %s",
        recruiter.name, recruiter.slug, len(posts), inserted, updated, since,
    )


def fetch_discovery(
    db_path: str,
    *,
    queries: list[str] | None = None,
    client: ApifyClient | None = None,
) -> FetchRunSummary:
    """Run the weekly keyword discovery search across the seed query list."""
    summary = FetchRunSummary()
    store = PostStore(db_path)
    client = client or ApifyClient()
    queries = queries or DEFAULT_DISCOVERY_QUERIES

    for query in queries:
        status = budget.check_budget(db_path)
        if status.blocked:
            summary.budget_blocked = True
            logger.error(
                "Budget cap hit ($%.2f) — stopping discovery search early", status.month_to_date_usd
            )
            break

        try:
            result = client.search_posts(query)
            _record_result_cost(db_path, result, run_kind="discovery")
            summary.cost_usd += result.cost_usd

            posts = [
                _parse_vendor_item(
                    item, recruiter_slug=_discovery_slug(item), source_run="discovery"
                )
                for item in result.items
            ]
            posts = [p for p in posts if p is not None]
            inserted, updated = store.upsert_posts(posts)
            summary.posts_inserted += inserted
            summary.posts_updated += updated
            summary.recruiters_polled += 1  # reused as "queries run" for this summary
            logger.info(
                "Discovery query %r: %d posts (%d new, %d refreshed)",
                query, len(posts), inserted, updated,
            )
        except ApifyAuthError:
            logger.error("Apify auth failed — aborting discovery search entirely")
            summary.errors.append("Apify auth failed")
            summary.recruiters_failed += 1
            break
        except Exception as exc:  # noqa: BLE001 - one bad query must not stop the rest
            logger.exception("Discovery query %r failed", query)
            summary.recruiters_failed += 1
            summary.errors.append(f"{query!r}: {exc}")

    logger.info(
        "Discovery search done: %d/%d queries ok, %d posts inserted, %d updated, $%.4f spent",
        summary.recruiters_polled, len(queries),
        summary.posts_inserted, summary.posts_updated, summary.cost_usd,
    )
    return summary


def _resolve_since(last_fetched_at: str | None) -> str:
    """max(last_fetched_at, now - CATCHUP_FLOOR_HOURS), as an ISO date string."""
    floor = datetime.now(UTC) - timedelta(hours=CATCHUP_FLOOR_HOURS)
    if last_fetched_at:
        try:
            last = datetime.fromisoformat(last_fetched_at)
            since = max(last, floor)
            if last < floor:
                logger.warning(
                    "Last fetch was %s, older than the %dh catch-up floor — "
                    "capping lookback to avoid a full-history pull",
                    last_fetched_at, CATCHUP_FLOOR_HOURS,
                )
            return since.date().isoformat()
        except ValueError:
            logger.warning("Unparseable last_fetched_at %r — using catch-up floor", last_fetched_at)
    return floor.date().isoformat()


def _record_result_cost(db_path: str, result: VendorResult, *, run_kind: str) -> None:
    if not result.items:
        return
    budget.record_cost(
        db_path,
        vendor="apify",
        actor=result.actor,
        run_kind=run_kind,
        items=len(result.items),
        cost_usd=result.cost_usd,
    )


def _discovery_slug(item: dict[str, Any]) -> str:
    """
    Discovery posts don't come from a known recruiters.yaml entry. Prefix
    with 'disc-' so this can never collide with a real watchlist slug —
    LP-6's candidate-review-queue is what promotes a discovery author into
    a real recruiters.yaml entry with a proper slug.
    """
    author = item.get("author") or {}
    ident = (
        author.get("publicIdentifier")
        or author.get("universalName")
        or author.get("id")
        or "unknown"
    )
    return f"disc-{ident}"


def _parse_vendor_item(
    item: dict[str, Any], *, recruiter_slug: str, source_run: str
) -> RawPost | None:
    """
    Map one HarvestAPI dataset item to a RawPost. Shape confirmed against
    real LP-0 bake-off output (docs/bakeoff/*.json) — both actors return the
    same core fields (id, linkedinUrl, content, author, postedAt, engagement).
    """
    post_urn = item.get("id")
    if not post_urn:
        logger.warning("Vendor item missing 'id' — skipped: %r", str(item)[:200])
        return None

    author = item.get("author") or {}
    posted_at = (item.get("postedAt") or {}).get("date")
    engagement = item.get("engagement") or {}

    return RawPost(
        post_urn=str(post_urn),
        recruiter_slug=recruiter_slug,
        source_run=source_run,
        author_name=author.get("name"),
        author_profile_url=author.get("linkedinUrl"),
        post_text=item.get("content") or "",
        post_url=item.get("linkedinUrl"),
        posted_at=posted_at,
        engagement_likes=int(engagement.get("likes") or 0),
        engagement_comments=int(engagement.get("comments") or 0),
        vendor_payload=item,
    )
