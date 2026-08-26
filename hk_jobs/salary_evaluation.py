"""Reproducible, non-destructive cohorts for salary-estimator evaluations.

This module deliberately selects from a read-only view of ``jobs.db``.  An
evaluation must never write ``jobs`` or ``job_enrichments``: its output is an
evidence artifact, not a new production estimate.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any


def _metrics(rows: list[dict[str, Any]]) -> dict[str, int | float]:
    """Calculate interval and midpoint accuracy without choosing a fake point truth."""
    if not rows:
        return {
            "n": 0,
            "range_overlap_rate": 0.0,
            "truth_midpoint_covered_rate": 0.0,
            "midpoint_mae_hkd": 0,
            "midpoint_mape": 0.0,
            "mean_estimate_width_hkd": 0,
        }
    overlap = 0
    midpoint_covered = 0
    absolute_errors: list[float] = []
    percentage_errors: list[float] = []
    widths: list[int] = []
    for row in rows:
        estimate_min = int(row["estimate_min"])
        estimate_max = int(row["estimate_max"])
        truth_min = int(row["truth_min"])
        truth_max = int(row["truth_max"])
        if estimate_min > estimate_max or truth_min > truth_max:
            raise ValueError("Salary bands must be ascending")
        overlap += estimate_max >= truth_min and truth_max >= estimate_min
        truth_midpoint = (truth_min + truth_max) / 2
        estimate_midpoint = (estimate_min + estimate_max) / 2
        midpoint_covered += estimate_min <= truth_midpoint <= estimate_max
        absolute_errors.append(abs(estimate_midpoint - truth_midpoint))
        percentage_errors.append(abs(estimate_midpoint - truth_midpoint) / truth_midpoint)
        widths.append(estimate_max - estimate_min)
    total = len(rows)
    return {
        "n": total,
        "range_overlap_rate": round(overlap / total, 4),
        "truth_midpoint_covered_rate": round(midpoint_covered / total, 4),
        "midpoint_mae_hkd": round(sum(absolute_errors) / total),
        "midpoint_mape": round(sum(percentage_errors) / total, 4),
        "mean_estimate_width_hkd": round(sum(widths) / total),
    }


def score_holdout(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Score independently verified salary truth overall and by key market strata.

    Each row must carry estimated and independently verified truth endpoints in
    monthly HKD. The caller owns provenance validation; keeping this pure allows
    it to score a frozen JSON holdout as well as a future disclosed-salary feed.
    """
    required = {"estimate_min", "estimate_max", "truth_min", "truth_max"}
    if any(required - set(row) for row in rows):
        raise ValueError("Each holdout row needs estimated and truth endpoints")
    by_tier: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_cohort: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_tier[str(row.get("tier") or "unresolved")].append(row)
        by_cohort[str(row.get("cohort") or "unclassified")].append(row)
    return {
        "overall": _metrics(rows),
        "by_tier": {key: _metrics(value) for key, value in sorted(by_tier.items())},
        "by_cohort": {key: _metrics(value) for key, value in sorted(by_cohort.items())},
    }


def prior_sample_keys(path: Path) -> set[tuple[str, str]]:
    """Return the exact source identities used in the earlier 150-role audit."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        (str(row["source"]), str(row["source_id"]))
        for row in payload.get("sample", [])
    }


def _allocate(groups: dict[str, list[dict[str, Any]]], target: int) -> dict[str, int]:
    """Hamilton allocation: proportional quotas that add up to exactly target."""
    total = sum(len(rows) for rows in groups.values())
    if target > total:
        raise ValueError(f"Cannot select {target} roles from only {total} candidates.")
    exact = {key: target * len(rows) / total for key, rows in groups.items()}
    counts = {key: int(value) for key, value in exact.items()}
    remaining = target - sum(counts.values())
    for key in sorted(groups, key=lambda key: (-(exact[key] - counts[key]), key))[:remaining]:
        counts[key] += 1
    return counts


def eligible_roles(
    db_path: str,
    *,
    prior_keys: set[tuple[str, str]],
    recent_days: int = 21,
    min_description_chars: int = 500,
) -> list[dict[str, Any]]:
    """Load recent, active, primary, unpinned roles outside the earlier sample."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT j.source, j.source_id, j.title, j.company, j.company_slug,
                   j.description_clean, j.posted_at, j.fetched_at,
                   e.seniority, e.salary_tier, e.salary_role, e.salary_grade,
                   e.salary_estimated_min AS baseline_min,
                   e.salary_estimated_max AS baseline_max,
                   e.salary_estimated_confidence AS baseline_confidence
              FROM jobs AS j
              JOIN job_enrichments AS e
                ON e.source = j.source AND e.source_id = j.source_id
             WHERE j.is_active = 1
               AND j.is_primary = 1
               AND e.manually_edited_at IS NULL
               AND e.salary_estimated_max IS NOT NULL
               AND length(trim(j.description_clean)) >= ?
               AND datetime(COALESCE(NULLIF(j.posted_at, ''), j.fetched_at))
                   >= datetime('now', ?)
             ORDER BY j.source, j.source_id
            """,
            (min_description_chars, f"-{recent_days} days"),
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows if (row["source"], row["source_id"]) not in prior_keys]


def build_cohort(
    rows: list[dict[str, Any]], *, target: int, seed: str) -> list[dict[str, Any]]:
    """Choose a deterministic source-and-tier-balanced cohort, then split 40/60."""
    by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_source[row["source"]].append(row)
    source_quota = _allocate(by_source, target)

    selected: list[dict[str, Any]] = []
    for source, source_rows in by_source.items():
        by_tier: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in source_rows:
            by_tier[row["salary_tier"] or "unresolved"].append(row)
        tier_quota = _allocate(by_tier, source_quota[source])
        for tier, tier_rows in by_tier.items():
            ranked = sorted(
                tier_rows,
                key=lambda row: hashlib.sha256(
                    f"{seed}|{row['source']}|{row['source_id']}".encode("utf-8")
                ).hexdigest(),
            )
            selected.extend(ranked[:tier_quota[tier]])

    # The pilot is also representative: it receives ~40% of each source+tier stratum.
    by_stratum: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in selected:
        by_stratum[f"{row['source']}::{row['salary_tier'] or 'unresolved'}"].append(row)
    pilot_quota = _allocate(by_stratum, 400)
    pilot_keys: set[tuple[str, str]] = set()
    for stratum, stratum_rows in by_stratum.items():
        ranked = sorted(
            stratum_rows,
            key=lambda row: hashlib.sha256(
                f"pilot|{seed}|{row['source']}|{row['source_id']}".encode("utf-8")
            ).hexdigest(),
        )
        pilot_keys.update(
            (row["source"], row["source_id"])
            for row in ranked[:pilot_quota[stratum]]
        )

    cohort = []
    for row in selected:
        row = dict(row)
        row["batch"] = (
            "pilot_400"
            if (row["source"], row["source_id"]) in pilot_keys
            else "continuation_600"
        )
        cohort.append(row)
    return sorted(cohort, key=lambda row: (row["batch"], row["source"], row["source_id"]))
