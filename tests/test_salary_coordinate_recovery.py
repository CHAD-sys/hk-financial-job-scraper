"""
ADR 0037 follow-up — three ways a correct classification was being thrown away.

Measured on the 2026-09-02 nightly: 500 Roles attempted, 338 answered, and 116
of those answered came back with no salary. Replaying them through the three
fixes here recovers 60 (66% -> 83% priced).

  A. the model answers with the GRADE in the role field   -> 10
  B. a valid role whose grade row is unknown is priced from
     the seniority slice of its ladder instead of rejected -> 15
  C. the model declines while OUR retrieval was confident  -> 50
"""

from __future__ import annotations

from hk_jobs import salary
from hk_jobs.salary_clamp import (
    normalise_coordinate,
    price_from_partial_coordinate,
    price_from_role_envelope,
)

# ── A. role/grade arrived in the wrong fields ────────────────────────────────

def test_a_grade_returned_as_the_role_is_recovered():
    """`network_engineer` is a GRADE inside it_infrastructure_support worth
    45,000-65,000. The old code looked for a ROLE of that name, found none, and
    binned an exact published cell."""
    assert normalise_coordinate("back_office_operations", "network_engineer", None) == (
        "back_office_operations", "it_infrastructure_support", "network_engineer",
    )
    assert normalise_coordinate("middle_office", "security_engineer", None) == (
        "middle_office", "cybersecurity", "security_engineer",
    )


def test_a_recovered_coordinate_prices_to_its_exact_cell():
    lo, hi = salary.finalise(
        None, None,
        tier="back_office_operations", role="it_infrastructure_support",
        grade="network_engineer", seniority="senior", coordinate_only=True,
    )
    assert (lo, hi) == (45_000, 65_000)


def test_a_valid_coordinate_is_left_exactly_as_it_is():
    assert normalise_coordinate("middle_office", "cybersecurity", "security_engineer") == (
        "middle_office", "cybersecurity", "security_engineer",
    )


def test_a_name_in_neither_field_is_not_invented_into_one():
    """Pure lookup: it can move a name into the field the table says it belongs
    in, never conjure a role that does not exist."""
    assert normalise_coordinate("middle_office", "not_a_real_thing", None) == (
        "middle_office", "not_a_real_thing", None,
    )


# ── B. a wide ladder is narrowed by seniority, not rejected ──────────────────

def test_a_wide_ladder_is_narrowed_by_seniority_instead_of_refused():
    """change_project_management spans 21,500-200,000 (9.3x) — past the width
    guard. With a seniority we can take the slice of the ladder it occupies."""
    assert price_from_role_envelope("middle_office", "change_project_management") is None
    band = price_from_partial_coordinate("middle_office", "change_project_management", "junior")
    assert band is not None
    lo, hi = band
    assert lo < hi and hi <= 200_000
    assert hi < 200_000, "a junior must not inherit the top of the ladder"


def test_seniority_windows_move_up_the_ladder():
    role = ("front_office", "global_markets_trading")
    junior = price_from_partial_coordinate(*role, "junior")
    senior = price_from_partial_coordinate(*role, "senior")
    assert junior and senior
    assert senior[0] > junior[0] and senior[1] > junior[1]


def test_without_a_seniority_a_ladder_wide_range_is_still_refused():
    """The guard still applies when there is nothing to narrow with — a
    junior-to-Head span is not an estimate."""
    assert price_from_partial_coordinate("middle_office", "compliance_banking", None) is None


# ── C. adopt our own top candidate when the model declines ───────────────────

class _Candidate:
    def __init__(self, tier, role, score):
        self.tier, self.role, self.score = tier, role, score
        self.grades = ("Analyst",)


class _Context:
    def __init__(self, *candidates):
        self.candidates = candidates


def _enricher():
    from hk_jobs.enrichers.deepseek import DeepSeekEnricher
    return DeepSeekEnricher(api_key="test")


def test_a_declined_coordinate_is_filled_from_a_confident_top_candidate():
    """RED before this change: the model returned a null coordinate for 90 Roles
    on the 2026-09-02 nightly, 28 of them while our own scorer had the answer
    (Receptionist -> secretarial_admin, Cyber Security -> cybersecurity(37))."""
    enricher = _enricher()
    ctx = _Context(_Candidate("middle_office", "cybersecurity", 37))
    out = enricher._adopt_top_candidate(
        {"salary_tier": None, "salary_role": None, "salary_grade": None}, ctx, "Cyber Security"
    )
    assert out["salary_tier"] == "middle_office"
    assert out["salary_role"] == "cybersecurity"
    assert out["salary_grade"] is None      # priced from the seniority window
    assert out["salary_estimated_confidence"] == "low"


def test_a_weak_top_candidate_is_not_adopted():
    """The override needs OUR side to be confident too — a 2-point coincidence
    is not evidence, and a wrong role is a permanent public figure."""
    enricher = _enricher()
    ctx = _Context(_Candidate("middle_office", "cybersecurity", 2))
    out = enricher._adopt_top_candidate({"salary_tier": None}, ctx, "Something Vague")
    assert out.get("salary_tier") is None


def test_an_empty_candidate_block_is_not_adopted():
    enricher = _enricher()
    out = enricher._adopt_top_candidate({"salary_tier": None}, _Context(), "Office Cat")
    assert out.get("salary_tier") is None


def test_a_coordinate_the_model_did_name_is_never_overridden():
    """It read the posting; we did not. Only a DECLINE is filled in."""
    enricher = _enricher()
    ctx = _Context(_Candidate("middle_office", "cybersecurity", 99))
    out = enricher._adopt_top_candidate(
        {"salary_tier": "insurance", "salary_role": "claims", "salary_grade": "Manager"},
        ctx, "Claims Manager",
    )
    assert (out["salary_tier"], out["salary_role"]) == ("insurance", "claims")
