"""
Reading Roles out of jobs.db.

WHY THIS MODULE EXISTS
----------------------
The rule for which rows a visitor may see — `is_active = 1 AND is_primary = 1` —
used to live inside one filter-building function in main.py, and two of the three
read paths never called it. `get_job` applied half of it; `list_saved` applied
none, so a Saved Role that had closed months ago came back looking live, which is
the exact behaviour CONTEXT.md promises Saved Roles do not have. The rule had no
home, so callers forgot it.

It has a home now. Everything the three read paths share sits behind this
module's interface: the select and its column aliases, the visibility rule, the
filters, the sort, the count, the row-to-wire mapping, and the cross-post signal
aggregation. A caller cannot spell a visibility rule of its own.

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
from enum import Enum
from typing import Iterable, Optional, Sequence

from pydantic import BaseModel

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


#: The SQL each rule contributes to the WHERE clause. `None` means "no predicate",
#: which is a deliberate value rather than an oversight: addressing a Role by
#: reference is unfiltered by design.
_VISIBILITY_SQL: dict[Visibility, Optional[str]] = {
    Visibility.BOARD: "j.is_active = 1 AND j.is_primary = 1",
    Visibility.ADDRESSABLE: None,
}


class Sort(str, Enum):
    NEWEST = "newest"
    SALARY_HIGH = "salary_high"
    SALARY_LOW = "salary_low"
    COMPANY = "company"


# ── Sector taxonomy ───────────────────────────────────────────────────────────
# Derived from the employer name at read time; jobs.db has no sector column.
# Lives here rather than in main.py because BASE_SELECT embeds it, and importing
# it back out of main.py would be a cycle. /api/filters and /api/stats import it
# from here.

_IB_TERMS = [
    "goldman", "morgan stanley", "deutsche bank", "barclays",
    "jpmorgan chase", "bank of america", "ubs",
    "hong kong exchanges",          # HKEX — market operator
    "futu", "cicc", "china international capital",
    "citic futures",                # CITIC Futures (brokerage); China CITIC Bank stays Banking
]
_INS_TERMS = [
    "manulife", "axa", "aia", "prudential", "fwd", "sun life",
    "zurich", "generali", "china life", "china pacific", "ping an",
    "chubb", "swiss re", "samsung life", "allianz", "nippon", "metlife",
]
_AM_TERMS = [
    "blackrock", "value partners", "macquarie", "fidelity",
    "state street", "invesco", "bnp paribas am", "man group",
    "schroders", "northern trust", "jpm am", "pimco", "kkr",
    "franklin", "amundi",
]
# Professional services (Big 4). EY's advertiser is literally "EY", matched
# EXACTLY (in _PS_EXACT) — a "%ey%" LIKE would wrongly match money/survey/key.
_PS_TERMS = ["kpmg", "pwc", "pricewaterhouse", "deloitte", "ernst & young", "ernst and young"]
_PS_EXACT = ["ey"]
# Digital assets / crypto.
_DA_TERMS = ["hashkey"]


def _sector_clause(like_terms, exact_terms=()) -> str:
    """Build a parenthesised OR clause of LIKE-substring + exact-equality matches."""
    parts = [f"LOWER(j.company) LIKE '%{t}%'" for t in like_terms]
    parts += [f"LOWER(j.company) = '{t}'" for t in exact_terms]
    return "(" + " OR ".join(parts) + ")"


_DA_COND = _sector_clause(_DA_TERMS)
_PS_COND = _sector_clause(_PS_TERMS, _PS_EXACT)
_IB_COND = _sector_clause(_IB_TERMS)
_INS_COND = _sector_clause(_INS_TERMS)
_AM_COND = _sector_clause(_AM_TERMS)

#: Named sector → the condition that selects it. Banking is absent on purpose:
#: it is defined as "none of the others", built in `_sector_condition`.
_SECTOR_CONDS: dict[str, str] = {
    "Digital Assets": _DA_COND,
    "Professional Services": _PS_COND,
    "Investment Banking": _IB_COND,
    "Insurance": _INS_COND,
    "Asset Management": _AM_COND,
}

SECTOR_SQL = "CASE " + " ".join(
    f"WHEN {cond} THEN '{name}'" for name, cond in _SECTOR_CONDS.items()
) + " ELSE 'Banking' END"


def _sector_condition(name: str) -> str:
    """
    The WHERE fragment selecting one sector.

    Banking is the fallthrough bucket, so filtering for it means negating every
    other sector. Deriving that from the same table the CASE is built from is
    what stops the two drifting — the old hand-written negation had to be
    updated by hand whenever a sector was added, and forgetting it made Banking
    silently double-count.
    """
    if name in _SECTOR_CONDS:
        return _SECTOR_CONDS[name]
    return "(" + " AND ".join(f"NOT {c}" for c in _SECTOR_CONDS.values()) + ")"


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

BASE_SELECT = f"""
  SELECT
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
  {_FROM}
""".strip()

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


def _where(filters: JobFilters, visibility: Visibility) -> tuple[str, list]:
    conditions: list[str] = []
    params: list = []

    rule = _VISIBILITY_SQL[visibility]
    if rule:
        conditions.append(rule)

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
        conditions.append("(LOWER(j.title) LIKE ? OR LOWER(j.company) LIKE ?)")
        s = f"%{filters.search.lower()}%"
        params += [s, s]

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

_SORT_SQL: dict[Sort, str] = {
    Sort.NEWEST: f"{_VALID_POSTED} DESC NULLS LAST",
    Sort.SALARY_HIGH: f"CASE WHEN {_SAL_HIGH} IS NULL THEN 1 ELSE 0 END, {_SAL_HIGH} DESC",
    Sort.SALARY_LOW: f"CASE WHEN {_SAL_LOW} IS NULL THEN 1 ELSE 0 END, {_SAL_LOW} ASC",
    Sort.COMPANY: "j.company ASC",
}


# ── Row mapping ───────────────────────────────────────────────────────────────


def _parse_json_list(value: Optional[str]) -> list[str]:
    if not value:
        return []
    try:
        result = json.loads(value)
        return result if isinstance(result, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


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
) -> JobListResponse:
    """One page of the board."""
    where_sql, params = _where(filters, visibility)
    offset = (page - 1) * page_size

    total = conn.execute(f"{_COUNT_SELECT} {where_sql}", params).fetchone()[0]
    rows = conn.execute(
        f"{BASE_SELECT} {where_sql} ORDER BY {_SORT_SQL[sort]} LIMIT ? OFFSET ?",
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

    Built for Saved Roles: seekers.db stores references only, never a copy of the
    Role, so the Role a Seeker sees is always the Role as it stands now —
    including `closed=True` once it is gone. A reference whose row has left
    jobs.db entirely is dropped; there is nothing to render but the reference.
    """
    pairs = list(refs)
    if not pairs:
        return []

    where_sql, base_params = _where(JobFilters(), visibility)
    by_key: dict[tuple[str, str], sqlite3.Row] = {}

    for start in range(0, len(pairs), _REF_CHUNK):
        chunk = pairs[start:start + _REF_CHUNK]
        ref_clause = " OR ".join(["(j.source = ? AND j.source_id = ?)"] * len(chunk))
        clause = f"{where_sql} AND ({ref_clause})" if where_sql else f"WHERE ({ref_clause})"
        params = base_params + [value for pair in chunk for value in pair]
        for row in conn.execute(f"{BASE_SELECT} {clause}", params).fetchall():
            by_key[(row["source"], row["source_id"])] = row

    rows = [by_key[p] for p in pairs if p in by_key]
    summaries = [_to_summary(r) for r in rows]
    _attach_group_signals(conn, rows, summaries)
    return summaries
