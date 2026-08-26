#!/usr/bin/env python3
"""Score a frozen, independently verified HK salary holdout.

Usage:
    python scripts/evaluate_salary_holdout.py data/salary_holdout.jsonl

Every JSONL row needs estimated and truth monthly-HKD endpoints plus
``truth_independent: true``. Truth extracted from the same listing that supplied
the estimate is rejected: it measures extraction, not estimation quality.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hk_jobs.salary_evaluation import score_holdout  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("holdout", type=Path, help="JSONL rows with independent truth")
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.holdout.read_text(encoding="utf-8").splitlines() if line]
    invalid = [row.get("key", "<unknown>") for row in rows if row.get("truth_independent") is not True]
    if invalid:
        parser.error("truth_independent must be true for every holdout row: " + ", ".join(invalid[:5]))
    print(json.dumps(score_holdout(rows), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
