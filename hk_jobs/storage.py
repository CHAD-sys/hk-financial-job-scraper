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
import logging
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from hk_jobs.schema import Job, jobs_to_jsonl

logger = logging.getLogger(__name__)

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

    -- Provenance (Phase 13)
    -- The company_slug of the page this job was scraped from.  For direct ATS
    -- sources (Workday, Eightfold) this equals company_slug.  For JobsDB it
    -- may differ when a company's page surfaces third-party listings.
    scraped_under_slug TEXT,

    -- Extraction track (Phase 16 — Longtail LLM extraction)
    source_tier      TEXT NOT NULL DEFAULT 'mainstream',  -- 'mainstream' | 'boutique'
    extraction_confidence REAL,                            -- 0.0-1.0 (LLM), NULL otherwise

    -- Boutique business category from company config (Phase 17), NOT LLM-extracted
    category         TEXT,

    -- Cross-source apply routing (Phase 19).  apply_url is '' unless this vacancy
    -- was also found on another source, in which case reconcile_cross_posted()
    -- sets it to the highest-priority source's URL (eFinancialCareers first).
    apply_url        TEXT NOT NULL DEFAULT '',
    cross_posted     INTEGER NOT NULL DEFAULT 0,   -- SQLite: 1/0 for boolean
    -- Phase 20: the row to display for a cross-posted vacancy (richest source);
    -- 0 hides the duplicate copy. Managed by reconcile_cross_posted().
    is_primary       INTEGER NOT NULL DEFAULT 1,

    -- Per-board market signals (Phase 21): JSON blob of demand / promotion /
    -- urgency / reposts / expiry / employer-reputation fields, board-specific.
    board_signals    TEXT NOT NULL DEFAULT '{}',

    PRIMARY KEY (source, source_id)
);
"""

_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_jobs_company_slug ON jobs (company_slug);",
    "CREATE INDEX IF NOT EXISTS idx_jobs_dedup_hash   ON jobs (dedup_hash);",
    "CREATE INDEX IF NOT EXISTS idx_jobs_is_active    ON jobs (is_active);",
    "CREATE INDEX IF NOT EXISTS idx_jobs_seniority    ON jobs (seniority);",
    # Phase 19: reconcile_cross_posted() groups active rows by dedup_hash and
    # mark_inactive_for_run() now filters by source as well as company_slug.
    "CREATE INDEX IF NOT EXISTS idx_jobs_source       ON jobs (source);",
]

# ── Cross-source apply priority (Phase 19) ─────────────────────────────────────
# When one vacancy is found on several sources, its apply_url points at the
# URL of the FIRST source in this list that is present in the group. Sources not
# listed rank last (in the order they were seen). Edit this list to change
# apply-link preference globally.
#
# Ordering rationale (per the product directive):
#     1. longtail — boutique roles (source_tier="boutique") take top apply priority.
#   2-3. workday / eightfold — the company's OWN ATS (its real careers page), the
#        best apply target after boutique.
#   4-7. efinancialcareers → linkedin → indeed → jobsdb — the aggregator fallback
#        order for roles with no boutique/own-ATS copy.
_SOURCE_PRIORITY: tuple[str, ...] = (
    "longtail",
    "workday",
    "eightfold",
    "efinancialcareers",
    "linkedin",
    "indeed",
    "jobsdb",
    # linkedin_posts (LP-3 "Secret Market") is deliberately LAST: apply-routing
    # must always prefer a real ATS/board listing over a recruiter's post when
    # the same vacancy exists on both (PLAN_LINKEDIN_POSTS.md decision record).
    "linkedin_posts",
)


def _preferred_apply_url(members: list[sqlite3.Row]) -> str:
    """Return the URL of the highest-priority source among cross-posted copies."""
    def rank(row: sqlite3.Row) -> int:
        src = row["source"]
        return _SOURCE_PRIORITY.index(src) if src in _SOURCE_PRIORITY else len(_SOURCE_PRIORITY)

    return min(members, key=rank)["url"]


# ── Cross-source DISPLAY priority (Phase 20) ───────────────────────────────────
# Which copy of a cross-posted vacancy the web app shows. Distinct from the apply
# priority above: we apply on eFinancialCareers, but we DISPLAY the richest record.
# JobsDB first — per the product decision, and because JobsDB rows carry both a
# full description AND the DeepSeek enrichment (skills/summary). LinkedIn ranks
# above indeed because LinkedIn rows now carry a fetched description + summary,
# whereas indeed is listing-only (no description). The suppressed copies get
# is_primary=0.
_DISPLAY_PRIORITY: tuple[str, ...] = (
    "jobsdb",
    "eightfold",
    "workday",
    "efinancialcareers",
    "longtail",
    "linkedin",
    "indeed",
    # Same reasoning as _SOURCE_PRIORITY above: never show the thin/confidential
    # post copy over a real board listing when both exist for the same vacancy.
    "linkedin_posts",
)


def _primary_rowid(members: list[sqlite3.Row]) -> int:
    """rowid of the copy to display (highest display priority) among a group."""
    def rank(row: sqlite3.Row) -> int:
        src = row["source"]
        return _DISPLAY_PRIORITY.index(src) if src in _DISPLAY_PRIORITY else len(_DISPLAY_PRIORITY)

    return min(members, key=rank)["rowid"]


_TITLE_NOISE_RE = re.compile(r"[^a-z0-9]+")

# How much title-word overlap counts as "the same vacancy on two boards". Fuzzy
# (not exact string) so different phrasings of the SAME role match — reordering
# ("Product Manager, Banking" vs "Banking Product Manager") and tiny wording
# differences. Set high (0.8) on purpose: a single distinguishing word usually
# means a DIFFERENT role — "App Development Manager (Cloud)" vs "(E-Banking)",
# "System Admin (Linux)" vs "(Windows)" — and a lower bar collapsed those. At
# 0.85 a one-word specialization keeps roles apart while reordering still matches.
# (0.8 was too low: a spec-less "System Admin Manager" (4 words) still reached a
# "...Manager (Cloud)" (5 words) at 4/5=0.8 and chained distinct specializations
# together through transitivity; 0.85 breaks that bridge.)
_FUZZY_TITLE_THRESHOLD = 0.85

# Seniority/rank words that MUST agree before two titles are treated as the same
# role. This stops the fuzzy match from collapsing different levels of the same
# job — "Analyst" vs "Senior Analyst", "Manager" vs "Assistant Manager" — which
# a raw word-overlap score would otherwise merge.
_LEVEL_TOKENS = frozenset({
    "senior", "junior", "assistant", "deputy", "vice", "president", "vp", "avp",
    "svp", "evp", "head", "chief", "lead", "principal", "director", "executive",
    "intern", "internship", "graduate", "trainee",
})


def _title_tokens(title: str) -> frozenset[str]:
    """Word set of a title (lowercased, punctuation folded) for overlap scoring."""
    return frozenset(t for t in _TITLE_NOISE_RE.sub(" ", title.lower()).split() if t)


def _titles_match(a: frozenset[str], b: frozenset[str], a_lvl: frozenset[str],
                  b_lvl: frozenset[str]) -> bool:
    """True if two token sets are the same vacancy: same seniority + enough overlap."""
    if not a or not b:
        return a == b
    if a_lvl != b_lvl:               # different seniority → different role
        return False
    return len(a & b) / len(a | b) >= _FUZZY_TITLE_THRESHOLD


def _cluster_by_title(members: list[sqlite3.Row]) -> list[list[sqlite3.Row]]:
    """
    Group a company's rows into vacancies by fuzzy title match (union-find).

    Two rows join a cluster when _titles_match. Only called for companies whose
    rows span more than one source, so the O(n^2) comparison stays cheap.
    """
    from collections import defaultdict

    n = len(members)
    toks = [_title_tokens(m["title"]) for m in members]
    lvls = [t & _LEVEL_TOKENS for t in toks]
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(n):
        if not toks[i]:
            continue
        for j in range(i + 1, n):
            if _titles_match(toks[i], toks[j], lvls[i], lvls[j]):
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[ri] = rj

    clusters: dict[int, list[sqlite3.Row]] = defaultdict(list)
    for i, m in enumerate(members):
        clusters[find(i)].append(m)
    return list(clusters.values())

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
    posted_at, fetched_at, is_active,
    scraped_under_slug,
    source_tier, extraction_confidence, category,
    apply_url, cross_posted, board_signals
) VALUES (
    :source, :source_id, :company, :company_slug, :url, :dedup_hash,
    :title, :description_raw, :description_clean,
    :locations, :remote_type,
    :department, :seniority, :employment_type,
    :salary_min, :salary_max, :salary_currency,
    :skills_required, :skills_preferred, :years_experience_min,
    :posted_at, :fetched_at, 1,
    :scraped_under_slug,
    :source_tier, :extraction_confidence, :category,
    :apply_url, :cross_posted, :board_signals
)
ON CONFLICT (source, source_id) DO UPDATE SET
    title              = excluded.title,
    -- Preserve previously-fetched descriptions. Listing-only scrapes carry an
    -- empty description; without this guard every re-scrape would wipe the
    -- descriptions populated by the separate --fetch-descriptions pass, forcing
    -- a full daily re-fetch. NULLIF(...,'') turns an empty incoming value into
    -- NULL so COALESCE falls back to the existing stored value.
    description_raw    = COALESCE(NULLIF(excluded.description_raw, ''), jobs.description_raw),
    description_clean  = COALESCE(NULLIF(excluded.description_clean, ''), jobs.description_clean),
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
    is_active          = 1,
    -- Backfill provenance for rows that pre-date Phase 13 (NULL → new value).
    -- Never overwrite a previously-set scraped_under_slug.
    scraped_under_slug = COALESCE(jobs.scraped_under_slug, excluded.scraped_under_slug),
    source_tier        = excluded.source_tier,
    extraction_confidence = excluded.extraction_confidence,
    category           = excluded.category,
    -- Refresh board signals on every scrape, but never let an empty '{}' from a
    -- lighter re-scrape wipe previously-captured signals.
    board_signals      = CASE WHEN excluded.board_signals IN ('', '{}')
                              THEN jobs.board_signals ELSE excluded.board_signals END
    -- NOTE: apply_url and cross_posted are intentionally NOT updated here. A
    -- daily scrape re-inserts each job with the default ('' / 0); the correct
    -- values are (re)computed by reconcile_cross_posted() at the end of the run,
    -- so leaving them stable on upsert avoids a scrape wiping a set apply_url.
    -- NOTE: company is intentionally NOT updated here. The correct advertiser
    -- name is set on INSERT from the card HTML (Fix A), and repaired for
    -- existing rows by --repair-companies (GraphQL advertiser.name).
    -- Leaving company stable on re-scrape prevents a card-extraction fallback
    -- from overwriting a correct company set by a prior repair pass.
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
        # check_same_thread=False lets worker threads reuse this connection;
        # callers must serialise writes with a threading.Lock (pipeline.py does this).
        self._conn = sqlite3.connect(path, check_same_thread=False)
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

    def mark_inactive_for_run(
        self,
        company_slug: str,
        fetched_at: datetime,
        new_job_count: int = None,
        source: str | None = None,
    ) -> int:
        """
        Soft-delete jobs for a company that were NOT seen in this run.

        After we finish scraping a company we call this with the timestamp
        used for fetched_at during that run. Any row for this company whose
        fetched_at is OLDER than the run timestamp is a job that disappeared
        — it was active before but wasn't returned by the ATS this time.
        We mark it inactive rather than deleting it (see module docstring
        for why).

        source: when given, only rows from THIS source are considered. This
        matters once a company is scraped from more than one source under the
        same company_slug (e.g. a JobsDB entry AND an eFinancialCareers entry
        both using slug 'aia-hk'): without the source filter, finishing the
        JobsDB scrape would wrongly deactivate the company's eFC rows (and vice
        versa). Left as None for single-source companies → old behaviour.

        Safety check: if new_job_count is 0 or suspiciously low (< 30% of
        historical average), skip deactivation — likely a transient scrape
        failure (e.g. Cloudflare block) rather than jobs actually disappearing.

        Returns the number of rows deactivated.
        """
        # Safety: never deactivate if scrape returned 0 jobs (likely Cloudflare block)
        if new_job_count == 0:
            logger.warning(
                "%s: returned 0 jobs — skipping deactivation. "
                "Likely transient block (Cloudflare, rate-limit). Jobs remain active.",
                company_slug,
            )
            return 0

        # Check historical average for this company (scoped to this source when given)
        if new_job_count is not None:
            src_clause = "AND source = ?" if source is not None else ""
            params = (company_slug, fetched_at.isoformat())
            if source is not None:
                params = (company_slug, source, fetched_at.isoformat())
            row = self._conn.execute(
                f"""
                SELECT AVG(CAST(active_count AS FLOAT)) as avg_count
                FROM (
                    SELECT SUM(is_active) as active_count
                    FROM jobs
                    WHERE company_slug = ?
                    {src_clause}
                    AND fetched_at < ?
                    GROUP BY DATE(fetched_at)
                    ORDER BY DATE(fetched_at) DESC
                    LIMIT 7
                )
                """,
                params,
            ).fetchone()

            if row and row["avg_count"]:
                historical_avg = row["avg_count"]
                # If new count is < 30% of average, likely a failed scrape
                if new_job_count < (historical_avg * 0.3):
                    logger.warning(
                        "%s: got %d jobs vs avg %.0f (%.1f%% of average) — "
                        "skipping deactivation. Likely transient scrape failure.",
                        company_slug, new_job_count, historical_avg,
                        (new_job_count / historical_avg * 100) if historical_avg else 0,
                    )
                    return 0

        fetched_iso = fetched_at.isoformat()
        src_clause = "AND source = ?" if source is not None else ""
        params = (
            (company_slug, source, fetched_iso)
            if source is not None
            else (company_slug, fetched_iso)
        )
        cursor = self._conn.execute(
            f"""
            UPDATE jobs
               SET is_active = 0
             WHERE company_slug = ?
               {src_clause}
               AND is_active    = 1
               AND fetched_at   < ?
            """,
            params,
        )
        self._conn.commit()
        return cursor.rowcount

    def reconcile_cross_posted(self) -> tuple[int, int]:
        """
        Detect vacancies that appear on more than one source and set apply_url.

        The same role is often posted on several sites (e.g. eFinancialCareers
        AND JobsDB). This pass groups a company's ACTIVE jobs into vacancies by
        FUZZY title match (_cluster_by_title — word-overlap with a seniority guard,
        location-independent) and, for any cluster spanning more than one distinct
        source:

          - sets cross_posted = 1 on every copy, and
          - sets apply_url on every copy to the highest-priority source's URL
            (see _SOURCE_PRIORITY — eFinancialCareers first), so the frontend can
            always send an applicant to the preferred site while still showing
            that the role was found on multiple boards.

        It also sets is_primary for display de-duplication: within a cross-posted
        group exactly one copy — the richest source (see _DISPLAY_PRIORITY, JobsDB
        first: it carries the description AND the DeepSeek enrichment) — keeps
        is_primary=1 and the other copies get 0, so the web app shows one card per
        vacancy (with apply_url still pointing at eFinancialCareers). De-dup only
        applies across DIFFERENT sources; two rows from the SAME source that happen
        to share a normalised title are both left visible (they are usually
        distinct roles, not a cross-post).

        Groups on a single source are reset to (apply_url='', cross_posted=0,
        is_primary=1) so the pass is fully idempotent: if a role stops being
        cross-posted (its eFC copy disappears), the leftover routing is cleared on
        the next run. Only rows whose value actually changes are written.

        Returns (cross_posted_groups, rows_updated).
        """
        from collections import defaultdict

        rows = self._conn.execute(
            "SELECT rowid, company_slug, title, source, url, apply_url, cross_posted, is_primary "
            "FROM jobs WHERE is_active = 1"
        ).fetchall()

        by_company: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for r in rows:
            by_company[r["company_slug"]].append(r)

        # (apply_url, cross_posted, is_primary, rowid)
        updates: list[tuple[str, int, int, int]] = []
        cross_groups = 0
        for company_rows in by_company.values():
            # Fast path: a company scraped from a single source can't cross-post;
            # skip the O(n^2) title clustering and just reset routing to defaults.
            if len({m["source"] for m in company_rows}) <= 1:
                clusters: list[list[sqlite3.Row]] = [company_rows]
            else:
                clusters = _cluster_by_title(company_rows)

            for members in clusters:
                if len({m["source"] for m in members}) > 1:
                    cross_groups += 1
                    preferred = _preferred_apply_url(members)
                    primary = _primary_rowid(members)
                    for m in members:
                        is_primary = 1 if m["rowid"] == primary else 0
                        if (m["apply_url"] != preferred or m["cross_posted"] != 1
                                or m["is_primary"] != is_primary):
                            updates.append((preferred, 1, is_primary, m["rowid"]))
                else:
                    for m in members:
                        if m["apply_url"] != "" or m["cross_posted"] != 0 or m["is_primary"] != 1:
                            updates.append(("", 0, 1, m["rowid"]))

        if updates:
            with self._conn:
                self._conn.executemany(
                    "UPDATE jobs SET apply_url = ?, cross_posted = ?, is_primary = ? "
                    "WHERE rowid = ?",
                    updates,
                )
        self.refresh_signal_flags()
        return cross_groups, len(updates)

    def refresh_signal_flags(self) -> None:
        """
        Recompute the indexed grp_new / grp_urgent / grp_applicants columns from
        board_signals, aggregated across each vacancy's cross-post group.

        Run once here (after reconciliation) rather than per web request: filtering
        the JSON with a correlated group subquery was ~15-45 s per page; this makes
        the web filters plain indexed lookups (<1 ms). A vacancy is flagged if ANY
        board copy carries the signal; grp_applicants is the highest known count
        across boards (NULL when no board reports one). Guards missing columns so it
        is a no-op on a pre-Phase-22 DB.
        """
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(jobs)")}
        if not {"grp_new", "grp_urgent", "grp_applicants"} <= cols:
            return
        # A copy "g" is in row j's group when it is j itself or a cross-post sharing
        # the apply_url group key. The IN-subqueries below are materialised once and
        # hit the apply_url index, so the whole refresh is a handful of set updates.
        with self._conn:
            self._conn.execute(
                "UPDATE jobs SET grp_new = 0, grp_urgent = 0, grp_applicants = NULL "
                "WHERE is_active = 1"
            )
            for col, path in (("grp_new", "$.new_job"), ("grp_urgent", "$.urgently_hiring")):
                self._conn.execute(
                    f"UPDATE jobs SET {col} = 1 WHERE is_active = 1 AND is_primary = 1 AND ("
                    f"  json_extract(board_signals, '{path}') = 1"
                    f"  OR (cross_posted = 1 AND apply_url IN ("
                    f"       SELECT apply_url FROM jobs WHERE is_active = 1 AND cross_posted = 1"
                    f"       AND json_extract(board_signals, '{path}') = 1)))"
                )
            self._conn.execute(
                "UPDATE jobs SET grp_applicants = ("
                "  SELECT MAX(CAST(json_extract(g.board_signals, '$.applicant_count') AS INTEGER))"
                "    FROM jobs g WHERE g.is_active = 1"
                "    AND ((g.source = jobs.source AND g.source_id = jobs.source_id)"
                "         OR (jobs.cross_posted = 1 AND g.cross_posted = 1 AND g.apply_url = jobs.apply_url))"
                "    AND json_extract(g.board_signals, '$.applicant_count') IS NOT NULL) "
                "WHERE is_active = 1 AND is_primary = 1"
            )

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
        "scraped_under_slug": job.scraped_under_slug,
        "source_tier": job.source_tier,
        "extraction_confidence": job.extraction_confidence,
        "category": job.category,
        "apply_url": job.apply_url,
        "cross_posted": int(job.cross_posted),
        "board_signals": json.dumps(job.board_signals or {}),
    }


def _row_to_job(row: sqlite3.Row) -> Job:
    """Reconstruct a Job from a SQLite row (inverse of _job_to_row)."""
    # scraped_under_slug was added in Phase 13 — guard against pre-migration rows.
    try:
        scraped_under_slug = row["scraped_under_slug"]
    except IndexError:
        scraped_under_slug = None
    # source_tier / extraction_confidence added in Phase 16 — guard likewise.
    try:
        source_tier = row["source_tier"] or "mainstream"
    except IndexError:
        source_tier = "mainstream"
    try:
        extraction_confidence = row["extraction_confidence"]
    except IndexError:
        extraction_confidence = None
    # category added in Phase 17 — guard likewise.
    try:
        category = row["category"]
    except IndexError:
        category = None
    # apply_url / cross_posted added in Phase 19 — guard likewise.
    try:
        apply_url = row["apply_url"] or ""
    except IndexError:
        apply_url = ""
    try:
        cross_posted = bool(row["cross_posted"])
    except IndexError:
        cross_posted = False
    # board_signals added in Phase 21 — guard against pre-migration rows.
    try:
        board_signals = json.loads(row["board_signals"] or "{}")
    except (IndexError, TypeError, json.JSONDecodeError):
        board_signals = {}

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
        scraped_under_slug=scraped_under_slug,
        source_tier=source_tier,
        extraction_confidence=extraction_confidence,
        category=category,
        apply_url=apply_url,
        cross_posted=cross_posted,
        board_signals=board_signals,
    )
