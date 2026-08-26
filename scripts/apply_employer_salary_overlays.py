#!/usr/bin/env python3
"""Apply documented employer salary overlays to existing, unpinned board rows.

The salary clamp corrects every future enrichment. Existing rows do not pass
through it again unless they are re-enriched, and spending model calls just to
apply an exact employer-and-title rule would be wasteful. This script is the
safe bridge: it touches only rows that match a configured overlay and leaves
Ultimate Admin corrections alone.

Run without ``--apply`` to inspect the precise rows and changes. ``--apply``
creates a timestamped database backup unless ``--no-backup`` is supplied.
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hk_jobs.salary_clamp import clamp_salary, employer_salary_overlay  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="data/jobs.db", help="SQLite board database")
    parser.add_argument("--company-slug", help="limit the backfill to one employer slug")
    parser.add_argument("--apply", action="store_true", help="write the listed corrections")
    parser.add_argument("--no-backup", action="store_true", help="do not copy the database first")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    employer_filter = "AND j.company_slug = ?" if args.company_slug else ""
    rows = conn.execute(
        f"""
        SELECT j.source, j.source_id, j.company, j.company_slug, j.title, j.source_tier,
               e.salary_estimated_min AS old_min, e.salary_estimated_max AS old_max,
               e.manually_edited_at AS pinned_at
          FROM jobs AS j
          JOIN job_enrichments AS e
            ON e.source = j.source AND e.source_id = j.source_id
         WHERE j.is_active = 1 AND e.salary_estimated_max IS NOT NULL
           {employer_filter}
        """
        , (args.company_slug,) if args.company_slug else (),
    ).fetchall()

    changes: list[tuple[sqlite3.Row, int, int, str]] = []
    pinned: list[sqlite3.Row] = []
    for row in rows:
        overlay = employer_salary_overlay(row["company_slug"], row["title"])
        if overlay is None:
            continue
        if row["pinned_at"] is not None:
            pinned.append(row)
            continue
        new_min, new_max = clamp_salary(
            None,
            None,
            row["old_min"],
            row["old_max"],
            company_slug=row["company_slug"],
            title=row["title"],
            source_tier=row["source_tier"],
        )
        if new_min is None or new_max is None:
            raise RuntimeError(f"Overlay produced no salary for {row['source']}/{row['source_id']}")
        if (new_min, new_max) != (row["old_min"], row["old_max"]):
            changes.append((row, new_min, new_max, overlay[2]))

    print(f"Active estimated roles: {len(rows)}")
    print(f"Overlay corrections: {len(changes)}")
    print(f"Pinned matches skipped: {len(pinned)}")
    for row, new_min, new_max, key in changes:
        print(
            f"  {row['old_min']:,}-{row['old_max']:,} -> {new_min:,}-{new_max:,} "
            f"[{key}] {row['title']} @ {row['company']}"
        )

    if not args.apply:
        print("DRY RUN — no writes. Re-run with --apply to apply these corrections.")
        conn.close()
        return

    if not args.no_backup:
        database = Path(args.db)
        backup_dir = database.parent / "snapshots"
        backup_dir.mkdir(exist_ok=True)
        backup = backup_dir / f"{database.name}.pre-employer-overlays-{datetime.now():%Y%m%d-%H%M%S}"
        shutil.copy2(database, backup)
        print(f"Backup: {backup}")

    with conn:
        for row, new_min, new_max, _ in changes:
            conn.execute(
                """
                UPDATE job_enrichments
                   SET salary_estimated_min = ?, salary_estimated_max = ?
                 WHERE source = ? AND source_id = ?
                """,
                (new_min, new_max, row["source"], row["source_id"]),
            )
    print(f"Applied {len(changes)} employer-overlay corrections.")
    conn.close()


if __name__ == "__main__":
    main()
