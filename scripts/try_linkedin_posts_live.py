"""
Live smoke-test for the Apify/HarvestAPI vendor client (LP-2).

⚠  LEGAL: hits Apify's paid API, which performs the actual LinkedIn access.
   Prototype/verification use only. See hk_jobs/posts/vendor_client.py and
   CLAUDE.md's "Exception: LinkedIn recruiter posts" section for the posture.
⚠  COSTS MONEY: $2 per 1,000 results returned. A single small run (one
   profile, maxPosts=5) is a fraction of a cent, but this is real spend
   against the $30/mo cap — check hk_jobs/posts/budget.py's numbers after
   running this.

The field names in vendor_client.py (targetUrls, postedLimitDate,
searchQueries, postedLimit) were drawn from the LP-0 bake-off's raw output,
not from re-verified live docs. Run this script once before trusting
--fetch-posts / --posts-discovery in the daily cron, to confirm they still
match the actor's current schema.

Usage:
    python scripts/try_linkedin_posts_live.py profile \\
        --url https://hk.linkedin.com/in/lamgillian
    python scripts/try_linkedin_posts_live.py search \\
        --query "hiring Hong Kong compliance private bank"
"""

import argparse
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

from hk_jobs.posts.vendor_client import ApifyClient  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description="Live Apify/HarvestAPI smoke-test")
    sub = p.add_subparsers(dest="mode", required=True)

    p_profile = sub.add_parser("profile", help="Poll one recruiter profile")
    p_profile.add_argument("--url", required=True, help="LinkedIn profile URL")
    p_profile.add_argument("--since", default=None, help="postedLimitDate, e.g. 2026-07-01")
    p_profile.add_argument("--max-posts", type=int, default=5)

    p_search = sub.add_parser("search", help="Run one discovery search query")
    p_search.add_argument("--query", required=True)
    p_search.add_argument("--posted-limit", default="month")
    p_search.add_argument("--max-posts", type=int, default=5)

    args = p.parse_args()
    client = ApifyClient()

    if args.mode == "profile":
        result = client.fetch_profile_posts(
            args.url, since_date=args.since, max_posts=args.max_posts
        )
    else:
        result = client.search_posts(
            args.query, posted_limit=args.posted_limit, max_posts=args.max_posts
        )

    print(f"\nActor: {result.actor}")
    print(f"Items: {len(result.items)}   Cost: ${result.cost_usd:.4f}\n")
    print("-" * 60)
    for item in result.items[:5]:
        author = item.get("author") or {}
        engagement = item.get("engagement") or {}
        print(f"id       : {item.get('id')}")
        print(f"author   : {author.get('name')} ({author.get('linkedinUrl')})")
        print(f"posted   : {(item.get('postedAt') or {}).get('date')}")
        print(f"likes    : {engagement.get('likes')}  comments: {engagement.get('comments')}")
        print(f"content  : {(item.get('content') or '')[:200]}")
        print()

    if not result.items:
        print("0 items — check the URL/query, or confirm the actor's field names haven't changed.")


if __name__ == "__main__":
    main()
