"""
Create the PocketBase `jobs` collection matching the hk_jobs Job schema.

Idempotent: skips creation if the collection already exists. Run against a local
PocketBase (`./pocketbase/pocketbase serve`) or any instance via env vars.

Env:
  POCKETBASE_URL             (default http://127.0.0.1:8090)
  POCKETBASE_ADMIN_EMAIL     (default admin@finex.local)
  POCKETBASE_ADMIN_PASSWORD  (default finex-pb-dev-2026)

Usage:  python scripts/setup_pocketbase.py
"""

from __future__ import annotations

import os
import sys

import httpx

PB_URL = os.getenv("POCKETBASE_URL", "http://127.0.0.1:8090").rstrip("/")
ADMIN_EMAIL = os.getenv("POCKETBASE_ADMIN_EMAIL", "admin@finex.local")
ADMIN_PASSWORD = os.getenv("POCKETBASE_ADMIN_PASSWORD", "finex-pb-dev-2026")

# Fields mirror hk_jobs/schema.py Job. PocketBase auto-adds id/created/updated.
_FIELDS = [
    {"name": "source", "type": "text", "required": True},
    {"name": "source_id", "type": "text", "required": True},
    {"name": "company", "type": "text"},
    {"name": "company_slug", "type": "text"},
    {"name": "url", "type": "url"},
    {"name": "title", "type": "text", "required": True},
    # Large explicit max — PocketBase treats max:0 as its 5000-char default, which
    # truncates real job descriptions (some are ~14k chars).
    {"name": "description_raw", "type": "text", "max": 500000},
    {"name": "description_clean", "type": "text", "max": 500000},
    {"name": "locations", "type": "json", "maxSize": 2000000},
    {"name": "remote_type", "type": "select", "maxSelect": 1,
     "values": ["onsite", "hybrid", "remote"]},
    {"name": "seniority", "type": "text"},
    {"name": "employment_type", "type": "text"},
    {"name": "salary_min", "type": "number"},
    {"name": "salary_max", "type": "number"},
    {"name": "skills_required", "type": "json", "maxSize": 2000000},
    {"name": "skills_preferred", "type": "json", "maxSize": 2000000},
    {"name": "years_experience_min", "type": "number"},
    {"name": "posted_at", "type": "date"},
    {"name": "fetched_at", "type": "date"},
    {"name": "is_active", "type": "bool"},
    {"name": "source_tier", "type": "select", "maxSelect": 1,
     "values": ["mainstream", "boutique"]},
    {"name": "category", "type": "text"},
    {"name": "extraction_confidence", "type": "number"},
    # dedup_hash is our upsert key — unique index below.
    {"name": "dedup_hash", "type": "text", "required": True},
]

_COLLECTION = {
    "name": "jobs",
    "type": "base",
    "fields": _FIELDS,
    "indexes": [
        "CREATE UNIQUE INDEX `idx_jobs_dedup_hash` ON `jobs` (`dedup_hash`)",
        "CREATE INDEX `idx_jobs_is_active` ON `jobs` (`is_active`)",
        "CREATE INDEX `idx_jobs_source_tier` ON `jobs` (`source_tier`)",
    ],
    # Public read for the deployed board; writes require superuser/API auth.
    "listRule": "",
    "viewRule": "",
    "createRule": None,
    "updateRule": None,
    "deleteRule": None,
}


def admin_token(client: httpx.Client) -> str:
    r = client.post(
        f"{PB_URL}/api/collections/_superusers/auth-with-password",
        json={"identity": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    r.raise_for_status()
    return r.json()["token"]


def main() -> int:
    with httpx.Client(timeout=30.0) as client:
        token = admin_token(client)
        headers = {"Authorization": token}

        existing = client.get(f"{PB_URL}/api/collections/jobs", headers=headers)
        if existing.status_code == 200:
            print("jobs collection already exists — skipping creation.")
            return 0

        r = client.post(f"{PB_URL}/api/collections", headers=headers, json=_COLLECTION)
        if r.status_code not in (200, 201):
            print(f"FAILED to create collection ({r.status_code}):\n{r.text}", file=sys.stderr)
            return 1
        data = r.json()
        n_fields = len(data.get("fields", []))
        print(f"Created 'jobs' collection ({n_fields} fields) with dedup_hash unique index.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
