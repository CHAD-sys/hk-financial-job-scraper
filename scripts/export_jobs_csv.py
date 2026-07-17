"""
Export the jobs database to a single CSV (a shareable, spreadsheet-friendly copy).

Same data as the PocketBase mirror: every active job (jobs LEFT JOIN
job_enrichments), one row per posting, with the AI-enrichment columns included.
Reads jobs.db READ-ONLY and writes nothing back.

List columns stored as JSON in SQLite (locations, required_skills) are flattened
to "a; b; c" so they read cleanly in Excel / Google Sheets. The apply link is the
cross-post-preferred URL (apply_url), falling back to the posting's own url.

Usage
    python scripts/export_jobs_csv.py                      # -> jobs_export.csv (active only)
    python scripts/export_jobs_csv.py --out /tmp/jobs.csv
    python scripts/export_jobs_csv.py --all                # include soft-deleted (is_active=0)
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from pathlib import Path

_DEFAULT_SQLITE = "data/jobs.db"
_DEFAULT_OUT = "jobs_export.csv"

# Output column  ->  SQL expression. Order here is the CSV column order.
_COLUMNS: dict[str, str] = {
    "company": "j.company",
    "title": "j.title",
    "title_en": "e.title_en",
    "job_category": "e.job_category",
    # Rule-based fields live on the jobs table (set for every job, incl.
    # listing-only LinkedIn/Indeed rows); the richer LLM values live in
    # job_enrichments. Prefer the LLM value, fall back to the rule-based one so
    # rows without an LLM-enrichment row still show seniority/skills/etc.
    "seniority": "COALESCE(e.seniority, j.seniority)",
    "remote_type": "COALESCE(e.remote_type, j.remote_type)",
    "locations": "j.locations",                       # JSON list -> flattened
    "years_experience_required": "COALESCE(e.years_experience_required, j.years_experience_min)",
    "salary_hkd_min": "j.salary_min",
    "salary_hkd_max": "j.salary_max",
    "salary_estimated_min": "e.salary_estimated_min",
    "salary_estimated_max": "e.salary_estimated_max",
    "salary_estimated_confidence": "e.salary_estimated_confidence",
    # JSON list -> flattened; prefer LLM skills, fall back to rule-based
    "required_skills": "COALESCE(NULLIF(e.required_skills, ''), j.skills_required)",
    "description_summary": "e.description_summary",
    "source": "j.source",
    "source_tier": "j.source_tier",
    "cross_posted": "j.cross_posted",
    "posted_at": "j.posted_at",
    "apply_url": "COALESCE(NULLIF(j.apply_url, ''), j.url)",
    "is_active": "j.is_active",
}


def _flatten(value: str | None) -> str:
    """A JSON list stored as text -> 'a; b; c'; leave plain strings/None alone."""
    if not value:
        return ""
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return str(value)
    if isinstance(parsed, list):
        return "; ".join(str(x) for x in parsed)
    return str(value)


def export(sqlite_path: str, out_path: str, include_inactive: bool = False) -> int:
    src = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    select = ",\n            ".join(f"{expr} AS {name}" for name, expr in _COLUMNS.items())
    where = "" if include_inactive else "WHERE j.is_active = 1"
    rows = src.execute(f"""
        SELECT {select}
          FROM jobs j
          LEFT JOIN job_enrichments e
            ON j.source = e.source AND j.source_id = e.source_id
        {where}
        ORDER BY j.company, j.title
    """).fetchall()

    list_cols = {"locations", "required_skills"}
    with open(out_path, "w", newline="", encoding="utf-8-sig") as fh:  # utf-8-sig: Excel-friendly
        writer = csv.writer(fh)
        writer.writerow(_COLUMNS.keys())
        for r in rows:
            writer.writerow([
                _flatten(r[c]) if c in list_cols else ("" if r[c] is None else r[c])
                for c in _COLUMNS
            ])
    src.close()
    return len(rows)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Export jobs.db to CSV.")
    p.add_argument("--sqlite", default=_DEFAULT_SQLITE, help="Source SQLite DB (read-only).")
    p.add_argument("--out", default=_DEFAULT_OUT, help="Output CSV path.")
    p.add_argument("--all", dest="include_inactive", action="store_true",
                   help="Include soft-deleted (is_active=0) jobs too. Default: active only.")
    args = p.parse_args(argv)
    n = export(args.sqlite, args.out, include_inactive=args.include_inactive)
    print(f"Wrote {n} rows to {Path(args.out).resolve()}")


if __name__ == "__main__":
    main()
