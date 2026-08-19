#!/usr/bin/env python3
"""Re-extract and re-analyse every stored resume — no network, no API cost.

`analyse_resume()` runs in exactly one place: the upload endpoint
(webapp/backend/main.py). A stored resume's `text_content` and `analysis_json`
are then rehydrated verbatim forever by `evidence_from_storage()`, so a resume
uploaded before an extractor change keeps its old evidence for good. There is
no other re-analysis path, which is why this script exists.

It matters here because the v2 extractor changed BOTH halves:

  * `text_content` — PDFs are now read with pypdf's "layout" mode. The old
    default mode shredded table-based CVs into one word per line and glued
    headings onto neighbouring text. Re-analysing the STORED TEXT alone would
    not fix those, so this re-parses the original `file_content` blob.
  * `analysis_json` — durations now come from dated roles, seniority is read
    from title lines only (a bullet naming someone else's boss no longer
    promotes an intern), and certifications are extracted.

Bare run = DRY RUN (counts, diffs and examples, no writes). Add --apply to
write, which backs up seekers.db first.

Usage
    python scripts/reanalyse_resumes.py                      # dry run
    python scripts/reanalyse_resumes.py --apply              # write
    SEEKERS_DB_PATH=/data/seekers.db python scripts/reanalyse_resumes.py --apply
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

def _backend_dir() -> Path:
    """Where webapp/backend's modules live.

    Two layouts have to work. In a repo checkout they sit under
    webapp/backend. On Railway the deploy uploads that directory AS the app
    root, so the modules are at /app and there is no `scripts/` at all — this
    file gets piped in. Without this the backfill can only run somewhere the
    production database isn't.
    """
    for candidate in (
        Path(__file__).resolve().parent.parent / "webapp" / "backend",
        Path("/app"),
        Path.cwd(),
    ):
        if (candidate / "seekers_store.py").exists():
            return candidate
    raise SystemExit("Could not locate webapp/backend's modules.")


sys.path.insert(0, str(_backend_dir()))

import resume_intelligence  # noqa: E402
import seekers_store  # noqa: E402


def _describe(analysis: dict) -> str:
    seniority = analysis.get("seniority") or "—"
    years = analysis.get("years_experience")
    years_label = "—" if years is None else str(years)
    return (
        f"seniority={seniority:<9} years={years_label:<3} "
        f"skills={len(analysis.get('skills') or []):<3} "
        f"certs={len(analysis.get('certifications') or [])}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="write the results (default is a dry run)"
    )
    parser.add_argument(
        "--limit", type=int, default=0, help="only process the first N resumes"
    )
    args = parser.parse_args()

    db_path = seekers_store.resolve_seekers_db_path()
    if not db_path.exists():
        print(f"No seekers.db at {db_path}", file=sys.stderr)
        return 1
    print(f"seekers.db: {db_path}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT seeker_id, filename, media_type, file_content, text_content, analysis_json
        FROM seeker_resumes
        ORDER BY uploaded_at
        """
    ).fetchall()
    if args.limit > 0:
        rows = rows[: args.limit]
    print(f"{len(rows)} stored resume(s)\n")

    updates: list[tuple[str, str, str]] = []
    failures: list[tuple[str, str]] = []
    seniority_moves: Counter[str] = Counter()
    changed = text_grew = 0

    for row in rows:
        try:
            before = json.loads(row["analysis_json"] or "{}")
        except json.JSONDecodeError:
            before = {}
        try:
            parsed = resume_intelligence.parse_resume(
                row["filename"], row["media_type"], bytes(row["file_content"])
            )
            after = resume_intelligence.analyse_resume(parsed).as_dict()
        except resume_intelligence.ResumeValidationError as exc:
            # A file that no longer parses keeps whatever it already had; this
            # backfill must never leave a Seeker with less than they started.
            failures.append((row["seeker_id"], str(exc)))
            continue

        if after != before or parsed.text != row["text_content"]:
            changed += 1
            updates.append((parsed.text, json.dumps(after, ensure_ascii=False), row["seeker_id"]))
        if len(parsed.text) > len(row["text_content"] or ""):
            text_grew += 1
        move = f"{before.get('seniority') or '—'} -> {after.get('seniority') or '—'}"
        if before.get("seniority") != after.get("seniority"):
            seniority_moves[move] += 1
        print(f"  {row['seeker_id'][:8]}  {_describe(before)}   ->   {_describe(after)}")

    print(f"\n{changed} of {len(rows)} would change; {text_grew} gained extracted text")
    if seniority_moves:
        print("seniority moves:")
        for move, count in seniority_moves.most_common():
            print(f"  {count:4}  {move}")
    if failures:
        print(f"\n{len(failures)} could not be re-parsed and were left untouched:")
        for seeker_id, message in failures[:10]:
            print(f"  {seeker_id[:8]}  {message}")

    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply to write.")
        return 0
    if not updates:
        print("\nNothing to write.")
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = db_path.with_name(f"{db_path.name}.{stamp}.bak")
    shutil.copy2(db_path, backup)
    print(f"\nBacked up to {backup}")

    with conn:
        conn.executemany(
            "UPDATE seeker_resumes SET text_content = ?, analysis_json = ? WHERE seeker_id = ?",
            updates,
        )
    print(f"Wrote {len(updates)} resume(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
