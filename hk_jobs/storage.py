"""
SQLite persistence layer.

Design principles:
  - SQL is written to be Postgres-compatible wherever possible. The only
    SQLite-specific features used are noted with "# SQLite:" comments so a
    future migration can find them quickly.
  - Soft-delete only: when a job disappears from the source we set
    is_active=0 rather than deleting the row. This matters because a member
    may have bookmarked or applied to a job that later gets taken down — we
    still want to be able to show it to them. Hard-delete would lose that
    history permanently.
  - Lists (locations, skills) are serialised as JSON text. SQLite has no
    array type; JSON is human-readable and survives a Postgres migration
    (Postgres has native JSON columns).
  - Datetimes are stored as ISO 8601 text ("2024-03-01T09:00:00+00:00").
    SQLite has no native datetime type; ISO text sorts correctly and is
    understood by both Python's datetime.fromisoformat() and Postgres.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from hk_jobs.schema import Job, jobs_to_jsonl

# ── DDL ───────────────────────────────────────────────────────────────────────

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS jobs (
    -- Identity
    source          TEXT NOT NULL,
    source_id       TEXT NOT NULL,
    company         TEXT NOT NULL,
    company_slug    TEXT NOT NULL,
    url             TEXT NOT NULL,
    dedup_hash      TEXT NOT NULL,

    -- Descriptive
    title           TEXT NOT NULL,
    description_raw  TEXT NOT NULL DEFAULT '',
    description_clean TEXT NOT NULL DEFAULT '',

    -- Location
    locations       TEXT NOT NULL DEFAULT '[]',   -- JSON array
    remote_type     TEXT,

    -- Classification
    department      TEXT,
    seniority       TEXT,
    employment_type TEXT,

    -- Compensation
    salary_min      INTEGER,
    salary_max      INTEGER,
    salary_currency TEXT,

    -- Skills (JSON arrays)
    skills_required  TEXT NOT NULL DEFAULT '[]',
    skills_preferred TEXT NOT NULL DEFAULT '[]',
    years_experience_min INTEGER,

    -- Metadata
    posted_at       TEXT,                         -- ISO 8601
    fetched_at      TEXT NOT NULL,                -- ISO 8601
    is_active       INTEGER NOT NULL DEFAULT 1,   -- SQLite: 1/0 for boolean

    PRIMARY KEY (source, source_id)
);
"""

_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_jobs_company_slug ON jobs (company_slug);",
    "CREATE INDEX IF NOT EXISTS idx_jobs_dedup_hash   ON jobs (dedup_hash);",
    "CREATE INDEX IF NOT EXISTS idx_jobs_is_active    ON jobs (is_active);",
    "CREATE INDEX IF NOT EXISTS idx_jobs_seniority    ON jobs (seniority);",
]

# ── Upsert SQL ────────────────────────────────────────────────────────────────
# INSERT ... ON CONFLICT is standard SQL:2003 and supported by both SQLite
# (≥3.24, 2018) and Postgres. The DO UPDATE clause refreshes mutable fields
# on re-insert while leaving immutable fields (source, source_id, first
# fetched_at) untouched.

_UPSERT = """
INSERT INTO jobs (
    source, source_id, company, company_slug, url, dedup_hash,
    title, description_raw, description_clean,
    locations, remote_type,
    department, seniority, employment_type,
    salary_min, salary_max, salary_currency,
    skills_required, skills_preferred, years_experience_min,
    posted_at, fetched_at, is_active
) VALUES (
    :source, :source_id, :company, :company_slug, :url, :dedup_hash,
    :title, :description_raw, :description_clean,
    :locations, :remote_type,
    :department, :seniority, :employment_type,
    :salary_min, :salary_max, :salary_currency,
    :skills_required, :skills_preferred, :years_experience_min,
    :posted_at, :fetched_at, 1
)
ON CONFLICT (source, source_id) DO UPDATE SET
    title              = excluded.title,
    description_raw    = excluded.description_raw,
    description_clean  = excluded.description_clean,
    locations          = excluded.locations,
    remote_type        = excluded.remote_type,
    department         = excluded.department,
    seniority          = excluded.seniority,
    employment_type    = excluded.employment_type,
    salary_min         = excluded.salary_min,
    salary_max         = excluded.salary_max,
    salary_currency    = excluded.salary_currency,
    skills_required    = excluded.skills_required,
    skills_preferred   = excluded.skills_preferred,
    years_experience_min = excluded.years_experience_min,
    posted_at          = excluded.posted_at,
    fetched_at         = excluded.fetched_at,
    dedup_hash         = excluded.dedup_hash,
    url                = excluded.url,
    is_active          = 1
;
"""


class JobStore:
    """
    Manages a SQLite database of job postings.

    Usage:
        store = JobStore("data/jobs.db")
        inserted, updated = store.upsert_many(jobs)
        store.mark_inactive_for_run("hsbc", run_fetched_at)
        store.close()
    """

    def __init__(self, path: str = "data/jobs.db") -> None:
        # SQLite: isolation_level=None puts the connection in autocommit mode
        # by default; we manage transactions explicitly with BEGIN/COMMIT.
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row
        # SQLite: WAL mode improves read concurrency and crash safety.
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.execute(_CREATE_TABLE)
            for idx_sql in _CREATE_INDEXES:
                self._conn.execute(idx_sql)

    # ── Public API ─────────────────────────────────────────────────────────

    def upsert_many(self, jobs: list[Job]) -> tuple[int, int]:
        """
        Insert or update a batch of jobs.

        Returns (inserted, updated) counts. A job is counted as 'inserted'
        when it's new (no existing row for that source + source_id), and
        'updated' when a row already existed and was refreshed.
        """
        if not jobs:
            return 0, 0

        inserted = 0
        updated = 0

        with self._conn:
            for job in jobs:
                row = _job_to_row(job)
                # Check whether this source+source_id already exists so we
                # can tally inserts vs updates accurately after the upsert.
                exists = self._conn.execute(
                    "SELECT 1 FROM jobs WHERE source=? AND source_id=?",
                    (job.source, job.source_id),
                ).fetchone()
                self._conn.execute(_UPSERT, row)
                if exists:
                    updated += 1
                else:
                    inserted += 1

        return inserted, updated

    def mark_inactive_for_run(self, company_slug: str, fetched_at: datetime) -> int:
        """
        Soft-delete jobs for a company that were NOT seen in this run.

        After we finish scraping a company we call this with the timestamp
        used for fetched_at during that run. Any row for this company whose
        fetched_at is OLDER than the run timestamp is a job that disappeared
        — it was active before but wasn't returned by the ATS this time.
        We mark it inactive rather than deleting it (see module docstring
        for why).

        Returns the number of rows deactivated.
        """
        fetched_iso = fetched_at.isoformat()
        cursor = self._conn.execute(
            """
            UPDATE jobs
               SET is_active = 0
             WHERE company_slug = ?
               AND is_active    = 1
               AND fetched_at   < ?
            """,
            (company_slug, fetched_iso),
        )
        self._conn.commit()
        return cursor.rowcount

    def stats(self) -> dict[str, Any]:
        """
        Return summary counts for monitoring and reporting.

        Shape:
            {
              "total":  <int>,
              "active": <int>,
              "by_company": {"hsbc": 42, "aia": 17, ...}
            }
        """
        row = self._conn.execute(
            "SELECT COUNT(*) AS total, SUM(is_active) AS active FROM jobs"
        ).fetchone()
        by_company = {
            r["company_slug"]: r["active_count"]
            for r in self._conn.execute(
                """
                SELECT company_slug, SUM(is_active) AS active_count
                  FROM jobs
                 GROUP BY company_slug
                 ORDER BY company_slug
                """
            ).fetchall()
        }
        return {
            "total": row["total"] or 0,
            "active": row["active"] or 0,
            "by_company": by_company,
        }

    def export_active_jsonl(self, path: str) -> int:
        """
        Write all active jobs to a JSONL file, sorted by company then title.

        Returns the number of jobs exported.
        """
        rows = self._conn.execute(
            "SELECT * FROM jobs WHERE is_active=1 ORDER BY company_slug, title"
        ).fetchall()
        jobs = [_row_to_job(row) for row in rows]
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        jobs_to_jsonl(jobs, path)
        return len(jobs)

    def close(self) -> None:
        """Close the underlying database connection."""
        self._conn.close()

    def __enter__(self) -> "JobStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


# ── Serialisation helpers ─────────────────────────────────────────────────────

def _job_to_row(job: Job) -> dict[str, Any]:
    """Flatten a Job into a dict of SQLite-compatible scalar values."""
    return {
        "source": job.source,
        "source_id": job.source_id,
        "company": job.company,
        "company_slug": job.company_slug,
        "url": job.url,
        "dedup_hash": job.dedup_hash(),
        "title": job.title,
        "description_raw": job.description_raw,
        "description_clean": job.description_clean,
        "locations": json.dumps(job.locations),
        "remote_type": job.remote_type,
        "department": job.department,
        "seniority": job.seniority,
        "employment_type": job.employment_type,
        "salary_min": job.salary_min,
        "salary_max": job.salary_max,
        "salary_currency": job.salary_currency,
        "skills_required": json.dumps(job.skills_required),
        "skills_preferred": json.dumps(job.skills_preferred),
        "years_experience_min": job.years_experience_min,
        "posted_at": job.posted_at.isoformat() if job.posted_at else None,
        "fetched_at": job.fetched_at.isoformat(),
    }


def _row_to_job(row: sqlite3.Row) -> Job:
    """Reconstruct a Job from a SQLite row (inverse of _job_to_row)."""
    return Job(
        source=row["source"],
        source_id=row["source_id"],
        company=row["company"],
        company_slug=row["company_slug"],
        url=row["url"],
        title=row["title"],
        description_raw=row["description_raw"],
        description_clean=row["description_clean"],
        locations=json.loads(row["locations"]),
        remote_type=row["remote_type"],
        department=row["department"],
        seniority=row["seniority"],
        employment_type=row["employment_type"],
        salary_min=row["salary_min"],
        salary_max=row["salary_max"],
        salary_currency=row["salary_currency"],
        skills_required=json.loads(row["skills_required"]),
        skills_preferred=json.loads(row["skills_preferred"]),
        years_experience_min=row["years_experience_min"],
        posted_at=datetime.fromisoformat(row["posted_at"]) if row["posted_at"] else None,
        fetched_at=datetime.fromisoformat(row["fetched_at"]),
        is_active=bool(row["is_active"]),
    )
