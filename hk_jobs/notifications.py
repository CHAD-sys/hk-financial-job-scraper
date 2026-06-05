"""
Email notifications for pipeline events.

Sends two types of emails:
  - Failure alert: sent immediately when any phase raises an exception
  - Daily summary: sent after a successful run with today's stats

Configuration — set these environment variables (or in config/api_keys.env):
  SMTP_HOST    (default: smtp.gmail.com)
  SMTP_PORT    (default: 587)
  SMTP_USER    your Gmail address
  SMTP_PASS    Gmail App Password (16 chars — NOT your regular password)
  NOTIFY_EMAIL recipient (default: mohamedaminechahid@gmail.com)

Gmail setup (one-time):
  1. myaccount.google.com → Security → 2-Step Verification → ON
  2. Security → App Passwords → Mail → Other ("HK Scraper")
  3. Copy the 16-character password → set as SMTP_PASS
"""

from __future__ import annotations

import json
import logging
import os
import smtplib
import sqlite3
from datetime import date, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)

SMTP_HOST    = os.getenv("SMTP_HOST",    "smtp.gmail.com")
SMTP_PORT    = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER    = os.getenv("SMTP_USER",    "")
SMTP_PASS    = os.getenv("SMTP_PASS",    "")
NOTIFY_EMAIL = os.getenv("NOTIFY_EMAIL", "mohamedaminechahid@gmail.com")
PROJECT_NAME = "HK Job Board Scraper"

_BLUE = "#185FA5"
_RED  = "#dc2626"
_GRN  = "#16a34a"
_GREY = "#f9fafb"


# ── Core sender ────────────────────────────────────────────────────────────────

def _send_email(subject: str, body_html: str, body_text: str) -> bool:
    if not SMTP_USER or not SMTP_PASS:
        logger.warning(
            "Email not configured (SMTP_USER/SMTP_PASS missing) — skipping notification. "
            "Set these env vars or add them to config/api_keys.env."
        )
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = SMTP_USER
        msg["To"]      = NOTIFY_EMAIL
        msg.attach(MIMEText(body_text, "plain"))
        msg.attach(MIMEText(body_html, "html"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as srv:
            srv.ehlo()
            srv.starttls()
            srv.login(SMTP_USER, SMTP_PASS)
            srv.sendmail(SMTP_USER, NOTIFY_EMAIL, msg.as_string())

        logger.info("✅ Email sent → %s: %s", NOTIFY_EMAIL, subject)
        return True
    except Exception as exc:
        logger.error("❌ Failed to send email: %s", exc)
        return False


# ── Public API ─────────────────────────────────────────────────────────────────

def send_failure_alert(
    phase: str,
    error: str,
    jobs_collected: int = 0,
    duration_seconds: int = 0,
) -> bool:
    """Send an immediate alert when the pipeline raises an exception."""
    now      = datetime.now().strftime("%B %d, %Y at %I:%M %p HKT")
    duration = (f"{duration_seconds // 60}m {duration_seconds % 60}s"
                if duration_seconds else "unknown")
    subject  = f"🚨 {PROJECT_NAME} FAILED — {datetime.now().strftime('%B %d, %Y')}"

    html = f"""
<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;">
  <div style="background:{_RED};color:white;padding:20px;border-radius:8px 8px 0 0;">
    <h1 style="margin:0;font-size:24px;">🚨 Pipeline Failed</h1>
    <p style="margin:5px 0 0;opacity:.9;">{now}</p>
  </div>
  <div style="background:#fef2f2;padding:20px;border:1px solid #fecaca;">
    <table style="width:100%;border-collapse:collapse;">
      <tr><td style="padding:8px;font-weight:bold;color:#666;">Failed Phase</td>
          <td style="padding:8px;color:{_RED};font-weight:bold;">{phase}</td></tr>
      <tr style="background:white;">
          <td style="padding:8px;font-weight:bold;color:#666;">Error</td>
          <td style="padding:8px;font-family:monospace;font-size:13px;">{error}</td></tr>
      <tr><td style="padding:8px;font-weight:bold;color:#666;">Jobs before failure</td>
          <td style="padding:8px;">{jobs_collected:,}</td></tr>
      <tr style="background:white;">
          <td style="padding:8px;font-weight:bold;color:#666;">Runtime</td>
          <td style="padding:8px;">{duration}</td></tr>
    </table>
  </div>
  <div style="background:{_GREY};padding:15px;border:1px solid #e5e7eb;
              border-top:none;border-radius:0 0 8px 8px;">
    <p style="margin:0;color:#666;font-size:13px;">
      Check logs: logs/daily_runs.log
    </p>
  </div>
</div>"""

    text = (
        f"HK Job Board Scraper — PIPELINE FAILED\n\n"
        f"Time: {now}\nFailed Phase: {phase}\nError: {error}\n"
        f"Jobs before failure: {jobs_collected:,}\nRuntime: {duration}\n\n"
        f"Check logs: logs/daily_runs.log"
    )
    return _send_email(subject, html, text)


def send_daily_summary(db_path: str = "data/jobs.db") -> bool:
    """Query today's stats and send a summary email."""
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        total = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE is_active=1"
        ).fetchone()[0]

        new_today = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE is_active=1 AND DATE(fetched_at)=DATE('now')"
        ).fetchone()[0]

        removed = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE is_active=0 AND DATE(fetched_at)<DATE('now')"
        ).fetchone()[0]

        top_cos = conn.execute("""
            SELECT company, COUNT(*) as n FROM jobs
            WHERE DATE(fetched_at)=DATE('now') AND is_active=1
            GROUP BY company ORDER BY n DESC LIMIT 5
        """).fetchall()

        # Skills in today's new jobs via JSON
        top_skills_raw = conn.execute("""
            SELECT required_skills FROM job_enrichments e
            JOIN jobs j ON j.source=e.source AND j.source_id=e.source_id
            WHERE DATE(j.fetched_at)=DATE('now')
              AND e.required_skills IS NOT NULL AND e.required_skills!='[]'
        """).fetchall()

        from collections import Counter
        skill_counter: Counter = Counter()
        for row in top_skills_raw:
            try:
                for s in json.loads(row["required_skills"]):
                    skill_counter[s.lower().strip()] += 1
            except Exception:
                pass
        top_skills = skill_counter.most_common(5)

        cov = conn.execute("""
            SELECT COUNT(*) as t,
                   SUM(CASE WHEN description_raw IS NOT NULL AND description_raw!='' THEN 1 ELSE 0 END) as d
            FROM jobs WHERE is_active=1
        """).fetchone()
        desc_pct = round(cov["d"] / cov["t"] * 100, 1) if cov["t"] else 0.0
        conn.close()

    except Exception as exc:
        logger.error("Failed to query DB for summary: %s", exc)
        return False

    now     = datetime.now().strftime("%B %d, %Y")
    subject = f"✅ HK Jobs Daily Update — {now}"

    def _rows(items, fmt):
        return "".join(fmt(i) for i in items)

    co_rows = _rows(top_cos, lambda r: (
        f'<tr><td style="padding:8px;">{r["company"]}</td>'
        f'<td style="padding:8px;text-align:center;color:{_GRN};font-weight:bold;">+{r["n"]}</td></tr>'
    ))
    sk_rows = _rows(top_skills, lambda r: (
        f'<tr><td style="padding:8px;">{r[0].title()}</td>'
        f'<td style="padding:8px;text-align:center;">{r[1]} jobs</td></tr>'
    ))

    stat = (
        lambda val, label, colour:
        f'<td style="padding:15px;text-align:center;">'
        f'<div style="font-size:36px;font-weight:bold;color:{colour};">{val}</div>'
        f'<div style="color:#666;font-size:13px;">{label}</div></td>'
    )

    html = f"""
<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;">
  <div style="background:{_BLUE};color:white;padding:20px;border-radius:8px 8px 0 0;">
    <h1 style="margin:0;font-size:24px;">✅ Daily Pipeline Complete</h1>
    <p style="margin:5px 0 0;opacity:.9;">{now}</p>
  </div>
  <div style="background:#f0f9ff;padding:20px;border:1px solid #bae6fd;text-align:center;">
    <table style="width:100%;border-collapse:collapse;"><tr>
      {stat(f"{total:,}", "Active Jobs", _BLUE)}
      {stat(f"+{new_today}", "New Today", _GRN)}
      {stat(f"-{removed}", "Removed", _RED)}
      {stat(f"{desc_pct}%", "Coverage", "#7c3aed")}
    </tr></table>
  </div>
  <div style="padding:20px;border:1px solid #e5e7eb;border-top:none;">
    <h3 style="color:{_BLUE};margin-top:0;">🏢 Top Companies Hiring Today</h3>
    <table style="width:100%;border-collapse:collapse;">
      <tr style="background:{_BLUE};color:white;">
        <th style="padding:8px;text-align:left;">Company</th>
        <th style="padding:8px;text-align:center;">New Jobs</th>
      </tr>{co_rows}
    </table>
  </div>
  <div style="padding:20px;border:1px solid #e5e7eb;border-top:none;">
    <h3 style="color:{_BLUE};margin-top:0;">🔥 Top Skills in Today's New Jobs</h3>
    <table style="width:100%;border-collapse:collapse;">
      <tr style="background:{_BLUE};color:white;">
        <th style="padding:8px;text-align:left;">Skill</th>
        <th style="padding:8px;text-align:center;">Jobs</th>
      </tr>{sk_rows}
    </table>
  </div>
  <div style="background:{_GREY};padding:15px;border:1px solid #e5e7eb;
              border-top:none;border-radius:0 0 8px 8px;text-align:center;">
    <p style="margin:0;color:#666;font-size:12px;">
      {PROJECT_NAME} — Finex Members Only
    </p>
  </div>
</div>"""

    text = (
        f"HK Jobs Daily Update — {now}\n\n"
        f"Active jobs: {total:,}\nNew today: +{new_today}\n"
        f"Removed: -{removed}\nCoverage: {desc_pct}%\n\n"
        f"TOP COMPANIES:\n" +
        "\n".join(f"  {r['company']}: +{r['n']}" for r in top_cos) +
        f"\n\nTOP SKILLS:\n" +
        "\n".join(f"  {s.title()}: {n}" for s, n in top_skills)
    )
    return _send_email(subject, html, text)
