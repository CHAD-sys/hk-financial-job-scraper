"""What we actually send DeepSeek per job — the shape that sets the bill.

History, because both directions of this switch have now caused an incident:

- Before v11 the body carried `{"thinking": {"type": "enabled"}}` with a blanket
  12,000 max_tokens. The 2026-08-16 run spent $4.26 on 806 roles, ~94% of it on
  reasoning traces nobody read.
- v11 turned thinking off and cut max_tokens to 700/450, sized for a "~350-token
  answer". The answer is bigger than that. Every call on 2026-08-19 came back at
  exactly 700.0 output tokens — truncated mid-JSON — failed to parse, burned all
  three retries, and wrote NOTHING. Two nights produced zero enrichments while
  still billing.
- v12 (here) restores thinking, because the v9 A/B test showed it genuinely picks
  tiers and roles better, and re-sizes max_tokens PER TASK instead of one blanket
  number. Crucially it also makes truncation loud: that is the failure that hid
  for two days behind a generic retry.

These tests pin all three of those decisions.
"""

from __future__ import annotations

import json

import pytest

from hk_jobs.enrichers.deepseek import (
    MAX_TOKENS_TITLE_ONLY,
    MAX_TOKENS_WITH_DESCRIPTION,
    DeepSeekEnricher,
    TruncatedAnswer,
)
from hk_jobs.salary_corrections import Correction

_ANSWER = {
    "seniority": "mid", "years_experience": 5, "skills": ["excel"],
    "remote_type": "onsite", "job_category": "middle_office",
    "salary_hkd_min": 40000, "salary_hkd_max": 60000,
    "estimated_salary_hkd_min": 40000, "estimated_salary_hkd_max": 60000,
    "estimated_salary_confidence": "medium", "description_summary": "A role.",
    "title_en": "Risk Analyst", "salary_tier": "middle_office", "salary_role": None,
}


def _payload(content: str, finish_reason: str = "stop") -> dict:
    return {
        "choices": [{"message": {"content": content}, "finish_reason": finish_reason}],
        "usage": {
            "prompt_tokens": 8800, "prompt_cache_hit_tokens": 8500,
            "prompt_cache_miss_tokens": 300, "completion_tokens": 340,
        },
    }


class _Response:
    status_code = 200

    def __init__(self, payload: dict):
        self._payload = payload

    def json(self) -> dict:
        return self._payload


@pytest.fixture
def sent(monkeypatch):
    """Capture the JSON body of the one request enrich_single makes."""
    captured: dict = {}
    captured["_reply"] = _payload(json.dumps(_ANSWER))

    class _Client:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def post(self, _url, *, headers, json):  # noqa: A002 — httpx's own kwarg name
            captured.update(json)
            return _Response(captured["_reply"])

    monkeypatch.setattr("hk_jobs.enrichers.deepseek.httpx.Client", _Client)
    return captured


def _enricher() -> DeepSeekEnricher:
    return DeepSeekEnricher(api_key="test-key")


# ── the switch that sets the bill ────────────────────────────────────────────

def test_thinking_mode_is_requested(sent):
    """v12: back on. The v9 A/B test showed measurably better tier/role selection."""
    _enricher().enrich_single("Risk Analyst", "A Bank", description="Do risk things.")
    assert sent["thinking"] == {"type": "enabled"}


def test_reasoning_effort_is_left_at_the_default(sent):
    """Never send "max": v9.2 burned the whole DeepSeek balance in ~9 minutes on it
    for no proven quality gain. The A/B test that justified thinking used default
    effort, so default is the validated setting."""
    _enricher().enrich_single("Risk Analyst", "A Bank", description="Do risk things.")
    assert "reasoning_effort" not in sent


def test_sampling_params_are_not_sent_under_thinking(sent):
    """DeepSeek silently ignores temperature/top_p when thinking is on. Sending them
    implies a control we do not have."""
    _enricher().enrich_single("Risk Analyst", "A Bank", description="Do risk things.")
    assert "temperature" not in sent
    assert "top_p" not in sent


# ── the allocation that broke it ─────────────────────────────────────────────

def test_max_tokens_is_allocated_per_task(sent):
    """RED at v11: both branches asked for an answer-sized budget and truncated.

    Two independent requirements. The budget must cover a reasoning trace (the
    observed spend under thinking was ~7,000 output tokens a role), and the
    title-only branch must get less than the description branch — it has no
    posting to reason over and no description_summary to write.
    """
    enricher = _enricher()

    enricher.enrich_single("Risk Analyst", "A Bank", description="Do risk things.")
    with_description = sent["max_tokens"]
    enricher.enrich_single("Risk Analyst", "A Bank")
    title_only = sent["max_tokens"]

    assert with_description == MAX_TOKENS_WITH_DESCRIPTION
    assert title_only == MAX_TOKENS_TITLE_ONLY
    assert title_only < with_description
    # Observed consumption under thinking was ~7,000 output tokens per role; a
    # budget at or below that truncates the answer, which is exactly the v11 bug.
    assert with_description > 7_000


# ── truncation must never be silent again ────────────────────────────────────

def test_a_truncated_answer_raises_a_named_error(sent):
    """RED at v11: this surfaced as json.JSONDecodeError, indistinguishable from a
    transient fault, and was retried three times before being dropped."""
    sent["_reply"] = _payload('{"seniority": "mi', finish_reason="length")
    with pytest.raises(TruncatedAnswer):
        _enricher().enrich_single("Risk Analyst", "A Bank", description="Do risk things.")


def test_thinking_that_eats_the_whole_budget_raises_the_same_error(sent):
    """With thinking on, an exhausted budget returns EMPTY content rather than a
    partial answer — a different symptom of the same problem."""
    sent["_reply"] = _payload("", finish_reason="length")
    with pytest.raises(TruncatedAnswer):
        _enricher().enrich_single("Risk Analyst", "A Bank", description="Do risk things.")


def test_truncations_are_counted_so_a_run_can_see_them(sent):
    """The two-day outage was invisible because nothing counted this."""
    sent["_reply"] = _payload("", finish_reason="length")
    enricher = _enricher()
    result = enricher._enrich_with_retry("Risk Analyst", description="Do risk things.")
    assert result is None
    assert enricher.usage_totals["truncated"] >= 1


def test_usage_is_still_accumulated_for_the_cost_ledger(sent):
    enricher = _enricher()
    enricher.enrich_single("Risk Analyst", "A Bank", description="Do risk things.")
    assert enricher.usage_totals["calls"] == 1
    assert enricher.usage_totals["cache_hit"] == 8500
    assert enricher.usage_totals["cache_miss"] == 300
    assert enricher.usage_totals["completion"] == 340


# ── Human corrections reaching the model ─────────────────────────────────────
# The write side (job_edit) and the selection side (salary_corrections) are
# tested elsewhere. What is tested here is the join between them: that a
# correction actually lands in the request body, and — the property that keeps
# the nightly bill flat — that an irrelevant one changes nothing at all.


def _prompt(sent) -> str:
    return sent["messages"][0]["content"]


#: The evidence block's own lead-in. NOT the bare words "HUMAN CORRECTIONS":
#: Step 6 of the static salary instructions names the block in order to explain
#: how to treat it, so those words are in every prompt whether or not any
#: correction was attached.
_BLOCK_MARKER = "our team reviewed these similar roles"


def test_a_relevant_correction_reaches_the_model(sent):
    enricher = DeepSeekEnricher(
        api_key="test-key",
        salary_corrections=[
            Correction(
                title="Credit Analyst", company="Industrial Bank", seniority="mid",
                category=None, old_min=35000, old_max=60000,
                new_min=42000, new_max=68000,
            ),
        ],
    )
    enricher.enrich_single("Senior Credit Analyst", "A Bank", description="Do credit things.")
    prompt = _prompt(sent)
    assert _BLOCK_MARKER in prompt
    assert "HK$42,000-68,000" in prompt


def test_an_irrelevant_correction_leaves_the_prompt_untouched(sent):
    """The one that matters for cost. If an unrelated correction perturbed the
    prompt, every admin edit would change what ~6,000 nightly calls send."""
    baseline_enricher = DeepSeekEnricher(api_key="test-key")
    baseline_enricher.enrich_single("Risk Analyst", "A Bank", description="Do risk things.")
    baseline = _prompt(sent)

    enricher = DeepSeekEnricher(
        api_key="test-key",
        salary_corrections=[
            Correction(
                title="Marine Biologist", company="Ocean Co", seniority="mid",
                category=None, old_min=1, old_max=2, new_min=3, new_max=4,
            ),
        ],
    )
    enricher.enrich_single("Risk Analyst", "A Bank", description="Do risk things.")
    assert _prompt(sent) == baseline


def test_an_enricher_given_no_corrections_behaves_exactly_as_before(sent):
    _enricher().enrich_single("Risk Analyst", "A Bank", description="Do risk things.")
    assert _BLOCK_MARKER not in _prompt(sent)
