"""Morris H.'s bank / insurance title-grade bands (2026-08-19).

These bands are the one place where a job TITLE is treated as hard evidence that
outranks the model's own read: at a known bank or insurer, "Assistant Vice
President" means a specific pay grade, and the estimator guessing otherwise is
the estimator being wrong.

The old `management_grade_caps_monthly_hkd` only ever lowered a ceiling, so it
could not fix the opposite error — a senior grade estimated far too LOW. Every
test below that asserts a raise is a test the old caps could not have passed.
"""

from __future__ import annotations

import pytest

from hk_jobs.salary_clamp import clamp_salary


# ── Banks ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "title,expected",
    [
        ("Assistant Vice President, Operations", (50_000, 70_000)),
        ("Vice President, Client Onboarding", (60_000, 80_000)),
        ("Senior Vice President, Risk", (80_000, 100_000)),
        ("Director, Compliance", (100_000, 150_000)),
        ("Executive Director, Technology", (130_000, 180_000)),
        ("Managing Director, Corporate Banking", (180_000, 250_000)),
        ("Global Head of Operations", (200_000, 300_000)),
    ],
)
def test_bank_grade_sets_the_whole_band(title, expected):
    """A matched bank grade is authoritative for BOTH endpoints, not just the top."""
    assert clamp_salary(
        "middle_office", "mid", 20_000, 25_000,
        company_slug="hsbc-hk", title=title, source_tier="mainstream",
    ) == expected


def test_bank_associate_director_reads_as_senior_vice_president():
    """Morris: 'Senior Vice President (senior mgr/associate director)' — one grade."""
    assert clamp_salary(
        "middle_office", "senior", 30_000, 40_000,
        company_slug="hsbc-hk", title="Associate Director, Audit", source_tier="mainstream",
    ) == (80_000, 100_000)


def test_managing_director_is_allowed_above_the_global_ceiling():
    """180-250k exceeds the 200k global cap; a deterministic title match may pass it.

    The cap exists to stop an unmatched model estimate drifting up, which is a
    different situation from a named grade at a named bank.
    """
    _, hi = clamp_salary(
        "middle_office", "lead", 50_000, 60_000,
        company_slug="jpmorgan", title="Managing Director, Markets", source_tier="mainstream",
    )
    assert hi == 250_000


def test_front_office_is_exempt_from_the_grade_bands():
    """A trading VP is not an operations VP — the revenue ladder wins.

    Capping front office at the flat VP band would contradict the anchor table
    outright and re-break the rows a previous audit priced at HK$125,000-166,500.
    """
    lo, hi = clamp_salary(
        "front_office", "senior", 120_000, 160_000,
        company_slug="goldman-sachs", title="Vice President, Equity Derivatives",
        source_tier="mainstream",
    )
    assert (lo, hi) == (120_000, 160_000)


def test_non_bank_non_insurer_is_untouched_by_the_grade_bands():
    lo, hi = clamp_salary(
        "middle_office", "mid", 30_000, 40_000,
        company_slug="some-random-fintech", title="Vice President, Ops",
        source_tier="mainstream",
    )
    assert (lo, hi) == (30_000, 40_000)


# ── Insurers ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "title,expected",
    [
        ("Assistant Vice President, Underwriting", (100_000, 150_000)),
        ("Director, Claims", (120_000, 150_000)),
        ("Senior Director, Actuarial", (120_000, 150_000)),
        ("Associate Director, Product", (80_000, 120_000)),
        ("Senior Manager, Pricing", (65_000, 80_000)),
        ("Manager, Policy Administration", (50_000, 60_000)),
        ("Assistant Manager, Claims", (35_000, 45_000)),
    ],
)
def test_tier_1_insurer_grades(title, expected):
    """At an insurer the hierarchy INVERTS: AVP is a top grade, not a mid one."""
    assert clamp_salary(
        "insurance", "mid", 20_000, 30_000,
        company_slug="aia-hk", title=title, source_tier="mainstream",
    ) == expected


def test_insurance_vice_president_cannot_fall_below_the_top_grade_safety_band():
    """An exact low guide coordinate must not undercut insurance's top title grade."""
    assert clamp_salary(
        "insurance", "lead", 40_000, 60_000,
        role="underwriting", grade="VP",
        company_slug="aia-hk", title="Vice President, Underwriting",
        source_tier="mainstream",
    ) == (100_000, 200_000)


def test_unclassified_insurer_does_not_invent_a_tier_2_discount():
    """Only an explicitly reviewed Tier 2 membership may lower a whole grade band."""
    assert clamp_salary(
        "insurance", "mid", 20_000, 30_000,
        company_slug="allianz", title="Manager, Claims", source_tier="mainstream",
    ) == (50_000, 60_000)


def test_explicit_tier_2_insurer_takes_the_reviewed_discount(monkeypatch):
    """The discount remains active when membership is positively classified."""
    import hk_jobs.salary_clamp as salary_clamp

    monkeypatch.setattr(salary_clamp, "_INSURANCE_TIER_2", frozenset({"allianz"}))
    assert salary_clamp.clamp_salary(
        "insurance", "mid", 20_000, 30_000,
        company_slug="allianz", title="Manager, Claims", source_tier="mainstream",
    ) == (round(50_000 * 0.85), round(60_000 * 0.85))


def test_insurance_tier_registries_are_explicit_and_disjoint():
    from hk_jobs import salary_anchors

    insurance = salary_anchors.GRADE_BANDS["insurance"]
    assert set(insurance["hierarchy_high_to_low"]) <= set(insurance["bands_monthly_hkd"])
    assert salary_anchors.INSURANCE_TIER_1_SLUGS.isdisjoint(
        salary_anchors.INSURANCE_TIER_2_SLUGS
    )
    assert "allianz" not in salary_anchors.INSURANCE_TIER_1_SLUGS
    assert "allianz" not in salary_anchors.INSURANCE_TIER_2_SLUGS


def test_hang_seng_bank_is_a_bank_not_a_tier_2_insurer():
    """Hang Seng Insurance is Tier 2; 'hang-seng-bank' is the BANK and must not be."""
    assert clamp_salary(
        "middle_office", "mid", 20_000, 25_000,
        company_slug="hang-seng-bank", title="Vice President, Operations",
        source_tier="mainstream",
    ) == (60_000, 80_000)


# ── Interaction with the rules that already existed ──────────────────────────

def test_sme_discount_stacks_on_a_matched_grade():
    """Morris's 30% SME discount is the existing boutique multiplier."""
    assert clamp_salary(
        "middle_office", "mid", 20_000, 25_000,
        company_slug="hsbc-hk", title="Vice President, Ops", source_tier="boutique",
    ) == (round(60_000 * 0.7), round(80_000 * 0.7))


def test_internship_still_beats_every_grade_band():
    """'Assistant Manager Intern' must not collect the AVP band."""
    _, hi = clamp_salary(
        "middle_office", "junior", 8_000, 12_000,
        company_slug="hsbc-hk", title="Assistant Manager, Operations (Intern)",
        source_tier="mainstream",
    )
    assert hi <= 15_000


def test_a_disclosed_style_high_estimate_is_still_pulled_into_the_grade_band():
    """The band is authoritative in BOTH directions for a matched grade."""
    assert clamp_salary(
        "middle_office", "senior", 150_000, 190_000,
        company_slug="hsbc-hk", title="Assistant Vice President, Settlements",
        source_tier="mainstream",
    ) == (50_000, 70_000)


# ── "Manager" is a gloss at a bank, a grade at an insurer ────────────────────
#
# This is the distinction that matters most in practice. On a real 78-row sample
# a bare-"Manager"-means-AVP FLOOR moved the median +47.7%, because "Manager" in
# a HK bank title spans most of the pay scale. As a ceiling the same mapping was
# harmless and had shipped for months.

@pytest.mark.parametrize(
    "title",
    [
        "Business Transformation Manager",
        "Customer Service Manager",
        "Manager, Data Analytics",
        "Assistant Manager, Settlements",
    ],
)
def test_bank_bare_manager_titles_are_never_floored(title):
    """A bank 'Manager' keeps its estimate; the old ceiling still applies."""
    lo, hi = clamp_salary(
        "middle_office", "mid", 22_000, 30_000,
        company_slug="hsbc-hk", title=title, source_tier="mainstream",
    )
    assert lo == 22_000, "a bare 'Manager' must not be raised to the AVP floor"
    assert hi <= 70_000, "the legacy AVP ceiling should still cap it"


def test_bank_manager_ceiling_still_bites_on_an_overestimate():
    _, hi = clamp_salary(
        "middle_office", "senior", 60_000, 150_000,
        company_slug="hsbc-hk", title="Manager, Operations", source_tier="mainstream",
    )
    assert hi == 70_000


def test_insurance_manager_IS_an_authoritative_grade():
    """Morris lists Manager and Assistant Manager as insurance grades in their own right."""
    assert clamp_salary(
        "insurance", "mid", 20_000, 30_000,
        company_slug="aia-hk", title="Manager, Policy Administration",
        source_tier="mainstream",
    ) == (50_000, 60_000)


def test_explicit_bank_avp_title_still_sets_the_floor():
    """The gloss is ambiguous; the actual grade word is not."""
    assert clamp_salary(
        "middle_office", "mid", 22_000, 30_000,
        company_slug="hsbc-hk", title="Assistant Vice President, Settlements",
        source_tier="mainstream",
    ) == (50_000, 70_000)


def test_cmb_wing_lung_avp_uses_the_reviewed_smaller_bank_band():
    """CMB Wing Lung is a smaller bank; its AVP range is HK$40k-55k."""
    assert clamp_salary(
        "middle_office", "mid", 50_000, 70_000,
        company_slug="cmb-wing-lung", title="Assistant VP (Compliance)",
        source_tier="mainstream",
    ) == (40_000, 55_000)


@pytest.mark.parametrize(
    "role,grade,title",
    [
        (
            "corporate_accounting_finance", "Accounting Manager",
            "Manager, Accounting (Retail Finance & Credit Card Dept)",
        ),
        (
            "banking_industry_finance", "Manager",
            "Manager, Accounting (Retail Finance & Credit Card Dept) (6 months contract)",
        ),
    ],
)
def test_cmb_accounting_manager_pay_does_not_depend_on_contract_status(role, grade, title):
    """Equivalent permanent and contract Roles share the reviewed Manager band."""
    assert clamp_salary(
        "corporate_finance_accounting", "mid", 50_000, 70_000,
        role=role, grade=grade, company_slug="cmb-wing-lung", title=title,
        source_tier="mainstream",
    ) == (40_000, 55_000)


def test_cmb_unambiguous_finance_manager_has_the_reviewed_whole_band():
    """A low generic coordinate must not shrink CMB's Manager-grade ceiling to HK$50k."""
    assert clamp_salary(
        "back_office_operations", "mid", 25_000, 39_000,
        role="operations_general", grade="Manager", company_slug="cmb-wing-lung",
        title="Manager, Treasury Operations", source_tier="mainstream",
    ) == (40_000, 55_000)


def test_cmb_explicit_manager_prefix_outranks_the_support_function():
    """`Manager, …` states the bank grade even when the function is systems/support."""
    assert clamp_salary(
        "middle_office", "mid", 20_000, 30_000,
        role="it_management", grade="Manager", company_slug="cmb-wing-lung",
        title="Manager, Operation & System (Customer Contact Centre)",
        source_tier="mainstream",
    ) == (40_000, 55_000)


def test_cmb_intern_has_a_reviewed_nonzero_student_pay_band():
    """CMB's size rounding must not turn a positive intern salary into HK$0."""
    assert clamp_salary(
        "front_office", "junior", 3_000, 8_000,
        company_slug="cmb-wing-lung", title="Intern, Financial Institutions Department",
        source_tier="mainstream",
    ) == (5_000, 15_000)


def test_cmb_trainee_has_a_wide_distinct_programme_band():
    """Graduate trainee pay is variable and must not be collapsed into intern pay."""
    assert clamp_salary(
        "front_office", "junior", 35_000, 57_000,
        company_slug="cmb-wing-lung", title="Financial Market Trainee 2026",
        source_tier="mainstream",
    ) == (12_000, 25_000)


# ── Two bugs found by dry-running fix-s against the real board ───────────────

@pytest.mark.parametrize(
    "title",
    [
        "2027 HSBC Hong Kong Corporate and Institutional Banking Graduate Programmes",
        "Graduate Programs 2027",
        "Management Trainee Programmes",
    ],
)
def test_internship_matcher_handles_plural_programmes(title):
    """PRE-EXISTING BUG: `graduate\\s+programme\\b` cannot match "Programmes".

    The trailing "s" is a word character, so the word boundary fails and a
    graduate programme was priced on the full-time ladder. Found because fix-s
    wanted to lift one of these off the HK$15,000 internship cap.
    """
    from hk_jobs.salary_clamp import is_internship
    assert is_internship(title) is True


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Assistant VP (Compliance)", (40_000, 55_000)),
        ("Asst VP, Operations", (40_000, 55_000)),
        ("Assistant V.P., Risk", (40_000, 55_000)),
    ],
)
def test_assistant_vp_abbreviation_is_the_AVP_grade_not_VP(title, expected):
    """"Assistant VP" contains "VP" and was matching the higher VP band.

    Real row: "Assistant VP (Compliance) - CMB Wing Lung Bank" was being priced
    at the Vice President band instead of AVP. CMB's reviewed smaller-bank AVP
    band now supplies the expected amount while this test keeps protecting the grade.
    """
    assert clamp_salary(
        "middle_office", "mid", 35_000, 45_000,
        company_slug="cmb-wing-lung", title=title, source_tier="mainstream",
    ) == expected


# ── Morris's second batch (2026-08-20) ───────────────────────────────────────
#
# Functional titles, as opposed to the corporate grade words above. They rank
# BELOW an explicit grade in the same title — "Director, Trade Product Manager"
# is a Director because it says so — and above the ambiguous "Manager" gloss.

def test_division_head_is_the_managing_director_grade():
    """Morris: 'Division Head is a big role, equal to Managing Director grade.'"""
    assert clamp_salary(
        "middle_office", "senior", 65_000, 80_000,
        company_slug="hsbc-hk", title="Division Head, Corporate Banking",
        source_tier="mainstream",
    ) == (180_000, 250_000)


def test_team_head_is_the_director_grade():
    """Morris: 'Team Head is equal to Director grade.'"""
    assert clamp_salary(
        "middle_office", "senior", 60_000, 90_000,
        company_slug="dbs-hk", title="Team Head, Consumer Banking Transformation",
        source_tier="mainstream",
    ) == (100_000, 150_000)


def test_cmb_team_lead_uses_the_reviewed_smaller_bank_band():
    """At a smaller bank Team Lead is at least Senior Manager, not Director."""
    assert clamp_salary(
        "middle_office", "lead", 100_000, 150_000,
        role="fcc_aml", grade="Director",
        company_slug="cmb-wing-lung", title="Team Lead of Advisory",
        source_tier="mainstream",
    ) == (45_000, 60_000)


@pytest.mark.parametrize(
    "title",
    [
        "Team Head, Client Relationship Management, Private Banking",
        "Team Head, Client Services",
        "Team Head, Customer Service Centre",
        "Team Head, Operations Support",
    ],
)
def test_a_service_team_head_keeps_the_older_calibration(title):
    """The one place Morris's rule is NOT applied wholesale.

    deepseek.py's prompt has carried the opposite instruction since v8, for a
    measured reason: a bank has MANY client-relationship/service/operations team
    heads at ~50k-100k and few desk heads at 150k+, and pricing the former as
    Directors is the exact over-estimation that disambiguation was added to stop.
    A title naming a service/support function keeps the old behaviour; every other
    Team Head takes Morris's Director band.
    """
    lo, hi = clamp_salary(
        "middle_office", "senior", 60_000, 90_000,
        company_slug="dbs-hk", title=title, source_tier="mainstream",
    )
    assert (lo, hi) != (100_000, 150_000)


def test_an_explicit_grade_outranks_the_functional_title():
    """"ED, Team Head" is an Executive Director — the grade word is harder evidence
    than the functional label."""
    assert clamp_salary(
        "middle_office", "lead", 129_500, 164_500,
        company_slug="dbs-hk", title="ED, Team Head, Client Services, Private Banking",
        source_tier="mainstream",
    ) == (130_000, 180_000)


@pytest.mark.parametrize(
    "title", ["Product Manager, Deposit Strategy", "Senior Product Manager, Payments"]
)
def test_product_manager_does_not_create_a_director_salary_from_a_normal_estimate(title):
    """A functional product title alone cannot promote an ordinary bank Role."""
    assert clamp_salary(
        "middle_office", "mid", 30_000, 45_000,
        company_slug="citibank-hk", title=title, source_tier="mainstream",
    ) != (100_000, 150_000)


def test_product_manager_can_confirm_a_director_salary_already_supported_by_the_estimate():
    """The reviewed rule preserves a genuinely senior Product Manager reading."""
    assert clamp_salary(
        "middle_office", "lead", 90_000, 120_000,
        company_slug="citibank-hk", title="Product Manager, Deposit Strategy",
        source_tier="mainstream",
    ) == (100_000, 150_000)


def test_welab_product_manager_is_not_promoted_to_director_by_title_alone():
    """The audit regression: WeLab's ordinary product Roles must stay below Director."""
    assert clamp_salary(
        "middle_office", "mid", 25_000, 50_000,
        company_slug="welab-bank", title="Product Manager (Unsecured Lending)",
        source_tier="mainstream",
    ) != (100_000, 150_000)


@pytest.mark.parametrize("title", ["Assistant Product Manager", "Junior Product Manager"])
def test_a_junior_product_manager_is_not_a_director(title):
    """The category is senior; a title that explicitly says otherwise is not."""
    lo, hi = clamp_salary(
        "middle_office", "junior", 21_500, 25_000,
        company_slug="citibank-hk", title=title, source_tier="mainstream",
    )
    assert (lo, hi) != (100_000, 150_000)


def test_cmb_mobile_app_product_manager_uses_the_reviewed_function_band():
    """A smaller-bank digital Product Manager is not a Director-grade Role."""
    assert clamp_salary(
        "middle_office", "senior", 100_000, 130_000,
        role="product_management", grade="Director / Head of Product",
        company_slug="cmb-wing-lung",
        title="Mobile App Product Manager, Digital Banking Department",
        source_tier="mainstream",
    ) == (45_000, 60_000)


@pytest.mark.parametrize(
    "title",
    [
        "Senior Group Manager, IFRS",
        "Senior Manager, Agency Performance Management",
        "Senior Manager, Partnership Distribution",
    ],
)
def test_prudential_sized_insurer_uses_one_senior_manager_band(title):
    """Reviewed Prudential-sized insurer roles share HK$55k-80k."""
    assert clamp_salary(
        "insurance", "senior", 25_000, 120_000,
        company_slug="prudential-hk", title=title, source_tier="mainstream",
    ) == (55_000, 80_000)


def test_compound_grade_title_uses_broad_ambiguity_band():
    assert clamp_salary(
        "middle_office", "mid", 35_000, 50_000,
        company_slug="kpmg",
        title="Senior Consultant / Manager / Associate Director, HR Transformation Consulting",
        source_tier="mainstream",
    ) == (55_000, 80_000)


def test_big_four_group_anchor_applies_to_all_four_slugs():
    """The employer-group registry keeps future Big Four corrections reusable."""
    from hk_jobs.salary_anchors import BIG_FOUR_SLUGS

    assert BIG_FOUR_SLUGS == {"ey", "kpmg", "deloitte", "pwc"}


@pytest.mark.parametrize("slug", ["ey", "kpmg", "deloitte", "pwc"])
def test_big_four_manager_and_associate_director_bands_are_shared(slug):
    assert clamp_salary(
        "middle_office", "mid", 35_000, 70_000,
        company_slug=slug, title="Manager, Corporate Audit", source_tier="mainstream",
    ) == (50_000, 60_000)
    assert clamp_salary(
        "middle_office", "senior", 70_000, 130_000,
        company_slug=slug, title="Associate Director, Finance Consulting", source_tier="mainstream",
    ) == (85_000, 120_000)


def test_big_four_associate_director_wins_in_compound_title():
    assert clamp_salary(
        "middle_office", "senior", 35_000, 50_000,
        company_slug="kpmg", title="Manager / Associate Director, Finance Consulting",
        source_tier="mainstream",
    ) == (85_000, 120_000)


@pytest.mark.parametrize("slug", ["ey", "kpmg", "deloitte", "pwc"])
def test_big_four_senior_forensics_roles_share_40k_55k_band(slug):
    assert clamp_salary(
        "middle_office", "senior", 30_000, 40_000,
        company_slug=slug,
        title="Assurance - Forensics - Cyber Incident Response - Senior",
        source_tier="mainstream",
    ) == (40_000, 55_000)


def test_big_four_explicit_associate_director_forensics_keeps_ad_band():
    assert clamp_salary(
        "middle_office", "senior", 70_000, 120_000,
        company_slug="ey",
        title="Associate Director, Forensics",
        source_tier="mainstream",
    ) == (85_000, 120_000)


def test_big_four_assistant_manager_is_not_plain_manager_grade():
    assert clamp_salary(
        "middle_office", "mid", 25_000, 45_000,
        company_slug="kpmg", title="Assistant Manager, Corporates Audit",
        source_tier="mainstream",
    ) != (50_000, 60_000)


def test_deloitte_manager_ma_uses_50k_90k_band():
    assert clamp_salary(
        "middle_office", "senior", 60_000, 110_000,
        company_slug="deloitte", title="Manager, M&A Advisory",
        source_tier="mainstream",
    ) == (50_000, 90_000)


def test_deloitte_senior_consultant_uses_40k_55k_band():
    assert clamp_salary(
        "middle_office", "senior", 35_000, 70_000,
        company_slug="deloitte", title="Senior Consultant, Risk Advisory",
        source_tier="mainstream",
    ) == (40_000, 55_000)


def test_deloitte_parenthesized_senior_consultant_wins_over_manager_token():
    assert clamp_salary(
        "middle_office", "senior", 45_000, 75_000,
        company_slug="deloitte", title="(Senior) Consultant / Manager, Technology",
        source_tier="mainstream",
    ) == (40_000, 55_000)


def test_deloitte_senior_manager_is_not_plain_manager_grade():
    assert clamp_salary(
        "middle_office", "senior", 55_000, 85_000,
        company_slug="deloitte", title="Senior Manager, Audit",
        source_tier="mainstream",
    ) != (50_000, 60_000)


def test_deloitte_mixed_manager_senior_manager_in_ma_uses_ma_band():
    assert clamp_salary(
        "middle_office", "senior", 60_000, 100_000,
        company_slug="deloitte", title="Manager / Senior Manager - M&A",
        source_tier="mainstream",
    ) == (50_000, 90_000)


def test_deloitte_non_ma_manager_keeps_shared_big_four_band():
    assert clamp_salary(
        "middle_office", "mid", 40_000, 70_000,
        company_slug="deloitte", title="Manager, Corporate Audit",
        source_tier="mainstream",
    ) == (50_000, 60_000)


@pytest.mark.parametrize("slug", ["jpmorgan", "jpmorgan-am-hk", "jpmorgan-chase"])
def test_jpmorgan_vp_uses_shared_85k_120k_band(slug):
    assert clamp_salary(
        "middle_office", "senior", 150_000, 171_000,
        company_slug=slug,
        title="Wealth Management Solutions - Multi-Asset Specialist - Vice President",
        source_tier="mainstream",
    ) == (85_000, 120_000)


@pytest.mark.parametrize("slug", ["hsbc-hk", "standard-chartered-hk", "dbs-hk", "citibank-hk"])
def test_hsbc_scale_bank_lead_product_uses_75k_100k(slug):
    assert clamp_salary(
        "middle_office", "lead", 75_000, 85_000,
        company_slug=slug, title="Lead Product Owner for Banking", source_tier="mainstream",
    ) == (75_000, 100_000)


@pytest.mark.parametrize("slug", ["citibank-hk", "hsbc-hk", "standard-chartered-hk"])
def test_spread_products_banker_vp_uses_100k_125k_except_jpmorgan(slug):
    assert clamp_salary(
        "front_office", "lead", 115_000, 130_000,
        company_slug=slug, title="Spread Products Banker - Vice President",
        source_tier="mainstream",
    ) == (100_000, 125_000)


def test_jpmorgan_spread_products_vp_keeps_jpmorgan_band():
    assert clamp_salary(
        "front_office", "lead", 115_000, 130_000,
        company_slug="jpmorgan", title="Spread Products Banker - Vice President",
        source_tier="mainstream",
    ) == (85_000, 120_000)


@pytest.mark.parametrize("slug", ["dbs-hk", "citibank-hk", "bochk", "hang-seng-bank"])
@pytest.mark.parametrize("title,expected", [
    ("Specialist, Cash Product Manager, Transaction Banking", (35_000, 50_000)),
    ("Relationship Manager, Consumer Banking", (35_000, 50_000)),
    ("Senior Product Manager, Digital Banking", (80_000, 110_000)),
])
def test_hsbc_scale_dbs_product_role_bands(slug, title, expected):
    assert clamp_salary(
        "middle_office", "mid", 75_000, 150_000,
        company_slug=slug, title=title, source_tier="mainstream",
    ) == expected


def test_dbs_scale_parenthesized_senior_product_manager_uses_senior_band():
    assert clamp_salary(
        "middle_office", "mid", 50_000, 100_000,
        company_slug="bochk", title="(Senior) Product Manager, Cash Management",
        source_tier="mainstream",
    ) == (80_000, 110_000)


@pytest.mark.parametrize("title,expected", [
    ("Group Strategy, Vice President", (80_000, 120_000)),
    ("Assistant Vice President, Market Risk Management", (50_000, 90_000)),
    ("Assistant VP, Market Risk Management", (50_000, 90_000)),
])
def test_market_infrastructure_vp_grades_use_shared_hkex_bands(title, expected):
    assert clamp_salary(
        "middle_office", "senior", 34_000, 85_000,
        company_slug="hkex", title=title, source_tier="mainstream",
    ) == expected


def test_icbc_scale_digital_product_manager_uses_70k_85k():
    assert clamp_salary(
        "middle_office", "mid", 50_000, 50_000,
        company_slug="icbc-asia",
        title="Digital Solutions Product Manager - Business & Tech Coordination",
        source_tier="mainstream",
    ) == (70_000, 85_000)


@pytest.mark.parametrize("title,expected", [
    ("Global Markets Sales - Cross Border Team", (45_000, 55_000)),
    ("Global Markets Senior Sales", (45_000, 55_000)),
    ("Investment Consultant, Product and Investment", (57_000, 70_000)),
])
def test_icbc_scale_market_roles_use_reviewed_bands(title, expected):
    assert clamp_salary(
        "middle_office", "mid", 30_000, 85_000,
        company_slug="icbc-asia", title=title, source_tier="mainstream",
    ) == expected


@pytest.mark.parametrize("title,expected", [
    ("Director, Underwriting", (80_000, 110_000)),
    ("Senior Underwriter, Commercial Lines", (70_000, 100_000)),
    ("Assistant Vice President, Risk", (90_000, 150_000)),
])
def test_fwd_sized_insurer_uses_shared_reviewed_bands(title, expected):
    assert clamp_salary(
        "insurance", "senior", 30_000, 160_000,
        company_slug="fwd-insurance", title=title, source_tier="mainstream",
    ) == expected


def test_deutsche_mixed_director_vp_uses_70k_120k():
    assert clamp_salary(
        "middle_office", "senior", 145_000, 171_000,
        company_slug="deutsche-bank",
        title="Private Bank - FX Advisory, Director/VP",
        source_tier="mainstream",
    ) == (70_000, 120_000)


def test_general_manager_at_a_chinese_bank_is_the_director_grade():
    """Morris: 'For Chinese banks they like using General Manager or Deputy GM,
    which is equivalent to Director/Head of.'"""
    assert clamp_salary(
        "middle_office", "senior", 40_000, 80_000,
        company_slug="citic-bank", title="Assistant General Manager, Corporate Banking",
        source_tier="mainstream",
    ) == (100_000, 150_000)


def test_deputy_gm_at_a_chinese_bank_is_the_director_grade():
    assert clamp_salary(
        "middle_office", "senior", 40_000, 80_000,
        company_slug="bochk", title="Deputy GM, Treasury", source_tier="mainstream",
    ) == (100_000, 150_000)


def test_general_manager_at_a_non_chinese_bank_is_not_mapped():
    """Morris scoped this to Chinese banks. Elsewhere "General Manager" means too
    many different things to price off the title."""
    lo, hi = clamp_salary(
        "middle_office", "senior", 56_000, 112_000,
        company_slug="hsbc-hk", title="Senior Legal Counsel (General Manager)",
        source_tier="mainstream",
    )
    assert (lo, hi) != (100_000, 150_000)


def test_a_bare_GM_abbreviation_is_never_matched():
    """Real live rows: "Senior Treasury Marketing Manager (GM-Corporate)" and
    "Senior Legal Counsel (GM)" — the two letters are part of a department name,
    not a grade. Same trap as the bare "Manager" gloss."""
    lo, hi = clamp_salary(
        "middle_office", "mid", 66_000, 70_000,
        company_slug="bochk", title="Senior Treasury Marketing Manager (GM-Corporate)",
        source_tier="mainstream",
    )
    assert (lo, hi) != (100_000, 150_000)


# ── Relationship management reference (2026-08-21) ──────────────────────────

@pytest.mark.parametrize(
    "tier,role,grade,title,expected",
    [
        (
            "commercial_corporate_banking", "commercial_banking_rm", "Assistant RM",
            "Assistant Relationship Manager, Commercial Banking", (55_000, 70_000),
        ),
        (
            "commercial_corporate_banking", "corporate_banking_rm", "Senior RM",
            "Senior Relationship Manager, Corporate Banking", (90_000, 150_000),
        ),
        (
            "commercial_corporate_banking", "sme_banking_rm", "RM",
            "Relationship Manager, SME Banking", (56_000, 72_000),
        ),
        (
            "retail_banking", "relationship_management", "Senior RM",
            "Senior Relationship Manager, Retail Banking", (72_000, 120_000),
        ),
    ],
)
def test_relationship_manager_coordinates_apply_the_bank_reference_and_sme_retail_discount(
    tier, role, grade, title, expected,
):
    """Plain RM titles are functional roles, not the bank AVP "manager" grade."""
    assert clamp_salary(
        tier, "senior", 10_000, 200_000, role=role, grade=grade,
        company_slug="hsbc-hk", title=title, source_tier="mainstream",
    ) == expected


def test_an_explicit_avp_relationship_manager_still_uses_the_avp_grade():
    """The RM exception is for functional titles only, never a named HR grade."""
    assert clamp_salary(
        "commercial_corporate_banking", "mid", 20_000, 150_000,
        company_slug="hsbc-hk", title="AVP, Relationship Manager, Commercial Banking",
        source_tier="mainstream",
    ) == (50_000, 70_000)


# ── Morris's Pricing Test corrections (2026-08-21) ──────────────────────────

@pytest.mark.parametrize(
    "tier,role,grade,title,expected",
    [
        (
            "middle_office", "private_banking_business_management", "Manager",
            "E-Banking Business Manager, Private Banking Department", (50_000, 70_000),
        ),
        (
            "corporate_finance_accounting", "strategy_business_consulting", "Senior Consultant",
            "Senior Consultant, Strategy & Business Design (Public Sector)", (45_000, 65_000),
        ),
        (
            "back_office_operations", "exchange_clearing_operations", "AVP",
            "AVP - Derivatives Trading Operations (Morning Shift) - Operations", (50_000, 80_000),
        ),
        (
            "insurance", "underwriting", "Underwriter",
            "Underwriter - Healthcare Professional Liability", (60_000, 90_000),
        ),
    ],
)
def test_pricing_test_coordinate_corrections(tier, role, grade, title, expected):
    assert clamp_salary(
        tier, "senior", 10_000, 200_000, role=role, grade=grade,
        company_slug="not-a-bank-or-insurer", title=title, source_tier="mainstream",
    ) == expected


@pytest.mark.parametrize(
    "company_slug,tier,title,expected",
    [
        ("bochk", "retail_banking", "Team Head, Mortgage Services", (50_000, 80_000)),
        ("everbright-bank", "front_office", "Senior Manager, Investment Management", (70_000, 90_000)),
        ("za-bank", "back_office_operations", "Senior Manager, Investment Operations", (65_000, 80_000)),
        ("sun-life-hk", "insurance", "Director, Agency Recruitment", (80_000, 100_000)),
        ("sun-life-hk", "insurance", "Assistant Vice President, Control & Governance", (120_000, 150_000)),
    ],
)
def test_pricing_test_title_specific_corrections(company_slug, tier, title, expected):
    assert clamp_salary(
        tier,
        "senior", 10_000, 200_000, company_slug=company_slug, title=title,
        source_tier="mainstream",
    ) == expected
