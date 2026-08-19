"""Deterministic salary-estimate clamp.

The DeepSeek enricher returns a Hong Kong monthly BASE salary estimate that is only
*soft*-guided by the prompt's Hays bands — so it can still drift above them, especially
at lead level (an ambiguous role mis-tiered as front office jumps toward the ceiling).

This module clips the model's estimate DOWN through four independent, ever-tightening
ceilings, then applies one final scale-down for boutique employers:
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
7. A final check that the range never comes out as a single value. Steps 1-4 only ever
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
    r"|graduate\s+(?:intern|programme|program|trainee)"
    r"|trainee|trainees"
    r"|trainee\s+(?:programme|program)"
    r"|industrial\s+placement"
    r"|placement\s+(?:programme|program)"
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
    for grade, pattern in patterns:
        if pattern.search(title):
            return grade
    return None


def _title_grade_ceiling(company_slug: str | None, title: str | None) -> int | None:
    """Bank/insurance management-grade cap for this title, or None if not applicable."""
    if not title:
        return None
    category = _company_category(company_slug)
    if category == "bank":
        grade = _detect_grade(title, _BANK_GRADE_PATTERNS)
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

    if source_tier == "boutique":
        if new_min is not None:
            new_min = round(new_min * BOUTIQUE_SALARY_MULTIPLIER)
        if new_max is not None:
            new_max = round(new_max * BOUTIQUE_SALARY_MULTIPLIER)

    # Final safety net: never emit a single-value range. If the endpoints inverted
    # (min above the newly-capped max) or simply landed equal, widen by pulling min
    # down to SINGLE_VALUE_MIN_FRACTION of max instead of collapsing to a flat point.
    if new_min is not None and new_max is not None and new_min >= new_max:
        new_min = round(new_max * SINGLE_VALUE_MIN_FRACTION)

    return new_min, new_max
