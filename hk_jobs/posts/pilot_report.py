"""
LP-4 pilot deliverable (PLAN_LINKEDIN_POSTS.md decision #11): a one-page
summary of promoted jobs, % truly hidden, precision, and cost — the numbers
the go/no-go decision for LP-5 (UI + PocketBase) is based on.

Honesty notes, matching the plan's own caveats:
  - Precision here is the automated confidence-threshold PROXY from
    hk_jobs.posts.metrics (share of promotions with extraction_confidence >=
    threshold), NOT the plan's real precision metric, which is a MANUAL
    spot-check by a human reading a sample of promoted posts. This module
    can't perform that read; it prints a sample of promoted jobs sized for
    exactly that manual check instead of fabricating a precision number.
  - Apify cost is real (read from vendor_costs). DeepSeek cost is NOT
    tracked anywhere in this codebase (confirmed: no token/cost logging
    exists in llm_client.py, enrichers/deepseek.py, or tech_filter.py) — this
    report states the DeepSeek CALL COUNT, not a dollar figure, rather than
    inventing a per-token price.
  - Volume/week is extrapolated from whatever window has actually run so
    far, which may be much shorter than the plan's nominal "3-4 days."
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime

from hk_jobs.posts.metrics import compute_metrics
from hk_jobs.posts.promote import SOURCE

SPOT_CHECK_SAMPLE_SIZE = 15


@dataclass
class PilotReport:
    window_start: str | None
    window_days: float
    promoted_total: int
    truly_hidden: int
    pct_truly_hidden: float
    high_confidence_proxy_pct: float
    apify_cost_to_date: float
    apify_cost_per_day: float
    apify_extrapolated_monthly: float
    deepseek_calls_this_window: int
    spot_check_sample: list[dict] = field(default_factory=list)


def generate_pilot_report(db_path: str) -> PilotReport:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        window_start = conn.execute(
            "SELECT MIN(fetched_at) FROM linkedin_posts"
        ).fetchone()[0]

        apify_cost = conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM vendor_costs WHERE vendor='apify'"
        ).fetchone()[0]

        deepseek_calls = conn.execute(
            "SELECT COUNT(*) FROM linkedin_posts WHERE extraction_result_json IS NOT NULL"
        ).fetchone()[0]

        sample_rows = conn.execute(
            """
            SELECT jobs.title, jobs.company, jobs.locations, jobs.extraction_confidence,
                   linkedin_posts.post_url
            FROM jobs
            JOIN linkedin_posts ON linkedin_posts.post_urn = jobs.source_id
            WHERE jobs.source = ? AND jobs.is_active = 1
            ORDER BY RANDOM() LIMIT ?
            """,
            (SOURCE, SPOT_CHECK_SAMPLE_SIZE),
        ).fetchall()
    finally:
        conn.close()

    window_days = _window_days(window_start)
    metrics = compute_metrics(db_path)

    apify_per_day = apify_cost / window_days if window_days > 0 else 0.0

    return PilotReport(
        window_start=window_start,
        window_days=round(window_days, 2),
        promoted_total=metrics.promoted_active,
        truly_hidden=metrics.truly_hidden,
        pct_truly_hidden=metrics.pct_truly_hidden,
        high_confidence_proxy_pct=metrics.pct_high_confidence,
        apify_cost_to_date=round(apify_cost, 4),
        apify_cost_per_day=round(apify_per_day, 4),
        apify_extrapolated_monthly=round(apify_per_day * 30, 2),
        deepseek_calls_this_window=deepseek_calls,
        spot_check_sample=[dict(r) for r in sample_rows],
    )


def _window_days(window_start: str | None) -> float:
    if not window_start:
        return 0.0
    try:
        start = datetime.fromisoformat(window_start)
        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
        delta = datetime.now(UTC) - start
        return max(delta.total_seconds() / 86400, 0.01)  # floor to avoid /0 on same-day runs
    except ValueError:
        return 0.0


def format_report(r: PilotReport) -> str:
    lines = [
        "# Secret Market — LP-4 Pilot Report",
        "",
        f"Window: {r.window_start or 'n/a'} -> now (~{r.window_days} days)",
        "",
        "## Numbers the plan's go/no-go decision is based on",
        f"- Promoted jobs (active): **{r.promoted_total}**",
        f"- Truly hidden (no cross-source match): **{r.truly_hidden} ({r.pct_truly_hidden}%)**",
        f"- High-confidence automated proxy (>= threshold): {r.high_confidence_proxy_pct}% "
        "— NOT a substitute for the manual spot-check below",
        "",
        "## Cost",
        f"- Apify spend to date: **${r.apify_cost_to_date}** "
        f"(~${r.apify_cost_per_day}/day over this window)",
        f"- Extrapolated monthly (Apify only): **${r.apify_extrapolated_monthly}**",
        f"- DeepSeek calls this window: {r.deepseek_calls_this_window} "
        "(no cost tracking exists for DeepSeek anywhere in this codebase — "
        "not a fabricated dollar figure, see module docstring)",
        "",
        f"## Manual precision spot-check sample ({len(r.spot_check_sample)} random promoted jobs)",
        "Read each of these against its original post and judge: genuine open mandate, "
        "reasonable title/location extraction? This is the plan's actual precision metric "
        "— a human read, not an automated score.",
        "",
    ]
    for row in r.spot_check_sample:
        conf = row["extraction_confidence"]
        lines.append(
            f"- [{row['company']}] {row['title']} — {row['locations']} "
            f"(confidence {conf}) — {row['post_url']}"
        )

    lines += [
        "",
        "## Caveats",
        "- Volume/week is extrapolated from a small window and may not represent steady state.",
        "- % truly hidden and the high-confidence proxy are computed over every post-derived "
        "job seen so far, not just this window — solid on a per-post basis regardless of "
        "window length (plan decision #12).",
        "- Precision is ONLY as good as the manual read above — the automated proxy is not "
        "a substitute (LP-0 bake-off already showed keyword-only precision overstates the "
        "true rate; the same caution applies to any purely automated confidence proxy).",
    ]
    return "\n".join(lines)
