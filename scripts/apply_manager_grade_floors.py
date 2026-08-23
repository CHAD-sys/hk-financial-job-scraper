#!/usr/bin/env python3
"""Apply Morris's Manager-grade floor to existing, unpinned estimates.

Future enrichments use this rule inside ``clamp_salary``. Existing salary
estimates are already final, so this script applies only the new floor
transform—it does not re-run the full clamp and therefore cannot double-apply
the boutique multiplier or older ceilings. A more specific employer overlay is
left for ``apply_employer_salary_overlays.py`` and is reported as skipped here.

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

from hk_jobs.salary_clamp import (  # noqa: E402
    apply_manager_grade_floor,
    employer_salary_overlay,
    manager_grade_floor,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="data/jobs.db", help="SQLite board database")
    parser.add_argument("--apply", action="store_true", help="write the listed corrections")
    parser.add_argument("--no-backup", action="store_true", help="do not copy the database first")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT j.source, j.source_id, j.company, j.company_slug, j.title,
               e.seniority, e.salary_tier, e.salary_role,
               e.salary_estimated_min AS old_min, e.salary_estimated_max AS old_max,
               e.manually_edited_at AS pinned_at
          FROM jobs AS j
          JOIN job_enrichments AS e
            ON e.source = j.source AND e.source_id = j.source_id
         WHERE j.is_active = 1 AND e.salary_estimated_max IS NOT NULL
        """
    ).fetchall()

    changes: list[tuple[sqlite3.Row, int, int, str]] = []
    pinned: list[sqlite3.Row] = []
    specific_overlay: list[sqlite3.Row] = []
    for row in rows:
        if employer_salary_overlay(row["company_slug"], row["title"]) is not None:
            specific_overlay.append(row)
            continue
        floor_band = manager_grade_floor(
            row["salary_tier"], row["salary_role"], row["company_slug"], row["title"]
        )
        if floor_band is None:
            continue
        if row["pinned_at"] is not None:
            pinned.append(row)
            continue
        new_min, new_max = apply_manager_grade_floor(row["old_min"], row["old_max"], floor_band)
        if (new_min, new_max) != (row["old_min"], row["old_max"]):
            if new_min is None or new_max is None:
                raise RuntimeError(f"Manager floor produced no salary for {row['source']}/{row['source_id']}")
            changes.append((row, new_min, new_max, floor_band[2]))

    print(f"Active estimated roles: {len(rows)}")
    print(f"Manager-grade floor corrections: {len(changes)}")
    print(f"Pinned matches skipped: {len(pinned)}")
    print(f"Specific employer overlays deferred: {len(specific_overlay)}")
    for row, new_min, new_max, group in changes:
        print(
            f"  {row['old_min']:,}-{row['old_max']:,} -> {new_min:,}-{new_max:,} "
            f"[{group}] {row['title']} @ {row['company']}"
        )

    if not args.apply:
        print("DRY RUN — no writes. Re-run with --apply to apply these corrections.")
        conn.close()
        return

    if not args.no_backup:
        database = Path(args.db)
        backup_dir = database.parent / "snapshots"
        backup_dir.mkdir(exist_ok=True)
        backup = backup_dir / f"{database.name}.pre-manager-grade-floors-{datetime.now():%Y%m%d-%H%M%S}"
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
    print(f"Applied {len(changes)} Manager-grade floor corrections.")
    conn.close()


if __name__ == "__main__":
    main()
