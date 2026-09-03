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
6. A reviewed smaller-bank adjustment keyed by Employer slug, independent of source_tier.
   CMB Wing Lung takes a 20% discount rounded to HK$5,000 band steps, with narrower reviewed
   Product Manager, Team Lead and Manager-grade bands. This replaces rather than stacks with
   the generic boutique discount if a Listing's collection route later changes.
7. A floor raise (2026-07-22) — the one exception to "down-only" below. When the enricher
   confidently matched a specific standardized grade row (named-row match: junior->Analyst,
   mid->Associate, etc. — never the idiosyncratic proportional-position fallback), but its
   own raw estimate undershoots that row's own floor, the anchor table is trusted over the
   raw number, since it's the same table already used to cap the ceiling in step 2. Found
   in production: "Account Opening Officer, Commercial Banking" matched
   back_office_operations/operations_general/junior (Analyst row: HK$14,500-18,500) but the
   model's raw estimate was HK$11,200-14,400 — below the very row it matched. Down-only
   clamping has no way to catch an under-shoot like that, so this step adds a narrow,
   evidence-bounded exception: raise only up to a band we already trust for the ceiling.
8. An employer-specific overlay, if an exact company slug and a narrowly functional
   title pattern match. This is the exception to the generic boutique multiplier: it
   uses a documented role-specific band and is deliberately not a company-wide rule.
9. Morris's Manager-grade floor for a recognised finance coordinate: HK$40,000 at a
   smaller/unclassified firm, HK$50,000 at an explicitly large employer. Assistant,
   service/support and non-finance Manager titles are excluded before this can apply.
10. A final check that the range never comes out as a single value. Steps 1-4 only ever
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
from dataclasses import dataclass
from enum import IntEnum
from math import ceil
from typing import Iterable

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

# A functional Product Manager title is not, by itself, a corporate Director grade.
# It can confirm an already-senior estimate, but must not manufacture a 100k-150k
# range from the ordinary 25k-70k product roles found in the reviewed bank sample.
_PRODUCT_MANAGER_DIRECTOR_MIN_RAW_MAX_HKD = (
    salary_anchors.PRODUCT_MANAGER_DIRECTOR_MIN_RAW_MAX_HKD
)
_AMBIGUOUS_MULTI_GRADE_TITLE_BAND = salary_anchors.AMBIGUOUS_MULTI_GRADE_TITLE_BAND

# A bare Manager token only represents a competing corporate grade when it is
# presented as a title option (start of title or after a separator). In
# ``Associate Director, Relationship Manager`` the word Manager belongs to the
# banking function and must not manufacture a second grade. The same distinction
# protects Product/Project/Account Manager titles without maintaining an endless
# list of functions.
_STANDALONE_MANAGER_GRADE = re.compile(
    r"(?:^|[/|;&,-]\s*)(?:senior\s+)?manager\b",
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
# Morris states it as the general rule for insurers. Morris supplied no direct VP
# range, so the anchor owns a deliberately broad safety band from the reviewed
# AVP floor to the global ceiling; this prevents a low functional coordinate from
# putting the top grade below AVP without claiming false precision.
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
_INSURANCE_TIER_2 = salary_anchors.INSURANCE_TIER_2_SLUGS
_INSURANCE_TIER_2_DISCOUNT = salary_anchors.INSURANCE_TIER_2_DISCOUNT
_BANK_EXCEEDS_GLOBAL_MAX = salary_anchors.BANK_EXCEEDS_GLOBAL_MAX
_CHINESE_BANK_SLUGS = salary_anchors.CHINESE_BANK_SLUGS
_SMALLER_BANK_SLUGS = salary_anchors.SMALLER_BANK_SLUGS
_SMALLER_BANK_DISCOUNT = salary_anchors.SMALLER_BANK_DISCOUNT
_SMALLER_BANK_ROUNDING_INCREMENT_HKD = salary_anchors.SMALLER_BANK_ROUNDING_INCREMENT_HKD
_SMALLER_BANK_REVIEWED_TITLE_BANDS = salary_anchors.SMALLER_BANK_REVIEWED_TITLE_BANDS
_MID_SIZED_BANK_DEPARTMENT_HEAD = salary_anchors.MID_SIZED_BANK_DEPARTMENT_HEAD
_MID_SIZED_BANK_DEPARTMENT_HEAD_SLUGS = salary_anchors.MID_SIZED_BANK_DEPARTMENT_HEAD_SLUGS
_BEA_SIZED_BANK_ASSISTANT_MANAGER = salary_anchors.BEA_SIZED_BANK_ASSISTANT_MANAGER
_BEA_SIZED_BANK_ASSISTANT_MANAGER_SLUGS = salary_anchors.BEA_SIZED_BANK_ASSISTANT_MANAGER_SLUGS
_SUN_LIFE_SIZED_INSURER_GRADES = salary_anchors.SUN_LIFE_SIZED_INSURER_GRADES
_SUN_LIFE_SIZED_INSURER_SLUGS = salary_anchors.SUN_LIFE_SIZED_INSURER_SLUGS
_MID_SIZED_INSURER_SENIOR_MANAGER = salary_anchors.MID_SIZED_INSURER_SENIOR_MANAGER
_MID_SIZED_INSURER_SENIOR_MANAGER_SLUGS = salary_anchors.MID_SIZED_INSURER_SENIOR_MANAGER_SLUGS
_EMPLOYER_SALARY_OVERLAYS = salary_anchors.EMPLOYER_SALARY_OVERLAYS
_BIG_FOUR_SLUGS = salary_anchors.BIG_FOUR_SLUGS
_BIG_FOUR_BANDS = salary_anchors.BIG_FOUR_BANDS
_BANK_PRODUCT_MANAGEMENT_BANDS = salary_anchors.BANK_PRODUCT_MANAGEMENT_BANDS
_JPMORGAN_SLUGS = salary_anchors.JPMORGAN_SLUGS
_JPMORGAN_BANDS = salary_anchors.JPMORGAN_BANDS
_HSBC_SIZED_BANK_SLUGS = salary_anchors.HSBC_SIZED_BANK_SLUGS
_HSBC_SIZED_BANK_BANDS = salary_anchors.HSBC_SIZED_BANK_BANDS
_MARKET_INFRASTRUCTURE_SLUGS = salary_anchors.MARKET_INFRASTRUCTURE_SLUGS
_MARKET_INFRASTRUCTURE_BANDS = salary_anchors.MARKET_INFRASTRUCTURE_BANDS
_ICBC_SIZED_BANK_SLUGS = salary_anchors.ICBC_SIZED_BANK_SLUGS
_ICBC_SIZED_BANK_BANDS = salary_anchors.ICBC_SIZED_BANK_BANDS
_ICBC_SIZED_BANK_TITLE_PATTERN = salary_anchors.ICBC_SIZED_BANK_TITLE_PATTERN
_FWD_SIZED_INSURER_SLUGS = salary_anchors.FWD_SIZED_INSURER_SLUGS
_FWD_SIZED_INSURER_BANDS = salary_anchors.FWD_SIZED_INSURER_BANDS
_DEUTSCHE_MIXED_SLUGS = salary_anchors.DEUTSCHE_MIXED_SLUGS
_DEUTSCHE_MIXED_BANDS = salary_anchors.DEUTSCHE_MIXED_BANDS
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
_ROLE_TABLE_SEMANTICS = salary_anchors.ROLE_TABLE_SEMANTICS
_GRADE_CAPS = salary_anchors.GRADE_CAPS
_BANK_CAPS: dict = salary_anchors.BANK_CAPS
_INSURANCE_CAPS: dict = salary_anchors.INSURANCE_CAPS

# Valid tier keys, exposed so the enricher/tests can reference the canonical set.
TIER_KEYS = salary_anchors.TIER_KEYS


def _role_seniority_band(
    tier: str | None, role: str | None, seniority: str | None
) -> tuple[int, int] | None:
    """Resolve a coarse seniority only through an explicit grade-ladder map.

    A title catalogue deliberately returns ``None``. Its row order is not a
    seniority scale; an exact ``grade`` coordinate may still select any row via
    :func:`price_from_coordinate`.
    """
    if not tier or not role or not seniority:
        return None
    semantics = _ROLE_TABLE_SEMANTICS.get(tier, {}).get(role, {})
    if semantics.get("kind") != "grade_ladder":
        return None
    row_name = (semantics.get("seniority_to_grade") or {}).get(seniority)
    if not row_name:
        return None
    band = _TABLES.get(tier, {}).get("roles", {}).get(role, {}).get(row_name)
    if (
        not isinstance(band, list)
        or len(band) != 2
        or not isinstance(band[0], int)
        or not isinstance(band[1], int)
        or band[0] <= 0
        or band[1] <= band[0]
    ):
        return None
    return band[0], band[1]


def _role_band(tier: str | None, role: str | None, seniority: str | None) -> tuple[int, int] | None:
    """(lo, hi) of the explicitly mapped grade row, or ``None``."""
    return _role_seniority_band(tier, role, seniority)


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


#: A partial coordinate's envelope is rejected past this width (docs/adr/0037).
#: Uppercase, so `salary._clamp_rule_state()` fingerprints it like every other
#: clamp rule and a change to it invalidates stored estimates.
MAX_ENVELOPE_WIDTH_RATIO = 3.0

#: Where each coarse seniority sits in a role's grade ladder, as a fraction of
#: the ladder's rows (which the table orders by pay). Used only when the exact
#: grade row is unknown AND `_role_band`'s name mapping did not resolve — about
#: half the ladders use idiosyncratic labels the four-value `seniority` field
#: cannot address. Slices overlap on purpose: the boundary between "mid" and
#: "senior" is genuinely fuzzy, and a slightly wide window beats no figure.
_SENIORITY_LADDER_WINDOW: dict[str, tuple[float, float]] = {
    "intern": (0.00, 0.25),
    "junior": (0.00, 0.40),
    "mid": (0.20, 0.65),
    "senior": (0.50, 0.90),
    "lead": (0.70, 1.00),
    "executive": (0.80, 1.00),
}


def normalise_coordinate(
    tier: str | None, role: str | None, grade: str | None
) -> tuple[str | None, str | None, str | None]:
    """Repair a coordinate whose role and grade arrived in the wrong fields.

    The candidate block prints a role's grades in the same snake_case a role key
    uses (``- middle_office / cybersecurity: security_engineer | ...``), so the
    model regularly answers with the GRADE in ``salary_role``. Measured on the
    2026-09-02 nightly that binned 12 otherwise-perfect classifications, each of
    which had an exact published cell waiting:

        network_engineer   -> it_infrastructure_support  45,000-65,000
        security_engineer  -> cybersecurity              35,000-65,000
        it_audit_security  -> it_governance_risk_compliance  65,000-80,000
        hr_business_partner-> human_resources            40,000-50,000

    Pure lookup against the published table — it can only ever move a name into
    the field the table itself says it belongs in, never invent one. Returns the
    input unchanged when the role is already valid or nothing matches.
    """
    roles = (_TABLES.get(tier or "", {}) or {}).get("roles") or {}
    if not roles or (role and role in roles):
        return tier, role, grade
    if role:
        # `role` is really a grade name: find the role whose ladder holds it.
        owners = sorted(name for name, ladder in roles.items() if role in ladder)
        if owners:
            return tier, owners[0], role
    if grade and grade in roles:
        # The two are simply swapped.
        return tier, grade, role if role in (roles.get(grade) or {}) else None
    return tier, role, grade


def price_from_role_envelope(
    tier: str | None, role: str | None, seniority: str | None = None
) -> tuple[int, int] | None:
    """The full published range of a role's ladder — its lowest grade's floor to
    its highest grade's ceiling — or None.

    A PARTIAL coordinate (docs/adr/0037). `price_from_coordinate` above needs all
    three parts and is the exact answer; this is the honest wider one for a
    posting the enricher could place in a role but not on a specific grade row.
    30 Roles in the 2026-09-02 run returned exactly that and were stored with no
    salary at all, which serves a Seeker worse than a real — if wide — published
    range for the right job family.

    Deliberately NOT a substitute for the exact cell: `clamp_salary` uses it only
    when `price_from_coordinate` returns None, and INTERSECTS it with any
    estimate already in hand rather than replacing one. Every number still comes
    from the anchor table; nothing here is inferred.
    """
    if not tier or not role:
        return None
    ladder = _TABLES.get(tier, {}).get("roles", {}).get(role) or {}
    bands = [band for band in ladder.values()
             if isinstance(band, list) and len(band) == 2 and band[0] and band[1]]
    if not bands:
        return None
    bands.sort(key=lambda band: (band[0], band[1]))

    # A whole ladder spans junior to Head — compliance_banking is 21,500-200,000
    # and change_project_management is 21,500-200,000 (9.3x). Publishing that as
    # an estimate is noise wearing a number's clothes.
    #
    # But rejecting it outright wasted 14 correct classifications on the
    # 2026-09-02 nightly. When we know the seniority, take the slice of the
    # ladder that seniority occupies instead: the rows ARE ordered by pay, so a
    # "junior" is in the bottom of them and a "lead" is at the top. That is still
    # entirely the published table — a narrower window on it, not a new number.
    window = _SENIORITY_LADDER_WINDOW.get((seniority or "").lower())
    if window is not None and len(bands) > 1:
        start = int(window[0] * len(bands))
        stop = max(start + 1, ceil(window[1] * len(bands)))
        bands = bands[start:stop] or bands
        low, high = int(min(b[0] for b in bands)), int(max(b[1] for b in bands))
        # The SAME width guard the un-narrowed envelope gets. Narrowing by
        # seniority usually lands inside it, but not always: a board audit found
        # "System Analyst" at 35,000-120,000 (3.4x) and "Customer Experience
        # Designer" at 23,000-80,000 (3.5x). A range that wide tells a Seeker
        # nothing, and an honest blank beats noise wearing a number's clothes.
        # Leaving this path unguarded was an oversight when the window was added.
        if high > low * MAX_ENVELOPE_WIDTH_RATIO:
            return None
        return low, high

    low, high = int(min(b[0] for b in bands)), int(max(b[1] for b in bands))
    # No seniority to narrow with — fall back to the honest blank past 3x. Real
    # grade rows in this table run about 1.4-1.7x wide.
    if high > low * MAX_ENVELOPE_WIDTH_RATIO:
        return None
    return low, high


def price_from_partial_coordinate(
    tier: str | None, role: str | None, seniority: str | None
) -> tuple[int, int] | None:
    """The band for a coordinate that names a role but no grade row.

    Tries the seniority-mapped grade row first — `mid` on `compliance_banking`
    is 50,000-75,000, against a 21,500-200,000 envelope for the same role — and
    only falls back to the role's whole range when that mapping does not resolve
    (about half the ladders use idiosyncratic grade labels the four-value
    `seniority` field cannot address).

    One definition, called by both `clamp_salary` and `salary.finalise`, so the
    "is there anything to price?" test and the pricing itself cannot disagree.
    """
    return _role_band(tier, role, seniority) or price_from_role_envelope(tier, role, seniority)


def _role_ceiling(tier: str | None, role: str | None, seniority: str | None) -> int | None:
    """Ceiling of the explicitly mapped grade row, or ``None``."""
    band = _role_seniority_band(tier, role, seniority)
    return band[1] if band is not None else None


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
    company that is neither a bank nor an insurer, or a title that names no known
    grade. Insurance Vice President is intentionally broad because its hierarchy
    is known while its precise market range is not.

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
        # "For Tier 2 companies apply 15% discount." Employer size is an explicit
        # classification, not an inference from absence: an insurer omitted from
        # Tier 1 may be unreviewed, newly configured, or simply use another scale.
        if company_slug in _INSURANCE_TIER_2 and _INSURANCE_TIER_2_DISCOUNT:
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
        rule_slug = rule.get("company_slug")
        rule_group = rule.get("company_group")
        matches_company = rule_slug == company_slug
        matches_group = rule_group == "big_four" and company_slug in _BIG_FOUR_SLUGS
        if not (matches_company or matches_group):
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
    support functions. Employer size comes from durable large- and smaller-employer
    allowlists, not ``source_tier`` — which only identifies the scraper route.
    """
    if not tier or not role or not title or tier not in salary_anchors.TIER_KEYS:
        return None
    # A coordinate is the pair, not two independently plausible strings. The old
    # guard checked only that ``tier`` existed, so an invented role—or a real role
    # borrowed from another tier—could manufacture a Manager-grade promotion.
    roles = salary_anchors.TABLES.get(tier, {}).get("roles", {})
    if role not in roles:
        return None
    if role in set(_MANAGER_GRADE_FLOORS.get("excluded_salary_roles", ())):
        return None
    if not _MANAGER_GRADE_TITLE.search(title) or _NON_MANAGER_GRADE_TITLE.search(title):
        return None

    large = _MANAGER_GRADE_FLOORS.get("large_employer", {})
    additional_large = frozenset(large.get("additional_slugs", ()))
    is_large = (
        company_slug not in _SMALLER_BANK_SLUGS
        and company_slug in (_BANK_SLUGS | _INSURANCE_SLUGS | additional_large)
    )
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


def _round_salary_band(value: int, increment: int) -> int:
    """Round one reviewed Employer-size adjustment to a normal salary-band step."""
    if increment <= 1:
        return round(value)
    return ((value + increment // 2) // increment) * increment


def smaller_bank_title_band(
    company_slug: str | None, title: str | None
) -> tuple[int, int, str] | None:
    """Return a management-reviewed function band for a classified smaller bank."""
    if company_slug not in _SMALLER_BANK_SLUGS or not title:
        return None

    key = None
    # Campus titles are their own reviewed CMB ranges. They must resolve before
    # the generic internship cap and bank-size rounding, which otherwise turn a
    # positive intern range into HK$0-5k and collapse graduate trainees to it.
    if re.search(r"\b(?:intern|internship)s?\b|暑期實習|實習生|實習", title, re.I):
        key = "intern"
    elif re.search(r"\btrainees?\b|\bgraduate\s+(?:programmes?|programs?)\b", title, re.I):
        key = "trainee"
    elif _EXPLICIT_AVP_GRADE.search(title) or re.search(
        r"\b(?:senior\s+)?vice president\b|\b(?:senior\s+)?director\b|\b(?:SVP|VP|ED|MD)\b",
        title,
        re.I,
    ):
        # Corporate-grade words are harder evidence than the functional labels below.
        return None
    if re.search(r"\bteam lead(?:er)?\b|\blead of (?:the )?team\b", title, re.I):
        key = "team_lead"
    elif re.search(r"\b(?:senior\s+)?product manager\b", title, re.I):
        if _JUNIOR_PRODUCT_MANAGER.search(title):
            return None
        key = "product_manager"
    elif re.match(r"^\s*manager\s*[-,:]", title, re.I):
        # In HK-bank titles the leading "Manager, …" token is the corporate grade;
        # function words later in the title must not erase that harder evidence.
        key = "manager_grade"
    elif _MANAGER_GRADE_TITLE.search(title) and not _NON_MANAGER_GRADE_TITLE.search(title):
        key = "manager_grade"

    band = _SMALLER_BANK_REVIEWED_TITLE_BANDS.get(key or "")
    if not isinstance(band, list) or len(band) != 2:
        return None
    try:
        lo, hi = int(band[0]), int(band[1])
    except (TypeError, ValueError):
        return None
    if lo <= 0 or hi <= lo:
        return None
    return lo, hi, key


def mid_sized_bank_department_head_band(
    company_slug: str | None, title: str | None
) -> tuple[int, int, str] | None:
    """Return the reviewed Director band for a large department at a smaller bank.

    The employer list classifies a bank by size; it does not make the salary rule
    employer-specific. Adding another reviewed comparable bank to the anchor
    registry applies the same narrowly-defined Head-of-department rule.
    """
    if company_slug not in _MID_SIZED_BANK_DEPARTMENT_HEAD_SLUGS or not title:
        return None
    try:
        pattern = _MID_SIZED_BANK_DEPARTMENT_HEAD["title_pattern"]
        band = _MID_SIZED_BANK_DEPARTMENT_HEAD["band_monthly_hkd"]
        if not re.search(pattern, title, re.I):
            return None
        if not isinstance(band, list) or len(band) != 2:
            raise ValueError("band must contain exactly two endpoints")
        lo, hi = int(band[0]), int(band[1])
        if lo <= 0 or hi <= lo:
            raise ValueError("band must be positive and ascending")
    except (KeyError, TypeError, ValueError, re.error) as exc:
        logger.warning("Ignoring malformed mid-sized-bank department-head anchor: %s", exc)
        return None
    return lo, hi, "mid_sized_bank_large_department_head"


def bea_sized_bank_assistant_manager_band(
    company_slug: str | None, title: str | None
) -> tuple[int, int, str] | None:
    """Return the reviewed functional Assistant Manager band for a BEA-sized bank."""
    if company_slug not in _BEA_SIZED_BANK_ASSISTANT_MANAGER_SLUGS or not title:
        return None
    try:
        pattern = _BEA_SIZED_BANK_ASSISTANT_MANAGER["title_pattern"]
        band = _BEA_SIZED_BANK_ASSISTANT_MANAGER["band_monthly_hkd"]
        if not re.search(pattern, title, re.I):
            return None
        if not isinstance(band, list) or len(band) != 2:
            raise ValueError("band must contain exactly two endpoints")
        lo, hi = int(band[0]), int(band[1])
        if lo <= 0 or hi <= lo:
            raise ValueError("band must be positive and ascending")
    except (KeyError, TypeError, ValueError, re.error) as exc:
        logger.warning("Ignoring malformed BEA-sized-bank Assistant Manager anchor: %s", exc)
        return None
    return lo, hi, "bea_sized_bank_functional_assistant_manager"


def sun_life_sized_insurer_grade_band(
    company_slug: str | None, title: str | None
) -> tuple[int, int, str] | None:
    """Return a uniform AD or AVP band for a reviewed Sun-Life-sized insurer."""
    if company_slug not in _SUN_LIFE_SIZED_INSURER_SLUGS or not title:
        return None
    hit = _detect_grade_with_authority(title, _INSURANCE_BAND_PATTERNS)
    if hit is None or not hit[1]:
        return None
    grade = hit[0]
    try:
        band = _SUN_LIFE_SIZED_INSURER_GRADES["bands_monthly_hkd"][grade]
        if not isinstance(band, list) or len(band) != 2:
            raise ValueError("band must contain exactly two endpoints")
        lo, hi = int(band[0]), int(band[1])
        if lo <= 0 or hi <= lo:
            raise ValueError("band must be positive and ascending")
    except KeyError:
        return None
    except (TypeError, ValueError) as exc:
        logger.warning("Ignoring malformed Sun-Life-sized-insurer grade anchor: %s", exc)
        return None
    return lo, hi, f"sun_life_sized_insurer_{grade}"


def mid_sized_insurer_senior_manager_band(
    company_slug: str | None, title: str | None
) -> tuple[int, int, str] | None:
    """Return the reviewed Senior Manager band for a Prudential-sized insurer."""
    if company_slug not in _MID_SIZED_INSURER_SENIOR_MANAGER_SLUGS or not title:
        return None
    try:
        pattern = _MID_SIZED_INSURER_SENIOR_MANAGER["title_pattern"]
        band = _MID_SIZED_INSURER_SENIOR_MANAGER["band_monthly_hkd"]
        if not re.search(pattern, title, re.I):
            return None
        if not isinstance(band, list) or len(band) != 2:
            raise ValueError("band must contain exactly two endpoints")
        lo, hi = int(band[0]), int(band[1])
        if lo <= 0 or hi <= lo:
            raise ValueError("band must be positive and ascending")
    except (KeyError, TypeError, ValueError, re.error) as exc:
        logger.warning("Ignoring malformed mid-sized-insurer Senior Manager anchor: %s", exc)
        return None
    return lo, hi, "mid_sized_insurer_senior_manager"


def ambiguous_multi_grade_title_band(
    title: str | None,
) -> tuple[int, int, str] | None:
    """Return a broad band when several *corporate* grade labels are combined.

    A functional suffix such as Relationship Manager is not a second grade. The
    configured bare-Manager pattern therefore has a stricter title-position test
    than the other grade tokens.
    """
    if not title:
        return None
    try:
        patterns = _AMBIGUOUS_MULTI_GRADE_TITLE_BAND["patterns"]
        minimum_matches = int(_AMBIGUOUS_MULTI_GRADE_TITLE_BAND["minimum_matches"])
        band = _AMBIGUOUS_MULTI_GRADE_TITLE_BAND["band_monthly_hkd"]
        if not isinstance(patterns, list) or not isinstance(band, list) or len(band) != 2:
            raise ValueError("patterns and band are malformed")
        matches = _ambiguous_grade_match_count(title, patterns)
        if matches < minimum_matches:
            return None
        lo, hi = int(band[0]), int(band[1])
        if lo <= 0 or hi <= lo:
            raise ValueError("band must be positive and ascending")
    except (KeyError, TypeError, ValueError, re.error) as exc:
        logger.warning("Ignoring malformed ambiguous multi-grade anchor: %s", exc)
        return None
    return lo, hi, "ambiguous_multi_grade_title"


def _ambiguous_grade_match_count(title: str, patterns: list[str] | None = None) -> int:
    """Count genuine corporate-grade alternatives in an ambiguity rule."""
    configured = patterns
    if configured is None:
        configured = _AMBIGUOUS_MULTI_GRADE_TITLE_BAND.get("patterns", [])
    if not isinstance(configured, list):
        return 0
    matches = 0
    for pattern in configured:
        try:
            if pattern == r"\bmanager\b":
                matched = bool(_STANDALONE_MANAGER_GRADE.search(title))
            else:
                matched = bool(re.search(pattern, title, re.I))
        except (TypeError, re.error):
            continue
        matches += matched
    return matches


#: "Senior <anything> Consultant". Up to four words may sit between the two,
#: which is what a Big Four specialist title looks like ("Senior Cloud Security
#: Consultant"). Bounded so it cannot span a slash-separated grade menu.
_SENIOR_CONSULTANT_RE = r"(?:\bsenior\b|\(\s*senior\s*\))(?:\s+[\w&-]+){0,4}\s+consultant\b"
#: A SECURITY specialism at Big Four commands a premium over generic advisory at
#: the same grade (owner calibration, docs/adr/0037 follow-up). Deliberately NOT
#: "technology" or "digital": at a Big Four firm those name whole service lines
#: ("Senior Consultant, Technology Consulting"), not a scarce specialism, and
#: treating a whole practice as premium is exactly the over-reach
#: test_big_four_shared_professional_services_bands_apply_to_every_firm pins.
_TECH_SPECIALISM_RE = (
    r"\b(?:cloud|cyber|cybersecurity|security|devsecops|infosec|"
    r"penetration\s+testing|pentest|red\s+team)\b"
)


def big_four_grade_band(
    company_slug: str | None, title: str | None, *, professional_practice: bool = False,
) -> tuple[int, int, str] | None:
    """Return an evidenced shared Big Four professional-services band.

    Hays is deliberately not converted with one blanket divisor here: it
    reports total annual package, while the reviewed ranges below are based on
    a grade-specific mix of owner calibration, source-listed salaries and
    Glassdoor base-pay signals recorded in the anchor data.
    """
    if company_slug not in _BIG_FOUR_SLUGS or not title:
        return None
    higher_grade = r"\b(?:associate\s+director|director|partner|principal|head|vice\s+president|VP)\b"
    # Associate Director is harder evidence and wins in compound titles such as
    # "Manager / Associate Director". The group deliberately has no generic
    # Director/Partner band: both Hays and the public market data are too
    # open-ended to turn into a safe base-pay replacement.
    if re.search(r"\bassociate director\b|\bAD\b", title, re.I):
        grade = "associate_director"
    elif re.search(higher_grade, title, re.I):
        return None
    # Two reviewed Big Four function/grade patterns are more specific than a
    # slash-separated title menu.  Preserve them before applying the generic
    # ambiguity guard: ``Senior Consultant / Manager`` still carries the reviewed
    # Senior Consultant band, and ``Manager / Senior Manager - M&A`` is still M&A.
    elif re.search(r"\(\s*senior\s*\)\s+consultant\b", title, re.I):
        grade = "senior_consultant"
    elif (
        re.search(r"\bmanager\b", title, re.I)
        and re.search(r"\b(?:M\s*&\s*A|Mergers?\s*(?:&|and)\s*Acquisitions?)\b", title, re.I)
    ):
        grade = "manager_ma"
    # A slash-separated grade menu is not otherwise evidence that the employer
    # is hiring at one particular grade. The dedicated ambiguous-title policy
    # can keep a deliberately broad range without false precision.
    elif _is_multi_grade_title(title):
        return None
    elif re.search(_SENIOR_CONSULTANT_RE, title, re.I):
        # "Senior Cloud Security Consultant", "Senior Data Consultant" — the
        # words are not adjacent, and requiring that graded every specialist
        # senior consultant as a plain Consultant (20,000-33,000 instead of
        # 40,000-55,000). A technology specialism carries its own row.
        grade = (
            "senior_consultant_technology"
            if re.search(_TECH_SPECIALISM_RE, title, re.I)
            else "senior_consultant"
        )
    elif (
        re.search(r"\bforensic(?:s)?\b", title, re.I)
        and re.search(r"\bsenior\b", title, re.I)
    ):
        grade = "forensics_senior"
    elif re.search(r"\bmanager\b", title, re.I) and not re.search(
        r"\(?\s*(?:assistant|senior|associate)\s*\)?\s+manager\b", title, re.I
    ):
        grade = "manager"
    elif not professional_practice:
        return None
    elif re.search(r"\bsenior manager\b", title, re.I):
        grade = "senior_manager"
    elif re.search(_SENIOR_CONSULTANT_RE, title, re.I):
        grade = (
            "senior_consultant_technology"
            if re.search(_TECH_SPECIALISM_RE, title, re.I)
            else "senior_consultant"
        )
    elif re.search(r"\bsenior associate\b|\bassistant manager\b", title, re.I):
        grade = "senior_associate_or_assistant_manager"
    elif re.search(r"\b(?:consultant|associate)\b", title, re.I):
        grade = "consultant_or_associate"
    else:
        return None
    try:
        band = _BIG_FOUR_BANDS[grade]
        if not isinstance(band, list) or len(band) != 2:
            raise ValueError("band must contain exactly two endpoints")
        lo, hi = int(band[0]), int(band[1])
        if lo <= 0 or hi <= lo:
            raise ValueError("band must be positive and ascending")
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("Ignoring malformed Big Four grade anchor: %s", exc)
        return None
    return lo, hi, f"big_four_{grade}"


def _is_multi_grade_title(title: str) -> bool:
    """Whether slash syntax presents more than one corporate grade.

    A slash in a functional phrase (for example ``Valuation Dispute /
    Litigation``) is harmless.  We only reject it where multiple grade words,
    or a grade paired with the standalone ``Senior`` qualifier, appear in the
    same title.
    """
    if re.search(r"\b(?:staff|junior|senior)\b\s*(?:/|&|or|to)\s*\b(?:staff|junior|senior)\b", title, re.I):
        return True
    if "/" not in title:
        return False
    grade_words = re.findall(
        r"\b(?:analyst|associate|consultant|manager|director|partner|principal)\b",
        title,
        re.I,
    )
    return len(grade_words) >= 2 or (
        bool(grade_words) and bool(re.search(r"\bsenior\b", title, re.I))
    )


def bank_ordinary_product_manager_band(
    company_slug: str | None,
    title: str | None,
    *,
    product_management: bool = False,
) -> tuple[int, int, str] | None:
    """Return an evidence-bounded ungraded bank-product band by product domain.

    Product management is a job family, not a corporate grade. Once the
    classifier has made that family decision, an employer's ``Business
    Manager`` or ``Innovation Manager`` title can still identify the product
    economics. Formal grade, seniority, ambiguity and high-scope signals
    deliberately opt out.
    """
    if (
        not product_management
        or company_slug not in _BANK_SLUGS
        or not title
        or _is_multi_grade_title(title)
    ):
        return None
    if re.search(
        r"\b(?:senior|lead|head|assistant|associate|junior|graduate|trainee|"
        r"director|managing director|executive director|vice president|avp|vp|ad)\b",
        title,
        re.I,
    ):
        return None
    if re.search(r"\b(?:regional|global|cross[- ]?border|enterprise|platform|gen\s*ai|AI)\b", title, re.I):
        return None
    try:
        # Functional responsibility takes precedence over the underlying product
        # vertical: governance over investment products remains governance, and
        # e-banking inside private banking remains a digital product role.
        if re.search(r"\b(?:governance|proposition|portfolio|segment|innovation|strategy)\b", title, re.I):
            domain = "governance_proposition_portfolio"
        elif (
            re.search(r"\b(?:digital|mobile|e-?banking|online|app|journey|fintech|finance\s+tech)\b", title, re.I)
            or ("金融科技" in title and "证券" not in title)
        ):
            domain = "digital_mobile_ebanking"
        elif re.search(r"\b(?:trade finance|trade|working capital)\b", title, re.I) or "贸易融资" in title:
            domain = "trade_finance"
        elif re.search(r"\b(?:card|loan|lending|deposit|liabilit(?:y|ies)|secured|consumer|reward)\b", title, re.I):
            domain = "cards_lending_deposits"
        elif re.search(r"\b(?:cash|transaction|payment|GTS)\b", title, re.I):
            domain = "cash_transaction"
        elif re.search(r"\b(?:wealth|investment|asset|private bank|ETF|fund)\b", title, re.I) or any(
            phrase in title for phrase in ("财富管理", "资产配置", "私人财富")
        ):
            domain = "wealth_investment"
        elif re.search(r"\b(?:markets?|securit(?:y|ies)|equities|custody|fixed income|derivative)\b", title, re.I) or "证券" in title:
            domain = "markets_securities_custody"
        else:
            domain = "unresolved_product_domain"
        band = _BANK_PRODUCT_MANAGEMENT_BANDS[domain]
        if not isinstance(band, list) or len(band) != 2:
            raise ValueError("band must contain exactly two endpoints")
        lo, hi = int(band[0]), int(band[1])
        if lo <= 0 or hi <= lo:
            raise ValueError("band must be positive and ascending")
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("Ignoring malformed ordinary bank Product Manager anchor: %s", exc)
        return None
    return lo, hi, f"bank_product_management_{domain}"


def jpmorgan_vp_band(
    company_slug: str | None, title: str | None,
) -> tuple[int, int, str] | None:
    """Return JPMorgan's reviewed HK Vice President band."""
    if company_slug not in _JPMORGAN_SLUGS or not title:
        return None
    if not re.search(r"\bvice president\b|\bVP\b", title, re.I):
        return None
    try:
        band = _JPMORGAN_BANDS["vice_president"]
        if not isinstance(band, list) or len(band) != 2:
            raise ValueError("band must contain exactly two endpoints")
        lo, hi = int(band[0]), int(band[1])
        if lo <= 0 or hi <= lo:
            raise ValueError("band must be positive and ascending")
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("Ignoring malformed JPMorgan VP anchor: %s", exc)
        return None
    return lo, hi, "jpmorgan_vice_president"


def hsbc_sized_bank_lead_product_band(
    company_slug: str | None, title: str | None,
) -> tuple[int, int, str] | None:
    """Return the reviewed Lead Product band for HSBC-scale banks."""
    if company_slug not in _HSBC_SIZED_BANK_SLUGS or not title:
        return None
    if not (re.search(r"\blead\b", title, re.I) and re.search(r"\bproduct\b", title, re.I)):
        return None
    try:
        band = _HSBC_SIZED_BANK_BANDS["lead_product"]
        if not isinstance(band, list) or len(band) != 2:
            raise ValueError("band must contain exactly two endpoints")
        lo, hi = int(band[0]), int(band[1])
        if lo <= 0 or hi <= lo:
            raise ValueError("band must be positive and ascending")
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("Ignoring malformed HSBC-scale Lead Product anchor: %s", exc)
        return None
    return lo, hi, "hsbc_sized_bank_lead_product"


def hsbc_sized_bank_spread_products_vp_band(
    company_slug: str | None, title: str | None,
) -> tuple[int, int, str] | None:
    """Return the reviewed Spread Products Banker VP band, excluding JPMorgan."""
    if (
        company_slug not in _HSBC_SIZED_BANK_SLUGS
        or company_slug in _JPMORGAN_SLUGS
        or not title
        or not re.search(r"\bspread\s+products\s+banker\b", title, re.I)
        or not re.search(r"\bvice\s+president\b|\bVP\b", title, re.I)
    ):
        return None
    try:
        band = _HSBC_SIZED_BANK_BANDS["spread_products_banker_vp"]
        if not isinstance(band, list) or len(band) != 2:
            raise ValueError("band must contain exactly two endpoints")
        lo, hi = int(band[0]), int(band[1])
        if lo <= 0 or hi <= lo:
            raise ValueError("band must be positive and ascending")
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("Ignoring malformed Spread Products Banker VP anchor: %s", exc)
        return None
    return lo, hi, "hsbc_sized_bank_spread_products_banker_vp"


def dbs_sized_bank_product_role_band(
    company_slug: str | None, title: str | None,
) -> tuple[int, int, str] | None:
    """Return reviewed DBS-scale product/relationship bands within HSBC-scale banks."""
    if company_slug not in salary_anchors.DBS_SIZED_BANK_SLUGS or not title:
        return None
    lower = title.lower()
    if re.search(r"(?:\bsenior\b|\(\s*senior\s*\)).{0,80}\bproduct\s+manager\b", lower):
        grade = "senior_product_manager"
    elif re.search(r"\bcash\s+product\s+manager\b", lower):
        grade = "cash_product_manager"
    elif re.search(r"\brelationship\s+manager\b", lower):
        if re.search(r"\b(?:director|md|vice\s+president|VP)\b", lower):
            return None
        prefix = lower.split("relationship manager", 1)[0]
        if re.search(
            r"\b(?:senior|assistant|associate|deputy|director|md|vice\s+president|vp)\b",
            prefix,
        ):
            return None
        grade = "relationship_manager"
    else:
        return None
    try:
        band = salary_anchors.DBS_SIZED_BANK_BANDS[grade]
        if not isinstance(band, list) or len(band) != 2:
            raise ValueError("band must contain exactly two endpoints")
        lo, hi = int(band[0]), int(band[1])
        if lo <= 0 or hi <= lo:
            raise ValueError("band must be positive and ascending")
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("Ignoring malformed DBS-scale product-role anchor: %s", exc)
        return None
    return lo, hi, f"dbs_sized_bank_{grade}"


def market_infrastructure_grade_band(
    company_slug: str | None, title: str | None,
) -> tuple[int, int, str] | None:
    """Return the reviewed VP/AVP band for HKEX-scale market infrastructure."""
    if company_slug not in _MARKET_INFRASTRUCTURE_SLUGS or not title:
        return None
    if re.search(
        r"\bassistant vice president\b|\bassistant\s+V\.?P\.?\b|\bAVP\b",
        title,
        re.I,
    ):
        grade = "assistant_vice_president"
    elif re.search(r"\bvice president\b|\bVP\b", title, re.I):
        grade = "vice_president"
    else:
        return None
    try:
        band = _MARKET_INFRASTRUCTURE_BANDS[grade]
        if not isinstance(band, list) or len(band) != 2:
            raise ValueError("band must contain exactly two endpoints")
        lo, hi = int(band[0]), int(band[1])
        if lo <= 0 or hi <= lo:
            raise ValueError("band must be positive and ascending")
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("Ignoring malformed market-infrastructure grade anchor: %s", exc)
        return None
    return lo, hi, f"market_infrastructure_{grade}"


def icbc_sized_bank_product_manager_band(
    company_slug: str | None, title: str | None,
) -> tuple[int, int, str] | None:
    """Return the reviewed digital/solutions Product Manager band for ICBC-scale banks."""
    if company_slug not in _ICBC_SIZED_BANK_SLUGS or not title:
        return None
    try:
        if not re.search(_ICBC_SIZED_BANK_TITLE_PATTERN, title, re.I):
            return None
        band = _ICBC_SIZED_BANK_BANDS["digital_solutions_product_manager"]
        if not isinstance(band, list) or len(band) != 2:
            raise ValueError("band must contain exactly two endpoints")
        lo, hi = int(band[0]), int(band[1])
        if lo <= 0 or hi <= lo:
            raise ValueError("band must be positive and ascending")
    except (KeyError, TypeError, ValueError, re.error) as exc:
        logger.warning("Ignoring malformed ICBC-scale Product Manager anchor: %s", exc)
        return None
    return lo, hi, "icbc_sized_bank_digital_solutions_product_manager"


def icbc_sized_bank_market_role_band(
    company_slug: str | None, title: str | None,
) -> tuple[int, int, str] | None:
    """Return reviewed Global Markets Sales or Investment Consultant bands."""
    if company_slug not in _ICBC_SIZED_BANK_SLUGS or not title:
        return None
    title_lower = title.lower()
    if "global markets" in title_lower and "sales" in title_lower:
        grade = "global_markets_sales"
    elif "investment consultant" in title_lower:
        grade = "investment_consultant"
    else:
        return None
    try:
        band = _ICBC_SIZED_BANK_BANDS[grade]
        if not isinstance(band, list) or len(band) != 2:
            raise ValueError("band must contain exactly two endpoints")
        lo, hi = int(band[0]), int(band[1])
        if lo <= 0 or hi <= lo:
            raise ValueError("band must be positive and ascending")
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("Ignoring malformed ICBC-scale market-role anchor: %s", exc)
        return None
    return lo, hi, f"icbc_sized_bank_{grade}"


def fwd_sized_insurer_grade_band(
    company_slug: str | None, title: str | None,
) -> tuple[int, int, str] | None:
    """Return the reviewed Director/Underwriter/AVP band for FWD-sized insurers."""
    if company_slug not in _FWD_SIZED_INSURER_SLUGS or not title:
        return None
    if re.search(r"\bunderwriter\b", title, re.I):
        grade = "underwriter"
    elif re.search(r"\bassistant vice president\b|\bassistant\s+V\.?P\.?\b|\bAVP\b", title, re.I):
        grade = "assistant_vice_president"
    elif re.search(r"\bdirector\b", title, re.I) and not re.search(
        r"\bassociate director\b", title, re.I
    ):
        grade = "director"
    else:
        return None
    try:
        band = _FWD_SIZED_INSURER_BANDS[grade]
        if not isinstance(band, list) or len(band) != 2:
            raise ValueError("band must contain exactly two endpoints")
        lo, hi = int(band[0]), int(band[1])
        if lo <= 0 or hi <= lo:
            raise ValueError("band must be positive and ascending")
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("Ignoring malformed FWD-sized insurer anchor: %s", exc)
        return None
    return lo, hi, f"fwd_sized_insurer_{grade}"


def deutsche_mixed_director_vp_band(
    company_slug: str | None, title: str | None,
) -> tuple[int, int, str] | None:
    """Return Deutsche's reviewed band for a title combining Director and VP."""
    if company_slug not in _DEUTSCHE_MIXED_SLUGS or not title:
        return None
    if not re.search(r"\bdirector\b", title, re.I) or not re.search(
        r"\bvice president\b|\bVP\b", title, re.I
    ):
        return None
    try:
        band = _DEUTSCHE_MIXED_BANDS["mixed_director_vp"]
        if not isinstance(band, list) or len(band) != 2:
            raise ValueError("band must contain exactly two endpoints")
        lo, hi = int(band[0]), int(band[1])
        if lo <= 0 or hi <= lo:
            raise ValueError("band must be positive and ascending")
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("Ignoring malformed Deutsche mixed Director/VP anchor: %s", exc)
        return None
    return lo, hi, "deutsche_bank_mixed_director_vp"


class SalaryRulePriority(IntEnum):
    """Explicit precedence for authoritative whole-band salary rules.

    Higher values win. The names describe why one source of evidence outranks
    another; changing source-code order cannot change the result.
    """

    BASE_TITLE_GRADE = 100
    AMBIGUOUS_TWO_GRADE = 150
    EMPLOYER_GROUP_GRADE = 200
    AMBIGUOUS_MULTI_GRADE = 300
    REVIEWED_EMPLOYER_SIZE = 400
    REVIEWED_EMPLOYER_ROLE = 500
    NARROW_EMPLOYER_ROLE = 550
    EXPLICIT_MIXED_GRADE = 600
    EXACT_EMPLOYER_OVERLAY = 1_000


@dataclass(frozen=True)
class SalaryRuleMatch:
    """One whole-band rule that matched a Listing's stable facts."""

    rule: str
    band: tuple[int, int]
    evidence_key: str
    priority: SalaryRulePriority


@dataclass(frozen=True)
class SalaryRuleResolution:
    """The winning rule plus every competing match for audit/debug output."""

    winner: SalaryRuleMatch | None
    matches: tuple[SalaryRuleMatch, ...]
    conflicts: tuple[SalaryRuleMatch, ...]
    has_top_priority_conflict: bool


def _salary_rule_match(
    rule: str,
    result: tuple[int, int, str] | None,
    priority: SalaryRulePriority,
) -> SalaryRuleMatch | None:
    if result is None:
        return None
    lo, hi, evidence_key = result
    return SalaryRuleMatch(rule, (lo, hi), evidence_key, priority)


def resolve_salary_rule_matches(
    matches: Iterable[SalaryRuleMatch],
) -> SalaryRuleResolution:
    """Resolve matches independently of their construction/source-code order.

    Different lower-priority bands are expected and retained as diagnostics. If
    two top-priority rules disagree, emit a warning: the lexicographic rule name
    is only a deterministic fail-safe, not a hidden policy decision.
    """
    ordered = tuple(sorted(matches, key=lambda match: (int(match.priority), match.rule)))
    if not ordered:
        return SalaryRuleResolution(None, (), (), False)

    winner = ordered[-1]
    conflicts = tuple(match for match in ordered if match.band != winner.band)
    top = tuple(match for match in ordered if match.priority == winner.priority)
    has_top_priority_conflict = len({match.band for match in top}) > 1
    if has_top_priority_conflict:
        logger.warning(
            "Conflicting salary rules at priority %s; deterministic winner=%s; matches=%s",
            winner.priority.name,
            winner.rule,
            [(match.rule, match.band) for match in top],
        )
    return SalaryRuleResolution(
        winner=winner,
        matches=ordered,
        conflicts=conflicts,
        has_top_priority_conflict=has_top_priority_conflict,
    )


def salary_rule_resolution(
    company_slug: str | None,
    title: str | None,
    *,
    role: str | None = None,
    internship: bool = False,
    base_title_grade_band: tuple[int, int, str] | None = None,
) -> SalaryRuleResolution:
    """Collect and resolve every authoritative whole-band rule for a Listing.

    ``base_title_grade_band`` is the already-adjusted generic bank/insurance
    title band. The clamp passes it after employer-size discounts so diagnostics
    describe the number that can actually win, rather than the pre-discount band.
    """
    candidates: list[SalaryRuleMatch] = []

    def add(
        rule: str,
        result: tuple[int, int, str] | None,
        priority: SalaryRulePriority,
    ) -> None:
        match = _salary_rule_match(rule, result, priority)
        if match is not None:
            candidates.append(match)

    # CMB campus bands are reviewed exceptions to the generic internship cap.
    # No full-time grade or employer rule is allowed to join them.
    if internship:
        add(
            "smaller_bank_title",
            smaller_bank_title_band(company_slug, title),
            SalaryRulePriority.REVIEWED_EMPLOYER_SIZE,
        )
        return resolve_salary_rule_matches(candidates)

    add("base_title_grade", base_title_grade_band, SalaryRulePriority.BASE_TITLE_GRADE)
    add(
        "big_four_grade",
        big_four_grade_band(
            company_slug,
            title,
            professional_practice=role == "professional_practice_advisory",
        ),
        SalaryRulePriority.EMPLOYER_GROUP_GRADE,
    )
    add(
        "bank_ordinary_product_manager",
        bank_ordinary_product_manager_band(
            company_slug,
            title,
            product_management=role == "product_management",
        ),
        SalaryRulePriority.EMPLOYER_GROUP_GRADE,
    )
    ambiguous_band = ambiguous_multi_grade_title_band(title)
    ambiguity_priority = (
        SalaryRulePriority.AMBIGUOUS_MULTI_GRADE
        if title and _ambiguous_grade_match_count(title) >= 3
        else SalaryRulePriority.AMBIGUOUS_TWO_GRADE
    )
    add("ambiguous_multi_grade", ambiguous_band, ambiguity_priority)

    for rule, result in (
        ("smaller_bank_title", smaller_bank_title_band(company_slug, title)),
        ("mid_sized_bank_department_head", mid_sized_bank_department_head_band(company_slug, title)),
        ("bea_sized_bank_assistant_manager", bea_sized_bank_assistant_manager_band(company_slug, title)),
        ("sun_life_sized_insurer_grade", sun_life_sized_insurer_grade_band(company_slug, title)),
        ("mid_sized_insurer_senior_manager", mid_sized_insurer_senior_manager_band(company_slug, title)),
    ):
        add(rule, result, SalaryRulePriority.REVIEWED_EMPLOYER_SIZE)

    for rule, result in (
        ("jpmorgan_vp", jpmorgan_vp_band(company_slug, title)),
        ("hsbc_sized_bank_lead_product", hsbc_sized_bank_lead_product_band(company_slug, title)),
        ("hsbc_sized_bank_spread_products_vp", hsbc_sized_bank_spread_products_vp_band(company_slug, title)),
        ("market_infrastructure_grade", market_infrastructure_grade_band(company_slug, title)),
        ("icbc_sized_bank_product_manager", icbc_sized_bank_product_manager_band(company_slug, title)),
        ("icbc_sized_bank_market_role", icbc_sized_bank_market_role_band(company_slug, title)),
        ("fwd_sized_insurer_grade", fwd_sized_insurer_grade_band(company_slug, title)),
    ):
        add(rule, result, SalaryRulePriority.REVIEWED_EMPLOYER_ROLE)

    add(
        "dbs_sized_bank_product_role",
        dbs_sized_bank_product_role_band(company_slug, title),
        SalaryRulePriority.NARROW_EMPLOYER_ROLE,
    )
    add(
        "deutsche_mixed_director_vp",
        deutsche_mixed_director_vp_band(company_slug, title),
        SalaryRulePriority.EXPLICIT_MIXED_GRADE,
    )
    add(
        "employer_salary_overlay",
        employer_salary_overlay(company_slug, title),
        SalaryRulePriority.EXACT_EMPLOYER_OVERLAY,
    )
    return resolve_salary_rule_matches(candidates)


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
    if (
        coordinate_band is None
        and not internship
        and new_min is None
        and new_max is None
    ):
        # Partial coordinate (docs/adr/0037): the role is known, the grade row is
        # not. Fill the gap from the role's own published band rather than store
        # nothing — 30 Roles in the 2026-09-02 run returned exactly this shape.
        #
        # Deliberately ONLY when there is no estimate at all. This rung exists to
        # replace a blank, never to move a number: a role matched without a grade
        # is weaker evidence than every ceiling and floor above, and letting it
        # touch an existing figure would override the deliberate pass-through for
        # roles whose ladder `_role_band` cannot resolve (see
        # test_floor_raise_does_not_apply_to_idiosyncratic_fallback_roles).
        coordinate_band = price_from_partial_coordinate(tier, role, seniority)
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
    if (
        grade_band is not None
        and grade_band[2] == "product_manager"
        and _PRODUCT_MANAGER_DIRECTOR_MIN_RAW_MAX_HKD
        and (est_max is None or est_max < _PRODUCT_MANAGER_DIRECTOR_MIN_RAW_MAX_HKD)
    ):
        # The management review explicitly corrected ordinary/mobile/digital Product
        # Manager roles down to the normal bank-product range. Preserve a true
        # Director-level reading only when the model independently saw a senior
        # range; otherwise the title alone is insufficient evidence for a promotion.
        grade_band = None
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

    smaller_bank = company_slug in _SMALLER_BANK_SLUGS
    if source_tier == "boutique" and not smaller_bank:
        if new_min is not None:
            new_min = round(new_min * BOUTIQUE_SALARY_MULTIPLIER)
        if new_max is not None:
            new_max = round(new_max * BOUTIQUE_SALARY_MULTIPLIER)

    # Employer size is a pricing fact; source_tier is only a collection-route fact.
    # A reviewed smaller bank therefore takes its own adjustment even when its Listings
    # come from a mainstream board. It replaces (rather than stacks with) the generic
    # boutique discount, and the anchor file owns both the registry and calibration.
    if smaller_bank and _SMALLER_BANK_DISCOUNT:
        factor = 1.0 - _SMALLER_BANK_DISCOUNT
        if new_min is not None:
            new_min = _round_salary_band(
                round(new_min * factor), _SMALLER_BANK_ROUNDING_INCREMENT_HKD
            )
        if new_max is not None:
            new_max = _round_salary_band(
                round(new_max * factor), _SMALLER_BANK_ROUNDING_INCREMENT_HKD
            )

    # Resolve every authoritative whole-band rule in one place. Before this
    # resolver existed, the same candidates appeared as a long series of `if`
    # blocks and whichever block happened to be last silently won. Priorities now
    # encode the policy, and the resolution retains all competing matches for an
    # audit to explain. The generic title band is passed after employer discounts,
    # so selecting it cannot accidentally undo a smaller-bank calibration.
    base_title_grade_band = None
    if grade_band is not None and new_min is not None and new_max is not None:
        base_title_grade_band = (new_min, new_max, grade_band[2])
    rule_resolution = salary_rule_resolution(
        company_slug,
        title,
        role=role,
        internship=internship,
        base_title_grade_band=base_title_grade_band,
    )
    if rule_resolution.winner is not None:
        new_min, new_max = rule_resolution.winner.band
        winner_exceeds_global_max = (
            _BANK_EXCEEDS_GLOBAL_MAX
            and rule_resolution.winner.rule == "base_title_grade"
            and _company_category(company_slug) == "bank"
            and rule_resolution.winner.evidence_key
            in {"managing_director", "global_head", "division_head"}
        )
        if not winner_exceeds_global_max:
            new_max = min(new_max, GLOBAL_MAX_MONTHLY_HKD)
            new_min = min(new_min, new_max)

    # The generic Manager-grade protection runs after the boutique multiplier,
    # otherwise a valid HK$40k floor would immediately become HK$28k. Any exact
    # title rule is authoritative for both endpoints, so the generic floor cannot
    # distort it (for example Cash Product Manager 35k-50k into 25k-50k).
    manager_floor = None if rule_resolution.winner is not None or internship else manager_grade_floor(
        tier, role, company_slug, title
    )
    new_min, new_max = apply_manager_grade_floor(new_min, new_max, manager_floor)

    # Final safety net: never emit a single-value range. If the endpoints inverted
    # (min above the newly-capped max) or simply landed equal, widen by pulling min
    # down to SINGLE_VALUE_MIN_FRACTION of max instead of collapsing to a flat point.
    if new_min is not None and new_max is not None and new_min >= new_max:
        new_min = round(new_max * SINGLE_VALUE_MIN_FRACTION)

    return new_min, new_max
