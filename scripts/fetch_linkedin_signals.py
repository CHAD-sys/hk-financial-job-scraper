"""
Fetch LinkedIn detail-page market signals (applicant count, reposted) and merge
them into jobs.board_signals — for the P2 web-card badges.

LinkedIn's applicant count and reposted flag live on the guest job-detail page,
not the listing card. This pass fetches that page for every active LinkedIn job
and json_patches the new signals into board_signals (preserving new_job/reposted
already set by the listing scrape).

Plain httpx (rate-limited, so run with a few workers). Commits every 200 so a
kill loses at most the in-flight batch. Idempotent — safe to re-run.

Usage:
    .venv/bin/python scripts/fetch_linkedin_signals.py
    .venv/bin/python scripts/fetch_linkedin_signals.py --limit 50 --workers 4
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hk_jobs.adapters.linkedin import parse_detail_signals  # noqa: E402

_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{id}"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}
_BATCH = 200


def _fetch(source_id: str, max_retries: int = 3) -> dict | None:
    for attempt in range(max_retries):
        try:
            with httpx.Client(timeout=15, headers=_HEADERS, follow_redirects=True) as c:
                r = c.get(_URL.format(id=source_id))
        except httpx.HTTPError:
            time.sleep(2 ** (attempt + 1))
            continue
        if r.status_code in (429, 999, 503):
            time.sleep(2 ** (attempt + 1))
            continue
        if r.status_code != 200:
            return None
        return parse_detail_signals(r.text)
    return None


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default="data/jobs.db")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--workers", type=int, default=4)
    args = p.parse_args(argv)

    conn = sqlite3.connect(args.db, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=60000")
    sql = ("SELECT source_id FROM jobs WHERE source='linkedin' AND is_active=1 "
           "ORDER BY fetched_at DESC")
    if args.limit:
        sql += f" LIMIT {args.limit}"
    ids = [r["source_id"] for r in conn.execute(sql)]
    print(f"Fetching LinkedIn signals for {len(ids)} jobs ({args.workers} workers)…",
          file=sys.stderr)

    written = 0
    for start in range(0, len(ids), _BATCH):
        batch = ids[start:start + _BATCH]
        results: dict[str, dict] = {}
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futs = {pool.submit(_fetch, sid): sid for sid in batch}
            for f in as_completed(futs):
                sig = f.result()
                if sig:
                    results[futs[f]] = sig
        with conn:
            for sid, sig in results.items():
                # merge into existing board_signals without clobbering listing signals
                conn.execute(
                    "UPDATE jobs SET board_signals = json_patch("
                    "CASE WHEN board_signals IN ('', '{}') THEN '{}' ELSE board_signals END, ?"
                    ") WHERE source='linkedin' AND source_id=?",
                    (json.dumps(sig), sid),
                )
                written += 1
        print(f"  committed {min(start+_BATCH, len(ids))}/{len(ids)} "
              f"({written} with signals)", file=sys.stderr)
    print(f"✅ done: {written} LinkedIn jobs updated with detail signals", file=sys.stderr)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
