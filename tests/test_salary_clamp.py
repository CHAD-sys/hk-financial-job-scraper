"""Tests for the deterministic salary clamp (hk_jobs.salary_clamp)."""
from hk_jobs.salary_clamp import (
    _LADDERS,
    _TABLES,
    BOUTIQUE_SALARY_MULTIPLIER,
    GLOBAL_MAX_MONTHLY_HKD,
    INTERNSHIP_MAX_MONTHLY_HKD,
    clamp_salary,
    employer_salary_overlay,
    fix_salary_magnitude,
    manager_grade_floor,
    price_from_coordinate,
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
    # Compliance is a control function, so it is tiered accordingly. Tiering it
    # `front_office` (as this case did before 2026-08-19) now EXEMPTS it from the flat
    # grade ceilings — see `test_a_front_office_desk_is_exempt_from_the_flat_grade_ceiling`
    # — which is exactly why the tier, not the title, has to be right for a control role.
    out = clamp_salary(
        "middle_office", "senior", 40_000, 180_000,
        company_slug="hsbc-hk", title="Assistant Vice President, Compliance",
    )
    # SUPERSEDED 2026-08-19 by Morris H.'s title_grade_bands_monthly_hkd: the old
    # management_grade_caps table was a CEILING; the band is a range and is
    # authoritative for both endpoints. See tests/test_title_grade_bands.py.
    # The floor is the upgrade: a ceiling-only table could never have raised 40k.
    assert out == (50_000, 70_000)


def test_bank_director_capped_at_160k_even_if_role_band_is_higher():
    # Tier changed from front_office on 2026-08-19: revenue desks are now exempt from
    # the flat bank grade ceilings, so a front_office Director is bounded by the
    # front_office ladder (HK$200,000) rather than by the HK$160,000 Director cap. The
    # cap itself is unchanged and still governs every non-front-office desk.
    out = clamp_salary(
        "middle_office", "lead", 100_000, 200_000,
        company_slug="goldman-sachs", title="Director, Global Markets",
    )
    # SUPERSEDED 2026-08-19 by Morris H.'s title_grade_bands_monthly_hkd: the old
    # management_grade_caps table was a CEILING; the band is a range and is
    # authoritative for both endpoints. See tests/test_title_grade_bands.py.
    # Bank Director is now 100k-150k, tighter than the old 160k cap.
    assert out[1] == 150_000


def test_bank_relationship_manager_title_is_not_treated_as_the_avp_grade():
    out = clamp_salary(
        "middle_office", "senior", 30_000, 150_000,
        company_slug="standard-chartered-hk", title="Relationship Manager",
    )
    assert out == (30_000, 150_000)


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
    # SUPERSEDED 2026-08-19 by Morris H.'s title_grade_bands_monthly_hkd: the old
    # management_grade_caps table was a CEILING; the band is a range and is
    # authoritative for both endpoints. See tests/test_title_grade_bands.py.
    # Insurance Associate Director is now 80k-120k.
    assert out[1] == 120_000


def test_insurance_director_capped_at_200k_global():
    # The insurance "director" grade cap and the absolute global ceiling are both
    # 200k post-recalibration, so this mainly regression-tests that an extreme
    # over-estimate still lands at 200k rather than passing through untouched.
    out = clamp_salary(
        "insurance", "lead", 100_000, 500_000,
        company_slug="fwd-insurance", title="Director, Distribution",
    )
    # SUPERSEDED 2026-08-19 by Morris H.'s title_grade_bands_monthly_hkd: the old
    # management_grade_caps table was a CEILING; the band is a range and is
    # authoritative for both endpoints. See tests/test_title_grade_bands.py.
    # Insurance Director is now 120k-150k; the extreme over-estimate is still
    # pulled down, which is what this test actually guards.
    assert out[1] == 150_000


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
        "middle_office", "lead", 100_000, 200_000,
        company_slug="citibank-hk", title="Director, Global Markets",
    )
    # SUPERSEDED 2026-08-19 by Morris H.'s title_grade_bands_monthly_hkd: the old
    # management_grade_caps table was a CEILING; the band is a range and is
    # authoritative for both endpoints. See tests/test_title_grade_bands.py.
    # Slug matching is what this test guards; the number moved with the band.
    assert out[1] == 150_000


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


# ── employer-specific salary overlays ─────────────────────────────────────────

_AM_SLUG = "alvarez-marsal-corporate-finance-limited"
_AM_PROJECT_MANAGER = (
    "Manager - Project Delivery and Operations "
    "(Infrastructure & Capital Projects)"
)


def test_employer_overlay_replaces_the_boutique_discount_for_the_confirmed_role():
    """The reported A&M manager case must become HK$45k-60k, not HK$17.5k-35k."""
    out = clamp_salary(
        "corporate_finance_accounting", "mid", 17_500, 35_000,
        role="professional_practice_advisory", grade=None,
        company_slug=_AM_SLUG, title=_AM_PROJECT_MANAGER, source_tier="boutique",
    )
    assert out == (45_000, 60_000)


def test_employer_overlay_uses_scraped_title_not_model_coordinate():
    """A blank/misclassified model coordinate cannot evade a title-specific correction."""
    assert employer_salary_overlay(_AM_SLUG, _AM_PROJECT_MANAGER) == (
        45_000, 60_000, "am_infrastructure_capital_projects_manager",
    )


def test_employer_overlay_does_not_spread_to_other_managers_or_employers():
    unrelated_am = clamp_salary(
        "corporate_finance_accounting", "mid", 17_500, 35_000,
        company_slug=_AM_SLUG, title="Manager (Financial Services – M&A / Deals)",
        source_tier="boutique",
    )
    other_employer = clamp_salary(
        "corporate_finance_accounting", "mid", 17_500, 35_000,
        company_slug="another-advisory-firm", title=_AM_PROJECT_MANAGER,
        source_tier="boutique",
    )
    senior_manager = clamp_salary(
        "corporate_finance_accounting", "senior", 49_000, 63_000,
        company_slug=_AM_SLUG,
        title="Senior Manager - Project Delivery and Operations (Infrastructure & Capital Projects)",
        source_tier="boutique",
    )
    assert unrelated_am == other_employer == (12_250, 24_500)
    assert senior_manager == (34_300, 44_100)


# ── Morris's Manager-grade floors ─────────────────────────────────────────────

def test_smaller_firm_finance_manager_gets_the_40k_to_50k_floor_after_discount():
    out = clamp_salary(
        "back_office_operations", "mid", 25_000, 39_000,
        role="operations_general", company_slug="smaller-firm",
        title="Manager, Treasury Operations", source_tier="boutique",
    )
    assert out == (40_000, 50_000)


def test_large_finance_employer_manager_starts_at_50k():
    out = clamp_salary(
        "middle_office", "mid", 35_000, 48_000,
        role="risk_credit", company_slug="hsbc-hk", title="Manager, Credit Risk",
    )
    assert out == (50_000, 60_000)


def test_big_four_is_explicitly_large_even_though_source_tier_is_not_used():
    assert manager_grade_floor(
        "corporate_finance_accounting", "professional_practice_advisory", "kpmg",
        "Manager, Transaction Advisory",
    ) == (50_000, 60_000, "large_employer")


def test_manager_floor_excludes_assistant_and_service_titles():
    assistant = clamp_salary(
        "back_office_operations", "mid", 25_000, 39_000,
        role="operations_general", company_slug="smaller-firm",
        title="Assistant Manager, Treasury Operations",
    )
    service = clamp_salary(
        "back_office_operations", "mid", 11_500, 23_000,
        role="customer_service", company_slug="hsbc-hk",
        title="Customer Service Manager",
    )
    # The existing role ceiling still applies; the Manager-grade floor does not.
    assert assistant == (25_000, 31_000)
    assert service == (11_500, 23_000)


def test_manager_floor_leaves_relationship_manager_on_its_own_calibrated_bands():
    assert manager_grade_floor(
        "commercial_corporate_banking", "commercial_banking_rm", "hsbc-hk",
        "Relationship Manager, Corporate Banking",
    ) is None


def test_manager_floor_excludes_sales_and_business_development_titles():
    assert manager_grade_floor(
        "insurance", "agency_distribution", "smaller-firm",
        "Business Development Manager, Insurance Partnership",
    ) is None


def test_manager_floor_needs_a_recognised_finance_coordinate():
    assert manager_grade_floor(None, None, "smaller-firm", "Manager, Treasury Operations") is None


def test_manager_floor_excludes_abbreviated_assistant_manager_titles():
    assert manager_grade_floor(
        "insurance", "commercial_insurance", "ping-an",
        "Sr Acc Executive/Ass. Manager - Large Corporate",
    ) is None


def test_specific_employer_overlay_wins_over_the_generic_manager_floor():
    out = clamp_salary(
        "corporate_finance_accounting", "mid", 17_500, 35_000,
        role="professional_practice_advisory", company_slug=_AM_SLUG,
        title=_AM_PROJECT_MANAGER, source_tier="boutique",
    )
    assert out == (45_000, 60_000)


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


# ── internship cap ──────────────────────────────────────────────────────────────
#
# Found by the 2026-08-18 estimator audit (docs/SALARY_ESTIMATOR_AUDIT.html): 58 of the
# 153 live internship listings were priced above the HK$15,000 ceiling the enricher's own
# prompt sets for them, the worst at HK$41,500-83,500 — 5.6x the cap. The mechanism is
# always the same: "Summer ANALYST, Investment Banking" matches the full-time IBD Analyst
# row (corporate_finance_ma_ecm_dcm 41k-83k) and the model copies that band verbatim,
# never reaching the internship rule at all. The prompt states the rule; the model ignores
# it on 38% of cases; so it is enforced here instead, where it cannot be ignored.

def test_summer_analyst_is_capped_at_the_internship_ceiling():
    # Real production row: Citi, "Banking - Investment Banking, Summer Analyst,
    # Hong Kong - APAC, 2027" stored at 41,500-83,500.
    out = clamp_salary(
        "front_office", "junior", 41_500, 83_500,
        role="corporate_finance_ma_ecm_dcm",
        title="Banking - Investment Banking, Summer Analyst, Hong Kong - APAC, 2027",
    )
    assert out[1] <= INTERNSHIP_MAX_MONTHLY_HKD


def test_named_internship_titles_are_all_caught():
    # Every one of these is a real live row from the audit.
    for title in (
        "Global Banking Intern Hong Kong 2027",
        "Investment Banking Graduate Programme 2027 Hong Kong",
        "2027 Deutsche Bank Summer Internship Programme - Investment Banking & Capital Markets - Hong Kong",
        "2027 Investment Banking Summer Associate (MBA) Program (Hong Kong)",
        "2027 Global Capital Markets Industrial Placement / Summer Analyst Program (Hong Kong)",
        "Financial Market Trainee 2026",
        "暑期實習生 - 投資銀行",
    ):
        out = clamp_salary(
            "front_office", "junior", 41_500, 83_500,
            role="corporate_finance_ma_ecm_dcm", title=title,
        )
        assert out[1] <= INTERNSHIP_MAX_MONTHLY_HKD, title


def test_internship_cap_never_raises_a_lower_estimate():
    # Down-only holds here too: an internship already priced under the cap is untouched.
    out = clamp_salary(
        "front_office", "junior", 8_000, 12_000,
        role="corporate_finance_ma_ecm_dcm", title="Summer Intern",
    )
    assert out == (8_000, 12_000)


def test_internal_and_international_are_not_internships():
    # The prompt's own warning, enforced: these words merely CONTAIN "intern".
    for title in (
        "Director, Internal Audit",
        "International Wealth Manager",
        "Head of Internal Control",
        "International Corporate Banking Relationship Manager",
    ):
        out = clamp_salary(
            "middle_office", "lead", 90_000, 120_000, title=title,
        )
        assert out[1] > INTERNSHIP_MAX_MONTHLY_HKD, title


def test_internship_cap_applies_without_a_tier_or_role():
    # The cap is title-driven and must fire even when nothing else is recognised.
    out = clamp_salary(None, None, 40_000, 80_000, title="Summer Analyst 2027")
    assert out[1] <= INTERNSHIP_MAX_MONTHLY_HKD


def test_internship_range_is_never_a_single_value():
    out = clamp_salary(
        "front_office", "junior", 41_500, 83_500,
        role="corporate_finance_ma_ecm_dcm", title="Summer Analyst, Hong Kong 2027",
    )
    assert out[0] is not None and out[0] < out[1]


# ── the grade ceiling, the floor raise, and front-office desks ────────────────
# Found live 2026-08-19: 62 board rows sat ABOVE their own title-grade ceiling, and
# rows enriched on the SAME DAY sat both at and above it — so this was never "written
# before the ceiling shipped". The floor raise below adopts a matched band outright
# (`new_min, new_max = lo, hi`) and then re-applies only the GLOBAL cap, handing back
# a max the grade ceiling had already lowered. The internship cap was guarded against
# exactly this; the grade ceiling never was.


def test_the_floor_raise_cannot_undo_the_title_grade_ceiling():
    """A support-function VP stays at their grade ceiling, band floor or no band floor.

    `middle_office`/`senior` matches a band whose floor sits above the HK$80,000 VP
    ceiling, which is precisely the shape that let the floor raise overwrite it.
    """
    out_min, out_max = clamp_salary(
        "middle_office", "senior", 75_000, 100_000,
        role="risk_credit", company_slug="dbs-hk",
        title="Senior Manager, Credit Risk",
    )
    assert out_max <= 70_000, "the Manager/AVP grade ceiling must survive the floor raise"
    assert out_min < out_max, "must never collapse to a flat point"


def test_a_front_office_desk_is_exempt_from_the_flat_grade_ceiling():
    """A flat "VP = HK$80,000" is a support-function rule, not a market-wide one.

    The front_office ladder reaches HK$166,500-200,000 by design. Capping a Goldman
    or JPMorgan trading VP at HK$80,000 contradicts that table and understates the one
    stratum an independent re-estimate already found reading low.
    """
    out_min, out_max = clamp_salary(
        "front_office", "mid", 125_000, 166_500,
        company_slug="goldman-sachs",
        title="Global Banking & Markets, SPG Basis Trading, Vice President",
    )
    assert out_max == 166_500, "front office keeps its own ladder's ceiling"


def test_the_exemption_is_scoped_to_front_office_only():
    """Same title, same bank, different desk — the ceiling still bites."""
    _, front = clamp_salary("front_office", "mid", 125_000, 166_500,
                            company_slug="citibank-hk", title="Vice President, Operations")
    _, middle = clamp_salary("middle_office", "mid", 125_000, 166_500,
                             company_slug="citibank-hk", title="Vice President, Operations")
    assert front > middle, "the exemption must not leak into support functions"
    assert middle <= 80_000


def test_an_internship_is_still_capped_inside_a_front_office_desk():
    """The front-office exemption must not reopen the internship hole."""
    _, out_max = clamp_salary(
        "front_office", "junior", 41_500, 83_500,
        company_slug="goldman-sachs", title="2027 Summer Analyst Programme",
    )
    assert out_max <= INTERNSHIP_MAX_MONTHLY_HKD


# ── price_from_coordinate / coordinate pricing (v13) ─────────────────────────
# The model's own exact (tier, role, grade) read, priced straight off
# tables_monthly_hkd — no seniority-to-standardized-row-name translation, unlike
# `_role_band`. Added so a resolved coordinate can replace an estimate outright,
# the same way Morris's title-grade band already does, for the roughly half of
# ladders whose grade rows use idiosyncratic names `_role_band` cannot reach.

def test_price_from_coordinate_resolves_an_exact_cell():
    band = price_from_coordinate("back_office_operations", "customer_service", "cs_manager")
    assert band == tuple(_TABLES["back_office_operations"]["roles"]["customer_service"]["cs_manager"])


def test_price_from_coordinate_returns_none_on_an_unknown_grade():
    assert price_from_coordinate("back_office_operations", "customer_service", "not_a_real_grade") is None


def test_price_from_coordinate_is_none_safe():
    assert price_from_coordinate(None, None, None) is None
    assert price_from_coordinate("back_office_operations", None, "cs_manager") is None
    assert price_from_coordinate("back_office_operations", "customer_service", None) is None


def test_a_resolved_coordinate_replaces_a_bad_raw_guess():
    """The whole point: a wildly-low raw estimate is overridden, not just capped."""
    out_min, out_max = clamp_salary(
        "back_office_operations", "mid", 5_000, 8_000,
        role="customer_service", grade="cs_manager",
        company_slug="some-boutique-firm", title="CS Manager",
    )
    assert (out_min, out_max) == (40_000, 60_000)


def test_no_grade_leaves_clamp_salary_behaviour_unchanged():
    """Backward compatibility: every caller that doesn't pass `grade` is unaffected."""
    with_grade_none = clamp_salary(
        "back_office_operations", "mid", 5_000, 8_000,
        role="customer_service", grade=None,
        company_slug="some-boutique-firm", title="CS Manager",
    )
    without_grade_kwarg = clamp_salary(
        "back_office_operations", "mid", 5_000, 8_000,
        role="customer_service",
        company_slug="some-boutique-firm", title="CS Manager",
    )
    assert with_grade_none == without_grade_kwarg == (5_000, 8_000)


def test_morris_title_grade_band_still_outranks_a_resolved_coordinate():
    """Title is harder evidence than a role/grade guess — priority must not flip.

    At a recognised bank, "Vice President" is Morris's authoritative band
    (HK$60,000-80,000), which must win over a coordinate resolving to a lower
    generic cell for the same job.
    """
    out_min, out_max = clamp_salary(
        "back_office_operations", "mid", 5_000, 8_000,
        role="customer_service", grade="cs_manager",
        company_slug="bank-of-east-asia", title="Vice President, Customer Service",
    )
    assert (out_min, out_max) == (60_000, 80_000)


def test_coordinate_replace_still_respects_the_title_grade_ceiling():
    """A resolved coordinate must not hand back a maximum the title ceiling lowered.

    Mirrors the same guard the floor-raise step already has (line ~552 above):
    adopting a band outright is not allowed to undo evidence the title itself
    already supplied.
    """
    out_min, out_max = clamp_salary(
        "middle_office", "mid", 5_000, 8_000,
        role="risk_credit", grade="Manager",
        company_slug="dbs-hk", title="Manager, Credit Risk",
    )
    assert out_max <= 70_000, "the Manager/AVP grade ceiling must survive the coordinate replace"
    assert out_min < out_max


def test_coordinate_pricing_is_skipped_for_an_internship():
    """The internship cap must win even when a (bad) coordinate is also supplied."""
    _, out_max = clamp_salary(
        "back_office_operations", "junior", 5_000, 8_000,
        role="customer_service", grade="cs_manager",
        title="2027 Summer Intern, Customer Service",
    )
    assert out_max <= INTERNSHIP_MAX_MONTHLY_HKD
