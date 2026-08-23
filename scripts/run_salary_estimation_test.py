"""Run a bounded, separate-file salary-estimation evaluation.

Usage:
    python scripts/run_salary_estimation_test.py --prepare
    DEEPSEEK_API_KEY=... python scripts/run_salary_estimation_test.py --run pilot_400

It never writes production salary columns.  The manifest freezes the source
identities before the first call, making the 400/600 pause meaningful.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hk_jobs.ai_budget import BudgetExceeded, RunBudget  # noqa: E402
from hk_jobs.enrichers.deepseek import _MODEL, PROMPT_VERSION, DeepSeekEnricher  # noqa: E402
from hk_jobs.salary_evaluation import (  # noqa: E402
    build_cohort,
    eligible_roles,
    prior_sample_keys,
)

DEFAULT_DB = ROOT / "data" / "jobs.db"
DEFAULT_AUDIT = ROOT / "docs" / "salary_audit_2026-08-18" / "sample_truth.json"
DEFAULT_DIR = ROOT / "data" / "salary_evaluation_2026-08-22"
SEED = "salary-evaluation-20260822"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def prepare(args: argparse.Namespace) -> Path:
    manifest = args.output_dir / "manifest.json"
    if manifest.exists():
        raise SystemExit(f"Refusing to replace existing frozen cohort: {manifest}")
    prior = prior_sample_keys(args.prior_sample)
    candidates = eligible_roles(
        str(args.db), prior_keys=prior, recent_days=args.recent_days,
        min_description_chars=args.min_description_chars,
    )
    cohort = build_cohort(candidates, target=1_000, seed=SEED)
    batches = {
        name: sum(row["batch"] == name for row in cohort)
        for name in ("pilot_400", "continuation_600")
    }
    payload = {
        "created_at": datetime.now(UTC).isoformat(),
        "purpose": "Separate-file DeepSeek salary-estimation evaluation; never writes jobs.db.",
        "seed": SEED,
        "model": _MODEL,
        "prompt_version": PROMPT_VERSION,
        "selection": {
            "recent_days": args.recent_days,
            "minimum_description_characters": args.min_description_chars,
            "required": [
                "active listing", "primary listing", "existing baseline estimate",
                "manually_edited_at is null", "not in prior 150-role audit",
            ],
            "eligible_candidates": len(candidates),
            "excluded_prior_audit_roles": len(prior),
        },
        "batches": batches,
        "roles": cohort,
    }
    _write_json(manifest, payload)
    print(f"Frozen {len(cohort)} roles from {len(candidates)} eligible candidates: {batches}.")
    return manifest


def run_batch(args: argparse.Namespace) -> None:
    manifest_path = args.output_dir / "manifest.json"
    if not manifest_path.exists():
        raise SystemExit("No manifest. Run with --prepare before purchasing any calls.")
    if not os.environ.get("DEEPSEEK_API_KEY", "").strip():
        raise SystemExit(
            "DEEPSEEK_API_KEY is required and must be supplied through the environment."
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    roles = [row for row in manifest["roles"] if row["batch"] == args.run]
    result_path = args.output_dir / f"{args.run}_results.jsonl"
    if result_path.exists():
        raise SystemExit(f"Refusing to append to an existing result file: {result_path}")
    cap = 3.50 if args.run == "pilot_400" else 4.75
    enricher = DeepSeekEnricher(run_budget=RunBudget(limit_usd=cap))
    stopped = False

    def one(row: dict[str, Any]) -> dict[str, Any]:
        try:
            result = enricher.enrich_single(
                row["title"], company=row["company"], description=row["description_clean"],
                seniority=row["seniority"],
            )
            return {
                "source": row["source"], "source_id": row["source_id"],
                "status": "ok", "result": result,
            }
        except BudgetExceeded as exc:
            return {
                "source": row["source"], "source_id": row["source_id"],
                "status": "budget_stopped", "error": str(exc),
            }
        except Exception as exc:  # Records evidence; the live rows remain untouched.
            return {
                "source": row["source"], "source_id": row["source_id"],
                "status": "error", "error": f"{type(exc).__name__}: {exc}",
            }

    with (
        result_path.open("x", encoding="utf-8") as output,
        ThreadPoolExecutor(max_workers=args.workers) as pool,
    ):
        futures = {pool.submit(one, row): row for row in roles}
        for future in as_completed(futures):
            record = future.result()
            output.write(json.dumps(record, ensure_ascii=False) + "\n")
            output.flush()
            if record["status"] == "budget_stopped":
                stopped = True

    results = [json.loads(line) for line in result_path.read_text(encoding="utf-8").splitlines()]
    summary = {
        "batch": args.run,
        "attempted_roles": len(roles),
        "records": len(results),
        "by_status": {
            status: sum(row["status"] == status for row in results)
            for status in {row["status"] for row in results}
        },
        "budget_cap_usd": cap,
        "conservative_spend_usd": round(enricher.run_budget.spent_usd, 4),
        "usage_totals": enricher.usage_totals,
        "budget_stop_seen": stopped,
        "result_file": str(result_path),
    }
    _write_json(args.output_dir / f"{args.run}_checkpoint.json", summary)
    print(json.dumps(summary, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--run", choices=("pilot_400", "continuation_600"))
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--prior-sample", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--recent-days", type=int, default=21)
    parser.add_argument("--min-description-chars", type=int, default=500)
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    if args.prepare == (args.run is not None):
        parser.error("choose exactly one of --prepare or --run")
    if args.prepare:
        prepare(args)
    else:
        run_batch(args)


if __name__ == "__main__":
    main()
