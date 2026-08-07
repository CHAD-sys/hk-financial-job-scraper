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
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUEUE = ROOT / "data" / "submitted_roles.jsonl"
DB = ROOT / "data" / "jobs.db"

# The write path (the INSERT, the dedup-hash formula, the queue file format) now
# lives in webapp/backend/submissions.py, shared with Admin Mode's
# /api/admin/submissions endpoints (webapp/backend/admin.py) — one definition of
# "how a submission becomes a board row" instead of two copies drifting apart.
sys.path.insert(0, str(ROOT / "webapp" / "backend"))
from submissions import (  # noqa: E402
    SOURCE,
    approve_submission,
    load_queue as _load_queue,
    mark_approved,
    mark_rejected,
    save_queue as _save_queue,
)


def load_queue() -> list[dict]:
    return _load_queue(QUEUE)


def save_queue(rows: list[dict]) -> None:
    _save_queue(QUEUE, rows)


def approve(row: dict) -> str:
    return approve_submission(DB, row)


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
        rows[args.approve] = mark_approved(row, sid)
        save_queue(rows)
        print(f"Approved and published: {row.get('title')} @ {row.get('company')}")
        print(f"  on the board as {SOURCE}/{sid}")
        return

    if args.reject is not None:
        row = rows[args.reject]
        rows[args.reject] = mark_rejected(row, reason=args.reason)
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
