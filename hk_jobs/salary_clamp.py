"""Deterministic salary-estimate clamp.

The DeepSeek enricher returns a Hong Kong monthly BASE salary estimate that is only
*soft*-guided by the prompt's Hays bands — so it can still drift above them, especially
at lead level (an ambiguous role mis-tiered as front office jumps toward the ceiling).

This module clips the model's estimate DOWN through four independent, ever-tightening
ceilings, then applies a final scale-down for boutique employers. A documented
employer-and-title overlay may then replace that result for the one role it evidences:
1. The (tier, seniority) coarse ladder ceiling — as before.
2. The specific named role's own ceiling, if the model matched one (tables_monthly_hkd) —
   almost always tighter than its whole tier's general band.
3. A management-grade title cap, if the company is a bank or big insurance company and the
   job title clearly names a senior grade (AVP/VP/Director/etc.) — these employers'
   published bands run notably lower than the generic Hays tier bands at the same title.
4. An absolute HK$200,000/month ceiling that applies unconditionally, to every role, even
   when the tier/role/company is unrecognised.
5. A flat 70% scale-down for boutique-tier employers (`source_tier == "boutique"` — the
   Longtail-adapter companies, smaller HK financial firms scraped via LLM extraction). The
   Hays reference data behind steps 1-4 is calibrated for the large, established employers
   in companies.yaml's main sections; a medium/boutique firm's real pay scale runs lower
   than that reference at the same title, so this multiplies both endpoints (not just the
   ceiling) rather than adding another cap.
6. A floor raise (2026-07-22) — the one exception to "down-only" below. When the enricher
   confidently matched a specific standardized grade row (named-row match: junior->Analyst,
   mid->Associate, etc. — never the idiosyncratic proportional-position fallback), but its
   own raw estimate undershoots that row's own floor, the anchor table is trusted over the
   raw number, since it's the same table already used to cap the ceiling in step 2. Found
   in production: "Account Opening Officer, Commercial Banking" matched
   back_office_operations/operations_general/junior (Analyst row: HK$14,500-18,500) but the
   model's raw estimate was HK$11,200-14,400 — below the very row it matched. Down-only
   clamping has no way to catch an under-shoot like that, so this step adds a narrow,
   evidence-bounded exception: raise only up to a band we already trust for the ceiling.
7. An employer-specific overlay, if an exact company slug and a narrowly functional
   title pattern match. This is the exception to the generic boutique multiplier: it
   uses a documented role-specific band and is deliberately not a company-wide rule.
8. Morris's Manager-grade floor for a recognised finance coordinate: HK$40,000 at a
   smaller/unclassified firm, HK$50,000 at an explicitly large employer. Assistant,
   service/support and non-finance Manager titles are excluded before this can apply.
9. A final check that the range never comes out as a single value. Steps 1-4 only ever
   lower `est_max`, so if the model's own `est_min` sat above the newly-capped ceiling (or
   the two simply end up equal — e.g. an anchor band already collapsed to a flat number),
   the naive fix is to snap min down to max, which produces a literal "200k-200k" range.
   Instead this widens by pulling min down to SINGLE_VALUE_MIN_FRACTION of max.

Design choices:
- **Down-only, with one narrow floor exception (step 6).** The dominant failure mode this
  system was built for is over-estimation (~30% of estimates ran too high in production),
  so every ceiling only ever lowers. The floor raise is deliberately the single exception,
  and only fires on the SAME confidently-matched anchor row already used to cap the
  ceiling — it never invents a number beyond what's already in the table, and never
  applies to the idiosyncratic-fallback or unmatched-role cases where we're not sure
  enough to trust the anchor's floor over the model's own read of the job.
- **Fail open, except the absolute ceiling.** If a tier/role/company/title can't be
  recognised, that specific step is skipped — but step 4 (the HK$200,000 cap) is hardcoded
  in this module and always applies, so a broken or missing anchors file can never let an
  estimate through uncapped.

The enricher supplies the tier/role via "salary_tier"/"salary_role" (the exact keys it used
in the prompt's Step 3), and the caller passes the job's own `company_slug` and `title` for
step 3 — those are never LLM-inferred, they come straight from the scraped row. Classifying
by `company_slug` rather than the free-text `company` display name matters: the same
employer shows up under different strings depending on which adapter scraped it (e.g. Citi
as "Citi", "Citibank Hong Kong", or "Citibank (Hong Kong) Limited") but always shares one
slug, defined once in companies.yaml — so slug matching can't miss a display-name variant
the way substring-matching the free-text name did.
"""
from __future__ import annotations

import logging
import re

from hk_jobs import salary_anchors

logger = logging.getLogger(__name__)

# The ceiling and the anchor tables both come from hk_jobs.salary_anchors, which
# reads the calibrated JSON once. This constant used to be hardcoded here with a
# comment telling the reader to keep it in sync with the same number in the file
# — and conceding that the file's copy was "documentation". One number, one home.
GLOBAL_MAX_MONTHLY_HKD = salary_anchors.GLOBAL_MAX_MONTHLY_HKD

# Boutique (source_tier == "boutique") employers pay a flat fraction of what the same
# title at a mainstream/big employer would — applied to both endpoints, after every other
# ceiling above, so it scales the whole estimate down rather than just trimming the top.
BOUTIQUE_SALARY_MULTIPLIER = 0.7

# A range must never come out as a single value (min == max) — e.g. a "200k-200k" band
# from a ceiling that fell below the model's own min. When the final endpoints collapse
# or invert, widen by pulling min down to this fraction of max, rather than showing (or
# storing) a flat point.
SINGLE_VALUE_MIN_FRACTION = 0.5

# Bank / big-insurance company classifiers, matched by exact `company_slug` — the stable
# per-employer identifier defined once in companies.yaml, immune to the display-name
# variance that a free-text substring match would miss (see module docstring). Sourced
# directly from companies.yaml's own "Banking" / "Insurance" section groupings — mirroring
# the existing hardcoded bulge-bracket lists in the DeepSeek prompt (Step 3d), this is a
# hand-maintained allowlist. Update when companies.yaml gains/loses a bank or insurer.
_BANK_SLUGS = frozenset({
    "hsbc-hk", "bochk", "standard-chartered-hk", "hang-seng-bank", "dbs-hk",
    "bank-of-east-asia", "citibank-hk", "icbc-asia", "ccb-asia", "ocbc-wing-hang",
    "za-bank", "welab-bank", "mox-bank", "cmb-wing-lung",
    "agricultural-bank-china", "bank-of-communications", "citic-bank",
    "everbright-bank", "china-merchants-bank", "minsheng-bank", "psbc",
    "mufg", "mizuho", "smbc", "anz", "uob", "maybank", "sbi",
    "bank-of-america", "deutsche-bank", "goldman-sachs",
    "jpmorgan", "jpmorgan-am-hk", "jpmorgan-chase",
    "morgan-stanley", "barclays", "cicc",
})
_INSURANCE_SLUGS = frozenset({
    "aia-hk", "manulife-hk", "prudential-hk", "axa-hk", "zurich-hk",
    "fwd-insurance", "sun-life-hk", "hsbc-life", "generali-hk", "china-taiping",
    "china-life", "china-pacific-insurance", "ping-an", "chubb", "allianz",
    "swiss-re", "samsung-life", "metlife", "nippon-life",
})

# Ordered highest-to-lowest grade first: a title like "Associate Director" must match
# "associate director" before the bare "director" pattern gets a chance to fire.
_BANK_GRADE_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("managing_director", re.compile(r"\bmanaging director\b", re.I)),
    ("executive_director", re.compile(r"\bexecutive director\b", re.I)),
    ("associate_director", re.compile(r"\bassociate director\b|\bAD\b", re.I)),
    ("assistant_vice_president", re.compile(r"\bassistant vice president\b|\bAVP\b|\bassistant manager\b", re.I)),
    ("vice_president", re.compile(r"\bvice president\b|\bVP\b", re.I)),
    ("director", re.compile(r"\bdirector\b", re.I)),
    ("assistant_vice_president", re.compile(r"\bmanager\b", re.I)),  # plain "Manager" = AVP grade
)
_INSURANCE_GRADE_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("associate_director", re.compile(r"\bassociate director\b|\bAD\b", re.I)),
    ("director", re.compile(r"\bdirector\b", re.I)),
    ("senior_manager_or_principal", re.compile(r"\bsenior manager\b|\bprincipal\b", re.I)),
)

# ── Morris H.'s title-grade BANDS (2026-08-19) ───────────────────────────────
# Ordered highest-to-lowest, and the order is load-bearing: "Senior Vice
# President" must match before the bare "Vice President" pattern gets a chance,
# and "Associate Director" before "Director".
#
# Bank: Morris's parenthetical equivalences are encoded here — Senior Vice
# President == senior manager == associate director; Vice President == Manager /
# Senior Manager; Assistant Vice President == Manager. A bare "Manager" is
# genuinely ambiguous between the VP and AVP bands, so it keeps the existing
# table's reading (the lower one) rather than inventing a promotion.
# The third element is AUTHORITATIVE: may this match set the whole band (floor
# included), or may it only lower a ceiling?
#
# This distinction is the difference between a safe rule and a very unsafe one.
# The old table mapped a bare "Manager" to the AVP grade, which was harmless
# while it was only a CEILING — capping a HK$25,000 job at HK$70,000 does
# nothing. As a FLOOR the same mapping drags every "Business Transformation
# Manager" and "Customer Service Manager" at a bank up to HK$50,000, and on a
# real 78-row sample it moved the median +47.7%.
#
# "Manager" in a HK bank title spans most of the pay scale and is not evidence
# of a grade. Morris's own text reflects this: in the BANK list "Manager" is a
# parenthetical gloss on AVP, whereas in the INSURANCE list Manager and
# Assistant Manager are grades in their own right with their own bands. So the
# explicit grade words are authoritative here and the glosses are not.
_BANK_BAND_PATTERNS: tuple[tuple[str, re.Pattern, bool], ...] = (
    ("global_head", re.compile(r"\bglobal head\b|\bhead of global\b", re.I), True),
    ("division_head", re.compile(r"\bdivision head\b|\bhead of division\b", re.I), True),
    ("managing_director", re.compile(r"\bmanaging director\b|\bMD\b", re.I), True),
    ("executive_director", re.compile(r"\bexecutive director\b|\bED\b", re.I), True),
    ("senior_vice_president", re.compile(r"\bsenior vice president\b|\bSVP\b", re.I), True),
    # Morris folds associate director into the SVP grade.
    ("senior_vice_president", re.compile(r"\bassociate director\b|\bAD\b", re.I), True),
    ("assistant_vice_president",
     re.compile(r"\bassistant vice president\b|\bassistant\s+V\.?P\.?\b|\bass?t\.?\s+V\.?P\.?\b|\bAVP\b", re.I), True),
    ("vice_president", re.compile(r"\bvice president\b|\bVP\b", re.I), True),
    ("director", re.compile(r"\bdirector\b", re.I), True),
    # ── Functional titles (Morris, 2026-08-20) ───────────────────────────────
    # Ranked BELOW every explicit grade word above, on purpose: "Director, Trade
    # Product Manager" is a Director because the title says so, and "ED, Team Head"
    # is an Executive Director. The grade word is harder evidence about the HR
    # grade than the function is.
    ("team_head", re.compile(r"\bteam head\b|\bhead of team\b", re.I), True),
    # "Section Head is close to Team Head, close to Associate Director or
    # Director grade" (Morris H., 2026-08-21). Ranked with the other functional
    # titles, above the ambiguous glosses below — "Section Head" is specific
    # enough to be hard evidence, unlike a bare "Manager".
    ("section_head", re.compile(r"\bsection head\b|\bhead of section\b", re.I), True),
    ("general_manager",
     # "General Manager" / "Deputy GM" spelled out only. A bare \bGM\b is NOT
     # matched: live rows include "Senior Legal Counsel (GM)" and "Senior Treasury
     # Marketing Manager (GM-Corporate)", where the two letters are part of a
     # department name. Same trap as the bare "Manager" gloss.
     re.compile(r"\b(?:deputy|assistant|acting)?\s*general manager\b|\bdeputy\s+GM\b", re.I),
     True),
    ("product_manager", re.compile(r"\b(?:senior\s+)?product manager\b", re.I), True),
    # "Change Senior Associate to $45k-60k" (Morris H., 2026-08-21), a direct
    # correction on a live row — supersedes the earlier assistant_vice_president-
    # band guess. Deliberately "senior associate" only, not bare "associate":
    # Morris's number was for this exact title, and a bare "Associate" is far
    # more ambiguous (Research Associate, Client Associate...) than a title
    # that specifically says "Senior".
    ("senior_associate", re.compile(r"\bsenior associate\b", re.I), True),
    # Ambiguous glosses — ceiling only, exactly as before Morris's tables landed.
    ("assistant_vice_president", re.compile(r"\bassistant manager\b", re.I), False),
    ("assistant_vice_president", re.compile(r"\bmanager\b", re.I), False),
)

#: A Team Head of one of these does NOT take the Director band — see the anchors
#: file's `team_head_service_exclusion`. deepseek.py's prompt has carried this
#: carve-out since v8 because a bank has MANY service/CR team heads at ~50k-100k.
_SERVICE_TEAM = re.compile(
    r"client relationship|client servic|customer servic|\bCRM\b|servicing"
    r"|support|operations|\badmin\b|helpdesk|contact centre|call centre",
    re.I,
)

#: The category is senior; a title that explicitly says otherwise is not.
_JUNIOR_PRODUCT_MANAGER = re.compile(
    r"\b(?:assistant|junior|trainee|graduate|associate)\s+(?:senior\s+)?product manager\b",
    re.I,
)

# Relationship Manager is a banking function, not a corporate-grade word. It
# deliberately bypasses only the legacy bare-"Manager" ceiling below: an
# explicit AVP/VP/Director in the same title still wins through the higher
# priority grade patterns. The exact RM bands live in the anchor table, with a
# 20% lower set for SME and Retail Banking (owner calibration, 2026-08-21).
_RELATIONSHIP_MANAGER = re.compile(r"\b(?:assistant\s+|senior\s+)?relationship manager\b", re.I)
_EXPLICIT_AVP_GRADE = re.compile(
    r"\bassistant vice president\b|\bassistant\s+V\.?P\.?\b|\bass?t\.?\s+V\.?P\.?\b|\bAVP\b"
    r"|\bassistant manager\b",
    re.I,
)

# Insurance: the hierarchy INVERTS. VP and AVP are the top grades here, not the
# middle ones — the old caps table already knew this for FWD/Sun Life/Manulife;
# Morris states it as the general rule for insurers. `vice_president` is matched
# but has NO band (he left the range blank), so it resolves to None and the row
# falls through to the ordinary ceilings rather than to an invented number.
# At insurers Manager and Assistant Manager ARE named grades in Morris's list,
# each with its own band, so unlike the bank table they are authoritative.
_INSURANCE_BAND_PATTERNS: tuple[tuple[str, re.Pattern, bool], ...] = (
    ("assistant_vice_president",
     re.compile(r"\bassistant vice president\b|\bassistant\s+V\.?P\.?\b|\bass?t\.?\s+V\.?P\.?\b|\bAVP\b", re.I), True),
    ("vice_president", re.compile(r"\bvice president\b|\bVP\b", re.I), True),
    ("associate_director", re.compile(r"\bassociate director\b|\bAD\b", re.I), True),
    ("director", re.compile(r"\b(?:senior\s+)?director\b", re.I), True),
    ("senior_manager_or_principal",
     re.compile(r"\bsenior manager\b|\bprincipal\b", re.I), True),
    ("assistant_manager", re.compile(r"\bassistant manager\b", re.I), True),
    ("manager", re.compile(r"\bmanager\b", re.I), True),
)

# These are deliberately narrower than title-grade bands. Each combines a
# corporate grade with the function that Morris corrected in the Pricing Test;
# without the function, applying its range across an entire bank or insurer
# would create a new class of pricing error.
_BANK_FUNCTION_BAND_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("mortgage_team_head", re.compile(r"(?=.*\bteam head\b)(?=.*\bmortgage\b)", re.I)),
    ("investment_management_senior_manager", re.compile(r"(?=.*\bsenior manager\b)(?=.*\binvestment management\b)", re.I)),
    ("investment_operations_senior_manager", re.compile(r"(?=.*\bsenior manager\b)(?=.*\binvestment operations\b)", re.I)),
)
_INSURANCE_FUNCTION_BAND_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("agency_recruitment_director", re.compile(r"(?=.*\bdirector\b)(?=.*\bagency recruitment\b)", re.I)),
)

_BANK_BANDS = salary_anchors.BANK_BANDS
_INSURANCE_BANDS = salary_anchors.INSURANCE_BANDS
_BANK_FUNCTION_BANDS = salary_anchors.BANK_FUNCTION_BANDS
_INSURANCE_FUNCTION_BANDS = salary_anchors.INSURANCE_FUNCTION_BANDS
_INSURANCE_TIER_1 = salary_anchors.INSURANCE_TIER_1_SLUGS
_INSURANCE_TIER_2_DISCOUNT = salary_anchors.INSURANCE_TIER_2_DISCOUNT
_BANK_EXCEEDS_GLOBAL_MAX = salary_anchors.BANK_EXCEEDS_GLOBAL_MAX
_CHINESE_BANK_SLUGS = salary_anchors.CHINESE_BANK_SLUGS
_EMPLOYER_SALARY_OVERLAYS = salary_anchors.EMPLOYER_SALARY_OVERLAYS
_MANAGER_GRADE_FLOORS = salary_anchors.MANAGER_GRADE_FLOORS

_MANAGER_GRADE_TITLE = re.compile(r"\b(?:senior\s+)?manager\b", re.I)
_NON_MANAGER_GRADE_TITLE = re.compile(
    # A mixed-grade title ("Assistant/Senior Manager", "Consultant/Manager",
    # "Relationship Manager Trainee") is not proof that THIS post is priced at
    # the Manager grade. Treating each slash-separated possibility as the most
    # senior one was the exact broadening the first dry-run revealed.
    r"\b(?:assistant|associate|deputy|consultant|analyst|officer|trainee|intern|graduate|specialist)\b"
    r"|\b(?:asst|ass)\.?\s*/?\s*(?:senior\s+)?manager\b"
    r"|\b(?:relationship|customer|client|account|service|support|facilities|office|"
    r"human resources|people|learning|training|marketing|events|agency|sales|distribution|"
    r"business development|vendor|case|zone|software|technology|developer|engineer)\b",
    re.I,
)


# An internship is never paid on the ladder its desk sits on. The enricher's prompt says
# so in STEP 1 — "cap at HK$3,000-12,000/month regardless of company tier; bulge-bracket
# may reach HK$10,000-15,000; never exceed HK$15,000" — and the 2026-08-18 audit found the
# model ignoring it on 38% of internship listings (58 of 153 live rows above the cap, the
# worst at HK$41,500-83,500). The mechanism is legible: "Summer ANALYST, Investment
# Banking" matches the full-time IBD Analyst row and the band is copied verbatim, so the
# title's own word "Analyst" beats the internship rule. A prompt cannot enforce this; this
# module can.
#
# 15,000 is the prompt's absolute never-exceed, not its 3,000-12,000 typical band: this is
# a ceiling, and like every other ceiling here it only ever lowers. An estimate already
# below it is left exactly as the model wrote it.
INTERNSHIP_MAX_MONTHLY_HKD = 15_000

#: The one tier exempt from the flat bank/insurance title-grade ceilings. Revenue desks
#: run their own ladder here, several times the support-function cap for the same word
#: in the title. Named rather than inlined so `salary_repair` applies the same exemption
#: the clamp does — the two drifting apart is what a repair pass exists to prevent.
FRONT_OFFICE_TIER = "front_office"

# Whole words only, exactly as the prompt's own STEP 1 spells out — `\bintern\b` cannot
# match "Internal" or "International", which is the false-positive class the prompt
# explicitly warns about ("a Director, Internal Audit is a full-time senior role"). Bare
# "trainee" is included: in this market "Financial Market Trainee 2026" and "Management
# Trainee" are graduate programmes, and the audit found them priced on the full-time
# ladder too. "Trainer"/"Training" are untouched by the word boundary.
_INTERNSHIP_PATTERN = re.compile(
    r"\b(?:"
    r"intern|interns|internship|internships"
    r"|summer\s+(?:intern|analyst|associate)"
    # `programmes?` / `programs?`: without the optional plural the word boundary
    # after "programme" fails against "Programmes" (the trailing "s" is a word
    # character), and "2027 HSBC ... Graduate Programmes" was priced on the
    # full-time ladder for months as a result.
    r"|graduate\s+(?:intern|programmes?|programs?|trainee)"
    r"|trainee|trainees"
    r"|trainee\s+(?:programmes?|programs?)"
    r"|industrial\s+placement"
    r"|placement\s+(?:programmes?|programs?)"
    r")\b"
    r"|暑期實習|實習生|實習",
    re.I,
)


def is_internship(title: str | None) -> bool:
    """True when the title names a genuine internship / graduate / trainee programme.

    Title-only by design. It is the one field that is never LLM-inferred — it comes
    straight off the scraped row — so this cannot be talked out of firing by a model that
    has already decided the role sits on a front-office desk.
    """
    return bool(title) and bool(_INTERNSHIP_PATTERN.search(title))


# Real production bug (found 2026-07-22): DeepSeek occasionally emits the salary in
# "thousands" shorthand — e.g. 66 instead of 66000 — with no unit marker, so a naive
# int-coercion stores the bare number verbatim (found via a scan across 4,766 active
# jobs: 18 rows had salary_estimated_max under 150, e.g. "31-48" meaning HK$31-48/month).
# No monthly HK base salary in this market is plausibly below this floor, so a max under
# it is unambiguously the x1000 glitch, not a genuine tiny estimate. Confirmed via
# reproduction: re-running the same job/description through enrich_single gave normally-
# scaled numbers on retry, so this is stochastic model output noise, not something the
# prompt or reference table caused. Shared by both enrichment.py (the model's raw output)
# and salary_audit.py (the audit judge's own corrected_min/corrected_max) since either
# LLM call can produce it.
MAGNITUDE_GLITCH_CEILING = 3_000


def fix_salary_magnitude(est_min: int | None, est_max: int | None) -> tuple[int | None, int | None]:
    """Detect and correct the x1000 "thousands shorthand" glitch described above."""
    if est_max is None or est_max >= MAGNITUDE_GLITCH_CEILING:
        return est_min, est_max
    fixed_max = est_max * 1000
    fixed_min = est_min * 1000 if est_min is not None else None
    logger.warning(
        "Salary magnitude glitch detected (max=%s < %s) — correcting x1000 to %s-%s",
        est_max, MAGNITUDE_GLITCH_CEILING, fixed_min, fixed_max,
    )
    return fixed_min, fixed_max


_LADDERS = salary_anchors.LADDERS
_TABLES = salary_anchors.TABLES
_GRADE_CAPS = salary_anchors.GRADE_CAPS
_BANK_CAPS: dict = salary_anchors.BANK_CAPS
_INSURANCE_CAPS: dict = salary_anchors.INSURANCE_CAPS

# Valid tier keys, exposed so the enricher/tests can reference the canonical set.
TIER_KEYS = salary_anchors.TIER_KEYS


# Position a seniority level within a role's ordered title ladder (0.0 = the ladder's
# first/most-junior row, 1.0 = its last/most-senior row). Used only for ladders with
# idiosyncratic title labels; standardized grade ladders are mapped by name below.
_SENIORITY_FRACTIONS = {"junior": 0.0, "mid": 1 / 3, "senior": 2 / 3, "lead": 1.0}

# The merged anchor tables (2026-07-21) standardize most banking roles onto
# Analyst/Associate/VP/Director/MD rows and insurance roles onto the PERSOLKELLY
# 4-grade ladder. Map the enricher's seniority directly onto those row labels —
# fraction interpolation over a 5-row ladder would send "senior" to the Director
# row (index 2.7 -> 3), silently over-capping by a full grade. "lead" maps to
# Director, not MD: an MD-level estimate is only appropriate when the title
# actually says MD, and the bank-grade title caps handle that case separately.
_GRADE_ROW_NAMES = {
    "junior": ("Analyst", "Officer / Senior Analyst"),
    "mid": ("Associate", "Assistant Manager / Manager"),
    "senior": ("VP", "Senior Manager / Senior Director"),
    "lead": ("Director", "Head"),
}


def _role_band(tier: str | None, role: str | None, seniority: str | None) -> tuple[int, int] | None:
    """(lo, hi) of the *named* standardized grade row matching seniority, or None.

    Deliberately narrower than _role_ceiling: only returns a value on the confident
    name-matched row (junior->Analyst/Officer, etc.), never the idiosyncratic
    proportional-position fallback — we only want to trust this band enough to raise
    an estimate when we're as sure of the match as the ceiling logic already is.
    """
    if not tier or not role:
        return None
    ladder = _TABLES.get(tier, {}).get("roles", {}).get(role)
    if not ladder:
        return None
    for row_name in _GRADE_ROW_NAMES.get(seniority or "", ()):
        band = ladder.get(row_name)
        if isinstance(band, list) and band[0] is not None and band[1] is not None:
            return band[0], band[1]
    return None


def price_from_coordinate(tier: str | None, role: str | None, grade: str | None) -> tuple[int, int] | None:
    """The published band for an exact (tier, role, grade) cell, or None.

    Unlike `_role_band`, this needs no seniority-to-row-name translation: `grade`
    is the model's own read of which named row in the role's ladder this posting
    is (e.g. "cs_supervisor", "VP") — the same thing `/fix-s` asks a classifier to
    pick, now asked inline by the nightly enricher. A hit here is exact evidence,
    not the standardized-row-name-only subset `_role_band` trusts, so it also
    resolves the roughly half of ladders that use idiosyncratic grade labels the
    coarse 4-value `seniority` field cannot address at all.

    Public because `/fix-s/scripts/apply.py` prices a coordinate the same way the
    pipeline does; the two drifting into separate implementations is what this
    function exists to prevent.
    """
    if not tier or not role or not grade:
        return None
    band = _TABLES.get(tier, {}).get("roles", {}).get(role, {}).get(grade)
    if not isinstance(band, list) or len(band) != 2 or not band[0] or not band[1]:
        return None
    return int(band[0]), int(band[1])


def _role_ceiling(tier: str | None, role: str | None, seniority: str | None) -> int | None:
    """Ceiling of the role's ladder row matching `seniority`, or None if unrecognised."""
    if not tier or not role:
        return None
    ladder = _TABLES.get(tier, {}).get("roles", {}).get(role)
    if not ladder:
        return None
    # Standardized grade rows: match by name first.
    for row_name in _GRADE_ROW_NAMES.get(seniority or "", ()):
        band = ladder.get(row_name)
        if isinstance(band, list) and band[1] is not None:
            return band[1]
    # Idiosyncratic ladders: fall back to proportional position.
    bands = [band for band in ladder.values() if isinstance(band, list) and band[1] is not None]
    if not bands:
        return None
    frac = _SENIORITY_FRACTIONS.get(seniority or "", 0.5)
    idx = round(frac * (len(bands) - 1))
    return bands[idx][1]


def _company_category(company_slug: str | None) -> str | None:
    if company_slug in _BANK_SLUGS:
        return "bank"
    if company_slug in _INSURANCE_SLUGS:
        return "insurance"
    return None


def _detect_grade(title: str, patterns: tuple[tuple[str, re.Pattern], ...]) -> str | None:
    """First matching grade. Used by the legacy ceiling tables (2-tuples)."""
    for grade, pattern in patterns:
        if pattern.search(title):
            return grade
    return None


def _detect_grade_with_authority(
    title: str, patterns: tuple[tuple[str, re.Pattern, bool], ...]
) -> tuple[str, bool] | None:
    """(grade, authoritative) for the highest-ranked pattern this title matches."""
    for grade, pattern, authoritative in patterns:
        if pattern.search(title):
            return grade, authoritative
    return None


def title_grade_band(
    company_slug: str | None, title: str | None
) -> tuple[int, int, str] | None:
    """Morris's (lo, hi, grade_key) for a bank/insurer title, or None.

    Returns None — meaning "no opinion, use the ordinary ceilings" — for a
    company that is neither a bank nor an insurer, a title that names no known
    grade, and the one grade Morris deliberately left blank (insurance Vice
    President). Inventing a band for that last case is the failure this guards.

    Public because `/fix-s` and `salary_repair` must price a title exactly the
    way the pipeline does; the two drifting apart is what a repair pass exists
    to prevent.
    """
    if not title:
        return None
    category = _company_category(company_slug)
    if category == "bank":
        hit = _detect_grade_with_authority(title, _BANK_BAND_PATTERNS)
        if hit is None or not hit[1]:
            return None          # no match, or a ceiling-only gloss like "Manager"
        grade = hit[0]

        # Three narrow exclusions on the functional titles. Each one exists because
        # the title alone is not enough evidence for the band it would otherwise get.
        if grade == "team_head" and _SERVICE_TEAM.search(title):
            return None
        if grade == "product_manager" and _JUNIOR_PRODUCT_MANAGER.search(title):
            return None
        if grade == "general_manager" and company_slug not in _CHINESE_BANK_SLUGS:
            # Morris scoped this convention to Chinese banks. Anywhere else
            # "General Manager" means too many different things to price off.
            return None

        band = _BANK_BANDS.get(grade)
        if not band:
            return None
        return int(band[0]), int(band[1]), grade

    if category == "insurance":
        hit = _detect_grade_with_authority(title, _INSURANCE_BAND_PATTERNS)
        if hit is None or not hit[1]:
            return None
        grade = hit[0]
        band = _INSURANCE_BANDS.get(grade)
        if not band:
            return None
        lo, hi = int(band[0]), int(band[1])
        # "The index above only applies to Tier 1 groups below. For Tier 2
        # companies apply 15% discount." Anyone not on Morris's Tier 1 list
        # takes the discount — that is the literal reading, and it is also the
        # conservative one.
        if company_slug not in _INSURANCE_TIER_1 and _INSURANCE_TIER_2_DISCOUNT:
            factor = 1.0 - _INSURANCE_TIER_2_DISCOUNT
            lo, hi = round(lo * factor), round(hi * factor)
        return lo, hi, grade
    return None


def title_function_band(
    company_slug: str | None, title: str | None
) -> tuple[int, int, str] | None:
    """Return a narrow Morris Pricing-Test band for a bank/insurer title.

    Unlike a normal grade band this is specific to BOTH title and function, so
    it safely applies even to a front-office role.  The conventional broad
    grade bands remain disabled there because front-office compensation has a
    separate ladder.
    """
    if not title:
        return None
    category = _company_category(company_slug)
    if category == "bank":
        patterns, bands = _BANK_FUNCTION_BAND_PATTERNS, _BANK_FUNCTION_BANDS
    elif category == "insurance":
        patterns, bands = _INSURANCE_FUNCTION_BAND_PATTERNS, _INSURANCE_FUNCTION_BANDS
    else:
        return None

    for key, pattern in patterns:
        if pattern.search(title):
            band = bands.get(key)
            if band:
                return int(band[0]), int(band[1]), key
    return None


def employer_salary_overlay(
    company_slug: str | None, title: str | None
) -> tuple[int, int, str] | None:
    """Return a documented employer-and-title band, if one exactly applies.

    The title comes from the scraped role, rather than the model's inferred
    tier/role/grade. That makes the overlay resilient to the very classification
    miss it is intended to correct. A malformed future rule fails closed: it is
    logged and cannot affect an unrelated salary.
    """
    if not company_slug or not title:
        return None

    for rule in _EMPLOYER_SALARY_OVERLAYS:
        if rule.get("company_slug") != company_slug:
            continue
        try:
            pattern = rule["title_pattern"]
            band = rule["band_monthly_hkd"]
            if not isinstance(band, list) or len(band) != 2:
                raise ValueError("band must contain exactly two endpoints")
            if not re.search(pattern, title, re.I):
                continue
            lo, hi = int(band[0]), int(band[1])
            if lo <= 0 or hi < lo:
                raise ValueError("band must be positive and ascending")
            return lo, hi, str(rule["key"])
        except (KeyError, TypeError, ValueError, re.error) as exc:
            logger.warning("Ignoring malformed employer salary overlay %r: %s", rule, exc)
    return None


def manager_grade_floor(
    tier: str | None, role: str | None, company_slug: str | None, title: str | None
) -> tuple[int, int, str] | None:
    """Return Morris's Manager-grade floor when title and finance coordinate agree.

    A bare word "Manager" is not enough. The role must already be a recognised
    finance coordinate and must not be one of the explicitly non-manager-grade
    support functions. Employer size comes from durable company allowlists, not
    ``source_tier`` — which only identifies the scraper route.
    """
    if not tier or not role or not title or tier not in salary_anchors.TIER_KEYS:
        return None
    if role in set(_MANAGER_GRADE_FLOORS.get("excluded_salary_roles", ())):
        return None
    if not _MANAGER_GRADE_TITLE.search(title) or _NON_MANAGER_GRADE_TITLE.search(title):
        return None

    large = _MANAGER_GRADE_FLOORS.get("large_employer", {})
    additional_large = frozenset(large.get("additional_slugs", ()))
    is_large = company_slug in (_BANK_SLUGS | _INSURANCE_SLUGS | additional_large)
    group = large if is_large else _MANAGER_GRADE_FLOORS.get("smaller_or_unclassified", {})
    try:
        floor = int(group["minimum_monthly_hkd"])
        fallback_max = int(group["fallback_maximum_monthly_hkd"])
    except (KeyError, TypeError, ValueError):
        logger.warning("Manager-grade floor configuration is malformed; floor skipped.")
        return None
    if floor <= 0 or fallback_max <= floor:
        logger.warning("Manager-grade floor configuration is not an ascending positive band; floor skipped.")
        return None
    return floor, fallback_max, "large_employer" if is_large else "smaller_or_unclassified"


def apply_manager_grade_floor(
    est_min: int | None, est_max: int | None, floor_band: tuple[int, int, str] | None
) -> tuple[int | None, int | None]:
    """Apply one Manager-grade floor without re-running any other clamp rule.

    This tiny transform is public so the historical backfill can reproduce the
    new policy exactly without accidentally applying the boutique multiplier or
    a role ceiling for a second time to an estimate that is already final.
    """
    if floor_band is None:
        return est_min, est_max
    floor, fallback_max, _ = floor_band
    if est_max is None or est_max < floor:
        return floor, fallback_max
    if est_min is None or est_min < floor:
        return floor, est_max
    return est_min, est_max


def _title_grade_ceiling(company_slug: str | None, title: str | None) -> int | None:
    """Bank/insurance management-grade cap for this title, or None if not applicable."""
    if not title:
        return None
    category = _company_category(company_slug)
    if category == "bank":
        grade = _detect_grade(title, _BANK_GRADE_PATTERNS)
        if (
            grade == "assistant_vice_president"
            and _RELATIONSHIP_MANAGER.search(title)
            and not _EXPLICIT_AVP_GRADE.search(title)
        ):
            return None
        return _BANK_CAPS.get(grade) if grade else None
    if category == "insurance":
        grade = _detect_grade(title, _INSURANCE_GRADE_PATTERNS)
        return _INSURANCE_CAPS.get(grade) if grade else None
    return None


def clamp_salary(
    tier: str | None,
    seniority: str | None,
    est_min: int | None,
    est_max: int | None,
    *,
    role: str | None = None,
    grade: str | None = None,
    company_slug: str | None = None,
    title: str | None = None,
    source_tier: str | None = None,
) -> tuple[int | None, int | None]:
    """Clip (est_min, est_max) DOWN through the tier, role, title-grade, and global ceilings,
    then scale down for boutique employers.

    Each ceiling can only lower est_max, never raise it; whichever is tightest wins. Returns
    the estimate unchanged (aside from the unconditional global cap) when a given ceiling's
    inputs are unknown or the anchors file is unavailable. Never raises an estimate.
    ``est_min``/``est_max`` may be None (unable-to-estimate) and pass through.

    ``source_tier`` is the job's own `jobs.source_tier` column ("mainstream" or "boutique")
    — never LLM-inferred. When "boutique", both endpoints are scaled by
    BOUTIQUE_SALARY_MULTIPLIER after every ceiling above has been applied.
    """
    new_min, new_max = est_min, est_max

    band = _LADDERS.get(tier or "", {}).get(seniority or "")
    if band and band[1] is not None and new_max is not None:
        new_max = min(new_max, band[1])

    role_ceiling = _role_ceiling(tier, role, seniority)
    if role_ceiling is not None and new_max is not None:
        new_max = min(new_max, role_ceiling)

    # A flat "Vice President = HK$80,000" is a SUPPORT-function rule. Front-office desks
    # — trading, IB, private banking — have their own ladder in this file reaching
    # HK$166,500 (mid) and HK$200,000 (senior/lead), and applying the grade ceiling there
    # contradicts that table outright: a Goldman SPG trading VP is not paid an operations
    # VP's salary. Two independent re-estimates priced exactly those rows as correct at
    # HK$125,000-166,500, and `senior` is the one stratum a blind audit already found
    # reading LOW, so capping it further would compound a known error rather than fix one.
    grade_ceiling = _title_grade_ceiling(company_slug, title)
    if tier == FRONT_OFFICE_TIER:
        grade_ceiling = None
    if grade_ceiling is not None and new_max is not None:
        new_max = min(new_max, grade_ceiling)

    if new_max is not None:
        new_max = min(new_max, GLOBAL_MAX_MONTHLY_HKD)

    # The internship ceiling, applied after every ladder above so it wins over all of
    # them — the whole failure mode is a genuine internship matching a real full-time
    # band, so a cap that merely competed with those bands would lose.
    internship = is_internship(title)
    if internship and new_max is not None:
        new_max = min(new_max, INTERNSHIP_MAX_MONTHLY_HKD)

    # Floor raise: the one exception to "down-only". When the enricher confidently
    # matched a specific standardized grade row (named-row match, not the idiosyncratic
    # fallback) but its own raw estimate undershoots that row's own floor, trust the
    # anchor table over the raw number — the same table already used to cap the ceiling
    # above. If the whole estimate sits below the row's floor, adopt the row's own band
    # outright; if only the min is a touch low but max already reaches into/above the
    # row, just lift the min (preserves whatever signal the model's own max carried).
    # ...but never for an internship. The floor raise adopts a matched full-time grade
    # row outright when the estimate falls below it, which is exactly what an internship
    # capped to HK$15,000 now does — without this guard it would hand the IBD Analyst
    # band straight back and undo the cap above.
    band = None if internship else _role_band(tier, role, seniority)
    if band is not None:
        lo, hi = band
        if new_max is not None and new_max < lo:
            new_min, new_max = lo, hi
        elif new_min is not None and new_min < lo:
            new_min = lo
        if new_max is not None:
            # Re-apply the title-grade ceiling, not just the global one. Adopting the
            # band outright above hands back a maximum the grade ceiling had already
            # lowered — which is how 62 live rows came to sit above their own ceiling,
            # 46 of them still reproducible against this very function. The title is
            # hard evidence (it says "Vice President"); tier/role/seniority are model
            # output, so the title-derived ceiling wins. Exactly the reasoning that
            # already guards the internship cap against this same block.
            if grade_ceiling is not None:
                new_max = min(new_max, grade_ceiling)
            new_max = min(new_max, GLOBAL_MAX_MONTHLY_HKD)

    # Coordinate pricing (v13). The enricher's own exact (tier, role, grade) read,
    # not the seniority-to-standardized-row-name guess `_role_band` above depends
    # on. When it resolves, it REPLACES both endpoints outright, same treatment as
    # Morris's title-grade band below and for the same reason: a coordinate the
    # model committed to by name is harder evidence than the ceiling/floor stack
    # above, which only ever worked from the coarse `seniority` field. Runs before
    # Morris's block so a bank/insurance title match can still override it — title
    # is harder evidence again, this time about company-specific pay grades a
    # generic cross-employer table cannot know.
    coordinate_band = None if internship else price_from_coordinate(tier, role, grade)
    if coordinate_band is not None:
        new_min, new_max = coordinate_band
        # Same re-capping as the floor raise above, and for the same reason: adopting
        # the cell outright must not hand back a maximum the title-grade ceiling or
        # global cap had already lowered.
        if grade_ceiling is not None:
            new_max = min(new_max, grade_ceiling)
        new_max = min(new_max, GLOBAL_MAX_MONTHLY_HKD)
        new_min = min(new_min, new_max)

    # Morris H.'s title-grade band (2026-08-19). The ONE rule here that is not a
    # ceiling: a matched grade at a known bank or insurer replaces BOTH endpoints,
    # because at these employers the title is hard evidence of a pay grade and the
    # model's tier/role read is not. It therefore also fixes the error every
    # ceiling above is structurally blind to — a senior grade estimated far too LOW.
    #
    # Two exemptions, both already argued elsewhere in this module:
    #   - front office, because a trading VP is not an operations VP and the
    #     revenue ladder in the anchors file already reaches HK$200,000;
    #   - internships, because the whole internship failure mode is a genuine
    #     intern matching a real full-time band, so a band that merely competed
    #     with the cap would win and undo it.
    grade_band = None if internship else title_function_band(company_slug, title)
    if grade_band is None and not internship and tier != FRONT_OFFICE_TIER:
        grade_band = title_grade_band(company_slug, title)
    if grade_band is not None:
        lo, hi, grade_key = grade_band
        new_min, new_max = lo, hi
        # Managing Director (250k), Division Head (=MD) and Global Head (300k) are
        # the only bands that
        # may pass the global ceiling, and only on a deterministic title match at
        # a bank. That ceiling exists to stop an UNMATCHED estimate drifting up;
        # this is the opposite situation. Everything else still hard-caps.
        exempt = (
            _BANK_EXCEEDS_GLOBAL_MAX
            and _company_category(company_slug) == "bank"
            and grade_key in {"managing_director", "global_head", "division_head"}
        )
        if not exempt:
            new_max = min(new_max, GLOBAL_MAX_MONTHLY_HKD)
            new_min = min(new_min, new_max)

    if source_tier == "boutique":
        if new_min is not None:
            new_min = round(new_min * BOUTIQUE_SALARY_MULTIPLIER)
        if new_max is not None:
            new_max = round(new_max * BOUTIQUE_SALARY_MULTIPLIER)

    # This runs after the generic boutique multiplier on purpose. An overlay is
    # evidence for one employer's one function-bearing title, so applying the
    # multiplier again would recreate the error it exists to correct. The global
    # maximum remains a hard safety boundary for every path.
    overlay = employer_salary_overlay(company_slug, title)
    if overlay is not None and not internship:
        new_min, new_max, _ = overlay
        new_max = min(new_max, GLOBAL_MAX_MONTHLY_HKD)
        new_min = min(new_min, new_max)

    # The generic Manager-grade protection runs after the boutique multiplier,
    # otherwise a valid HK$40k floor would immediately become HK$28k. A narrower
    # employer overlay is still authoritative and has already won above.
    manager_floor = None if overlay is not None or internship else manager_grade_floor(
        tier, role, company_slug, title
    )
    new_min, new_max = apply_manager_grade_floor(new_min, new_max, manager_floor)

    # Final safety net: never emit a single-value range. If the endpoints inverted
    # (min above the newly-capped max) or simply landed equal, widen by pulling min
    # down to SINGLE_VALUE_MIN_FRACTION of max instead of collapsing to a flat point.
    if new_min is not None and new_max is not None and new_min >= new_max:
        new_min = round(new_max * SINGLE_VALUE_MIN_FRACTION)

    return new_min, new_max
