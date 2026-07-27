"""
Review roles recruiters submitted through /post-a-role.

The web backend never writes to jobs.db. A submitted role lands in an
append-only queue at data/submitted_roles.jsonl with status "pending", and
nothing reaches the board until a human approves it here. This script is that
human's tool.

Approving inserts the role into `jobs` with source "direct" and marks it active,
primary and already-enriched-by-hand, so it behaves like any other listing on the
board. Rejecting only records the decision — the submission is never deleted, so
there is always an audit trail of what was turned down and why.

Decisions are written back to data/submitted_roles.jsonl in place (status becomes
"approved" / "rejected" with a timestamp), so re-running never re-offers a role
that has already been dealt with.

Usage
    python scripts/review_submissions.py                 # list everything pending
    python scripts/review_submissions.py --show 3        # print one submission in full
    python scripts/review_submissions.py --approve 3     # publish it to the board
    python scripts/review_submissions.py --reject 3 --reason "duplicate"
    python scripts/review_submissions.py --all           # include already-decided rows
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUEUE = ROOT / "data" / "submitted_roles.jsonl"
DB = ROOT / "data" / "jobs.db"

SOURCE = "direct"


def load_queue() -> list[dict]:
    if not QUEUE.exists():
        return []
    rows = []
    for line in QUEUE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def save_queue(rows: list[dict]) -> None:
    """Rewrite the queue atomically — a half-written queue would lose submissions."""
    tmp = QUEUE.with_suffix(".jsonl.tmp")
    tmp.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )
    tmp.replace(QUEUE)


def source_id_for(row: dict) -> str:
    """
    Stable id from the submission's own content.

    Deterministic so that approving the same submission twice cannot create two
    board entries — the INSERT OR IGNORE below then simply does nothing.
    """
    basis = f"{row.get('company','')}|{row.get('title','')}|{row.get('received_at','')}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def slugify(company: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (company or "").lower()).strip("-")


def dedup_hash_for(company_slug: str, title: str, location: str) -> str:
    """
    Same fingerprint the scraper uses — see Job.dedup_hash() in hk_jobs/schema.py:
    sha256 of "company_slug|lowercased title|first location", first 12 hex chars.

    Recomputed here rather than imported so this script does not drag the whole
    hk_jobs package (and its dependencies) in just to hash three strings. If that
    definition ever changes, this must change with it.
    """
    key = f"{company_slug}|{(title or '').lower()}|{(location or '').lower()}"
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def approve(row: dict) -> str:
    """
    Insert the submission into jobs.db. Returns the source_id used.

    Raises on failure. Note there is no INSERT OR IGNORE here: `dedup_hash` is
    NOT NULL with no default, and an OR IGNORE swallowed exactly that violation
    during development while still reporting success to the operator. A
    moderation tool that says "published" without publishing is worse than one
    that crashes.
    """
    sid = source_id_for(row)
    now = datetime.now(timezone.utc).isoformat()
    company = row.get("company", "")
    slug = slugify(company)
    location = row.get("location", "Hong Kong")

    with sqlite3.connect(DB) as conn:
        try:
            cur = conn.execute(
                """
                INSERT INTO jobs (
                    source, source_id, company, company_slug, url, dedup_hash, title,
                    description_raw, description_clean, locations,
                    employment_type, apply_url, posted_at, fetched_at,
                    is_active, source_tier, is_primary, cross_posted,
                    extraction_confidence
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,1,0,1.0)
                """,
                (
                    SOURCE,
                    sid,
                    company,
                    slug,
                    row.get("apply_url", ""),
                    dedup_hash_for(slug, row.get("title", ""), location),
                    row.get("title", ""),
                    row.get("description", ""),
                    row.get("description", ""),
                    json.dumps([location]),
                    row.get("employment_type", ""),
                    row.get("apply_url", ""),
                    row.get("received_at", now),
                    now,
                    # Vetted by a person, so these sit in the Exclusive tier
                    # rather than with scraped mainstream listings.
                    "boutique",
                ),
            )
        except sqlite3.IntegrityError as exc:
            # The (source, source_id) primary key makes re-approval a no-op, which
            # is fine. Anything else is a real problem and must not be swallowed.
            if "UNIQUE" in str(exc) or "PRIMARY KEY" in str(exc):
                return sid
            raise

        if cur.rowcount != 1:
            raise RuntimeError(f"insert affected {cur.rowcount} rows, expected 1")

    return sid


def fmt(i: int, row: dict) -> str:
    status = row.get("status", "pending")
    mark = {"pending": " ", "approved": "✓", "rejected": "✗"}.get(status, "?")
    return (
        f"[{mark}] {i:>3}  {row.get('title','?')[:44]:<44} "
        f"{row.get('company','?')[:26]:<26} {row.get('received_at','')[:10]}"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--approve", type=int, metavar="N", help="approve submission N and publish it")
    ap.add_argument("--reject", type=int, metavar="N", help="reject submission N")
    ap.add_argument("--reason", default="", help="note stored with a rejection")
    ap.add_argument("--show", type=int, metavar="N", help="print submission N in full")
    ap.add_argument("--all", action="store_true", help="include already-decided submissions")
    args = ap.parse_args()

    rows = load_queue()
    if not rows:
        print(f"No submissions yet ({QUEUE} does not exist or is empty).")
        return

    if args.show is not None:
        row = rows[args.show]
        for k, v in row.items():
            print(f"{k:>16}: {v}")
        return

    if args.approve is not None:
        row = rows[args.approve]
        if row.get("status") == "approved":
            print(f"Already approved: {row.get('title')}")
            return
        sid = approve(row)
        row["status"] = "approved"
        row["decided_at"] = datetime.now(timezone.utc).isoformat()
        row["source_id"] = sid
        save_queue(rows)
        print(f"Approved and published: {row.get('title')} @ {row.get('company')}")
        print(f"  on the board as {SOURCE}/{sid}")
        return

    if args.reject is not None:
        row = rows[args.reject]
        row["status"] = "rejected"
        row["decided_at"] = datetime.now(timezone.utc).isoformat()
        if args.reason:
            row["reason"] = args.reason
        save_queue(rows)
        print(f"Rejected: {row.get('title')} @ {row.get('company')}")
        return

    shown = [(i, r) for i, r in enumerate(rows) if args.all or r.get("status", "pending") == "pending"]
    if not shown:
        print(f"Nothing pending. {len(rows)} submission(s) already decided — use --all to see them.")
        return

    print(f"{len(shown)} submission(s):\n")
    for i, row in shown:
        print(fmt(i, row))
    print("\n  --show N to read one, --approve N to publish, --reject N --reason '…'")


if __name__ == "__main__":
    main()
