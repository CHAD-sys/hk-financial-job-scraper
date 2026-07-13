"""
PocketBase storage backend — drop-in alternative to storage.JobStore.

Implements the same interface the pipeline uses (upsert_many, mark_inactive_for_run,
stats, export_active_jsonl, close, context manager) but talks to PocketBase's REST
API instead of raw SQLite. dedup_hash is the upsert key (unique index), mirroring
the SQLite ON CONFLICT logic — including preserving a previously-fetched description
when a re-scrape carries an empty one, and keeping `company` stable on update.

Config via env (or constructor args):
  POCKETBASE_URL             (default http://127.0.0.1:8090)
  POCKETBASE_ADMIN_EMAIL     (default admin@finex.local)
  POCKETBASE_ADMIN_PASSWORD  (default finex-pb-dev-2026)

The 'jobs' collection must exist first — run scripts/setup_pocketbase.py.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any

import httpx

from hk_jobs.schema import Job, jobs_to_jsonl

logger = logging.getLogger(__name__)

_COLL = "jobs"


def _pb_dt(dt: datetime | None) -> str:
    """
    Format a datetime the way PocketBase stores dates: 'YYYY-MM-DD HH:MM:SS.sssZ'
    (space separator, millisecond precision, Z). Filter comparisons are string-based,
    so filter values MUST use this exact format or `<`/`>` silently misbehave
    (the space-vs-'T' at char 10 otherwise makes every comparison true).
    """
    if dt is None:
        return ""
    d = dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)
    return d.strftime("%Y-%m-%d %H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def _job_to_record(job: Job) -> dict[str, Any]:
    """Flatten a Job into a PocketBase record payload (full, for INSERT)."""
    return {
        "source": job.source,
        "source_id": job.source_id,
        "company": job.company,
        "company_slug": job.company_slug,
        "url": job.url,
        "title": job.title,
        "description_raw": job.description_raw,
        "description_clean": job.description_clean,
        "locations": job.locations,
        "remote_type": job.remote_type or "",
        "seniority": job.seniority or "",
        "employment_type": job.employment_type or "",
        "salary_min": job.salary_min,
        "salary_max": job.salary_max,
        "skills_required": job.skills_required,
        "skills_preferred": job.skills_preferred,
        "years_experience_min": job.years_experience_min,
        "posted_at": _pb_dt(job.posted_at),
        "fetched_at": _pb_dt(job.fetched_at),
        "is_active": job.is_active,
        "source_tier": getattr(job, "source_tier", None) or "mainstream",
        # category is optional on the Job model (added with the longtail track); tolerate
        # its absence so this storage backend is self-contained.
        "category": getattr(job, "category", None) or "",
        "extraction_confidence": job.extraction_confidence,
        "dedup_hash": job.dedup_hash(),
    }


def _parse_dt(value: Any) -> datetime | None:
    """Parse a PocketBase datetime string (e.g. '2024-01-01 00:00:00.000Z')."""
    if not value:
        return None
    s = str(value).strip().replace(" ", "T").replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _record_to_job(r: dict[str, Any]) -> Job:
    """Reconstruct a Job from a PocketBase record (for export)."""
    return Job(
        source=r["source"],
        source_id=r["source_id"],
        company=r.get("company", ""),
        company_slug=r.get("company_slug", ""),
        url=r.get("url", ""),
        title=r["title"],
        description_raw=r.get("description_raw", ""),
        description_clean=r.get("description_clean", ""),
        locations=r.get("locations") or [],
        remote_type=r.get("remote_type") or None,
        seniority=r.get("seniority") or None,
        employment_type=r.get("employment_type") or None,
        salary_min=r.get("salary_min") or None,
        salary_max=r.get("salary_max") or None,
        skills_required=r.get("skills_required") or [],
        skills_preferred=r.get("skills_preferred") or [],
        years_experience_min=r.get("years_experience_min") or None,
        posted_at=_parse_dt(r.get("posted_at")),
        fetched_at=_parse_dt(r.get("fetched_at")) or datetime.now(),
        is_active=bool(r.get("is_active")),
        source_tier=r.get("source_tier") or "mainstream",
        category=r.get("category") or None,
        extraction_confidence=r.get("extraction_confidence"),
    )


class PocketBaseStorage:
    """PocketBase-backed store with the same interface as storage.JobStore."""

    def __init__(
        self,
        url: str | None = None,
        admin_email: str | None = None,
        admin_password: str | None = None,
    ) -> None:
        self.url = (url or os.getenv("POCKETBASE_URL", "http://127.0.0.1:8090")).rstrip("/")
        self._email = admin_email or os.getenv("POCKETBASE_ADMIN_EMAIL", "admin@finex.local")
        self._password = admin_password or os.getenv("POCKETBASE_ADMIN_PASSWORD", "finex-pb-dev-2026")
        self._client = httpx.Client(timeout=60.0, base_url=self.url)
        self._auth()

    # ── auth ────────────────────────────────────────────────────────────────
    def _auth(self) -> None:
        r = self._client.post(
            "/api/collections/_superusers/auth-with-password",
            json={"identity": self._email, "password": self._password},
        )
        r.raise_for_status()
        self._client.headers["Authorization"] = r.json()["token"]

    # ── lookups ─────────────────────────────────────────────────────────────
    def _find_by_dedup(self, dedup_hash: str) -> dict[str, Any] | None:
        r = self._client.get(
            f"/api/collections/{_COLL}/records",
            params={"filter": f'dedup_hash="{dedup_hash}"', "perPage": 1},
        )
        r.raise_for_status()
        items = r.json().get("items", [])
        return items[0] if items else None

    def _count(self, filt: str | None = None) -> int:
        params: dict[str, Any] = {"perPage": 1, "page": 1}
        if filt:
            params["filter"] = filt
        r = self._client.get(f"/api/collections/{_COLL}/records", params=params)
        r.raise_for_status()
        return r.json().get("totalItems", 0)

    def _iter_records(self, filt: str | None = None):
        page = 1
        while True:
            params: dict[str, Any] = {"perPage": 200, "page": page}
            if filt:
                params["filter"] = filt
            r = self._client.get(f"/api/collections/{_COLL}/records", params=params)
            r.raise_for_status()
            data = r.json()
            yield from data.get("items", [])
            if page >= data.get("totalPages", 1):
                break
            page += 1

    # ── public API (mirrors JobStore) ───────────────────────────────────────
    def upsert_many(self, jobs: list[Job]) -> tuple[int, int]:
        """Insert new jobs / update existing ones keyed on dedup_hash. Returns (inserted, updated)."""
        inserted = updated = 0
        for job in jobs:
            record = _job_to_record(job)
            existing = self._find_by_dedup(record["dedup_hash"])
            if existing is None:
                r = self._client.post(f"/api/collections/{_COLL}/records", json=record)
                if r.status_code in (200, 201):
                    inserted += 1
                else:
                    logger.error("PB insert failed (%s): %s", r.status_code, r.text[:200])
            else:
                patch = dict(record)
                # Keep `company` stable on re-scrape (mirrors SQLite: company set on
                # insert, not overwritten by a card-extraction fallback later).
                patch.pop("company", None)
                # Preserve a previously-fetched description if this scrape has none
                # (listing-only re-scrapes carry empty text). Mirrors COALESCE(NULLIF()).
                if not record["description_clean"]:
                    patch.pop("description_raw", None)
                    patch.pop("description_clean", None)
                r = self._client.patch(
                    f"/api/collections/{_COLL}/records/{existing['id']}", json=patch
                )
                if r.status_code == 200:
                    updated += 1
                else:
                    logger.error("PB update failed (%s): %s", r.status_code, r.text[:200])
        return inserted, updated

    def mark_inactive_for_run(
        self, company_slug: str, fetched_at: datetime, new_job_count: int | None = None
    ) -> int:
        """
        Soft-delete active records for a company whose fetched_at predates this run.

        Safety guard mirrors JobStore: if the scrape returned 0 jobs, skip deactivation
        (likely a transient block) so we never wipe a company on a failed fetch.
        """
        if new_job_count == 0:
            logger.warning(
                "%s: returned 0 jobs — skipping deactivation (likely transient block).",
                company_slug,
            )
            return 0

        run_ts = _pb_dt(fetched_at)  # PocketBase-format timestamp for correct comparison
        # Active records for this company not refreshed in this run.
        stale = list(self._iter_records(
            f'company_slug="{company_slug}" && is_active=true && fetched_at<"{run_ts}"'
        ))
        deactivated = 0
        for rec in stale:
            r = self._client.patch(
                f"/api/collections/{_COLL}/records/{rec['id']}", json={"is_active": False}
            )
            if r.status_code == 200:
                deactivated += 1
        return deactivated

    def stats(self) -> dict[str, Any]:
        """{'total', 'active', 'by_company'} — same shape as JobStore.stats()."""
        total = self._count()
        active = self._count("is_active=true")
        by_company: dict[str, int] = {}
        for rec in self._iter_records("is_active=true"):
            slug = rec.get("company_slug", "")
            by_company[slug] = by_company.get(slug, 0) + 1
        return {"total": total, "active": active, "by_company": by_company}

    def export_active_jsonl(self, path: str) -> int:
        jobs = [_record_to_job(r) for r in self._iter_records("is_active=true")]
        jobs.sort(key=lambda j: (j.company_slug, j.title))
        jobs_to_jsonl(jobs, path)
        return len(jobs)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "PocketBaseStorage":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
