"""
Database migrations for hk_jobs.

WHY THERE IS A LEDGER
---------------------
There was no record of what had run. Nineteen idempotent functions existed, and
knowing whether a database was up to date meant reading `pipeline.main()` and
comparing its import list against the `def`s in this file by eye. That went
wrong in the three ways you would expect:

  - **The list drifted.** Phases 27 and 28 were never added to it. They ran only
    inside `--promote-posts` and `--harvest-recruiter-emails`, so a database
    that had never been asked to do either was missing columns nothing would
    tell you about.
  - **Every mode re-derived its own subset.** Five separate branches called
    `migrate_to_phase_26` before doing their work, each one a guess at its own
    prerequisites.
  - **A fresh database could not be built at all.** Seven migrations
    `ALTER TABLE jobs`, but `jobs` is created by `JobStore`, which `main()` did
    not reach until after the migrations had already failed. Phase 10 below is
    that missing first step.

`MIGRATIONS` is now the single ordered list, and `migrate()` applies whatever a
given database has not recorded yet. Each function is still idempotent — that
property is what lets an existing database (which has every migration applied
and no ledger) converge safely on its next run: everything is re-applied as a
no-op, then recorded, and subsequent runs skip it.

ADDING A MIGRATION
------------------
Write `migrate_to_phase_NN(db_path)` and append `(NN, migrate_to_phase_NN)` to
`MIGRATIONS`. Nothing else. Never edit a migration that has already been
applied somewhere — the ledger means it will not run again, so the edit would
land on new databases only.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable

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


def migrate_to_phase_10(db_path: str) -> None:
    """
    Create the `jobs` table and its indexes — the base schema.

    Numbered 10 because it is what existed before phase 11: the shape every
    later `ALTER TABLE jobs` migration assumes. It lived in `JobStore.__init__`
    only, which meant it ran after the migrations rather than before them, and
    a database that did not already exist could not be migrated.
    """
    from hk_jobs.storage import ensure_schema

    ensure_schema(db_path)


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


def migrate_to_phase_18(db_path: str) -> None:
    """
    Add title_en column to job_enrichments.

    Holds an English version of the job title, produced by the SAME DeepSeek
    enrichment call (no extra API pass). Many boutique/"Exclusive" postings have
    Traditional/Simplified Chinese titles; title_en carries a faithful English
    translation, or the original title verbatim when it is already English.

    Deliberately a NEW column: the original title on the jobs table is left
    untouched so the source-language title is always preserved. The frontend
    displays title_en when present and falls back to the original title.
    """
    conn = sqlite3.connect(db_path)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(job_enrichments)").fetchall()}
        if "title_en" not in cols:
            with conn:
                conn.execute("ALTER TABLE job_enrichments ADD COLUMN title_en TEXT")
            logger.info("Phase 18 migration: added title_en column to job_enrichments")
        else:
            logger.debug("Phase 18 migration: title_en already exists")
    finally:
        conn.close()


def migrate_to_phase_19(db_path: str) -> None:
    """
    Add cross-source apply-routing columns to the jobs table.

    - apply_url: the preferred URL for a candidate to apply. Empty string means
      "use the row's own `url`". It is filled by JobStore.reconcile_cross_posted()
      when the same vacancy (same dedup_hash) is found on more than one source:
      every copy's apply_url is set to the highest-priority source's URL, with
      eFinancialCareers ranked first (the "migrate priority to eFC" requirement).
    - cross_posted: 1 when this exact vacancy was found on more than one source
      (e.g. both eFinancialCareers AND JobsDB), 0 otherwise.

    Both default so existing rows behave exactly as before (apply_url='' → apply
    at `url`, cross_posted=0) until the next reconciliation pass runs.
    """
    conn = sqlite3.connect(db_path)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
        added = []
        with conn:
            if "apply_url" not in cols:
                conn.execute("ALTER TABLE jobs ADD COLUMN apply_url TEXT NOT NULL DEFAULT ''")
                added.append("apply_url")
            if "cross_posted" not in cols:
                conn.execute("ALTER TABLE jobs ADD COLUMN cross_posted INTEGER NOT NULL DEFAULT 0")
                added.append("cross_posted")
        if added:
            logger.info("Phase 19 migration: added columns to jobs: %s", ", ".join(added))
        else:
            logger.debug("Phase 19 migration: apply_url / cross_posted already exist")
    finally:
        conn.close()


def migrate_to_phase_20(db_path: str) -> None:
    """
    Add the is_primary display flag to the jobs table.

    When one vacancy is cross-posted (e.g. on JobsDB AND eFinancialCareers) there
    are two rows. The web app must show only ONE card. is_primary marks the row to
    display (the richest source — JobsDB first: it carries the description AND the
    DeepSeek enrichment), set by JobStore.reconcile_cross_posted(). The suppressed
    duplicate keeps is_primary=0. Singletons are 1. The apply_url on the displayed
    row still points at eFinancialCareers (see reconcile_cross_posted). Defaults to
    1 so every existing row shows until the next reconciliation pass runs.
    """
    conn = sqlite3.connect(db_path)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
        if "is_primary" not in cols:
            with conn:
                conn.execute("ALTER TABLE jobs ADD COLUMN is_primary INTEGER NOT NULL DEFAULT 1")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_is_primary ON jobs (is_primary)")
            logger.info("Phase 20 migration: added is_primary column to jobs")
        else:
            logger.debug("Phase 20 migration: is_primary already exists")
    finally:
        conn.close()


def migrate_to_phase_21(db_path: str) -> None:
    """
    Add board_signals — a JSON blob of per-board market signals (P2/P3).

    Each adapter fills whatever its payload exposes beyond the core Job fields:
    demand (applicant/apply counts), promotion (sponsored/paid/featured/highlighted),
    urgency, reposts, expiry, employer reputation (rating/reviews/responsive),
    parent company, geo coordinates, last-updated. Stored as JSON so a heterogeneous,
    board-specific set costs one column and stays fully queryable via json_extract.
    """
    conn = sqlite3.connect(db_path)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
        if "board_signals" not in cols:
            with conn:
                conn.execute("ALTER TABLE jobs ADD COLUMN board_signals TEXT NOT NULL DEFAULT '{}'")
            logger.info("Phase 21 migration: added board_signals column to jobs")
        else:
            logger.debug("Phase 21 migration: board_signals already exists")
    finally:
        conn.close()


def migrate_to_phase_22(db_path: str) -> None:
    """
    Add pre-computed, indexed signal-flag columns for fast web filtering.

    Filtering on board_signals JSON directly is O(n²) (a correlated subquery per
    row over the cross-post group). Instead we precompute per-vacancy aggregates
    once, at reconcile time (see JobStore.refresh_signal_flags), into indexed
    columns the web app filters on instantly:
      grp_new        = any board copy is newly posted
      grp_urgent     = any board copy is urgently hiring
      grp_applicants = highest applicant count across boards (NULL if unknown)
    Plus an index on apply_url (the cross-post group key).
    """
    conn = sqlite3.connect(db_path)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
        with conn:
            if "grp_new" not in cols:
                conn.execute("ALTER TABLE jobs ADD COLUMN grp_new INTEGER NOT NULL DEFAULT 0")
            if "grp_urgent" not in cols:
                conn.execute("ALTER TABLE jobs ADD COLUMN grp_urgent INTEGER NOT NULL DEFAULT 0")
            if "grp_applicants" not in cols:
                conn.execute("ALTER TABLE jobs ADD COLUMN grp_applicants INTEGER")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_apply_url ON jobs(apply_url)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_grp_new ON jobs(grp_new)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_grp_urgent ON jobs(grp_urgent)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_grp_applicants ON jobs(grp_applicants)")
        logger.info("Phase 22 migration: added grp_new/grp_urgent/grp_applicants + indexes")
    finally:
        conn.close()


def migrate_to_phase_23(db_path: str) -> None:
    """
    Add prompt_version column to job_enrichments.

    Tracks which enricher prompt/model version produced each row (see
    hk_jobs.enrichers.deepseek.PROMPT_VERSION). Without this, a job that gets
    soft-deleted and later reactivated keeps whatever salary estimate it had from
    whenever it was last enriched — potentially predating a prompt or model
    change — because the default (non re-enrich) enrichment pass only looks at
    whether a row has *any* enrichment, not whether it's current. Comparing this
    column against the live PROMPT_VERSION lets the regular daily enrichment pass
    catch and refresh stale rows on its own.
    """
    conn = sqlite3.connect(db_path)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(job_enrichments)").fetchall()}
        with conn:
            if "prompt_version" not in cols:
                conn.execute("ALTER TABLE job_enrichments ADD COLUMN prompt_version TEXT")
        if "prompt_version" not in cols:
            logger.info("Phase 23 migration: added prompt_version column to job_enrichments")
        else:
            logger.debug("Phase 23 migration: prompt_version already exists")
    finally:
        conn.close()


def migrate_to_phase_24(db_path: str) -> None:
    """
    Create the salary_audit_log table.

    Every correction the outlier audit agent (hk_jobs.salary_audit) applies — and
    every upward suggestion it declines to apply — is recorded here so changes to
    published salary estimates are always traceable to a reason, never silent.
    """
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS salary_audit_log (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    source      TEXT NOT NULL,
                    source_id   TEXT NOT NULL,
                    audited_at  TEXT NOT NULL,
                    old_min     INTEGER,
                    old_max     INTEGER,
                    new_min     INTEGER,
                    new_max     INTEGER,
                    action      TEXT NOT NULL,   -- 'lowered' | 'flag_up'
                    reason      TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_source ON salary_audit_log(source, source_id)")
        logger.debug("Phase 24 migration: salary_audit_log ready")
    finally:
        conn.close()


def migrate_to_phase_25(db_path: str) -> None:
    """
    Add salary_tier / salary_role columns to job_enrichments.

    DeepSeek classifies both on every call and enrichment.py already uses them
    in-memory to run the deterministic clamp (see EnrichmentPipeline.run), but
    was discarding them afterwards instead of storing them. Without a stored
    tier/role, anything that needs to re-run clamp_salary later — the outlier
    audit agent, a future retroactive re-clamp — has no way to recover the
    per-role ceiling and falls back to weaker company/title-only caps. Rows
    enriched before this migration will have both columns NULL; only rows
    enriched from now on carry them.
    """
    conn = sqlite3.connect(db_path)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(job_enrichments)").fetchall()}
        with conn:
            if "salary_tier" not in cols:
                conn.execute("ALTER TABLE job_enrichments ADD COLUMN salary_tier TEXT")
            if "salary_role" not in cols:
                conn.execute("ALTER TABLE job_enrichments ADD COLUMN salary_role TEXT")
        if "salary_tier" not in cols or "salary_role" not in cols:
            logger.info("Phase 25 migration: added salary_tier/salary_role columns to job_enrichments")
        else:
            logger.debug("Phase 25 migration: salary_tier/salary_role already exist")
    finally:
        conn.close()


def migrate_to_phase_26(db_path: str) -> None:
    """
    Create the LP-2 "Secret Market" ingestion tables: linkedin_posts,
    recruiter_fetch_state, and vendor_costs.

    linkedin_posts is the raw, replayable tier (PLAN_LINKEDIN_POSTS.md §4) —
    every post the vendor returns lands here untouched, including the full
    vendor_payload_json, so extraction (LP-3) can be re-run later without
    re-paying Apify. It is NOT the jobs table: promotion to jobs happens only
    after LP-3's classifier + promotion gate exist.

    recruiter_fetch_state tracks last_fetched_at per recruiters.yaml slug so
    the fetcher can ask for "posts since last success" instead of a fixed
    last-24h window, which would silently create gaps on a missed/delayed
    daily run (see hk_jobs.posts.fetcher module docstring).

    vendor_costs is the running Apify spend ledger backing the $30/mo hard
    cap (PLAN_LINKEDIN_POSTS.md decision #6): hk_jobs.posts.budget checks
    month-to-date cost against it before every call and refuses new calls
    once the cap is hit.
    """
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS linkedin_posts (
                    post_urn            TEXT PRIMARY KEY,
                    recruiter_slug      TEXT NOT NULL,
                    source_run          TEXT NOT NULL,   -- 'watchlist' | 'discovery'
                    author_name         TEXT,
                    author_profile_url  TEXT,
                    post_text           TEXT NOT NULL DEFAULT '',
                    post_url            TEXT,
                    posted_at           TEXT,
                    engagement_likes    INTEGER DEFAULT 0,
                    engagement_comments INTEGER DEFAULT 0,
                    fetched_at          TEXT NOT NULL,
                    vendor_payload_json TEXT NOT NULL,
                    extraction_status   TEXT NOT NULL DEFAULT 'pending'
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_linkedin_posts_recruiter "
                "ON linkedin_posts(recruiter_slug)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_linkedin_posts_status "
                "ON linkedin_posts(extraction_status)"
            )

            conn.execute("""
                CREATE TABLE IF NOT EXISTS recruiter_fetch_state (
                    slug            TEXT PRIMARY KEY,
                    last_fetched_at TEXT,
                    last_status     TEXT,   -- 'ok' | 'error'
                    last_error      TEXT
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS vendor_costs (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    logged_at   TEXT NOT NULL,
                    vendor      TEXT NOT NULL,   -- 'apify'
                    actor       TEXT NOT NULL,   -- e.g. 'harvestapi/linkedin-profile-posts'
                    run_kind    TEXT NOT NULL,   -- 'watchlist' | 'discovery'
                    items       INTEGER NOT NULL,
                    cost_usd    REAL NOT NULL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_vendor_costs_logged_at "
                "ON vendor_costs(logged_at)"
            )
        logger.info("Phase 26 migration: linkedin_posts/recruiter_fetch_state/vendor_costs ready")
    finally:
        conn.close()


def migrate_to_phase_27(db_path: str) -> None:
    """
    Add extraction result columns to linkedin_posts (LP-3).

    Stores the extractor's raw JSON response, its confidence, and the prompt
    version that produced it — same replayability principle as vendor_payload_json
    (phase 26): a prompt/model change can be detected (stored prompt_version !=
    current PROMPT_VERSION) and re-run without re-paying Apify, mirroring how
    job_enrichments.prompt_version (phase 23) lets stale enrichments self-heal.
    """
    conn = sqlite3.connect(db_path)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(linkedin_posts)").fetchall()}
        added = []
        with conn:
            if "extraction_result_json" not in cols:
                conn.execute("ALTER TABLE linkedin_posts ADD COLUMN extraction_result_json TEXT")
                added.append("extraction_result_json")
            if "extraction_confidence" not in cols:
                conn.execute("ALTER TABLE linkedin_posts ADD COLUMN extraction_confidence REAL")
                added.append("extraction_confidence")
            if "extraction_prompt_version" not in cols:
                conn.execute("ALTER TABLE linkedin_posts ADD COLUMN extraction_prompt_version TEXT")
                added.append("extraction_prompt_version")
        if added:
            logger.info("Phase 27 migration: added columns to linkedin_posts: %s", ", ".join(added))
        else:
            logger.debug("Phase 27 migration: extraction columns already exist")
    finally:
        conn.close()


def migrate_to_phase_28(db_path: str) -> None:
    """
    Add email/email_fetched_at columns to recruiter_fetch_state (LP-5 email
    harvest, PLAN_LINKEDIN_POSTS.md decision #10).

    Lives on recruiter_fetch_state (not a new table) since it's already the
    per-recruiter-slug runtime state table (phase 26) — one row per recruiter,
    same key. email_fetched_at lets the harvest skip recruiters with a
    recent-enough email without re-paying the $10/1k email-search rate, and
    supports the plan's "refresh quarterly" cadence later without a schema
    change.
    """
    conn = sqlite3.connect(db_path)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(recruiter_fetch_state)").fetchall()}
        added = []
        with conn:
            if "email" not in cols:
                conn.execute("ALTER TABLE recruiter_fetch_state ADD COLUMN email TEXT")
                added.append("email")
            if "email_fetched_at" not in cols:
                conn.execute("ALTER TABLE recruiter_fetch_state ADD COLUMN email_fetched_at TEXT")
                added.append("email_fetched_at")
        if added:
            logger.info("Phase 28 migration: added columns to recruiter_fetch_state: %s", ", ".join(added))
        else:
            logger.debug("Phase 28 migration: email columns already exist")
    finally:
        conn.close()


def migrate_to_phase_29(db_path: str) -> None:
    """
    Restamp enrichments whose version string only changed SHAPE, not meaning.

    `PROMPT_VERSION` used to be a hand-edited constant. It is now derived from
    the model, the prompt text, the anchor calibration and the clamp's constants
    (see `hk_jobs.salary.version`) — so the string changed for every row even
    though none of those inputs did.

    Without this, the first run after that change would find ~5,000 active rows
    whose stored version no longer matches, decide they are stale, and re-pay
    DeepSeek to reproduce estimates that are already correct.

    Only rows stamped with the exact old tag are touched, and only when the
    derived version still contains that tag — i.e. when the manual part has not
    itself moved on. Anything else is genuinely stale and should re-enrich.
    """
    from hk_jobs.enrichers.deepseek import PROMPT_VERSION
    from hk_jobs.salary import MANUAL_TAG

    if not PROMPT_VERSION.startswith(MANUAL_TAG + "+"):
        logger.debug("Phase 29: manual tag has moved on; leaving stored versions alone.")
        return

    conn = sqlite3.connect(db_path)
    try:
        with conn:
            cur = conn.execute(
                "UPDATE job_enrichments SET prompt_version = ? WHERE prompt_version = ?",
                (PROMPT_VERSION, MANUAL_TAG),
            )
        if cur.rowcount:
            logger.info(
                "Phase 29 migration: restamped %s enrichment(s) from the bare tag to the "
                "derived version — same inputs, so no re-enrichment needed.", cur.rowcount,
            )
        else:
            logger.debug("Phase 29 migration: nothing to restamp.")
    finally:
        conn.close()


# ── The ledger ────────────────────────────────────────────────────────────────

_SCHEMA_MIGRATIONS_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    phase       INTEGER PRIMARY KEY,
    applied_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

#: Every migration, in the order it must run. The ONE list — appending here is
#: the whole of registering a new phase.
#:
#: Order is load-bearing beyond the obvious: 10 creates `jobs` before the seven
#: phases that alter it; 26 creates `linkedin_posts` and `recruiter_fetch_state`
#: before 27 and 28 add columns to them; 12 creates `job_enrichments` before 29
#: restamps rows in it.
MIGRATIONS: tuple[tuple[int, Callable[[str], None]], ...] = (
    (10, migrate_to_phase_10),
    (11, migrate_to_phase_11),
    (12, migrate_to_phase_12),
    (13, migrate_to_phase_13),
    (14, migrate_to_phase_14),
    (15, migrate_to_phase_15),
    (16, migrate_to_phase_16),
    (17, migrate_to_phase_17),
    (18, migrate_to_phase_18),
    (19, migrate_to_phase_19),
    (20, migrate_to_phase_20),
    (21, migrate_to_phase_21),
    (22, migrate_to_phase_22),
    (23, migrate_to_phase_23),
    (24, migrate_to_phase_24),
    (25, migrate_to_phase_25),
    (26, migrate_to_phase_26),
    (27, migrate_to_phase_27),
    (28, migrate_to_phase_28),
    (29, migrate_to_phase_29),
)

LATEST_PHASE = MIGRATIONS[-1][0]


def applied_phases(db_path: str) -> set[int]:
    """
    Which phases this database has recorded.

    Empty for a database that has never been migrated AND for one that was
    migrated before the ledger existed — the two are indistinguishable, which is
    fine precisely because every migration is idempotent: re-applying them all
    on the pre-ledger database is a series of no-ops.
    """
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            conn.execute(_SCHEMA_MIGRATIONS_DDL)
        return {row[0] for row in conn.execute("SELECT phase FROM schema_migrations")}
    finally:
        conn.close()


def migrate(db_path: str) -> list[int]:
    """
    Bring `db_path` up to `LATEST_PHASE`. Returns the phases applied this call.

    The one way to migrate. Callers do not choose which phases they need — that
    was the previous arrangement, and it is how phases 27 and 28 came to be
    missing from the startup path while five separate modes each hand-picked
    phase 26.

    A phase is applied and recorded in the same connection-less step; if one
    raises, the phases before it stay recorded and the run aborts, so the next
    run resumes at the failure rather than starting over.
    """
    done = applied_phases(db_path)
    pending = [(phase, fn) for phase, fn in MIGRATIONS if phase not in done]
    if not pending:
        logger.debug("Schema is current at phase %d.", LATEST_PHASE)
        return []

    logger.info(
        "Applying %d migration(s): %s",
        len(pending), ", ".join(str(p) for p, _ in pending),
    )
    for phase, fn in pending:
        fn(db_path)
        conn = sqlite3.connect(db_path)
        try:
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO schema_migrations (phase) VALUES (?)",
                    (phase,),
                )
        finally:
            conn.close()

    return [phase for phase, _ in pending]
