# ruff: noqa: E501 -- email-client-safe inline CSS is intentionally kept intact.
"""Select, lock and email the strongest Roles for next week's highlight rail.

Every Sunday the latest database is filtered to Roles that a visitor can
actually open, that were posted recently, and whose monthly salary floor is at
least HK$40,000. The final pass rotates across pay levels and limits repetition
by employer/category so one large bank cannot occupy the whole banner. The
ordered references are then write-once for the coming Monday-to-Sunday week.
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from html import escape
from pathlib import Path
from urllib.parse import urlencode

from hk_jobs.board_visibility import board_visible_sql
from hk_jobs.notifications import _send_email
from hk_jobs.weekly_highlights import WeeklyHighlightRef, lock_weekly_highlights

logger = logging.getLogger(__name__)

DEFAULT_SITE_URL = "https://www.finexcareers.com"
MIN_MONTHLY_SALARY = 40_000
LOOKBACK_DAYS = 14
MAX_PER_EMPLOYER = 2
MAX_PER_CATEGORY = 3


@dataclass(frozen=True)
class HighlightCandidate:
    source: str
    source_id: str
    company: str
    title: str
    category: str
    seniority: str
    posted_at: str
    salary_min: int
    salary_max: int
    salary_confidence: str

    @property
    def salary_band(self) -> str:
        if self.salary_min >= 100_000:
            return "Executive"
        if self.salary_min >= 70_000:
            return "Senior"
        return "Established"


def _candidate_from_row(row: sqlite3.Row) -> HighlightCandidate:
    salary_min = int(row["salary_min"])
    salary_max = int(row["salary_max"] or salary_min)
    return HighlightCandidate(
        source=row["source"],
        source_id=row["source_id"],
        company=row["company"],
        title=row["title"],
        category=row["category"] or "Finance",
        seniority=row["seniority"] or "Experienced",
        posted_at=row["posted_at"] or "",
        salary_min=salary_min,
        salary_max=max(salary_min, salary_max),
        salary_confidence=row["salary_confidence"] or "unknown",
    )


def _pick_diverse(candidates: list[HighlightCandidate], limit: int) -> list[HighlightCandidate]:
    """Round-robin pay bands, while capping employer/category repetition."""
    bands = ("Executive", "Senior", "Established")
    buckets = {
        band: [candidate for candidate in candidates if candidate.salary_band == band]
        for band in bands
    }
    chosen: list[HighlightCandidate] = []
    employer_counts: Counter[str] = Counter()
    category_counts: Counter[str] = Counter()
    chosen_keys: set[tuple[str, str]] = set()

    def allowed(candidate: HighlightCandidate, *, enforce_category: bool = True) -> bool:
        key = (candidate.source, candidate.source_id)
        return (
            key not in chosen_keys
            and employer_counts[candidate.company] < MAX_PER_EMPLOYER
            and (not enforce_category or category_counts[candidate.category] < MAX_PER_CATEGORY)
        )

    def add(candidate: HighlightCandidate) -> None:
        chosen.append(candidate)
        chosen_keys.add((candidate.source, candidate.source_id))
        employer_counts[candidate.company] += 1
        category_counts[candidate.category] += 1

    # First pass guarantees range: the strongest candidate in each pay band
    # gets a turn before the second candidate from any band.
    while len(chosen) < limit:
        made_progress = False
        for band in bands:
            match = next((candidate for candidate in buckets[band] if allowed(candidate)), None)
            if match is None:
                continue
            add(match)
            made_progress = True
            if len(chosen) == limit:
                break
        if not made_progress:
            break

    # If category diversity alone prevented a full email, relax that one cap.
    # The employer cap remains hard: a shortlist dominated by one bank is not
    # a useful editorial choice set.
    if len(chosen) < limit:
        for candidate in candidates:
            if allowed(candidate, enforce_category=False):
                add(candidate)
            if len(chosen) == limit:
                break

    return chosen


def select_weekly_highlight_candidates(
    db_path: str | Path = "data/jobs.db",
    *,
    as_of: date | None = None,
    limit: int = 12,
) -> list[HighlightCandidate]:
    """Return recent, visible, >=HK$40k Roles in editorially useful order."""
    if limit < 1:
        return []
    today = as_of or date.today()
    cutoff = today - timedelta(days=LOOKBACK_DAYS)
    board_where = board_visible_sql(with_hidden=False)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            f"""
            SELECT
                j.source,
                j.source_id,
                j.company,
                COALESCE(NULLIF(e.title_en, ''), j.title) AS title,
                COALESCE(NULLIF(e.job_category, ''), 'Finance') AS category,
                COALESCE(NULLIF(e.seniority, ''), 'Experienced') AS seniority,
                j.posted_at,
                COALESCE(e.salary_hkd_min, e.salary_estimated_min) AS salary_min,
                COALESCE(e.salary_hkd_max, e.salary_estimated_max,
                         e.salary_hkd_min, e.salary_estimated_min) AS salary_max,
                COALESCE(NULLIF(e.salary_estimated_confidence, ''), 'unknown') AS salary_confidence
            FROM jobs j
            JOIN job_enrichments e
              ON e.source = j.source AND e.source_id = j.source_id
            WHERE {board_where}
              AND COALESCE(j.source_tier, 'mainstream') NOT IN ('boutique', 'social')
              AND DATE(j.posted_at) BETWEEN DATE(?) AND DATE(?)
              AND COALESCE(e.salary_hkd_min, e.salary_estimated_min, 0) >= ?
              AND TRIM(j.title) != ''
              AND LOWER(j.title) NOT LIKE '%intern%'
            ORDER BY
              DATE(j.posted_at) DESC,
              CASE e.salary_estimated_confidence
                WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2
              END,
              salary_max DESC,
              j.company ASC
            """,
            (cutoff.isoformat(), today.isoformat(), MIN_MONTHLY_SALARY),
        ).fetchall()
    finally:
        conn.close()

    return _pick_diverse([_candidate_from_row(row) for row in rows], limit)


def _upcoming_week(as_of: date) -> tuple[date, date]:
    days_until_monday = (7 - as_of.weekday()) % 7
    monday = as_of + timedelta(days=days_until_monday)
    return monday, monday + timedelta(days=6)


def _week_label(start: date, end: date) -> str:
    if start.year == end.year and start.month == end.month:
        return f"{start.day}–{end.day} {end.strftime('%b %Y')}"
    if start.year == end.year:
        return f"{start.strftime('%-d %b')}–{end.strftime('%-d %b %Y')}"
    return f"{start.strftime('%-d %b %Y')}–{end.strftime('%-d %b %Y')}"


def _salary_label(candidate: HighlightCandidate) -> str:
    low = f"{candidate.salary_min // 1_000}k"
    high = f"{candidate.salary_max // 1_000}k"
    value = low if low == high else f"{low}–{high}"
    return f"HK${value}/mo"


def _role_url(candidate: HighlightCandidate, site_url: str) -> str:
    params = urlencode(
        {
            "q": candidate.category,
            "role_source": candidate.source,
            "role_id": candidate.source_id,
        }
    )
    return f"{site_url.rstrip('/')}/jobs?{params}"


def lock_next_week_highlights(
    db_path: str | Path = "data/jobs.db",
    *,
    as_of: date | None = None,
    limit: int = 12,
) -> list[WeeklyHighlightRef]:
    """Select and atomically lock the coming week's promotional Role refs."""
    today = as_of or date.today()
    candidates = select_weekly_highlight_candidates(db_path, as_of=today, limit=limit)
    week_start, _ = _upcoming_week(today)
    refs = [
        WeeklyHighlightRef(
            source=candidate.source,
            source_id=candidate.source_id,
            related_search=candidate.category,
        )
        for candidate in candidates
    ]
    return lock_weekly_highlights(db_path, refs, week_start=week_start)


def build_weekly_highlight_email(
    candidates: list[HighlightCandidate],
    *,
    as_of: date | None = None,
    site_url: str = DEFAULT_SITE_URL,
) -> tuple[str, str, str]:
    """Build the subject, HTML and plain-text versions of the curator email."""
    today = as_of or date.today()
    week_start, week_end = _upcoming_week(today)
    label = _week_label(week_start, week_end)
    subject = f"FinEx highlight candidates · {label}"

    cards: list[str] = []
    text_rows: list[str] = []
    for index, candidate in enumerate(candidates, start=1):
        url = _role_url(candidate, site_url)
        title = escape(candidate.title)
        company = escape(candidate.company)
        category = escape(candidate.category)
        seniority = escape(candidate.seniority)
        salary = _salary_label(candidate)
        cards.append(
            f"""
            <tr><td style="padding:0 28px 14px;">
              <a href="{escape(url, quote=True)}" style="display:block;text-decoration:none;color:#11111a;background:#fffef8;border:1px solid #d9d5cb;border-left:5px solid #d8ae50;border-radius:8px;padding:16px 18px;">
                <div style="font:700 11px Arial,sans-serif;letter-spacing:.09em;text-transform:uppercase;color:#53617a;">{index:02d} · {category} · {escape(candidate.salary_band)}</div>
                <div style="font:700 18px Arial,sans-serif;line-height:1.3;color:#11111a;margin-top:7px;">{title}</div>
                <div style="font:600 13px Arial,sans-serif;color:#53617a;margin-top:5px;">{company} · {seniority}</div>
                <div style="font:600 12px Arial,sans-serif;color:#8a6508;margin-top:10px;">{salary} · Open in Careers →</div>
              </a>
            </td></tr>
            """
        )
        text_rows.append(
            f"{index}. {candidate.title} — {candidate.company}\n"
            f"   {candidate.category} · {candidate.salary_band} · {salary}\n"
            f"   {url}"
        )

    if not cards:
        cards.append(
            '<tr><td style="padding:24px 28px;color:#53617a;font:14px Arial,sans-serif;">'
            "No eligible new Roles met the HK$40k floor this week.</td></tr>"
        )
        text_rows.append("No eligible new Roles met the HK$40k floor this week.")

    html = f"""
    <div style="background:#eef1f6;padding:28px 12px;">
      <table role="presentation" style="width:100%;max-width:680px;margin:0 auto;border-collapse:collapse;background:#202d52;border-radius:12px;overflow:hidden;">
        <tr><td style="padding:28px;color:white;">
          <div style="font:700 11px Arial,sans-serif;letter-spacing:.13em;text-transform:uppercase;color:#e2bd68;">This week at FinEx</div>
          <h1 style="font:800 28px Arial,sans-serif;letter-spacing:-.03em;margin:8px 0 5px;">Next week’s strongest Role candidates</h1>
          <p style="font:14px Arial,sans-serif;color:#dbe5ee;margin:0;">{escape(label)} · {len(candidates)} editorial picks</p>
        </td></tr>
        {"".join(cards)}
        <tr><td style="padding:10px 28px 26px;color:#aebad0;font:12px Arial,sans-serif;line-height:1.5;">
          Selected from open, board-visible Roles posted in the last {LOOKBACK_DAYS} days. Minimum estimated monthly salary: HK${MIN_MONTHLY_SALARY // 1_000}k. Maximum two picks per employer.
        </td></tr>
      </table>
    </div>
    """
    text = (
        f"FINEX HIGHLIGHT CANDIDATES · {label}\n\n"
        + "\n\n".join(text_rows)
        + f"\n\nCriteria: open and visible, posted in the last {LOOKBACK_DAYS} days, "
        f"minimum HK${MIN_MONTHLY_SALARY // 1_000}k/month, maximum two per employer."
    )
    return subject, html, text


def send_weekly_highlight_candidates(
    db_path: str | Path = "data/jobs.db",
    *,
    as_of: date | None = None,
    limit: int = 12,
    site_url: str = DEFAULT_SITE_URL,
) -> bool:
    candidates = select_weekly_highlight_candidates(db_path, as_of=as_of, limit=limit)
    today = as_of or date.today()
    week_start, _ = _upcoming_week(today)
    lock_weekly_highlights(
        db_path,
        [
            WeeklyHighlightRef(
                candidate.source,
                candidate.source_id,
                candidate.category,
            )
            for candidate in candidates
        ],
        week_start=week_start,
    )
    subject, html, text = build_weekly_highlight_email(
        candidates,
        as_of=today,
        site_url=site_url,
    )
    logger.info("Sending %d weekly highlight candidates", len(candidates))
    return _send_email(subject, html, text)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Email next week's FinEx highlight Role candidates."
    )
    parser.add_argument("--database", default="data/jobs.db")
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--site-url", default=DEFAULT_SITE_URL)
    args = parser.parse_args()
    sent = send_weekly_highlight_candidates(
        args.database,
        limit=args.limit,
        site_url=args.site_url,
    )
    return 0 if sent else 1


if __name__ == "__main__":
    raise SystemExit(main())
