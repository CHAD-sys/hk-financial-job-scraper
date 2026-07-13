"""
Database migrations for hk_jobs.

Each migration function is idempotent — safe to call on every startup.
"""

from __future__ import annotations

import logging
import sqlite3

logger = logging.getLogger(__name__)

_JOB_HISTORY_DDL = """
CREATE TABLE IF NOT EXISTS job_history (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id       TEXT    NOT NULL,
    company_name     TEXT    NOT NULL,
    job_count        INTEGER NOT NULL,
    scraped_date     DATE    NOT NULL,
    trend_direction  TEXT,           -- 'growing' | 'declining' | 'stable' | 'new'
    trend_percent    REAL,           -- e.g. +5.2, -3.1
    jobs_added       INTEGER,        -- max(0, delta)
    jobs_removed     INTEGER,        -- max(0, -delta)
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (company_id, scraped_date)
);
"""

_COMPANY_METRICS_DDL = """
CREATE TABLE IF NOT EXISTS company_metrics (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id       TEXT    NOT NULL UNIQUE,
    company_name     TEXT    NOT NULL,
    avg_jobs_7d      REAL,
    avg_jobs_30d     REAL,
    growth_rate_7d   REAL,
    growth_rate_30d  REAL,
    current_trend    TEXT,
    last_updated     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


_JOB_ENRICHMENTS_DDL = """
CREATE TABLE IF NOT EXISTS job_enrichments (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    source                    TEXT    NOT NULL,
    source_id                 TEXT    NOT NULL,
    seniority                 TEXT,
    years_experience_required INTEGER,
    required_skills           TEXT,           -- JSON array
    remote_type               TEXT,
    salary_hkd_min            INTEGER,
    salary_hkd_max            INTEGER,
    job_category              TEXT,
    enriched_at               TIMESTAMP,
    model_used                TEXT DEFAULT 'deepseek-chat',
    UNIQUE (source, source_id),
    FOREIGN KEY (source, source_id) REFERENCES jobs (source, source_id)
);
"""


def migrate_to_phase_11(db_path: str) -> None:
    """
    Create job_history and company_metrics tables if they don't already exist.

    Safe to call on every startup — uses CREATE TABLE IF NOT EXISTS so it
    only does work the first time.
    """
    conn = sqlite3.connect(db_path)
    try:
        existing = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        with conn:
            conn.execute(_JOB_HISTORY_DDL)
            conn.execute(_COMPANY_METRICS_DDL)

        created = [t for t in ("job_history", "company_metrics") if t not in existing]
        if created:
            logger.info("Phase 11 migration: created tables: %s", ", ".join(created))
        else:
            logger.debug("Phase 11 migration: tables already exist")
    finally:
        conn.close()


def migrate_to_phase_12(db_path: str) -> None:
    """Create job_enrichments table if it doesn't already exist."""
    conn = sqlite3.connect(db_path)
    try:
        existing = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        with conn:
            conn.execute(_JOB_ENRICHMENTS_DDL)
        if "job_enrichments" not in existing:
            logger.info("Phase 12 migration: created table job_enrichments")
        else:
            logger.debug("Phase 12 migration: job_enrichments already exists")
    finally:
        conn.close()


def migrate_to_phase_13(db_path: str) -> None:
    """
    Add scraped_under_slug column to jobs table.

    This column records which company's JobsDB page a job was found on.
    For direct ATS sources (Workday, Eightfold) it equals company_slug.
    For JobsDB it may differ: a job whose true advertiser is AIA can appear
    on the Manulife page, giving company='AIA International Limited' but
    scraped_under_slug='manulife-hk'. That provenance is useful for auditing
    data quality and understanding which employers cross-post on JobsDB.
    """
    conn = sqlite3.connect(db_path)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
        if "scraped_under_slug" not in cols:
            with conn:
                conn.execute("ALTER TABLE jobs ADD COLUMN scraped_under_slug TEXT")
            logger.info("Phase 13 migration: added scraped_under_slug column to jobs")
        else:
            logger.debug("Phase 13 migration: scraped_under_slug already exists")
    finally:
        conn.close()


def migrate_to_phase_14(db_path: str) -> None:
    """
    Add AI salary-estimate columns to job_enrichments.

    These hold DeepSeek's *estimated* HK market salary (HKD per month), distinct
    from salary_hkd_min / salary_hkd_max which hold *disclosed* salaries (almost
    always NULL — <5% of postings publish pay). The estimate is produced in the
    same enrichment call (no extra API cost) from role, seniority, company tier
    and sector. Confidence is one of low / medium / high.
    """
    conn = sqlite3.connect(db_path)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(job_enrichments)").fetchall()}
        added = []
        with conn:
            if "salary_estimated_min" not in cols:
                conn.execute("ALTER TABLE job_enrichments ADD COLUMN salary_estimated_min INTEGER")
                added.append("salary_estimated_min")
            if "salary_estimated_max" not in cols:
                conn.execute("ALTER TABLE job_enrichments ADD COLUMN salary_estimated_max INTEGER")
                added.append("salary_estimated_max")
            if "salary_estimated_confidence" not in cols:
                conn.execute("ALTER TABLE job_enrichments ADD COLUMN salary_estimated_confidence TEXT")
                added.append("salary_estimated_confidence")
        if added:
            logger.info("Phase 14 migration: added columns to job_enrichments: %s", ", ".join(added))
        else:
            logger.debug("Phase 14 migration: salary_estimated columns already exist")
    finally:
        conn.close()


def migrate_to_phase_15(db_path: str) -> None:
    """
    Add description_summary column to job_enrichments.

    Holds a short (<= 3 sentence, ~50 word) neutral prose summary of the job
    description, produced by the SAME DeepSeek enrichment call (no extra API
    pass) for display on job cards. It is an empty string when the posting has
    no description (e.g. Indeed listing-only rows) — never hallucinated.

    Deliberately a NEW column: the full description on the jobs table
    (description_raw / description_clean) is left untouched, because the salary /
    skills / seniority enrichment still depends on it.
    """
    conn = sqlite3.connect(db_path)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(job_enrichments)").fetchall()}
        if "description_summary" not in cols:
            with conn:
                conn.execute("ALTER TABLE job_enrichments ADD COLUMN description_summary TEXT")
            logger.info("Phase 15 migration: added description_summary column to job_enrichments")
        else:
            logger.debug("Phase 15 migration: description_summary already exists")
    finally:
        conn.close()


def migrate_to_phase_16(db_path: str) -> None:
    """
    Add source_tier and extraction_confidence columns to the jobs table.

    - source_tier: 'mainstream' (Workday/Eightfold/JobsDB/Indeed) or 'boutique'
      (longtail companies scraped via LLM extraction). Existing rows default to
      'mainstream'.
    - extraction_confidence: 0.0-1.0 LLM extraction score; NULL for non-LLM sources.

    Same jobs table, same upsert/dedup logic — no other schema change.
    """
    conn = sqlite3.connect(db_path)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
        added = []
        with conn:
            if "source_tier" not in cols:
                conn.execute(
                    "ALTER TABLE jobs ADD COLUMN source_tier TEXT NOT NULL DEFAULT 'mainstream'"
                )
                added.append("source_tier")
            if "extraction_confidence" not in cols:
                conn.execute("ALTER TABLE jobs ADD COLUMN extraction_confidence REAL")
                added.append("extraction_confidence")
        if added:
            logger.info("Phase 16 migration: added columns to jobs: %s", ", ".join(added))
        else:
            logger.debug("Phase 16 migration: source_tier / extraction_confidence already exist")
    finally:
        conn.close()


def migrate_to_phase_17(db_path: str) -> None:
    """
    Add the category column to the jobs table.

    Holds a boutique company's business category taken from the company config
    (NOT LLM-extracted) — e.g. 'Asset Management', 'Audit firm', 'Insurance
    Company', 'Investment Banking', 'Securities Brokerage', 'Fintech-*'. NULL for
    mainstream sources. Lets the frontend filter the boutique/"Exclusive" section
    by category.
    """
    conn = sqlite3.connect(db_path)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
        if "category" not in cols:
            with conn:
                conn.execute("ALTER TABLE jobs ADD COLUMN category TEXT")
            logger.info("Phase 17 migration: added category column to jobs")
        else:
            logger.debug("Phase 17 migration: category already exists")
    finally:
        conn.close()
