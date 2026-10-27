#!/usr/bin/env python3
"""Re-estimate a frozen disclosed-pay cohort with all pay copy removed.

Only blinded_title and blinded_description are sent to the model. The truth
columns stay in the local input artifact for scoring after prediction.
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hk_jobs import salary
from hk_jobs.ai_budget import RunBudget
from hk_jobs.enrichers.deepseek import DeepSeekEnricher
from hk_jobs.salary_clamp import normalise_coordinate
from hk_jobs.salary_corrections import Correction


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cohort", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--budget-usd", type=float, default=1.50)
    parser.add_argument("--corrections", type=Path)
    args = parser.parse_args()
    cohort = [json.loads(line) for line in args.cohort.read_text().splitlines() if line]
    results = {}
    if args.output.exists():
        results = {row["key"]: row for row in map(json.loads, args.output.read_text().splitlines())}
    pending = [row for row in cohort if row["key"] not in results]
    corrections = []
    if args.corrections:
        corrections = [
            Correction(**record)
            for record in map(json.loads, args.corrections.read_text().splitlines())
            if record["new_min"] is not None or record["new_max"] is not None
        ]
    enricher = DeepSeekEnricher(
        run_budget=RunBudget(limit_usd=args.budget_usd), salary_corrections=corrections,
    )

    def estimate(row: dict) -> dict:
        data = enricher.enrich_single(
            title=row["blinded_title"],
            company=row["company_label"],
            description=row["blinded_description"],
        )
        tier, role, grade = normalise_coordinate(
            data.get("salary_tier"), data.get("salary_role"), data.get("salary_grade")
        )
        low, high = salary.finalise(
            None, None,
            tier=tier, seniority=data.get("seniority"), role=role, grade=grade,
            title=row["blinded_title"],
            source_tier="social" if row["source"] == "linkedin_posts" else "mainstream",
            coordinate_only=True,
        )
        return {
            "key": row["key"], "source": row["source"],
            "truth_min": row["truth_min"], "truth_max": row["truth_max"],
            "estimate_min": low, "estimate_max": high,
            "tier": tier, "role": role, "grade": grade,
            "confidence": data.get("salary_estimated_confidence"),
            "truth_independent": True, "prediction_blinded": True,
        }

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(estimate, row): row for row in pending}
        for future in as_completed(futures):
            row = futures[future]
            try:
                results[row["key"]] = future.result()
            except Exception as exc:
                results[row["key"]] = {"key": row["key"], "error": str(exc)[:300]}
            args.output.write_text(
                "".join(json.dumps(results[r["key"]]) + "\n" for r in cohort if r["key"] in results)
            )
            print(f"{len(results)}/{len(cohort)} {row['key']} ${enricher.run_budget.spent_usd:.3f}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
