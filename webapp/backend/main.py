"""
FinEx Careers — FastAPI backend
Read-only access to jobs.db (SQLite).
"""

from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ── DB path ───────────────────────────────────────────────────────────────────

DB_PATH = (Path(__file__).parent.parent.parent / "data" / "jobs.db").resolve()


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA query_only=ON")
    return conn


# ── Sector logic ──────────────────────────────────────────────────────────────

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


def _sector_clause(like_terms, exact_terms=()):
    """Build a parenthesised OR clause of LIKE-substring + exact-equality matches."""
    parts = [f"LOWER(j.company) LIKE '%{t}%'" for t in like_terms]
    parts += [f"LOWER(j.company) = '{t}'" for t in exact_terms]
    return "(" + " OR ".join(parts) + ")"


_DA_COND  = _sector_clause(_DA_TERMS)
_PS_COND  = _sector_clause(_PS_TERMS, _PS_EXACT)
_IB_COND  = _sector_clause(_IB_TERMS)
_INS_COND = _sector_clause(_INS_TERMS)
_AM_COND  = _sector_clause(_AM_TERMS)

SECTOR_SQL = f"""
  CASE
    WHEN {_DA_COND}  THEN 'Digital Assets'
    WHEN {_PS_COND}  THEN 'Professional Services'
    WHEN {_IB_COND}  THEN 'Investment Banking'
    WHEN {_INS_COND} THEN 'Insurance'
    WHEN {_AM_COND}  THEN 'Asset Management'
    ELSE 'Banking'
  END
""".strip()

INTERNSHIP_COND = """(
  LOWER(j.title) LIKE '%intern%'
  OR LOWER(j.title) LIKE '%graduate trainee%'
  OR LOWER(j.title) LIKE '%summer analyst%'
  OR LOWER(j.title) LIKE '%summer associate%'
)"""

INTERNSHIP_SQL = f"CASE WHEN {INTERNSHIP_COND} THEN 1 ELSE 0 END"


# ── Pydantic models ────────────────────────────────────────────────────────────

class JobSummary(BaseModel):
    source: str
    source_id: str
    company: str
    sector: str
    title: str
    locations: list[str]
    seniority: Optional[str]
    job_category: Optional[str]
    remote_type: Optional[str]
    required_skills: list[str]
    salary_hkd_min: Optional[int]
    salary_hkd_max: Optional[int]
    years_experience_required: Optional[int]
    posted_at: Optional[str]
    url: str
    is_internship: bool
    description_excerpt: str


class JobDetail(JobSummary):
    description_clean: str


class JobListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    total_pages: int
    jobs: list[JobSummary]


class NameCount(BaseModel):
    name: str
    count: int


class SalaryRange(BaseModel):
    min: Optional[int]
    max: Optional[int]


class ExperienceRange(BaseModel):
    min: Optional[int]
    max: Optional[int]


class FiltersResponse(BaseModel):
    companies: list[NameCount]
    sectors: list[NameCount]
    skills: list[NameCount]
    seniority_levels: list[str]
    remote_types: list[str]
    salary_range: SalaryRange
    experience_range: ExperienceRange


class StatsResponse(BaseModel):
    total_active_jobs: int
    by_sector: dict[str, int]
    by_seniority: dict[str, int]
    by_remote_type: dict[str, int]
    top_skills: list[NameCount]
    top_companies: list[NameCount]
    internship_count: int


# ── Helpers ────────────────────────────────────────────────────────────────────

def _parse_json_list(value: Optional[str]) -> list[str]:
    if not value:
        return []
    try:
        result = json.loads(value)
        return result if isinstance(result, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _row_to_summary(row: sqlite3.Row) -> JobSummary:
    desc = row["description_clean"] or ""
    excerpt = desc[:200].rstrip() + ("…" if len(desc) > 200 else "")
    return JobSummary(
        source=row["source"],
        source_id=row["source_id"],
        company=row["company"],
        sector=row["sector"],
        title=row["title"],
        locations=_parse_json_list(row["locations"]),
        seniority=row["seniority"],
        job_category=row["job_category"],
        remote_type=row["remote_type"],
        required_skills=_parse_json_list(row["required_skills"]),
        salary_hkd_min=row["salary_hkd_min"],
        salary_hkd_max=row["salary_hkd_max"],
        years_experience_required=row["years_experience_required"],
        posted_at=row["posted_at"],
        url=row["url"],
        is_internship=bool(row["is_internship"]),
        description_excerpt=excerpt,
    )


# ── Base SELECT used by /api/jobs ─────────────────────────────────────────────

BASE_SELECT = f"""
  SELECT
    j.source,
    j.source_id,
    j.company,
    j.url,
    j.title,
    j.locations,
    j.description_clean,
    j.posted_at,
    e.seniority,
    e.job_category,
    e.remote_type,
    e.required_skills,
    e.salary_hkd_min,
    e.salary_hkd_max,
    e.years_experience_required,
    ({SECTOR_SQL}) AS sector,
    ({INTERNSHIP_SQL}) AS is_internship
  FROM jobs j
  LEFT JOIN job_enrichments e
    ON j.source = e.source AND j.source_id = e.source_id
""".strip()


def _build_where(
    search: Optional[str],
    sectors: list[str],
    companies: list[str],
    seniority: list[str],
    remote_type: list[str],
    skills: list[str],
    salary_min: Optional[int],
    salary_max: Optional[int],
    exp_min: Optional[int],
    exp_max: Optional[int],
    posted_within_days: Optional[int],
    is_internship: Optional[bool],
) -> tuple[str, list]:
    conditions: list[str] = ["j.is_active = 1"]
    params: list = []

    if search:
        conditions.append("(LOWER(j.title) LIKE ? OR LOWER(j.company) LIKE ?)")
        s = f"%{search.lower()}%"
        params += [s, s]

    if sectors:
        sector_parts: list[str] = []
        for sec in sectors:
            if sec == "Digital Assets":
                sector_parts.append(_DA_COND)
            elif sec == "Professional Services":
                sector_parts.append(_PS_COND)
            elif sec == "Investment Banking":
                sector_parts.append(_IB_COND)
            elif sec == "Insurance":
                sector_parts.append(_INS_COND)
            elif sec == "Asset Management":
                sector_parts.append(_AM_COND)
            else:  # Banking (everything not matched by a specific sector)
                sector_parts.append(
                    f"(NOT {_DA_COND} AND NOT {_PS_COND} AND NOT {_IB_COND} "
                    f"AND NOT {_INS_COND} AND NOT {_AM_COND})"
                )
        conditions.append("(" + " OR ".join(sector_parts) + ")")

    if companies:
        ph = ",".join("?" * len(companies))
        conditions.append(f"j.company IN ({ph})")
        params += list(companies)

    if seniority:
        ph = ",".join("?" * len(seniority))
        conditions.append(f"e.seniority IN ({ph})")
        params += list(seniority)

    if remote_type:
        ph = ",".join("?" * len(remote_type))
        conditions.append(f"e.remote_type IN ({ph})")
        params += list(remote_type)

    if skills:
        skill_parts = [
            "EXISTS (SELECT 1 FROM json_each(e.required_skills) sk"
            " WHERE LOWER(sk.value) = LOWER(?))"
        ]
        skill_cond = " OR ".join(skill_parts * len(skills))
        # rebuild correctly — one EXISTS per skill
        skill_parts2 = []
        for sk in skills:
            skill_parts2.append(
                "EXISTS (SELECT 1 FROM json_each(e.required_skills) sk"
                " WHERE LOWER(sk.value) = LOWER(?))"
            )
            params.append(sk)
        conditions.append("(" + " OR ".join(skill_parts2) + ")")

    if salary_min is not None:
        conditions.append("e.salary_hkd_min >= ?")
        params.append(salary_min)
    if salary_max is not None:
        conditions.append("e.salary_hkd_max <= ?")
        params.append(salary_max)

    if exp_min is not None:
        conditions.append("e.years_experience_required >= ?")
        params.append(exp_min)
    if exp_max is not None:
        conditions.append("e.years_experience_required <= ?")
        params.append(exp_max)

    if posted_within_days is not None:
        conditions.append("j.posted_at >= datetime('now', ?)")
        params.append(f"-{posted_within_days} days")

    if is_internship is not None:
        if is_internship:
            conditions.append(INTERNSHIP_COND)
        else:
            conditions.append(f"NOT {INTERNSHIP_COND}")

    where_sql = "WHERE " + " AND ".join(conditions)
    return where_sql, params


# ── App ────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="FinEx Careers API",
    description="Read-only API for Hong Kong financial job listings.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


# ── /api/jobs ─────────────────────────────────────────────────────────────────

@app.get("/api/jobs", response_model=JobListResponse, tags=["jobs"])
def list_jobs(
    search: Optional[str] = Query(None, description="Full-text search on title + company"),
    sectors: list[str] = Query(default=[], description="Filter by sector(s)"),
    companies: list[str] = Query(default=[], description="Filter by company name(s)"),
    seniority: list[str] = Query(default=[], description="Filter by seniority level(s)"),
    remote_type: list[str] = Query(default=[], description="Filter by remote type(s)"),
    skills: list[str] = Query(default=[], description="Filter by required skill(s)"),
    salary_min: Optional[int] = Query(None, description="Minimum HKD salary"),
    salary_max: Optional[int] = Query(None, description="Maximum HKD salary"),
    exp_min: Optional[int] = Query(None, description="Minimum years experience"),
    exp_max: Optional[int] = Query(None, description="Maximum years experience"),
    posted_within_days: Optional[int] = Query(None, description="Posted within N days"),
    is_internship: Optional[bool] = Query(None, description="Filter internships only"),
    sort: str = Query("newest", description="Sort: newest | salary_high | salary_low | company"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(24, ge=1, le=100, description="Results per page"),
):
    sort_clause = {
        "newest":      "j.posted_at DESC NULLS LAST",
        "salary_high": "e.salary_hkd_max DESC NULLS LAST",
        "salary_low":  "e.salary_hkd_min ASC NULLS LAST",
        "company":     "j.company ASC",
    }.get(sort, "j.posted_at DESC NULLS LAST")

    where_sql, params = _build_where(
        search, sectors, companies, seniority, remote_type, skills,
        salary_min, salary_max, exp_min, exp_max, posted_within_days, is_internship,
    )

    offset = (page - 1) * page_size

    with get_db() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM jobs j "
            f"LEFT JOIN job_enrichments e ON j.source=e.source AND j.source_id=e.source_id "
            f"{where_sql}",
            params,
        ).fetchone()[0]

        rows = conn.execute(
            f"{BASE_SELECT} {where_sql} ORDER BY {sort_clause} LIMIT ? OFFSET ?",
            params + [page_size, offset],
        ).fetchall()

    return JobListResponse(
        total=total,
        page=page,
        page_size=page_size,
        total_pages=math.ceil(total / page_size) if total else 0,
        jobs=[_row_to_summary(r) for r in rows],
    )


# ── /api/jobs/{source}/{source_id} ────────────────────────────────────────────

@app.get("/api/jobs/{source}/{source_id}", response_model=JobDetail, tags=["jobs"])
def get_job(source: str, source_id: str):
    sql = f"""
      {BASE_SELECT}
      WHERE j.is_active = 1 AND j.source = ? AND j.source_id = ?
    """
    with get_db() as conn:
        row = conn.execute(sql, [source, source_id]).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")

    summary = _row_to_summary(row)
    return JobDetail(
        **summary.model_dump(),
        description_clean=row["description_clean"] or "",
    )


# ── /api/filters ──────────────────────────────────────────────────────────────

@app.get("/api/filters", response_model=FiltersResponse, tags=["meta"])
def get_filters():
    with get_db() as conn:
        # Companies with count
        companies = [
            NameCount(name=r["company"], count=r["cnt"])
            for r in conn.execute(
                "SELECT j.company, COUNT(*) AS cnt FROM jobs j"
                " WHERE j.is_active=1 GROUP BY j.company ORDER BY cnt DESC",
            ).fetchall()
        ]

        # Sectors with count
        sectors_raw = conn.execute(
            f"""
            SELECT sector, COUNT(*) AS cnt FROM (
              SELECT ({SECTOR_SQL}) AS sector
              FROM jobs j
              LEFT JOIN job_enrichments e ON j.source=e.source AND j.source_id=e.source_id
              WHERE j.is_active=1
            ) sub GROUP BY sector ORDER BY cnt DESC
            """
        ).fetchall()
        sectors = [NameCount(name=r["sector"], count=r["cnt"]) for r in sectors_raw]

        # Top 100 skills
        skills_raw = conn.execute(
            """
            SELECT LOWER(sk.value) AS skill, COUNT(*) AS cnt
            FROM jobs j
            JOIN job_enrichments e ON j.source=e.source AND j.source_id=e.source_id
            JOIN json_each(e.required_skills) sk
            WHERE j.is_active=1
              AND e.required_skills IS NOT NULL
              AND e.required_skills != '[]'
            GROUP BY LOWER(sk.value)
            ORDER BY cnt DESC
            LIMIT 100
            """
        ).fetchall()
        skills = [NameCount(name=r["skill"], count=r["cnt"]) for r in skills_raw]

        # Seniority levels
        seniority_levels = [
            r[0] for r in conn.execute(
                "SELECT DISTINCT e.seniority FROM job_enrichments e"
                " JOIN jobs j ON j.source=e.source AND j.source_id=e.source_id"
                " WHERE j.is_active=1 AND e.seniority IS NOT NULL ORDER BY e.seniority"
            ).fetchall()
        ]

        # Remote types
        remote_types = [
            r[0] for r in conn.execute(
                "SELECT DISTINCT e.remote_type FROM job_enrichments e"
                " JOIN jobs j ON j.source=e.source AND j.source_id=e.source_id"
                " WHERE j.is_active=1 AND e.remote_type IS NOT NULL ORDER BY e.remote_type"
            ).fetchall()
        ]

        # Salary range
        sal = conn.execute(
            "SELECT MIN(e.salary_hkd_min), MAX(e.salary_hkd_max)"
            " FROM job_enrichments e JOIN jobs j ON j.source=e.source AND j.source_id=e.source_id"
            " WHERE j.is_active=1"
        ).fetchone()

        # Experience range
        exp = conn.execute(
            "SELECT MIN(e.years_experience_required), MAX(e.years_experience_required)"
            " FROM job_enrichments e JOIN jobs j ON j.source=e.source AND j.source_id=e.source_id"
            " WHERE j.is_active=1"
        ).fetchone()

    return FiltersResponse(
        companies=companies,
        sectors=sectors,
        skills=skills,
        seniority_levels=seniority_levels,
        remote_types=remote_types,
        salary_range=SalaryRange(min=sal[0], max=sal[1]),
        experience_range=ExperienceRange(min=exp[0], max=exp[1]),
    )


# ── /api/stats ────────────────────────────────────────────────────────────────

@app.get("/api/stats", response_model=StatsResponse, tags=["meta"])
def get_stats():
    with get_db() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE is_active=1"
        ).fetchone()[0]

        # By sector
        sectors_raw = conn.execute(
            f"""
            SELECT sector, COUNT(*) AS cnt FROM (
              SELECT ({SECTOR_SQL}) AS sector
              FROM jobs j
              LEFT JOIN job_enrichments e ON j.source=e.source AND j.source_id=e.source_id
              WHERE j.is_active=1
            ) sub GROUP BY sector ORDER BY cnt DESC
            """
        ).fetchall()
        by_sector = {r["sector"]: r["cnt"] for r in sectors_raw}

        # By seniority
        sen_raw = conn.execute(
            "SELECT e.seniority, COUNT(*) AS cnt"
            " FROM job_enrichments e JOIN jobs j ON j.source=e.source AND j.source_id=e.source_id"
            " WHERE j.is_active=1 AND e.seniority IS NOT NULL"
            " GROUP BY e.seniority ORDER BY cnt DESC"
        ).fetchall()
        by_seniority = {r["seniority"]: r["cnt"] for r in sen_raw}

        # By remote type
        rem_raw = conn.execute(
            "SELECT e.remote_type, COUNT(*) AS cnt"
            " FROM job_enrichments e JOIN jobs j ON j.source=e.source AND j.source_id=e.source_id"
            " WHERE j.is_active=1 AND e.remote_type IS NOT NULL"
            " GROUP BY e.remote_type ORDER BY cnt DESC"
        ).fetchall()
        by_remote_type = {r["remote_type"]: r["cnt"] for r in rem_raw}

        # Top 15 skills
        skills_raw = conn.execute(
            """
            SELECT LOWER(sk.value) AS skill, COUNT(*) AS cnt
            FROM jobs j
            JOIN job_enrichments e ON j.source=e.source AND j.source_id=e.source_id
            JOIN json_each(e.required_skills) sk
            WHERE j.is_active=1
              AND e.required_skills IS NOT NULL
              AND e.required_skills != '[]'
            GROUP BY LOWER(sk.value)
            ORDER BY cnt DESC
            LIMIT 15
            """
        ).fetchall()
        top_skills = [NameCount(name=r["skill"], count=r["cnt"]) for r in skills_raw]

        # Top 15 companies
        comp_raw = conn.execute(
            "SELECT j.company, COUNT(*) AS cnt FROM jobs j"
            " WHERE j.is_active=1 GROUP BY j.company ORDER BY cnt DESC LIMIT 15"
        ).fetchall()
        top_companies = [NameCount(name=r["company"], count=r["cnt"]) for r in comp_raw]

        # Internship count
        intern_count = conn.execute(
            f"SELECT COUNT(*) FROM jobs j WHERE j.is_active=1 AND {INTERNSHIP_COND}"
        ).fetchone()[0]

    return StatsResponse(
        total_active_jobs=total,
        by_sector=by_sector,
        by_seniority=by_seniority,
        by_remote_type=by_remote_type,
        top_skills=top_skills,
        top_companies=top_companies,
        internship_count=intern_count,
    )


# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok", "db": str(DB_PATH)}
