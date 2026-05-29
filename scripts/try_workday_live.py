"""
Live smoke-test for the Workday adapter.

Run this LOCALLY (not in CI) to verify that the real Workday API returns
data in the shape our adapter expects. The script fetches the first 3 jobs
from one tenant and prints their field mapping so you can spot mismatches.

Usage:
    python scripts/try_workday_live.py
    python scripts/try_workday_live.py --tenant hsbc --site External --wd wd3

The sandbox that runs automated tests may block outbound HTTPS — that is
fine; this script is meant to be run by a human to validate assumptions.
"""

import argparse
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

from hk_jobs.adapters.workday import WorkdayAdapter  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Live Workday adapter smoke-test")
    parser.add_argument("--tenant", default="aia", help="Workday tenant slug (default: aia)")
    parser.add_argument("--site", default="External", help="Workday site name (default: External)")
    parser.add_argument("--wd", default="wd3", help="Platform subdomain (default: wd3)")
    parser.add_argument("--no-details", action="store_true", help="Skip detail calls")
    args = parser.parse_args()

    print(f"\nFetching jobs from  https://{args.tenant}.{args.wd}.myworkdayjobs.com")
    print(f"Site: {args.site}   fetch_details: {not args.no_details}\n")

    adapter = WorkdayAdapter(
        company="LiveTest",
        company_slug="live-test",
        tenant=args.tenant,
        site=args.site,
        wd=args.wd,
        fetch_details=not args.no_details,
    )

    jobs = adapter.fetch_jobs()

    if not jobs:
        print("No jobs returned — check tenant/site/wd or whether the endpoint is reachable.")
        return

    print(f"Total jobs fetched: {len(jobs)}")
    print("-" * 60)

    for job in jobs[:3]:
        print(f"title          : {job.title}")
        print(f"source_id      : {job.source_id}")
        print(f"url            : {job.url}")
        print(f"locations      : {job.locations}")
        print(f"employment_type: {job.employment_type}")
        print(f"posted_at      : {job.posted_at}")
        print(f"description_raw: {job.description_raw[:120]!r}...")
        print(f"description_cln: {job.description_clean[:120]!r}...")
        print()

    # Dump the raw first job as JSON so we can inspect unmapped fields
    print("=== First job as JSON (for field verification) ===")
    print(jobs[0].model_dump_json(indent=2))


if __name__ == "__main__":
    main()
