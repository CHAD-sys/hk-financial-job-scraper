"""
Reading Roles out of jobs.db.

WHY THIS MODULE EXISTS
----------------------
The catalogue-row rule for browsing — `is_active = 1 AND is_primary = 1` —
used to live inside one filter-building function in main.py, and two of the three
read paths never called it. `get_job` applied half of it; `list_saved` applied
none, so a Saved Role that had closed months ago came back looking live, which is
the exact behaviour CONTEXT.md promises Saved Roles do not have. The rule had no
home, so callers forgot it.

It has a home now. Everything the three read paths share sits behind this
module's interface: the select and its column aliases, the row-visibility rule, the
filters, the sort, the count, the row-to-wire mapping, and the cross-post signal
aggregation. A caller cannot spell a row-visibility rule of its own.

Request authorization is a different question. ADR 0018's public research
requirement and short-lived detail grants live at the HTTP edge in ``main.py``
and ``role_access.py``. This module does own the catalogue-audience predicate,
however, so anonymous list results, facets and counts cannot disagree about the
member-only boutique/social tiers. Internal ranking opts into the member audience.

TWO VISIBILITY RULES, NOT ONE
-----------------------------
The obvious design — hide one invariant behind the interface — is wrong, because
the callers genuinely differ:

    browsing is filtered, addressing is not.

`Visibility.BOARD` is for browsing: active and primary, so a cross-posted vacancy
appears once rather than once per source. `Visibility.ADDRESSABLE` is for anything
that names a specific `(source, source_id)` — a deep link, a Saved Role — and
returns the row whatever state it is in, with `closed` telling you which. Requiring
`is_primary` when addressing would 404 a link whose copy stopped being primary at
the last reconciliation; requiring `is_active` would hide a Saved Role that closed,
which is the thing a Seeker most needs to be told.

NO FASTAPI IN HERE
------------------
The interface takes a `sqlite3.Connection`. Nothing in this module knows what an
HTTP status code is — `get_job` returns `None` and the route handler decides that
means 404. That is what makes it testable with a temp database and no TestClient,
no app import, and none of the `sys.modules` surgery the endpoint tests need.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Iterable, Literal, Optional, Sequence

from pydantic import BaseModel

import search_index
from hk_jobs.sector_classify import sector_case_sql, sector_condition_sql

# ── Connection requirements ───────────────────────────────────────────────────


def _regexp(pattern: str, value: Optional[str]) -> int:
    """SQLite REGEXP impl (case-insensitive) so we can match whole words, not substrings."""
    if value is None:
        return 0
    return 1 if re.search(pattern, value, re.IGNORECASE) else 0


def prepare(conn: sqlite3.Connection) -> sqlite3.Connection:
    """
    Make a connection usable by this module. Call once, before any read.

    Two things are not optional and neither is expressible in a type signature,
    which is exactly why they live here rather than in a caller's docstring:

      - `row_factory = sqlite3.Row`, because every row is read by column name.
      - a `REGEXP` function, because internship detection matches whole words
        (`INTERNSHIP_SQL`). Without it SQLite raises "no such function: REGEXP"
        on the very first query.
    """
    conn.row_factory = sqlite3.Row
    conn.create_function("REGEXP", 2, _regexp)
    return conn

# ── Visibility ────────────────────────────────────────────────────────────────


class Visibility(str, Enum):
    """Which rows a read is allowed to see. See the module docstring."""

    #: Browsing. One row per live vacancy.
    BOARD = "board"
    #: Addressing a specific (source, source_id). Any copy, any state.
    ADDRESSABLE = "addressable"


class CatalogueAudience(str, Enum):
    """Which catalogue tiers the current reader may discover."""

    #: Anonymous research exposes established, mainstream sources only.
    PUBLIC = "public"
    #: Signed-in Seekers and Admins may also discover boutique and social Roles.
    MEMBER = "member"


#: The SQL each rule contributes to the WHERE clause. `None` means "no predicate",
#: which is a deliberate value rather than an oversight: addressing a Role by
#: reference is unfiltered by design.
_VISIBILITY_SQL: dict[Visibility, Optional[str]] = {
    Visibility.BOARD: "j.is_active = 1 AND j.is_primary = 1",
    Visibility.ADDRESSABLE: None,
}

#: The BOARD rule as a bare SQL fragment, for aggregate queries that build their
#: own SELECT and so cannot go through `list_jobs` — /api/filters and /api/stats
#: are nine hand-written GROUP BYs between them. They used to spell the predicate
#: out sixteen times, which is how /api/stats and /api/jobs could come to disagree
#: about what an open Role is. Expects the jobs table aliased as `j`.
BOARD_WHERE = _VISIBILITY_SQL[Visibility.BOARD]

#: Recruiter-posted Roles and medium/boutique company Roles are a member benefit.
#: Keep this policy next to the lifecycle visibility rule so lists, facets and
#: counts cannot accidentally disagree about which rows an audience may discover.
MEMBER_ONLY_TIERS = frozenset({"boutique", "social"})
PUBLIC_AUDIENCE_WHERE = (
    "COALESCE(j.source_tier, 'mainstream') NOT IN ('boutique', 'social')"
)


class Sort(str, Enum):
    NEWEST = "newest"
    #: Best-match ranking from the full-text search index (search_index.py).
    #: Meaningless with no `search` term — `list_jobs` falls back to NEWEST
    #: when this is requested without one, same as an unknown value would.
    RELEVANCE = "relevance"
    SALARY_HIGH = "salary_high"
    SALARY_LOW = "salary_low"
    COMPANY = "company"


# ── Sector taxonomy ───────────────────────────────────────────────────────────
# Derived from the posting's own title first, falling back to the employer's
# name, at read time; jobs.db has no sector column. Rules live in
# hk_jobs/sector_classify.py — the SAME rule list drives both this SQL and the
# plain-Python classify_sector(), so they cannot drift the way the old
# hand-written negation could. Lives here rather than in main.py because
# BASE_SELECT embeds it, and importing it back out of main.py would be a
# cycle. /api/filters and /api/stats import it from here.

SECTOR_SQL = sector_case_sql("j.title", "j.company")


def _sector_condition(name: str) -> str:
    return sector_condition_sql(name, "j.title", "j.company")


# ── Internship detection ──────────────────────────────────────────────────────
# Whole-word match via REGEXP (registered on the connection by the caller) so we
# match "intern"/"internship" as words and NEVER inside "internal",
# "international", "internet".
_INTERNSHIP_REGEX = (
    r"\bintern(ship)?s?\b"
    r"|\bsummer (analyst|associate|intern)\b"
    r"|\bgraduate (intern|trainee|programme|program)\b"
    r"|\btrainee programme?\b"
    r"|\bindustrial placement\b"
    r"|實習"
)
INTERNSHIP_COND = f"(j.title REGEXP '{_INTERNSHIP_REGEX}')"
INTERNSHIP_SQL = f"CASE WHEN {INTERNSHIP_COND} THEN 1 ELSE 0 END"


# ── The select ────────────────────────────────────────────────────────────────
# FROM/JOIN is a single constant used by BOTH the row query and the count. They
# used to be typed out separately, so a change to one silently disagreed with the
# other and paging broke with no error.

_FROM = """
  FROM jobs j
  LEFT JOIN job_enrichments e
    ON j.source = e.source AND j.source_id = e.source_id
"""

#: The row shape both the plain query and the boosted-order query (below) select
#: — split out so `_boosted_rows_sql` can add a window-function column to the
#: same SELECT list rather than duplicating it.
_SELECT_COLUMNS = f"""
    j.source,
    j.source_id,
    j.company,
    -- Route "apply" to the preferred board. For a cross-posted role the displayed
    -- card is the richest copy (JobsDB: description + skills) but apply_url points
    -- at eFinancialCareers (set by reconcile_cross_posted); '' falls back to own url.
    COALESCE(NULLIF(j.apply_url, ''), j.url) AS url,
    j.title,
    j.board_signals,
    j.cross_posted,
    j.is_active,
    j.apply_url AS raw_apply_url,
    j.source_tier,
    j.locations,
    j.description_clean,
    j.posted_at,
    e.seniority,
    e.job_category,
    e.remote_type,
    e.required_skills,
    e.salary_hkd_min,
    e.salary_hkd_max,
    e.salary_estimated_min,
    e.salary_estimated_max,
    e.salary_estimated_confidence,
    e.years_experience_required,
    e.description_summary,
    e.title_en,
    ({SECTOR_SQL}) AS sector,
    ({INTERNSHIP_SQL}) AS is_internship
""".strip()

BASE_SELECT = f"SELECT\n{_SELECT_COLUMNS}\n{_FROM}".strip()

_COUNT_SELECT = f"SELECT COUNT(*) {_FROM}"


# ── Wire types ────────────────────────────────────────────────────────────────


class JobSummary(BaseModel):
    source: str
    source_id: str
    company: str
    sector: str
    title: str
    title_en: Optional[str] = None
    source_tier: str
    locations: list[str] = []
    seniority: Optional[str] = None
    job_category: Optional[str] = None
    remote_type: Optional[str] = None
    required_skills: list[str] = []
    salary_hkd_min: Optional[int] = None
    salary_hkd_max: Optional[int] = None
    salary_period: Literal["month", "year"] | None = None
    salary_estimated_min: Optional[int] = None
    salary_estimated_max: Optional[int] = None
    salary_estimated_confidence: Optional[str] = None
    years_experience_required: Optional[int] = None
    posted_at: Optional[str] = None
    url: str
    is_internship: bool = False
    description_excerpt: str = ""
    #: The vacancy is no longer open. Only ever true for a Role reached by
    #: reference (a Saved Role, a deep link) — the board never returns one.
    #: The domain word is "closed"; `is_active` is a storage detail and stays
    #: on this side of the wire.
    closed: bool = False
    # Market signals by board, e.g. { indeed: { urgently_hiring, applicant_count } }
    board_signals: dict[str, dict] = {}
    #: Short-lived proof that this Role reached the caller through an allowed
    #: discovery path. Issued at the HTTP edge; jobs.db never stores it.
    access_token: Optional[str] = None


class JobDetail(JobSummary):
    description_clean: str = ""
    description_summary: str = ""
    sources: list[str] = []


class JobListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    total_pages: int
    jobs: list[JobSummary]


class NameCount(BaseModel):
    name: str
    count: int


class NumericRange(BaseModel):
    min: Optional[int]
    max: Optional[int]


class ResearchFacets(BaseModel):
    """Every filter choice available inside one text-research result set."""

    research_total: int
    tier_counts: dict[str, int]
    companies: list[NameCount]
    sectors: list[NameCount]
    skills: list[NameCount]
    seniority_levels: list[str]
    remote_types: list[str]
    salary_range: NumericRange
    experience_range: NumericRange


@dataclass(frozen=True)
class JobFilters:
    """
    Everything the board can narrow by.

    Sequences are tuples so the whole thing stays hashable and cannot be mutated
    by a caller after the fact. Route handlers build one of these from their
    query parameters.
    """

    search: Optional[str] = None
    sectors: tuple[str, ...] = ()
    companies: tuple[str, ...] = ()
    seniority: tuple[str, ...] = ()
    remote_type: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    exp_min: Optional[int] = None
    exp_max: Optional[int] = None
    posted_within_days: Optional[int] = None
    is_internship: Optional[bool] = None
    tier: Optional[str] = None
    is_new: Optional[bool] = None
    urgently_hiring: Optional[bool] = None
    max_applicants: Optional[int] = None
    hidden_only: Optional[bool] = None
    verified_only: Optional[bool] = None

    @classmethod
    def of(cls, **kwargs) -> "JobFilters":
        """Build from loose values — lists become tuples, `None` means default."""
        clean = {}
        for name, value in kwargs.items():
            if value is None and name in ("sectors", "companies", "seniority",
                                          "remote_type", "skills"):
                continue
            clean[name] = tuple(value) if isinstance(value, list) else value
        return cls(**clean)


# ── WHERE building ────────────────────────────────────────────────────────────


def _where(
    filters: JobFilters,
    visibility: Visibility,
    search_rowids: Optional[list[int]] = None,
    audience: CatalogueAudience = CatalogueAudience.MEMBER,
) -> tuple[str, list]:
    """
    `search_rowids`: the caller's own `search_index.matching_rowids()` result,
    already computed because `list_jobs` needs the same list a second time (to
    build the RELEVANCE ordering). `_where` stays a pure string/param builder —
    it does not touch `conn` — by taking that list rather than the raw query.

    `None` means "no search filter requested"; `[]` means "searched, matched
    nothing", which must exclude every row (`0`), not be skipped as if no
    search had been requested at all.
    """
    conditions: list[str] = []
    params: list = []

    rule = _VISIBILITY_SQL[visibility]
    if rule:
        conditions.append(rule)

    if audience == CatalogueAudience.PUBLIC:
        conditions.append(PUBLIC_AUDIENCE_WHERE)

    # ── Market-signal filters. These read the pre-computed, indexed grp_* columns
    # (populated by JobStore.refresh_signal_flags at reconcile time), which already
    # aggregate each vacancy's cross-post group — so filtering is instant. ──
    if filters.is_new:
        conditions.append("j.grp_new = 1")
    if filters.urgently_hiring:
        conditions.append("j.grp_urgent = 1")
    if filters.max_applicants is not None:
        # Low-competition: highest known applicant count across boards is below the
        # threshold. Jobs with no known count are excluded (grp_applicants IS NULL).
        conditions.append("j.grp_applicants IS NOT NULL AND j.grp_applicants < ?")
        params.append(filters.max_applicants)

    # Tier tabs: 'boutique' = the Exclusive section (longtail companies scraped via
    # LLM extraction), 'mainstream' = structured job-board sources, 'social' = the
    # Recruiter Posts. 'all'/None = every tier.
    if filters.tier in ("boutique", "mainstream", "social"):
        conditions.append("j.source_tier = ?")
        params.append(filters.tier)

    # Recruiter Posts "truly hidden" filter: a social-tier job with no cross-source
    # match, i.e. a vacancy that genuinely doesn't exist on any real board.
    if filters.hidden_only:
        conditions.append("j.source_tier = 'social' AND j.cross_posted = 0")

    # "Verified job": a Recruiter Posts listing that ghost_check confirmed is the
    # SAME real vacancy as a listing already on the board. cross_posted can't carry
    # this (confidential posts never share a company_slug with a real listing), so
    # it is read straight from board_signals.
    if filters.verified_only:
        conditions.append("json_extract(j.board_signals, '$.not_a_ghost_job') = 1")

    if filters.search:
        # search_index.matching_rowids() is what actually decided which Roles
        # this query reaches — full text across title/title_en/company/skills/
        # description, stemmed and typo-corrected. This is only the filter: an
        # `IN (…)` over its result. Literal ints, not bound params — they are
        # this process's own rowids, never user input, and a bound-parameter
        # list this long risks SQLite's variable-count ceiling.
        if search_rowids:
            conditions.append(f"j.rowid IN ({','.join(str(r) for r in search_rowids)})")
        else:
            conditions.append("0")

    if filters.sectors:
        parts = [_sector_condition(sec) for sec in filters.sectors]
        conditions.append("(" + " OR ".join(parts) + ")")

    if filters.companies:
        ph = ",".join("?" * len(filters.companies))
        conditions.append(f"j.company IN ({ph})")
        params += list(filters.companies)

    if filters.seniority:
        ph = ",".join("?" * len(filters.seniority))
        conditions.append(f"e.seniority IN ({ph})")
        params += list(filters.seniority)

    if filters.remote_type:
        ph = ",".join("?" * len(filters.remote_type))
        conditions.append(f"e.remote_type IN ({ph})")
        params += list(filters.remote_type)

    if filters.skills:
        parts = []
        for sk in filters.skills:
            parts.append(
                "EXISTS (SELECT 1 FROM json_each(e.required_skills) sk"
                " WHERE LOWER(sk.value) = LOWER(?))"
            )
            params.append(sk)
        conditions.append("(" + " OR ".join(parts) + ")")

    # Salary filter matches the disclosed figure when present, else the AI estimate
    # (disclosed salaries are rare, so without this the filter returns almost nothing).
    if filters.salary_min is not None:
        conditions.append("COALESCE(e.salary_hkd_min, e.salary_estimated_min) >= ?")
        params.append(filters.salary_min)
    if filters.salary_max is not None:
        conditions.append("COALESCE(e.salary_hkd_max, e.salary_estimated_max) <= ?")
        params.append(filters.salary_max)

    if filters.exp_min is not None:
        conditions.append("e.years_experience_required >= ?")
        params.append(filters.exp_min)
    if filters.exp_max is not None:
        conditions.append("e.years_experience_required <= ?")
        params.append(filters.exp_max)

    if filters.posted_within_days is not None:
        conditions.append("j.posted_at >= datetime('now', ?)")
        params.append(f"-{filters.posted_within_days} days")

    if filters.is_internship is not None:
        conditions.append(INTERNSHIP_COND if filters.is_internship else f"NOT {INTERNSHIP_COND}")

    where_sql = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    return where_sql, params


# ── Sorting ───────────────────────────────────────────────────────────────────
# Salary sorts treat an AI estimate as the job's salary when nothing is disclosed
# (COALESCE), so disclosed- and estimate-only jobs rank in one unified list. The
# leading CASE forces rows with NO salary at all to sink to the bottom in BOTH
# directions — not relying on SQLite NULL ordering, which would float them to the
# top on DESC.
_SAL_HIGH = "COALESCE(e.salary_hkd_max, e.salary_estimated_max)"
_SAL_LOW = "COALESCE(e.salary_hkd_min, e.salary_estimated_min)"

# "Newest" = most recent POSTING date. Some sources mis-parse dates and yield
# posted_at values in the FUTURE (e.g. JobsDB relative-date bugs). A future date is
# invalid data, not "newest", so anything dated beyond tomorrow — and NULLs — sink
# rather than dominating the top. (+1 day of slack absorbs UTC/HKT skew for
# genuinely today's postings.)
_VALID_POSTED = "CASE WHEN date(j.posted_at) <= date('now','+1 day') THEN j.posted_at END"

#: RELEVANCE has no entry here on purpose: its ordering is one search's own
#: rowid ranking, not a fixed expression, so `list_jobs` builds it with
#: `_relevance_order_sql` instead of looking it up in this table.
_SORT_SQL: dict[Sort, str] = {
    Sort.NEWEST: f"{_VALID_POSTED} DESC NULLS LAST",
    Sort.SALARY_HIGH: f"CASE WHEN {_SAL_HIGH} IS NULL THEN 1 ELSE 0 END, {_SAL_HIGH} DESC",
    Sort.SALARY_LOW: f"CASE WHEN {_SAL_LOW} IS NULL THEN 1 ELSE 0 END, {_SAL_LOW} ASC",
    Sort.COMPANY: "j.company ASC",
}


def _relevance_order_sql(search_rowids: list[int]) -> str:
    """
    An `ORDER BY` expression that reproduces `search_rowids`' order exactly.

    `search_rowids` already comes out of `search_index.matching_rowids` ranked
    by BM25 — best match first. That ranking cannot be recomputed in plain SQL
    (it lives in the FTS5 index, not on `jobs`), so this just replays the
    Python-side order as a `CASE`: position 0 sorts first, position 1 second,
    and so on. A rowid outside the list (impossible here, since the WHERE
    clause already restricted to exactly this list) would sort last.
    """
    when_clauses = " ".join(
        f"WHEN {rowid} THEN {position}" for position, rowid in enumerate(search_rowids)
    )
    return f"CASE j.rowid {when_clauses} ELSE {len(search_rowids)} END ASC"


# ── Recruiter Posts boost ─────────────────────────────────────────────────────
# A Recruiter Post (source_tier='social') competes for a "newest" or "salary"
# ranking against a far larger, longer-lived pool of aggregator rows, so under a
# single sort it can fall past page 3 — even though the point of Secret Market
# ingestion is that these vacancies are not posted anywhere a Seeker would
# otherwise see them. Product wants them quickly visible, but not the whole
# board: a fixed cadence merge, not a resort and not a random shuffle. One slot
# in every BOOST_STRIDE is reserved for the next Recruiter Post in the caller's
# own sort order; every other slot is filled by the next non-Recruiter-Post row
# in that same order. Ranking WITHIN a tier never changes — only which tier
# occupies which slot does.
#
# Opt-in via `boost_recruiter_posts` on `list_jobs`: role_feed's candidate
# window re-ranks by its own recommendation score and would just discard this
# ordering, so it has no reason to pay for the extra window-function pass.
BOOST_STRIDE = 4
BOOST_OFFSET = 3
#: Every slot in a stride except the reserved one, in fill order — [1, 2, 4] at
#: the defaults above.
_BOOST_FILL_OFFSETS = [n for n in range(1, BOOST_STRIDE + 1) if n != BOOST_OFFSET]


def _boosted_rows_sql(where_sql: str, order_sql: str) -> str:
    """
    A query equivalent to `{BASE_SELECT} {where_sql}`, plus one extra column,
    `boost_slot`, that a caller `ORDER BY`s instead of `order_sql` directly.

    Two SQLite window-function passes. `tier_rank` is each row's 1-based rank
    inside its own tier (Recruiter Post vs. everything else), by `order_sql` —
    the caller's actual sort is untouched, just computed once per tier instead
    of once overall. `boost_slot` then places tier rank N of the Recruiter Post
    tier at `BOOST_STRIDE*(N-1) + BOOST_OFFSET`, and tier rank N of everything
    else at the next free slot in stride order (a stable merge of the two
    already-sorted tiers). If one tier is empty — a single-tier filter, or a
    catalogue audience that excludes Recruiter Posts entirely — every row lands
    in the other tier's branch, whose slot function is monotonic in `tier_rank`,
    so the result is `order_sql`'s own order with no special-casing needed.
    """
    block = len(_BOOST_FILL_OFFSETS)
    fill_case = " ".join(
        f"WHEN {i} THEN {offset}" for i, offset in enumerate(_BOOST_FILL_OFFSETS)
    )
    ranked = f"""
      SELECT
        {_SELECT_COLUMNS},
        ROW_NUMBER() OVER (
          PARTITION BY (j.source_tier = 'social') ORDER BY {order_sql}
        ) AS tier_rank
      {_FROM}
      {where_sql}
    """
    return f"""
      SELECT *,
        CASE WHEN source_tier = 'social'
          THEN {BOOST_STRIDE} * (tier_rank - 1) + {BOOST_OFFSET}
          ELSE {BOOST_STRIDE} * ((tier_rank - 1) / {block})
               + CASE (tier_rank - 1) % {block} {fill_case} END
        END AS boost_slot
      FROM ({ranked})
    """


# ── Row mapping ───────────────────────────────────────────────────────────────


def _parse_json_list(value: Optional[str]) -> list[str]:
    if not value:
        return []
    try:
        result = json.loads(value)
        return result if isinstance(result, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


_ANNUAL_SALARY_RE = re.compile(
    r"\b(?:per\s+annum|per\s+year|yearly)\b"
    r"|\bannual\s+(?:base\s+)?salary\b"
    r"|\bsalary.{0,40}\bannual(?:ly)?\b"
    r"|/(?:yr|year)\b|\bp\.?a\.?\b",
    re.IGNORECASE,
)
_MONTHLY_SALARY_RE = re.compile(
    r"\bper\s+month\b"
    r"|\bmonthly\s+(?:base\s+)?salary\b"
    r"|\bsalary.{0,40}\bmonthly\b"
    r"|/(?:mo|month)\b|\bpcm\b|月薪",
    re.IGNORECASE,
)
_MAX_PLAUSIBLE_MONTHLY_SALARY = 200_000


def _salary_period(row: sqlite3.Row) -> Literal["month", "year"] | None:
    """Infer the quoted period while legacy enrichment rows lack a unit column.

    The Hong Kong catalogue treats salary filters and estimates as monthly. A
    disclosed figure keeps an explicit source period when the posting states
    one; otherwise a figure above the calibrated monthly ceiling is annual and
    a plausible HK monthly amount defaults to month. This makes ambiguous copy
    such as "up to HK$30K" read as the market convention it actually uses.
    """
    values = [row["salary_hkd_min"], row["salary_hkd_max"]]
    stated = [int(value) for value in values if value is not None]
    if not stated:
        return None
    evidence = " ".join(
        str(value or "") for value in (row["description_clean"], row["description_summary"])
    )
    if _MONTHLY_SALARY_RE.search(evidence):
        return "month"
    if _ANNUAL_SALARY_RE.search(evidence):
        return "year"
    return "year" if max(stated) > _MAX_PLAUSIBLE_MONTHLY_SALARY else "month"


def _own_signals(row: sqlite3.Row) -> dict[str, dict]:
    """This row's own board_signals, namespaced by its source ({source: {...}})."""
    try:
        sig = json.loads(row["board_signals"] or "{}")
    except (TypeError, ValueError, IndexError):
        sig = {}
    return {row["source"]: sig} if sig else {}


def _to_summary(row: sqlite3.Row) -> JobSummary:
    desc = row["description_clean"] or ""
    excerpt = desc[:200].rstrip() + ("…" if len(desc) > 200 else "")
    return JobSummary(
        source=row["source"],
        source_id=row["source_id"],
        company=row["company"],
        sector=row["sector"],
        title=row["title"],
        title_en=row["title_en"],
        source_tier=row["source_tier"] or "mainstream",
        locations=_parse_json_list(row["locations"]),
        seniority=row["seniority"],
        job_category=row["job_category"],
        remote_type=row["remote_type"],
        required_skills=_parse_json_list(row["required_skills"]),
        salary_hkd_min=row["salary_hkd_min"],
        salary_hkd_max=row["salary_hkd_max"],
        salary_period=_salary_period(row),
        salary_estimated_min=row["salary_estimated_min"],
        salary_estimated_max=row["salary_estimated_max"],
        salary_estimated_confidence=row["salary_estimated_confidence"],
        years_experience_required=row["years_experience_required"],
        posted_at=row["posted_at"],
        url=row["url"],
        is_internship=bool(row["is_internship"]),
        description_excerpt=excerpt,
        closed=not row["is_active"],
        board_signals=_own_signals(row),
    )


def _attach_group_signals(
    conn: sqlite3.Connection,
    rows: Sequence[sqlite3.Row],
    summaries: Sequence[JobSummary],
) -> None:
    """
    Give each cross-posted card the signals from every copy of its vacancy.

    A displayed card is one copy of a cross-posted vacancy; its signals may live
    on a copy from another board that the board never shows. Copies share an
    apply_url (set by reconcile_cross_posted), so that is the group key.
    """
    apply_urls = [r["raw_apply_url"] for r in rows if r["cross_posted"] and r["raw_apply_url"]]
    if not apply_urls:
        return

    ph = ",".join("?" * len(apply_urls))
    group_rows = conn.execute(
        f"SELECT apply_url, source, board_signals FROM jobs "
        f"WHERE is_active = 1 AND cross_posted = 1 AND apply_url IN ({ph})",
        apply_urls,
    ).fetchall()

    by_url: dict[str, dict[str, dict]] = {}
    for g in group_rows:
        try:
            sig = json.loads(g["board_signals"] or "{}")
        except (TypeError, ValueError):
            sig = {}
        if sig:
            by_url.setdefault(g["apply_url"], {})[g["source"]] = sig

    for row, summary in zip(rows, summaries):
        if row["cross_posted"] and row["raw_apply_url"] in by_url:
            summary.board_signals = by_url[row["raw_apply_url"]]


# ── The interface ─────────────────────────────────────────────────────────────

#: How many (source, source_id) pairs go into one query in `jobs_by_refs`.
#: SQLite caps expression-tree depth at 1000, and an OR-chain of pair terms hits
#: it somewhere between 500 and 1000 refs — at which point the whole request
#: raised OperationalError and the Seeker could not even unsave their way out,
#: because the list is what crashed.
_REF_CHUNK = 200


def list_jobs(
    conn: sqlite3.Connection,
    filters: JobFilters,
    *,
    sort: Sort = Sort.NEWEST,
    page: int = 1,
    page_size: int = 24,
    visibility: Visibility = Visibility.BOARD,
    audience: CatalogueAudience = CatalogueAudience.PUBLIC,
    boost_recruiter_posts: bool = False,
) -> JobListResponse:
    """
    One page of the board.

    `boost_recruiter_posts` interleaves `source_tier='social'` rows into a
    fixed cadence near the top of EVERY page instead of leaving them to rank
    purely on `sort` — see `_boosted_rows_sql`. It changes row order only:
    `total`/`total_pages` and the WHERE clause (filters, visibility, audience)
    are identical with it on or off.
    """
    # One search_index lookup, used twice: to filter (in _where, via the IN
    # clause) and, if the caller asked for RELEVANCE, to order. Computed once
    # here rather than inside _where so _where can stay a pure string/param
    # builder that never touches conn.
    search_rowids = search_index.matching_rowids(conn, filters.search) if filters.search else None
    where_sql, params = _where(filters, visibility, search_rowids, audience)
    offset = (page - 1) * page_size

    # RELEVANCE with no search term (or one that matched nothing) has no
    # ranking to fall back on — NEWEST is the same silent fallback an unknown
    # Sort value not in _SORT_SQL would need anyway.
    order_sql = (
        _relevance_order_sql(search_rowids)
        if sort == Sort.RELEVANCE and search_rowids
        else _SORT_SQL[Sort.NEWEST if sort == Sort.RELEVANCE else sort]
    )

    total = conn.execute(f"{_COUNT_SELECT} {where_sql}", params).fetchone()[0]

    if boost_recruiter_posts:
        rows_sql = (
            f"SELECT * FROM ({_boosted_rows_sql(where_sql, order_sql)}) "
            "ORDER BY boost_slot ASC, tier_rank ASC"
        )
    else:
        rows_sql = f"{BASE_SELECT} {where_sql} ORDER BY {order_sql}"

    rows = conn.execute(
        f"{rows_sql} LIMIT ? OFFSET ?",
        params + [page_size, offset],
    ).fetchall()

    summaries = [_to_summary(r) for r in rows]
    _attach_group_signals(conn, rows, summaries)

    return JobListResponse(
        total=total,
        page=page,
        page_size=page_size,
        total_pages=math.ceil(total / page_size) if total else 0,
        jobs=summaries,
    )


def research_facets(
    conn: sqlite3.Connection,
    query: str,
    *,
    audience: CatalogueAudience = CatalogueAudience.PUBLIC,
) -> ResearchFacets:
    """Filter choices and counts drawn only from Roles matched by ``query``."""
    rowids = search_index.matching_rowids(conn, query)
    audience_sql = (
        f" AND {PUBLIC_AUDIENCE_WHERE}"
        if audience == CatalogueAudience.PUBLIC
        else ""
    )
    research = (
        f"{BOARD_WHERE}{audience_sql} AND j.rowid IN ({','.join(str(rowid) for rowid in rowids)})"
        if rowids
        else f"{BOARD_WHERE}{audience_sql} AND 0"
    )

    total = conn.execute(f"SELECT COUNT(*) FROM jobs j WHERE {research}").fetchone()[0]
    companies = [
        NameCount(name=row["company"], count=row["cnt"])
        for row in conn.execute(
            "SELECT j.company, COUNT(*) AS cnt FROM jobs j"
            f" WHERE {research} GROUP BY j.company ORDER BY cnt DESC, j.company",
        ).fetchall()
    ]
    sectors = [
        NameCount(name=row["sector"], count=row["cnt"])
        for row in conn.execute(
            f"""
            SELECT sector, COUNT(*) AS cnt FROM (
              SELECT ({SECTOR_SQL}) AS sector
              FROM jobs j
              LEFT JOIN job_enrichments e
                ON j.source=e.source AND j.source_id=e.source_id
              WHERE {research}
            ) scoped GROUP BY sector ORDER BY cnt DESC, sector
            """
        ).fetchall()
    ]
    skills = [
        NameCount(name=row["skill"], count=row["cnt"])
        for row in conn.execute(
            f"""
            SELECT LOWER(sk.value) AS skill, COUNT(*) AS cnt
            FROM jobs j
            JOIN job_enrichments e
              ON j.source=e.source AND j.source_id=e.source_id
            JOIN json_each(e.required_skills) sk
            WHERE {research}
              AND e.required_skills IS NOT NULL
              AND e.required_skills != '[]'
            GROUP BY LOWER(sk.value)
            ORDER BY cnt DESC, skill
            LIMIT 100
            """
        ).fetchall()
    ]
    seniority_levels = [
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT e.seniority FROM job_enrichments e"
            " JOIN jobs j ON j.source=e.source AND j.source_id=e.source_id"
            f" WHERE {research} AND e.seniority IS NOT NULL ORDER BY e.seniority"
        ).fetchall()
    ]
    remote_types = [
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT e.remote_type FROM job_enrichments e"
            " JOIN jobs j ON j.source=e.source AND j.source_id=e.source_id"
            f" WHERE {research} AND e.remote_type IS NOT NULL ORDER BY e.remote_type"
        ).fetchall()
    ]
    salary = conn.execute(
        "SELECT MIN(COALESCE(e.salary_hkd_min, e.salary_estimated_min)),"
        " MAX(COALESCE(e.salary_hkd_max, e.salary_estimated_max))"
        " FROM job_enrichments e"
        " JOIN jobs j ON j.source=e.source AND j.source_id=e.source_id"
        f" WHERE {research}"
    ).fetchone()
    experience = conn.execute(
        "SELECT MIN(e.years_experience_required), MAX(e.years_experience_required)"
        " FROM job_enrichments e"
        " JOIN jobs j ON j.source=e.source AND j.source_id=e.source_id"
        f" WHERE {research}"
    ).fetchone()
    tier_counts = {
        row["tier"]: row["cnt"]
        for row in conn.execute(
            "SELECT COALESCE(j.source_tier, 'mainstream') AS tier, COUNT(*) AS cnt"
            f" FROM jobs j WHERE {research} GROUP BY tier"
        ).fetchall()
    }

    return ResearchFacets(
        research_total=total,
        tier_counts=tier_counts,
        companies=companies,
        sectors=sectors,
        skills=skills,
        seniority_levels=seniority_levels,
        remote_types=remote_types,
        salary_range=NumericRange(min=salary[0], max=salary[1]),
        experience_range=NumericRange(min=experience[0], max=experience[1]),
    )


def get_job(
    conn: sqlite3.Connection,
    source: str,
    source_id: str,
    *,
    visibility: Visibility = Visibility.ADDRESSABLE,
) -> Optional[JobDetail]:
    """
    One Role by reference, or `None` if no such row exists.

    `None` rather than an exception: this module does not know what a 404 is.
    """
    where_sql, params = _where(JobFilters(), visibility)
    ref = "j.source = ? AND j.source_id = ?"
    clause = f"{where_sql} AND {ref}" if where_sql else f"WHERE {ref}"

    row = conn.execute(f"{BASE_SELECT} {clause}", params + [source, source_id]).fetchone()
    if row is None:
        return None

    summary = _to_summary(row)
    _attach_group_signals(conn, [row], [summary])

    return JobDetail(
        **summary.model_dump(),
        description_clean=row["description_clean"] or "",
        description_summary=row["description_summary"] or "",
        sources=_group_sources(conn, source, source_id),
    )


def list_sitemap_refs(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """
    Every (source, source_id) the public sitemap should list.

    Same BOARD_WHERE rule as browsing — one row per live vacancy, no duplicate
    cross-posted copies — but deliberately with NO tier restriction. The public
    teaser pages this feeds (see main.py) are open to every tier, unlike the
    board itself: a search engine is not a discovery path ADR 0018 gates.
    """
    return conn.execute(
        f"""
        SELECT j.source, j.source_id, j.title, j.company, j.posted_at
        {_FROM}
        WHERE {BOARD_WHERE}
        ORDER BY j.posted_at DESC
        """
    ).fetchall()


def _group_sources(conn: sqlite3.Connection, source: str, source_id: str) -> list[str]:
    """
    Which job boards this vacancy is on.

    A cross-posted role's copies all share the same apply_url (set by
    reconcile_cross_posted), so that URL is a reliable group key. Single-source
    roles have apply_url='' → just themselves.
    """
    meta = conn.execute(
        "SELECT apply_url, cross_posted FROM jobs WHERE is_active = 1 AND source = ? AND source_id = ?",
        [source, source_id],
    ).fetchone()
    if not (meta and meta["cross_posted"] and meta["apply_url"]):
        return [source]

    group = conn.execute(
        "SELECT DISTINCT source FROM jobs WHERE is_active = 1 AND cross_posted = 1 AND apply_url = ?",
        [meta["apply_url"]],
    ).fetchall()
    return sorted({r["source"] for r in group} | {source})


def jobs_by_refs(
    conn: sqlite3.Connection,
    refs: Iterable[tuple[str, str]],
    *,
    visibility: Visibility = Visibility.ADDRESSABLE,
) -> list[JobSummary]:
    """
    Resolve `(source, source_id)` references, preserving the caller's order.

    Every reference that still has a row comes back, in whatever state it is in —
    including `closed=True`. A reference whose row has left jobs.db entirely is
    dropped; there is nothing to render but the reference.

    For a Seeker's Saved Roles use `saved_roles` instead: it is this, plus the
    retention rule, and that rule is not something a caller should be spelling.
    """
    return _by_refs(conn, list(refs), visibility)


#: How long a Closed Role stays in a Seeker's Saved Roles before it drops out.
#:
#: Not a visibility rule and deliberately not a third `Visibility` member — the
#: question is not "may this Seeker see this row" but "is this still worth
#: keeping in front of them". ADR 0010 asks that anything reaching for a third
#: visibility rule be argued as a new KIND of question; this one is a retention
#: rule that happens to read the same column, and lives here so no route handler
#: can pick its own fortnight. See docs/adr/0011.
SAVED_ROLE_RETENTION = timedelta(days=14)

#: Keep a Saved Role unless it is closed AND we can date that closure AND the
#: date is older than the cutoff. Every unknown keeps the Role: a NULL
#: `closed_at` (a row that closed before phase 30 and was never backfilled) and
#: an unparseable one (`datetime()` returns NULL) both fail open. Hiding a Saved
#: Role is the destructive direction — the Seeker did not ask for it to go — so
#: it happens only on a date we can actually read.
_RETENTION_SQL = (
    "(j.is_active = 1"
    " OR j.closed_at IS NULL"
    " OR datetime(j.closed_at) IS NULL"
    " OR datetime(j.closed_at) >= datetime(?))"
)


def saved_roles(
    conn: sqlite3.Connection,
    refs: Iterable[tuple[str, str]],
    *,
    now: Optional[datetime] = None,
) -> list[JobSummary]:
    """
    A Seeker's Saved Roles: their references resolved, minus the long-dead ones.

    Open Roles and recently-Closed ones come back exactly as `jobs_by_refs`
    returns them, order preserved. A Role that has been Closed for longer than
    `SAVED_ROLE_RETENTION` is left out.

    The row is NOT touched — not the Listing in jobs.db, not the reference in
    seekers.db. This is a read-time rule and nothing else, which is what makes it
    reversible: a Listing that reopens has its `closed_at` cleared by the upsert,
    and the Saved Role comes back on its own without the Seeker doing anything.

    `now` is injectable because the alternative is a test that sleeps for a
    fortnight.
    """
    pairs = list(refs)
    if not pairs:
        return []

    cutoff = (now or datetime.now(timezone.utc)) - SAVED_ROLE_RETENTION
    return _by_refs(
        conn,
        pairs,
        Visibility.ADDRESSABLE,
        extra_sql=_RETENTION_SQL,
        extra_params=[cutoff.isoformat()],
    )


def _by_refs(
    conn: sqlite3.Connection,
    pairs: list[tuple[str, str]],
    visibility: Visibility,
    *,
    extra_sql: Optional[str] = None,
    extra_params: Sequence = (),
) -> list[JobSummary]:
    """Shared body of `jobs_by_refs` and `saved_roles`. Order follows `pairs`."""
    if not pairs:
        return []

    where_sql, base_params = _where(JobFilters(), visibility)
    head_params = list(base_params)
    if extra_sql:
        where_sql = f"{where_sql} AND {extra_sql}" if where_sql else f"WHERE {extra_sql}"
        head_params += list(extra_params)

    by_key: dict[tuple[str, str], sqlite3.Row] = {}
    for start in range(0, len(pairs), _REF_CHUNK):
        chunk = pairs[start:start + _REF_CHUNK]
        ref_clause = " OR ".join(["(j.source = ? AND j.source_id = ?)"] * len(chunk))
        clause = f"{where_sql} AND ({ref_clause})" if where_sql else f"WHERE ({ref_clause})"
        params = head_params + [value for pair in chunk for value in pair]
        for row in conn.execute(f"{BASE_SELECT} {clause}", params).fetchall():
            by_key[(row["source"], row["source_id"])] = row

    rows = [by_key[p] for p in pairs if p in by_key]
    summaries = [_to_summary(r) for r in rows]
    _attach_group_signals(conn, rows, summaries)
    return summaries
