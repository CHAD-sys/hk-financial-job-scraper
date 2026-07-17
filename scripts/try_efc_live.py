"""
Live smoke-test for the eFinancialCareers adapter (JSON API).

⚠  LEGAL: hits eFinancialCareers' backend JSON API. Prototype/verification use
   only. See hk_jobs/adapters/efc.py for the full legal notice.

Unlike the bot-walled HTML site, the JSON API (job-search-api.efinancialcareers.com)
is reachable with a plain HTTP client — no Scrapling/browser needed. This script
fetches one employer's HK jobs and prints the first few, so you can confirm the
exact clientBrandNameFilter value and the mapping before enabling a company.

Usage:
    python scripts/try_efc_live.py --brand "Bank Of China (Hong Kong) Limited"
    python scripts/try_efc_live.py --employer "Man Group"        # brand defaults to employer
    python scripts/try_efc_live.py --brand "JPMorgan Chase & Co." --slug jpmorgan
"""

import argparse
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

from hk_jobs.adapters.efc import EfcAdapter  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description="Live eFinancialCareers JSON-API smoke-test")
    p.add_argument("--employer", default="Bank of China (Hong Kong) Limited", help="Employer name")
    p.add_argument("--brand", default=None, help="Exact clientBrandNameFilter (default: employer)")
    p.add_argument("--slug", default=None, help="company_slug (default: derived)")
    p.add_argument("--country", default="HK", help="countryCode2 (default: HK)")
    p.add_argument("--proxy", default=None, help="HTTP proxy URL, if needed")
    args = p.parse_args()

    slug = args.slug or args.employer.lower().replace(" ", "-")
    adapter = EfcAdapter(
        company=args.employer,
        company_slug=slug,
        efc_employer=args.employer,
        efc_brand=args.brand,
        country_code=args.country,
        proxy=args.proxy,
    )
    print(f"\nBrand filter: {adapter.efc_brand!r}   country={args.country}\n")

    jobs = adapter.fetch_jobs()
    print(f"Fetched {len(jobs)} jobs.")
    if not jobs:
        print("0 jobs — check the exact --brand value (resolve via the jobs/search API).")
        return
    print("-" * 60)
    for j in jobs[:5]:
        print(f"title    : {j.title}")
        print(f"source_id: {j.source_id}")
        print(f"url      : {j.url}")
        print(f"company  : {j.company}")
        print(f"location : {j.locations}  | type: {j.employment_type}  | posted: {j.posted_at}")
        print(f"desc     : {len(j.description_clean)} chars")
        print()


if __name__ == "__main__":
    main()
