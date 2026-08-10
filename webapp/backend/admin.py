"""
Admin Mode — the HTTP surface signed-in admins get that an ordinary Seeker
does not: the recruiter-submission queue (Verification), today's pipeline run,
a deep read-only analytics pass over jobs.db, and — for Ultimate Admin only —
direct read/write onto a single job's row and its enrichment.

Every human-facing route here sits behind `require_admin` (the job_edit routes
ALSO sit behind `require_super_admin`), both dependencies main.py hands to
`build_router()`.  The machine-facing `/pipeline/database` and
`/pipeline/snapshot` routes use a separate timing-safe shared secret so the
scheduled GitHub pipeline can publish its catalogue and completed daily facts
without possessing a human session.

Writes to jobs.db are limited to submission approval, Ultimate Admin job edits,
and the authenticated daily publication routes described above. All other
dashboard queries use the read-only `get_db` connection.

Several queries below touch `job_history` / `company_metrics`, tables the
pipeline (hk_jobs/migrations.py, phase 11) creates but this backend never
migrates itself and a bare test stand-in (tests/support.py) never seeds. Every
one of those queries is wrapped in `_scalar`/`_rows`, which returns a safe
default instead of raising — a fresh or stand-in database must show an empty
dashboard, never a 500.
"""

from __future__ import annotations

import hmac
import json
import re
import sqlite3
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

import job_edit
import pipeline_publish
import submissions
from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from job_read import BOARD_WHERE, SECTOR_SQL

#: Repo root, for the pipeline's log file — computed the same way settings.py
#: computes it, since admin.py sits at the same depth (webapp/backend/).
_REPO = Path(__file__).resolve().parent.parent.parent
_LOG_PATH = _REPO / "logs" / "daily_runs.log"

#: How much of the log to read from the end. Tail-only: the file runs past
#: 100k lines and grows forever, so reading it in full on every dashboard
#: load would make the one admin-only page the slowest thing this API does.
_LOG_TAIL_BYTES = 300_000

_RUN_STARTED_RE = re.compile(r"===\s*Daily pipeline started\s*===")
_RUN_FINISHED_RE = re.compile(r"===\s*Daily pipeline finished\s*===")
_PHASE_RE = re.compile(r"^\[[\d\- :]+\]\s*(Phase .+|=== .+ ===)\s*$")
_HONG_KONG = ZoneInfo("Asia/Hong_Kong")

_JOB_HISTORY_DDL = """
CREATE TABLE IF NOT EXISTS job_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id TEXT NOT NULL,
    company_name TEXT NOT NULL,
    job_count INTEGER NOT NULL,
    scraped_date DATE NOT NULL,
    trend_direction TEXT,
    trend_percent REAL,
    jobs_added INTEGER,
    jobs_removed INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (company_id, scraped_date)
)
"""

_PIPELINE_SYNC_DDL = """
CREATE TABLE IF NOT EXISTS pipeline_snapshot_sync (
    scraped_date DATE PRIMARY KEY,
    received_at TEXT NOT NULL,
    company_count INTEGER NOT NULL,
    total_jobs INTEGER NOT NULL,
    source_run_url TEXT
)
"""


def _hong_kong_today() -> date:
    """The operating day shown to FinEx admins, independent of server region."""
    return datetime.now(_HONG_KONG).date()


def _scalar(conn: sqlite3.Connection, sql: str, *params: Any, default: Any = 0) -> Any:
    """Run a query expecting one column, one row. `default` on ANY failure —
    missing table, missing column, whatever — never a 500 for optional data."""
    try:
        row = conn.execute(sql, params).fetchone()
        return row[0] if row and row[0] is not None else default
    except sqlite3.Error:
        return default


def _rows(conn: sqlite3.Connection, sql: str, *params: Any) -> list[sqlite3.Row]:
    """Same guard as `_scalar`, for queries returning several rows."""
    try:
        return conn.execute(sql, params).fetchall()
    except sqlite3.Error:
        return []


# ── Today's run ────────────────────────────────────────────────────────────────


def _tail_log() -> dict[str, Any]:
    """
    Best-effort read of the pipeline's own log file — the one piece of "did
    today's run actually happen" signal this backend does not otherwise have,
    since (per this module's docstring) it never migrates or writes job_history
    itself. Absent file, unreadable file, or no run marker at all: every field
    comes back None/empty rather than raising, because a log file is
    operational furniture, not something a dashboard should die over.
    """
    if not _LOG_PATH.is_file():
        return {"available": False}

    try:
        size = _LOG_PATH.stat().st_size
        with open(_LOG_PATH, "rb") as fh:
            if size > _LOG_TAIL_BYTES:
                fh.seek(size - _LOG_TAIL_BYTES)
            tail = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return {"available": False}

    lines = tail.splitlines()

    start_idx = None
    for i in range(len(lines) - 1, -1, -1):
        if _RUN_STARTED_RE.search(lines[i]):
            start_idx = i
            break

    if start_idx is None:
        return {"available": True, "last_run_found": False}

    after = lines[start_idx:]
    finished = any(_RUN_FINISHED_RE.search(line) for line in after)
    crashed = not finished and any("Traceback (most recent call last)" in line for line in after)
    phases = [m.group(1) for line in after if (m := _PHASE_RE.match(line))]

    return {
        "available": True,
        "last_run_found": True,
        "finished": finished,
        "crashed": crashed,
        "last_phase": phases[-1] if phases else None,
        "phases_seen": phases,
    }


def _run_today(conn: sqlite3.Connection) -> dict[str, Any]:
    """Everything answering "did the pipeline run today, and how did it go?" """
    day = _hong_kong_today().isoformat()
    active = _scalar(conn, "SELECT COUNT(*) FROM jobs WHERE is_active=1")
    companies_active = _scalar(
        conn, "SELECT COUNT(DISTINCT company_slug) FROM jobs WHERE is_active=1"
    )

    scraped_today = _scalar(conn, "SELECT COUNT(*) FROM job_history WHERE scraped_date = ?", day)
    zero_today = _scalar(
        conn,
        "SELECT COUNT(*) FROM job_history WHERE scraped_date = ? AND job_count = 0",
        day,
    )
    jobs_added_today = _scalar(
        conn, "SELECT SUM(jobs_added) FROM job_history WHERE scraped_date = ?", day
    )
    jobs_removed_today = _scalar(
        conn, "SELECT SUM(jobs_removed) FROM job_history WHERE scraped_date = ?", day
    )
    listings_collected_today = _scalar(
        conn, "SELECT SUM(job_count) FROM job_history WHERE scraped_date = ?", day
    )
    zero_companies = [
        r["company_name"]
        for r in _rows(
            conn,
            """
            SELECT h.company_name
            FROM job_history h
            LEFT JOIN (SELECT company_id, MAX(job_count) peak
                       FROM job_history GROUP BY company_id) p
                   ON p.company_id = h.company_id
            WHERE h.scraped_date = ? AND h.job_count = 0
            ORDER BY COALESCE(p.peak, 0) DESC, h.company_name
            LIMIT 20
            """,
            day,
        )
    ]

    snapshot_received_at = _scalar(
        conn,
        "SELECT received_at FROM pipeline_snapshot_sync WHERE scraped_date = ?",
        day,
        default=None,
    )

    desc_pct = _scalar(
        conn,
        "SELECT ROUND(100.0 * SUM(description_clean <> '') / COUNT(*), 1) "
        "FROM jobs WHERE is_active = 1",
        default=0.0,
    )
    enrich_pct = _scalar(
        conn,
        """
        SELECT ROUND(100.0 * COUNT(*) /
            (SELECT COUNT(*) FROM jobs WHERE is_active = 1), 1)
        FROM job_enrichments e JOIN jobs j
          ON j.source = e.source AND j.source_id = e.source_id
        WHERE j.is_active = 1
        """,
        default=0.0,
    )

    return {
        "date": day,
        "ran_today": bool(scraped_today),
        "snapshot_received_at": snapshot_received_at,
        "companies_scraped_today": scraped_today,
        "companies_zero_today": zero_today,
        "zero_companies": zero_companies,
        "jobs_added_today": jobs_added_today or 0,
        "jobs_removed_today": jobs_removed_today or 0,
        "listings_collected_today": listings_collected_today or 0,
        "active_jobs": active,
        "companies_active": companies_active,
        "description_coverage_pct": desc_pct,
        "enrichment_coverage_pct": enrich_pct,
        "log": _tail_log(),
    }


def _run_history(conn: sqlite3.Connection, days: int) -> list[dict[str, Any]]:
    """Daily totals for broadly-covered scrape days, for a time-series chart.

    Probe/aborted days with only a handful of companies are operational events,
    not market observations. Keeping them in the series manufactured a plunge
    from ~1,800 listings to 10 on a one-company day. The 80% rule matches
    `_market_movers`, so every time comparison on the page uses the same cohort
    quality threshold.
    """
    since = (_hong_kong_today() - timedelta(days=days)).isoformat()
    rows = _rows(
        conn,
        """
        WITH daily AS (
          SELECT scraped_date,
                 SUM(job_count) AS total_jobs,
                 COUNT(*) AS companies_scraped,
                 SUM(CASE WHEN job_count = 0 THEN 1 ELSE 0 END) AS companies_down
          FROM job_history
          WHERE scraped_date >= ?
          GROUP BY scraped_date
        )
        SELECT scraped_date, total_jobs, companies_scraped, companies_down
        FROM daily
        WHERE companies_scraped >= 0.8 * (SELECT MAX(companies_scraped) FROM daily)
        ORDER BY scraped_date
        """,
        since,
    )
    return [dict(r) for r in rows]


# ── Analytics overview ────────────────────────────────────────────────────────


def _herfindahl(shares_pct: list[float]) -> float:
    """
    Herfindahl-Hirschman Index over market-share percentages (0-100 each).
    Standard concentration measure: sum of squared shares. 10,000 is one
    company holding the entire board; below ~1,500 is usually called
    unconcentrated. Matches the definition already used in
    docs/ (HK Market Evidence Report) so the two numbers are comparable.
    """
    return round(sum(s * s for s in shares_pct), 1)


def _salary_bucket_label(mid_k: float) -> str:
    edges = [20, 40, 60, 80, 100, 150]
    labels = ["<20k", "20-40k", "40-60k", "60-80k", "80-100k", "100-150k", "150k+"]
    for edge, label in zip(edges, labels):
        if mid_k < edge:
            return label
    return labels[-1]


def _pct(part: int | float, whole: int | float) -> float:
    """One-decimal percentage with the zero-denominator policy in one place."""
    return round(100.0 * part / whole, 1) if whole else 0.0


def _percentile(values: list[float], percentile: float) -> int:
    """
    Linear-interpolated percentile, matching the common spreadsheet definition.

    SQLite does not ship a percentile aggregate, and loading a few thousand
    salary midpoints is both clearer and cheaper than adding an analytics
    dependency to the admin-only endpoint.
    """
    if not values:
        return 0
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight)


def _market_movers(conn: sqlite3.Connection) -> dict[str, Any]:
    """
    Biggest inventory moves between the latest two broadly-complete scrape days.

    A one-company probe occasionally lands in job_history. Comparing against it
    would manufacture spectacular, meaningless growth, so a usable day must have
    at least 80% of the best coverage recorded anywhere in the table.
    """
    dates = _rows(
        conn,
        """
        WITH daily AS (
          SELECT scraped_date, COUNT(*) AS companies
          FROM job_history GROUP BY scraped_date
        )
        SELECT scraped_date, companies
        FROM daily
        WHERE companies >= 0.8 * (SELECT MAX(companies) FROM daily)
        ORDER BY scraped_date DESC
        LIMIT 2
        """,
    )
    if len(dates) < 2:
        return {"current_date": None, "comparison_date": None, "gainers": [], "decliners": []}

    current_date, comparison_date = dates[0]["scraped_date"], dates[1]["scraped_date"]
    rows = _rows(
        conn,
        """
        SELECT cur.company_name AS name,
               cur.job_count AS current,
               prev.job_count AS previous,
               cur.job_count - prev.job_count AS change
        FROM job_history cur
        JOIN job_history prev ON prev.company_id = cur.company_id
        WHERE cur.scraped_date = ? AND prev.scraped_date = ?
        """,
        current_date,
        comparison_date,
    )

    def item(row: sqlite3.Row) -> dict[str, Any]:
        previous = row["previous"]
        return {
            "name": row["name"],
            "current": row["current"],
            "previous": previous,
            "change": row["change"],
            "change_pct": _pct(row["change"], previous) if previous else None,
        }

    gainers = sorted((r for r in rows if r["change"] > 0), key=lambda r: r["change"], reverse=True)
    decliners = sorted((r for r in rows if r["change"] < 0), key=lambda r: r["change"])
    return {
        "current_date": current_date,
        "comparison_date": comparison_date,
        "gainers": [item(r) for r in gainers[:6]],
        "decliners": [item(r) for r in decliners[:6]],
    }


def _analytics_overview(conn: sqlite3.Connection) -> dict[str, Any]:
    total_active_all = _scalar(conn, "SELECT COUNT(*) FROM jobs WHERE is_active=1")
    total_board = _scalar(conn, f"SELECT COUNT(*) FROM jobs j WHERE {BOARD_WHERE}")
    cross_posted_rows = max(0, total_active_all - total_board)
    cross_posting_rate_pct = (
        round(100.0 * cross_posted_rows / total_active_all, 1) if total_active_all else 0.0
    )

    by_source = {
        r["source"]: r["cnt"]
        for r in _rows(
            conn,
            "SELECT source, COUNT(*) AS cnt FROM jobs WHERE is_active=1 "
            "GROUP BY source ORDER BY cnt DESC",
        )
    }

    # The source that owns each visible card after cross-post reconciliation.
    # This is the honest market-facing source mix; `by_source` above remains the
    # operational listing volume, including suppressed copies.
    by_board_source = {
        r["source"]: r["cnt"]
        for r in _rows(
            conn,
            f"SELECT source, COUNT(*) AS cnt FROM jobs j WHERE {BOARD_WHERE} "
            "GROUP BY source ORDER BY cnt DESC",
        )
    }

    by_sector = {
        r["sector"]: r["cnt"]
        for r in _rows(
            conn,
            f"""
            SELECT sector, COUNT(*) AS cnt FROM (
              SELECT ({SECTOR_SQL}) AS sector FROM jobs j WHERE {BOARD_WHERE}
            ) sub GROUP BY sector ORDER BY cnt DESC
            """,
        )
    }

    by_seniority = {
        r["seniority"]: r["cnt"]
        for r in _rows(
            conn,
            "SELECT e.seniority, COUNT(*) AS cnt FROM job_enrichments e "
            "JOIN jobs j ON j.source=e.source AND j.source_id=e.source_id "
            f"WHERE {BOARD_WHERE} AND e.seniority IS NOT NULL "
            "GROUP BY e.seniority ORDER BY cnt DESC",
        )
    }

    by_remote_type = {
        r["remote_type"]: r["cnt"]
        for r in _rows(
            conn,
            "SELECT e.remote_type, COUNT(*) AS cnt FROM job_enrichments e "
            "JOIN jobs j ON j.source=e.source AND j.source_id=e.source_id "
            f"WHERE {BOARD_WHERE} AND e.remote_type IS NOT NULL "
            "GROUP BY e.remote_type ORDER BY cnt DESC",
        )
    }

    # Company concentration (HHI) over every company on the board, not just the
    # top 15 the public /api/stats shows — a concentration index computed on a
    # truncated top-N would understate concentration whenever the tail is long.
    # Concentration must operate on a canonical employer key. Display names
    # contain variants ("HSBC" / "HSBC Hong Kong") that split one employer and
    # materially understate HHI. Production has company_slug; the reduced test
    # stand-in intentionally does not, so retain a display-name fallback there.
    job_columns = {row[1] for row in _rows(conn, "PRAGMA table_info(jobs)")}
    if "company_slug" in job_columns:
        raw_company_rows = _rows(
            conn,
            f"SELECT j.company_slug, j.company, COUNT(*) AS cnt FROM jobs j "
            f"WHERE {BOARD_WHERE} GROUP BY j.company_slug, j.company",
        )
        canonical: dict[str, dict[str, Any]] = {}
        for row in raw_company_rows:
            slug = row["company_slug"] or row["company"]
            item = canonical.setdefault(slug, {"cnt": 0, "names": Counter()})
            item["cnt"] += row["cnt"]
            item["names"][row["company"]] += row["cnt"]
        company_rows = [
            {"company": item["names"].most_common(1)[0][0], "cnt": item["cnt"]}
            for item in canonical.values()
        ]
    else:
        company_rows = [
            dict(row)
            for row in _rows(
                conn,
                f"SELECT j.company, COUNT(*) AS cnt FROM jobs j "
                f"WHERE {BOARD_WHERE} GROUP BY j.company",
            )
        ]
    company_shares = [100.0 * r["cnt"] / total_board for r in company_rows] if total_board else []
    top_companies = [
        {"name": r["company"], "count": r["cnt"]}
        for r in sorted(company_rows, key=lambda r: -r["cnt"])[:12]
    ]
    top5_share_pct = (
        round(
            100.0 * sum(sorted((r["cnt"] for r in company_rows), reverse=True)[:5]) / total_board,
            1,
        )
        if total_board
        else 0.0
    )
    concentration_hhi = _herfindahl(company_shares)

    # Salary distribution: midpoint of the estimated range, bucketed in HK$/month
    # thousands. Board-visible rows only — a duplicate suppressed by is_primary
    # would double-count the same real vacancy's salary.
    salary_rows = _rows(
        conn,
        f"""
        SELECT ({SECTOR_SQL}) AS sector,
               e.salary_estimated_min AS smin, e.salary_estimated_max AS smax
        FROM job_enrichments e JOIN jobs j
          ON j.source = e.source AND j.source_id = e.source_id
        WHERE {BOARD_WHERE} AND e.salary_estimated_min IS NOT NULL
          AND e.salary_estimated_max IS NOT NULL
        """,
    )
    salary_hist: Counter[str] = Counter()
    salary_midpoints: list[float] = []
    salary_by_sector: dict[str, list[float]] = {}
    for r in salary_rows:
        midpoint = (r["smin"] + r["smax"]) / 2
        salary_midpoints.append(midpoint)
        salary_by_sector.setdefault(r["sector"], []).append(midpoint)
        mid_k = midpoint / 1000
        salary_hist[_salary_bucket_label(mid_k)] += 1

    sector_salary = [
        {
            "name": sector,
            "median_hkd": _percentile(values, 0.5),
            "p25_hkd": _percentile(values, 0.25),
            "p75_hkd": _percentile(values, 0.75),
            "sample_size": len(values),
        }
        for sector, values in salary_by_sector.items()
        if len(values) >= 10
    ]
    sector_salary.sort(key=lambda item: item["median_hkd"], reverse=True)

    confidence_rows = _rows(
        conn,
        f"""
        SELECT COALESCE(e.salary_estimated_confidence, 'unknown') AS conf, COUNT(*) AS cnt
        FROM job_enrichments e JOIN jobs j
          ON j.source = e.source AND j.source_id = e.source_id
        WHERE {BOARD_WHERE} AND e.salary_estimated_min IS NOT NULL
          AND e.salary_estimated_max IS NOT NULL
        GROUP BY conf
        """,
    )
    salary_confidence = {r["conf"]: r["cnt"] for r in confidence_rows}

    # Required-skills output is a JSON array. Case-fold before counting: model
    # output contains e.g. "Stakeholder management", "Stakeholder Management"
    # and lowercase variants, which are one signal, not three skills.
    skill_counts: Counter[str] = Counter()
    skill_spellings: dict[str, Counter[str]] = {}
    roles_with_skills = 0
    for row in _rows(
        conn,
        "SELECT e.required_skills FROM job_enrichments e JOIN jobs j "
        "ON j.source=e.source AND j.source_id=e.source_id "
        f"WHERE {BOARD_WHERE}",
    ):
        try:
            skills = json.loads(row["required_skills"] or "[]")
        except (TypeError, json.JSONDecodeError):
            continue
        unique: dict[str, str] = {}
        if isinstance(skills, list):
            for raw in skills:
                spelling = re.sub(r"\s+", " ", str(raw)).strip()
                if spelling:
                    unique.setdefault(spelling.casefold(), spelling)
        if not unique:
            continue
        roles_with_skills += 1
        for key, spelling in unique.items():
            skill_counts[key] += 1
            skill_spellings.setdefault(key, Counter())[spelling] += 1

    top_skills = []
    for key, count in skill_counts.most_common(12):
        spelling = skill_spellings[key].most_common(1)[0][0]
        top_skills.append({"name": spelling, "count": count, "share_pct": _pct(count, total_board)})

    sector_total = sum(by_sector.values())
    dominant_sector_name, dominant_sector_count = (
        min(by_sector.items(), key=lambda item: (-item[1], item[0])) if by_sector else ("", 0)
    )
    remote_classified = sum(by_remote_type.values())
    remote_friendly = sum(
        count for name, count in by_remote_type.items() if name.casefold() in {"remote", "hybrid"}
    )
    description_count = _scalar(
        conn,
        f"SELECT COUNT(*) FROM jobs j WHERE {BOARD_WHERE} AND TRIM(j.description_clean) <> ''",
    )
    enrichment_count = _scalar(
        conn,
        "SELECT COUNT(*) FROM job_enrichments e JOIN jobs j "
        "ON j.source=e.source AND j.source_id=e.source_id "
        f"WHERE {BOARD_WHERE}",
    )

    return {
        "total_board_roles": total_board,
        "total_active_rows": total_active_all,
        "cross_posting_rate_pct": cross_posting_rate_pct,
        "duplicate_rows_suppressed": cross_posted_rows,
        "by_source": by_source,
        "by_board_source": by_board_source,
        "by_sector": by_sector,
        "by_seniority": by_seniority,
        "by_remote_type": by_remote_type,
        "top_companies": top_companies,
        "company_concentration_hhi": concentration_hhi,
        "company_concentration_label": (
            "concentrated"
            if concentration_hhi >= 2500
            else "moderately concentrated"
            if concentration_hhi >= 1500
            else "unconcentrated"
        ),
        "company_entity_count": len(company_rows),
        "top5_company_share_pct": top5_share_pct,
        "salary_distribution": dict(salary_hist),
        "salary_confidence": salary_confidence,
        "salary_median_hkd": _percentile(salary_midpoints, 0.5),
        "salary_p25_hkd": _percentile(salary_midpoints, 0.25),
        "salary_p75_hkd": _percentile(salary_midpoints, 0.75),
        "salary_sample_size": len(salary_midpoints),
        "sector_salary": sector_salary,
        "top_skills": top_skills,
        "dominant_sector": {
            "name": dominant_sector_name,
            "count": dominant_sector_count,
            "share_pct": _pct(dominant_sector_count, sector_total),
        },
        "remote_friendly_pct": _pct(remote_friendly, remote_classified),
        "data_quality": {
            "description_coverage_pct": _pct(description_count, total_board),
            "enrichment_coverage_pct": _pct(enrichment_count, total_board),
            "salary_coverage_pct": _pct(len(salary_midpoints), total_board),
            "high_confidence_salary_pct": _pct(
                salary_confidence.get("high", 0), len(salary_midpoints)
            ),
            "skills_coverage_pct": _pct(roles_with_skills, total_board),
            "seniority_coverage_pct": _pct(sum(by_seniority.values()), total_board),
            "workplace_coverage_pct": _pct(remote_classified, total_board),
        },
        "market_movers": _market_movers(conn),
    }


# ── Router ─────────────────────────────────────────────────────────────────────


def build_router(
    *,
    cfg: Callable[[Request], Any],
    get_db: Callable[[Request], sqlite3.Connection],
    get_write_db: Callable[[Request], sqlite3.Connection],
    require_admin: Callable[[Request], dict],
    require_super_admin: Callable[[Request], dict],
) -> APIRouter:
    """
    Assemble the admin router against main.py's own dependencies.

    Taking them as arguments (rather than importing main.py) is what keeps this
    module free of the one import that would make it circular: main.py imports
    THIS module to mount the router, so this module cannot import main.py back.
    """
    router = APIRouter(prefix="/api/admin", tags=["admin"])

    def _queue_path(request: Request) -> Path:
        return cfg(request).submissions_dir / "submitted_roles.jsonl"

    def _require_pipeline_token(request: Request, supplied: str | None) -> None:
        expected = cfg(request).pipeline_sync_token
        if not expected:
            raise HTTPException(status_code=503, detail="Pipeline sync is disabled")
        if not supplied or not hmac.compare_digest(supplied, expected):
            raise HTTPException(status_code=401, detail="Invalid pipeline sync token")

    @router.post("/pipeline/database")
    def ingest_pipeline_database(
        request: Request,
        snapshot: UploadFile = File(...),
        sync_token: str | None = Header(default=None, alias="X-Pipeline-Sync-Token"),
        source_run_id: str | None = Header(default=None, alias="X-Pipeline-Run-Id"),
        snapshot_sha256: str | None = Header(default=None, alias="X-Pipeline-Snapshot-SHA256"),
        source_run_url: str | None = Header(default=None, alias="X-Pipeline-Source-Url"),
    ):
        """Publish a completed, checksummed pipeline jobs.db into Railway."""
        _require_pipeline_token(request, sync_token)
        try:
            return pipeline_publish.publish_snapshot(
                Path(cfg(request).jobs_db),
                snapshot.file,
                expected_sha256=snapshot_sha256 or "",
                source_run_id=source_run_id or "",
                source_run_url=source_run_url,
            )
        except pipeline_publish.InvalidSnapshot as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        except pipeline_publish.PublishConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        except sqlite3.OperationalError as exc:
            raise HTTPException(
                status_code=503, detail="Catalogue publication is temporarily busy"
            ) from exc

    @router.post("/pipeline/snapshot")
    def ingest_pipeline_snapshot(
        request: Request,
        body: dict = Body(...),
        sync_token: str | None = Header(default=None, alias="X-Pipeline-Sync-Token"),
    ):
        """Upsert one completed daily pipeline snapshot from GitHub Actions."""
        _require_pipeline_token(request, sync_token)

        try:
            scraped_date = date.fromisoformat(str(body["scraped_date"])).isoformat()
        except (KeyError, TypeError, ValueError):
            raise HTTPException(
                status_code=400, detail="scraped_date must be ISO YYYY-MM-DD"
            ) from None

        companies = body.get("companies")
        if not isinstance(companies, list) or not 1 <= len(companies) <= 1000:
            raise HTTPException(status_code=400, detail="companies must contain 1-1000 rows")

        cleaned: list[tuple[Any, ...]] = []
        seen: set[str] = set()
        for row in companies:
            try:
                company_id = str(row["company_id"]).strip()
                company_name = str(row["company_name"]).strip()
                job_count = max(0, int(row["job_count"]))
                jobs_added = max(0, int(row.get("jobs_added") or 0))
                jobs_removed = max(0, int(row.get("jobs_removed") or 0))
                trend_direction = row.get("trend_direction")
                trend_percent = float(row.get("trend_percent") or 0)
            except (KeyError, TypeError, ValueError):
                raise HTTPException(
                    status_code=400, detail="Invalid company snapshot row"
                ) from None
            if not company_id or not company_name or company_id in seen:
                raise HTTPException(
                    status_code=400,
                    detail="Company IDs and names must be unique and non-empty",
                )
            seen.add(company_id)
            cleaned.append(
                (
                    company_id,
                    company_name,
                    job_count,
                    scraped_date,
                    trend_direction,
                    trend_percent,
                    jobs_added,
                    jobs_removed,
                )
            )

        received_at = datetime.now(_HONG_KONG).isoformat()
        with get_write_db(request) as conn:
            with conn:
                conn.execute(_JOB_HISTORY_DDL)
                conn.execute(_PIPELINE_SYNC_DDL)
                # A rerun is a complete replacement for the same operating
                # day. Deleting first prevents companies removed from the
                # pipeline configuration from surviving as stale rows.
                conn.execute("DELETE FROM job_history WHERE scraped_date = ?", (scraped_date,))
                conn.executemany(
                    """
                    INSERT INTO job_history
                        (company_id, company_name, job_count, scraped_date,
                         trend_direction, trend_percent, jobs_added, jobs_removed)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    cleaned,
                )
                conn.execute(
                    """
                    INSERT INTO pipeline_snapshot_sync
                        (scraped_date, received_at, company_count, total_jobs, source_run_url)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT (scraped_date) DO UPDATE SET
                        received_at=excluded.received_at,
                        company_count=excluded.company_count,
                        total_jobs=excluded.total_jobs,
                        source_run_url=excluded.source_run_url
                    """,
                    (
                        scraped_date,
                        received_at,
                        len(cleaned),
                        sum(row[2] for row in cleaned),
                        body.get("source_run_url"),
                    ),
                )

        return {
            "scraped_date": scraped_date,
            "companies": len(cleaned),
            "total_jobs": sum(row[2] for row in cleaned),
            "received_at": received_at,
        }

    # ── Recruiter submissions ───────────────────────────────────────────────

    @router.get("/submissions")
    def list_submissions(
        request: Request,
        status: str = Query("pending", pattern="^(pending|approved|rejected|all)$"),
        _admin: dict = Depends(require_admin),
    ):
        rows = submissions.load_queue(_queue_path(request))
        out = []
        for row in rows:
            row_status = row.get("status", "pending")
            if status != "all" and row_status != status:
                continue
            out.append({**row, "id": submissions.source_id_for(row), "status": row_status})
        # Newest first — that is what "latest requests" means to someone opening the tab.
        out.sort(key=lambda r: r.get("received_at", ""), reverse=True)
        return out

    @router.post("/submissions/{submission_id}/approve")
    def approve_submission_route(
        submission_id: str, request: Request, _admin: dict = Depends(require_admin)
    ):
        path = _queue_path(request)
        rows = submissions.load_queue(path)
        idx = submissions.find_by_source_id(rows, submission_id)
        if idx is None:
            raise HTTPException(status_code=404, detail="Submission not found")

        row = rows[idx]
        if row.get("status") == "approved":
            return {**row, "id": submission_id}

        try:
            sid = submissions.approve_submission(cfg(request).jobs_db, row)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"Could not publish role: {exc}") from None

        rows[idx] = submissions.mark_approved(row, sid)
        submissions.save_queue(path, rows)
        return {**rows[idx], "id": submission_id}

    @router.post("/submissions/{submission_id}/reject")
    def reject_submission_route(
        submission_id: str,
        request: Request,
        reason: str = Body("", embed=True),
        _admin: dict = Depends(require_admin),
    ):
        path = _queue_path(request)
        rows = submissions.load_queue(path)
        idx = submissions.find_by_source_id(rows, submission_id)
        if idx is None:
            raise HTTPException(status_code=404, detail="Submission not found")

        rows[idx] = submissions.mark_rejected(rows[idx], reason=reason)
        submissions.save_queue(path, rows)
        return {**rows[idx], "id": submission_id}

    # ── Today's run ─────────────────────────────────────────────────────────

    @router.get("/run/today")
    def run_today(request: Request, _admin: dict = Depends(require_admin)):
        with get_db(request) as conn:
            return _run_today(conn)

    @router.get("/run/history")
    def run_history(
        request: Request,
        days: int = Query(30, ge=1, le=365),
        _admin: dict = Depends(require_admin),
    ):
        with get_db(request) as conn:
            return {"days": days, "points": _run_history(conn, days)}

    # ── Analytics ───────────────────────────────────────────────────────────

    @router.get("/analytics/overview")
    def analytics_overview(request: Request, _admin: dict = Depends(require_admin)):
        with get_db(request) as conn:
            return _analytics_overview(conn)

    # ── Ultimate Admin: direct job edit ─────────────────────────────────────
    # Behind require_super_admin, not require_admin — the other four admins
    # never reach these two routes. See job_edit.py's module docstring for
    # the allowlist, the audit trail, and why every enrichment write here
    # marks the row against future automated correction.

    @router.get("/jobs/{source}/{source_id}")
    def get_job_route(
        source: str,
        source_id: str,
        request: Request,
        _admin: dict = Depends(require_super_admin),
    ):
        with get_write_db(request) as conn:
            try:
                return job_edit.get_job_for_edit(conn, source, source_id)
            except job_edit.JobNotFound:
                raise HTTPException(status_code=404, detail="Job not found") from None

    @router.patch("/jobs/{source}/{source_id}")
    def patch_job_route(
        source: str,
        source_id: str,
        request: Request,
        body: dict = Body(default={}),
        admin: dict = Depends(require_super_admin),
    ):
        job_changes = body.get("job") or {}
        enrichment_changes = body.get("enrichment") or {}
        with get_write_db(request) as conn:
            try:
                return job_edit.apply_edit(
                    conn,
                    source,
                    source_id,
                    admin["id"],
                    job_changes=job_changes,
                    enrichment_changes=enrichment_changes,
                )
            except job_edit.JobNotFound:
                raise HTTPException(status_code=404, detail="Job not found") from None
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from None

    return router
