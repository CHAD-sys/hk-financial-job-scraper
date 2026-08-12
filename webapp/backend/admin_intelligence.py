"""A coherent, evidence-aware read model for the FinEx admin intelligence desk.

The interface is one outcome: build_admin_intelligence(). It owns catalogue
metrics, Daily Run interpretation, operational health, market intelligence and
degradation semantics. HTTP transport and human authorization stay in admin.py.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import seekers_store
from job_read import BOARD_WHERE, SECTOR_SQL

from hk_jobs.daily_run.model import DailyRunRecord
from hk_jobs.daily_run.registry import profile_for

_REPO = Path(__file__).resolve().parent.parent.parent
_LOG_PATH = _REPO / "logs" / "daily_runs.log"
_LOG_TAIL_BYTES = 300_000
_RUN_STARTED_RE = re.compile(r"===\s*Daily pipeline started\s*===")
_RUN_FINISHED_RE = re.compile(r"===\s*Daily pipeline finished\s*===")
_PHASE_RE = re.compile(r"^\[[\d\- :]+\]\s*(Phase .+|=== .+ ===)\s*$")
_HONG_KONG = ZoneInfo("Asia/Hong_Kong")
_PHASE_KEYS = tuple((phase.key, phase.label) for phase in profile_for("hosted").phases)


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


def _run_today(conn: sqlite3.Connection, *, operating_day: date | None = None) -> dict[str, Any]:
    """Everything answering "did the pipeline run today, and how did it go?" """
    day = (operating_day or _hong_kong_today()).isoformat()
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
        "SELECT received_at FROM pipeline_catalog_sync "
        "WHERE date(received_at, '+8 hours') = ? "
        "ORDER BY received_at DESC LIMIT 1",
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


def _run_history(
    conn: sqlite3.Connection,
    days: int,
    *,
    operating_day: date | None = None,
) -> list[dict[str, Any]]:
    """Daily totals for broadly-covered scrape days, for a time-series chart.

    Probe/aborted days with only a handful of companies are operational events,
    not market observations. Keeping them in the series manufactured a plunge
    from ~1,800 listings to 10 on a one-company day. The 80% rule matches
    `_market_movers`, so every time comparison on the page uses the same cohort
    quality threshold.
    """
    since = ((operating_day or _hong_kong_today()) - timedelta(days=days)).isoformat()
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


def _operations_dashboard(
    conn: sqlite3.Connection, *, generated_at: str | None = None, is_super_admin: bool = False
) -> dict[str, Any]:
    """One evidence-backed operational view; absent ledgers stay visibly absent."""
    latest_operation = _rows(
        conn, "SELECT * FROM pipeline_operations ORDER BY recorded_at DESC LIMIT 1"
    )
    operation = dict(latest_operation[0]) if latest_operation else None
    canonical_record = None
    if operation and operation.get("record_json"):
        try:
            canonical_record = DailyRunRecord.from_dict(json.loads(operation["record_json"]))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            canonical_record = None
    if operation:
        operation.pop("record_json", None)
    phases = (
        [
            {
                "key": phase.key,
                "label": phase.label,
                "status": phase.status.value,
                "duration_seconds": phase.duration_seconds,
                "detail": phase.detail,
            }
            for phase in canonical_record.phases
        ]
        if canonical_record
        else json.loads(operation["phases_json"])
        if operation
        else []
    )
    seen = {str(phase.get("key")) for phase in phases}
    phases.extend(
        {"key": key, "label": label, "status": "not_recorded", "duration_seconds": None}
        for key, label in _PHASE_KEYS
        if key not in seen
    )
    order = {key: index for index, (key, _label) in enumerate(_PHASE_KEYS)}
    phases.sort(key=lambda phase: order.get(str(phase.get("key")), 99))

    active = int(_scalar(conn, "SELECT COUNT(*) FROM jobs WHERE is_active=1"))
    active_board = int(_scalar(conn, f"SELECT COUNT(*) FROM jobs j WHERE {BOARD_WHERE}"))
    duplicates = int(
        _scalar(conn, "SELECT COUNT(*) FROM jobs WHERE is_active=1 AND cross_posted=1")
    )
    missing_descriptions = int(
        _scalar(
            conn,
            "SELECT COUNT(*) FROM jobs WHERE is_active=1 "
            "AND TRIM(COALESCE(description_clean,''))=''",
        )
    )
    enriched = int(
        _scalar(
            conn,
            """SELECT COUNT(*) FROM jobs j JOIN job_enrichments e
               ON j.source=e.source AND j.source_id=e.source_id WHERE j.is_active=1""",
        )
    )
    latest_day = _scalar(conn, "SELECT MAX(scraped_date) FROM job_history", default=None)
    deltas = _rows(
        conn,
        """
        WITH dates AS (
          SELECT MAX(scraped_date) current_date,
                 (SELECT MAX(scraped_date) FROM job_history
                   WHERE scraped_date < (SELECT MAX(scraped_date) FROM job_history)) previous_date
          FROM job_history
        ), current AS (
          SELECT company_id, job_count FROM job_history, dates
          WHERE scraped_date=dates.current_date
        ), previous AS (
          SELECT company_id, job_count FROM job_history, dates
          WHERE scraped_date=dates.previous_date
        )
        SELECT
          COALESCE(SUM(MAX(current.job_count-COALESCE(previous.job_count,0),0)),0) added,
          COALESCE(SUM(MAX(COALESCE(previous.job_count,0)-current.job_count,0)),0) removed
        FROM current LEFT JOIN previous USING (company_id)
        """,
    )
    added = int(deltas[0]["added"]) if deltas else 0
    deactivated = int(deltas[0]["removed"]) if deltas else 0
    description_pct = _pct(active - missing_descriptions, active)
    enrichment_pct = _pct(enriched, active)
    gates = [
        {
            "key": "new_roles",
            "label": "New roles",
            "value": added,
            "unit": "roles",
            "status": "pass",
            "detail": "Added in the latest complete company snapshot.",
        },
        {
            "key": "deactivated",
            "label": "Deactivated roles",
            "value": deactivated,
            "unit": "roles",
            "status": "warning" if active and deactivated > max(100, active * 0.15) else "pass",
            "detail": "Flagged closed versus prior company snapshots.",
        },
        {
            "key": "duplicates",
            "label": "Duplicate listings",
            "value": duplicates,
            "unit": "suppressed",
            "status": "pass",
            "detail": f"{active_board:,} deduplicated Roles remain visible.",
        },
        {
            "key": "descriptions",
            "label": "Description coverage",
            "value": description_pct,
            "unit": "%",
            "status": "pass" if description_pct >= 80 else "warning",
            "detail": f"{missing_descriptions:,} active listings are missing descriptions.",
        },
        {
            "key": "enrichment",
            "label": "Enrichment coverage",
            "value": enrichment_pct,
            "unit": "%",
            "status": "pass" if enrichment_pct >= 90 else "warning",
            "detail": f"{max(0, active - enriched):,} active listings remain unenriched.",
        },
    ]

    # Source health, Publication safety and Recommendation health are all
    # Ultimate-Admin-only, same posture as ai_cost above: not queried at all
    # for the other four admins, not just hidden client-side.
    source_health: list[dict[str, Any]] | None = None
    if is_super_admin:
        source_rows = _rows(
            conn,
            """
            WITH latest AS (SELECT MAX(scraped_date) AS day FROM pipeline_company_runs)
            SELECT source, COUNT(*) companies, SUM(status='success') successful,
                   SUM(status='zero') zero_results, SUM(status='failed') failed,
                   SUM(jobs_found) roles, ROUND(SUM(runtime_seconds),1) runtime_seconds
            FROM pipeline_company_runs, latest
            WHERE scraped_date=latest.day GROUP BY source ORDER BY roles DESC, source
            """,
        )
        source_health = []
        for row in source_rows:
            companies = int(row["companies"])
            success_rate = _pct(int(row["successful"]), companies)
            source_health.append(
                {
                    **dict(row),
                    "tracking_available": True,
                    "roles_found": int(row["roles"]),
                    "active_roles": None,
                    "success_rate_pct": success_rate,
                    "status": "healthy"
                    if success_rate >= 90
                    else "warning"
                    if success_rate >= 70
                    else "failed",
                }
            )
        if not source_health:
            source_health = [
                {
                    "source": row["source"],
                    "companies": None,
                    "successful": None,
                    "zero_results": None,
                    "failed": None,
                    "roles": row["roles"],
                    "tracking_available": False,
                    "roles_found": None,
                    "active_roles": int(row["roles"]),
                    "runtime_seconds": None,
                    "success_rate_pct": None,
                    "status": "not_recorded",
                }
                for row in _rows(
                    conn,
                    "SELECT source, COUNT(*) roles FROM jobs WHERE is_active=1 "
                    "GROUP BY source ORDER BY roles DESC",
                )
            ]

    # AI spend is Ultimate-Admin-only (main.py's require_super_admin). The other
    # four admins never receive this section — not hidden client-side, never
    # queried or serialised for them in the first place.
    ai: dict[str, Any] | None = None
    if is_super_admin:
        usage_rows = _rows(
            conn,
            """SELECT phase, model, calls, roles_processed, prompt_cache_hit_tokens,
                      prompt_cache_miss_tokens, completion_tokens, estimated_cost_usd, recorded_at
               FROM ai_usage
               WHERE run_id=(SELECT run_id FROM ai_usage ORDER BY recorded_at DESC LIMIT 1)
               ORDER BY phase""",
        )
        usage = [dict(row) for row in usage_rows]
        prompt_version = _scalar(
            conn,
            "SELECT prompt_version FROM job_enrichments WHERE prompt_version IS NOT NULL "
            "GROUP BY prompt_version ORDER BY COUNT(*) DESC LIMIT 1",
            default=None,
        )
        backlog = int(
            _scalar(
                conn,
                """SELECT COUNT(*) FROM jobs j LEFT JOIN job_enrichments e
                   ON j.source=e.source AND j.source_id=e.source_id
                   WHERE j.is_active=1
                     AND (e.source_id IS NULL OR e.prompt_version IS NULL
                          OR e.prompt_version<>?)""",
                prompt_version,
            )
            if prompt_version
            else active
        )
        ai = {
            "calls": sum(int(row["calls"]) for row in usage),
            "roles_processed": sum(int(row["roles_processed"]) for row in usage),
            "estimated_cost_usd": round(sum(float(row["estimated_cost_usd"]) for row in usage), 4),
            "cache_hit_tokens": sum(int(row["prompt_cache_hit_tokens"]) for row in usage),
            "cache_miss_tokens": sum(int(row["prompt_cache_miss_tokens"]) for row in usage),
            "completion_tokens": sum(int(row["completion_tokens"]) for row in usage),
            "backlog": backlog,
            "daily_limit": 300,
            "phases": usage,
            "tracking_available": bool(usage),
        }

    publication: dict[str, Any] | None = None
    if is_super_admin:
        publication_rows = _rows(
            conn,
            "SELECT * FROM pipeline_catalog_sync ORDER BY received_at DESC LIMIT 1",
        )
        publication = dict(publication_rows[0]) if publication_rows else None
        if publication:
            publication["restore_source"] = operation.get("restore_source") if operation else None
            publication["restore_sha256"] = operation.get("restore_sha256") if operation else None

    alerts = []
    for phase in phases:
        if phase.get("status") == "failed":
            alerts.append(
                {
                    "severity": "critical",
                    "title": f"{phase.get('label')} failed",
                    "detail": phase.get("detail") or "Open the GitHub run for the error log.",
                }
            )
    for gate in gates:
        if gate["status"] == "warning":
            alerts.append(
                {
                    "severity": "warning",
                    "title": f"{gate['label']} needs review",
                    "detail": gate["detail"],
                }
            )
    # source_health-derived alerts are Ultimate-Admin-only too, since the
    # underlying data is: an ordinary admin sees pipeline-phase and
    # quality-gate alerts above, just not a per-source breakdown.
    for source in source_health or []:
        if source["status"] in {"warning", "failed"}:
            alerts.append(
                {
                    "severity": "warning",
                    "title": f"{source['source']} source health dropped",
                    "detail": f"Success rate {source['success_rate_pct']}% in the latest run.",
                }
            )

    recommendations: dict[str, Any] | None = None
    if is_super_admin:
        try:
            recommendations = seekers_store.get_store().recommendation_health()
        except (sqlite3.Error, OSError, ValueError):
            recommendations = {
                "impressions": 0,
                "clicks": 0,
                "click_through_pct": 0.0,
                "saves": 0,
                "more_like": 0,
                "dismissals": 0,
                "wrong_reason": 0,
                "seekers_reached": 0,
                "eligible_seekers": 0,
                "coverage_pct": 0.0,
                "tracking_available": False,
                "window_started_at": None,
                "window_ended_at": None,
            }

    return {
        "generated_at": generated_at or datetime.now(_HONG_KONG).isoformat(),
        "run": {
            **(operation or {"scraped_date": latest_day, "status": "not_recorded"}),
            "phases": phases,
        },
        "quality_gates": gates,
        "source_health": source_health,
        "ai_cost": ai,
        "publication": publication,
        "recommendations": recommendations,
        "alerts": alerts,
    }


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


def _table_available(conn: sqlite3.Connection, table: str) -> bool:
    try:
        return (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            is not None
        )
    except sqlite3.Error:
        return False


def build_admin_intelligence(
    conn: sqlite3.Connection,
    *,
    history_days: int = 30,
    operating_day: date | None = None,
    is_super_admin: bool = False,
) -> dict[str, Any]:
    """Return one point-in-time intelligence snapshot for every admin section.

    jobs.db is read in one SQLite transaction. Seeker recommendation health and
    Seeker activity are intentionally sampled through their own store inside
    _operations_dashboard / here; ADR 0006 forbids attaching Seeker-owned state
    to the catalogue.
    """
    days = max(1, min(int(history_days), 365))
    generated = datetime.now(_HONG_KONG)
    day = operating_day or _hong_kong_today()
    started_transaction = not conn.in_transaction
    if started_transaction:
        conn.execute("BEGIN")
    try:
        availability = {
            "catalogue": _table_available(conn, "jobs"),
            "history": _table_available(conn, "job_history"),
            "daily_run": _table_available(conn, "pipeline_operations"),
            "source_health": _table_available(conn, "pipeline_company_runs"),
            "ai_usage": _table_available(conn, "ai_usage"),
            "publication": _table_available(conn, "pipeline_catalog_sync"),
        }
        today = _run_today(conn, operating_day=day)
        today["tracking_available"] = availability["history"]
        operations = _operations_dashboard(
            conn, generated_at=generated.isoformat(), is_super_admin=is_super_admin
        )
        availability["recommendations"] = bool(
            (operations["recommendations"] or {}).get("tracking_available")
        )
        try:
            user_activity = seekers_store.get_store().user_activity_overview(days=days)
        except (sqlite3.Error, OSError, ValueError):
            user_activity = {
                "days": days,
                "window_started_on": None,
                "window_ended_on": None,
                "total_seekers": 0,
                "new_signups": 0,
                "active_seekers": 0,
                "returning_seekers": 0,
                "repeat_visit_rate_pct": 0.0,
                "points": [],
                "tracking_available": False,
                "anonymous": {
                    "unique_visitors": 0,
                    "returning_visitors": 0,
                    "repeat_visit_rate_pct": 0.0,
                    "points": [],
                },
            }
        return {
            "schema_version": 1,
            "generated_at": generated.isoformat(),
            "operating_date": day.isoformat(),
            "availability": availability,
            "today": today,
            "history": {
                "days": days,
                "tracking_available": availability["history"],
                "points": _run_history(conn, days, operating_day=day),
            },
            "operations": operations,
            "analytics": _analytics_overview(conn),
            "user_activity": user_activity,
        }
    finally:
        if started_transaction:
            conn.rollback()
