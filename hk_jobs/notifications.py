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
  NOTIFY_EMAILS comma/semicolon-separated recipients
                (default: amine@finexclub.org and mohamedaminechahid@gmail.com)

The legacy singular NOTIFY_EMAIL variable is still accepted when
NOTIFY_EMAILS is absent.

Gmail setup (one-time):
  1. myaccount.google.com → Security → 2-Step Verification → ON
  2. Security → App Passwords → Mail → Other ("HK Scraper")
  3. Copy the 16-character password → set as SMTP_PASS

── How "new" and "closed" are counted ────────────────────────────────────────
This is the part that used to be wrong, so it is worth stating plainly.

`jobs.fetched_at` is LAST-seen, not first-seen: the upsert rewrites it on every
run (see storage.py). So `DATE(fetched_at) = today` matches every job the run
touched — essentially the whole active board — not the new ones. The old summary
counted that as "new today" and reported ~4,700 when the real figure was ~140.
"Removed" had the same flaw and reported every inactive row ever recorded.

Until the schema gains a first_seen_at column, the honest way to get a daily
delta is to diff today's database against the most recent backup snapshot taken
before today (data/backups/jobs_YYYY-MM-DD.db, written by phase 6). That is what
_daily_delta() does. When no prior snapshot exists the counts are reported as
unavailable rather than guessed.
"""

from __future__ import annotations

import json
import logging
import os
import re
import smtplib
import sqlite3
from collections import Counter
from datetime import date, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hk_jobs.daily_run.model import DailyRunRecord

logger = logging.getLogger(__name__)

SMTP_HOST    = os.getenv("SMTP_HOST",    "smtp.gmail.com")
SMTP_PORT    = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER    = os.getenv("SMTP_USER",    "")
SMTP_PASS    = os.getenv("SMTP_PASS",    "")
PROJECT_NAME = "FinEx Careers — HK Job Board"

DEFAULT_NOTIFY_EMAILS = (
    "amine@finexclub.org",
    "mohamedaminechahid@gmail.com",
)


def _notification_recipients(raw: str | None = None) -> list[str]:
    """Return a stable, case-insensitively deduplicated recipient list."""
    if raw is None:
        raw = os.getenv("NOTIFY_EMAILS") or os.getenv("NOTIFY_EMAIL")
    candidates = re.split(r"[,;]", raw) if raw else list(DEFAULT_NOTIFY_EMAILS)
    recipients: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        address = candidate.strip()
        normalized = address.casefold()
        if not address or normalized in seen:
            continue
        if "\n" in address or "\r" in address or "@" not in address:
            logger.warning("Ignoring invalid notification recipient: %r", address)
            continue
        seen.add(normalized)
        recipients.append(address)
    return recipients


NOTIFY_EMAILS = _notification_recipients()

BACKUP_DIR = Path("data/backups")
APIFY_CAP  = 30.0          # USD/month, see CLAUDE.md and posts/budget.py

# FinEx palette (webapp/frontend/DESIGN.md). Email clients need inline hex.
C_NAVY   = "#0B1628"
C_PAPER  = "#FFFDF9"
C_CARD   = "#FFFFFF"
C_ALT    = "#F7F4EE"
C_INK    = "#0B1628"
C_MUTED  = "#4A5A70"
C_FAINT  = "#7C8B9E"
C_RULE   = "#E3DED4"
C_GOLD   = "#9A6F00"
C_GOLDBG = "#FBF0D3"
C_BLUE   = "#1E3A8A"
C_GOOD   = "#15803D"
C_WARN   = "#B45309"
C_CRIT   = "#B91C1C"

F_SERIF = "Georgia,'Times New Roman',serif"
F_SANS  = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"
F_MONO  = "'SF Mono',Menlo,Consolas,'Courier New',monospace"


# ── Core sender ────────────────────────────────────────────────────────────────

def _send_email(subject: str, body_html: str, body_text: str) -> bool:
    if not SMTP_USER or not SMTP_PASS:
        logger.warning(
            "Email not configured (SMTP_USER/SMTP_PASS missing) — skipping notification. "
            "Set these env vars or add them to config/api_keys.env."
        )
        return False
    if not NOTIFY_EMAILS:
        logger.warning("No valid notification recipients configured — skipping notification.")
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = SMTP_USER
        msg["To"]      = ", ".join(NOTIFY_EMAILS)
        msg.attach(MIMEText(body_text, "plain"))
        msg.attach(MIMEText(body_html, "html"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as srv:
            srv.ehlo()
            srv.starttls()
            srv.login(SMTP_USER, SMTP_PASS)
            srv.sendmail(SMTP_USER, NOTIFY_EMAILS, msg.as_string())

        logger.info("✅ Email sent → %s: %s", ", ".join(NOTIFY_EMAILS), subject)
        return True
    except Exception as exc:
        logger.error("❌ Failed to send email: %s", exc)
        return False


# ── Small helpers ──────────────────────────────────────────────────────────────

def _n(v) -> str:
    return f"{v:,}" if isinstance(v, int) else str(v)


def _prev_snapshot(today: date) -> Path | None:
    """Newest data/backups/jobs_YYYY-MM-DD.db strictly older than today."""
    if not BACKUP_DIR.is_dir():
        return None
    dated: list[tuple[date, Path]] = []
    for p in BACKUP_DIR.glob("jobs_*.db"):
        m = re.search(r"(\d{4}-\d{2}-\d{2})", p.name)
        if not m:
            continue
        try:
            d = date.fromisoformat(m.group(1))
        except ValueError:
            continue
        if d < today:
            dated.append((d, p))
    if not dated:
        return None
    return max(dated, key=lambda t: t[0])[1]


def _daily_delta(conn: sqlite3.Connection, today: date) -> dict:
    """Diff the live DB against the last pre-today snapshot.

    Returns opened / reopened / closed counts and the comparison date, or
    available=False when there is no snapshot to compare against.
    """
    prev = _prev_snapshot(today)
    if prev is None:
        return {"available": False}
    try:
        pc = sqlite3.connect(f"file:{prev}?mode=ro", uri=True)
        old = {(s, i): a for s, i, a in
               pc.execute("SELECT source, source_id, is_active FROM jobs")}
        pc.close()
    except Exception as exc:                       # a corrupt snapshot must not
        logger.warning("Could not read snapshot %s: %s", prev, exc)
        return {"available": False}                # break the whole email

    opened: list[tuple[str, str]] = []
    reopened = closed = 0
    for s, i, a in conn.execute("SELECT source, source_id, is_active FROM jobs"):
        was = old.get((s, i))
        if a == 1 and was is None:
            opened.append((s, i))
        elif a == 1 and was == 0:
            reopened += 1
        elif a == 0 and was == 1:
            closed += 1

    return {
        "available": True,
        "since": re.search(r"(\d{4}-\d{2}-\d{2})", prev.name).group(1),
        "opened": len(opened),
        "reopened": reopened,
        "closed": closed,
        "opened_ids": opened,
    }


def _sample_new_roles(conn: sqlite3.Connection, ids: list[tuple[str, str]],
                      limit: int = 6) -> list[sqlite3.Row]:
    """Highest-paying genuinely-new roles, for the 'what landed today' block."""
    if not ids:
        return []
    conn.execute("CREATE TEMP TABLE IF NOT EXISTS _new(src TEXT, sid TEXT)")
    conn.execute("DELETE FROM _new")
    conn.executemany("INSERT INTO _new VALUES (?,?)", ids)
    rows = conn.execute("""
        SELECT j.company, j.title, j.source,
               e.seniority, e.job_category,
               e.salary_estimated_min AS smin, e.salary_estimated_max AS smax
        FROM _new n
        JOIN jobs j ON j.source = n.src AND j.source_id = n.sid
        LEFT JOIN job_enrichments e
               ON e.source = j.source AND e.source_id = j.source_id
        ORDER BY COALESCE(e.salary_estimated_max, 0) DESC, j.company
        LIMIT ?
    """, (limit,)).fetchall()
    conn.execute("DELETE FROM _new")
    return rows


def _collect(db_path: str) -> dict:
    """Everything the summary needs, in one pass. Never raises on optional bits."""
    today = date.today()
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    def one(sql, *a, default=0):
        try:
            r = conn.execute(sql, a).fetchone()
            return (r[0] if r and r[0] is not None else default)
        except Exception:
            return default

    d: dict = {"date": today}
    d["active"] = one("SELECT COUNT(*) FROM jobs WHERE is_active=1")
    d["total_rows"] = one("SELECT COUNT(*) FROM jobs")
    d["companies"] = one("SELECT COUNT(DISTINCT company_slug) FROM jobs WHERE is_active=1")

    # Distinct roles: cross-posted duplicates are suppressed via is_primary.
    d["distinct_roles"] = one(
        "SELECT COUNT(*) FROM jobs WHERE is_active=1 AND is_primary=1")

    d["delta"] = _daily_delta(conn, today)
    d["new_roles"] = (_sample_new_roles(conn, d["delta"].get("opened_ids", []))
                      if d["delta"].get("available") else [])

    # ── run health ────────────────────────────────────────────────────────────
    d["scraped_today"] = one(
        "SELECT COUNT(*) FROM job_history WHERE scraped_date=DATE('now')")
    d["zero_today"] = one(
        "SELECT COUNT(*) FROM job_history WHERE scraped_date=DATE('now') AND job_count=0")
    # Rank today's failures by how many jobs that company normally carries, so
    # the ones that matter surface instead of an alphabetical run of boutiques.
    try:
        d["zero_names"] = [r[0] for r in conn.execute("""
            SELECT h.company_name
            FROM job_history h
            LEFT JOIN (SELECT company_id, MAX(job_count) peak
                       FROM job_history GROUP BY company_id) p
                   ON p.company_id = h.company_id
            WHERE h.scraped_date = DATE('now') AND h.job_count = 0
            ORDER BY COALESCE(p.peak, 0) DESC, h.company_name
            LIMIT 6""")]
    except Exception:
        d["zero_names"] = []

    d["enriched_today"] = one(
        "SELECT COUNT(*) FROM job_enrichments WHERE DATE(enriched_at)=DATE('now')")
    d["desc_pct"] = one(
        "SELECT ROUND(100.0*SUM(description_clean<>'')/COUNT(*),1) "
        "FROM jobs WHERE is_active=1", default=0.0)
    d["enrich_pct"] = one("""
        SELECT ROUND(100.0*COUNT(*)/(SELECT COUNT(*) FROM jobs WHERE is_active=1),1)
        FROM job_enrichments e JOIN jobs j
          ON j.source=e.source AND j.source_id=e.source_id
        WHERE j.is_active=1""", default=0.0)

    # ── needs a human ─────────────────────────────────────────────────────────
    d["flag_up"] = one("SELECT COUNT(*) FROM salary_audit_log "
                       "WHERE DATE(audited_at)=DATE('now') AND action='flag_up'")
    d["lowered"] = one("SELECT COUNT(*) FROM salary_audit_log "
                       "WHERE DATE(audited_at)=DATE('now') AND action='lowered'")

    # ── secret market + vendor budget ─────────────────────────────────────────
    d["hidden"] = one("SELECT COUNT(*) FROM jobs "
                      "WHERE source='linkedin_posts' AND is_active=1")
    d["spend"] = one("SELECT ROUND(SUM(cost_usd),2) FROM vendor_costs "
                     "WHERE strftime('%Y-%m',logged_at)=strftime('%Y-%m','now')",
                     default=0.0)

    # ── top sources of genuinely-new supply ───────────────────────────────────
    d["by_source"] = []
    try:
        d["by_source"] = conn.execute("""
            SELECT source, COUNT(*) n FROM jobs WHERE is_active=1
            GROUP BY source ORDER BY n DESC LIMIT 5""").fetchall()
    except Exception:
        pass

    # ── skills in today's enrichments (case-normalised — the raw column is not) ─
    cnt: Counter = Counter()
    try:
        for (blob,) in conn.execute("""
            SELECT required_skills FROM job_enrichments
            WHERE DATE(enriched_at)=DATE('now')
              AND required_skills IS NOT NULL AND required_skills NOT IN ('','[]')"""):
            try:
                for s in json.loads(blob):
                    if isinstance(s, str) and s.strip():
                        cnt[" ".join(s.strip().lower().split())] += 1
            except Exception:
                pass
    except Exception:
        pass
    d["skills"] = cnt.most_common(5)

    conn.close()

    # Overall verdict drives the banner and the subject line.
    fail_rate = (d["zero_today"] / d["scraped_today"] * 100) if d["scraped_today"] else 0
    d["fail_rate"] = round(fail_rate, 1)
    d["status"] = ("attention" if fail_rate >= 10 or d["zero_today"] >= 20
                   else "ok")
    return d


# ── HTML building blocks ───────────────────────────────────────────────────────

def _stat(value: str, label: str, note: str = "", colour: str = C_INK) -> str:
    note_html = (f'<div style="font:400 11px/1.4 {F_SANS};color:{C_FAINT};'
                 f'padding-top:2px;">{note}</div>') if note else ""
    return (
        f'<td width="25%" style="padding:14px 10px;text-align:center;'
        f'border-right:1px solid {C_RULE};">'
        f'<div style="font:700 26px/1.1 {F_MONO};color:{colour};'
        f'letter-spacing:-0.5px;">{value}</div>'
        f'<div style="font:600 10px/1.4 {F_SANS};color:{C_MUTED};'
        f'text-transform:uppercase;letter-spacing:.08em;padding-top:5px;">{label}</div>'
        f'{note_html}</td>'
    )


def _section(title: str, inner: str, sub: str = "") -> str:
    sub_html = (f'<div style="font:400 12px/1.5 {F_SANS};color:{C_FAINT};'
                f'padding-top:2px;">{sub}</div>') if sub else ""
    return (
        f'<tr><td style="padding:22px 24px 6px;">'
        f'<div style="font:600 11px/1.4 {F_SANS};color:{C_GOLD};'
        f'text-transform:uppercase;letter-spacing:.1em;">{title}</div>{sub_html}'
        f'</td></tr>'
        f'<tr><td style="padding:8px 24px 4px;">{inner}</td></tr>'
    )


def _render_html(d: dict) -> str:
    dt = d["date"].strftime("%A, %d %B %Y")
    delta = d["delta"]
    ok = d["status"] == "ok"

    # ── banner ────────────────────────────────────────────────────────────────
    if ok:
        band, btxt, blabel = C_GOOD, "#FFFFFF", "Pipeline healthy"
    else:
        band, btxt, blabel = C_WARN, "#FFFFFF", "Completed with source failures"

    # ── headline numbers ──────────────────────────────────────────────────────
    if delta.get("available"):
        opened, closed = f"+{delta['opened']:,}", f"−{delta['closed']:,}"
        onote = f"vs {delta['since']}"
        cnote = f"{delta['reopened']:,} reopened"
    else:
        opened = closed = "n/a"
        onote = cnote = "no prior snapshot"
    distinct_note = f"{_n(d['distinct_roles'])} unduplicated"
    enrichment_note = f"{d['enrich_pct']}% covered"

    stats = (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="border-collapse:collapse;background:{C_CARD};">'
        f'<tr>'
        f'{_stat(_n(d["active"]), "Live roles", distinct_note)}'
        f'{_stat(opened, "New today", onote, C_GOOD)}'
        f'{_stat(closed, "Closed today", cnote, C_MUTED)}'
        f'{_stat(_n(d["enriched_today"]), "Enriched", enrichment_note, C_BLUE)}'
        f'</tr></table>'
    )

    # ── needs attention ───────────────────────────────────────────────────────
    alerts = []
    if d["zero_today"]:
        names = ", ".join(escape(n) for n in d["zero_names"])
        more = (f" +{d['zero_today'] - len(d['zero_names'])} more"
                if d["zero_today"] > len(d["zero_names"]) else "")
        alerts.append((
            C_CRIT, f"{d['zero_today']} of {d['scraped_today']} sources returned zero jobs",
            f"{d['fail_rate']}% of the roster. Recorded as real zeros, so they "
            f"corrupt trend data. {names}{more}"))
    if d["flag_up"]:
        alerts.append((
            C_WARN, f"{d['flag_up']} salary estimates flagged too low",
            "Senior titles the audit will not auto-raise — needs a human call. "
            "See salary_audit_log where action='flag_up'."))
    if d["spend"] and d["spend"] >= APIFY_CAP * 0.8:
        alerts.append((
            C_WARN, f"Apify spend ${d['spend']:.2f} of ${APIFY_CAP:.0f} cap",
            "Approaching the monthly hard cap."))

    if alerts:
        rows = "".join(
            f'<tr><td style="padding:10px 12px;border-left:3px solid {c};'
            f'background:{C_ALT};">'
            f'<div style="font:600 13px/1.45 {F_SANS};color:{C_INK};">{escape(h)}</div>'
            f'<div style="font:400 12px/1.55 {F_SANS};color:{C_MUTED};padding-top:3px;">'
            f'{b}</div></td></tr>'
            f'<tr><td style="height:6px;line-height:6px;">&nbsp;</td></tr>'
            for c, h, b in alerts)
        attention = _section(
            "Needs attention",
            f'<table role="presentation" width="100%" cellpadding="0" '
            f'cellspacing="0" style="border-collapse:collapse;">{rows}</table>')
    else:
        attention = _section(
            "Needs attention",
            f'<div style="font:400 13px/1.6 {F_SANS};color:{C_MUTED};'
            f'padding:10px 12px;background:{C_ALT};border-left:3px solid {C_GOOD};">'
            f'Nothing to action. Every source reported and no estimates were '
            f'flagged for review.</div>')

    # ── new roles table ───────────────────────────────────────────────────────
    if d["new_roles"]:
        trs = []
        for r in d["new_roles"]:
            if r["smin"] and r["smax"]:
                pay = f"{r['smin'] // 1000}–{r['smax'] // 1000}k"
            else:
                pay = "—"
            meta = " · ".join(x for x in (r["seniority"], r["job_category"]) if x)
            trs.append(
                f'<tr>'
                f'<td style="padding:9px 10px 9px 0;border-bottom:1px solid {C_RULE};">'
                f'<div style="font:600 13px/1.4 {F_SANS};color:{C_INK};">'
                f'{escape(r["title"][:62])}</div>'
                f'<div style="font:400 11.5px/1.5 {F_SANS};color:{C_FAINT};">'
                f'{escape(r["company"][:40])}{" · " + escape(meta) if meta else ""}</div>'
                f'</td>'
                f'<td align="right" style="padding:9px 0;border-bottom:1px solid {C_RULE};'
                f'font:600 12px/1.4 {F_MONO};color:{C_GOLD};white-space:nowrap;">'
                f'{pay}</td></tr>')
        roles = _section(
            "Highest-paying new roles today",
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'style="border-collapse:collapse;">{"".join(trs)}</table>',
            f"{delta['opened']:,} roles appeared that were not in yesterday's snapshot"
            " · HK$ per month, estimated")
    else:
        roles = ""

    # ── market pulse ──────────────────────────────────────────────────────────
    src_bits = " · ".join(f'{escape(r["source"])} {r["n"]:,}' for r in d["by_source"])
    skills = ", ".join(s.title() for s, _ in d["skills"]) or "none recorded"
    pulse = _section(
        "Coverage",
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="border-collapse:collapse;font:400 12.5px/1.7 {F_SANS};color:{C_MUTED};">'
        f'<tr><td width="34%" style="color:{C_FAINT};">Descriptions</td>'
        f'<td>{d["desc_pct"]}% of live roles</td></tr>'
        f'<tr><td style="color:{C_FAINT};">Hidden market</td>'
        f'<td>{_n(d["hidden"])} recruiter roles on no public board</td></tr>'
        f'<tr><td style="color:{C_FAINT};">Vendor spend</td>'
        f'<td>${d["spend"]:.2f} of ${APIFY_CAP:.0f} monthly cap</td></tr>'
        f'<tr><td style="color:{C_FAINT};">Top sources</td>'
        f'<td>{src_bits}</td></tr>'
        f'<tr><td style="color:{C_FAINT};">Skills in demand</td>'
        f'<td>{escape(skills)}</td></tr>'
        f'</table>')

    return f"""\
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light">
<meta name="supported-color-schemes" content="light">
<title>{escape(PROJECT_NAME)} — {dt}</title>
</head>
<body style="margin:0;padding:0;background:{C_ALT};">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;">
{d['delta'].get('opened', 0)} new roles, {d['delta'].get('closed', 0)} closed,
{d['zero_today']} sources down. {_n(d['active'])} live.
</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
       style="border-collapse:collapse;background:{C_ALT};">
<tr><td align="center" style="padding:24px 12px;">

<table role="presentation" width="600" cellpadding="0" cellspacing="0"
       style="border-collapse:collapse;width:600px;max-width:100%;
              background:{C_PAPER};border:1px solid {C_RULE};">

  <!-- masthead -->
  <tr><td style="background:{C_NAVY};padding:22px 24px 18px;">
    <div style="font:600 10px/1.4 {F_SANS};color:{C_GOLDBG};
                text-transform:uppercase;letter-spacing:.14em;">FinEx Careers</div>
    <div style="font:700 23px/1.25 {F_SERIF};color:#FFFFFF;padding-top:6px;">
      Daily Market Brief</div>
    <div style="font:400 12.5px/1.5 {F_SANS};color:#9FB0C6;padding-top:4px;">
      {dt}</div>
  </td></tr>

  <!-- status band -->
  <tr><td style="background:{band};padding:9px 24px;
                 font:600 11.5px/1.4 {F_SANS};color:{btxt};
                 letter-spacing:.04em;">{blabel}</td></tr>

  <!-- stats -->
  <tr><td style="padding:0;border-bottom:1px solid {C_RULE};">{stats}</td></tr>

  {attention}
  {roles}
  {pulse}

  <!-- footer -->
  <tr><td style="padding:20px 24px 22px;border-top:1px solid {C_RULE};">
    <div style="font:400 11.5px/1.6 {F_SANS};color:{C_FAINT};">
      New and closed counts come from diffing today's database against the
      {escape(str(delta.get('since', 'previous')))} snapshot, not from
      <span style="font-family:{F_MONO};">fetched_at</span>, which records
      last-seen and cannot identify new roles.
      <br>Full run log: <span style="font-family:{F_MONO};">logs/daily_runs.log</span>
      &nbsp;·&nbsp; Panel analysis:
      <span style="font-family:{F_MONO};">docs/MARKET_PANEL_ANALYSIS.html</span>
    </div>
  </td></tr>

</table>
</td></tr></table>
</body></html>"""


def _render_text(d: dict) -> str:
    delta = d["delta"]
    L = []
    L.append("FINEX CAREERS — DAILY MARKET BRIEF")
    L.append(d["date"].strftime("%A, %d %B %Y"))
    L.append("=" * 58)
    L.append("")
    L.append("STATUS: " + ("healthy" if d["status"] == "ok"
                           else "completed with source failures"))
    L.append("")
    L.append(f"Live roles       {_n(d['active'])}  ({_n(d['distinct_roles'])} unduplicated)")
    if delta.get("available"):
        L.append(f"New today        +{delta['opened']:,}  (vs {delta['since']} snapshot)")
        L.append(f"Closed today     -{delta['closed']:,}  ({delta['reopened']:,} reopened)")
    else:
        L.append("New / closed     unavailable — no prior snapshot to diff")
    L.append(f"Enriched today   {_n(d['enriched_today'])}  ({d['enrich_pct']}% covered)")
    L.append("")

    L.append("NEEDS ATTENTION")
    L.append("-" * 58)
    any_alert = False
    if d["zero_today"]:
        any_alert = True
        L.append(f"* {d['zero_today']} of {d['scraped_today']} sources returned zero "
                 f"({d['fail_rate']}%). Recorded as real zeros — corrupts trend data.")
        if d["zero_names"]:
            L.append(f"  {', '.join(d['zero_names'])}")
    if d["flag_up"]:
        any_alert = True
        L.append(f"* {d['flag_up']} salary estimates flagged too low (senior titles, "
                 f"not auto-raised) — needs a human call.")
    if d["spend"] >= APIFY_CAP * 0.8:
        any_alert = True
        L.append(f"* Apify spend ${d['spend']:.2f} of ${APIFY_CAP:.0f} cap.")
    if not any_alert:
        L.append("Nothing to action.")
    L.append("")

    if d["new_roles"]:
        L.append("HIGHEST-PAYING NEW ROLES TODAY")
        L.append("-" * 58)
        for r in d["new_roles"]:
            pay = (f"{r['smin']//1000}-{r['smax']//1000}k"
                   if r["smin"] and r["smax"] else "-")
            L.append(f"  {pay:>10}  {r['title'][:44]}")
            L.append(f"              {r['company'][:44]}")
        L.append("")

    L.append("COVERAGE")
    L.append("-" * 58)
    L.append(f"Descriptions     {d['desc_pct']}% of live roles")
    L.append(f"Hidden market    {_n(d['hidden'])} recruiter roles on no public board")
    L.append(f"Vendor spend     ${d['spend']:.2f} of ${APIFY_CAP:.0f} monthly cap")
    if d["skills"]:
        L.append(f"Skills in demand {', '.join(s.title() for s, _ in d['skills'])}")
    L.append("")
    L.append("New/closed counts diff today's DB against the previous backup "
             "snapshot; fetched_at records last-seen and cannot identify new roles.")
    L.append("Log: logs/daily_runs.log")
    return "\n".join(L)


# ── Public API ─────────────────────────────────────────────────────────────────

def send_failure_alert(
    phase: str,
    error: str,
    jobs_collected: int = 0,
    duration_seconds: int = 0,
) -> bool:
    """Send an immediate alert when the pipeline raises an exception."""
    now      = datetime.now().strftime("%A, %d %B %Y at %H:%M HKT")
    duration = (f"{duration_seconds // 60}m {duration_seconds % 60}s"
                if duration_seconds else "unknown")
    subject  = f"[FAILED] HK Job Board — {phase} — {date.today():%d %b}"

    rows = [("Failed phase", escape(phase)),
            ("Error", f'<span style="font-family:{F_MONO};font-size:12px;">'
                      f'{escape(error[:400])}</span>'),
            ("Jobs before failure", f"{jobs_collected:,}"),
            ("Runtime", duration)]
    body = "".join(
        f'<tr><td width="38%" style="padding:9px 0;border-bottom:1px solid {C_RULE};'
        f'font:400 12px/1.5 {F_SANS};color:{C_FAINT};">{k}</td>'
        f'<td style="padding:9px 0;border-bottom:1px solid {C_RULE};'
        f'font:400 13px/1.5 {F_SANS};color:{C_INK};">{v}</td></tr>'
        for k, v in rows)

    html = f"""\
<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"></head>
<body style="margin:0;background:{C_ALT};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
       style="border-collapse:collapse;background:{C_ALT};">
<tr><td align="center" style="padding:24px 12px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0"
       style="border-collapse:collapse;width:600px;max-width:100%;
              background:{C_PAPER};border:1px solid {C_RULE};">
  <tr><td style="background:{C_NAVY};padding:22px 24px 18px;">
    <div style="font:600 10px/1.4 {F_SANS};color:{C_GOLDBG};
                text-transform:uppercase;letter-spacing:.14em;">FinEx Careers</div>
    <div style="font:700 23px/1.25 {F_SERIF};color:#FFFFFF;padding-top:6px;">
      Pipeline Failed</div>
    <div style="font:400 12.5px/1.5 {F_SANS};color:#9FB0C6;padding-top:4px;">
      {now}</div></td></tr>
  <tr><td style="background:{C_CRIT};padding:9px 24px;
      font:600 11.5px/1.4 {F_SANS};color:#FFFFFF;">Run aborted — data may be incomplete</td></tr>
  <tr><td style="padding:18px 24px 22px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
           style="border-collapse:collapse;">{body}</table>
    <div style="font:400 11.5px/1.6 {F_SANS};color:{C_FAINT};padding-top:16px;">
      Full traceback: <span style="font-family:{F_MONO};">logs/daily_runs.log</span>
    </div></td></tr>
</table></td></tr></table></body></html>"""

    text = (
        f"FINEX CAREERS — PIPELINE FAILED\n{now}\n" + "=" * 58 +
        f"\n\nFailed phase        {phase}\nError               {error}\n"
        f"Jobs before failure {jobs_collected:,}\nRuntime             {duration}\n\n"
        f"Full traceback: logs/daily_runs.log"
    )
    return _send_email(subject, html, text)


def send_daily_summary(db_path: str = "data/jobs.db") -> bool:
    """Query today's stats and send the daily market brief."""
    try:
        d = _collect(db_path)
    except Exception as exc:
        logger.error("Failed to query DB for summary: %s", exc)
        return False

    delta = d["delta"]
    if delta.get("available"):
        head = f"+{delta['opened']} new, {delta['closed']} closed"
    else:
        head = f"{d['active']:,} live"
    tail = f" · {d['zero_today']} sources down" if d["zero_today"] else ""
    subject = f"HK Jobs · {d['date']:%d %b} — {head}{tail}"

    return _send_email(subject, _render_html(d), _render_text(d))


def send_daily_run_result(
    record: "DailyRunRecord", db_path: str = "data/jobs.db"
) -> bool:
    """Send status and phase evidence from the authoritative run record."""
    from hk_jobs.daily_run.model import PhaseStatus, RunStatus

    if record.status is RunStatus.FAILED:
        failed = next(
            (phase for phase in record.phases if phase.status is PhaseStatus.FAILED),
            None,
        )
        return send_failure_alert(
            phase=failed.label if failed else "Daily Run",
            error=(failed.detail if failed else None)
            or f"Run {record.run_id} failed. {record.source_run_url or ''}".strip(),
        )

    try:
        market = _collect(db_path)
    except Exception as exc:
        logger.error("Failed to query DB for Daily Run result: %s", exc)
        return False

    outcome = record.status.value.upper()
    subject = (
        f"HK Jobs · {record.operating_date} — {outcome} · "
        f"{market['active']:,} live Roles"
    )
    phase_rows = "".join(
        f"<tr><td style='padding:6px 10px;border-bottom:1px solid {C_RULE};'>"
        f"{escape(phase.label)}</td>"
        f"<td style='padding:6px 10px;border-bottom:1px solid {C_RULE};'>"
        f"{escape(phase.status.value)}</td>"
        f"<td style='padding:6px 10px;border-bottom:1px solid {C_RULE};'>"
        f"{escape(phase.detail or '')}</td></tr>"
        for phase in record.phases
    )
    html = (
        f"<html><body style='font-family:{F_SANS};color:{C_INK};'>"
        f"<h2>Daily Run: {outcome}</h2>"
        f"<p><strong>{market['active']:,}</strong> live Roles · "
        f"{market['zero_today']} sources down</p>"
        f"<table style='border-collapse:collapse;width:100%;max-width:760px;'>"
        f"<tr><th align='left'>Phase</th><th align='left'>Outcome</th>"
        f"<th align='left'>Detail</th></tr>{phase_rows}</table>"
        f"<p>Run ID: {escape(record.run_id)}</p></body></html>"
    )
    phase_lines = "\n".join(
        f"- {phase.label}: {phase.status.value}"
        + (f" — {phase.detail}" if phase.detail else "")
        for phase in record.phases
    )
    text = (
        f"FINEX CAREERS — DAILY RUN {outcome}\n"
        f"{record.operating_date}\n\n"
        f"{market['active']:,} live Roles · {market['zero_today']} sources down\n\n"
        f"{phase_lines}\n\nRun ID: {record.run_id}"
    )
    return _send_email(subject, html, text)
