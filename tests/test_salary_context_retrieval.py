"""
ADR 0037 — the candidate shortlist is what actually decides whether a Role gets
priced.

v14 stopped showing the model the 105-role table and shows it a per-posting
shortlist instead, with instructions to return null if nothing fits. That makes
`build_salary_context` the real classifier: the model can only be as good as
the list it is handed. On the 2026-09-02 board it was handed the wrong list
often enough that 916 Roles came back with `salary_tier = null`.

Three faults, each pinned below:

1. a description phrase scored the same 12 as a title phrase, so one boilerplate
   "wealth management" in an employer blurb ranked `private_banking_rm` above
   every compliance role on a job titled "Compliance Manager";
2. `_GENERIC` stripped role keys down to nothing, so `operations_general` — the
   catch-all for the board's largest unpriced family — could never be offered;
3. grade words ("assistant", "manager") were treated as function evidence.
"""

from __future__ import annotations

from hk_jobs import salary_anchors
from hk_jobs.salary_context import (
    _DEFAULT_CANDIDATE_LIMIT,
    _role_vocabulary,
    build_salary_context,
)


def _ranked(context) -> list[str]:
    return [candidate.role for candidate in context.candidates]


def test_every_published_role_can_be_offered_to_the_model():
    """RED before ADR 0037: `operations_general` and `insurance_finance_operations`
    reduced to only `_GENERIC` tokens and had no vocabulary, so no posting could
    ever surface them — the model was never given the chance to pick them."""
    unreachable = [
        f"{tier}/{role}"
        for tier, table in salary_anchors.TABLES.items()
        for role in (table.get("roles") or {})
        if not any(_role_vocabulary(role))
    ]
    assert unreachable == []


def test_a_title_match_outranks_a_boilerplate_description_phrase():
    """RED before ADR 0037: private_banking_rm(16) ranked above compliance_banking(5)
    on this posting, purely because the blurb said "wealth management"."""
    context = build_salary_context(
        title="Assistant Compliance Manager / Compliance Manager (General Compliance)",
        description=(
            "Support the private bank's wealth management business. Handle compliance "
            "advisory, regulatory liaison and policy review."
        ),
    )
    ranked = _ranked(context)
    assert "compliance_banking" in ranked
    assert ranked.index("compliance_banking") < ranked.index("private_banking_rm")


def test_a_grade_word_is_not_function_evidence():
    """"Assistant" says how senior a job is, never what it does. RED before
    ADR 0037: it made `assistant_private_banker` a top candidate for any title
    containing the word."""
    context = build_salary_context(
        title="Assistant Manager, Financial Reporting",
        description="Prepare monthly management and financial reporting packs.",
    )
    ranked = _ranked(context)
    assert "assistant_private_banker" not in ranked[:3]


def test_a_back_office_operations_title_reaches_the_operations_catch_all():
    context = build_salary_context(
        title="Senior Officer, Operation Support",
        description="Provide back office operations support for the digital bank.",
    )
    assert "operations_general" in _ranked(context)


def test_an_aml_posting_reaches_the_financial_crime_role():
    """RED before ADR 0037: this was offered six relationship-manager roles,
    because "Transaction" token-matched `transaction_banking_rm`, and `fcc_aml`
    had no vocabulary at all."""
    context = build_salary_context(
        title="Assistant Manager, Transaction Monitoring (1 Year Contract)",
        description="Review alerts from the transaction monitoring system and "
                    "investigate potential money laundering.",
    )
    assert _ranked(context)[0] == "fcc_aml"


def test_a_budgeting_posting_reaches_the_fpa_role():
    """RED before ADR 0037: the ONLY candidate offered was
    front_office/asset_management_sales."""
    context = build_salary_context(
        title="Assistant Manager / Manager, Cost Management (Financial Budgeting)",
        description="Lead cost management, financial budgeting and forecasting.",
    )
    assert _ranked(context)[0] == "fpa_corporate"


def test_a_chinese_processing_title_is_not_left_without_candidates():
    context = build_salary_context(
        title="Processing Officer 審批處理主任 (政府項目)",
        description="Handle application processing and verification for a government scheme.",
    )
    assert context.candidates


def test_the_shortlist_is_capped_and_ranked():
    context = build_salary_context(
        title="Senior Manager, Risk and Compliance, Banking Operations",
        description="Risk, compliance, audit, operations, finance and technology.",
    )
    assert len(context.candidates) <= _DEFAULT_CANDIDATE_LIMIT
    scores = [candidate.score for candidate in context.candidates]
    assert scores == sorted(scores, reverse=True)


def test_the_block_tells_the_model_to_pick_a_best_fit_not_to_decline():
    """ADR 0037 flips the default. The old header said "only when the posting
    clearly fits it; otherwise return null", which is what the model obeyed."""
    context = build_salary_context(
        title="Compliance Manager", description="Regulatory compliance advisory."
    )
    rendered = context.render()
    assert "best fits" in rendered
    assert "only when the posting clearly fits it" not in rendered


def test_an_unrelated_title_still_declines():
    """Flipping the default must not make the shortlist accept anything."""
    context = build_salary_context(title="Office Happiness Champion")
    assert context.requires_review
    assert "Return null" in context.render()


# ── follow-up: the two retrieval gaps the ADR 0037 verification pass exposed ──

def test_a_structured_products_dealer_reaches_the_trading_desk():
    """The verification run offered this posting exactly one candidate:
    back_office_operations/human_resources. "dealer" and "structured products"
    are what a HK trading-desk advert says; neither was in the vocabulary."""
    context = build_salary_context(
        title="Dealer, Structured Products Team",
        description="Price and execute structured product trades for institutional "
                    "clients; manage desk risk.",
    )
    assert _ranked(context)[0] == "global_markets_trading"


def test_an_infrastructure_engineer_outranks_unrelated_front_office_roles():
    """RED before this change: it_infrastructure_support tied at score 3 with
    corporate_finance_ma_ecm_dcm and private_banking_rm."""
    context = build_salary_context(
        title="Senior Load Balancer Engineer - ETS",
        description="Own load balancer platforms, F5 estate, network and middleware "
                    "infrastructure.",
    )
    ranked = _ranked(context)
    assert ranked[0] == "it_infrastructure_support"
    assert "private_banking_rm" not in ranked[:3]
