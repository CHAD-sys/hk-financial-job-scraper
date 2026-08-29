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
import uuid
from collections.abc import Collection, Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hk_jobs.schema import Job, jobs_to_jsonl
from hk_jobs.sources import apply_rank, display_rank

logger = logging.getLogger(__name__)

#: SQLite caps expression-tree depth around 1000, so batched IN (...)
#: clauses are chunked. Same limit and same reason as webapp/backend/job_read.py.
_REF_CHUNK = 200

#: A source's own "new" badge (board_signals.new_job) is a one-time snapshot from
#: whichever scrape first saw it — see refresh_signal_flags(). It never expires on
#: its own, so this is the cap we enforce instead.
_NEW_BADGE_MAX_AGE_DAYS = 14

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

    -- When the Listing stopped being open (Phase 30). NULL for as long as it is
    -- open, and set back to NULL if it reopens, so `closed_at IS NOT NULL` and
    -- `is_active = 0` always agree. Written only by deactivate() and cleared
    -- only by the upsert — nowhere else, which is what keeps them agreeing.
    --
    -- is_active answers "is this Role open"; closed_at answers "for how long has
    -- it not been", and the second question had no answer at all: a Saved Role
    -- that closed last night and one that closed in May were the same row to
    -- every reader. Saved Roles need the difference (docs/adr/0011).
    closed_at       TEXT,                         -- ISO 8601 UTC, NULL while open

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

    -- Phase 38: a stable id for the VACANCY a cross-posted cluster represents,
    -- persisted across runs (unlike is_primary, which is recomputed from
    -- scratch every reconcile_cross_posted() call). NULL for a Role that has
    -- never been cross-posted. Lets a Saved Role whose exact copy has closed
    -- find a still-active sibling instead of wrongly reading as closed (see
    -- docs/adr/0030) — it is a lookup key only, never a Saved Role's own
    -- reference, which stays (source, source_id).
    vacancy_id       TEXT,

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
    # Phase 38: job_read._resolve_vacancy_refs looks up active siblings by
    # vacancy_id for every Saved Roles / jobs_by_refs read.
    "CREATE INDEX IF NOT EXISTS idx_jobs_vacancy_id   ON jobs (vacancy_id);",
]

# ── Cross-source apply priority (Phase 19) ─────────────────────────────────────
# The order itself lives in hk_jobs/sources.py, with every other fact about a
# source, because it used to live here — where the SuccessFactors adapter's
# author had no reason to look, and so did not.


def _preferred_apply_url(members: list[sqlite3.Row]) -> str:
    """Return the URL of the highest-priority source among cross-posted copies."""
    return min(members, key=lambda row: apply_rank(row["source"]))["url"]


def ensure_schema(db_path: str) -> None:
    """
    Create the `jobs` table and its indexes if they are absent.

    The base schema every later migration alters. It used to be reachable only
    by constructing a `JobStore`, which put it AFTER the migrations in `main()`
    — so on a database that did not already exist, the seven `ALTER TABLE jobs`
    migrations died on `no such table: jobs` and the pipeline could not
    bootstrap. `migrations.migrate()` calls this first (as phase 10) so the
    ordering is stated once instead of depending on which object happens to be
    constructed first.
    """
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            conn.execute(_CREATE_TABLE)
            for idx_sql in _CREATE_INDEXES:
                conn.execute(idx_sql)
    finally:
        conn.close()


# ── Cross-source DISPLAY priority (Phase 20) ───────────────────────────────────
# Also in hk_jobs/sources.py — see DISPLAY_ORDER for why it differs from the
# apply order.


def _richness(row: sqlite3.Row) -> tuple[int, int]:
    """(has_description, has_disclosed_salary) — a per-ROW check, standing in
    for what DISPLAY_ORDER otherwise only assumes about a whole source."""
    has_desc = 1 if (row["description_clean"] or "").strip() else 0
    has_salary = 1 if row["salary_min"] is not None else 0
    return has_desc, has_salary


def _primary_rowid(members: list[sqlite3.Row]) -> int:
    """
    rowid of the copy to display: the highest-DISPLAY_ORDER-priority source,
    UNLESS that specific copy is materially thinner (no description, or no
    disclosed salary where another copy has one) than another copy in the
    same cluster.

    DISPLAY_ORDER encodes a statistical prior — "JobsDB rows are usually
    richest" — not a per-row guarantee (see docs/adr/0029). A stale or
    listing-only copy from the usually-richest source must not win the
    display slot over a genuinely fuller copy just because of where it was
    scraped from; the fuller copy's content would otherwise be silently
    unreachable, since only the elected primary's own columns are read.
    Ties on richness keep the DISPLAY_ORDER default, so this only ever moves
    the election when there's a real, checkable reason to.
    """
    default = min(members, key=lambda row: display_rank(row["source"]))
    best, best_richness = default, _richness(default)
    for row in members:
        if row["rowid"] == default["rowid"]:
            continue
        richness = _richness(row)
        if richness > best_richness:
            best, best_richness = row, richness
    return best["rowid"]


def _elect_vacancy_id(members: list[sqlite3.Row]) -> str:
    """
    Stable id for a cross-posted cluster, persisted across runs (docs/adr/0030)
    — unlike is_primary, which reconcile_cross_posted recomputes from scratch
    every call. Lets job_read._resolve_vacancy_refs find a still-active sibling
    when the exact copy a Saved Role references later closes.

    Adopts the id a member already carries from a previous run when there is
    exactly one distinct one. Zero existing ids (every member is new to this
    cluster) mints one. Two or more distinct existing ids means two previously
    separate vacancies just merged — a bridging source appeared this run — and
    the id belonging to the DISPLAY_ORDER-preferred row wins; the other id is
    simply retired, which is safe because vacancy_id is a lookup key only,
    never a Saved Role's own stored reference.
    """
    existing = {m["vacancy_id"] for m in members if m["vacancy_id"]}
    if len(existing) == 1:
        return next(iter(existing))
    if not existing:
        return uuid.uuid4().hex
    preferred = min(members, key=lambda row: display_rank(row["source"]))
    return preferred["vacancy_id"] or next(iter(existing))


#: Ordinal rank for the tie-break in `_seniority_consensus` below. Only the
#: four levels DeepSeek's live prompt actually returns (`junior|mid|senior|
#: lead` — see `enrichers/deepseek.py`) are ranked; anything else sorts last,
#: deterministically, by name — reachable only from a stale row enriched
#: under a retired prompt version.
_SENIORITY_RANK = {"junior": 0, "mid": 1, "senior": 2, "lead": 3}


def _seniority_consensus(seniorities: list[str], current: str | None) -> str:
    """
    The majority `job_enrichments.seniority` value across one cross-posted
    vacancy's active, enriched copies.

    A tie keeps `current` (the primary row's own value) when it is among the
    tied candidates — the smallest possible change from what is already
    shown. An unbroken tie with `current` outside it (the primary's own
    answer was itself a minority) falls back to the LOWEST-ranked tied
    value: conservative, same "when unsure, answer the smaller claim"
    default this codebase already uses elsewhere (search_index's typo
    correction, the retired tech filter's "when unsure, NOT TECH").
    """
    from collections import Counter

    counts = Counter(seniorities)
    top = max(counts.values())
    winners = [level for level, n in counts.items() if n == top]
    if len(winners) == 1:
        return winners[0]
    if current in winners:
        return current
    return min(winners, key=lambda level: (_SENIORITY_RANK.get(level, 99), level))


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


# Specific HK district/area names. When BOTH sides of a title match name a
# specific district and those sets are disjoint, that's a real signal of two
# different branch openings (e.g. "Relationship Manager" in Central AND in
# Kwun Tong the same week — common among multi-branch banks/insurers) and the
# match is refused even though the titles are identical. Deliberately NOT
# exhaustive and NOT used to REQUIRE agreement: a location this list doesn't
# recognise, or a generic HK-wide phrasing ("Hong Kong", "Hong Kong SAR") on
# either side, falls back to the pre-existing title-only match — matching
# despite differently-phrased generic locations is itself a fix for a real
# false-negative (see test_reconcile_matches_despite_different_location_strings).
_HK_DISTRICTS = frozenset({
    # Hong Kong Island
    "central", "admiralty", "wan chai", "causeway bay", "north point",
    "quarry bay", "taikoo", "sheung wan", "kennedy town", "aberdeen",
    "wong chuk hang", "chai wan", "shau kei wan", "happy valley",
    "tin hau", "fortress hill", "sai ying pun", "mid levels",
    # Kowloon
    "tsim sha tsui", "yau ma tei", "mong kok", "prince edward",
    "sham shui po", "cheung sha wan", "kowloon bay", "kwun tong",
    "kowloon east", "kowloon city", "to kwa wan", "hung hom",
    "san po kong", "diamond hill", "wong tai sin", "lok fu",
    "ngau tau kok", "kai tak",
    # New Territories
    "sha tin", "tai po", "fanling", "sheung shui", "tuen mun",
    "yuen long", "tin shui wai", "tsuen wan", "kwai chung",
    "tsing yi", "sai kung", "tseung kwan o", "ma on shan",
    "cyberport", "science park",
    # Outlying islands
    "lantau", "tung chung", "discovery bay",
})


def _location_districts(locations: list[str]) -> frozenset[str]:
    """Specific HK district tokens named across a row's locations, if any."""
    found: set[str] = set()
    for loc in locations:
        lowered = (loc or "").lower()
        for district in _HK_DISTRICTS:
            if district in lowered:
                found.add(district)
    return frozenset(found)


def _parse_locations(raw: str | None) -> list[str]:
    try:
        value = json.loads(raw) if raw else []
        return value if isinstance(value, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _titles_match(a: frozenset[str], b: frozenset[str], a_lvl: frozenset[str],
                  b_lvl: frozenset[str], a_districts: frozenset[str] = frozenset(),
                  b_districts: frozenset[str] = frozenset()) -> bool:
    """True if two token sets are the same vacancy: same seniority + enough overlap."""
    if not a or not b:
        return a == b
    if a_lvl != b_lvl:               # different seniority → different role
        return False
    if a_districts and b_districts and a_districts.isdisjoint(b_districts):
        return False                 # named, non-overlapping branches → different role
    return len(a & b) / len(a | b) >= _FUZZY_TITLE_THRESHOLD


_COMPANY_NOISE_RE = re.compile(r"[^a-z0-9]+")
# Legal-entity/formatting noise only — never a partial or fuzzy company match.
# Merging two DIFFERENT employers would hide one of them's entire board, not
# just one listing, so this stays deliberately conservative: strip known
# corporate suffixes and punctuation, then require the two names to be
# EXACTLY equal afterwards (see _company_group_key's length guard below for
# the case where that strips a name down to nothing useful).
_COMPANY_SUFFIX_RE = re.compile(
    r"\b(?:limited|ltd|holdings?|group|corporation|corp|plc|inc|incorporated|"
    r"hong kong|hk|pte|pvt|llp|llc)\b"
)


def _normalize_company_name(name: str) -> str:
    """Same employer name, minus legal-suffix/formatting noise, for grouping."""
    cleaned = _COMPANY_NOISE_RE.sub(" ", (name or "").lower())
    cleaned = " ".join(cleaned.split())
    cleaned = _COMPANY_SUFFIX_RE.sub(" ", cleaned)
    return " ".join(cleaned.split())


def _company_group_key(company_slug: str, company: str) -> str:
    """
    The key `reconcile_cross_posted` clusters on — normally the normalized
    company NAME (so two `companies.yaml` entries for the same employer under
    different slugs, e.g. a JobsDB entry and an unrelated longtail entry that
    nobody thought to pair, are still recognised as one vacancy pool), falling
    back to the raw slug when normalization leaves too little to safely match
    on (empty, or under 3 characters — avoids two unrelated employers whose
    names both strip down to something generic colliding into one group).
    """
    normalized = _normalize_company_name(company)
    return normalized if len(normalized) >= 3 else f"slug:{company_slug}"


def _cluster_by_title(members: list[sqlite3.Row]) -> list[list[sqlite3.Row]]:
    """
    Group a company's rows into vacancies by fuzzy title match (union-find).

    Two rows join a cluster when _titles_match. Comparisons are BLOCKED by
    shared title tokens (an inverted index: token -> rows containing it) rather
    than a plain pairwise scan over every (i, j) — lossless, not an approximation:
    _titles_match requires word-overlap >= _FUZZY_TITLE_THRESHOLD (0.85), and two
    token sets with ZERO tokens in common have overlap 0, so a true match always
    shares at least one token and can never be skipped by this blocking. What it
    skips is exactly the pairs that could never have matched anyway.

    This was a real, not theoretical, cost: one company (bochk, 587 active rows)
    was 34% of a measured 1,002,066-pair full pass, and grouping now spans
    multiple company_slugs for the same employer (ADR 0027), which can only grow
    a single company's row count further.
    """
    from collections import defaultdict

    n = len(members)
    toks = [_title_tokens(m["title"]) for m in members]
    lvls = [t & _LEVEL_TOKENS for t in toks]
    districts = [_location_districts(_parse_locations(m["locations"])) for m in members]
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    buckets: dict[str, list[int]] = defaultdict(list)
    for i, tok_set in enumerate(toks):
        for token in tok_set:
            buckets[token].append(i)

    compared: set[tuple[int, int]] = set()
    for candidates in buckets.values():
        for a in range(len(candidates)):
            i = candidates[a]
            for b in range(a + 1, len(candidates)):
                j = candidates[b]
                pair = (i, j) if i < j else (j, i)
                if pair in compared:
                    continue
                compared.add(pair)
                if _titles_match(toks[i], toks[j], lvls[i], lvls[j],
                                 districts[i], districts[j]):
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
    -- A Listing that comes back is open again, so it is no longer closed AT any
    -- time. Leaving a stale closed_at behind would make a live Role look like
    -- one that closed months ago, and after two weeks it would vanish from the
    -- Saved Roles of every Seeker holding it (docs/adr/0011).
    closed_at          = NULL,
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
        # Select what is stale, then hand the write to deactivate(). The guards
        # above are this method's own business — they answer "did this scrape
        # fail?", which is a question no other caller asks — but the write, the
        # soft-delete rule and the re-reconcile are everyone's, and live there.
        stale = self._conn.execute(
            f"""
            SELECT source, source_id
              FROM jobs
             WHERE company_slug = ?
               {src_clause}
               AND is_active    = 1
               AND fetched_at   < ?
            """,
            params,
        ).fetchall()
        return self.deactivate(
            [(r["source"], r["source_id"]) for r in stale],
            reason="gone-from-source",
        )

    def deactivate(self, refs: Iterable[tuple[str, str]], *, reason: str) -> int:
        """
        Soft-delete the given (source, source_id) Listings. Returns rows changed.

        THE ONE WRITE PATH TO is_active = 0, and the reason it exists.

        It also stamps `closed_at`, which is only correct BECAUSE it is the one
        write path: a closure timestamp written by three of four writers would be
        worse than none, since a NULL would then mean either "still open" or "one
        of the writers that forgot", and Saved Roles read it to decide what to
        stop showing (docs/adr/0011).

        "Soft-delete only" was enforced by comments in four modules rather than by
        a module: `tech_filter.py`, `posts/expiry.py` and
        `scripts/remove_tech_roles.py` each opened their own connection and ran
        their own `UPDATE jobs SET is_active=0`. Three of them were correct about
        the soft delete and wrong about what it costs.

        Deactivating a Listing can hide a Role entirely. `reconcile_cross_posted`
        elects exactly one copy of a cross-posted vacancy as `is_primary = 1` and
        the board shows only that copy; deactivate the elected copy without
        re-running the election and the surviving copies are all `is_primary = 0`,
        so the Role disappears from the board while a live listing still exists.
        Reproduced: a JobsDB + Workday pair, deactivate the JobsDB row, board goes
        from 1 visible to 0 with the Workday row still `is_active = 1`.

        Nothing in `tech_filter` or `expiry` mentioned it, and `pipeline.run()`
        calls `run_tech_filter` AFTER `reconcile_cross_posted()`, so the window
        opened on every nightly run and stayed open until the next one.

        The re-election is scoped to the affected `company_slug`s, which bounds
        the cost rather than eliminating it. Clustering is O(n^2) WITHIN a
        company, so the work is sum(n^2) over the companies touched: measured on
        the live database that is 1,002,066 pair comparisons in total, and one
        company (bochk, 587 active Listings) is 34% of it. Deactivating anything
        in a large company therefore costs about as much as a full pass — 22s
        idle, ~50s under load.

        Across a nightly run that is fine and the arithmetic is the reason:
        `mark_inactive_for_run` fires once per company, each re-electing only its
        own, so the total is sum(n^2) — ONE extra full pass, not 147. On a
        20-minute scrape that is roughly 4%.
        """
        refs = list(refs)
        if not refs:
            return 0

        # One timestamp for the whole call, not one per chunk: a Listing's
        # closure is an event, and 5,000 stale rows from one nightly run closed
        # together whether the loop takes 40ms or 40s.
        closed_at = datetime.now(timezone.utc).isoformat()

        slugs: set[str] = set()
        changed = 0
        with self._conn:
            for chunk in (refs[i:i + _REF_CHUNK] for i in range(0, len(refs), _REF_CHUNK)):
                placeholders = ",".join("(?,?)" * 1 for _ in chunk)
                flat = [x for ref in chunk for x in ref]
                rows = self._conn.execute(
                    f"SELECT company_slug FROM jobs "
                    f"WHERE is_active = 1 AND (source, source_id) IN (VALUES {placeholders})",
                    flat,
                ).fetchall()
                slugs.update(r["company_slug"] for r in rows)
                cur = self._conn.execute(
                    f"UPDATE jobs SET is_active = 0, closed_at = ? "
                    f"WHERE is_active = 1 AND (source, source_id) IN (VALUES {placeholders})",
                    [closed_at, *flat],
                )
                changed += cur.rowcount

        if changed:
            logger.info(
                "Deactivated %d listing(s) [%s]; re-electing primaries for %d company slug(s).",
                changed, reason, len(slugs),
            )
            self.reconcile_cross_posted(company_slugs=slugs)
        return changed

    def reactivate(self, refs: Iterable[tuple[str, str]], *, reason: str) -> int:
        """
        Undo a soft-delete. The inverse of `deactivate` — see that docstring for
        why re-election has to happen here too: bringing a Listing back can
        change which copy of a cross-posted vacancy ought to be primary just as
        much as removing one does, and this is the only other place `is_active`
        is ever written, so it carries the same obligation.

        Only ever reaches rows that ARE currently inactive (`is_active = 0` in
        the WHERE), so calling this on a ref that was never deactivated, or one
        some other writer already reactivated, is a no-op rather than a
        double-count.

        `closed_at` is cleared back to NULL — an active row with a closure date
        is the "live Role claiming to have closed" shape phase 30's migration
        exists to prevent (see its docstring), and Saved Roles read `closed_at`
        to decide what to stop showing (docs/adr/0011).
        """
        refs = list(refs)
        if not refs:
            return 0

        slugs: set[str] = set()
        changed = 0
        with self._conn:
            for chunk in (refs[i:i + _REF_CHUNK] for i in range(0, len(refs), _REF_CHUNK)):
                placeholders = ",".join("(?,?)" * 1 for _ in chunk)
                flat = [x for ref in chunk for x in ref]
                rows = self._conn.execute(
                    f"SELECT company_slug FROM jobs "
                    f"WHERE is_active = 0 AND (source, source_id) IN (VALUES {placeholders})",
                    flat,
                ).fetchall()
                slugs.update(r["company_slug"] for r in rows)
                cur = self._conn.execute(
                    f"UPDATE jobs SET is_active = 1, closed_at = NULL "
                    f"WHERE is_active = 0 AND (source, source_id) IN (VALUES {placeholders})",
                    flat,
                )
                changed += cur.rowcount

        if changed:
            logger.info(
                "Reactivated %d listing(s) [%s]; re-electing primaries for %d company slug(s).",
                changed, reason, len(slugs),
            )
            self.reconcile_cross_posted(company_slugs=slugs)
        return changed

    def reconcile_cross_posted(
        self, *, company_slugs: Collection[str] | None = None
    ) -> tuple[int, int]:
        """
        Detect vacancies that appear on more than one source and set apply_url.

        The same role is often posted on several sites (e.g. eFinancialCareers
        AND JobsDB). This pass groups ACTIVE jobs for the same employer into
        vacancies by FUZZY title match (_cluster_by_title — word-overlap with a
        seniority guard, generic-location-independent but district-aware: see
        _location_districts) and, for any cluster spanning more than one
        distinct source:

          - sets cross_posted = 1 on every copy, and
          - sets apply_url on every copy to the highest-priority source's URL
            (see sources.APPLY_ORDER — eFinancialCareers first), so the frontend can
            always send an applicant to the preferred site while still showing
            that the role was found on multiple boards.

        It also sets is_primary for display de-duplication: within a cross-posted
        group exactly one copy keeps is_primary=1 and the other copies get 0, so
        the web app shows one card per vacancy (with apply_url still pointing at
        eFinancialCareers). The copy chosen is normally the richest SOURCE (see
        sources.DISPLAY_ORDER, JobsDB first: it usually carries the description
        AND the DeepSeek enrichment) — but _primary_rowid checks the specific
        ROW too, and picks a genuinely fuller copy over a thin one from the
        usually-richest source (see docs/adr/0029). De-dup only applies across
        DIFFERENT sources; two rows from the SAME source that happen to share a
        normalised title are both left visible (they are usually distinct roles,
        not a cross-post).

        "Same employer" is normally "same company_slug", but grouping is actually
        keyed by _company_group_key (normalized company NAME), not the raw slug —
        two `companies.yaml`/`companies_longtail.yaml` entries for the same real
        employer under DIFFERENT slugs (nobody thought to pair them, e.g. a
        longtail entry added before a JobsDB entry for the same company existed)
        used to get zero cross-source matching at all, invisibly: two boards, two
        cards, forever. See docs/adr/0027 (cross-slug candidate audit, 2026-08-27).
        The name match is deliberately conservative — legal-suffix/punctuation
        noise only, never fuzzy overlap — since collapsing two DIFFERENT employers
        together would hide one of their entire boards, not just one listing.

        Groups on a single source are reset to (apply_url='', cross_posted=0,
        is_primary=1) so the pass is fully idempotent: if a role stops being
        cross-posted (its eFC copy disappears), the leftover routing is cleared on
        the next run. Only rows whose value actually changes are written.

        Returns (cross_posted_groups, rows_updated).
        """
        from collections import defaultdict

        # company_slugs scopes the pass to the companies whose Listings just
        # changed. Clustering is per-group and O(n^2) within one, so a full pass
        # costs ~22s over 5,000 active rows — too slow to run after every
        # deactivation, and unnecessary: a company nobody touched cannot have
        # changed its election.
        sql = (
            "SELECT rowid, company_slug, company, title, locations, source, url, "
            "apply_url, cross_posted, is_primary, description_clean, salary_min, "
            "vacancy_id FROM jobs WHERE is_active = 1"
        )
        if company_slugs is None:
            rows = self._conn.execute(sql).fetchall()
        else:
            slugs = list(company_slugs)
            if not slugs:
                return 0, 0
            # Expand to sibling slugs sharing a normalized company identity.
            # Without this, a scoped re-election touching only ONE of two slugs
            # that are really the same employer would see only that slug's rows,
            # wrongly conclude the group is single-slug/single-source, and reset
            # cross_posted/is_primary — flapping the election on every incremental
            # call instead of just on the full nightly pass that sees everything.
            slug_company = self._conn.execute(
                "SELECT DISTINCT company_slug, company FROM jobs WHERE is_active = 1"
            ).fetchall()
            slugs_by_key: dict[str, set[str]] = defaultdict(set)
            key_by_slug: dict[str, str] = {}
            for r in slug_company:
                key = _company_group_key(r["company_slug"], r["company"])
                key_by_slug[r["company_slug"]] = key
                slugs_by_key[key].add(r["company_slug"])
            expanded: set[str] = set()
            for s in slugs:
                expanded |= slugs_by_key.get(key_by_slug.get(s, f"slug:{s}"), {s})
            slugs = sorted(expanded)

            rows = []
            for i in range(0, len(slugs), _REF_CHUNK):
                chunk = slugs[i:i + _REF_CHUNK]
                ph = ",".join("?" * len(chunk))
                rows += self._conn.execute(
                    f"{sql} AND company_slug IN ({ph})", chunk
                ).fetchall()

        by_group: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for r in rows:
            by_group[_company_group_key(r["company_slug"], r["company"])].append(r)

        # (apply_url, cross_posted, is_primary, vacancy_id, rowid)
        updates: list[tuple[str, int, int, str | None, int]] = []
        cross_groups = 0
        for company_rows in by_group.values():
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
                    vacancy_id = _elect_vacancy_id(members)
                    for m in members:
                        is_primary = 1 if m["rowid"] == primary else 0
                        if (m["apply_url"] != preferred or m["cross_posted"] != 1
                                or m["is_primary"] != is_primary
                                or m["vacancy_id"] != vacancy_id):
                            updates.append((preferred, 1, is_primary, vacancy_id, m["rowid"]))
                else:
                    for m in members:
                        if (m["apply_url"] != "" or m["cross_posted"] != 0
                                or m["is_primary"] != 1 or m["vacancy_id"] is not None):
                            updates.append(("", 0, 1, None, m["rowid"]))

        if updates:
            with self._conn:
                self._conn.executemany(
                    "UPDATE jobs SET apply_url = ?, cross_posted = ?, is_primary = ?, "
                    "vacancy_id = ? WHERE rowid = ?",
                    updates,
                )
        self.refresh_signal_flags()
        self.refresh_seniority_consensus()
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

        board_signals.new_job is capped to _NEW_BADGE_MAX_AGE_DAYS before the grp_new
        aggregation below reads it. Without this, a job that ages off a source's own
        listing pages stops being re-scraped, so board_signals is never refreshed
        again and new_job stays true forever — the source's "new" badge outliving the
        window it was ever meant to describe. Capping by posted_at (not fetched_at)
        answers "how long has this vacancy existed", which is the actual question;
        a NULL posted_at fails closed (stripped, not kept) since we cannot vouch for
        a listing's age without one. Stripping the key here — not just zeroing
        grp_new — also fixes the per-card "New" badge, which reads board_signals
        directly (webapp/backend/job_read.py's _own_signals) rather than grp_new.
        """
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(jobs)")}
        if not {"grp_new", "grp_urgent", "grp_applicants"} <= cols:
            return
        # A copy "g" is in row j's group when it is j itself or a cross-post sharing
        # the apply_url group key. The IN-subqueries below are materialised once and
        # hit the apply_url index, so the whole refresh is a handful of set updates.
        with self._conn:
            self._conn.execute(
                "UPDATE jobs SET board_signals = json_remove(board_signals, '$.new_job') "
                "WHERE is_active = 1 AND json_extract(board_signals, '$.new_job') = 1 "
                "AND (posted_at IS NULL OR posted_at < datetime('now', ?))",
                (f"-{_NEW_BADGE_MAX_AGE_DAYS} days",),
            )
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

    def refresh_seniority_consensus(self) -> int:
        """
        Resolve conflicting `job_enrichments.seniority` across a cross-posted
        vacancy's copies into one canonical `jobs.grp_seniority`.

        WHY THIS EXISTS
        ----------------
        Each copy of a cross-posted vacancy is enriched independently, and
        DeepSeek runs at temperature=0.2 (not 0), so near-identical
        description text across copies of the SAME real vacancy can
        genuinely produce different seniority answers — measured on the live
        board: 14% of cross-posted clusters disagreed across their copies,
        and roughly half of those had a PRIMARY copy (the only one a Seeker
        or the seniority filter ever sees) that contradicted every sibling.
        `_seniority_consensus` settles it by majority vote; see that
        function's docstring for the tie-break.

        Only writes `grp_seniority` for a cluster where copies actually
        DISAGREE — an already-consistent cluster, or a singleton job, is
        left at NULL, and `job_read.py` falls back to the primary's own
        `e.seniority` for both. That keeps writes proportional to genuine
        disagreement (a few dozen rows on the live board), not a rewrite of
        every cross-posted cluster on every reconcile pass.

        Read-only join over `job_enrichments`, so — like `refresh_signal_flags`
        for `board_signals` — this has to run as its own pass rather than
        inside `reconcile_cross_posted`'s own single query, and belongs right
        after it: apply_url/cross_posted/is_primary must already be current
        for this pass's grouping to mean anything.

        Resets every active row's `grp_seniority` to NULL before recomputing
        — the same reset `refresh_signal_flags` does for `grp_new`/
        `grp_urgent`/`grp_applicants`, and for the identical reason: a
        cluster whose copies later converge (a stale sibling gets
        re-enriched to match) must not keep serving a PREVIOUS run's
        now-stale override forever. Without the reset this only ever adds
        overrides, never removes one whose disagreement has since resolved.

        Never overrides a primary row Ultimate Admin has hand-corrected
        (`job_enrichments.manually_edited_at IS NOT NULL`, phase 33) — the
        same unconditional exclusion `_fetch_unenriched` already applies for
        the ordinary enrichment pass and the salary outlier audit, for the
        identical reason their docstrings give: a human's deliberate
        correction is not a vote to be outnumbered by its own siblings, and
        silently reverting one the next time this pass runs is the exact
        failure phase 33 exists to prevent.
        """
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(jobs)")}
        if "grp_seniority" not in cols:
            return 0

        rows = self._conn.execute(
            "SELECT j.rowid, j.apply_url, j.is_primary, e.seniority, e.manually_edited_at"
            "  FROM jobs j"
            "  JOIN job_enrichments e ON j.source = e.source AND j.source_id = e.source_id"
            " WHERE j.is_active = 1 AND j.cross_posted = 1 AND e.seniority IS NOT NULL"
        ).fetchall()

        from collections import defaultdict

        by_group: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for row in rows:
            by_group[row["apply_url"]].append(row)

        updates: list[tuple[str, int]] = []
        for members in by_group.values():
            seniorities = [m["seniority"] for m in members]
            if len(set(seniorities)) <= 1:
                continue  # every copy already agrees — nothing to resolve
            primary = next((m for m in members if m["is_primary"]), None)
            if primary is None or primary["manually_edited_at"] is not None:
                continue
            consensus = _seniority_consensus(seniorities, primary["seniority"])
            updates.append((consensus, primary["rowid"]))

        with self._conn:
            self._conn.execute("UPDATE jobs SET grp_seniority = NULL WHERE is_active = 1")
            if updates:
                self._conn.executemany(
                    "UPDATE jobs SET grp_seniority = ? WHERE rowid = ?", updates
                )
        return len(updates)

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
