"""
Weekly hiring trends report — emailed every Monday 9 AM HKT.

Run manually:   python -m hk_jobs.pipeline --weekly-report
Cron (Monday):  0 1 * * 1 cd /opt/hk-job-scraper && source .venv/bin/activate
                && source config/api_keys.env
                && python -m hk_jobs.pipeline --weekly-report
                >> logs/weekly_report.log 2>&1
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections import Counter
from datetime import date, timedelta

from hk_jobs.notifications import _send_email

logger = logging.getLogger(__name__)

_BLUE = "#185FA5"
_GRN  = "#16a34a"
_RED  = "#dc2626"
_GREY = "#f9fafb"


def generate_weekly_report(db_path: str = "data/jobs.db") -> None:
    """Query the DB for the past 7 days and send a rich HTML summary email."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    today     = date.today()
    week_ago  = (today - timedelta(days=7)).isoformat()
    today_str = today.isoformat()

    # ── Headline numbers ──────────────────────────────────────────────────────
    total_now = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE is_active=1"
    ).fetchone()[0]

    row = conn.execute("""
        SELECT SUM(job_count) FROM job_history
        WHERE scraped_date = DATE('now', '-7 days')
    """).fetchone()
    total_last_week = row[0] if row and row[0] else total_now
    delta     = total_now - total_last_week
    delta_pct = round(delta / total_last_week * 100, 1) if total_last_week else 0.0

    new_this_week = conn.execute("""
        SELECT COUNT(*) FROM jobs
        WHERE DATE(fetched_at) >= DATE('now', '-7 days') AND is_active=1
    """).fetchone()[0]

    # ── Top companies ─────────────────────────────────────────────────────────
    top_cos = conn.execute("""
        SELECT company, COUNT(*) as n FROM jobs
        WHERE DATE(fetched_at) >= DATE('now', '-7 days') AND is_active=1
        GROUP BY company ORDER BY n DESC LIMIT 5
    """).fetchall()

    # ── Top skills via Python JSON parsing (avoids json_each portability issues)
    skill_rows = conn.execute("""
        SELECT e.required_skills FROM job_enrichments e
        JOIN jobs j ON j.source=e.source AND j.source_id=e.source_id
        WHERE DATE(j.fetched_at) >= DATE('now', '-7 days')
          AND e.required_skills IS NOT NULL AND e.required_skills != '[]'
    """).fetchall()
    skill_counter: Counter = Counter()
    for r in skill_rows:
        try:
            for s in json.loads(r["required_skills"]):
                skill_counter[s.lower().strip()] += 1
        except Exception:
            pass
    top_skills = skill_counter.most_common(10)

    # ── Seniority breakdown ───────────────────────────────────────────────────
    seniority = conn.execute("""
        SELECT e.seniority, COUNT(*) as n FROM job_enrichments e
        JOIN jobs j ON j.source=e.source AND j.source_id=e.source_id
        WHERE DATE(j.fetched_at) >= DATE('now', '-7 days')
          AND e.seniority IS NOT NULL
        GROUP BY e.seniority ORDER BY n DESC
    """).fetchall()
    total_sen = sum(r["n"] for r in seniority)

    # ── Category breakdown ────────────────────────────────────────────────────
    categories = conn.execute("""
        SELECT e.job_category, COUNT(*) as n FROM job_enrichments e
        JOIN jobs j ON j.source=e.source AND j.source_id=e.source_id
        WHERE DATE(j.fetched_at) >= DATE('now', '-7 days')
          AND e.job_category IS NOT NULL
        GROUP BY e.job_category ORDER BY n DESC
    """).fetchall()

    # ── Growing companies (from job_history) ──────────────────────────────────
    growing = conn.execute("""
        SELECT company_name, job_count, trend_percent FROM job_history
        WHERE scraped_date = DATE('now') AND trend_direction = 'growing'
        ORDER BY trend_percent DESC LIMIT 5
    """).fetchall()

    conn.close()

    # ── Print to terminal so you can verify data without sending email ─────────
    week_start_str = (today - timedelta(days=7)).strftime("%B %d")
    week_end_str   = today.strftime("%B %d, %Y")

    logger.info("Weekly report data (%s → %s):", week_start_str, week_end_str)
    logger.info("  Total now: %d  Last week: %d  Delta: %+d (%+.1f%%)",
                total_now, total_last_week, delta, delta_pct)
    logger.info("  New this week: %d", new_this_week)
    logger.info("  Top companies: %s", [(r["company"], r["n"]) for r in top_cos])
    logger.info("  Top skills: %s", top_skills[:5])
    logger.info("  Seniority: %s", [(r["seniority"], r["n"]) for r in seniority])
    logger.info("  Categories: %s", [(r["job_category"], r["n"]) for r in categories])

    # ── Build HTML ─────────────────────────────────────────────────────────────
    delta_col  = _GRN if delta >= 0 else _RED
    delta_str  = f"+{delta}" if delta >= 0 else str(delta)
    pct_str    = f"+{delta_pct}%" if delta_pct >= 0 else f"{delta_pct}%"

    def _trow(i, c1, c2, col2=None):
        bg = "white" if i % 2 == 0 else _GREY
        c2_style = f"color:{col2};font-weight:bold;" if col2 else ""
        return (
            f'<tr style="background:{bg};">'
            f'<td style="padding:8px;">{c1}</td>'
            f'<td style="padding:8px;text-align:center;{c2_style}">{c2}</td>'
            f'</tr>'
        )

    co_rows  = "".join(_trow(i, f"{i+1}. {r['company']}", f"+{r['n']}", _GRN)
                       for i, r in enumerate(top_cos))
    sk_rows  = "".join(_trow(i, f"{i+1}. {s.title()}", n)
                       for i, (s, n) in enumerate(top_skills))
    cat_rows = "".join(_trow(i, r["job_category"], r["n"])
                       for i, r in enumerate(categories))

    sen_rows = ""
    for r in seniority:
        pct = round(r["n"] / total_sen * 100) if total_sen else 0
        sen_rows += (
            f'<tr><td style="padding:6px;text-transform:capitalize;">{r["seniority"]}</td>'
            f'<td style="padding:6px;">'
            f'<div style="background:#e5e7eb;border-radius:4px;height:16px;">'
            f'<div style="background:{_BLUE};width:{pct}%;height:16px;border-radius:4px;"></div>'
            f'</div></td>'
            f'<td style="padding:6px;text-align:right;color:#666;">{pct}% ({r["n"]})</td></tr>'
        )

    stat = lambda val, label, colour: (
        f'<td style="padding:15px;text-align:center;">'
        f'<div style="font-size:32px;font-weight:bold;color:{colour};">{val}</div>'
        f'<div style="color:#666;font-size:12px;">{label}</div></td>'
    )

    section = lambda title, content: (
        f'<div style="padding:20px;border:1px solid #e5e7eb;border-top:none;">'
        f'<h3 style="color:{_BLUE};margin-top:0;">{title}</h3>'
        f'<table style="width:100%;border-collapse:collapse;">{content}</table>'
        f'</div>'
    )

    header_row = lambda *cols: (
        f'<tr style="background:{_BLUE};color:white;">' +
        "".join(f'<th style="padding:8px;text-align:{("left" if i==0 else "center")};">{c}</th>'
                for i, c in enumerate(cols)) +
        "</tr>"
    )

    html = f"""
<div style="font-family:Arial,sans-serif;max-width:650px;margin:0 auto;">
  <div style="background:{_BLUE};color:white;padding:25px;border-radius:8px 8px 0 0;">
    <h1 style="margin:0;font-size:22px;">📊 HK Finance Hiring — Weekly Report</h1>
    <p style="margin:8px 0 0;opacity:.85;font-size:14px;">{week_start_str} — {week_end_str}</p>
  </div>
  <div style="background:#f0f9ff;padding:20px;border:1px solid #bae6fd;text-align:center;">
    <table style="width:100%;border-collapse:collapse;"><tr>
      {stat(f"{total_now:,}", "Total Active Jobs", _BLUE)}
      {stat(f"{delta_str} ({pct_str})", "vs Last Week", delta_col)}
      {stat(f"{new_this_week:,}", "New This Week", "#7c3aed")}
    </tr></table>
  </div>
  {section("🏢 Top Companies Hiring This Week",
           header_row("Company", "New Jobs") + co_rows)}
  {section("🔥 Top 10 Skills This Week",
           header_row("Skill", "Jobs") + sk_rows)}
  <div style="padding:20px;border:1px solid #e5e7eb;border-top:none;">
    <h3 style="color:{_BLUE};margin-top:0;">📈 Seniority Breakdown</h3>
    <table style="width:100%;border-collapse:collapse;">{sen_rows}</table>
  </div>
  {section("🗂 Jobs by Category",
           header_row("Category", "Jobs") + cat_rows)}
  <div style="background:{_GREY};padding:15px;border:1px solid #e5e7eb;
              border-top:none;border-radius:0 0 8px 8px;text-align:center;">
    <p style="margin:0;color:#666;font-size:12px;">
      HK Job Board Scraper — Weekly Report &nbsp;·&nbsp;
      Finex Members Only &nbsp;·&nbsp; Every Monday 9 AM HKT
    </p>
  </div>
</div>"""

    text = (
        f"HK Finance Hiring — Weekly Report\n{week_start_str} → {week_end_str}\n\n"
        f"Total active: {total_now:,} ({delta_str} vs last week)\n"
        f"New this week: {new_this_week:,}\n\n"
        f"TOP COMPANIES:\n" + "\n".join(f"  {r['company']}: +{r['n']}" for r in top_cos) +
        f"\n\nTOP SKILLS:\n" + "\n".join(f"  {s.title()}: {n}" for s, n in top_skills) +
        f"\n\nSENIORITY:\n" + "\n".join(f"  {r['seniority']}: {r['n']}" for r in seniority) +
        f"\n\nCATEGORIES:\n" + "\n".join(f"  {r['job_category']}: {r['n']}" for r in categories)
    )

    subject = f"📊 HK Finance Weekly Report — {week_start_str} to {week_end_str}"
    _send_email(subject, html, text)
