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

from hk_jobs.enrichers import deepseek
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
    # These three field names were stale here (estimated_salary_hkd_min/max,
    # estimated_salary_confidence) — the real schema is salary_estimated_*, per
    # deepseek.py's _PROMPT_WITH_DESC/_PROMPT_TITLE_ONLY. Fixed in passing while
    # adding salary_grade (v13, coordinate pricing); this file only pins request
    # shape and error handling, so the mismatch never surfaced as a failure.
    "salary_estimated_min": 40000, "salary_estimated_max": 60000,
    "salary_estimated_confidence": "medium", "description_summary": "A role.",
    "title_en": "Risk Analyst", "salary_tier": "middle_office", "salary_role": None,
    "salary_grade": None,
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


def test_insurance_tier_prompt_requires_explicit_tier_2_membership():
    """The model must not recreate the blanket discount removed from runtime."""
    prompt = deepseek._SALARY_INSTRUCTIONS

    assert "ANY OTHER" not in prompt
    assert "Absence from Tier 1 is not evidence of Tier 2" in prompt
    assert "No configured insurer is currently classified as Tier 2" in prompt


def test_insurance_tier_prompt_renders_the_anchor_registry(monkeypatch):
    monkeypatch.setattr(
        deepseek.salary_anchors,
        "INSURANCE_TIER_2_SLUGS",
        frozenset({"bupa-hk", "hang-seng-insurance"}),
    )

    policy = deepseek._render_insurance_tier_policy()

    assert "bupa-hk, hang-seng-insurance" in policy
    assert "15% Tier 2 discount" in policy
    assert "No configured insurer" not in policy


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


def test_salary_prompt_uses_short_per_job_candidates_not_the_full_anchor_catalog(sent):
    _enricher().enrich_single(
        "Senior Product Manager, Wealth and Investments",
        "DBS Bank",
        description="Own the wealth product roadmap and investment proposition.",
        company_slug="dbs-hk",
    )

    prompt = sent["messages"][0]["content"]
    assert "ANCHOR CANDIDATES (classification only)" in prompt
    assert "middle_office / product_management" in prompt
    assert "Employer cohorts: dbs_sized_banks" in prompt
    # The old request embedded every role and band (~54k chars). v14 has only
    # the candidate list, keeping the static instruction well below that size.
    assert len(prompt) < 35_000


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
    # The 2026-08-22 evaluation exposed a long tail: 88/400 description-backed
    # calls exhausted 10,000 tokens. 16,000 keeps room for a full trace and the
    # final JSON, without removing the cost ceiling altogether.
    assert with_description == 16_000
    assert title_only == 8_000


# ── truncation must never be silent again ────────────────────────────────────

def test_a_truncated_answer_raises_a_named_error(sent):
    """RED at v11: this surfaced as json.JSONDecodeError, indistinguishable from a
    transient fault, and was retried three times before being dropped."""
    sent["_reply"] = _payload('{"seniority": "mi', finish_reason="length")
    with pytest.raises(TruncatedAnswer):
        _enricher().enrich_single("Risk Analyst", "A Bank", description="Do risk things.")


def test_started_but_server_capped_answer_is_never_accepted(sent):
    """A non-empty reply is still incomplete when DeepSeek reports `length`.

    The client is non-streaming, so it cannot remove the server's cap after
    generation has begun. Persisting this started response would turn an
    incomplete model answer into a false salary estimate.
    """
    sent["_reply"] = _payload(json.dumps(_ANSWER), finish_reason="length")
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


def test_contract_duration_does_not_discount_the_base_salary(sent):
    """Equivalent permanent and fixed-term Roles use the same base-pay calibration."""
    _enricher().enrich_single(
        "Manager, Accounting (6 months contract)",
        "CMB Wing Lung Bank",
        description="Manage accounting for retail finance and credit cards.",
    )
    prompt = _prompt(sent)
    assert "do not discount base salary because a Role is contract" in prompt
    assert "apply a 10-20% discount vs the equivalent permanent role" not in prompt


def test_cmb_smaller_bank_calibration_reaches_the_model(sent):
    """The standalone evaluator sees the same CMB policy as the final clamp."""
    _enricher().enrich_single(
        "Mobile App Product Manager, Digital Banking Department",
        "CMB Wing Lung Bank Limited",
        description="Own the bank's mobile application roadmap and releases.",
    )
    prompt = _prompt(sent)
    assert "CMB Wing Lung" in prompt
    assert "Product Manager and Team Lead: HK$45,000-60,000" in prompt
    assert "AVP and unambiguous Manager grade: HK$40,000-55,000" in prompt


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
