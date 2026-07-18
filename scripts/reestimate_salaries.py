#!/usr/bin/env python3
"""Re-run ONLY the salary estimate on the last fetch batch — no scraping, no other fields.

This applies the v6 Hays-anchored salary calibration (see hk_jobs/enrichers/deepseek.py and
salary_guidlines/hk_salary_anchors.json) to jobs that were already scraped, WITHOUT fetching
anything new. It calls DeepSeek per job but writes back ONLY salary_estimated_min / _max /
_confidence — seniority, skills, description_summary and title_en are left exactly as they are.

Scope: active jobs whose DATE(fetched_at) equals the most recent fetch date in the DB
(i.e. the last scrape run). Override with --date YYYY-MM-DD if you need a specific run.

Safe by default: a bare run is a DRY RUN (counts + current stats, no API calls, no writes).
Add --apply to actually call DeepSeek and update the DB. Needs DEEPSEEK_API_KEY.

Examples:
    python scripts/reestimate_salaries.py                 # dry run: show batch + current stats
    export DEEPSEEK_API_KEY=...
    python scripts/reestimate_salaries.py --apply         # do it (last fetch batch)
    python scripts/reestimate_salaries.py --apply --limit 50   # try 50 first
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import statistics as st
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hk_jobs.enrichers.deepseek import DeepSeekEnricher  # noqa: E402
from hk_jobs.enrichment import _coerce_int, _norm_confidence  # noqa: E402
from hk_jobs.salary_clamp import clamp_salary  # noqa: E402


def _stats(vals: list[int]) -> str:
    if not vals:
        return "(none)"
    s = sorted(vals)
    p90 = s[min(len(s) - 1, int(len(s) * 0.9))]
    return f"n={len(s)} median={int(st.median(s)):,} mean={int(st.mean(s)):,} p90={p90:,} max={max(s):,}"


def _est_max_vals(conn: sqlite3.Connection, date: str | None) -> list[int]:
    """est_max for the scope: a single fetch date, or all active jobs when date is None."""
    where = "AND DATE(j.fetched_at) = ?" if date else ""
    params = (date,) if date else ()
    rows = conn.execute(
        f"""SELECT e.salary_estimated_max
             FROM jobs j JOIN job_enrichments e
               ON j.source = e.source AND j.source_id = e.source_id
            WHERE j.is_active = 1 AND e.salary_estimated_max IS NOT NULL {where}""",
        params,
    ).fetchall()
    return [r[0] for r in rows]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="data/jobs.db")
    ap.add_argument("--date", default=None, help="fetch date YYYY-MM-DD (default: latest in DB)")
    ap.add_argument("--workers", type=int, default=20)
    ap.add_argument("--limit", type=int, default=None, help="cap number of jobs (for a trial run)")
    ap.add_argument("--apply", action="store_true", help="actually call DeepSeek and write (else dry run)")
    ap.add_argument("--no-backup", action="store_true", help="skip the pre-write DB snapshot")
    ap.add_argument("--fresh", action="store_true",
                    help="ignore any resume progress file and re-do the whole batch")
    ap.add_argument("--all-active", action="store_true",
                    help="re-estimate ALL active jobs (whole board), not just one fetch date")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    if args.all_active:
        scope_date = None  # stats over all active jobs
        scope_key = "all"
        rows = conn.execute(
            """SELECT j.source, j.source_id, j.title, j.company, j.description_clean
                 FROM jobs j JOIN job_enrichments e
                   ON j.source = e.source AND j.source_id = e.source_id
                WHERE j.is_active = 1
                ORDER BY j.fetched_at DESC""",
        ).fetchall()
    else:
        scope_date = args.date or conn.execute("SELECT MAX(DATE(fetched_at)) FROM jobs").fetchone()[0]
        scope_key = scope_date
        rows = conn.execute(
            """SELECT j.source, j.source_id, j.title, j.company, j.description_clean
                 FROM jobs j JOIN job_enrichments e
                   ON j.source = e.source AND j.source_id = e.source_id
                WHERE DATE(j.fetched_at) = ? AND j.is_active = 1
                ORDER BY j.fetched_at DESC""",
            (scope_date,),
        ).fetchall()
    if args.limit:
        rows = rows[: args.limit]

    total_in_batch = len(rows)

    # Resume support: a progress file records which (source, source_id) already got the
    # new estimate, so a run interrupted by a network drop can be re-run and only does
    # the remainder. Keyed by scope; deleted once the batch is fully done.
    progress_path = Path(args.db).parent / "snapshots" / f".reestimate_done_{scope_key}.txt"
    done: set[str] = set()
    if progress_path.exists() and not args.fresh:
        # Each line is "source\tsource_id" — split on LINES, not all whitespace, or the
        # tab inside each key gets torn apart and nothing matches (resume silently re-does all).
        done = {ln for ln in progress_path.read_text(encoding="utf-8").splitlines() if ln.strip()}
        rows = [r for r in rows if f'{r["source"]}\t{r["source_id"]}' not in done]

    print(f"Scope: {'ALL active jobs' if args.all_active else 'fetch date ' + str(scope_date)}")
    print(f"Batch (active, already-enriched): {total_in_batch} jobs")
    if done:
        print(f"Resuming: {len(done)} already done, {len(rows)} remaining.")
    print(f"BEFORE — salary_estimated_max: {_stats(_est_max_vals(conn, scope_date))}")

    if not args.apply:
        print("\nDRY RUN — no API calls, no writes. Re-run with --apply to execute.")
        print(f"This will make ~{len(rows)} DeepSeek calls and update ONLY the 3 salary columns.")
        conn.close()
        return

    if not rows:
        print("\nNothing left to do — batch already complete.")
        progress_path.unlink(missing_ok=True)
        conn.close()
        return

    enr = DeepSeekEnricher()  # raises if DEEPSEEK_API_KEY unset

    if not args.no_backup:
        snap_dir = Path(args.db).parent / "snapshots"
        snap_dir.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        dst = snap_dir / f"{Path(args.db).name}.pre-salary-reestimate-{ts}"
        shutil.copy2(args.db, dst)
        print(f"Backup: {dst}")

    print(f"Calling DeepSeek on {len(rows)} jobs (workers={args.workers}) — salary only …")
    updated = failed = 0
    BATCH = 100
    for start in range(0, len(rows), BATCH):
        chunk = rows[start : start + BATCH]
        results: dict[tuple[str, str], dict | None] = {}
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            fut = {
                pool.submit(enr._enrich_with_retry, r["title"], r["company"], r["description_clean"] or ""): r
                for r in chunk
            }
            for f in as_completed(fut):
                r = fut[f]
                try:
                    results[(r["source"], r["source_id"])] = f.result()
                except Exception:
                    results[(r["source"], r["source_id"])] = None

        chunk_done: list[str] = []
        with conn:
            for r in chunk:
                data = results.get((r["source"], r["source_id"]))
                if not data:
                    failed += 1
                    continue
                est_min, est_max = clamp_salary(
                    data.get("salary_tier"), data.get("seniority"),
                    _coerce_int(data.get("salary_estimated_min")),
                    _coerce_int(data.get("salary_estimated_max")),
                )
                conn.execute(
                    """UPDATE job_enrichments
                          SET salary_estimated_min = ?,
                              salary_estimated_max = ?,
                              salary_estimated_confidence = ?
                        WHERE source = ? AND source_id = ?""",
                    (
                        est_min,
                        est_max,
                        _norm_confidence(data.get("salary_estimated_confidence")),
                        r["source"], r["source_id"],
                    ),
                )
                updated += 1
                chunk_done.append(f'{r["source"]}\t{r["source_id"]}')
        # Record progress only AFTER the chunk's writes committed, so an interrupted
        # run never marks an unwritten job as done.
        if chunk_done:
            with progress_path.open("a", encoding="utf-8") as fh:
                fh.write("\n".join(chunk_done) + "\n")
        print(f"  … {min(start + BATCH, len(rows))}/{len(rows)}  (updated={updated} failed={failed})")

    print(f"\nDone: {updated} salary estimates updated, {failed} failed.")
    print(f"AFTER  — salary_estimated_max: {_stats(_est_max_vals(conn, scope_date))}")
    # Clear the resume file only if the whole batch is now covered (no failures left behind).
    if failed == 0 and len(done) + updated >= total_in_batch:
        progress_path.unlink(missing_ok=True)
        print("Batch fully complete — resume file cleared.")
    else:
        print(f"Resume file kept ({progress_path.name}); re-run to finish the remaining {failed} failed / skipped.")
    conn.close()


if __name__ == "__main__":
    main()
