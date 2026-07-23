"""Tests for the deterministic salary clamp (hk_jobs.salary_clamp)."""
from hk_jobs.salary_clamp import (
    BOUTIQUE_SALARY_MULTIPLIER,
    GLOBAL_MAX_MONTHLY_HKD,
    _LADDERS,
    _TABLES,
    clamp_salary,
    fix_salary_magnitude,
)


def _band(tier: str, level: str) -> list[int]:
    return _LADDERS[tier][level]


def test_over_band_max_is_capped_to_ceiling():
    lo, ceil = _band("middle_office", "senior")
    assert clamp_salary("middle_office", "senior", lo, ceil + 50_000) == (lo, ceil)


def test_within_band_is_left_untouched():
    lo, ceil = _band("middle_office", "senior")
    assert clamp_salary("middle_office", "senior", lo, ceil - 5_000) == (lo, ceil - 5_000)


def test_below_band_is_never_raised():
    # Down-only: a conservative estimate below the band floor stays as-is.
    lo, _ = _band("middle_office", "senior")
    assert clamp_salary("middle_office", "senior", lo - 20_000, lo - 5_000) == (lo - 20_000, lo - 5_000)


def test_min_is_widened_when_it_exceeds_capped_max():
    lo, ceil = _band("back_office_operations", "junior")
    # Both endpoints above the ceiling -> max clamps to the ceiling, and since that pulls
    # max below the original min, min widens to 50% of max rather than collapsing flat.
    out_min, out_max = clamp_salary("back_office_operations", "junior", ceil + 20_000, ceil + 40_000)
    assert out_max == ceil
    assert out_min == round(ceil * 0.5)


def test_unknown_tier_passes_through():
    assert clamp_salary("not_a_tier", "senior", 90_000, 180_000) == (90_000, 180_000)


def test_missing_seniority_passes_through():
    assert clamp_salary("middle_office", None, 90_000, 180_000) == (90_000, 180_000)


def test_none_estimates_pass_through():
    assert clamp_salary("front_office", "lead", None, None) == (None, None)


def test_front_office_lead_ceiling_enforced():
    # A lead role the model priced above even the front-office ceiling gets capped.
    lo, ceil = _band("front_office", "lead")
    assert clamp_salary("front_office", "lead", lo, ceil + 100_000) == (lo, ceil)


def test_lower_tier_has_a_lower_ceiling_than_front_office():
    # Since the 2026-07-21 merge, coarse tier ladders are loose envelopes (max across
    # the tier's roles per grade) — at lead level both tiers can reach the 200k global
    # cap (back office contains IT-leadership ladders). The meaningful tier separation
    # survives at junior level, and the per-role ceilings do the real tightening.
    assert _band("back_office_operations", "junior")[1] < _band("front_office", "junior")[1]


def test_named_grade_rows_map_directly_not_by_fraction():
    # "senior" must hit the VP row of a standardized ladder, not interpolate up to
    # the Director row (index-rounding bug with 5-row ladders).
    from hk_jobs.salary_clamp import _TABLES, _role_ceiling
    vp_ceiling = _TABLES["middle_office"]["roles"]["compliance_banking"]["VP"][1]
    assert _role_ceiling("middle_office", "compliance_banking", "senior") == vp_ceiling


# ── global absolute ceiling ─────────────────────────────────────────────────────

def test_global_ceiling_applies_even_with_no_tier_or_role():
    assert clamp_salary(None, None, 50_000, 500_000) == (50_000, GLOBAL_MAX_MONTHLY_HKD)


def test_global_ceiling_applies_on_top_of_a_matched_tier_band():
    # front_office/lead's own ceiling is already <= 200k post-recalibration, but the
    # global cap must hold even if a band were ever re-widened above it.
    lo, ceil = _band("front_office", "lead")
    assert ceil <= GLOBAL_MAX_MONTHLY_HKD
    assert clamp_salary("front_office", "lead", lo, 10_000_000) == (lo, GLOBAL_MAX_MONTHLY_HKD)


# ── granular named-role ceiling ──────────────────────────────────────────────────

def test_named_role_tightens_below_the_tier_ladder():
    # treasury's "senior" row (Senior Treasury Manager) sits below the whole
    # corporate_finance_accounting tier's senior ceiling — matching the role tightens it.
    tier_ceiling = _band("corporate_finance_accounting", "senior")[1]
    out_min, out_max = clamp_salary(
        "corporate_finance_accounting", "senior", 20_000, tier_ceiling, role="treasury",
    )
    assert out_max < tier_ceiling


def test_unknown_role_falls_back_to_tier_ceiling_only():
    tier_ceiling = _band("middle_office", "senior")[1]
    assert clamp_salary(
        "middle_office", "senior", 20_000, tier_ceiling + 50_000, role="not_a_real_role",
    ) == (20_000, tier_ceiling)


# ── bank management-grade title caps ────────────────────────────────────────────

def test_bank_avp_title_capped_at_70k():
    out = clamp_salary(
        "front_office", "senior", 40_000, 180_000,
        company_slug="hsbc-hk", title="Assistant Vice President, Compliance",
    )
    assert out == (40_000, 70_000)


def test_bank_director_capped_at_160k_even_if_role_band_is_higher():
    out = clamp_salary(
        "front_office", "lead", 100_000, 200_000,
        company_slug="goldman-sachs", title="Director, Global Markets",
    )
    assert out[1] == 160_000


def test_bank_plain_manager_title_treated_as_avp_grade():
    out = clamp_salary(
        "middle_office", "senior", 30_000, 150_000,
        company_slug="standard-chartered-hk", title="Relationship Manager",
    )
    assert out[1] == 70_000


def test_non_bank_company_is_not_subject_to_bank_title_caps():
    # front_office/lead's own ceiling is 200k post-recalibration; use an estimate below
    # that so only the (absent) bank-grade cap could possibly tighten it further.
    out = clamp_salary(
        "front_office", "lead", 100_000, 195_000,
        company_slug="blackrock-hk", title="Vice President, Portfolio Management",
    )
    assert out[1] == 195_000  # untouched — BlackRock is asset management, not a bank


# ── insurance management-grade title caps ───────────────────────────────────────

def test_insurance_senior_manager_capped_at_80k():
    out = clamp_salary(
        "insurance", "senior", 50_000, 150_000,
        company_slug="aia-hk", title="Senior Manager, Underwriting",
    )
    assert out[1] == 80_000


def test_insurance_associate_director_capped_at_150k():
    out = clamp_salary(
        "insurance", "lead", 100_000, 190_000,
        company_slug="manulife-hk", title="Associate Director, Actuarial",
    )
    assert out[1] == 150_000


def test_insurance_director_capped_at_200k_global():
    # The insurance "director" grade cap and the absolute global ceiling are both
    # 200k post-recalibration, so this mainly regression-tests that an extreme
    # over-estimate still lands at 200k rather than passing through untouched.
    out = clamp_salary(
        "insurance", "lead", 100_000, 500_000,
        company_slug="fwd-insurance", title="Director, Distribution",
    )
    assert out[1] == 200_000


def test_insurance_vp_at_fwd_falls_back_to_global_cap_only():
    # No tighter number is specified for VP/AVP at FWD/Sun Life/Manulife (they outrank
    # Director there) — they still can't exceed the global 200k ceiling.
    out = clamp_salary(
        "front_office", "lead", 100_000, 500_000,
        company_slug="sun-life-hk", title="Vice President, Investments",
    )
    assert out[1] == GLOBAL_MAX_MONTHLY_HKD


# ── company_slug is what's matched, not the free-text display name ─────────────

def test_citi_display_name_variant_still_gets_capped_via_slug():
    # Real bug found in production: "Citi" (and "Citibank (Hong Kong) Limited") don't
    # contain the substring "citibank" that a free-text keyword match would need — but
    # every Citi posting shares slug "citibank-hk" regardless of which adapter scraped
    # it, so matching on the slug catches all of them uniformly.
    out = clamp_salary(
        "front_office", "lead", 100_000, 200_000,
        company_slug="citibank-hk", title="Director, Global Markets",
    )
    assert out[1] == 160_000


def test_unrecognised_slug_is_not_capped():
    out = clamp_salary(
        "front_office", "lead", 100_000, 195_000,
        company_slug="some-new-boutique-firm", title="Director, Advisory",
    )
    assert out[1] == 195_000


# ── boutique-tier salary discount ───────────────────────────────────────────────

def test_boutique_tier_scales_both_endpoints_by_70_percent():
    out = clamp_salary(
        "middle_office", "mid", 40_000, 60_000, source_tier="boutique",
    )
    assert out == (round(40_000 * BOUTIQUE_SALARY_MULTIPLIER), round(60_000 * BOUTIQUE_SALARY_MULTIPLIER))


def test_mainstream_tier_is_not_discounted():
    out = clamp_salary(
        "middle_office", "mid", 40_000, 60_000, source_tier="mainstream",
    )
    assert out == (40_000, 60_000)


def test_missing_source_tier_is_not_discounted():
    out = clamp_salary("middle_office", "mid", 40_000, 60_000)
    assert out == (40_000, 60_000)


def test_boutique_discount_applies_after_other_ceilings():
    # A boutique job at a bank-recognised slug would be unusual, but the discount
    # must still apply on top of whatever the earlier ceilings produced.
    tier_ceiling = _band("middle_office", "senior")[1]
    out = clamp_salary(
        "middle_office", "senior", 20_000, tier_ceiling + 50_000, source_tier="boutique",
    )
    assert out[1] == round(tier_ceiling * BOUTIQUE_SALARY_MULTIPLIER)


def test_boutique_none_estimates_pass_through():
    assert clamp_salary("front_office", "lead", None, None, source_tier="boutique") == (None, None)


# ── never emit a single-value range ─────────────────────────────────────────────

def test_exact_equality_at_the_global_cap_is_widened_not_left_flat():
    # Real production bug: an MD-level role whose anchor band collapsed to exactly
    # [200000, 200000] after the 200k global cap produced a literal "200k-200k" range.
    out = clamp_salary(None, None, GLOBAL_MAX_MONTHLY_HKD, GLOBAL_MAX_MONTHLY_HKD)
    assert out == (round(GLOBAL_MAX_MONTHLY_HKD * 0.5), GLOBAL_MAX_MONTHLY_HKD)


def test_widened_range_is_never_flat_even_after_boutique_discount():
    out = clamp_salary(None, None, 100_000, 100_000, source_tier="boutique")
    scaled = round(100_000 * BOUTIQUE_SALARY_MULTIPLIER)
    assert out == (round(scaled * 0.5), scaled)


# ── floor raise: the one down-only exception ────────────────────────────────────

def test_undershoot_below_matched_band_is_raised_to_the_band():
    # Real production case: "Account Opening Officer, Commercial Banking" matched
    # back_office_operations/operations_general/junior (Analyst row) but the model's raw
    # estimate (11200-14400) undershot that row's own floor (14500-18500).
    lo, hi = _TABLES["back_office_operations"]["roles"]["operations_general"]["Analyst"]
    out = clamp_salary(
        "back_office_operations", "junior", 11_200, 14_400, role="operations_general",
    )
    assert out == (lo, hi)


def test_min_only_slightly_below_floor_is_lifted_without_touching_max():
    lo, hi = _TABLES["back_office_operations"]["roles"]["operations_general"]["Analyst"]
    # max is already within the row's own ceiling (the pre-existing role-ceiling step
    # would clip anything above hi anyway) -> only the min needs lifting here.
    out = clamp_salary(
        "back_office_operations", "junior", lo - 2_000, hi - 1_000,
        role="operations_general",
    )
    assert out == (lo, hi - 1_000)


def test_estimate_within_matched_band_is_not_touched_by_floor_raise():
    lo, hi = _TABLES["back_office_operations"]["roles"]["operations_general"]["Analyst"]
    mid_lo, mid_hi = lo + 500, hi - 500
    assert clamp_salary(
        "back_office_operations", "junior", mid_lo, mid_hi, role="operations_general",
    ) == (mid_lo, mid_hi)


def test_magnitude_glitch_is_scaled_up_by_1000():
    # Real production bug: DeepSeek returned salary_estimated_min/max as bare
    # "thousands shorthand" (31, 48) instead of the full HKD amount (31000, 48000).
    assert fix_salary_magnitude(31, 48) == (31_000, 48_000)


def test_normal_scale_values_are_left_untouched_by_magnitude_fix():
    assert fix_salary_magnitude(40_000, 80_000) == (40_000, 80_000)


def test_magnitude_fix_handles_none_min():
    assert fix_salary_magnitude(None, 66) == (None, 66_000)


def test_magnitude_fix_passes_through_none_max():
    assert fix_salary_magnitude(40_000, None) == (40_000, None)


def test_floor_raise_does_not_apply_to_idiosyncratic_fallback_roles():
    # accounting_support's ladder isn't standardized onto the named grade rows (its keys
    # are "Accounts Receivable / Payable", "Graduate Accountant", etc.), so _role_band
    # returns None for it (only _role_ceiling's proportional fallback applies) — an
    # undershoot here must pass through untouched, since we're not confident enough
    # in the match to trust its floor.
    out = clamp_salary(
        "corporate_finance_accounting", "senior", 1_000, 2_000, role="accounting_support",
    )
    assert out == (1_000, 2_000)
