"""
Sync SQLite (the source of truth) -> PocketBase (verification / presentation mirror).

Why this exists
---------------
The scraping + enrichment pipeline and the FastAPI API run on data/jobs.db — that is
the single source of truth. PocketBase is NOT part of the live app; it is a browsable,
shareable copy used to hand the data to a reviewer (e.g. a manager) via PocketBase's
admin UI. This script refreshes that copy so it never goes stale.

Direction is strictly ONE-WAY: jobs.db  ->  pocketbase/pb_data/data.db.
Nothing here ever writes back to jobs.db.

What it does
------------
1. Ensures the PocketBase `jobs` collection has the AI-enrichment fields the reviewer
   needs to verify (salary_estimated_*, title_en, description_summary, job_category),
   adding them to the collection if missing.
2. Upserts every active job (jobs LEFT JOIN job_enrichments) into the PB `jobs`
   collection, matched on (source, source_id) so existing PB record ids stay stable.
3. Deletes PB rows that are no longer active in SQLite, so the mirror stays clean.

Safety
------
- Refuses to run while PocketBase is serving (writing a live PB SQLite file can corrupt
  it). Stop PocketBase first.
- Reads jobs.db read-only.

Usage
-----
    # stop PocketBase first, then:
    python -m hk_jobs.sync_pocketbase
    python -m hk_jobs.sync_pocketbase --sqlite data/jobs.db --pb pocketbase/pb_data/data.db
    python -m hk_jobs.sync_pocketbase --all      # include soft-deleted (is_active=0) too
    python -m hk_jobs.sync_pocketbase --dry-run   # report only, write nothing
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import socket
import sqlite3
import string
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_SQLITE = "data/jobs.db"
_DEFAULT_PB = "pocketbase/pb_data/data.db"

# PB field name -> its source in SQLite. Fields whose PB name matches a `jobs`
# column are copied straight across (see _map_row); the entries below are the
# AI-enrichment extras that live in job_enrichments and must be added to PB.
_ENRICHMENT_FIELDS = {
    "salary_estimated_min": ("number", "e.salary_estimated_min"),
    "salary_estimated_max": ("number", "e.salary_estimated_max"),
    "salary_estimated_confidence": ("text", "e.salary_estimated_confidence"),
    "title_en": ("text", "e.title_en"),
    "description_summary": ("text", "e.description_summary"),
    "job_category": ("text", "e.job_category"),
}


def _pb_is_running(port: int = 8090) -> bool:
    """True if something is listening on the PocketBase port (don't write a live DB)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _field_def(name: str, kind: str) -> dict:
    """A PocketBase v0.2x field definition matching the format PB stores in _collections."""
    suffix = "".join(random.choices(string.digits, k=10))
    if kind == "number":
        return {
            "help": "", "hidden": False, "id": f"number{suffix}", "max": None,
            "min": None, "name": name, "onlyInt": False, "presentable": False,
            "required": False, "system": False, "type": "number",
        }
    return {
        "autogeneratePattern": "", "help": "", "hidden": False, "id": f"text{suffix}",
        "max": 0, "min": 0, "name": name, "pattern": "", "presentable": False,
        "primaryKey": False, "required": False, "system": False, "type": "text",
    }


def _ensure_pb_fields(pb: sqlite3.Connection, dry_run: bool) -> list[str]:
    """Add any missing enrichment columns to the PB `jobs` table + collection schema."""
    existing = {r[1] for r in pb.execute("PRAGMA table_info(jobs)")}
    row = pb.execute("SELECT fields FROM _collections WHERE name='jobs'").fetchone()
    if row is None:
        raise SystemExit("PocketBase has no `jobs` collection — nothing to sync into.")
    fields = json.loads(row[0])
    field_names = {f.get("name") for f in fields}

    added: list[str] = []
    for name, (kind, _src) in _ENRICHMENT_FIELDS.items():
        if name in existing and name in field_names:
            continue
        added.append(name)
        if dry_run:
            continue
        if name not in existing:
            col_type = "NUMERIC" if kind == "number" else "TEXT"
            pb.execute(f'ALTER TABLE jobs ADD COLUMN "{name}" {col_type}')
        if name not in field_names:
            fields.append(_field_def(name, kind))

    if added and not dry_run:
        pb.execute("UPDATE _collections SET fields=? WHERE name='jobs'", (json.dumps(fields),))
    return added


def _ensure_pb_indexes(pb: sqlite3.Connection, dry_run: bool) -> bool:
    """
    Relax the UNIQUE index on dedup_hash. dedup_hash (company+title+location) is NOT
    unique in the domain — 196 active jobs legitimately share one — so a UNIQUE index
    can't mirror them. Fix both the live index and PB's _collections.indexes (which PB
    recreates on boot) so it stays non-unique.
    """
    row = pb.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_jobs_dedup_hash'"
    ).fetchone()
    if not row or "UNIQUE" not in (row[0] or "").upper():
        return False
    if not dry_run:
        pb.execute("DROP INDEX IF EXISTS `idx_jobs_dedup_hash`")
        pb.execute("CREATE INDEX `idx_jobs_dedup_hash` ON `jobs` (`dedup_hash`)")
        crow = pb.execute("SELECT indexes FROM _collections WHERE name='jobs'").fetchone()
        idxs = json.loads(crow[0]) if crow and crow[0] else []
        idxs = [
            i.replace("UNIQUE INDEX", "INDEX") if "idx_jobs_dedup_hash" in i else i
            for i in idxs
        ]
        pb.execute("UPDATE _collections SET indexes=? WHERE name='jobs'", (json.dumps(idxs),))
    return True


def _map_row(src: sqlite3.Row, pb_cols: list[str],
             colinfo: dict[str, tuple[str, int]]) -> dict:
    """
    Build a PB-column -> value dict for one joined SQLite row.

    PocketBase columns are NOT NULL with defaults ('' for text, 0 for number/bool),
    so a NULL from SQLite must be coerced to that default or the INSERT/UPDATE fails.
    `id` is omitted entirely so PB's own column default mints a valid record id.
    """
    out: dict[str, object] = {}
    for col in pb_cols:
        if col == "id":
            continue
        if col in _ENRICHMENT_FIELDS or col in src.keys():
            val = src[col]
            if col == "is_active":
                val = 1 if val else 0
        else:
            val = None
        if val is None:
            typ, notnull = colinfo.get(col, ("TEXT", 0))
            if notnull:
                val = 0 if typ in ("NUMERIC", "REAL", "INTEGER", "BOOLEAN") else ""
        out[col] = val
    return out


def sync(sqlite_path: str, pb_path: str, include_inactive: bool = False,
         dry_run: bool = False) -> None:
    if _pb_is_running():
        raise SystemExit(
            "PocketBase appears to be running on :8090. Stop it before syncing "
            "(writing its live SQLite file can corrupt it), then re-run."
        )
    if not Path(pb_path).exists():
        raise SystemExit(f"PocketBase DB not found: {pb_path}")

    src = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    pb = sqlite3.connect(pb_path)
    pb.isolation_level = None  # we manage the transaction explicitly (atomic)
    pb.execute("BEGIN")
    try:
        added = _ensure_pb_fields(pb, dry_run)
        if added:
            logger.info("PB schema: added %d field(s): %s", len(added), ", ".join(added))
        if _ensure_pb_indexes(pb, dry_run):
            logger.info("PB schema: relaxed UNIQUE dedup_hash index to non-unique")

        pb_cols = [r[1] for r in pb.execute("PRAGMA table_info(jobs)")]
        colinfo = {r[1]: (str(r[2]).upper(), r[3]) for r in pb.execute("PRAGMA table_info(jobs)")}

        active_filter = "" if include_inactive else "WHERE j.is_active = 1"
        rows = src.execute(f"""
            SELECT j.*,
                   e.salary_estimated_min, e.salary_estimated_max,
                   e.salary_estimated_confidence, e.title_en,
                   e.description_summary, e.job_category
              FROM jobs j
              LEFT JOIN job_enrichments e
                ON j.source = e.source AND j.source_id = e.source_id
            {active_filter}
        """).fetchall()

        existing = {
            (r[0], r[1]): r[2]
            for r in pb.execute("SELECT source, source_id, id FROM jobs")
        }
        seen: set[tuple[str, str]] = set()
        inserted = updated = 0

        for r in rows:
            key = (r["source"], r["source_id"])
            seen.add(key)
            data = _map_row(r, pb_cols, colinfo)
            if key in existing:
                sets = ", ".join(f'"{c}"=?' for c in data)
                pb.execute(f"UPDATE jobs SET {sets} WHERE id=?", [*data.values(), existing[key]])
                updated += 1
            else:
                # omit id -> PB's column default mints a valid record id
                cols = ", ".join(f'"{c}"' for c in data)
                ph = ", ".join("?" * len(data))
                pb.execute(f"INSERT INTO jobs ({cols}) VALUES ({ph})", list(data.values()))
                inserted += 1

        stale = [i for (k, i) in existing.items() if k not in seen]
        if stale:
            pb.executemany("DELETE FROM jobs WHERE id=?", [(i,) for i in stale])

        pb.execute("ROLLBACK" if dry_run else "COMMIT")
        logger.info(
            "%sSync complete: %d inserted, %d updated, %d stale removed "
            "(PB now mirrors %d SQLite rows)",
            "[dry-run] " if dry_run else "", inserted, updated, len(stale), len(rows),
        )
    except Exception:
        pb.execute("ROLLBACK")
        raise
    finally:
        src.close()
        pb.close()


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Sync jobs.db -> PocketBase (one-way mirror).")
    p.add_argument("--sqlite", default=_DEFAULT_SQLITE, help="Source SQLite DB (read-only).")
    p.add_argument("--pb", default=_DEFAULT_PB, help="Target PocketBase data.db.")
    p.add_argument("--all", dest="include_inactive", action="store_true",
                   help="Include soft-deleted (is_active=0) jobs too. Default: active only.")
    p.add_argument("--dry-run", action="store_true", help="Report only; write nothing.")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
    sync(args.sqlite, args.pb, include_inactive=args.include_inactive, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
