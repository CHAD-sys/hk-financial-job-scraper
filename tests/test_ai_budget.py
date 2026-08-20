"""A hard per-run spend cap on DeepSeek, enforced mid-run.

Why this exists, from the real billing dashboard rather than our own ledger:

  2026-08-16   $6.31    thinking mode, 806 roles enriched
  2026-08-17   ~$5.80   same shape

Nothing stopped either. `DEEPSEEK_DAILY_ENRICH_LIMIT` caps how many ROLES a run
may enrich, which is only a proxy for cost and a bad one — the same 1,200-role
limit costs ~$0.08 with thinking off and ~$8 with it on. A budget has to be
denominated in the thing being spent.

Two further facts this module is built around, both learned the hard way:

  * `ai_usage.estimated_cost_usd` is an ESTIMATE from hardcoded prices, and it
    ran ~5-10x low. It is not a bill and must never be treated as one.
  * The ledger recorded 3,476 calls over a window the dashboard billed 16,527
    for, so a guard that reads only the stored ledger is reading ~21% of the
    truth. This one counts what THIS process has spent, in-process, as it goes.
"""

from __future__ import annotations

import pytest

from hk_jobs.ai_budget import (
    DEFAULT_RUN_BUDGET_USD,
    BudgetExceeded,
    RunBudget,
    estimate_cost_usd,
)


def test_cost_estimate_weights_output_far_above_cached_input():
    """Output is the expensive token. A guard that weighted them equally would
    let a thinking-mode run through while blocking a cheap one."""
    cached_heavy = estimate_cost_usd(cache_hit=1_000_000, cache_miss=0, completion=0)
    output_heavy = estimate_cost_usd(cache_hit=0, cache_miss=0, completion=1_000_000)
    assert output_heavy > cached_heavy * 10


def test_budget_allows_spending_up_to_the_cap():
    budget = RunBudget(limit_usd=1.00)
    budget.record(cache_hit=100_000, cache_miss=1_000, completion=10_000)
    assert not budget.exhausted
    budget.check()  # must not raise


def test_budget_blocks_once_the_cap_is_passed():
    budget = RunBudget(limit_usd=0.01)
    budget.record(cache_hit=0, cache_miss=0, completion=5_000_000)
    assert budget.exhausted
    with pytest.raises(BudgetExceeded):
        budget.check()


def test_the_error_names_the_numbers_a_human_needs():
    """A budget stop that does not say what it spent is a mystery, not a guard."""
    budget = RunBudget(limit_usd=0.50)
    budget.record(cache_hit=0, cache_miss=0, completion=50_000_000)
    try:
        budget.check()
    except BudgetExceeded as exc:
        message = str(exc)
    assert "0.50" in message
    assert "$" in message


def test_a_zero_or_negative_limit_disables_the_guard():
    """An explicit opt-out for a deliberate backfill, rather than editing code."""
    budget = RunBudget(limit_usd=0)
    budget.record(cache_hit=0, cache_miss=0, completion=500_000_000)
    assert not budget.exhausted
    budget.check()


def test_the_default_cap_is_well_under_the_nights_that_caused_this():
    """08-16 billed $6.31. The default must stop long before that."""
    assert 0 < DEFAULT_RUN_BUDGET_USD <= 2.00


def test_budget_reads_its_limit_from_the_environment(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_RUN_BUDGET_USD", "3.25")
    assert RunBudget.from_environment().limit_usd == 3.25


def test_a_malformed_environment_value_falls_back_to_the_default(monkeypatch):
    """Never fail open on a typo — an unparseable cap must not mean 'no cap'."""
    monkeypatch.setenv("DEEPSEEK_RUN_BUDGET_USD", "one dollar")
    assert RunBudget.from_environment().limit_usd == DEFAULT_RUN_BUDGET_USD


# ── the enricher must actually stop ──────────────────────────────────────────

def test_the_enricher_stops_calling_once_the_budget_is_gone(monkeypatch):
    """The guard is worthless if it only reports after the money is spent."""
    import json

    import hk_jobs.enrichers.deepseek as ds

    calls = {"n": 0}

    class _Response:
        status_code = 200

        def json(self):
            calls["n"] += 1
            return {
                "choices": [{"message": {"content": json.dumps({"seniority": "mid"})},
                             "finish_reason": "stop"}],
                # Each call burns a big chunk of output, as thinking mode does.
                "usage": {"prompt_cache_hit_tokens": 8_500,
                          "prompt_cache_miss_tokens": 300,
                          "completion_tokens": 7_000},
            }

    class _Client:
        def __init__(self, *_a, **_k): pass
        def __enter__(self): return self
        def __exit__(self, *_e): return False
        def post(self, _url, *, headers, json): return _Response()

    monkeypatch.setattr(ds.httpx, "Client", _Client)

    enricher = ds.DeepSeekEnricher(api_key="k", run_budget=RunBudget(limit_usd=0.02))
    jobs = [("jobsdb", str(i), f"Analyst {i}", "A description long enough to matter.")
            for i in range(200)]
    results = enricher.enrich_batch(jobs)

    assert calls["n"] < 200, "the enricher kept calling after the budget was gone"
    assert any(v is not None for v in results.values()), "it should keep what it bought"
    assert enricher.usage_totals.get("budget_stopped")
