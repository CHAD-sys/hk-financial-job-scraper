"""
Live smoke-test for the JobsDB fallback adapter.

⚠  LEGAL: This script scrapes hk.jobsdb.com, which violates their ToS.
   Run for prototype/verification purposes ONLY. Do not automate in production.
   See hk_jobs/adapters/jobsdb.py for the full legal notice.

Run this LOCALLY (not in CI) to confirm our HTML selectors work against
the live site. The script fetches one page of results for one company and
prints the first 3 jobs so you can spot any selector breakage.

Usage:
    python scripts/try_jobsdb_live.py
    python scripts/try_jobsdb_live.py --slug prudential --max-pages 1
"""

import argparse
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

from hk_jobs.adapters.jobsdb import JobsDBAdapter  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Live JobsDB adapter smoke-test")
    parser.add_argument(
        "--slug",
        default="bank-of-china-hong-kong",
        help="JobsDB company slug, e.g. 'prudential' (default: bank-of-china-hong-kong)",
    )
    parser.add_argument(
        "--company",
        default="Bank of China (HK)",
        help="Human-readable company name for display",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=1,
        help="Max listing pages to fetch (default: 1 to keep it quick)",
    )
    args = parser.parse_args()

    print(f"\nFetching jobs from  https://hk.jobsdb.com/{args.slug}-jobs")
    print(f"max_pages={args.max_pages}\n")

    adapter = JobsDBAdapter(
        company=args.company,
        company_slug=args.slug.replace("-", "_"),
        jobsdb_company_slug=args.slug,
        max_pages=args.max_pages,
    )

    jobs = adapter.fetch_jobs()

    if not jobs:
        print(
            "No jobs returned — the site may have challenged us (check logs) "
            "or the slug is wrong."
        )
        return

    print(f"Total jobs fetched: {len(jobs)}")
    print("-" * 60)

    for job in jobs[:3]:
        print(f"title          : {job.title}")
        print(f"source_id      : {job.source_id}")
        print(f"url            : {job.url}")
        print(f"locations      : {job.locations}")
        print(f"employment_type: {job.employment_type}")
        print(f"description_raw: {job.description_raw[:120]!r}...")
        print(f"description_cln: {job.description_clean[:120]!r}...")
        print()

    print("=== First job as JSON (for field verification) ===")
    print(jobs[0].model_dump_json(indent=2))


if __name__ == "__main__":
    main()
