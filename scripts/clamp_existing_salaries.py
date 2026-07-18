#!/usr/bin/env python3
"""Apply the deterministic salary clamp to EXISTING estimates — no DeepSeek calls.

The precise clamp (hk_jobs.salary_clamp) needs the function tier the model chose, but rows
enriched before the v7 `salary_tier` field don't have one stored. This backfill infers the
tier deterministically from the stored title + job_category, then clips the estimate DOWN to
that (tier, seniority) Hays band — purely in Python, zero API cost.

SAFETY — permissive fallback. We only assign a *lower* tier when the title clearly signals one
(operations / settlement / teller / compliance / audit / …). Anything ambiguous falls back to
`front_office` (the highest ceiling), so a genuine high-paying role can never be wrongly capped.
The clamp itself is down-only. Net effect: clearly-lower-tier over-estimates get tightened,
everything else is left as-is.

Bare run = DRY RUN (counts + examples, no writes). Add --apply to write. Backs up first.
"""
from __future__ import annotations

import argparse
import re
import shutil
import sqlite3
import statistics as st
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hk_jobs.salary_clamp import clamp_salary  # noqa: E402

# Ordered high-paying → low-paying. First match wins, so when a title carries signals for
# two tiers the HIGHER one is chosen — which means we never cap a role more than its strongest
# high-tier signal allows. Unmatched titles fall through to the permissive front_office default.
_TIER_RULES: list[tuple[str, str]] = [
    ("front_office", r"invest(ment)? bank|\bm&a\b|merger|\becm\b|\bdcm\b|capital market|private equity|\bpe\b|hedge fund|portfolio manager|fund manager|\btrader\b|trading|global market|fixed income|equities|structuring|derivatives trad|sell.?side|buy.?side|\bquant|private bank"),
    ("commercial_corporate_banking", r"relationship manager|corporate banking|commercial banking|\bsme\b|transaction banking|wealth manager|\brm\b|coverage banker"),
    ("corporate_finance_accounting", r"financial controller|fp&a|finance manager|management accountant|financial accountant|\btax\b|treasury manager|\bcfo\b|finance director|financial planning"),
    ("middle_office", r"\brisk\b|compliance|\baudit|internal control|product control|\baml\b|\bkyc\b analyst|credit analyst|surveillance|monitoring"),
    ("insurance", r"actuar|underwrit|\bclaims\b|bancassurance|\bagency\b|policy admin|\binsurance\b|reinsurance"),
    ("retail_banking", r"\bbranch\b|\bteller\b|retail banking|mortgage|premier banking|counter service"),
    ("back_office_operations", r"operation|settlement|reconciliation|custody|fund administ|\bpayment|clearing|documentation|onboarding|back.?office|trade support|loan admin|facilit|interior design|administrative"),
]
_COMPILED = [(tier, re.compile(rx, re.I)) for tier, rx in _TIER_RULES]


def infer_tier(title: str, category: str | None) -> str:
    """Deterministic, permissive tier guess. Defaults to front_office (highest ceiling)."""
    text = f"{title or ''} {category or ''}"
    for tier, rx in _COMPILED:
        if rx.search(text):
            return tier
    return "front_office"  # permissive: unknown → no meaningful cap (only >front-office is trimmed)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="data/jobs.db")
    ap.add_argument("--apply", action="store_true", help="write changes (else dry run)")
    ap.add_argument("--no-backup", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT j.title, j.company, e.source, e.source_id, e.seniority, e.job_category,
                  e.salary_estimated_min AS mn, e.salary_estimated_max AS mx
             FROM jobs j JOIN job_enrichments e
               ON j.source = e.source AND j.source_id = e.source_id
            WHERE j.is_active = 1 AND e.salary_estimated_max IS NOT NULL""",
    ).fetchall()

    changes = []  # (row, new_min, new_max, tier)
    for r in rows:
        tier = infer_tier(r["title"], r["job_category"])
        nmin, nmax = clamp_salary(tier, r["seniority"], r["mn"], r["mx"])
        if nmax != r["mx"] or nmin != r["mn"]:
            changes.append((r, nmin, nmax, tier))

    before = [r["mx"] for r in rows]
    chg_map = {(r["source"], r["source_id"]): (nm, nx) for r, nm, nx, _ in changes}
    after = [chg_map.get((r["source"], r["source_id"]), (r["mn"], r["mx"]))[1] for r in rows]

    def stats(v):
        s = sorted(v)
        return f"median={int(st.median(s)):,} mean={int(st.mean(s)):,} p90={s[int(len(s)*0.9)]:,} max={max(s):,}"

    print(f"Active jobs with an estimate: {len(rows)}")
    print(f"Would change: {len(changes)} rows")
    print(f"BEFORE est_max: {stats(before)}")
    print(f"AFTER  est_max: {stats(after)}")
    print("\nBiggest reductions (old -> new est_max, inferred tier):")
    for r, nm, nx, tier in sorted(changes, key=lambda c: c[0]["mx"] - c[2], reverse=True)[:15]:
        print(f"  {r['mx']:>7,} -> {nx:>7,}  [{tier:26} {r['seniority'] or '?':6}]  {r['title'][:44]} @ {r['company'][:18]}")

    if not args.apply:
        print("\nDRY RUN — no writes. Re-run with --apply to commit.")
        conn.close()
        return

    if not args.no_backup:
        snap = Path(args.db).parent / "snapshots"
        snap.mkdir(exist_ok=True)
        dst = snap / f"{Path(args.db).name}.pre-clamp-{datetime.now():%Y%m%d-%H%M%S}"
        shutil.copy2(args.db, dst)
        print(f"\nBackup: {dst}")

    with conn:
        for r, nm, nx, _ in changes:
            conn.execute(
                "UPDATE job_enrichments SET salary_estimated_min=?, salary_estimated_max=? "
                "WHERE source=? AND source_id=?",
                (nm, nx, r["source"], r["source_id"]),
            )
    print(f"Applied clamp to {len(changes)} rows.")
    conn.close()


if __name__ == "__main__":
    main()
