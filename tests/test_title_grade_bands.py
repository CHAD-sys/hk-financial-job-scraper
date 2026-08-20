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
        ("Assistant Vice President, Underwriting", (150_000, 200_000)),
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


def test_insurance_vice_president_is_deliberately_unmapped():
    """Morris gave no range for insurance VP. We must not invent one."""
    lo, hi = clamp_salary(
        "insurance", "lead", 40_000, 60_000,
        company_slug="aia-hk", title="Vice President, Distribution", source_tier="mainstream",
    )
    assert (lo, hi) == (40_000, 60_000)


def test_non_tier_1_insurer_takes_the_15_percent_discount():
    """'The index above only applies to Tier 1 groups' — everyone else is discounted."""
    assert clamp_salary(
        "insurance", "mid", 20_000, 30_000,
        company_slug="allianz", title="Manager, Claims", source_tier="mainstream",
    ) == (round(50_000 * 0.85), round(60_000 * 0.85))


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
        ("Assistant VP (Compliance)", (50_000, 70_000)),
        ("Asst VP, Operations", (50_000, 70_000)),
        ("Assistant V.P., Risk", (50_000, 70_000)),
    ],
)
def test_assistant_vp_abbreviation_is_the_AVP_grade_not_VP(title, expected):
    """"Assistant VP" contains "VP" and was matching the higher VP band.

    Real row: "Assistant VP (Compliance) - CMB Wing Lung Bank" was being priced
    at the Vice President band (60-80k) instead of AVP (50-70k).
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
def test_product_manager_is_the_director_grade(title):
    """Morris: 'Senior Product Manager/Product Manager is a big category, it is also
    a senior role, similar to Director grade.'"""
    assert clamp_salary(
        "middle_office", "mid", 30_000, 45_000,
        company_slug="citibank-hk", title=title, source_tier="mainstream",
    ) == (100_000, 150_000)


@pytest.mark.parametrize("title", ["Assistant Product Manager", "Junior Product Manager"])
def test_a_junior_product_manager_is_not_a_director(title):
    """The category is senior; a title that explicitly says otherwise is not."""
    lo, hi = clamp_salary(
        "middle_office", "junior", 21_500, 25_000,
        company_slug="citibank-hk", title=title, source_tier="mainstream",
    )
    assert (lo, hi) != (100_000, 150_000)


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
