"""
Job history analytics: snapshot recording and trend reporting.

Called by the pipeline after every real (non-dry-run) scrape to build up a
time-series of job counts, then queried by --report and --export-trends CLI
commands to surface hiring trends.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hk_jobs.pipeline import CompanyResult


_PIPELINE_COMPANY_RUNS_DDL = """
CREATE TABLE IF NOT EXISTS pipeline_company_runs (
    run_id TEXT NOT NULL, scraped_date TEXT NOT NULL, source TEXT NOT NULL,
    company_slug TEXT NOT NULL, company_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('success', 'zero', 'failed')),
    jobs_found INTEGER NOT NULL DEFAULT 0, jobs_inserted INTEGER NOT NULL DEFAULT 0,
    jobs_updated INTEGER NOT NULL DEFAULT 0, jobs_deactivated INTEGER NOT NULL DEFAULT 0,
    runtime_seconds REAL NOT NULL DEFAULT 0, error TEXT, recorded_at TEXT NOT NULL,
    PRIMARY KEY (run_id, company_slug)
)
"""


# ── Snapshot recording ────────────────────────────────────────────────────────

def record_scrape_snapshot(
    db_path: str,
    results: list[CompanyResult],
    scraped_date: date,
) -> None:
    """
    Write one job_history row per company and refresh company_metrics.

    Called at the end of every real pipeline run.  Skipped in dry-run mode
    (pipeline.py only calls this when dry_run=False).

    Trend logic (per spec):
      delta = today_count - yesterday_count
      growing   if delta > 2
      declining if delta < -2
      stable    otherwise
      new       if no yesterday row exists
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        date_str = scraped_date.isoformat()
        yesterday_str = (scraped_date - timedelta(days=1)).isoformat()

        with conn:
            for r in results:
                if not r.ok:
                    continue  # skip timed-out / errored companies

                company_id = r.slug
                company_name = r.name
                today_count = r.total_fetched

                # ── trend vs previous day ──────────────────────────────────
                prev = conn.execute(
                    "SELECT job_count FROM job_history WHERE company_id=? AND scraped_date=?",
                    (company_id, yesterday_str),
                ).fetchone()

                if prev:
                    yesterday_count = prev["job_count"]
                    delta = today_count - yesterday_count
                    trend_percent = (
                        round((delta / yesterday_count) * 100, 1)
                        if yesterday_count > 0 else 0.0
                    )
                    if delta > 2:
                        trend_direction = "growing"
                    elif delta < -2:
                        trend_direction = "declining"
                    else:
                        trend_direction = "stable"
                    jobs_added = max(0, delta)
                    jobs_removed = max(0, -delta)
                else:
                    trend_direction = "new"
                    trend_percent = 0.0
                    jobs_added = today_count
                    jobs_removed = 0

                # ── upsert job_history ─────────────────────────────────────
                conn.execute(
                    """
                    INSERT INTO job_history
                        (company_id, company_name, job_count, scraped_date,
                         trend_direction, trend_percent, jobs_added, jobs_removed)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (company_id, scraped_date) DO UPDATE SET
                        job_count       = excluded.job_count,
                        trend_direction = excluded.trend_direction,
                        trend_percent   = excluded.trend_percent,
                        jobs_added      = excluded.jobs_added,
                        jobs_removed    = excluded.jobs_removed
                    """,
                    (company_id, company_name, today_count, date_str,
                     trend_direction, trend_percent, jobs_added, jobs_removed),
                )

                # ── rolling averages ───────────────────────────────────────
                def _avg(days: int) -> float:
                    since = (scraped_date - timedelta(days=days)).isoformat()
                    row = conn.execute(
                        """SELECT AVG(job_count) FROM job_history
                           WHERE company_id=? AND scraped_date BETWEEN ? AND ?""",
                        (company_id, since, date_str),
                    ).fetchone()
                    return float(row[0]) if row[0] is not None else float(today_count)

                avg_7d = _avg(7)
                avg_30d = _avg(30)
                growth_7d = round(((today_count - avg_7d) / avg_7d) * 100, 1) if avg_7d else 0.0
                growth_30d = round(((today_count - avg_30d) / avg_30d) * 100, 1) if avg_30d else 0.0

                # ── upsert company_metrics ─────────────────────────────────
                conn.execute(
                    """
                    INSERT INTO company_metrics
                        (company_id, company_name, avg_jobs_7d, avg_jobs_30d,
                         growth_rate_7d, growth_rate_30d, current_trend, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT (company_id) DO UPDATE SET
                        company_name    = excluded.company_name,
                        avg_jobs_7d     = excluded.avg_jobs_7d,
                        avg_jobs_30d    = excluded.avg_jobs_30d,
                        growth_rate_7d  = excluded.growth_rate_7d,
                        growth_rate_30d = excluded.growth_rate_30d,
                        current_trend   = excluded.current_trend,
                        last_updated    = CURRENT_TIMESTAMP
                    """,
                    (company_id, company_name, avg_7d, avg_30d,
                     growth_7d, growth_30d, trend_direction),
                )
    finally:
        conn.close()


def record_pipeline_company_runs(
    db_path: str,
    results: list[CompanyResult],
    scraped_date: date,
    *,
    run_id: str,
) -> None:
    """Write the per-company evidence used for source reliability reporting."""
    stamp = datetime.now(UTC).isoformat()
    rows = []
    for result in results:
        status = "failed" if not result.ok else "zero" if result.total_fetched == 0 else "success"
        rows.append(
            (
                run_id, scraped_date.isoformat(), result.source, result.slug, result.name,
                status, result.total_fetched, result.inserted, result.updated,
                result.deactivated, round(result.elapsed_secs, 3), result.error, stamp,
            )
        )
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            conn.execute(_PIPELINE_COMPANY_RUNS_DDL)
            conn.executemany(
                """
                INSERT OR REPLACE INTO pipeline_company_runs (
                    run_id, scraped_date, source, company_slug, company_name, status,
                    jobs_found, jobs_inserted, jobs_updated, jobs_deactivated,
                    runtime_seconds, error, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
    finally:
        conn.close()


# ── Query helpers ─────────────────────────────────────────────────────────────

def get_company_trend(db_path: str, company_id: str, days: int = 30) -> list[dict]:
    """Return daily history rows for one company over the last N days."""
    since = (date.today() - timedelta(days=days)).isoformat()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """SELECT scraped_date, job_count, trend_direction, trend_percent
               FROM job_history
               WHERE company_id = ? AND scraped_date >= ?
               ORDER BY scraped_date""",
            (company_id, since),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_all_trends(db_path: str, days: int = 30) -> dict[str, list[dict]]:
    """Return {company_id: [daily rows]} for all companies over the last N days."""
    since = (date.today() - timedelta(days=days)).isoformat()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """SELECT company_id, scraped_date, job_count, trend_direction, trend_percent
               FROM job_history
               WHERE scraped_date >= ?
               ORDER BY company_id, scraped_date""",
            (since,),
        ).fetchall()
        result: dict[str, list[dict]] = {}
        for row in rows:
            result.setdefault(row["company_id"], []).append(dict(row))
        return result
    finally:
        conn.close()


def calculate_hiring_velocity(db_path: str) -> list[dict]:
    """Return all companies sorted by 7-day growth rate (descending)."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT cm.company_id, cm.company_name,
                   cm.growth_rate_7d, cm.growth_rate_30d, cm.current_trend,
                   cm.avg_jobs_7d,
                   jh.job_count AS current_jobs
              FROM company_metrics cm
              LEFT JOIN job_history jh
                ON cm.company_id = jh.company_id
               AND jh.scraped_date = (
                     SELECT MAX(scraped_date) FROM job_history
                      WHERE company_id = cm.company_id
                   )
             ORDER BY cm.growth_rate_7d DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def export_trends_jsonl(db_path: str, output_path: str) -> int:
    """
    Write the latest trend snapshot for each company to a JSONL file.
    Returns the number of records written.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT jh.scraped_date  AS date,
                   jh.company_name  AS company,
                   jh.job_count     AS jobs,
                   jh.trend_direction AS trend,
                   jh.trend_percent AS trend_pct,
                   cm.avg_jobs_7d,
                   cm.avg_jobs_30d
              FROM job_history jh
              LEFT JOIN company_metrics cm ON jh.company_id = cm.company_id
             WHERE jh.scraped_date = (
                     SELECT MAX(scraped_date) FROM job_history
                      WHERE company_id = jh.company_id
                   )
             ORDER BY jh.company_name
            """
        ).fetchall()

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            for row in rows:
                record = {
                    "date":     row["date"],
                    "company":  row["company"],
                    "jobs":     row["jobs"],
                    "trend":    row["trend"],
                    "trend_pct": row["trend_pct"],
                    "avg_7d":   row["avg_jobs_7d"],
                    "avg_30d":  row["avg_jobs_30d"],
                }
                f.write(json.dumps(record) + "\n")
        return len(rows)
    finally:
        conn.close()


# ── CLI report formatters ─────────────────────────────────────────────────────

def print_trends_report(db_path: str, days: int = 30) -> None:
    """Print a human-readable trend report to stdout."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT jh.company_name,
                   jh.job_count     AS current_jobs,
                   jh.trend_direction,
                   jh.trend_percent,
                   cm.avg_jobs_7d,
                   cm.avg_jobs_30d,
                   cm.growth_rate_7d,
                   cm.growth_rate_30d,
                   cm.current_trend
              FROM job_history jh
              LEFT JOIN company_metrics cm ON jh.company_id = cm.company_id
             WHERE jh.scraped_date = (
                     SELECT MAX(scraped_date) FROM job_history
                      WHERE company_id = jh.company_id
                   )
             ORDER BY jh.company_name
            """
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        print("No trend data yet — run the pipeline at least once without --dry-run.")
        return

    print()
    print(f"Company Trends Report (Last {days} Days)")
    print("=" * 40)

    for r in rows:
        trend_str = r["current_trend"].upper() if r["current_trend"] else "NEW"
        g7 = r["growth_rate_7d"]
        g30 = r["growth_rate_30d"]
        avg7 = r["avg_jobs_7d"]
        avg30 = r["avg_jobs_30d"]

        pct7_str  = f"{g7:+.1f}%"  if g7  is not None else "n/a"
        pct30_str = f"{g30:+.1f}%" if g30 is not None else "n/a"
        avg7_str  = f"{avg7:.0f}"  if avg7  is not None else "n/a"
        avg30_str = f"{avg30:.0f}" if avg30 is not None else "n/a"

        print()
        print(f"{r['company_name']}")
        print(f"  Current : {r['current_jobs']} jobs")
        print(f"  7d avg  : {avg7_str} jobs  (trend: {pct7_str})")
        print(f"  30d avg : {avg30_str} jobs  (trend: {pct30_str})")
        print(f"  Status  : {trend_str}")

    print()


def print_velocity_report(db_path: str) -> None:
    """Print companies ranked by 7-day hiring velocity."""
    rows = calculate_hiring_velocity(db_path)

    if not rows:
        print("No trend data yet — run the pipeline at least once without --dry-run.")
        return

    print()
    print("Hiring Velocity Ranking")
    print("=" * 40)

    for i, r in enumerate(rows, start=1):
        rate = r["growth_rate_7d"]
        current = r["current_jobs"] or 0
        baseline = r["avg_jobs_7d"] or current
        rate_str = f"{rate:+.1f}%" if rate is not None else "n/a "
        print(f"{i:2}. {r['company_name']:<35} {rate_str}  ({baseline:.0f} → {current} jobs)")

    print()
