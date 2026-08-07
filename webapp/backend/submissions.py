"""
Recruiter role submissions — the moderation queue behind /api/post-role.

A submitted role never touches jobs.db directly (main.py's module docstring).
It lands in an append-only JSONL file with status "pending", and the only way
it reaches the board is through `approve_submission` below, called either by
a human running scripts/review_submissions.py or by an admin from Admin Mode
(webapp/backend/admin.py). Both callers share this module rather than each
carrying their own copy of the INSERT — which is exactly the shape CLAUDE.md
warns against ("two modules used to parse the same file independently").

`dedup_hash_for` recomputes Job.dedup_hash()'s formula (hk_jobs/schema.py)
rather than importing hk_jobs: webapp/backend intentionally never imports the
pipeline package (see mailer.py/search_index.py — "the repo root is not on
sys.path"). If that formula ever changes, this must change with it.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

#: The `jobs.source` value every approved submission is stamped with.
SOURCE = "direct"


def load_queue(path: Path) -> list[dict[str, Any]]:
    """Every submission ever received, oldest first. `[]` if nothing has arrived yet."""
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def save_queue(path: Path, rows: list[dict[str, Any]]) -> None:
    """Rewrite the queue atomically — a half-written queue would lose submissions."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )
    tmp.replace(path)


def source_id_for(row: dict[str, Any]) -> str:
    """
    Stable id from the submission's own content — also what a caller uses to
    address one row (Admin Mode's UI has no other stable handle: a JSONL file
    has no primary key, and a list index shifts if the queue is edited between
    a list and an act).
    """
    basis = f"{row.get('company', '')}|{row.get('title', '')}|{row.get('received_at', '')}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def find_by_source_id(rows: list[dict[str, Any]], source_id: str) -> int | None:
    """Index of the row whose source_id_for() matches, or None."""
    for i, row in enumerate(rows):
        if source_id_for(row) == source_id:
            return i
    return None


def slugify(company: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (company or "").lower()).strip("-")


def dedup_hash_for(company_slug: str, title: str, location: str) -> str:
    """Same fingerprint the scraper uses — see the module docstring."""
    key = f"{company_slug}|{(title or '').lower()}|{(location or '').lower()}"
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def approve_submission(jobs_db_path: Path, row: dict[str, Any]) -> str:
    """
    Insert the submission into jobs.db. Returns the source_id used.

    Raises on failure. No INSERT OR IGNORE: `dedup_hash` is NOT NULL with no
    default, and an OR IGNORE swallowed exactly that violation during
    development while still reporting success to the caller. A moderation
    action that says "published" without publishing is worse than one that
    raises.
    """
    sid = source_id_for(row)
    now = datetime.now(timezone.utc).isoformat()
    company = row.get("company", "")
    slug = slugify(company)
    location = row.get("location", "Hong Kong")

    with sqlite3.connect(jobs_db_path) as conn:
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
            # The (source, source_id) primary key makes re-approval a no-op.
            if "UNIQUE" in str(exc) or "PRIMARY KEY" in str(exc):
                return sid
            raise

        if cur.rowcount != 1:
            raise RuntimeError(f"insert affected {cur.rowcount} rows, expected 1")

    return sid


def mark_approved(row: dict[str, Any], source_id: str, *, now: datetime | None = None) -> dict[str, Any]:
    """Return a copy of `row` stamped as approved. Never mutates the input."""
    updated = dict(row)
    updated["status"] = "approved"
    updated["decided_at"] = (now or datetime.now(timezone.utc)).isoformat()
    updated["source_id"] = source_id
    return updated


def mark_rejected(row: dict[str, Any], *, reason: str = "", now: datetime | None = None) -> dict[str, Any]:
    """Return a copy of `row` stamped as rejected. Never mutates the input."""
    updated = dict(row)
    updated["status"] = "rejected"
    updated["decided_at"] = (now or datetime.now(timezone.utc)).isoformat()
    if reason:
        updated["reason"] = reason
    return updated
