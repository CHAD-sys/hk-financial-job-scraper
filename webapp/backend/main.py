"""
FinEx Careers — FastAPI backend

Read access to jobs.db (SQLite), plus two write endpoints that do not touch the
database at all: /api/contact (consultation enquiries) and /api/post-role
(recruiter role submissions). Both persist to an append-only JSONL queue and
email a notification; neither publishes anything without human review.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field, field_validator

# Logging first, so that everything below — including the env load — is visible.
# uvicorn configures its own loggers and installs no root handler, so without
# this the application's INFO records are discarded entirely and only WARNING and
# above surface via logging's last-resort handler. That is why a *failed* send
# was visible but a successful one was not, which is exactly backwards for
# answering "did the email go out?".
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)

from env_file import load_env_file  # noqa: E402 — must import after logging setup

# MUST run before Settings.from_env() below, and before importing mailer, which
# reads its SMTP settings at import time. uvicorn does not source
# config/api_keys.env the way daily_run.sh does, so without this the backend
# starts with no credentials at all.
load_env_file()

import mailer  # noqa: E402 — see above
from mailer import RECIPIENT, SMTP_USER, send_mail  # noqa: E402

# The jobs read path. Everything about which Roles are visible, how they are
# filtered, sorted, counted and shaped for the wire lives in this module — see
# its docstring for why "browsing is filtered, addressing is not".
import job_read  # noqa: E402
from rate_limit import RateLimiter  # noqa: E402
from sender import Message, Sender, SmtpSender  # noqa: E402
from settings import Settings  # noqa: E402
from job_read import (  # noqa: E402
    BOARD_WHERE,
    INTERNSHIP_COND,
    SECTOR_SQL,
    JobDetail,
    JobFilters,
    JobListResponse,
    JobSummary,
    Sort,
    Visibility,
)

# ── Per-request dependencies ──────────────────────────────────────────────────
#
# Every route reaches its configuration through the app it is serving, never
# through a module global. That is what lets a test build a second app with a
# different database instead of deleting this module from sys.modules and
# re-importing it.

router = APIRouter()


def cfg(request: Request) -> Settings:
    """This app's settings."""
    return request.app.state.settings


def _seed_db_if_missing(settings: Settings) -> None:
    """
    Download the database once, if a seed URL is configured and it is absent.

    Called from the lifespan rather than at import: a slow or hanging download
    should delay startup visibly, not silently block `import main` — including
    inside a test process that inherited DB_SEED_URL from the developer's env
    file.
    """
    if settings.jobs_db.exists() or not settings.db_seed_url:
        return
    import urllib.request
    logger.info("Seeding %s from %s", settings.jobs_db, settings.db_seed_url)
    settings.jobs_db.parent.mkdir(parents=True, exist_ok=True)
    tmp = settings.jobs_db.with_name(settings.jobs_db.name + ".downloading")
    urllib.request.urlretrieve(settings.db_seed_url, tmp)  # noqa: S310 — operator-provided URL
    tmp.replace(settings.jobs_db)


def get_db(request: Request) -> sqlite3.Connection:
    """
    A read-only connection to jobs.db.

    `job_read.prepare` installs the row factory and the REGEXP function the read
    path needs — they are requirements of that module, so it owns them rather
    than this file remembering to repeat them.
    """
    conn = sqlite3.connect(cfg(request).jobs_db, check_same_thread=False)
    job_read.prepare(conn)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA query_only=ON")
    return conn


# ── Pydantic models ────────────────────────────────────────────────────────────

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
    by_source_tier: dict[str, int]
    top_skills: list[NameCount]
    top_companies: list[NameCount]
    internship_count: int


# ── App ────────────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Everything that must happen once, at startup — not at import.

    Seeding the database lives here because it is a network download: at import
    it blocked `import main`, which meant any process that merely imported this
    module (a test, a REPL, a linter) could start pulling a 100 MB file.

    The SMTP warning is here for a different reason: a missing mail setup breaks
    no request — submissions are still queued and still return 200 — so the only
    symptom is mail that never arrives. Saying so at boot, loudly, is what turns
    that into a five-second diagnosis.
    """
    settings: Settings = app.state.settings
    _seed_db_if_missing(settings)

    if SMTP_USER:
        logger.info("Email configured — enquiries will be sent to %s", RECIPIENT)
    else:
        logger.warning(
            "SMTP_USER/SMTP_PASS are not set. Submissions will still be queued to %s "
            "but NO email will be sent. Locally: check config/api_keys.env. "
            "In production: set them in the platform environment.",
            settings.submissions_dir,
        )

    if not settings.frontend_present():
        # Not fatal, by design: the API has to boot for backend-only local
        # development (and for a deploy whose build step failed, where a working
        # /api and a 404 UI is a far better failure than a service that will not
        # start at all).
        logger.warning(
            "No frontend bundle at %s — serving the API only. "
            "Build it with `npm run build` in webapp/frontend, or point FRONTEND_DIST "
            "at an existing dist/ directory.",
            settings.frontend_dist,
        )
    yield


# ── /api/jobs ─────────────────────────────────────────────────────────────────

@router.get("/api/jobs", response_model=JobListResponse, tags=["jobs"])
def list_jobs(
    request: Request,
    search: Optional[str] = Query(
        None,
        description="Full-text search across title, company, skills and description. "
                    "Tolerates typos and word order; sort=relevance ranks by match quality.",
    ),
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
    tier: Optional[str] = Query(
        None, description="Tier: boutique (Exclusive) | mainstream | social (Recruiter Posts) | all"
    ),
    is_new: Optional[bool] = Query(None, description="Only newly-posted jobs (board 'New' flag)"),
    urgently_hiring: Optional[bool] = Query(None, description="Only 'urgently hiring' jobs"),
    max_applicants: Optional[int] = Query(None, ge=1, description="Only jobs with fewer than N applicants"),
    hidden_only: Optional[bool] = Query(
        None, description="Only Recruiter Posts jobs with no match on any real board"
    ),
    verified_only: Optional[bool] = Query(
        None, description="Only jobs ghost_check confirmed match a real board listing"
    ),
    sort: Sort = Query(Sort.NEWEST, description="Sort order"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(24, ge=1, le=100, description="Results per page"),
):
    """
    Browse the board.

    Visibility is BOARD — active and primary — so a vacancy cross-posted to four
    sources appears once, not four times. Everything about how that is selected,
    filtered, sorted and counted lives in job_read.
    """
    filters = JobFilters.of(
        search=search, sectors=sectors, companies=companies, seniority=seniority,
        remote_type=remote_type, skills=skills, salary_min=salary_min,
        salary_max=salary_max, exp_min=exp_min, exp_max=exp_max,
        posted_within_days=posted_within_days, is_internship=is_internship,
        tier=tier, is_new=is_new, urgently_hiring=urgently_hiring,
        max_applicants=max_applicants, hidden_only=hidden_only,
        verified_only=verified_only,
    )
    with get_db(request) as conn:
        return job_read.list_jobs(
            conn, filters, sort=sort, page=page, page_size=page_size,
            visibility=Visibility.BOARD,
        )


# ── /api/jobs/{source}/{source_id} ────────────────────────────────────────────

@router.get("/api/jobs/{source}/{source_id}", response_model=JobDetail, tags=["jobs"])
def get_job(source: str, source_id: str, request: Request):
    """
    One Role, addressed by reference.

    Visibility is ADDRESSABLE: a URL naming a specific (source, source_id) gets
    that row whatever state it is in, and `closed` says which. Requiring
    is_primary here would 404 a link whose copy stopped being primary at the last
    reconciliation; requiring is_active would break every Saved Role the moment
    the vacancy closed, which is precisely when a Seeker wants to look at it.
    """
    with get_db(request) as conn:
        detail = job_read.get_job(conn, source, source_id, visibility=Visibility.ADDRESSABLE)
    if detail is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return detail


# ── /api/filters ──────────────────────────────────────────────────────────────

@router.get("/api/filters", response_model=FiltersResponse, tags=["meta"])
def get_filters(request: Request):
    with get_db(request) as conn:
        # Companies with count
        companies = [
            NameCount(name=r["company"], count=r["cnt"])
            for r in conn.execute(
                "SELECT j.company, COUNT(*) AS cnt FROM jobs j"
                f" WHERE {BOARD_WHERE} GROUP BY j.company ORDER BY cnt DESC",
            ).fetchall()
        ]

        # Sectors with count
        sectors_raw = conn.execute(
            f"""
            SELECT sector, COUNT(*) AS cnt FROM (
              SELECT ({SECTOR_SQL}) AS sector
              FROM jobs j
              LEFT JOIN job_enrichments e ON j.source=e.source AND j.source_id=e.source_id
              WHERE {BOARD_WHERE}
            ) sub GROUP BY sector ORDER BY cnt DESC
            """
        ).fetchall()
        sectors = [NameCount(name=r["sector"], count=r["cnt"]) for r in sectors_raw]

        # Top 100 skills
        skills_raw = conn.execute(
            f"""
            SELECT LOWER(sk.value) AS skill, COUNT(*) AS cnt
            FROM jobs j
            JOIN job_enrichments e ON j.source=e.source AND j.source_id=e.source_id
            JOIN json_each(e.required_skills) sk
            WHERE {BOARD_WHERE}
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
                f" WHERE {BOARD_WHERE} AND e.seniority IS NOT NULL ORDER BY e.seniority"
            ).fetchall()
        ]

        # Remote types
        remote_types = [
            r[0] for r in conn.execute(
                "SELECT DISTINCT e.remote_type FROM job_enrichments e"
                " JOIN jobs j ON j.source=e.source AND j.source_id=e.source_id"
                f" WHERE {BOARD_WHERE} AND e.remote_type IS NOT NULL ORDER BY e.remote_type"
            ).fetchall()
        ]

        # Salary range
        sal = conn.execute(
            "SELECT MIN(e.salary_hkd_min), MAX(e.salary_hkd_max)"
            " FROM job_enrichments e JOIN jobs j ON j.source=e.source AND j.source_id=e.source_id"
            f" WHERE {BOARD_WHERE}"
        ).fetchone()

        # Experience range
        exp = conn.execute(
            "SELECT MIN(e.years_experience_required), MAX(e.years_experience_required)"
            " FROM job_enrichments e JOIN jobs j ON j.source=e.source AND j.source_id=e.source_id"
            f" WHERE {BOARD_WHERE}"
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

@router.get("/api/stats", response_model=StatsResponse, tags=["meta"])
def get_stats(request: Request):
    with get_db(request) as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM jobs j WHERE {BOARD_WHERE}"
        ).fetchone()[0]

        # By sector
        sectors_raw = conn.execute(
            f"""
            SELECT sector, COUNT(*) AS cnt FROM (
              SELECT ({SECTOR_SQL}) AS sector
              FROM jobs j
              LEFT JOIN job_enrichments e ON j.source=e.source AND j.source_id=e.source_id
              WHERE {BOARD_WHERE}
            ) sub GROUP BY sector ORDER BY cnt DESC
            """
        ).fetchall()
        by_sector = {r["sector"]: r["cnt"] for r in sectors_raw}

        # By seniority
        sen_raw = conn.execute(
            "SELECT e.seniority, COUNT(*) AS cnt"
            " FROM job_enrichments e JOIN jobs j ON j.source=e.source AND j.source_id=e.source_id"
            f" WHERE {BOARD_WHERE} AND e.seniority IS NOT NULL"
            " GROUP BY e.seniority ORDER BY cnt DESC"
        ).fetchall()
        by_seniority = {r["seniority"]: r["cnt"] for r in sen_raw}

        # By remote type
        rem_raw = conn.execute(
            "SELECT e.remote_type, COUNT(*) AS cnt"
            " FROM job_enrichments e JOIN jobs j ON j.source=e.source AND j.source_id=e.source_id"
            f" WHERE {BOARD_WHERE} AND e.remote_type IS NOT NULL"
            " GROUP BY e.remote_type ORDER BY cnt DESC"
        ).fetchall()
        by_remote_type = {r["remote_type"]: r["cnt"] for r in rem_raw}

        # By source tier (powers the All / Exclusive / Mainstream tabs)
        tier_raw = conn.execute(
            "SELECT COALESCE(source_tier, 'mainstream') AS tier, COUNT(*) AS cnt"
            f" FROM jobs j WHERE {BOARD_WHERE} GROUP BY tier"
        ).fetchall()
        by_source_tier = {r["tier"]: r["cnt"] for r in tier_raw}

        # Top 15 skills
        skills_raw = conn.execute(
            f"""
            SELECT LOWER(sk.value) AS skill, COUNT(*) AS cnt
            FROM jobs j
            JOIN job_enrichments e ON j.source=e.source AND j.source_id=e.source_id
            JOIN json_each(e.required_skills) sk
            WHERE {BOARD_WHERE}
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
            f" WHERE {BOARD_WHERE} GROUP BY j.company ORDER BY cnt DESC LIMIT 15"
        ).fetchall()
        top_companies = [NameCount(name=r["company"], count=r["cnt"]) for r in comp_raw]

        # Internship count
        intern_count = conn.execute(
            f"SELECT COUNT(*) FROM jobs j WHERE {BOARD_WHERE} AND {INTERNSHIP_COND}"
        ).fetchone()[0]

    return StatsResponse(
        total_active_jobs=total,
        by_sector=by_sector,
        by_seniority=by_seniority,
        by_remote_type=by_remote_type,
        by_source_tier=by_source_tier,
        top_skills=top_skills,
        top_companies=top_companies,
        internship_count=intern_count,
    )


# ── Write endpoints ───────────────────────────────────────────────────────────
#
# The only two POSTs in the app. Neither writes to jobs.db: a consultation
# enquiry is not job data, and a submitted role must be reviewed by a person
# before it can appear on the board. Both append to a JSONL queue on disk first
# (durable) and then email a notification (best-effort) — so a mail outage
# delays the alert but never loses the submission.

# Rate limiting is in-memory and therefore per-app: it resets on deploy and does
# not span replicas. Adequate for a single instance at current traffic; move to
# Redis or a proxy-level limit before scaling out.
#
# The window and the log live on the app rather than on this module, so two apps
# in one process (which is what the tests now build) do not share a budget.
_RATE_WINDOW_S = 3600


def _client_ip(request: Request) -> str:
    """Left-most X-Forwarded-For entry when behind a proxy (Railway), else peer."""
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _rate_limited(request: Request, key: str) -> bool:
    return _limit(request, key, limit=cfg(request).submit_rate_limit, window_s=_RATE_WINDOW_S)


def _limit(request: Request, key: str, *, limit: int, window_s: int) -> bool:
    """
    True when this call should be REFUSED — the sense every call site reads.

    The window, the table, the clock and the sweep live in `rate_limit.py`; this
    is only the inversion. The table used to be a `defaultdict(list)` right here
    that never evicted a key, so an attacker choosing a fresh email each time
    grew it without bound (100,000 emails = 21.9 MiB, none of it ever reclaimed).
    """
    return not request.app.state.limiter.allow(key, limit=limit, window_s=window_s)


def _persist(request: Request, kind: str, payload: dict) -> bool:
    """Append one submission to data/{kind}.jsonl. Returns False if it could not
    be written — the only condition under which a submission is actually lost."""
    submissions = cfg(request).submissions_dir
    try:
        submissions.mkdir(parents=True, exist_ok=True)
        record = {"received_at": datetime.now(timezone.utc).isoformat(), **payload}
        with open(submissions / f"{kind}.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("Could not persist %s submission: %s", kind, exc)
        return False


CAREER_STAGES = {"3–8 years", "8–15 years", "15+ years", "C-suite / board"}
EMPLOYMENT_TYPES = {"Full-time", "Contract", "Part-time", "Internship"}


class EnquiryIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    career_stage: str = Field(max_length=40)
    message: str = Field(min_length=1, max_length=5000)
    # Honeypot. Named to look like a field worth filling; a human never sees it.
    website: str = ""

    @field_validator("career_stage")
    @classmethod
    def _known_stage(cls, v: str) -> str:
        if v not in CAREER_STAGES:
            raise ValueError("unknown career stage")
        return v


class RoleIn(BaseModel):
    contact_name: str = Field(min_length=1, max_length=100)
    contact_email: EmailStr
    company: str = Field(min_length=1, max_length=150)
    title: str = Field(min_length=1, max_length=200)
    location: str = Field(min_length=1, max_length=120)
    employment_type: str = Field(max_length=40)
    salary_range: str = Field(default="", max_length=100)
    description: str = Field(min_length=1, max_length=20000)
    apply_url: str = Field(min_length=1, max_length=500)
    website: str = ""

    @field_validator("employment_type")
    @classmethod
    def _known_type(cls, v: str) -> str:
        if v not in EMPLOYMENT_TYPES:
            raise ValueError("unknown employment type")
        return v

    @field_validator("apply_url")
    @classmethod
    def _http_url(cls, v: str) -> str:
        # Blocks javascript:, data: and mailto: — this URL is rendered as a link
        # on the board once approved.
        if not v.startswith(("http://", "https://")):
            raise ValueError("apply_url must start with http:// or https://")
        return v


class SubmitResponse(BaseModel):
    ok: bool


@router.post("/api/contact", response_model=SubmitResponse, tags=["submit"])
def submit_enquiry(payload: EnquiryIn, request: Request):
    """Executive Career Consultation enquiry → JSONL queue + email notification."""
    # A filled honeypot means a bot. Return the same 200 a human gets: telling it
    # that it was detected only helps the next attempt.
    if payload.website.strip():
        logger.info("Honeypot triggered on /api/contact from %s", _client_ip(request))
        return SubmitResponse(ok=True)

    if _rate_limited(request, f"contact:{_client_ip(request)}"):
        raise HTTPException(429, "Too many enquiries from this address. Please try again later.")

    data = payload.model_dump(exclude={"website"})
    stored = _persist(request, "enquiries", data)

    body = (
        f"New consultation enquiry\n\n"
        f"Name:         {data['name']}\n"
        f"Email:        {data['email']}\n"
        f"Career stage: {data['career_stage']}\n\n"
        f"{data['message']}\n"
    )
    sent = send_mail(f"Consultation enquiry — {data['name']}", body, reply_to=str(data["email"]))

    if not stored and not sent:
        raise HTTPException(500, "We could not record your enquiry. Please try again.")
    return SubmitResponse(ok=True)


@router.post("/api/post-role", response_model=SubmitResponse, tags=["submit"])
def submit_role(payload: RoleIn, request: Request):
    """
    Recruiter/employer role submission → JSONL moderation queue + email.

    Note this is NOT the board's Recruiter Posts tier, which is scraped LinkedIn
    activity. This is a direct submission channel, and nothing submitted here
    reaches the board until a human approves it.
    """
    if payload.website.strip():
        logger.info("Honeypot triggered on /api/post-role from %s", _client_ip(request))
        return SubmitResponse(ok=True)

    if _rate_limited(request, f"role:{_client_ip(request)}"):
        raise HTTPException(429, "Too many submissions from this address. Please try again later.")

    data = payload.model_dump(exclude={"website"})
    data["status"] = "pending"  # never anything else at rest; approval is manual
    stored = _persist(request, "submitted_roles", data)

    body = (
        f"New role submitted for review\n\n"
        f"Title:      {data['title']}\n"
        f"Company:    {data['company']}\n"
        f"Location:   {data['location']}\n"
        f"Type:       {data['employment_type']}\n"
        f"Salary:     {data['salary_range'] or '—'}\n"
        f"Apply URL:  {data['apply_url']}\n\n"
        f"Submitted by {data['contact_name']} <{data['contact_email']}>\n\n"
        f"--- Description ---\n{data['description']}\n"
    )
    sent = send_mail(
        f"Role submission — {data['title']} @ {data['company']}",
        body,
        reply_to=str(data["contact_email"]),
    )

    if not stored and not sent:
        raise HTTPException(500, "We could not record your submission. Please try again.")
    return SubmitResponse(ok=True)


# ── Health check ──────────────────────────────────────────────────────────────

@router.get("/health", tags=["meta"])
def health(request: Request):
    """
    Liveness plus the two bits of configuration that fail silently.

    `email` is reported because a misconfigured mailer does not break any
    request — submissions are still queued and still return 200 — so without
    surfacing it here the only symptom is an email that never arrives, which is
    exactly how this went unnoticed once already.
    """
    settings = cfg(request)
    return {
        "status": "ok",
        "db": str(settings.jobs_db),
        "email": "configured" if SMTP_USER else "NOT CONFIGURED — enquiries queue but no mail is sent",
        "enquiry_recipient": RECIPIENT if SMTP_USER else None,
        "submissions_dir": str(settings.submissions_dir),
        "frontend": str(settings.frontend_dist) if settings.frontend_present()
                    else "NOT BUILT — API only, no UI served",
    }


# ── Seeker accounts ───────────────────────────────────────────────────────────
# Phase 2 of docs/PLAN_ACCOUNTS.md. The crypto, sessions and storage all live in
# auth.py / seekers_store.py; this section is only the HTTP surface over them.
#
# Vocabulary note (CONTEXT.md): the account holder is a *Seeker*, never a "user".
#
# Nothing here gates anything. Per ADR 0002 the board stays fully public — these
# endpoints add capability for signed-in Seekers and take nothing away from
# anonymous ones. Do not "protect" any /api/jobs route with these dependencies.

import auth  # noqa: E402 — same local-module convention as mailer/env_file above
import seekers_store  # noqa: E402

SESSION_COOKIE = "finex_session"

def _set_session_cookie(request: Request, response: Response, raw_token: str) -> None:
    """
    Attach the session cookie.

    SameSite=Lax works here *only* because this service also serves the frontend
    (ADR 0005). If the UI were ever split back onto its own Railway domain, Lax
    would silently stop being sent — `up.railway.app` is a public suffix, so the
    two hosts are different sites — and every request would arrive anonymous with
    no error anywhere. Read ADR 0005 before changing the topology.
    """
    response.set_cookie(
        SESSION_COOKIE,
        raw_token,
        max_age=int(auth.SESSION_TTL.total_seconds()),
        httponly=True,          # unreadable to JS, so XSS cannot exfiltrate it
        secure=cfg(request).cookie_secure,
        samesite="lax",
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", samesite="lax")


def _current_seeker(request: Request) -> Optional[dict]:
    """
    The signed-in Seeker's row, or None. Never raises — anonymous is a normal
    state on this API, not an error, because nothing here is gated (ADR 0002).

    auth.verify_session() deliberately returns only a seeker_id and collapses
    every failure to None — unknown token, expired token, token belonging to a
    Seeker who has since deleted their account. We do the row lookup, and treat a
    missing row the same way: a valid-looking session for a Seeker who no longer
    exists is simply not signed in.
    """
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return None
    try:
        store = seekers_store.get_store()
        seeker_id = auth.verify_session(store, raw)
        return store.get_seeker(seeker_id) if seeker_id else None
    except Exception:  # noqa: BLE001 — a bad cookie is anonymous, not a 500
        logger.warning("Session verification failed", exc_info=True)
        return None


def _require_seeker(request: Request) -> dict:
    seeker = _current_seeker(request)
    if seeker is None:
        raise HTTPException(status_code=401, detail="Not signed in")
    return seeker


def _auth_rate_limited(request: Request, key: str, *, limit: int, window_s: int) -> bool:
    """
    The same sliding window as the submit endpoints, with per-call limits —
    3-per-hour is right for a contact form and would lock a Seeker out of their
    own account after three password typos.

    Same known weakness as the original: in-memory, so it resets on restart and
    does not survive multiple replicas. Accepted for now (PLAN_ACCOUNTS §5); it
    needs to be persistent before anyone pays us.
    """
    return _limit(request, key, limit=limit, window_s=window_s)


def _send_seeker_mail(request: Request, to: str, subject: str, body: str) -> bool:
    """
    Mail *to a Seeker*, at an address they typed.

    This is deliberately not mailer.send_mail(), which sends only to a hardcoded
    RECIPIENT precisely so that endpoint cannot become an open relay. Accounts
    invert that direction, which is why the rate limits above key on the target
    email and not only on the caller's IP: without that, anyone could point our
    sending reputation at a stranger's inbox.

    The sender is a collaborator of the app (see sender.py), not a module-level
    SMTP connection: that is what stops the test suite mailing real people, and
    what lets a test assert on what was sent.

    False means it did not go — because mail is not configured yet (ADR 0009,
    pending the mailbox password) or because the send failed. Registration must
    still succeed either way: the Seeker gets an account, just no mail.
    """
    return request.app.state.sender.send(Message(to=to, subject=subject, body=body))


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    display_name: str = Field(default="", max_length=100)
    # Honeypot, matching /api/contact and /api/post-role. A human never sees it.
    website: str = ""


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class SeekerOut(BaseModel):
    id: str
    email: str
    display_name: str
    email_verified: bool


class SaveRoleIn(BaseModel):
    source: str = Field(min_length=1, max_length=50)
    source_id: str = Field(min_length=1, max_length=200)


class MergeSavedIn(BaseModel):
    roles: list[SaveRoleIn] = Field(default_factory=list, max_length=500)


def _seeker_out(row: dict) -> SeekerOut:
    return SeekerOut(
        id=row["id"],
        email=row["email"],
        display_name=row.get("display_name") or "",
        email_verified=bool(row.get("email_verified")),
    )


@router.post("/api/auth/register", response_model=SeekerOut, status_code=201, tags=["auth"])
def register(payload: RegisterIn, request: Request, response: Response):
    """
    Create a Seeker and sign them straight in.

    Two behaviours that look like bugs and are not:

    1. A filled honeypot returns the same 201 shape a human gets. Telling a bot
       it was detected only teaches it what to change.
    2. Registering an address that already exists ALSO returns success, and mails
       the existing owner "someone tried to register" instead. Any observable
       difference here turns this endpoint into an oracle for who has an account.
       The caller is not signed in in that case, which is invisible to an
       attacker but obvious to the real owner.
    """
    email = seekers_store.normalise_email(payload.email)
    ip = _client_ip(request)

    if payload.website:
        logger.info("Honeypot triggered on /api/auth/register from %s", ip)
        return SeekerOut(id="", email=email, display_name="", email_verified=False)

    # Per-EMAIL first: the target is the constant in an inbox-bombing attempt,
    # the source IP is not.
    if _auth_rate_limited(request, f"reg:email:{email}", limit=3, window_s=3600) or \
       _auth_rate_limited(request, f"reg:ip:{ip}", limit=10, window_s=3600):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")

    store = seekers_store.get_store()
    try:
        seeker_id = store.create_seeker(
            email,
            password_hash=auth.hash_password(payload.password),
            display_name=payload.display_name.strip(),
        )
    except seekers_store.EmailAlreadyRegistered:
        store.log_event("seeker.register_existing", seeker_id=None)
        _send_seeker_mail(
            request,
            email,
            "Someone tried to register with your email",
            "Someone just tried to create a FinEx Careers account with this address.\n"
            "You already have one, so nothing changed. If this was you, sign in "
            "instead — or reset your password if you've forgotten it.\n\n"
            "If it wasn't you, you can ignore this message.",
        )
        return SeekerOut(id="", email=email, display_name="", email_verified=False)

    store.log_event("seeker.registered", seeker_id=seeker_id)
    _set_session_cookie(request, response, auth.issue_session(store, seeker_id,
                                                     user_agent=request.headers.get("user-agent")))
    raw_token = auth.issue_email_token(store, seeker_id, purpose="verify")
    _send_seeker_mail(
        request,
        email,
        "Confirm your email — FinEx Careers",
        f"Welcome to FinEx Careers.\n\nConfirm this address to finish setting up "
        f"your account:\n\n{_verify_url(request, raw_token)}\n\n"
        f"This link works once and expires in an hour.",
    )
    return _seeker_out(store.get_seeker(seeker_id))


def _verify_url(request: Request, raw_token: str) -> str:
    base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/") or str(request.base_url).rstrip("/")
    return f"{base}/verify?token={raw_token}"


@router.post("/api/auth/login", response_model=SeekerOut, tags=["auth"])
def login(payload: LoginIn, request: Request, response: Response):
    """
    Sign in. One failure message for every cause — wrong password, no such
    account, Google-only account with no password set — because distinguishing
    them is the same oracle problem as register.
    """
    email = seekers_store.normalise_email(payload.email)
    ip = _client_ip(request)
    if _auth_rate_limited(request, f"login:email:{email}", limit=10, window_s=900) or \
       _auth_rate_limited(request, f"login:ip:{ip}", limit=30, window_s=900):
        raise HTTPException(status_code=429,
                            detail="Too many attempts. Try again in a few minutes.")

    store = seekers_store.get_store()
    row = store.get_seeker_by_email(email)
    # verify_password() hashes against a dummy when the row is absent, so the
    # response time does not reveal whether the address exists.
    if not auth.verify_password(row["password_hash"] if row else None, payload.password):
        store.log_event("seeker.login_failed", seeker_id=row["id"] if row else None)
        raise HTTPException(status_code=401, detail="Email or password is incorrect")

    store.touch_last_login(row["id"])
    store.log_event("seeker.login", seeker_id=row["id"])
    _set_session_cookie(request, response, auth.issue_session(store, row["id"],
                                                     user_agent=request.headers.get("user-agent")))
    return _seeker_out(store.get_seeker(row["id"]))


@router.post("/api/auth/logout", status_code=204, tags=["auth"])
def logout(request: Request, response: Response):
    """Always 204. Logging out of a session you don't have is not an error."""
    auth.revoke_session(seekers_store.get_store(), request.cookies.get(SESSION_COOKIE))
    _clear_session_cookie(response)
    return Response(status_code=204)


@router.get("/api/auth/me", response_model=SeekerOut, tags=["auth"])
def whoami(request: Request):
    return _seeker_out(_require_seeker(request))


@router.get("/api/me/saved", response_model=list[JobSummary], tags=["saved"])
def list_saved(request: Request):
    """
    The Seeker's saved Roles, resolved against jobs.db at read time.

    seekers.db stores references only — (source, source_id) — never a copy of the
    Role. That is the fix for the bug this feature inherited: useSavedJobs.ts
    keeps whole Job objects in localStorage, so a save is a frozen snapshot and a
    role that closed months ago still displays as live.

    Resolving at read time is only half of that fix, and until this endpoint
    called job_read it was the only half present: the query carried no visibility
    predicate, so a closed Role came back looking exactly like a live one — the
    same bug, moved to the server. ADDRESSABLE returns it marked `closed`, which
    is what CONTEXT.md means by a Saved Role "showing as closed once the Role is
    gone". A reference whose row has left jobs.db entirely is dropped; there is
    nothing to render but the reference.

    `job_read.saved_roles` adds the one thing addressing itself does not decide:
    a Role that has been Closed for longer than the retention window stops being
    listed here (docs/adr/0011). It stays saved and stays readable by deep link;
    this endpoint just stops putting it in front of the Seeker.
    """
    seeker = _require_seeker(request)
    refs = seekers_store.get_store().list_saved_roles(seeker["id"])
    if not refs:
        return []

    pairs = [(r["source"], r["source_id"]) for r in refs]
    conn = get_db(request)
    try:
        # Order is the Seeker's newest-first save order, preserved by saved_roles.
        saved = job_read.saved_roles(conn, pairs)
    finally:
        conn.close()

    if len(saved) != len(pairs):
        # Two reasons a reference resolves to nothing, and they are worth telling
        # apart when reading logs: the row left jobs.db, or it is a Role that has
        # been closed past the retention window and is now hidden by design.
        logger.info(
            "Seeker %s: %d of %d Saved Role(s) not listed (row gone from jobs.db, "
            "or Closed longer than %s)",
            seeker["id"], len(pairs) - len(saved), len(pairs),
            job_read.SAVED_ROLE_RETENTION,
        )
    return saved


@router.post("/api/me/saved", status_code=204, tags=["saved"])
def save_role(payload: SaveRoleIn, request: Request):
    seeker = _require_seeker(request)
    store = seekers_store.get_store()
    store.save_role(seeker["id"], payload.source, payload.source_id)
    store.log_event("role.saved", seeker_id=seeker["id"])
    return Response(status_code=204)


@router.delete("/api/me/saved/{source}/{source_id}", status_code=204, tags=["saved"])
def unsave_role(source: str, source_id: str, request: Request):
    """204 whether or not it was saved — unsaving twice is not an error."""
    seeker = _require_seeker(request)
    seekers_store.get_store().unsave_role(seeker["id"], source, source_id)
    return Response(status_code=204)


@router.post("/api/me/saved/merge", tags=["saved"])
def merge_saved(payload: MergeSavedIn, request: Request):
    """
    Lift the browser's localStorage saves into the account on first sign-in
    (decision 14). A union, never a replace, and idempotent — so a client that
    retries, or a Seeker who signs in on a second device with its own local
    saves, keeps everything rather than losing a set.
    """
    seeker = _require_seeker(request)
    store = seekers_store.get_store()
    added = store.merge_saved_roles(seeker["id"], [(r.source, r.source_id) for r in payload.roles])
    if added:
        store.log_event("saved.migrated", seeker_id=seeker["id"])
    return {"merged": added, "submitted": len(payload.roles)}


@router.delete("/api/me", status_code=204, tags=["auth"])
def delete_account(request: Request, response: Response):
    """
    Really delete the account (ADR 0007) — rows gone, every session revoked.

    CLAUDE.md's "soft-delete only, never hard-delete" governs Roles, so that a
    Seeker can revisit a job they applied to after it closed. It does not extend
    to the Seeker's own account: flipping a flag while telling someone their data
    is gone turns an ordinary privacy question into a serious complaint.
    """
    seeker = _require_seeker(request)
    seekers_store.get_store().delete_seeker(seeker["id"])
    _clear_session_cookie(response)
    logger.info("Seeker %s deleted their account", seeker["id"])
    return Response(status_code=204)


# ── The factory ───────────────────────────────────────────────────────────────


def _mount_frontend(app: FastAPI, settings: Settings) -> None:
    """
    Serve the built React bundle from this same service (ADR 0005).

    Registered LAST, and only when a bundle exists. FastAPI matches routes in
    registration order and the catch-all matches every path — declared any
    earlier it would swallow /api/* and /health before they were ever reached.
    """
    if not settings.frontend_present():
        return

    dist = settings.frontend_dist

    # Vite emits hashed filenames under assets/ (app-a1b2c3.js), so those files are
    # immutable: a change produces a new name. Safe to cache hard. Mounting the
    # directory also means Starlette, not us, resolves the path — which is what
    # keeps `/assets/../../etc/passwd` from being a file read.
    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str):
        """
        Serve index.html for anything that is not an API path.

        The React app routes on the client: /jobs, /saved, /about, /learning and
        /post-a-role exist only in the browser's router, not on disk. A hard
        refresh (or a pasted link) asks THIS server for them, so without this
        route every one of them 404s — the classic single-page-app deploy bug.

        The /api and /health guards matter even though those routes are declared
        above and win on registration order: they win only for paths that EXIST.
        Without the guard, a typo'd or retired endpoint like /api/jobz would fall
        through to here and answer 200 with a page of HTML, so a broken frontend
        fetch would surface as a JSON parse error rather than an honest 404.
        """
        if full_path == "api" or full_path.startswith("api/") or full_path == "health":
            raise HTTPException(status_code=404, detail="Not found")

        # Real files at the root of the bundle — favicon.svg, icons.svg, and
        # anything later dropped into frontend/public/ — are served as themselves.
        # resolve() + is_relative_to() rejects any ../ that escapes the bundle.
        if full_path:
            candidate = (dist / full_path).resolve()
            if candidate.is_relative_to(dist) and candidate.is_file():
                return FileResponse(candidate)

        # index.html is the one file that must NOT be cached: it is what points at
        # the current hashed bundle, so a stale copy pins a returning visitor to a
        # deleted JS file and the app boots to a blank page.
        return FileResponse(settings.index_html, headers={"Cache-Control": "no-cache"})


def create_app(settings: Settings | None = None, *, sender: Sender | None = None) -> FastAPI:
    """
    Build an app from an explicit configuration.

    This is the seam the module used to lack. Everything that varies between a
    production process, a local dev process and a test now varies HERE, as an
    argument — rather than being read from the environment while the module was
    being imported, which made `sys.modules.pop("main")` the only way to
    reconfigure anything.
    """
    settings = settings or Settings.from_env()
    # SmtpSender by default; a test passes a RecordingSender and asserts on it.
    sender = sender if sender is not None else SmtpSender()

    app = FastAPI(
        title="FinEx Careers API",
        description="Read-only API for Hong Kong financial job listings.",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.sender = sender
    # Per-app, so two apps in one process (which is what the tests build) cannot
    # share a rate-limit budget.
    app.state.limiter = RateLimiter()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        # POST is required by /api/contact and /api/post-role — without it the
        # browser blocks the preflight and the forms fail before reaching FastAPI.
        # DELETE joins the list for the account endpoints (unsave a Role, delete an
        # account). At one origin CORS is inert, but a dev frontend pointed at an
        # absolute API URL still preflights, and a missing method fails there only.
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["*"],
    )

    app.include_router(router)
    _mount_frontend(app, settings)
    return app


# The process-wide app, for `uvicorn main:app` (Procfile, railway.json). One
# ordinary caller of the factory, not a special case.
app = create_app()
