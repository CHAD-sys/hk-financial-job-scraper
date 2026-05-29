"""
Live smoke-test for the Eightfold adapter.

Run this LOCALLY (not in CI) to confirm that the real Eightfold API
returns data in the shape our adapter expects. Prints the first 3 jobs
and dumps the first one as JSON so you can spot any field mismatches.

Usage:
    python scripts/try_eightfold_live.py
    python scripts/try_eightfold_live.py --tenant hsbc --domain hsbc.com
    python scripts/try_eightfold_live.py --tenant hangseng --domain hangseng.com
"""

import argparse
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

from hk_jobs.adapters.eightfold import EightfoldAdapter  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Live Eightfold adapter smoke-test")
    parser.add_argument("--tenant", default="hsbc", help="Eightfold tenant slug (default: hsbc)")
    parser.add_argument("--domain", default="hsbc.com", help="Company domain (default: hsbc.com)")
    parser.add_argument(
        "--location", default="Hong Kong", help="Location filter (default: Hong Kong)"
    )
    args = parser.parse_args()

    print(f"\nFetching jobs from  https://{args.tenant}.eightfold.ai")
    print(f"domain={args.domain}  location={args.location!r}\n")

    adapter = EightfoldAdapter(
        company="LiveTest",
        company_slug="live-test",
        tenant=args.tenant,
        domain=args.domain,
        location_filter=args.location,
    )

    jobs = adapter.fetch_jobs()

    if not jobs:
        print("No jobs returned — check tenant/domain or whether the endpoint is reachable.")
        return

    print(f"Total jobs fetched: {len(jobs)}")
    print("-" * 60)

    for job in jobs[:3]:
        print(f"title          : {job.title}")
        print(f"source_id      : {job.source_id}")
        print(f"url            : {job.url}")
        print(f"locations      : {job.locations}")
        print(f"department     : {job.department}")
        print(f"posted_at      : {job.posted_at}")
        print(f"description_raw: {job.description_raw[:120]!r}...")
        print(f"description_cln: {job.description_clean[:120]!r}...")
        print()

    print("=== First job as JSON (for field verification) ===")
    print(jobs[0].model_dump_json(indent=2))


if __name__ == "__main__":
    main()
