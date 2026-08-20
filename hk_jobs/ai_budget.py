"""A hard, in-process spend cap on DeepSeek enrichment.

WHY THIS EXISTS
---------------
From the real billing dashboard — not our own ledger:

    2026-08-16   $6.31    thinking mode on, 806 Roles enriched
    2026-08-17   ~$5.80   same shape
    08/02-08/20  $26.46 total, 16,527 requests, 171.0M tokens

Nothing stopped either night. The only lever that existed was
`DEEPSEEK_DAILY_ENRICH_LIMIT`, which caps how many ROLES a run may enrich — a
proxy for cost, and a bad one: the same 1,200-role limit costs pennies with
thinking off and several dollars with it on. A budget has to be denominated in
the thing actually being spent.

TWO THINGS THIS MODULE REFUSES TO TRUST
---------------------------------------
1. **`ai_usage.estimated_cost_usd` is not a bill.** It is computed from prices
   hardcoded in `hk_jobs/ai_usage.py`, and measured against the dashboard it ran
   roughly 5-10x LOW. The prices below are re-derived from observed spend and
   are deliberately biased HIGH, so this guard trips early rather than late. An
   over-cautious cap costs a few unenriched Roles; an under-cautious one costs
   money nobody noticed.

2. **The stored ledger is incomplete.** Over a window the dashboard billed
   16,527 requests for, our `ai_usage` table recorded 3,476 — about 21%. A guard
   that queried that table would be reading a fifth of the truth. This one counts
   what THIS process has spent, in-process, as the run proceeds, so it is exact
   for the run it is guarding regardless of what got persisted.

Mirrors the posture of `hk_jobs/posts/budget.py` (the Apify cap): a hard stop,
not a warn-only log line.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ── Prices, USD per 1,000,000 tokens ─────────────────────────────────────────
#
# NOT the published tariff — these are calibrated upward from observed billing
# and should be replaced the moment someone checks platform.deepseek.com/pricing.
#
# The calibration: across 08/02-08/20 the dashboard billed $26.46 for 171.0M
# tokens, a blended $0.155/1M. Our previous constants (0.0028 / 0.14 / 0.28)
# predicted roughly a third of the real bill on the observed token mix, which is
# how a "$0.21 night" was reported for a night that cost several times that.
# Output is weighted far above cached input because output is what thinking mode
# spends, and thinking mode is what produced the $6.31 day.
CACHE_HIT_PER_MILLION = 0.014
CACHE_MISS_PER_MILLION = 0.28
OUTPUT_PER_MILLION = 0.84

#: Default per-run ceiling. The nights that prompted this were $5.80-$6.31, so
#: the default has to stop long before that while still allowing an ordinary
#: night's work. Override with DEEPSEEK_RUN_BUDGET_USD; 0 disables the guard for
#: a deliberate backfill.
DEFAULT_RUN_BUDGET_USD = 1.50

_ENV_VAR = "DEEPSEEK_RUN_BUDGET_USD"


class BudgetExceeded(RuntimeError):
    """The run has spent its DeepSeek allowance and must stop calling."""


def estimate_cost_usd(*, cache_hit: int, cache_miss: int, completion: int) -> float:
    """Best-effort USD for a token triple, biased high on purpose."""
    return (
        cache_hit / 1_000_000 * CACHE_HIT_PER_MILLION
        + cache_miss / 1_000_000 * CACHE_MISS_PER_MILLION
        + completion / 1_000_000 * OUTPUT_PER_MILLION
    )


@dataclass
class RunBudget:
    """Tracks one run's spend and refuses to let it pass `limit_usd`.

    Thread-safe: the enricher is driven from a ThreadPoolExecutor, so the
    accumulator has to be, or the cap leaks by however many workers are running.
    """

    limit_usd: float = DEFAULT_RUN_BUDGET_USD
    spent_usd: float = 0.0
    calls: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @classmethod
    def from_environment(cls, environ: dict | None = None) -> "RunBudget":
        raw = (environ if environ is not None else os.environ).get(_ENV_VAR, "")
        try:
            limit = float(str(raw).strip()) if str(raw).strip() else DEFAULT_RUN_BUDGET_USD
        except (TypeError, ValueError):
            # A typo must never mean "no cap" — that is the failure this guards.
            logger.warning(
                "%s=%r is not a number; falling back to the $%.2f default.",
                _ENV_VAR, raw, DEFAULT_RUN_BUDGET_USD,
            )
            limit = DEFAULT_RUN_BUDGET_USD
        return cls(limit_usd=limit)

    @property
    def disabled(self) -> bool:
        return self.limit_usd is None or self.limit_usd <= 0

    @property
    def exhausted(self) -> bool:
        return not self.disabled and self.spent_usd >= self.limit_usd

    def record(self, *, cache_hit: int, cache_miss: int, completion: int) -> None:
        cost = estimate_cost_usd(
            cache_hit=cache_hit, cache_miss=cache_miss, completion=completion
        )
        with self._lock:
            self.spent_usd += cost
            self.calls += 1

    def check(self) -> None:
        """Raise if the allowance is gone. Called BEFORE each request."""
        if self.exhausted:
            raise BudgetExceeded(
                f"DeepSeek run budget spent: ${self.spent_usd:.2f} of "
                f"${self.limit_usd:.2f} over {self.calls} calls. Stopping before the "
                f"next request. Raise {_ENV_VAR} for a deliberate backfill, or set it "
                "to 0 to disable the cap entirely."
            )
