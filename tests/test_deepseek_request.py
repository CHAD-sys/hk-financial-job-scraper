"""What we actually send DeepSeek per job — the shape that sets the bill.

The 2026-08-16 run spent a real $4.26 enriching 806 roles, 94% of it on thinking
mode's reasoning trace at ~7,000 output tokens a job. Nothing in the suite looked
at the request body, so the switch that cost the money was untested. These tests
pin it: no thinking key, and an answer-sized max_tokens.
"""

from __future__ import annotations

import json

import pytest

from hk_jobs.enrichers.deepseek import DeepSeekEnricher

_ANSWER = {
    "seniority": "mid", "years_experience": 5, "skills": ["excel"],
    "remote_type": "onsite", "job_category": "middle_office",
    "salary_hkd_min": 40000, "salary_hkd_max": 60000,
    "estimated_salary_hkd_min": 40000, "estimated_salary_hkd_max": 60000,
    "estimated_salary_confidence": "medium", "description_summary": "A role.",
    "title_en": "Risk Analyst", "salary_tier": "middle_office", "salary_role": None,
}


class _Response:
    status_code = 200

    def json(self) -> dict:
        return {
            "choices": [{"message": {"content": json.dumps(_ANSWER)}}],
            "usage": {
                "prompt_tokens": 8800, "prompt_cache_hit_tokens": 8500,
                "prompt_cache_miss_tokens": 300, "completion_tokens": 340,
            },
        }


@pytest.fixture
def sent(monkeypatch):
    """Capture the JSON body of the one request enrich_single makes."""
    captured: dict = {}

    class _Client:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def post(self, _url, *, headers, json):  # noqa: A002 — httpx's own kwarg name
            captured.update(json)
            return _Response()

    monkeypatch.setattr("hk_jobs.enrichers.deepseek.httpx.Client", _Client)
    return captured


def _enricher() -> DeepSeekEnricher:
    return DeepSeekEnricher(api_key="test-key")


def test_thinking_mode_is_not_requested(sent):
    """RED before v11: the body carried {"thinking": {"type": "enabled"}}.

    That one key is what turned a ~350-token answer into ~7,000 billed output
    tokens per job. See the v11 changelog before putting it back.
    """
    _enricher().enrich_single("Risk Analyst", "A Bank", description="Do risk things.")
    assert "thinking" not in sent
    assert "reasoning_effort" not in sent


def test_max_tokens_is_sized_for_the_answer_not_a_reasoning_trace(sent):
    """RED before v11: both branches asked for 12,000."""
    enricher = _enricher()

    enricher.enrich_single("Risk Analyst", "A Bank", description="Do risk things.")
    with_description = sent["max_tokens"]
    enricher.enrich_single("Risk Analyst", "A Bank")
    title_only = sent["max_tokens"]

    assert with_description == 700
    assert title_only == 450
    assert title_only < with_description  # the summary field only exists in one branch


def test_sampling_params_return_now_that_thinking_is_off(sent):
    """Thinking mode silently ignored these; without it they are live again."""
    _enricher().enrich_single("Risk Analyst", "A Bank", description="Do risk things.")
    assert sent["temperature"] == 0.2
    assert sent["top_p"] == 0.9


def test_usage_is_still_accumulated_for_the_cost_ledger(sent):
    enricher = _enricher()
    enricher.enrich_single("Risk Analyst", "A Bank", description="Do risk things.")
    assert enricher.usage_totals == {
        "calls": 1, "cache_hit": 8500, "cache_miss": 300, "completion": 340,
    }
