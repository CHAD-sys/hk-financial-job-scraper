"""
FinEx Careers — FastAPI backend

Read access to jobs.db (SQLite), plus a public recruiter Role-submission endpoint
that persists to an append-only JSONL queue and emails a notification. Nothing
submitted through it is published without human review.
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import re
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional
from urllib.parse import quote_plus, urlparse

from fastapi import (
    APIRouter,
    FastAPI,
    File,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse, Response
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
from mailer import SUBMISSION_RECIPIENT, SMTP_USER  # noqa: E402

# The jobs read path. Everything about which Roles are visible, how they are
# filtered, sorted, counted and shaped for the wire lives in this module — see
# its docstring for why "browsing is filtered, addressing is not".
import alert_unsubscribe  # noqa: E402
import alerts  # noqa: E402
import disk_alerts  # noqa: E402
import job_read  # noqa: E402
import learning_content  # noqa: E402
import resume_intelligence  # noqa: E402
import role_access  # noqa: E402
import role_feed  # noqa: E402
from rate_limit import RateLimiter, RedisRateLimiter  # noqa: E402
from sender import (  # noqa: E402
    Message,
    Sender,
    SmtpSender,
    SmtpSubmissionNotifier,
    SubmissionNotifier,
)
from settings import Settings  # noqa: E402
from hk_jobs.migrations import migrate  # noqa: E402
from hk_jobs.sources import SOURCE_NAMES  # noqa: E402
from job_read import (  # noqa: E402
    BOARD_WHERE,
    INTERNSHIP_COND,
    MEMBER_ONLY_TIERS,
    SECTOR_SQL,
    CatalogueAudience,
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


def _grant_role_access(request: Request, jobs) -> None:
    """Attach detail grants only to Roles an allowed read path selected."""
    access = request.app.state.role_access
    for job in jobs:
        job.access_token = access.issue(job.source, job.source_id)


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


def get_write_db(request: Request) -> sqlite3.Connection:
    """
    A WRITABLE connection to jobs.db — the one exception to "read access to
    jobs.db" in this module's own docstring, alongside submissions.py's INSERT
    on approval. Used only by admin.py's job_edit routes, gated by
    `_require_super_admin`: nowhere else in this API writes to jobs.db through
    a connection this file hands out.
    """
    conn = sqlite3.connect(cfg(request).jobs_db, check_same_thread=False)
    job_read.prepare(conn)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# ── Pydantic models ────────────────────────────────────────────────────────────

class NameCount(BaseModel):
    name: str
    count: int


class StatsResponse(BaseModel):
    total_active_jobs: int
    employer_count: int
    by_sector: dict[str, int]
    by_seniority: dict[str, int]
    by_remote_type: dict[str, int]
    by_source_tier: dict[str, int]
    top_skills: list[NameCount]
    top_companies: list[NameCount]
    internship_count: int


# ── App ────────────────────────────────────────────────────────────────────────


_SESSION_PURGE_INTERVAL_S = 24 * 60 * 60  # once a day is plenty for housekeeping


def _purge_expired_sessions() -> None:
    """
    Delete session rows past their expiry, in both account stores.

    Both stores' `purge_expired_sessions()` were written with this exact use in
    mind ("safe to call on startup or from a periodic task") but had no caller
    anywhere in the codebase — expired rows were only ever removed one at a
    time, on the read that happened to land on them (`auth.verify_session`).
    Correct, but the table only ever grows. Imported locally so this file's
    carefully-ordered top-of-module imports (see the comments above them) never
    have to account for it.
    """
    import employers_store
    import seekers_store

    seeker_n = seekers_store.get_store().purge_expired_sessions()
    employer_n = employers_store.get_store().purge_expired_sessions()
    if seeker_n or employer_n:
        logger.info(
            "Purged expired sessions: %d seeker(s), %d employer(s)", seeker_n, employer_n
        )


async def _purge_expired_sessions_periodically() -> None:
    """Repeat the startup purge for a process that stays up longer than a day."""
    while True:
        await asyncio.sleep(_SESSION_PURGE_INTERVAL_S)
        try:
            _purge_expired_sessions()
        except Exception:
            logger.exception("Periodic session purge failed")


_DISK_ALERT_INTERVAL_S = 24 * 60 * 60  # once a day — see disk_alerts.py


def _check_disk_capacity(settings: Settings) -> None:
    """
    Email SUBMISSION_RECIPIENT if the Railway volume is at or above
    settings.disk_alert_threshold_pct. Checked against settings.jobs_db.parent,
    the mounted volume every Railway-resident file (jobs.db, seekers.db,
    employers.db, pipeline backups) shares — so this one reading stands in for
    all of them. Gated on settings.disk_alerts_enabled, OFF by default.
    """
    if not settings.disk_alerts_enabled:
        return
    usage = disk_alerts.maybe_send_capacity_alert(
        settings.jobs_db.parent,
        threshold_pct=settings.disk_alert_threshold_pct,
        send=mailer.send_mail,
    )
    logger.info(
        "Disk capacity check: %.1f%% used at %s", usage.percent_used, settings.jobs_db.parent
    )


async def _check_disk_capacity_periodically(settings: Settings) -> None:
    """
    Check once at startup, then every 24h — deliberately the opposite order
    from _purge_expired_sessions_periodically (which sleeps first, since the
    startup purge already ran separately). There is no separate startup call
    for the disk check, so checking first means a volume already over
    threshold at boot is reported the same day, not a day later.
    """
    while True:
        try:
            _check_disk_capacity(settings)
        except Exception:
            logger.exception("Periodic disk capacity check failed")
        await asyncio.sleep(_DISK_ALERT_INTERVAL_S)


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
    if settings.jobs_db.exists():
        migrate(str(settings.jobs_db))
    _purge_expired_sessions()
    purge_task = asyncio.create_task(_purge_expired_sessions_periodically())
    disk_alert_task = asyncio.create_task(_check_disk_capacity_periodically(settings))

    if SMTP_USER:
        logger.info("Email configured — Role submissions will be sent to %s", SUBMISSION_RECIPIENT)
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
    try:
        yield
    finally:
        purge_task.cancel()
        disk_alert_task.cancel()
        try:
            await purge_task
        except asyncio.CancelledError:
            pass
        try:
            await disk_alert_task
        except asyncio.CancelledError:
            pass


# ── /api/jobs ─────────────────────────────────────────────────────────────────

@router.get("/api/jobs", response_model=JobListResponse, tags=["jobs"])
def list_jobs(
    request: Request,
    search: Optional[str] = Query(
        None,
        max_length=200,
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
    research_query = (search or "").strip()
    if len(research_query) < 2:
        raise HTTPException(
            status_code=422,
            detail="Start with a specific search of at least two characters.",
        )

    filters = JobFilters.of(
        search=research_query, sectors=sectors, companies=companies, seniority=seniority,
        remote_type=remote_type, skills=skills, salary_min=salary_min,
        salary_max=salary_max, exp_min=exp_min, exp_max=exp_max,
        posted_within_days=posted_within_days, is_internship=is_internship,
        tier=tier, is_new=is_new, urgently_hiring=urgently_hiring,
        max_applicants=max_applicants, hidden_only=hidden_only,
        verified_only=verified_only,
    )
    audience = (
        CatalogueAudience.MEMBER
        if _current_seeker(request) is not None
        else CatalogueAudience.PUBLIC
    )
    with get_db(request) as conn:
        result = job_read.list_jobs(
            conn, filters, sort=sort, page=page, page_size=page_size,
            visibility=Visibility.BOARD, audience=audience,
            # Recruiter Posts get quick, steady visibility on the board itself,
            # whatever sort or filters are active — see job_read's boost docstring.
            boost_recruiter_posts=True,
        )
    _grant_role_access(request, result.jobs)
    return result


# ── /api/recommendations + discovery signals ─────────────────────────────────


class DiscoveryFiltersIn(BaseModel):
    """The user-controlled filters worth retaining as recommendation intent."""

    tier: str = Field(default="all", max_length=20)
    sectors: list[str] = Field(default_factory=list, max_length=20)
    companies: list[str] = Field(default_factory=list, max_length=20)
    seniority: list[str] = Field(default_factory=list, max_length=20)
    remote_type: list[str] = Field(default_factory=list, max_length=20)
    skills: list[str] = Field(default_factory=list, max_length=20)
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    salary_disclosed_only: bool = False
    exp_min: Optional[int] = None
    exp_max: Optional[int] = None
    is_internship: Optional[bool] = None
    is_new: bool = False
    urgently_hiring: bool = False
    max_applicants: Optional[int] = None
    hidden_only: bool = False
    verified_only: bool = False


class DiscoveryIn(BaseModel):
    search_query: str = Field(default="", max_length=200)
    filters: DiscoveryFiltersIn = Field(default_factory=DiscoveryFiltersIn)
    result_count: int = Field(ge=0, le=1_000_000)


class RecommendationFeedbackIn(BaseModel):
    action: Literal["more_like", "not_interested"]
    detail: Optional[str] = Field(default=None, max_length=300)


class ResumeAnalysisOut(BaseModel):
    skills: list[str] = Field(default_factory=list)
    role_families: list[str] = Field(default_factory=list)
    sectors: list[str] = Field(default_factory=list)
    years_experience: Optional[int] = None
    seniority: Optional[str] = None


class ResumeOut(BaseModel):
    filename: str
    media_type: str
    size_bytes: int
    uploaded_at: str
    analysis: ResumeAnalysisOut


def _resume_out(row: dict) -> ResumeOut:
    return ResumeOut(
        filename=row["filename"],
        media_type=row["media_type"],
        size_bytes=row["size_bytes"],
        uploaded_at=row["uploaded_at"],
        analysis=ResumeAnalysisOut(**(row.get("analysis") or {})),
    )


@router.post("/api/me/discovery", status_code=204, tags=["recommendations"])
def record_discovery(payload: DiscoveryIn, request: Request):
    """Persist one settled search/filter state for the signed-in Seeker."""
    seeker = _require_seeker(request)
    store = seekers_store.get_store()
    filters = payload.filters.model_dump(exclude_defaults=True, exclude_none=True)
    research_query = payload.search_query.strip()
    if not research_query and not filters:
        return Response(status_code=204)
    if len(research_query) < 2:
        raise HTTPException(
            status_code=422,
            detail="Filters can only be saved inside a specific Role search.",
        )
    store.record_discovery(
        seeker["id"],
        search_query=research_query,
        filters=filters,
        result_count=payload.result_count,
    )
    return Response(status_code=204)


@router.get(
    "/api/recommendations",
    response_model=role_feed.RoleFeed,
    tags=["recommendations"],
)
def recommended_roles(
    request: Request,
    page: int = Query(1, ge=1, le=10),
    page_size: int = Query(6, ge=1, le=24),
):
    """Return Roles justified by one signed-in Seeker's first-party evidence."""
    seeker = _require_seeker(request)
    with get_db(request) as conn:
        feed = role_feed.roles_for_seeker(
            conn,
            seeker_id=seeker["id"],
            page=page,
            page_size=page_size,
        )
    _grant_role_access(request, (item.job for item in feed.items))
    return feed


@router.post(
    "/api/me/recommendations/{source}/{source_id}/click",
    status_code=204,
    tags=["recommendations"],
)
def recommendation_clicked(
    source: str,
    source_id: str,
    request: Request,
    access_token: Optional[str] = Header(None, alias="X-Role-Access", max_length=2_048),
):
    """Attribute a card-open to the newest matching recommendation impression."""
    seeker = _require_seeker(request)
    if not request.app.state.role_access.allows(access_token, source, source_id):
        raise HTTPException(status_code=404, detail="Job not found")
    seekers_store.get_store().mark_recommendation_clicked(
        seeker["id"], source, source_id
    )
    return Response(status_code=204)


@router.post(
    "/api/me/recommendations/{source}/{source_id}/feedback",
    status_code=204,
    tags=["recommendations"],
)
def add_recommendation_feedback(
    source: str,
    source_id: str,
    payload: RecommendationFeedbackIn,
    request: Request,
    access_token: Optional[str] = Header(None, alias="X-Role-Access", max_length=2_048),
):
    seeker = _require_seeker(request)
    if not request.app.state.role_access.allows(access_token, source, source_id):
        raise HTTPException(status_code=404, detail="Job not found")
    seekers_store.get_store().record_recommendation_feedback(
        seeker["id"],
        source,
        source_id,
        action=payload.action,
        detail=payload.detail,
    )
    return Response(status_code=204)


@router.delete(
    "/api/me/recommendations/{source}/{source_id}/feedback/{action}",
    status_code=204,
    tags=["recommendations"],
)
def remove_recommendation_feedback(
    source: str,
    source_id: str,
    action: Literal["more_like", "not_interested"],
    request: Request,
):
    seeker = _require_seeker(request)
    seekers_store.get_store().delete_recommendation_feedback(
        seeker["id"], source, source_id, action
    )
    return Response(status_code=204)


@router.get("/api/me/resume", response_model=Optional[ResumeOut], tags=["resume"])
def get_resume_status(request: Request):
    """Return private resume metadata and derived evidence, never the document text."""
    seeker = _require_seeker(request)
    row = seekers_store.get_store().get_resume(seeker["id"])
    return _resume_out(row) if row else None


@router.put("/api/me/resume", response_model=ResumeOut, tags=["resume"])
async def upload_resume(request: Request, resume: UploadFile = File(...)):
    """Validate and analyse a replacement fully before atomically storing it."""
    seeker = _require_seeker(request)
    if _auth_rate_limited(
        request, f"resume:{seeker['id']}", limit=10, window_s=3_600
    ):
        raise HTTPException(
            status_code=429,
            detail="Too many resume uploads. Please try again later.",
        )

    try:
        data = await resume.read(resume_intelligence.MAX_RESUME_BYTES + 1)
        parsed = resume_intelligence.parse_resume(
            resume.filename or "", resume.content_type, data
        )
        analysis = resume_intelligence.analyse_resume(parsed)
    except resume_intelligence.ResumeValidationError as exc:
        status = 413 if len(data) > resume_intelligence.MAX_RESUME_BYTES else 422
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    finally:
        await resume.close()

    store = seekers_store.get_store()
    replaced = store.replace_resume(
        seeker["id"],
        filename=parsed.filename,
        media_type=parsed.media_type,
        size_bytes=parsed.size_bytes,
        content_sha256=parsed.content_sha256,
        file_content=data,
        text_content=parsed.text,
        analysis=analysis.as_dict(),
    )
    store.log_event("resume.replaced" if replaced else "resume.uploaded", seeker["id"])
    return _resume_out(store.get_resume(seeker["id"]))


@router.delete("/api/me/resume", status_code=204, tags=["resume"])
def delete_resume(request: Request):
    """Delete the source document, extracted text and derived evidence together."""
    seeker = _require_seeker(request)
    store = seekers_store.get_store()
    if store.delete_resume(seeker["id"]):
        store.log_event("resume.deleted", seeker["id"])
    return Response(status_code=204)


class AlertSettingsOut(BaseModel):
    opted_in: bool


class AlertSettingsIn(BaseModel):
    opted_in: bool


@router.get("/api/me/alerts", response_model=AlertSettingsOut, tags=["alerts"])
def get_alert_settings(request: Request):
    """Whether the signed-in Seeker has opted into the weekly Alert email."""
    seeker = _require_seeker(request)
    opted_in = seekers_store.get_store().get_alert_opt_in(seeker["id"])
    return AlertSettingsOut(opted_in=opted_in)


@router.put("/api/me/alerts", response_model=AlertSettingsOut, tags=["alerts"])
def set_alert_settings(payload: AlertSettingsIn, request: Request):
    """
    Turn the weekly Alert email on or off.

    Opt-in only (alerts.py's module docstring): nobody is enrolled by default,
    so this endpoint is the ONLY way `alert_settings.opted_in` becomes true.
    The unsubscribe link inside an Alert email (POST /api/alerts/unsubscribe,
    below) can only turn it back off, never on — matching PrivacyNotice.tsx
    clause 5's promise that consent for anything mailing-list-shaped is asked
    for, never assumed.
    """
    seeker = _require_seeker(request)
    store = seekers_store.get_store()
    opted_in = store.set_alert_opt_in(seeker["id"], payload.opted_in)
    store.log_event("alerts.opted_in" if opted_in else "alerts.opted_out", seeker["id"])
    return AlertSettingsOut(opted_in=opted_in)


@router.get(
    "/api/me/resume-matches",
    response_model=role_feed.ResumeMatches,
    tags=["resume"],
)
def resume_matches(
    request: Request,
    limit: int = Query(6, ge=1, le=12),
):
    """Return current Roles with the strongest observable resume alignment."""
    seeker = _require_seeker(request)
    with get_db(request) as conn:
        matches = role_feed.resume_matches_for_seeker(
            conn,
            seeker_id=seeker["id"],
            limit=limit,
        )
    _grant_role_access(request, (item.job for item in matches.items))
    return matches


# ── /api/jobs/{source}/{source_id} ────────────────────────────────────────────

@router.get("/api/jobs/{source}/{source_id}", response_model=JobDetail, tags=["jobs"])
def get_job(
    source: str,
    source_id: str,
    request: Request,
    access_token: Optional[str] = Header(None, alias="X-Role-Access", max_length=2_048),
):
    """
    One Role, addressed by reference.

    Visibility is ADDRESSABLE: a URL naming a specific (source, source_id) gets
    that row whatever state it is in, and `closed` says which. Requiring
    is_primary here would 404 a link whose copy stopped being primary at the last
    reconciliation; requiring is_active would break every Saved Role the moment
    the vacancy closed, which is precisely when a Seeker wants to look at it.
    """
    seeker = _current_seeker(request)
    is_admin = bool(seeker and seeker.get("is_admin"))
    if not is_admin and not request.app.state.role_access.allows(
        access_token, source, source_id
    ):
        # 404 reveals neither whether the reference exists nor why access was
        # denied. Knowing a jobs.db key is not a discovery path.
        raise HTTPException(status_code=404, detail="Job not found")

    with get_db(request) as conn:
        detail = job_read.get_job(conn, source, source_id, visibility=Visibility.ADDRESSABLE)
    if detail is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if detail.source_tier in MEMBER_ONLY_TIERS and seeker is None:
        # A grant issued while signed in must not remain a way to read a
        # members-only Role after signing out.
        raise HTTPException(status_code=404, detail="Job not found")
    return detail


# ── Public SEO surface (robots.txt, sitemap.xml, job teaser pages) ────────────
#
# Everything above answers only with a session or a short-lived Role-access
# grant (ADR 0018). This block is the one deliberate exception: a permanent,
# ungated, crawlable URL per Role so search engines can index FinEx Careers
# job-by-job. It hands out title, company, location, salary and a short AI
# summary — never `description_clean`, never an apply link. Full detail still
# requires signing in; these pages exist to fill that wall with search
# traffic, not to remove it. Declared on `router`, which is included before
# `_mount_frontend`'s catch-all (see that function's docstring) so these win
# over the SPA fallback.

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(text: str) -> str:
    return _SLUG_RE.sub("-", (text or "").lower()).strip("-")


def _job_slug(title: str, company: str) -> str:
    return _slugify(f"{title} {company}")[:80].strip("-") or "role"


def _job_teaser_path(source: str, source_id: str, title: str, company: str) -> str:
    return f"/jobs/{source}/{source_id}/{_job_slug(title, company)}"


def _job_posting_jsonld(detail: JobDetail, canonical_url: str) -> dict:
    location = detail.locations[0] if detail.locations else "Hong Kong"
    summary = detail.description_summary or f"{detail.title} at {detail.company}."
    posting: dict = {
        "@context": "https://schema.org/",
        "@type": "JobPosting",
        "title": detail.title,
        "description": f"<p>{html.escape(summary)}</p>",
        "hiringOrganization": {"@type": "Organization", "name": detail.company},
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressLocality": location,
                "addressCountry": "HK",
            },
        },
        "url": canonical_url,
        # Which record this is, so Google can tell two postings of the same
        # vacancy apart and re-identify this one across re-crawls.
        "identifier": {
            "@type": "PropertyValue",
            "name": detail.source,
            "value": detail.source_id,
        },
        # Applying always leaves this page — sign in, then the employer's own
        # form. Google added this flag precisely so a board cannot imply
        # one-click apply it does not have.
        "directApply": False,
    }
    if detail.posted_at:
        posting["datePosted"] = detail.posted_at[:10]
    # NO validThrough. Google recommends it, but we do not know when a vacancy
    # closes — every source here publishes an opening date and nothing else.
    # Inventing an expiry would either drop a live Role out of Google early or
    # assert a date no employer gave us. Closed Roles go noindex instead (see
    # `robots_directive`), which is the honest lever we actually have.
    if detail.is_internship:
        # The one employment type any source states plainly enough to repeat.
        posting["employmentType"] = "INTERN"
    if detail.remote_type == "remote":
        posting["jobLocationType"] = "TELECOMMUTE"
    if detail.years_experience_required:
        posting["experienceRequirements"] = {
            "@type": "OccupationalExperienceRequirements",
            "monthsOfExperience": detail.years_experience_required * 12,
        }
    if detail.job_category:
        posting["occupationalCategory"] = detail.job_category
    # Only the DISCLOSED figure goes into structured data — Google's guidelines
    # treat baseSalary as a claim about the actual posting, so the AI *estimate*
    # (shown to a human reader below, clearly labelled) has no place here.
    if detail.salary_hkd_min or detail.salary_hkd_max:
        value: dict = {"@type": "QuantitativeValue"}
        if detail.salary_hkd_min:
            value["minValue"] = detail.salary_hkd_min
        if detail.salary_hkd_max:
            value["maxValue"] = detail.salary_hkd_max
        value["unitText"] = "MONTH" if detail.salary_period == "month" else "YEAR"
        posting["baseSalary"] = {"@type": "MonetaryAmount", "currency": "HKD", "value": value}
    return posting


def _salary_line(detail: JobDetail) -> str:
    lo, hi = detail.salary_hkd_min, detail.salary_hkd_max
    estimated = False
    if not (lo or hi):
        lo, hi = detail.salary_estimated_min, detail.salary_estimated_max
        estimated = True
    if not (lo or hi):
        return ""
    period = "mo" if (detail.salary_period or "month") == "month" else "yr"
    amount = f"HK${lo:,}–{hi:,}/{period}" if lo and hi else f"HK${lo or hi:,}/{period}"
    return f"{amount} (AI-estimated)" if estimated else amount


def _job_teaser_html(detail: JobDetail, canonical_url: str) -> str:
    location = ", ".join(detail.locations) or "Hong Kong"
    title = html.escape(detail.title)
    company = html.escape(detail.company)
    meta_desc = html.escape(
        (detail.description_summary or f"{detail.title} at {detail.company}, Hong Kong.")[:300]
    )
    salary = html.escape(_salary_line(detail))
    skills = "".join(
        f'<span class="pill">{html.escape(s)}</span>' for s in detail.required_skills[:8]
    )
    robots_directive = "noindex,follow" if detail.closed else "index,follow"
    jsonld_block = ""
    if not detail.closed:
        jsonld_block = (
            '<script type="application/ld+json">'
            + json.dumps(_job_posting_jsonld(detail, canonical_url))
            + "</script>"
        )
    status_banner = (
        '<p class="closed-banner">This role has closed. '
        '<a href="/jobs">Search current openings</a>.</p>'
        if detail.closed
        else ""
    )
    facts = " &middot; ".join(
        html.escape(p) for p in [detail.seniority, location, detail.job_category] if p
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>{title} at {company} — FinEx Careers</title>
<meta name="description" content="{meta_desc}" />
<meta name="robots" content="{robots_directive}" />
<link rel="canonical" href="{canonical_url}" />
<link rel="icon" type="image/svg+xml" href="/favicon.svg" />
<meta property="og:type" content="website" />
<meta property="og:site_name" content="FinEx Careers" />
<meta property="og:title" content="{title} at {company}" />
<meta property="og:description" content="{meta_desc}" />
<meta property="og:url" content="{canonical_url}" />
<meta name="twitter:card" content="summary" />
{jsonld_block}
<style>
  :root {{ color-scheme: light; }}
  body {{
    margin: 0; background: #FFFDF9; color: #0B1628;
    font: 16px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, sans-serif;
  }}
  header {{ background: #0B1628; padding: 20px 24px; }}
  header a {{ color: #FBF0D3; text-decoration: none; font-weight: 600; letter-spacing: .02em; }}
  main {{ max-width: 640px; margin: 0 auto; padding: 40px 24px 64px; }}
  h1 {{ font: 700 28px/1.3 Georgia, "Playfair Display", serif; margin: 0 0 6px; }}
  .company {{ font-size: 18px; color: #475569; margin: 0 0 14px; }}
  .facts {{ color: #475569; margin: 0 0 18px; }}
  .salary {{
    display: inline-block; background: #FBF0D3; color: #9A6F00; font-weight: 600;
    padding: 6px 14px; border-radius: 999px; margin: 0 0 22px;
  }}
  .pill {{
    display: inline-block; border: 1px solid #E2E8F0; border-radius: 999px;
    padding: 4px 12px; margin: 0 8px 8px 0; font-size: 13px; color: #475569;
  }}
  .summary {{ margin: 22px 0; }}
  .closed-banner {{ background: #F1EFEA; color: #334155; padding: 12px 16px; border-radius: 8px; }}
  .cta {{
    display: inline-block; background: #1E3A8A; color: #F8FAFC; text-decoration: none;
    font-weight: 600; padding: 12px 24px; border-radius: 8px; margin-top: 12px;
  }}
  .secondary {{ margin-top: 16px; }}
  .secondary a {{ color: #1E3A8A; }}
</style>
</head>
<body>
<header><a href="/">FinEx Careers</a></header>
<main>
  <h1>{title}</h1>
  <p class="company">{company}</p>
  {f'<p class="facts">{facts}</p>' if facts else ""}
  {f'<p class="salary">{salary}</p>' if salary else ""}
  {status_banner}
  {f'<p class="summary">{html.escape(detail.description_summary)}</p>' if detail.description_summary else ""}
  <div>{skills}</div>
  <div>
    <a class="cta" href="/get-started">Sign in to see the full description &amp; apply</a>
  </div>
  <p class="secondary"><a href="/jobs">Search more roles on FinEx Careers</a></p>
</main>
</body>
</html>"""


# ── Crawlable identity for the app's own routes ───────────────────────────────
#
# Everything above this point that a crawler can read is a Role teaser. The app's
# OWN pages — "/", "/about", "/jobs", "/learning", "/get-started", "/post-a-role"
# — are React routes, and index.html deliberately carries no title or description
# (see its own comment: four page components set theirs via React 19 head
# hoisting, and a static tag would sit in the DOM alongside the page's own).
#
# That was fine for browsers and wrong for everything else. A client with no
# JavaScript got `<div id="root"></div>` and nothing else, which cost us twice:
#
#   1. Search. The five static URLs in sitemap.xml are the brand pages, and they
#      were the thinnest pages on the site. Google renders JS on a delay and not
#      always; Bing, DuckDuckGo, Yandex and Baidu largely do not render it at all.
#   2. Reputation. LinkedIn, Slack and X unfurlers do not run JS either. They
#      fetched a sign-in link and got an empty document. A page that answers a bot
#      with nothing and a human with a login form is the cloaking signature that
#      phishing kits use — and LinkedIn was showing a warning on our sign-in link
#      while that was true of every route here.
#
# So the server now writes each route's identity into the HTML before sending it.
# React still sets the same tags once it boots; the injected ones carry `data-ssr`
# so the app can drop them on mount and leave exactly one of each in the DOM
# rather than two competing titles.

_OG_IMAGE_PATH = "/og-image.png"

#: Indexable routes → (title, meta description). Keep in step with
#: `sitemap()`'s `static_paths` — tests/test_seo_shell.py pins that every one of
#: them answers with a distinct title and a description.
_ROUTE_META: dict[str, tuple[str, str]] = {
    "/": (
        "FinEx Careers — HK Finance Roles, Consultation & Learning",
        "Hong Kong finance careers in one place: a daily, AI-enriched index of open "
        "roles across 230+ employers, plus consultation and professional learning.",
    ),
    "/about": (
        "About FinEx Careers — How We Source Hong Kong Finance Roles",
        "How FinEx Careers builds its daily Hong Kong finance job index: direct ATS "
        "feeds, major boards, boutique careers pages and recruiter posts.",
    ),
    "/jobs": (
        "Search Hong Kong Finance Jobs — FinEx Careers",
        "Search open finance roles across Hong Kong — banking, asset management, "
        "insurance and professional services — indexed daily from employers and "
        "boards.",
    ),
    "/learning": (
        "Learning & Events for HK Finance — FinEx Careers",
        "Professional learning from the Financial Executive Club: training strands, "
        "a video library and upcoming events for Hong Kong finance professionals.",
    ),
    "/get-started": (
        "Create Your Free FinEx Careers Account",
        "Create a free FinEx Careers account to see full role descriptions, save "
        "positions, upload a CV for matching, and get a weekly digest of new roles.",
    ),
    "/post-a-role": (
        "Post a Finance Role in Hong Kong | FinEx Careers",
        "Reach Hong Kong finance professionals directly. Submit an open role to the "
        "FinEx Careers board, reviewed before it is published.",
    ),
}

#: Routes that must render but must never be indexed — anything behind or leading
#: into an account. A sign-in page in the index is a reputation liability, not a
#: traffic source: it is the page a phishing classifier looks hardest at.
_NOINDEX_PREFIXES = (
    "/account", "/saved", "/signin", "/register", "/forgot-password",
    "/reset-password", "/verify", "/admin", "/employer", "/choose-view",
)


#: The discipline tiles on the board's discover screen. Each one is a real,
#: crawlable landing page — "/jobs?q=Risk+Management" answers with ~2,000 roles
#: for a visitor with no session, where bare "/jobs" answers with none.
#:
#: That difference is why this list exists here as well as in the frontend.
#: ADR 0018 means the catalogue is not enumerable without a query, so "/jobs"
#: shows a crawler a page promising jobs and delivering none — Google called it
#: a Soft 404 on 2026-08-18, correctly. The query URLs are the ADR-compliant way
#: to give search engines real pages: every one carries a query, so nothing about
#: the "no enumerable catalogue" rule bends to make them work.
#:
#: Kept in step with MAJOR_CATEGORIES in webapp/frontend/src/components/
#: SearchHero.tsx by tests/test_route_meta_in_step.py.
BOARD_CATEGORIES = (
    "Risk Management",
    "Accounting & Finance",
    "Treasury",
    "Investment",
    "Operations",
    "Technology & Transformation",
    "Sales and Business Development",
    "Private Banking",
    "Commercial Banking",
    "Investment Banking",
    "Retail Banking",
    "Sales & Marketing",
    "Legal, Compliance & Audit",
)

#: The board reads its query from `?q=` (see searchParamsToFilters in
#: webapp/frontend/src/api/client.ts). Named here so the sitemap, the canonical
#: and the frontend's links cannot drift to three different spellings.
BOARD_QUERY_PARAM = "q"


def _category_path(label: str) -> str:
    return f"/jobs?{BOARD_QUERY_PARAM}={quote_plus(label)}"


def _category_meta(label: str) -> tuple[str, str]:
    """Title and description for one discipline landing page."""
    long_form = f"{label} Jobs in Hong Kong — FinEx Careers"
    title = long_form if len(long_form) <= 60 else f"{label} Jobs — FinEx Careers"
    description = (
        f"Open {label.lower()} roles across Hong Kong's banks, funds and boutiques. "
        "Indexed daily from employer sites and major boards, with an AI salary "
        "estimate on every listing."
    )
    return title, description


def _organisation_jsonld(base: str) -> list[dict]:
    """
    Who this site belongs to, in the vocabulary Google uses to build an entity.

    A young domain running an OAuth sign-in and no stated owner is, to a
    classifier, shaped exactly like a phishing site. `sameAs` is the part that
    matters most here: it ties finexcareers.com to the Financial Executive Club's
    established web presence, so the two are understood as one real organisation.
    """
    return [
        {
            "@context": "https://schema.org",
            "@type": "Organization",
            "name": "FinEx Careers",
            "legalName": "Financial Executive Club",
            "url": base,
            "logo": f"{base}{_OG_IMAGE_PATH}",
            "description": (
                "A daily, AI-enriched index of open finance roles in Hong Kong, "
                "published by the Financial Executive Club."
            ),
            "areaServed": {"@type": "Place", "name": "Hong Kong"},
            "sameAs": [
                "https://www.finexclub.org",
                "https://www.linkedin.com/company/financial-executive-club",
            ],
        },
        {
            "@context": "https://schema.org",
            "@type": "WebSite",
            "name": "FinEx Careers",
            "url": base,
            "potentialAction": {
                "@type": "SearchAction",
                "target": {
                    "@type": "EntryPoint",
                    "urlTemplate": f"{base}/jobs?search={{search_term_string}}",
                },
                "query-input": "required name=search_term_string",
            },
        },
    ]


def _shell_head_tags(request: Request, path: str) -> str:
    """The head a non-JS client gets for one app route. Empty string if unknown."""
    normalised = "/" + path.strip("/") if path.strip("/") else "/"

    # "/jobs?q=..." is its own page, not a variant of "/jobs". A known discipline
    # gets real metadata and a canonical carrying the query; ANY OTHER query is
    # noindex, because a board with free-text search otherwise offers a crawler
    # an infinite space of near-identical URLs to burn its crawl budget on.
    if normalised == "/jobs":
        query = (request.query_params.get(BOARD_QUERY_PARAM) or "").strip()
        if query:
            match = next(
                (c for c in BOARD_CATEGORIES if c.casefold() == query.casefold()), None
            )
            if match is None:
                return (
                    f"<title data-ssr>{html.escape(query)} — FinEx Careers</title>"
                    '<meta data-ssr name="robots" content="noindex,follow" />'
                )
            return _indexable_head(
                request, _category_path(match), *_category_meta(match)
            )

    meta = _ROUTE_META.get(normalised)
    noindex = normalised.startswith(_NOINDEX_PREFIXES)
    if meta is None and not noindex:
        # An unrecognised client-side route. React Router owns it and decides what
        # it is; guessing a title here would be worse than sending none.
        return ""

    if meta is None:
        title = "Sign in — FinEx Careers"
        description = "Sign in to FinEx Careers."
    else:
        title, description = meta

    if noindex:
        return (
            f"<title data-ssr>{html.escape(title)}</title>"
            f'<meta data-ssr name="description" content="{html.escape(description)}" />'
            '<meta data-ssr name="robots" content="noindex,follow" />'
        )

    return _indexable_head(request, normalised, title, description)


def _indexable_head(
    request: Request, path: str, title: str, description: str
) -> str:
    """The full head for one indexable page: identity, canonical, share card."""
    base = _public_base(request)
    canonical = f"{base}{path}" if path != "/" else f"{base}/"
    image = f"{base}{_OG_IMAGE_PATH}"
    tags = [
        f"<title data-ssr>{html.escape(title)}</title>",
        f'<meta data-ssr name="description" content="{html.escape(description)}" />',
        '<meta data-ssr name="robots" content="index,follow" />',
        f'<link data-ssr rel="canonical" href="{html.escape(canonical)}" />',
        '<meta data-ssr property="og:type" content="website" />',
        '<meta data-ssr property="og:site_name" content="FinEx Careers" />',
        '<meta data-ssr property="og:locale" content="en_HK" />',
        f'<meta data-ssr property="og:title" content="{html.escape(title)}" />',
        f'<meta data-ssr property="og:description" content="{html.escape(description)}" />',
        f'<meta data-ssr property="og:url" content="{html.escape(canonical)}" />',
        f'<meta data-ssr property="og:image" content="{html.escape(image)}" />',
        '<meta data-ssr property="og:image:width" content="1200" />',
        '<meta data-ssr property="og:image:height" content="630" />',
        '<meta data-ssr name="twitter:card" content="summary_large_image" />',
        f'<meta data-ssr name="twitter:title" content="{html.escape(title)}" />',
        f'<meta data-ssr name="twitter:description" content="{html.escape(description)}" />',
        f'<meta data-ssr name="twitter:image" content="{html.escape(image)}" />',
    ]
    if path == "/":
        for block in _organisation_jsonld(base):
            tags.append(
                '<script data-ssr type="application/ld+json">'
                + json.dumps(block)
                + "</script>"
            )
    return "".join(tags)


def _inject_head(document: str, tags: str) -> str:
    """
    Put `tags` at the top of the document's head.

    Top, not bottom: where a tag React also renders ends up duplicated for the
    moment before the app boots and removes the `data-ssr` copy, a crawler and a
    browser both take the FIRST one they see, and the first one should be ours.
    Handles a document with no <head> because the test bundle has none.
    """
    if not tags:
        return document
    lowered = document.lower()
    for opener in ("<head>", "<html>"):
        at = lowered.find(opener)
        if at != -1:
            cut = at + len(opener)
            return document[:cut] + tags + document[cut:]
    return tags + document


def _noindex_if_off_canonical(request: Request, response: Response) -> Response:
    """Header form of the robots.txt rule above, for hosts we do not publish."""
    if not _is_canonical_host(request):
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


def _shell_response(request: Request, settings: Settings, path: str) -> Response:
    """
    index.html with this route's identity written into it.

    Still `Cache-Control: no-cache` for the same reason the plain file was: this
    document names the current hashed JS bundle, and a stale copy pins a
    returning visitor to a deleted file. The body now varies by path, which is
    another reason it must not be cached by anything in front of us.
    """
    document = settings.index_html.read_text(encoding="utf-8")
    body = _inject_head(document, _shell_head_tags(request, path))
    return _noindex_if_off_canonical(
        request, HTMLResponse(body, headers={"Cache-Control": "no-cache"})
    )


def _spa_shell(request: Request) -> Response:
    """
    The same response `_mount_frontend`'s catch-all gives an unrecognised
    client-side route. `/jobs/{source}/...` is shared ground: React Router
    owns it for anything that is not a real source name (a future client
    route, a stray link), the two routes below own it for anything that is.
    Without this, a path like `/jobs/some/deep/path` — which used to be pure
    client-side routing per test_single_origin.py — would 404 at this server
    instead of reaching React Router.
    """
    settings = cfg(request)
    if not settings.frontend_present():
        raise HTTPException(status_code=404, detail="Not found")
    return _shell_response(request, settings, request.url.path)


@router.get("/jobs/{source}/{source_id}", include_in_schema=False)
def job_teaser_redirect(source: str, source_id: str, request: Request):
    """Bare reference → canonical slug URL, so a hand-built link still resolves."""
    if source not in SOURCE_NAMES:
        return _spa_shell(request)
    with get_db(request) as conn:
        detail = job_read.get_job(conn, source, source_id, visibility=Visibility.ADDRESSABLE)
    if detail is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return RedirectResponse(
        _job_teaser_path(source, source_id, detail.title, detail.company), status_code=301
    )


@router.get("/jobs/{source}/{source_id}/{slug}", include_in_schema=False)
def job_teaser(source: str, source_id: str, slug: str, request: Request):
    """
    Public, ungated teaser for one Role — title, company, salary, a short AI
    summary, JobPosting structured data. Every tier, no session required (see
    the module-level comment above this section). Never returns
    `description_clean`, and never issues a Role-access grant.
    """
    if source not in SOURCE_NAMES:
        return _spa_shell(request)
    with get_db(request) as conn:
        detail = job_read.get_job(conn, source, source_id, visibility=Visibility.ADDRESSABLE)
    if detail is None:
        raise HTTPException(status_code=404, detail="Job not found")
    canonical_slug = _job_slug(detail.title, detail.company)
    if slug != canonical_slug:
        return RedirectResponse(f"/jobs/{source}/{source_id}/{canonical_slug}", status_code=301)
    canonical_url = f"{_public_base(request)}/jobs/{source}/{source_id}/{canonical_slug}"
    return _noindex_if_off_canonical(
        request, HTMLResponse(_job_teaser_html(detail, canonical_url))
    )


@router.get("/sitemap.xml", include_in_schema=False)
def sitemap(request: Request):
    """
    Every static page plus one <url> per addressable Role, any tier.

    This is the one place in the codebase that hands out the full (source,
    source_id) catalogue with no query, no session and no grant — a
    deliberate, scoped exception to ADR 0018 made for search engines. See the
    section comment above.
    """
    base = _public_base(request)
    # The same set as _ROUTE_META — a page we give a title and description must
    # also be a page we tell Google exists. tests/test_route_meta_in_step.py
    # fails if these two drift apart.
    static_paths = list(_ROUTE_META)
    # The discipline landing pages. "/jobs" itself answers a crawler with no
    # roles (no session, no query — ADR 0018), which is what made it a Soft 404;
    # each of these answers with hundreds to thousands, and carries a query, so
    # the "no enumerable catalogue" rule is untouched.
    static_paths += [_category_path(c) for c in BOARD_CATEGORIES]
    urls = [f"<url><loc>{base}{html.escape(p)}</loc></url>" for p in static_paths]
    with get_db(request) as conn:
        for row in job_read.list_sitemap_refs(conn):
            path = _job_teaser_path(row["source"], row["source_id"], row["title"], row["company"])
            entry = f"<url><loc>{base}{path}</loc>"
            if row["posted_at"]:
                entry += f"<lastmod>{row['posted_at'][:10]}</lastmod>"
            entry += "</url>"
            urls.append(entry)
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + "".join(urls)
        + "</urlset>"
    )
    return Response(content=body, media_type="application/xml")


def _is_canonical_host(request: Request) -> bool:
    """
    Whether this request arrived on the address we publish.

    Railway also answers on its own *.up.railway.app hostname, and that origin
    served the entire site at 200 with `Allow: /`. Two consequences, both bad:
    the same pages exist on two hosts (Google picks a winner and splits the
    signals), and our sign-in page was reachable on a free-hosting subdomain,
    which is the single most common place phishing kits are hosted. Requests
    there still work — health checks use it — they just say "do not index me".
    """
    canonical = os.environ.get("PUBLIC_BASE_URL", "").strip()
    if not canonical:
        return True  # local dev: nothing to be non-canonical against
    return request.url.netloc.lower() == urlparse(canonical).netloc.lower()


@router.get("/robots.txt", include_in_schema=False)
def robots(request: Request):
    base = _public_base(request)
    if not _is_canonical_host(request):
        # A crawler that found the Railway hostname is told to leave entirely,
        # and pointed at the real one.
        return PlainTextResponse(
            "User-agent: *\nDisallow: /\n" f"Sitemap: {base}/sitemap.xml\n"
        )
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /api/\n"
        "Disallow: /account\n"
        "Disallow: /admin\n"
        "Disallow: /saved\n"
        "Disallow: /signin\n"
        "Disallow: /register\n"
        "Disallow: /reset-password\n"
        "Disallow: /forgot-password\n"
        "Disallow: /verify\n"
        "Disallow: /employer/\n"
        "\n"
        f"Sitemap: {base}/sitemap.xml\n"
    )
    return PlainTextResponse(body)


@router.get("/.well-known/security.txt", include_in_schema=False)
def security_txt(request: Request):
    """
    Where to report a security problem (RFC 9116).

    Small file, disproportionate effect on how automated reputation scoring
    reads a domain: a site that publishes a real contact is a site someone is
    accountable for. Costs nothing and is one of the few legitimacy signals we
    can simply assert.
    """
    base = _public_base(request)
    body = (
        "Contact: mailto:security@finexclub.org\n"
        "Preferred-Languages: en\n"
        f"Canonical: {base}/.well-known/security.txt\n"
    )
    return PlainTextResponse(body)


# ── /api/filters ──────────────────────────────────────────────────────────────

@router.get("/api/filters", response_model=job_read.ResearchFacets, tags=["meta"])
def get_filters(
    request: Request,
    search: str = Query(..., min_length=2, max_length=200),
):
    """Return facets computed inside one research query, never globally."""
    research_query = search.strip()
    if len(research_query) < 2:
        raise HTTPException(
            status_code=422,
            detail="Start with a specific search of at least two characters.",
        )
    audience = (
        CatalogueAudience.MEMBER
        if _current_seeker(request) is not None
        else CatalogueAudience.PUBLIC
    )
    with get_db(request) as conn:
        return job_read.research_facets(conn, research_query, audience=audience)


# ── /api/stats ────────────────────────────────────────────────────────────────

@router.get("/api/stats", response_model=StatsResponse, tags=["meta"])
def get_stats(request: Request):
    audience_where = BOARD_WHERE
    if _current_seeker(request) is None:
        audience_where = f"{BOARD_WHERE} AND {job_read.PUBLIC_AUDIENCE_WHERE}"
    with get_db(request) as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM jobs j WHERE {audience_where}"
        ).fetchone()[0]
        # "Employers", so Recruiter Posts are out: their `company` is a recruiter's
        # name or an LLM guess, never an employer. See EMPLOYER_DIMENSION_WHERE.
        # An anonymous audience never saw them anyway (social is a member tier);
        # without this a signed-in Seeker was told 242 employers when 189 were real.
        employer_count = conn.execute(
            f"SELECT COUNT(DISTINCT j.company) FROM jobs j"
            f" WHERE {audience_where} AND {job_read.EMPLOYER_DIMENSION_WHERE}"
        ).fetchone()[0]

        # By sector
        sectors_raw = conn.execute(
            f"""
            SELECT sector, COUNT(*) AS cnt FROM (
              SELECT ({SECTOR_SQL}) AS sector
              FROM jobs j
              LEFT JOIN job_enrichments e ON j.source=e.source AND j.source_id=e.source_id
              WHERE {audience_where}
            ) sub GROUP BY sector ORDER BY cnt DESC
            """
        ).fetchall()
        by_sector = {r["sector"]: r["cnt"] for r in sectors_raw}

        # By seniority
        sen_raw = conn.execute(
            "SELECT e.seniority, COUNT(*) AS cnt"
            " FROM job_enrichments e JOIN jobs j ON j.source=e.source AND j.source_id=e.source_id"
            f" WHERE {audience_where} AND e.seniority IS NOT NULL"
            " GROUP BY e.seniority ORDER BY cnt DESC"
        ).fetchall()
        by_seniority = {r["seniority"]: r["cnt"] for r in sen_raw}

        # By remote type
        rem_raw = conn.execute(
            "SELECT e.remote_type, COUNT(*) AS cnt"
            " FROM job_enrichments e JOIN jobs j ON j.source=e.source AND j.source_id=e.source_id"
            f" WHERE {audience_where} AND e.remote_type IS NOT NULL"
            " GROUP BY e.remote_type ORDER BY cnt DESC"
        ).fetchall()
        by_remote_type = {r["remote_type"]: r["cnt"] for r in rem_raw}

        # By source tier (powers the All / Exclusive / Mainstream tabs)
        tier_raw = conn.execute(
            "SELECT COALESCE(source_tier, 'mainstream') AS tier, COUNT(*) AS cnt"
            f" FROM jobs j WHERE {audience_where} GROUP BY tier"
        ).fetchall()
        by_source_tier = {r["tier"]: r["cnt"] for r in tier_raw}

        # Top 15 skills
        skills_raw = conn.execute(
            f"""
            SELECT LOWER(sk.value) AS skill, COUNT(*) AS cnt
            FROM jobs j
            JOIN job_enrichments e ON j.source=e.source AND j.source_id=e.source_id
            JOIN json_each(e.required_skills) sk
            WHERE {audience_where}
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
            f" WHERE {audience_where} AND {job_read.EMPLOYER_DIMENSION_WHERE}"
            " GROUP BY j.company ORDER BY cnt DESC LIMIT 15"
        ).fetchall()
        top_companies = [NameCount(name=r["company"], count=r["cnt"]) for r in comp_raw]

        # Internship count
        intern_count = conn.execute(
            f"SELECT COUNT(*) FROM jobs j WHERE {audience_where} AND {INTERNSHIP_COND}"
        ).fetchone()[0]

    return StatsResponse(
        total_active_jobs=total,
        employer_count=employer_count,
        by_sector=by_sector,
        by_seniority=by_seniority,
        by_remote_type=by_remote_type,
        by_source_tier=by_source_tier,
        top_skills=top_skills,
        top_companies=top_companies,
        internship_count=intern_count,
    )


# ── /api/learning ─────────────────────────────────────────────────────────────

@router.get("/api/learning", tags=["learning"])
def get_learning_content(request: Request):
    """Serve the last-known-good metadata without contacting either source."""

    return learning_content.public_snapshot(cfg(request).learning_content_path)


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
    """
    Left-most X-Forwarded-For entry when behind a trusted proxy (Railway), else
    the direct peer.

    Gated on settings.trust_proxy_headers — every IP-keyed rate limit in this
    file (register, login, reset, employer register/login, post-role)
    reads its key from this function, so trusting the header unconditionally
    would let a caller who can reach the app directly forge a fresh IP on every
    request and route around all of them.
    """
    if cfg(request).trust_proxy_headers:
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


EMPLOYMENT_TYPES = {"Full-time", "Contract", "Part-time", "Internship"}

# RFC 2606 reserved domains. Real recruiters never post from these — seeing one
# here is a reliable signature of an automated form-tester/scanner that fills
# every visible field with generic placeholder values (the honeypot field below
# only catches bots that blindly fill hidden inputs too, which this class of
# bot does not).
_RESERVED_PLACEHOLDER_DOMAINS = frozenset({
    "example.com", "example.net", "example.org", "example.edu",
})


def _is_placeholder_domain(host_or_email: str) -> bool:
    host = host_or_email.rsplit("@", 1)[-1].strip().lower().rstrip(".")
    return any(
        host == domain or host.endswith(f".{domain}")
        for domain in _RESERVED_PLACEHOLDER_DOMAINS
    )


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
        if _is_placeholder_domain(urlparse(v).hostname or ""):
            raise ValueError("apply_url must be a real, reachable URL")
        return v

    @field_validator("contact_email")
    @classmethod
    def _real_contact_domain(cls, v: str) -> str:
        if _is_placeholder_domain(v):
            raise ValueError("contact_email must be a real address")
        return v


class SubmitResponse(BaseModel):
    ok: bool


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
    sent = request.app.state.notifier.notify(
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
        "email": "configured" if SMTP_USER else "NOT CONFIGURED — Role submissions queue but no mail is sent",
        "submission_recipient": SUBMISSION_RECIPIENT if SMTP_USER else None,
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
# Public research needs no account, but ADR 0018 no longer permits an unscoped
# catalogue read. Accounts add Saved Roles and personalization; short-lived
# Role grants protect detail reads independently of sign-in.

import auth  # noqa: E402 — same local-module convention as mailer/env_file above
import identity_protocol  # noqa: E402
import seekers_store  # noqa: E402

# Admin Mode's router. admin.py takes cfg/get_db/_require_admin as arguments
# (see build_router's docstring) rather than importing them, specifically so
# THIS import stays one-directional — admin.py never imports main.py back.
import admin  # noqa: E402

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
    state on this API, not an error, because research itself is public (ADR 0018).

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


def _require_admin(request: Request) -> dict:
    """
    The signed-in Seeker, and only if Admin Mode is on for them.

    401 for "not signed in at all" and 403 for "signed in but not an admin" are
    kept distinct here — unlike login's deliberately-uniform failures, there is
    no enumeration risk in telling an ordinary Seeker they lack a privilege they
    already know they don't have.
    """
    seeker = _require_seeker(request)
    if not seeker.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return seeker


def _require_super_admin(request: Request) -> dict:
    """
    Admin Mode plus is_super_admin — Ultimate Admin, and only Ultimate Admin.
    Gates webapp/backend/job_edit.py's direct read/write onto a job row: the
    other four admins see the same dashboard but never this.
    """
    seeker = _require_admin(request)
    if not seeker.get("is_super_admin"):
        raise HTTPException(status_code=403, detail="Ultimate Admin access required")
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
    SUBMISSION_RECIPIENT precisely so that endpoint cannot become an open relay. Accounts
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
    # Honeypot, matching the public Role-submission form. A human never sees it.
    website: str = ""


class LoginIn(BaseModel):
    # NOT EmailStr, unlike RegisterIn — this field doubles as a username for
    # the handful of accounts scripts/create_admin.py gives one to (see
    # seekers_store.migrate_to_phase_3). Registration and password reset stay
    # EmailStr-only: those genuinely need a deliverable address, sign-in does
    # not, it needs the address you have already proven once.
    email: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class SeekerOut(BaseModel):
    id: str
    email: str
    display_name: str
    email_verified: bool
    is_admin: bool
    is_super_admin: bool


class SaveRoleIn(BaseModel):
    source: str = Field(min_length=1, max_length=50)
    source_id: str = Field(min_length=1, max_length=200)
    access_token: str = Field(min_length=1, max_length=2_048)


class MergeSavedIn(BaseModel):
    roles: list[SaveRoleIn] = Field(default_factory=list, max_length=500)


def _seeker_out(row: dict) -> SeekerOut:
    return SeekerOut(
        id=row["id"],
        email=row["email"],
        display_name=row.get("display_name") or "",
        email_verified=bool(row.get("email_verified")),
        is_admin=bool(row.get("is_admin")),
        is_super_admin=bool(row.get("is_super_admin")),
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
        return SeekerOut(id="", email=email, display_name="", email_verified=False, is_admin=False, is_super_admin=False)

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
        return SeekerOut(id="", email=email, display_name="", email_verified=False, is_admin=False, is_super_admin=False)

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


def _public_base(request: Request) -> str:
    """
    The externally-reachable origin the frontend is served from.

    PUBLIC_BASE_URL in production — Railway sits behind a proxy, so
    request.base_url would answer with the internal host, not the address a
    Seeker's browser can actually reach. Falls back to the request's own
    base_url for local dev, where there is no proxy in the way. Shared by
    every place this backend builds a link back into the single-page app: the
    verify and reset emails, and the Google OAuth redirect below.
    """
    return os.environ.get("PUBLIC_BASE_URL", "").rstrip("/") or str(request.base_url).rstrip("/")


def _verify_url(request: Request, raw_token: str) -> str:
    return _account_link_url(request, "verify", raw_token)


def _account_link_url(request: Request, path: str, raw_token: str) -> str:
    """Build a link into a single-page-app route that carries a raw email token."""
    return f"{_public_base(request)}/{path}?token={raw_token}"


class VerifyEmailIn(BaseModel):
    token: str = Field(min_length=1, max_length=200)


@router.post("/api/auth/verify-email", response_model=SeekerOut, tags=["auth"])
def verify_email(payload: VerifyEmailIn, request: Request):
    """
    Spend a verification token and mark the Seeker's email verified.

    Deliberately a POST the frontend page fires from JS, not a GET the email
    link itself resolves to. Some mail clients pre-fetch links to scan them for
    malware, which would silently burn a single-use GET token before the Seeker
    ever clicked it — a POST triggered by page script is invisible to that kind
    of prefetch.

    Not gated on being signed in: the token itself is the credential, the same
    way a password-reset link is. One failure message for every cause — unknown,
    expired, already used — for the same reason login collapses its failures:
    nothing here should let a caller distinguish them.
    """
    store = seekers_store.get_store()
    seeker_id = auth.consume_email_token(store, payload.token, purpose="verify")
    if seeker_id is None:
        raise HTTPException(status_code=400, detail="This link is no longer valid.")

    store.set_email_verified(seeker_id, True)
    store.log_event("seeker.email_verified", seeker_id=seeker_id)
    return _seeker_out(store.get_seeker(seeker_id))


class UnsubscribeAlertsIn(BaseModel):
    token: str = Field(min_length=1, max_length=512)


@router.post("/api/alerts/unsubscribe", status_code=204, tags=["alerts"])
def unsubscribe_from_alerts(payload: UnsubscribeAlertsIn, request: Request):
    """
    Turn off weekly Alerts from the link in an Alert email. No session required
    — the token itself is the credential, same posture as verify/reset.

    Deliberately a POST the frontend's /unsubscribe page fires from JS, not a
    GET the email link itself resolves to, for the same reason verify-email is
    a POST above: a mail client that pre-fetches links to scan them for
    malware must not be able to silently unsubscribe someone who never opened
    the email, let alone clicked anything in it.

    One response for every outcome — unknown Seeker, tampered token, already
    unsubscribed — because every one of those leaves the Seeker un-subscribed,
    which is the only state a broken or reused token could sensibly want.
    Unlike email_tokens, this token is not single-use and does not expire
    (alert_unsubscribe.py): resolving it twice is not an error.
    """
    store = seekers_store.get_store()
    seeker_id = request.app.state.alert_unsubscribe_tokens.resolve(payload.token)
    if seeker_id is not None and store.get_seeker(seeker_id) is not None:
        store.set_alert_opt_in(seeker_id, False)
        store.log_event("alerts.opted_out", seeker_id)
    return Response(status_code=204)


@router.post("/api/auth/login", response_model=SeekerOut, tags=["auth"])
def login(payload: LoginIn, request: Request, response: Response):
    """
    Sign in with an email OR a username. One failure message for every cause —
    wrong password, no such account, Google-only account with no password set —
    because distinguishing them is the same oracle problem as register.

    Username is the exception to "this field is an email": Admin Mode's five
    accounts (seekers_store.migrate_to_phase_3) each have one, precisely so
    signing in does not require remembering an address nobody ever mails. The
    lookup tries email first because that is what almost every caller sends;
    falling through to username costs one extra indexed query only for the
    identifiers that were never a registered email to begin with.
    """
    identifier = seekers_store.normalise_email(payload.email)
    ip = _client_ip(request)
    if _auth_rate_limited(request, f"login:email:{identifier}", limit=10, window_s=900) or \
       _auth_rate_limited(request, f"login:ip:{ip}", limit=30, window_s=900):
        raise HTTPException(status_code=429,
                            detail="Too many attempts. Try again in a few minutes.")

    store = seekers_store.get_store()
    row = store.get_seeker_by_email(identifier) or store.get_seeker_by_username(identifier)
    # verify_password() hashes against a dummy when the row is absent, so the
    # response time does not reveal whether the address/username exists.
    if not auth.verify_password(row["password_hash"] if row else None, payload.password):
        store.log_event("seeker.login_failed", seeker_id=row["id"] if row else None)
        raise HTTPException(status_code=401, detail="Email or password is incorrect")

    # The plaintext is only ever available right here, on a successful login —
    # this is the one place Argon2 parameters can be strengthened for the whole
    # Seeker base without forcing anyone through a password reset.
    if auth.password_needs_rehash(row["password_hash"]):
        store.set_password_hash(row["id"], auth.hash_password(payload.password))

    store.touch_last_login(row["id"])
    store.log_event("seeker.login", seeker_id=row["id"])
    _set_session_cookie(request, response, auth.issue_session(store, row["id"],
                                                     user_agent=request.headers.get("user-agent")))
    return _seeker_out(store.get_seeker(row["id"]))


class ForgotPasswordIn(BaseModel):
    email: EmailStr


@router.post("/api/auth/forgot-password", response_model=SubmitResponse, tags=["auth"])
def forgot_password(payload: ForgotPasswordIn, request: Request):
    """
    Request a password-reset email. Always answers the same way, same as
    register's account-enumeration defence (decision 15): whether or not the
    address has an account is not something a caller may learn from this
    response, only from whether an email arrives.
    """
    email = seekers_store.normalise_email(payload.email)
    ip = _client_ip(request)
    if _auth_rate_limited(request, f"reset:email:{email}", limit=3, window_s=3600) or \
       _auth_rate_limited(request, f"reset:ip:{ip}", limit=10, window_s=3600):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")

    store = seekers_store.get_store()
    row = store.get_seeker_by_email(email)
    if row is not None:
        raw_token = auth.issue_email_token(store, row["id"], purpose="reset")
        _send_seeker_mail(
            request,
            email,
            "Reset your password — FinEx Careers",
            f"Reset your FinEx Careers password:\n\n{_account_link_url(request, 'reset-password', raw_token)}\n\n"
            f"This link works once and expires in an hour. If you did not request this, "
            f"you can ignore this message — your password has not changed.",
        )
    return SubmitResponse(ok=True)


class ResetPasswordIn(BaseModel):
    token: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8, max_length=200)


@router.post("/api/auth/reset-password", response_model=SeekerOut, tags=["auth"])
def reset_password(payload: ResetPasswordIn, request: Request, response: Response):
    """
    Spend a reset token, set the new password, and sign out every other
    session (auth.py: "leaving the attacker's session alive defeats the point
    of the reset"). Signs the caller straight back in on this one, same as
    register — a reset that ends at a sign-in form is a worse flow than the
    one it replaced.
    """
    store = seekers_store.get_store()
    seeker_id = auth.consume_email_token(store, payload.token, purpose="reset")
    if seeker_id is None:
        raise HTTPException(status_code=400, detail="This link is no longer valid.")

    store.set_password_hash(seeker_id, auth.hash_password(payload.password))
    auth.revoke_all_sessions(store, seeker_id)
    store.log_event("seeker.password_reset", seeker_id=seeker_id)

    _set_session_cookie(request, response, auth.issue_session(store, seeker_id,
                                                     user_agent=request.headers.get("user-agent")))
    return _seeker_out(store.get_seeker(seeker_id))


@router.post("/api/auth/logout", status_code=204, tags=["auth"])
def logout(request: Request, response: Response):
    """Always 204. Logging out of a session you don't have is not an error."""
    auth.revoke_session(seekers_store.get_store(), request.cookies.get(SESSION_COOKIE))
    _clear_session_cookie(response)
    return Response(status_code=204)


@router.get("/api/auth/me", response_model=SeekerOut, tags=["auth"])
def whoami(request: Request):
    return _seeker_out(_require_seeker(request))


VISITOR_COOKIE = "finex_visitor"
# ~400 days: the cap most browsers enforce on cookie lifetime (Chrome since
# 2023), so anything longer is silently truncated anyway.
VISITOR_COOKIE_MAX_AGE = 60 * 60 * 24 * 400


@router.post("/api/visit", tags=["analytics"])
def record_board_visit(request: Request, response: Response):
    """
    Count one anonymous board visit, fired by the frontend once per app load.

    Skipped entirely for a request that already carries a valid Seeker
    session — that activity is already counted by `sessions`
    (seekers_store.user_activity_overview), and recording it twice would
    double-count the same human across both populations.

    The visitor cookie carries no identity: a random opaque token, hashed
    before storage exactly like a session token (auth.hash_token), sent
    nowhere but back to this one endpoint. Rate-limited per IP because unlike
    a Seeker session, nothing about this endpoint requires proving you are a
    distinct person — the limit is what stops a script with no cookie jar
    from inflating the count indefinitely.
    """
    # Mutate and return THIS SAME object, never a fresh Response(...) — FastAPI
    # only merges the injected response's headers/cookies into the final reply
    # when the endpoint returns it directly; a newly constructed Response
    # bypasses it and silently drops the cookie.
    response.status_code = 204
    if _current_seeker(request) is not None:
        return response
    if _auth_rate_limited(request, f"visit:ip:{_client_ip(request)}", limit=60, window_s=3600):
        return response

    raw = request.cookies.get(VISITOR_COOKIE)
    if not raw:
        raw = auth.generate_token()
        response.set_cookie(
            VISITOR_COOKIE,
            raw,
            max_age=VISITOR_COOKIE_MAX_AGE,
            httponly=True,          # unreadable to JS, so XSS cannot exfiltrate it
            secure=cfg(request).cookie_secure,
            samesite="lax",
            path="/",
        )
    seekers_store.get_store().record_visit(auth.hash_token(raw))
    return response


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
    _grant_role_access(request, saved)
    return saved


@router.post("/api/me/saved", status_code=204, tags=["saved"])
def save_role(payload: SaveRoleIn, request: Request):
    seeker = _require_seeker(request)
    if not request.app.state.role_access.allows(
        payload.access_token, payload.source, payload.source_id
    ):
        raise HTTPException(status_code=404, detail="Job not found")
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
    allowed_roles = [
        role
        for role in payload.roles
        if request.app.state.role_access.allows(
            role.access_token, role.source, role.source_id
        )
    ]
    allowed = [(role.source, role.source_id) for role in allowed_roles]
    added = store.merge_saved_roles(seeker["id"], allowed)
    if added:
        store.log_event("saved.migrated", seeker_id=seeker["id"])
    return {
        "merged": added,
        "submitted": len(payload.roles),
        "accepted": [
            {"source": role.source, "source_id": role.source_id}
            for role in allowed_roles
        ],
    }


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


# ── Google OAuth (phase 4 of PLAN_ACCOUNTS.md) ────────────────────────────────
#
# Wires the redirect GoogleButton (AuthShell.tsx) has pointed at since it was
# built — GOOGLE_SIGN_IN_PATH is `${API}/api/auth/google` on the frontend
# already; nothing there needs to change for this to light up.
#
# WHAT THIS NEEDS THAT NO AMOUNT OF CODE CAN SUPPLY: a Google Cloud project
# with an OAuth consent screen, and GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET in
# the environment. PLAN_ACCOUNTS.md §9 lists creating that project as an owner
# task with lead time — it needs a Google account with billing/console access
# this process does not have. Until those two variables are set, /api/auth/
# google answers with a redirect to an error state instead of attempting
# anything, on every environment including production: this is not a
# feature-flagged code path, it is the only thing correct to do with no
# credentials.
#
# The exchange delegates signature verification to Google's own tokeninfo
# endpoint rather than hand-rolling JWKS verification (ADR 0004: delegate
# crypto, do not reimplement it). That endpoint is documented by Google as
# suitable for server-side verification, not only debugging; the one thing
# worth knowing if this is hardened later is that it is one extra round trip
# per sign-in, which a local JWKS-based verifier (e.g. the `google-auth`
# package) would avoid at the cost of a new dependency — deliberately not
# added here without asking, per this repo's "no substitution without asking"
# rule on the tech stack.

#: Scoped to the OAuth start/callback pair, not path="/" — this cookie carries
#: no identity, only a CSRF nonce, and has no reason to ride along on every
#: other request for the ten minutes it lives.
GOOGLE_STATE_COOKIE = "google_oauth_state"
GOOGLE_STATE_COOKIE_PATH = "/api/auth/google"


def _google_redirect_uri(request: Request) -> str:
    """
    Where Google sends the browser back to. Must match a URI registered on the
    OAuth client EXACTLY (Google rejects anything else at the consent screen,
    before this code ever runs) — GOOGLE_REDIRECT_URI overrides the computed
    default for an operator who needs a value that PUBLIC_BASE_URL cannot
    express.
    """
    override = os.environ.get("GOOGLE_REDIRECT_URI", "").strip()
    return override or f"{_public_base(request)}/api/auth/google/callback"


def _google_failure_redirect(request: Request, reason: str) -> RedirectResponse:
    logger.warning("Google sign-in did not complete: %s", reason)
    resp = RedirectResponse(f"{_public_base(request)}/signin?error=google_failed")
    resp.delete_cookie(GOOGLE_STATE_COOKIE, path=GOOGLE_STATE_COOKIE_PATH)
    return resp


@router.get("/api/auth/google", tags=["auth"], include_in_schema=False)
def google_start(request: Request):
    """
    Redirect to Google's consent screen.

    A GET matched to GoogleButton's plain `<a href>`: only a full page
    navigation can carry the browser to accounts.google.com and back with
    Google's own cookies intact, which is why the button is a link rather than
    a fetch call (see AuthShell.tsx).
    """
    try:
        authorization = request.app.state.identity_protocol.begin(
            "google", _google_redirect_uri(request)
        )
    except identity_protocol.ProviderUnavailable:
        logger.warning("GET /api/auth/google called but GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET are not set")
        return RedirectResponse(f"{_public_base(request)}/signin?error=google_unavailable")

    resp = RedirectResponse(authorization.url)
    resp.set_cookie(
        GOOGLE_STATE_COOKIE,
        authorization.state,
        max_age=600,  # the consent screen round trip, generously bounded
        httponly=True,
        secure=cfg(request).cookie_secure,
        samesite="lax",
        path=GOOGLE_STATE_COOKIE_PATH,
    )
    return resp


@router.get("/api/auth/google/callback", tags=["auth"], include_in_schema=False)
def google_callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
):
    """
    Exchange the code, verify the identity token, and hand the result to
    auth.link_or_create_seeker — the same three-case rule a Google sign-in and
    a future LinkedIn one will both go through.
    """
    try:
        claim = request.app.state.identity_protocol.complete(
            "google",
            _google_redirect_uri(request),
            identity_protocol.Callback(
                code=code,
                state=state,
                cookie_state=request.cookies.get(GOOGLE_STATE_COOKIE),
                error=error,
            ),
        )
    except identity_protocol.ProviderUnavailable:
        logger.warning("Google callback reached but GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET are not set")
        resp = RedirectResponse(f"{_public_base(request)}/signin?error=google_unavailable")
        resp.delete_cookie(GOOGLE_STATE_COOKIE, path=GOOGLE_STATE_COOKIE_PATH)
        return resp
    except identity_protocol.IdentityProtocolError as exc:
        return _google_failure_redirect(request, str(exc))

    store = seekers_store.get_store()
    try:
        result = auth.link_or_create_seeker(store, claim)
    except auth.IdentityLinkRefused as exc:
        logger.warning("Google identity link refused for subject %s: %s", claim.subject, exc)
        resp = RedirectResponse(f"{_public_base(request)}/signin?error=google_link_refused")
        resp.delete_cookie(GOOGLE_STATE_COOKIE, path=GOOGLE_STATE_COOKIE_PATH)
        return resp

    store.touch_last_login(result.seeker_id)
    store.log_event(f"seeker.google_{result.outcome}", seeker_id=result.seeker_id)

    resp = RedirectResponse(f"{_public_base(request)}/account")
    resp.delete_cookie(GOOGLE_STATE_COOKIE, path=GOOGLE_STATE_COOKIE_PATH)
    _set_session_cookie(request, resp, auth.issue_session(store, result.seeker_id,
                                                     user_agent=request.headers.get("user-agent")))
    return resp


# ── LinkedIn OIDC (the fast-follow docs/adr/0003 scheduled) ───────────────────
#
# The identity-linking core never needed to change for this: auth.IdentityClaim
# and auth.link_or_create_seeker were written provider-agnostic from the start
# (test_auth_core.py's test_two_providers_reach_one_seeker already exercised
# provider="linkedin" before this file had a route for it). This section is the
# browser adapter around identity_protocol's provider exchange.
#
# WHAT THIS NEEDS THAT NO AMOUNT OF CODE CAN SUPPLY: a LinkedIn Company Page,
# a LinkedIn Developer app with the "Sign In with LinkedIn using OpenID
# Connect" product added, and LINKEDIN_CLIENT_ID / LINKEDIN_CLIENT_SECRET in
# the environment (docs/adr/0003's exact prerequisite). Until both are set,
# /api/auth/linkedin answers with a redirect to an error state instead of
# attempting anything — same posture as Google above, for the same reason.
#
# Why a userinfo call and not a decoded id_token: LinkedIn's OIDC userinfo
# endpoint (https://api.linkedin.com/v2/userinfo) returns the claims directly
# once called with the access token this exchange already obtained under our
# own client_secret — so there is no bare, self-issued id_token to verify the
# audience of the way Google's tokeninfo endpoint requires (ADR 0004: delegate
# verification to the provider rather than hand-rolling JWT signature checks).
#
# identity_protocol accepts only explicit true email-verification evidence —
# PLAN_ACCOUNTS.md §3's fact about this provider, and IdentityClaim's own
# docstring: LinkedIn includes email/email_verified only optionally at all.

#: Same reasoning as GOOGLE_STATE_COOKIE — a CSRF nonce, not identity, scoped
#: to the start/callback pair rather than path="/".
LINKEDIN_STATE_COOKIE = "linkedin_oauth_state"
LINKEDIN_STATE_COOKIE_PATH = "/api/auth/linkedin"


def _linkedin_redirect_uri(request: Request) -> str:
    """Must match a redirect URL registered on the LinkedIn app EXACTLY —
    LinkedIn rejects anything else at the consent screen, before this code
    ever runs. LINKEDIN_REDIRECT_URI overrides the computed default for an
    operator who needs a value PUBLIC_BASE_URL cannot express."""
    override = os.environ.get("LINKEDIN_REDIRECT_URI", "").strip()
    return override or f"{_public_base(request)}/api/auth/linkedin/callback"


def _linkedin_failure_redirect(request: Request, reason: str) -> RedirectResponse:
    logger.warning("LinkedIn sign-in did not complete: %s", reason)
    resp = RedirectResponse(f"{_public_base(request)}/signin?error=linkedin_failed")
    resp.delete_cookie(LINKEDIN_STATE_COOKIE, path=LINKEDIN_STATE_COOKIE_PATH)
    return resp


@router.get("/api/auth/linkedin", tags=["auth"], include_in_schema=False)
def linkedin_start(request: Request):
    """Redirect to LinkedIn's consent screen. A GET matched to LinkedInButton's
    plain `<a href>`, same reasoning as google_start: only a full page
    navigation can carry the browser to linkedin.com and back with LinkedIn's
    own cookies intact."""
    try:
        authorization = request.app.state.identity_protocol.begin(
            "linkedin", _linkedin_redirect_uri(request)
        )
    except identity_protocol.ProviderUnavailable:
        logger.warning("GET /api/auth/linkedin called but LINKEDIN_CLIENT_ID/LINKEDIN_CLIENT_SECRET are not set")
        return RedirectResponse(f"{_public_base(request)}/signin?error=linkedin_unavailable")

    resp = RedirectResponse(authorization.url)
    resp.set_cookie(
        LINKEDIN_STATE_COOKIE,
        authorization.state,
        max_age=600,  # the consent screen round trip, generously bounded
        httponly=True,
        secure=cfg(request).cookie_secure,
        samesite="lax",
        path=LINKEDIN_STATE_COOKIE_PATH,
    )
    return resp


@router.get("/api/auth/linkedin/callback", tags=["auth"], include_in_schema=False)
def linkedin_callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
):
    """Exchange the code, fetch the userinfo claims, and hand the result to
    auth.link_or_create_seeker — the same three-case rule Google sign-in
    already goes through."""
    try:
        claim = request.app.state.identity_protocol.complete(
            "linkedin",
            _linkedin_redirect_uri(request),
            identity_protocol.Callback(
                code=code,
                state=state,
                cookie_state=request.cookies.get(LINKEDIN_STATE_COOKIE),
                error=error,
            ),
        )
    except identity_protocol.ProviderUnavailable:
        logger.warning("LinkedIn callback reached but LINKEDIN_CLIENT_ID/LINKEDIN_CLIENT_SECRET are not set")
        resp = RedirectResponse(f"{_public_base(request)}/signin?error=linkedin_unavailable")
        resp.delete_cookie(LINKEDIN_STATE_COOKIE, path=LINKEDIN_STATE_COOKIE_PATH)
        return resp
    except identity_protocol.IdentityProtocolError as exc:
        return _linkedin_failure_redirect(request, str(exc))

    store = seekers_store.get_store()
    try:
        result = auth.link_or_create_seeker(store, claim)
    except auth.IdentityLinkRefused as exc:
        logger.warning("LinkedIn identity link refused for subject %s: %s", claim.subject, exc)
        resp = RedirectResponse(f"{_public_base(request)}/signin?error=linkedin_link_refused")
        resp.delete_cookie(LINKEDIN_STATE_COOKIE, path=LINKEDIN_STATE_COOKIE_PATH)
        return resp

    store.touch_last_login(result.seeker_id)
    store.log_event(f"seeker.linkedin_{result.outcome}", seeker_id=result.seeker_id)

    resp = RedirectResponse(f"{_public_base(request)}/account")
    resp.delete_cookie(LINKEDIN_STATE_COOKIE, path=LINKEDIN_STATE_COOKIE_PATH)
    _set_session_cookie(request, resp, auth.issue_session(store, result.seeker_id,
                                                     user_agent=request.headers.get("user-agent")))
    return resp


# ── Employer / recruiter accounts (opening ADR 0001's gate) ────────────────────
#
# A second, deliberately separate identity system — see docs/adr/0001:
# "Employer accounts stay out of scope until there is paid inventory to
# sell... Employers get their own table when they arrive." This reopens that
# ADR at the owner's explicit direction (2026-08-05 session), not by routing
# around it: its own store (employers_store.py), its own table, its own
# cookie. The only code shared with Seeker identity is auth.py's pure
# crypto/session functions and, as of phase 2, its email-token functions and
# a dedicated link_or_create_employer() — see auth.py's module docstring for
# what is shared and what genuinely diverges.
#
# v1 shipped identity only: register, sign in, sign out, see your own
# account, delete it. Phase 2 (this section, plus the verify-email/forgot-
# password/reset-password/Google endpoints below) adds email verification,
# password reset and Google sign-in — each alongside the frontend page that
# completes it, in the same change, per employers_store.py's module
# docstring rule. Google sign-in never CREATES an Employer (see
# auth.link_or_create_employer): registration always happens with a
# password first, and the registration form nudges toward a work email
# while Google — inherently Gmail-capable — stays fully available as a
# convenience for signing back in afterward.
#
# Still deferred: no submissions dashboard. Connecting this to
# data/submitted_roles.jsonl (scripts/review_submissions.py) by matching
# contact_email is the natural next slice, held back because it wants a
# product decision about the matching rule, not a code gap.

import employers_store  # noqa: E402

EMPLOYER_SESSION_COOKIE = "finex_employer_session"


def _set_employer_session_cookie(request: Request, response: Response, raw_token: str) -> None:
    """
    Same shape as _set_session_cookie, on a DIFFERENT cookie name. Deliberate:
    a browser can hold a Seeker session and an Employer session at the same
    time, which is the real case of someone who is both a candidate and posts
    roles for their firm.
    """
    response.set_cookie(
        EMPLOYER_SESSION_COOKIE,
        raw_token,
        max_age=int(auth.SESSION_TTL.total_seconds()),
        httponly=True,
        secure=cfg(request).cookie_secure,
        samesite="lax",
        path="/",
    )


def _clear_employer_session_cookie(response: Response) -> None:
    response.delete_cookie(EMPLOYER_SESSION_COOKIE, path="/", samesite="lax")


def _current_employer(request: Request) -> Optional[dict]:
    raw = request.cookies.get(EMPLOYER_SESSION_COOKIE)
    if not raw:
        return None
    try:
        store = employers_store.get_store()
        employer_id = auth.verify_session(store, raw)
        return store.get_employer(employer_id) if employer_id else None
    except Exception:  # noqa: BLE001 — a bad cookie is anonymous, not a 500
        logger.warning("Employer session verification failed", exc_info=True)
        return None


def _require_employer(request: Request) -> dict:
    employer = _current_employer(request)
    if employer is None:
        raise HTTPException(status_code=401, detail="Not signed in")
    return employer


class EmployerRegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    company_name: str = Field(min_length=1, max_length=150)
    contact_name: str = Field(default="", max_length=100)
    # Honeypot, same convention as every other form in this file.
    website: str = ""


class EmployerLoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class EmployerOut(BaseModel):
    id: str
    email: str
    company_name: str
    contact_name: str
    email_verified: bool


def _employer_out(row: dict) -> EmployerOut:
    return EmployerOut(
        id=row["id"],
        email=row["email"],
        company_name=row["company_name"],
        contact_name=row.get("contact_name") or "",
        email_verified=bool(row.get("email_verified")),
    )


def _send_employer_mail(request: Request, to: str, subject: str, body: str) -> bool:
    """Mail *to an Employer*, at an address they typed. Same shape and same
    reasoning as _send_seeker_mail — see that docstring; nothing here differs
    except the recipient store."""
    return request.app.state.sender.send(Message(to=to, subject=subject, body=body))


@router.post("/api/employer/register", response_model=EmployerOut, status_code=201, tags=["employer"])
def employer_register(payload: EmployerRegisterIn, request: Request, response: Response):
    """
    Create an Employer and sign them straight in.

    Deliberately NOT the Seeker flow's non-enumerable "answers like success
    either way": that trick only pays for itself when there is a mail path to
    tell the real owner someone tried (register() does, via
    _send_seeker_mail). There is no Employer mail path yet, so a fake-success
    response here would leave a legitimate Employer who forgot they had an
    account looking at a silent dead end instead of a "sign in instead" you
    can act on. A real 409 costs an email-enumeration signal this recruiter
    directory does not have much to protect — most of these addresses are
    already semi-public on a company's own careers page. Revisit if that
    changes.
    """
    email = employers_store.normalise_email(payload.email)
    ip = _client_ip(request)

    if payload.website.strip():
        logger.info("Honeypot triggered on /api/employer/register from %s", ip)
        return EmployerOut(
            id="", email=email, company_name=payload.company_name,
            contact_name="", email_verified=False,
        )

    if _auth_rate_limited(request, f"emp-reg:email:{email}", limit=3, window_s=3600) or \
       _auth_rate_limited(request, f"emp-reg:ip:{ip}", limit=10, window_s=3600):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")

    store = employers_store.get_store()
    try:
        employer_id = store.create_employer(
            email,
            password_hash=auth.hash_password(payload.password),
            company_name=payload.company_name.strip(),
            contact_name=payload.contact_name.strip() or None,
        )
    except employers_store.EmailAlreadyRegistered:
        raise HTTPException(
            status_code=409, detail="That email already has an employer account. Sign in instead."
        ) from None

    store.log_event("employer.registered", employer_id=employer_id)
    _set_employer_session_cookie(request, response, auth.issue_session(
        store, employer_id, user_agent=request.headers.get("user-agent")))
    raw_token = auth.issue_email_token(store, employer_id, purpose="verify")
    _send_employer_mail(
        request,
        email,
        "Confirm your email — FinEx Careers",
        f"Welcome to FinEx Careers.\n\nConfirm this address to finish setting up "
        f"your employer account:\n\n{_account_link_url(request, 'employer/verify', raw_token)}\n\n"
        f"This link works once and expires in an hour.",
    )
    return _employer_out(store.get_employer(employer_id))


class EmployerVerifyEmailIn(BaseModel):
    token: str = Field(min_length=1, max_length=200)


@router.post("/api/employer/auth/verify-email", response_model=EmployerOut, tags=["employer"])
def employer_verify_email(payload: EmployerVerifyEmailIn, request: Request):
    """Spend a verification token. Same shape as Seeker's verify_email() —
    see that docstring for why this is a POST fired from script rather than
    the GET the email link itself resolves to, and why every failure cause
    collapses to one answer."""
    store = employers_store.get_store()
    employer_id = auth.consume_email_token(store, payload.token, purpose="verify")
    if employer_id is None:
        raise HTTPException(status_code=400, detail="This link is no longer valid.")

    store.set_email_verified(employer_id, True)
    store.log_event("employer.email_verified", employer_id=employer_id)
    return _employer_out(store.get_employer(employer_id))


@router.post("/api/employer/login", response_model=EmployerOut, tags=["employer"])
def employer_login(payload: EmployerLoginIn, request: Request, response: Response):
    """One failure message for every cause, same reasoning as Seeker login."""
    email = employers_store.normalise_email(payload.email)
    ip = _client_ip(request)
    if _auth_rate_limited(request, f"emp-login:email:{email}", limit=10, window_s=900) or \
       _auth_rate_limited(request, f"emp-login:ip:{ip}", limit=30, window_s=900):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again in a few minutes.")

    store = employers_store.get_store()
    row = store.get_employer_by_email(email)
    if not auth.verify_password(row["password_hash"] if row else None, payload.password):
        store.log_event("employer.login_failed", employer_id=row["id"] if row else None)
        raise HTTPException(status_code=401, detail="Email or password is incorrect")

    # Same rehash-on-login as Seeker's login() — the plaintext is only ever
    # available right here.
    if auth.password_needs_rehash(row["password_hash"]):
        store.set_password_hash(row["id"], auth.hash_password(payload.password))

    store.touch_last_login(row["id"])
    store.log_event("employer.login", employer_id=row["id"])
    _set_employer_session_cookie(request, response, auth.issue_session(
        store, row["id"], user_agent=request.headers.get("user-agent")))
    return _employer_out(store.get_employer(row["id"]))


class EmployerForgotPasswordIn(BaseModel):
    email: EmailStr


@router.post("/api/employer/auth/forgot-password", response_model=SubmitResponse, tags=["employer"])
def employer_forgot_password(payload: EmployerForgotPasswordIn, request: Request):
    """
    Request a password-reset email.

    Unlike employer_register()'s honest 409, this DOES answer the same way
    whether or not the address has an account — the two endpoints made
    opposite trade-offs on purpose. Register's 409 costs an enumeration
    signal register()'s own docstring judges cheap (most of these addresses
    are already semi-public on a company careers page); a forgot-password
    endpoint that confirms "no account" is a stronger signal for the same
    cost, and unlike register there is no fake-success value being lost —
    nobody expects a substantive response from this one either way.
    """
    email = employers_store.normalise_email(payload.email)
    ip = _client_ip(request)
    if _auth_rate_limited(request, f"emp-reset:email:{email}", limit=3, window_s=3600) or \
       _auth_rate_limited(request, f"emp-reset:ip:{ip}", limit=10, window_s=3600):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")

    store = employers_store.get_store()
    row = store.get_employer_by_email(email)
    if row is not None:
        raw_token = auth.issue_email_token(store, row["id"], purpose="reset")
        _send_employer_mail(
            request,
            email,
            "Reset your password — FinEx Careers",
            f"Reset your FinEx Careers employer password:\n\n"
            f"{_account_link_url(request, 'employer/reset-password', raw_token)}\n\n"
            f"This link works once and expires in an hour. If you did not request this, "
            f"you can ignore this message — your password has not changed.",
        )
    return SubmitResponse(ok=True)


class EmployerResetPasswordIn(BaseModel):
    token: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8, max_length=200)


@router.post("/api/employer/auth/reset-password", response_model=EmployerOut, tags=["employer"])
def employer_reset_password(payload: EmployerResetPasswordIn, request: Request, response: Response):
    """Spend a reset token, set the new password, sign out every other
    session, and sign the caller back in. Same shape as Seeker's
    reset_password() — see that docstring."""
    store = employers_store.get_store()
    employer_id = auth.consume_email_token(store, payload.token, purpose="reset")
    if employer_id is None:
        raise HTTPException(status_code=400, detail="This link is no longer valid.")

    store.set_password_hash(employer_id, auth.hash_password(payload.password))
    auth.revoke_all_sessions(store, employer_id)
    store.log_event("employer.password_reset", employer_id=employer_id)

    _set_employer_session_cookie(request, response, auth.issue_session(
        store, employer_id, user_agent=request.headers.get("user-agent")))
    return _employer_out(store.get_employer(employer_id))


@router.post("/api/employer/logout", status_code=204, tags=["employer"])
def employer_logout(request: Request, response: Response):
    """Always 204. Logging out of a session you don't have is not an error."""
    auth.revoke_session(employers_store.get_store(), request.cookies.get(EMPLOYER_SESSION_COOKIE))
    _clear_employer_session_cookie(response)
    return Response(status_code=204)


@router.get("/api/employer/me", response_model=EmployerOut, tags=["employer"])
def employer_whoami(request: Request):
    return _employer_out(_require_employer(request))


@router.delete("/api/employer/me", status_code=204, tags=["employer"])
def employer_delete_account(request: Request, response: Response):
    """Real delete, same posture as Seeker deletion (ADR 0007's reasoning
    applies here too: an Employer's own account is not a Role — CLAUDE.md's
    soft-delete rule does not cover it)."""
    employer = _require_employer(request)
    employers_store.get_store().delete_employer(employer["id"])
    _clear_employer_session_cookie(response)
    logger.info("Employer %s deleted their account", employer["id"])
    return Response(status_code=204)


# ── Employer Google sign-in ─────────────────────────────────────────────────
#
# Reuses GOOGLE_AUTH_URL / GOOGLE_TOKEN_URL / GOOGLE_TOKENINFO_URL /
# _google_configured() from the Seeker Google section above — the exchange
# mechanics (delegate signature verification to Google's tokeninfo endpoint,
# ADR 0004) do not differ by account type, only what happens with the result
# does. That is why this is a SEPARATE registered redirect URI
# (/api/employer/auth/google/callback) rather than reusing the Seeker one
# with a query flag: Google's own consent screen enforces an exact match
# against a URI actually registered on the OAuth client, so branching inside
# one callback would still need two URIs registered anyway, and a wrong
# branch there is exactly the kind of bug worth making structurally
# impossible instead of tested for.
#
# WHAT THIS NEEDS, same as the Seeker version: GOOGLE_CLIENT_ID/SECRET are
# shared (one OAuth client serves both), but the REDIRECT URI below must be
# separately registered on that client in Google Cloud Console, or Google
# rejects the callback before this code ever runs.

EMPLOYER_GOOGLE_STATE_COOKIE = "google_employer_oauth_state"
EMPLOYER_GOOGLE_STATE_COOKIE_PATH = "/api/employer/auth/google"


def _employer_google_redirect_uri(request: Request) -> str:
    override = os.environ.get("EMPLOYER_GOOGLE_REDIRECT_URI", "").strip()
    return override or f"{_public_base(request)}/api/employer/auth/google/callback"


def _employer_google_failure_redirect(request: Request, reason: str) -> RedirectResponse:
    logger.warning("Employer Google sign-in did not complete: %s", reason)
    resp = RedirectResponse(f"{_public_base(request)}/employer/signin?error=google_failed")
    resp.delete_cookie(EMPLOYER_GOOGLE_STATE_COOKIE, path=EMPLOYER_GOOGLE_STATE_COOKIE_PATH)
    return resp


@router.get("/api/employer/auth/google", tags=["employer"], include_in_schema=False)
def employer_google_start(request: Request):
    """Redirect to Google's consent screen. Same shape as google_start() —
    see that docstring for why this must be a real navigation, not a fetch."""
    try:
        authorization = request.app.state.identity_protocol.begin(
            "google", _employer_google_redirect_uri(request)
        )
    except identity_protocol.ProviderUnavailable:
        logger.warning(
            "GET /api/employer/auth/google called but GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET "
            "are not set"
        )
        return RedirectResponse(f"{_public_base(request)}/employer/signin?error=google_unavailable")

    resp = RedirectResponse(authorization.url)
    resp.set_cookie(
        EMPLOYER_GOOGLE_STATE_COOKIE,
        authorization.state,
        max_age=600,
        httponly=True,
        secure=cfg(request).cookie_secure,
        samesite="lax",
        path=EMPLOYER_GOOGLE_STATE_COOKIE_PATH,
    )
    return resp


@router.get("/api/employer/auth/google/callback", tags=["employer"], include_in_schema=False)
def employer_google_callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
):
    """
    Exchange the code, verify the identity token, and hand the result to
    auth.link_or_create_employer — which, unlike the Seeker version, can only
    recognise or link, never create (see that function's docstring for why).
    """
    try:
        claim = request.app.state.identity_protocol.complete(
            "google",
            _employer_google_redirect_uri(request),
            identity_protocol.Callback(
                code=code,
                state=state,
                cookie_state=request.cookies.get(EMPLOYER_GOOGLE_STATE_COOKIE),
                error=error,
            ),
        )
    except identity_protocol.ProviderUnavailable:
        logger.warning(
            "Employer Google callback reached but GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET "
            "are not set"
        )
        resp = RedirectResponse(f"{_public_base(request)}/employer/signin?error=google_unavailable")
        resp.delete_cookie(EMPLOYER_GOOGLE_STATE_COOKIE, path=EMPLOYER_GOOGLE_STATE_COOKIE_PATH)
        return resp
    except identity_protocol.IdentityProtocolError as exc:
        return _employer_google_failure_redirect(request, str(exc))

    store = employers_store.get_store()
    try:
        result = auth.link_or_create_employer(store, claim)
    except auth.IdentityLinkRefused as exc:
        logger.warning(
            "Employer Google identity link refused for subject %s: %s", claim.subject, exc
        )
        target = f"{_public_base(request)}/employer/register?error=google_link_refused"
        resp = RedirectResponse(target)
        resp.delete_cookie(EMPLOYER_GOOGLE_STATE_COOKIE, path=EMPLOYER_GOOGLE_STATE_COOKIE_PATH)
        return resp

    store.touch_last_login(result.employer_id)
    store.log_event(f"employer.google_{result.outcome}", employer_id=result.employer_id)

    resp = RedirectResponse(f"{_public_base(request)}/post-a-role")
    resp.delete_cookie(EMPLOYER_GOOGLE_STATE_COOKIE, path=EMPLOYER_GOOGLE_STATE_COOKIE_PATH)
    _set_employer_session_cookie(request, resp, auth.issue_session(
        store, result.employer_id, user_agent=request.headers.get("user-agent")))
    return resp


def _trigger_weekly_alerts(request: Request) -> None:
    """
    Run the weekly Alerts job (alerts.py), as a BackgroundTask fired by
    admin.py right after a pipeline snapshot is ingested.

    This is the ONLY place run_weekly_alerts is called. It is not a cron
    phase in hk_jobs/daily_run/ because that orchestration runs on a GitHub
    Actions runner (the `hosted` profile), which never touches seekers.db —
    only this Railway process does, on the same volume as the jobs.db that
    `/api/admin/pipeline/database` just finished swapping in. Piggybacking on
    that publish is what gives Alerts its "once per pipeline run" cadence
    without a second scheduler.

    Gated on settings.alerts_enabled, OFF by default: the feature is fully
    built and wired end to end, but sends nothing until that flag is turned on
    — an environment change (ALERTS_ENABLED=1), not a deploy.

    Never raises. A background task's exception has nowhere to go but the log
    — and Alerts failing must never be mistaken for the publish itself having
    failed, since by the time this runs the publish has already succeeded and
    returned its response.
    """
    settings = cfg(request)
    if not settings.alerts_enabled:
        return
    public_base_url = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    if not public_base_url:
        logger.warning(
            "ALERTS_ENABLED is set but PUBLIC_BASE_URL is not configured — "
            "skipping this week's Alerts run entirely rather than mail links that 404"
        )
        return
    try:
        with sqlite3.connect(settings.jobs_db) as conn:
            job_read.prepare(conn)
            outcomes = alerts.run_weekly_alerts(
                conn,
                request.app.state.sender,
                request.app.state.alert_unsubscribe_tokens,
                public_base_url=public_base_url,
            )
        sent = sum(1 for outcome in outcomes if outcome.sent)
        logger.info("Weekly Alerts run: %d sent of %d attempted", sent, len(outcomes))
    except Exception:  # noqa: BLE001 — must never surface past a background task
        logger.exception("Weekly Alerts run failed")


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
    def spa_fallback(full_path: str, request: Request):
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
        # deleted JS file and the app boots to a blank page. It is also the one
        # file we rewrite per route — see _shell_response.
        return _shell_response(request, settings, "/" + full_path)


def create_app(
    settings: Settings | None = None,
    *,
    sender: Sender | None = None,
    notifier: SubmissionNotifier | None = None,
    external_identity: identity_protocol.IdentityProtocol | None = None,
    role_access_control: role_access.RoleAccess | None = None,
    alert_unsubscribe_tokens: alert_unsubscribe.AlertUnsubscribeToken | None = None,
) -> FastAPI:
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
    # Same shape, for the Role-submission moderation email — see sender.py's
    # "Sending the Role-submission moderation email" section for why this seam
    # exists: SmtpSubmissionNotifier by default, RecordingSubmissionNotifier in
    # tests via support.make_app().
    notifier = notifier if notifier is not None else SmtpSubmissionNotifier()
    external_identity = external_identity or identity_protocol.IdentityProtocol()
    role_access_control = role_access_control or role_access.RoleAccess(
        settings.role_access_secret
    )
    alert_unsubscribe_tokens = alert_unsubscribe_tokens or alert_unsubscribe.AlertUnsubscribeToken(
        settings.alert_unsubscribe_secret
    )

    app = FastAPI(
        title="FinEx Careers API",
        description="Read-only API for Hong Kong financial job listings.",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.sender = sender
    app.state.notifier = notifier
    app.state.identity_protocol = external_identity
    app.state.role_access = role_access_control
    app.state.alert_unsubscribe_tokens = alert_unsubscribe_tokens
    # Per-app, so two apps in one process (which is what the tests build) cannot
    # share a rate-limit budget. Redis-backed once settings.redis_url is set —
    # see Settings.redis_url and rate_limit.py for why that matters once this
    # runs on more than one replica.
    app.state.limiter = (
        RedisRateLimiter(settings.redis_url) if settings.redis_url else RateLimiter()
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        # POST is required by /api/post-role and account actions — without it the
        # browser blocks the preflight before requests reach FastAPI.
        # DELETE joins the list for account/profile removal; PATCH is used by the
        # recommendation preference centre. At one origin CORS is inert, but a dev
        # frontend pointed at an absolute API URL still preflights, and a missing
        # method fails there only.
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["*"],
    )

    app.include_router(router)
    app.include_router(
        admin.build_router(
            cfg=cfg, get_db=get_db, get_write_db=get_write_db,
            require_admin=_require_admin, require_super_admin=_require_super_admin,
            on_pipeline_published=_trigger_weekly_alerts,
        )
    )
    _mount_frontend(app, settings)
    return app


# The process-wide app, for `uvicorn main:app` (Procfile, railway.json). One
# ordinary caller of the factory, not a special case.
app = create_app()
