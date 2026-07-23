"""
Month-to-date Apify spend tracking and the $30/mo hard cap
(PLAN_LINKEDIN_POSTS.md decision #6).

No cost-cap enforcement of any kind exists elsewhere in this codebase today —
DeepSeek enrichment doesn't even log token costs. This is new ground, not a
convention to mirror, so it's deliberately simple: one table (vendor_costs,
created in migrations.migrate_to_phase_26), one running SUM query, and a
hard stop rather than a warn-only log line. A brand-new paid-vendor
integration with no track record yet should not be able to silently blow
through budget because nobody was watching the log.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

WARN_THRESHOLD_USD = 25.0
HARD_CAP_USD = 30.0


@dataclass
class BudgetStatus:
    month_to_date_usd: float
    warn: bool
    blocked: bool


def month_to_date_spend(db_path: str, *, as_of: datetime | None = None) -> float:
    """Sum cost_usd from vendor_costs for the current calendar month (UTC)."""
    now = as_of or datetime.now(UTC)
    month_prefix = now.strftime("%Y-%m")
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM vendor_costs "
            "WHERE substr(logged_at, 1, 7) = ?",
            (month_prefix,),
        ).fetchone()
        return float(row[0])
    finally:
        conn.close()


def check_budget(db_path: str, *, as_of: datetime | None = None) -> BudgetStatus:
    """
    Return the current budget status. Call this BEFORE making an Apify call.

    `blocked=True` means the caller must skip the call entirely — the month-
    to-date spend has already reached HARD_CAP_USD. `warn=True` (without
    blocked) means spend has crossed WARN_THRESHOLD_USD and should be logged
    loudly so it's visible in the daily report, but calls may continue.
    """
    spend = month_to_date_spend(db_path, as_of=as_of)
    status = BudgetStatus(
        month_to_date_usd=spend,
        warn=spend >= WARN_THRESHOLD_USD,
        blocked=spend >= HARD_CAP_USD,
    )
    if status.blocked:
        logger.error(
            "Apify budget cap reached: $%.2f spent this month (cap $%.2f) — "
            "skipping remaining vendor calls until next month",
            spend, HARD_CAP_USD,
        )
    elif status.warn:
        logger.warning(
            "Apify spend at $%.2f this month (warn threshold $%.2f, cap $%.2f)",
            spend, WARN_THRESHOLD_USD, HARD_CAP_USD,
        )
    return status


def record_cost(
    db_path: str,
    *,
    vendor: str,
    actor: str,
    run_kind: str,
    items: int,
    cost_usd: float,
) -> None:
    """Log one vendor call's cost. Call this AFTER a successful Apify call."""
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            conn.execute(
                "INSERT INTO vendor_costs (logged_at, vendor, actor, run_kind, items, cost_usd) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (datetime.now(UTC).isoformat(), vendor, actor, run_kind, items, cost_usd),
            )
        logger.info(
            "Vendor cost logged: %s/%s (%s) — %d items, $%.4f",
            vendor, actor, run_kind, items, cost_usd,
        )
    finally:
        conn.close()
