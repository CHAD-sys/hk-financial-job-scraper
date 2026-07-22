#!/usr/bin/env python3
"""Retroactively apply the boutique-tier 70% salary discount to already-enriched rows.

hk_jobs.salary_clamp.clamp_salary() now scales salary_estimated_min/max down by
BOUTIQUE_SALARY_MULTIPLIER (0.7) for source_tier='boutique' jobs, but that only takes
effect on enrichment calls made *after* the code changed. Rows enriched before this (or
by an already-running backfill process that loaded the old code into memory) still carry
the un-discounted, mainstream-calibrated estimate.

This is a one-time, no-API-call fix: it re-reads each boutique job's ALREADY-STORED
salary_estimated_min/max (the post-clamp "big company equivalent" value) and multiplies
both endpoints by the same 0.7 factor, in place.

SAFETY: run this exactly once. It has no way to tell an un-discounted value from an
already-discounted one, so running it twice would double-discount. Bare run = DRY RUN
(counts + before/after examples, no writes). Add --apply to write. Backs up first.
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import statistics as st
from datetime import datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hk_jobs.salary_clamp import BOUTIQUE_SALARY_MULTIPLIER  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="data/jobs.db")
    ap.add_argument("--apply", action="store_true", help="write changes (else dry run)")
    ap.add_argument("--no-backup", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT j.company, j.title, e.source, e.source_id,
                  e.salary_estimated_min AS mn, e.salary_estimated_max AS mx
             FROM jobs j JOIN job_enrichments e
               ON j.source = e.source AND j.source_id = e.source_id
            WHERE j.is_active = 1 AND j.source_tier = 'boutique'
              AND (e.salary_estimated_min IS NOT NULL OR e.salary_estimated_max IS NOT NULL)""",
    ).fetchall()

    print(f"Boutique active jobs with an estimate: {len(rows)}")
    if not rows:
        return

    changes = []
    for r in rows:
        new_min = round(r["mn"] * BOUTIQUE_SALARY_MULTIPLIER) if r["mn"] is not None else None
        new_max = round(r["mx"] * BOUTIQUE_SALARY_MULTIPLIER) if r["mx"] is not None else None
        changes.append((r, new_min, new_max))

    maxes = [r["mx"] for r in rows if r["mx"] is not None]
    new_maxes = [c[2] for c in changes if c[2] is not None]

    def stats(v: list[int]) -> str:
        s = sorted(v)
        return f"median={int(st.median(s)):,} mean={int(st.mean(s)):,} max={max(s):,}"

    print(f"BEFORE est_max: {stats(maxes)}")
    print(f"AFTER  est_max: {stats(new_maxes)}")
    print("\nSample:")
    for r, nmn, nmx in changes[:10]:
        print(f"  {r['company']:<30} {r['title'][:40]:<40} {r['mn']}-{r['mx']} -> {nmn}-{nmx}")

    if not args.apply:
        print("\nDRY RUN — no changes written. Re-run with --apply to write.")
        return

    if not args.no_backup:
        dst = f"{args.db}.bak-boutique-discount-{datetime.now():%Y%m%d-%H%M%S}"
        shutil.copy2(args.db, dst)
        print(f"\nBackup: {dst}")

    with conn:
        for r, new_min, new_max in changes:
            conn.execute(
                """UPDATE job_enrichments
                      SET salary_estimated_min = ?, salary_estimated_max = ?
                    WHERE source = ? AND source_id = ?""",
                (new_min, new_max, r["source"], r["source_id"]),
            )
    print(f"Applied discount to {len(changes)} boutique rows.")


if __name__ == "__main__":
    main()
