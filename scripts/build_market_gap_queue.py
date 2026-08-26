#!/usr/bin/env python3
"""Build a review queue for anchor cells that require independent market evidence.

The queue never changes salary anchors. It combines the provenance ledger with
active primary-listing demand so market research begins where a weak cell affects
the most Roles. A missing model grade is handled honestly: role-level usage raises
priority, while exact-grade usage remains a separate field.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PROVENANCE_PATH = ROOT / "salary_guidlines" / "hk_salary_anchor_provenance.json"
OUTPUT_PATH = ROOT / "salary_guidlines" / "market_gap_queue.json"
DEFAULT_DB = ROOT / "data" / "jobs.db"


def _priority(role_active: int) -> str:
    if role_active >= 25:
        return "critical"
    if role_active >= 10:
        return "high"
    if role_active >= 3:
        return "medium"
    return "low"


def usage_by_role(db_path: Path) -> dict[tuple[str, str], dict[str, int]]:
    """Count active primary listings by inferred role and, separately, exact grade."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """SELECT e.salary_tier, e.salary_role, e.salary_grade, COUNT(*) AS n
                 FROM jobs j JOIN job_enrichments e
                   ON j.source=e.source AND j.source_id=e.source_id
                WHERE j.is_active=1 AND j.is_primary=1
                  AND e.salary_tier IS NOT NULL AND e.salary_role IS NOT NULL
                GROUP BY e.salary_tier, e.salary_role, e.salary_grade"""
        ).fetchall()
    finally:
        conn.close()
    usage: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: {"role_active": 0, "exact_active": 0}
    )
    for row in rows:
        key = (row["salary_tier"], row["salary_role"])
        usage[key]["role_active"] += row["n"]
        if row["salary_grade"]:
            usage[key]["exact_active"] += row["n"]
    return dict(usage)


def build_queue(
    provenance: dict[str, Any], usage: dict[tuple[str, str], dict[str, int]]
) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for coordinate, cell in provenance.get("cells", {}).items():
        if not cell.get("requires_market_evidence"):
            continue
        tier, role, grade = coordinate.split("/", 2)
        counts = usage.get((tier, role), {"role_active": 0, "exact_active": 0})
        entries.append(
            {
                "coordinate": coordinate,
                "tier": tier,
                "role": role,
                "grade": grade,
                "current_band_monthly_hkd": cell["band_monthly_hkd"],
                "market_gap_reason": cell["market_gap_reason"],
                "semantic_status": cell["semantic_status"],
                "role_active_primary_listings": counts["role_active"],
                "exact_grade_active_primary_listings": counts["exact_active"],
                "priority": _priority(counts["role_active"]),
            }
        )
    rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    entries.sort(
        key=lambda row: (
            rank[row["priority"]],
            -row["role_active_primary_listings"],
            row["coordinate"],
        )
    )
    counts = Counter(row["priority"] for row in entries)
    return {
        "schema_version": 1,
        "description": (
            "Priority queue for independently sourced replacement evidence. Current bands "
            "remain unchanged until market evidence is reviewed and an explicit overlay is added."
        ),
        "summary": {
            "market_gaps": len(entries),
            "critical": counts["critical"],
            "high": counts["high"],
            "medium": counts["medium"],
            "low": counts["low"],
        },
        "entries": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    provenance = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    queue = build_queue(provenance, usage_by_role(args.db))
    rendered = json.dumps(queue, indent=2, ensure_ascii=False) + "\n"
    if args.check:
        if not OUTPUT_PATH.exists() or OUTPUT_PATH.read_text(encoding="utf-8") != rendered:
            print("Market-gap queue is stale. Run scripts/build_market_gap_queue.py.")
            return 1
        print(f"Market-gap queue is current ({queue['summary']['market_gaps']} gaps).")
        return 0
    OUTPUT_PATH.write_text(rendered, encoding="utf-8")
    print("Market-gap queue:", ", ".join(f"{key}={value}" for key, value in queue["summary"].items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
