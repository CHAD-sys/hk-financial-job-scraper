"""Persist DeepSeek token usage and a reproducible cost estimate.

The API response is the source of truth for tokens. Prices are deliberately
centralised here and stamped into the resulting dollar estimate; if DeepSeek
changes its public tariff, one small module changes instead of dashboard SQL.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime
from typing import Any

# USD per one million tokens.
#
# These were "checked 2026-08-10" and were measured WRONG on 2026-08-20: against
# the real billing dashboard ($26.46 for 171.0M tokens over 08/02-08/20, a
# blended $0.155/1M) the old values under-estimated the bill by roughly 5-10x,
# and a night that actually cost several dollars was reported internally as
# "$0.21". They now come from hk_jobs/ai_budget.py, calibrated upward from
# observed spend so an estimate errs toward caution.
#
# TWO CAVEATS, both load-bearing:
#   * This is still an ESTIMATE. `estimated_cost_usd` is not a bill. The only
#     authority on spend is platform.deepseek.com/usage.
#   * The ledger is incomplete anyway — it recorded 3,476 calls over a window
#     the dashboard billed 16,527 for (~21%). Do not size a decision on a SUM
#     over this table without checking it against the dashboard first.
from hk_jobs.ai_budget import (
    CACHE_HIT_PER_MILLION as _CACHE_HIT_PER_MILLION,
    CACHE_MISS_PER_MILLION as _CACHE_MISS_PER_MILLION,
    OUTPUT_PER_MILLION as _OUTPUT_PER_MILLION,
)

_DDL = """
CREATE TABLE IF NOT EXISTS ai_usage (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              TEXT NOT NULL,
    phase               TEXT NOT NULL,
    model               TEXT NOT NULL,
    calls               INTEGER NOT NULL DEFAULT 0,
    roles_processed     INTEGER NOT NULL DEFAULT 0,
    prompt_cache_hit_tokens  INTEGER NOT NULL DEFAULT 0,
    prompt_cache_miss_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens   INTEGER NOT NULL DEFAULT 0,
    estimated_cost_usd  REAL NOT NULL DEFAULT 0,
    recorded_at         TEXT NOT NULL,
    UNIQUE (run_id, phase, model)
)
"""


def run_id() -> str:
    """Stable ID on GitHub Actions; a useful timestamp for a local run."""
    return os.environ.get("GITHUB_RUN_ID", "").strip() or datetime.now(UTC).strftime(
        "local-%Y%m%dT%H%M%SZ"
    )


def estimate_cost_usd(*, cache_hit: int, cache_miss: int, completion: int) -> float:
    return round(
        (
            cache_hit * _CACHE_HIT_PER_MILLION
            + cache_miss * _CACHE_MISS_PER_MILLION
            + completion * _OUTPUT_PER_MILLION
        )
        / 1_000_000,
        6,
    )


def usage_from_payload(payload: dict[str, Any]) -> dict[str, int]:
    usage = payload.get("usage") or {}
    hit = int(usage.get("prompt_cache_hit_tokens") or 0)
    miss = int(usage.get("prompt_cache_miss_tokens") or 0)
    prompt = int(usage.get("prompt_tokens") or 0)
    if not hit and not miss:
        miss = prompt
    return {
        "calls": 1,
        "cache_hit": hit,
        "cache_miss": miss,
        "completion": int(usage.get("completion_tokens") or 0),
    }


def add_usage(total: dict[str, int], payload: dict[str, Any]) -> None:
    one = usage_from_payload(payload)
    for key, value in one.items():
        total[key] = total.get(key, 0) + value


def record(
    db_path: str,
    *,
    phase: str,
    model: str,
    totals: dict[str, int],
    roles_processed: int,
    source_run_id: str | None = None,
    increment: bool = False,
) -> None:
    calls = max(0, int(totals.get("calls", 0)))
    hit = max(0, int(totals.get("cache_hit", 0)))
    miss = max(0, int(totals.get("cache_miss", 0)))
    completion = max(0, int(totals.get("completion", 0)))
    stamp = datetime.now(UTC).isoformat()
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        with conn:
            conn.execute(_DDL)
            conflict = (
                "calls=ai_usage.calls+excluded.calls, "
                "roles_processed=ai_usage.roles_processed+excluded.roles_processed, "
                "prompt_cache_hit_tokens=ai_usage.prompt_cache_hit_tokens+excluded.prompt_cache_hit_tokens, "
                "prompt_cache_miss_tokens=ai_usage.prompt_cache_miss_tokens+excluded.prompt_cache_miss_tokens, "
                "completion_tokens=ai_usage.completion_tokens+excluded.completion_tokens, "
                "estimated_cost_usd=ai_usage.estimated_cost_usd+excluded.estimated_cost_usd, "
                "recorded_at=excluded.recorded_at"
                if increment
                else
                "calls=excluded.calls, roles_processed=excluded.roles_processed, "
                "prompt_cache_hit_tokens=excluded.prompt_cache_hit_tokens, "
                "prompt_cache_miss_tokens=excluded.prompt_cache_miss_tokens, "
                "completion_tokens=excluded.completion_tokens, "
                "estimated_cost_usd=excluded.estimated_cost_usd, recorded_at=excluded.recorded_at"
            )
            conn.execute(
                f"""
                INSERT INTO ai_usage (
                    run_id, phase, model, calls, roles_processed,
                    prompt_cache_hit_tokens, prompt_cache_miss_tokens,
                    completion_tokens, estimated_cost_usd, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (run_id, phase, model) DO UPDATE SET {conflict}
                """,
                (
                    source_run_id or run_id(),
                    phase,
                    model,
                    calls,
                    max(0, int(roles_processed)),
                    hit,
                    miss,
                    completion,
                    estimate_cost_usd(
                        cache_hit=hit, cache_miss=miss, completion=completion
                    ),
                    stamp,
                ),
            )
    finally:
        conn.close()
