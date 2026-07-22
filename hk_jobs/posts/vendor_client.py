"""
Thin client for the Apify/HarvestAPI actors that back the "Secret Market"
LinkedIn-posts pipeline (LP-0 bake-off winner — see docs/BAKEOFF_RESULTS.md).

⚠  LEGAL/POSTURE (PLAN_LINKEDIN_POSTS.md §3): we call a paid third-party API
   that performs the actual LinkedIn access on our behalf. This does not
   launder LinkedIn's ToS — scraping LinkedIn violates its terms regardless
   of who runs the browser — but it keeps OUR code on the same "no login, no
   credentials, no authwall" line the rest of this repo already draws.
   Prototype-only posture, same as the JobsDB/Indeed/LinkedIn-guest adapters.

Two actors, both billed at $2/1,000 results (confirmed in the LP-0 bake-off):
  • harvestapi/linkedin-profile-posts — watchlist polling, one profile at a
    time via `targetUrls` + `postedLimitDate` (fetch since a given date).
  • harvestapi/linkedin-post-search   — keyword discovery via `searchQueries`
    (NOT `queries` — a wrong field name silently returns 0 results, no error;
    confirmed the hard way during the bake-off) + `postedLimit`.

Field names above are drawn directly from the real LP-0 bake-off run
(docs/bakeoff/apify_profile_posts_raw.json, apify_post_search_raw.json), not
from vendor documentation, since the actor's build definition is the actual
source of truth. They have NOT been re-verified live in this codebase — run
scripts/try_linkedin_posts_live.py before trusting this in the daily cron.

API call shape: Apify's synchronous run endpoint
(POST /v2/acts/{actor}/run-sync-get-dataset-items) blocks until the actor
finishes and returns the dataset items directly — no separate poll-for-
completion loop needed, which fits our modest per-call volumes (one profile
or one search query at a time, capped results).

Single mockable seam: `_call_actor()`. Tests monkeypatch this method (same
pattern as LinkedInAdapter._fetch_url — see tests/test_linkedin.py) so no
real network call is ever made in the test suite.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

from hk_jobs.http_utils import with_retry

logger = logging.getLogger(__name__)

_API_BASE = "https://api.apify.com/v2"
_TIMEOUT_SECS = 120.0

# Confirmed in the LP-0 bake-off (docs/BAKEOFF_RESULTS.md): both actors bill
# $2 per 1,000 results (posts) returned, regardless of query complexity.
COST_PER_RESULT_USD = 2.0 / 1000

PROFILE_POSTS_ACTOR = "harvestapi/linkedin-profile-posts"
POST_SEARCH_ACTOR = "harvestapi/linkedin-post-search"


class ApifyAuthError(RuntimeError):
    """Raised when APIFY_API_TOKEN is missing or rejected. Never retried."""


@dataclass
class VendorResult:
    items: list[dict[str, Any]]
    actor: str

    @property
    def cost_usd(self) -> float:
        return len(self.items) * COST_PER_RESULT_USD


class ApifyClient:
    """
    Thin wrapper around the two HarvestAPI actors. Retries transient
    failures (timeout, network error, 429/5xx) up to 2 attempts total —
    kept low, not the repo's usual 3, because every retry on a paid vendor
    call is itself billable. A clean 4xx (bad token, bad input schema) is
    never retried since retrying won't fix it.
    """

    def __init__(self, api_token: str | None = None):
        self.api_token = api_token or os.environ.get("APIFY_API_TOKEN", "")
        if not self.api_token:
            raise ApifyAuthError(
                "APIFY_API_TOKEN not set. Export it or add it to config/api_keys.env "
                "(see hk_jobs/posts/vendor_client.py)."
            )

    def fetch_profile_posts(
        self, profile_url: str, *, since_date: str | None = None, max_posts: int = 20
    ) -> VendorResult:
        """
        Watchlist polling: posts from ONE profile, optionally since a date.

        `since_date` is `postedLimitDate` in the actor's schema (ISO date
        string) — the LP-0 bake-off confirmed this param exists and scopes
        results server-side, which is cheaper than fetching everything and
        filtering client-side.
        """
        payload = {"targetUrls": [profile_url], "maxPosts": max_posts}
        if since_date:
            payload["postedLimitDate"] = since_date
        items = self._call_actor(PROFILE_POSTS_ACTOR, payload)
        return VendorResult(items=items, actor=PROFILE_POSTS_ACTOR)

    def search_posts(
        self, query: str, *, posted_limit: str = "month", max_posts: int = 50
    ) -> VendorResult:
        """
        Weekly discovery search: posts matching a free-text query.

        `searchQueries` (plural, list) is the CORRECT field name — the LP-0
        bake-off's first attempt used `queries` and silently got 0 results
        with no error, so this is deliberately spelled out here to prevent
        that mistake from recurring.
        """
        payload = {
            "searchQueries": [query],
            "postedLimit": posted_limit,
            "sortBy": "date",
        }
        items = self._call_actor(POST_SEARCH_ACTOR, payload, max_items=max_posts)
        return VendorResult(items=items, actor=POST_SEARCH_ACTOR)

    def _call_actor(
        self, actor: str, payload: dict[str, Any], *, max_items: int | None = None
    ) -> list[dict[str, Any]]:
        """
        Single mockable seam — patch this in tests to inject fixture JSON
        instead of hitting the real Apify API.
        """
        actor_path = actor.replace("/", "~")
        url = f"{_API_BASE}/acts/{actor_path}/run-sync-get-dataset-items"

        def _do_call() -> list[dict[str, Any]]:
            resp = httpx.post(
                url,
                params={"token": self.api_token},
                json=payload,
                timeout=_TIMEOUT_SECS,
            )
            if resp.status_code in (401, 403):
                raise ApifyAuthError(f"Apify rejected the API token (HTTP {resp.status_code})")
            resp.raise_for_status()
            return resp.json()

        items = with_retry(_do_call, max_attempts=2)
        if max_items is not None:
            items = items[:max_items]
        return items
