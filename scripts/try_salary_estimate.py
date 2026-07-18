#!/usr/bin/env python3
"""Sanity-check the v6 Hays-anchored salary estimator (run locally — needs DEEPSEEK_API_KEY).

Runs a handful of roles that the old estimator tended to over-price, plus any titles you pass
on the command line, and prints the estimated monthly HK$ band next to the Hays reference band
for that role's tier/level so you can see whether the estimate now sits inside the anchors.

Usage:
    export DEEPSEEK_API_KEY=...
    python scripts/try_salary_estimate.py
    python scripts/try_salary_estimate.py "Compliance Manager" "HSBC"
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hk_jobs.enrichers.deepseek import DeepSeekEnricher, _SALARY_REFERENCE  # noqa: E402

# (title, company, description) — control/ops/senior roles are where inflation showed up.
SAMPLES = [
    ("Vice President, Compliance", "Standard Chartered", ""),
    ("Senior Manager, Internal Audit", "AIA", ""),
    ("Relationship Manager, Commercial Banking", "Hang Seng Bank", ""),
    ("Treasury Operations Officer", "Bank of China (Hong Kong)", ""),
    ("Managing Director, M&A", "Goldman Sachs", ""),
    ("KYC Analyst", "Citi", ""),
    ("Fund Manager", "BlackRock", ""),
    ("Actuarial Manager", "Prudential", ""),
]


def main() -> None:
    args = sys.argv[1:]
    samples = [(args[0], args[1] if len(args) > 1 else "", "")] if args else SAMPLES

    print("Reference ladders now in the prompt:\n")
    print(_SALARY_REFERENCE)
    print("\n" + "=" * 78)

    enr = DeepSeekEnricher()
    for title, company, desc in samples:
        try:
            r = enr.enrich_single(title, company=company, description=desc)
            lo, hi = r.get("salary_estimated_min"), r.get("salary_estimated_max")
            band = f"{lo:,} - {hi:,} HK$/mo" if (lo and hi) else f"{lo} - {hi}"
            print(
                f"\n{title}  @ {company or '(n/a)'}\n"
                f"  seniority={r.get('seniority')}  "
                f"conf={r.get('salary_estimated_confidence')}\n"
                f"  estimate: {band}"
            )
        except Exception as exc:  # noqa: BLE001
            print(f"\n{title} @ {company}: ERROR {exc}")


if __name__ == "__main__":
    main()
