"""
DeepSeek LLM enricher — v4: adds English translation of Chinese postings.

v1: title-only, 500 max_tokens
v2: title-only, 250 max_tokens, 20 concurrent workers
v3: title + description (capped 2 000 chars clean text), 350 max_tokens
    — skills coverage expected to jump from 75% → 90%+
v4: many boutique/"Exclusive" postings arrive with Mandarin/Cantonese titles
    and descriptions. The model now (a) returns an English `title_en` for every
    job (translating faithfully when the source is Chinese, verbatim when it is
    already English) and (b) always writes `description_summary` in clean English
    regardless of the source language, reviewing garbled/mixed-language text
    rather than parroting it. `title` and `description_clean` in the DB are left
    untouched — the original is always preserved.
v5: salary estimator recalibrated to the 2026 Hays Asia Salary Guide (HK). Adds a
    function-tier step (front / commercial / middle / back office) and much lower,
    Hays-anchored monthly bands — the old benchmarks over-estimated by 2-3x at
    senior levels. See salary_guidlines/HK_FINANCE_SALARY_GUIDELINES.md.
v6: the Hays bands are no longer hand-typed into the prompt. They are extracted per
    role/tier/level into salary_guidlines/hk_salary_anchors.json (the single source
    of truth, derived directly from the 2026 Hays HK tables) and rendered into the
    prompt at import time. The estimator is now told the bands are a HARD ceiling and
    to bias low / default to the modest tier — targeting the residual over-estimation.
    Update the JSON when a newer Hays guide lands; the prompt tracks it automatically.
v7: the model now also returns "salary_tier" — the exact anchor key of the function tier
    it used. hk_jobs.salary_clamp then clips the estimate DOWN to that (tier, seniority)
    band's ceiling deterministically in enrichment.py, so an over-band number can no longer
    reach the DB no matter what the model returns. The prompt still does the detection; the
    clamp only enforces the ceiling.
v8: switched the reference table from the coarse 7-tier x 4-level ladder to the ~50
    granular named-role ladders in hk_salary_anchors.json's tables_monthly_hkd (the model
    now also returns "salary_role" — the specific role key it matched, or null). Added a
    hard HK$200,000/month absolute ceiling and deterministic management-grade title caps
    for banks and big insurance companies (see management_grade_caps_monthly_hkd in the
    anchors file and hk_jobs.salary_clamp) — the estimator was running ~30% too high in
    production, mostly on senior titles at large employers being mis-tiered upward.
v9: migrated off deepseek-chat/deepseek-reasoner (retired 2026-07-24) to deepseek-v4-pro
    with thinking mode enabled. A/B test against 4 known-bad postings showed materially
    better tier/role selection (e.g. a KPMG "Associate Director" role dropped from a
    stale HK$333k to a well-reasoned HK$110k on tier/role alone, no clamp involved) — the
    remaining overestimation was as much a model-reasoning problem as a data-calibration
    one. Thinking mode drops temperature/top_p (unsupported, silently ignored) and needs
    a much larger max_tokens: the reasoning trace is billed as output and can exhaust a
    small budget before the model ever writes the final JSON answer.
    v9.1: v4-pro + thinking took ~16s/job — ~21h to re-enrich the full active set even at
    20 concurrent workers. Switched to deepseek-v4-flash (same thinking-mode toggle, same
    cheap base rate as the old deepseek-chat), keeping the large max_tokens budget from v9.
    v9.2: briefly set reasoning_effort="max" to push flash to reason as hard as possible —
    burned through the account balance in ~9 minutes with no proven quality gain over
    default effort (the v9 A/B test used default, not max). Reverted to default effort;
    thinking stays enabled, just without forcing maximum reasoning depth on every job.
v10: granular 3-source reference table + prefix-cached prompt layout. The anchors JSON is
    now a weighted merge of Hays 2026 + PERSOLKELLY 2025 + Adecco 2026 (60% most
    conservative / 25% / 15% where they overlap — see scripts/build_merged_salary_anchors.py),
    ~95 named roles with standardized Analyst/Associate/VP/Director/MD grade rows, including
    new IT/HR/admin/CS/marketing ladders for support roles at financial firms. Added explicit
    "Team Head" disambiguation (CR/service team heads are manager-grade, NOT the Director row
    — the #1 reported mispricing). Prompt reordered static-first/job-data-last so DeepSeek's
    automatic prefix caching bills the big reference block at ~1/10th input rate.
v11: thinking mode OFF. It was enabled in v9 for genuinely better tier/role selection,
    but the reasoning trace is billed as output tokens and it dominated the bill: the
    2026-08-16 run spent $4.26 enriching 806 Roles, ~94% of it on traces averaging
    ~7,000 output tokens a job to produce a ~350-token answer. Nothing in the suite
    inspected the request body, so the switch that cost the money was untested — see
    tests/test_deepseek_request.py, which now pins the shape of what we send.
    With thinking off, max_tokens returns to answer-sized (700 with a description,
    450 title-only) and temperature/top_p are live again (0.2/0.9) — thinking mode
    silently ignored both, so the model has been sampling at its defaults since v9.
    NOTE the tradeoff, deliberately accepted: the v9 A/B test that justified thinking
    measured tier/role accuracy WITH it on. Turning it off may cost some of that
    accuracy. The deterministic guards are unchanged and still catch the failure mode
    thinking was brought in to fix — hk_jobs.salary_clamp still clips every estimate
    to its (tier, seniority) band ceiling, the HK$200k/month absolute cap still
    applies, and the management-grade caps still apply. Watch hk_jobs.salary_audit
    for tier drift before assuming this was free.
    PROMPT_VERSION is deliberately NOT bumped: it derives from model + prompt text +
    anchors + clamp (none of which changed here), so this does not re-enrich the
    active set. Existing rows keep their v9/v10 estimates; only new calls get the
    cheaper shape.

v12: thinking mode BACK ON, with per-task output budgets and loud truncation.
    v11's cost diagnosis was right and its cure was wrong. Sizing max_tokens for the
    answer (700/450) while the model still had to produce one left no room at all:
    every call on 2026-08-19 returned exactly 700.0 output tokens, truncated mid-JSON,
    failed to parse, burned all three retries and wrote NOTHING. Two nightly runs
    produced zero enrichments while still billing ~$0.21 a night. The newest row in
    job_enrichments sat at 2026-08-17 for two days and no alarm existed to say so.
    Three changes: thinking is enabled again (the v9 A/B test showed measurably better
    tier/role selection, and tier/role is what selects the anchor cell that prices the
    job); max_tokens is allocated PER TASK from the observed ledger rather than as one
    blanket number — 10,000 with a description, 5,000 title-only, 4,000 for the audit
    judge; and truncation is now its own error class, counted into usage totals and
    never retried, because retrying a budget failure is deterministic and only triples
    the bill. reasoning_effort stays at its default: "max" was tried in v9.2 and burned
    the balance in ~9 minutes for no proven gain.
    The bill goes back up — roughly $0.60 a night against v11's $0.07 — which is the
    deliberate price of an estimator that produces estimates.

API key: set DEEPSEEK_API_KEY env var.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

import httpx

from hk_jobs import salary, salary_anchors, salary_corrections
from hk_jobs.salary_context import build_salary_context
from hk_jobs.ai_budget import BudgetExceeded, RunBudget
from hk_jobs.salary_corrections import Correction

logger = logging.getLogger(__name__)

_API_URL = "https://api.deepseek.com/chat/completions"
# v4-flash is the fast, cheap tier (same base rate as the retired deepseek-chat).
# It was chosen in v9.1 to carry thinking mode at a workable ~s/job; thinking is off
# as of v11 (see the changelog) but flash remains the right tier on price and speed.
# This module's PROMPT_VERSION string still carries a "v4pro" manual tag from the
# first v9 attempt — renaming it would re-enrich the whole active set for no gain.
_MODEL = "deepseek-v4-flash"
_DESC_MAX_CHARS = 2_000   # cap to keep prompt tight; descriptions are typically 1–4 KB

# ── Per-task output budgets (v13) ────────────────────────────────────────────
#
# With thinking on, `max_tokens` must cover the reasoning trace AND the answer.
# These are sized from the usage ledger, not from a guess: under thinking the
# observed spend was 6,500–10,200 billed output tokens per role across seven
# nightly runs, against a blanket 12,000 cap that the average never reached.
#
# v11 replaced that blanket with 700/450 — sized for the answer alone — and every
# call on 2026-08-19 returned exactly 700.0 output tokens, truncated mid-JSON, for
# zero enrichments across two nights. Never size this for the answer while
# thinking is enabled.
#
# The two differ because the tasks differ. The description branch reads up to
# 2,000 characters of posting, picks a tier/role/grade out of a 471-cell table and
# writes a summary. The title-only branch has no posting to reason over and no
# `description_summary` to produce, so it gets a smaller budget rather than the
# same one — that is the "per task" part, which the pre-v11 blanket never did.
#
# v13 raises those allocations after the 2026-08-22 salary-evaluation pilot:
# 88 of 400 description-backed calls ended at the 10,000-token server cap.
# `max_tokens` is enforced by DeepSeek *while* it generates; this non-streaming
# client receives the answer only after generation ends, so it cannot lift the
# cap after a response has started. The safe rule is therefore: reserve enough
# room for the complete reasoning trace plus final JSON, and reject every
# `finish_reason="length"` result rather than persisting a partial answer.
#
# 16,000 leaves roughly 5,800 tokens above the highest earlier observed trace
# while keeping a firm, auditable cost ceiling. Title-only work is cheaper but
# still needs room for thinking, so it is raised proportionally to 8,000.
MAX_TOKENS_WITH_DESCRIPTION = 16_000
MAX_TOKENS_TITLE_ONLY = 8_000


class TruncatedAnswer(RuntimeError):
    """The model ran out of output budget before finishing its JSON.

    It gets its own error class so the failure is legible in a log. As a bare
    `json.JSONDecodeError` it was indistinguishable from a transient fault, was
    retried three times, and hid a total two-day outage behind "all retries
    failed".
    """

# PROMPT_VERSION is derived, not written down — see the bottom of this module.
# hk_jobs.enrichment stores it alongside each enrichment row and re-enriches any
# active job whose stored version doesn't match, on every regular run, so a
# change reaches jobs that get soft-deleted and reactivated later rather than
# only what happens to be active the day it ships.

# Salary anchor table — the single source of truth, extracted from the 2026 Hays
# Asia Salary Guide (HK) into a structured JSON. Loaded and rendered into the prompt
# ONCE at import so every call carries the calibrated bands without re-reading the file.
# Anchors come from hk_jobs.salary_anchors — the same object the deterministic
# clamp reads. They used to be parsed here a second time from the same path, so
# the prompt the model saw and the ceiling applied to its answer were two
# independent reads of one file.

_TIER_LABELS = {
    "front_office":
        "FRONT OFFICE (IB/M&A, PE, hedge fund, asset mgmt, trading, private-banking RM) — "
        "HIGHEST; use ONLY if the title clearly names one of these desks",
    "commercial_corporate_banking":
        "COMMERCIAL/CORPORATE BANKING (corporate/commercial/SME/FI RM, transaction banking, wealth mgmt)",
    "corporate_finance_accounting":
        "CORPORATE FINANCE & ACCOUNTING (in-house FP&A, controller, finance mgr, tax, treasury)",
    "middle_office":
        "MIDDLE OFFICE (risk, compliance, internal audit, product control)",
    "insurance":
        "INSURANCE (actuarial, underwriting, claims, insurance risk/compliance/audit)",
    "retail_banking":
        "RETAIL BANKING (branch, retail RM, mortgage, teller)",
    "back_office_operations":
        "BACK OFFICE / OPERATIONS (treasury/trade/payment/fund/securities ops, KYC, settlements) — LOWEST",
}

# Fallback used only if the JSON is missing/corrupt — the previous v5 default ladder,
# so enrichment never crashes just because the anchor file was moved.
_SALARY_REFERENCE_FALLBACK = (
    "- BACK/MIDDLE OFFICE, COMMERCIAL/RETAIL, IN-HOUSE FINANCE, INSURANCE (most jobs):\n"
    "    junior 18k-35k | mid 30k-60k | senior 60k-110k | lead 100k-160k | MD/Head 150k-300k\n"
    "- FRONT OFFICE (IB/PE/HF/asset mgmt/trading/private-banking RM only):\n"
    "    junior 40k-85k | mid 75k-130k | senior 120k-170k | lead 165k-250k | MD/Head 250k-500k"
)


def _fmt_k(x: int | None) -> str:
    return f"{x // 1000}k" if x is not None else "+"


def _fmt_band(band: list) -> str:
    lo, hi = band
    if hi is None:
        return f"{_fmt_k(lo)}+"
    if lo == hi == 200_000:  # open-ended top row collapsed by the HK$200k global cap
        return "200k (capped)"
    if lo == hi:
        return f"{_fmt_k(hi)}"
    return f"{_fmt_k(lo)}-{_fmt_k(hi)}"


def _load_salary_reference() -> str:
    """
    Render the JSON's granular NAMED-ROLE ladders (tables_monthly_hkd) into a compact
    prompt block — one line per role, high tier first. This replaces the old coarse
    tier x seniority ladder: a specific named role (e.g. "audit_banking") is almost
    always a tighter, more accurate band than its whole function tier's general range.
    Each role line is prefixed with its "[role_key]" so the model can echo it back
    verbatim as "salary_role".
    """
    try:
        data = salary_anchors.ANCHORS
        tables = data["tables_monthly_hkd"]
        order = data["tier_order_low_to_high"][::-1]  # display highest-paid first
        lines = []
        for tier in order:
            tier_data = tables.get(tier)
            if not tier_data:
                continue
            lines.append(f"- {_TIER_LABELS.get(tier, tier)}:")
            for role, levels in tier_data.get("roles", {}).items():
                parts = [f"{title} {_fmt_band(band)}" for title, band in levels.items()]
                lines.append(f"    [{role}] " + " | ".join(parts))
        return "\n".join(lines)
    except Exception as exc:  # missing file, bad JSON, schema drift — degrade gracefully
        logger.warning("Salary anchor file unavailable (%s); using fallback ladder.", exc)
        return _SALARY_REFERENCE_FALLBACK


# v14 sends only per-posting candidates.  Keeping the full 729-cell catalogue
# in every request both encouraged salary-led grade picking and consumed most
# of the prompt.  The renderer remains as an emergency diagnostic helper, but
# it is intentionally not inserted into production requests.
_SALARY_REFERENCE = ""


def _load_blinded_salary_reference() -> str:
    """
    Render `salary_anchors.blinded_vocabulary()` into a compact prompt block —
    the same (tier -> role -> grade) tree as `_load_salary_reference()`, but with
    every dollar band stripped to grade NAMES only (v13 — coordinate pricing).

    Deliberately blind: shown the money, a model tends to pick the grade whose
    band suits the salary it already had in mind rather than the grade the
    posting actually describes, which turns independent evidence into a menu
    (the same reasoning `/fix-s` uses for its classifier vocabulary). This block
    is placed BEFORE the numbered `_SALARY_REFERENCE` fallback in the prompt so
    the coordinate pick is asked for first — not a hard guarantee in a single
    linear prompt, but the closest a one-call design can get to fix-s's
    two-script separation.
    """
    try:
        vocab = salary_anchors.blinded_vocabulary()
        order = salary_anchors.ANCHORS["tier_order_low_to_high"][::-1]
        lines = []
        for tier in order:
            tier_data = vocab.get(tier)
            if not tier_data:
                continue
            lines.append(f"- {_TIER_LABELS.get(tier, tier)}:")
            for role, grades in tier_data.get("roles", {}).items():
                lines.append(f"    [{role}] " + " | ".join(grades))
        return "\n".join(lines)
    except Exception as exc:  # missing file, bad JSON, schema drift — degrade gracefully
        logger.warning("Salary anchor file unavailable (%s); coordinate pricing disabled.", exc)
        return ""


_BLINDED_SALARY_REFERENCE = ""


def _render_insurance_tier_policy() -> str:
    """Render the same positive-membership Tier 2 policy the clamp enforces."""
    tier_2_slugs = sorted(salary_anchors.INSURANCE_TIER_2_SLUGS)
    discount_percent = round(salary_anchors.INSURANCE_TIER_2_DISCOUNT * 100)
    if tier_2_slugs:
        membership = (
            "Reviewed Tier 2 Employer slugs: " + ", ".join(tier_2_slugs) + "."
        )
    else:
        membership = "No configured insurer is currently classified as Tier 2."
    return (
        "- INSURANCE EMPLOYER TIERS. Apply the "
        f"{discount_percent}% Tier 2 discount only when the Employer is explicitly "
        "listed in the reviewed Tier 2 registry. Absence from Tier 1 is not evidence "
        f"of Tier 2. {membership} Unclassified insurers keep the standard insurance band."
    )


_INSURANCE_TIER_POLICY = _render_insurance_tier_policy()

# Salary-estimation instructions, shared by both prompts. Produced in the same
# call (no extra cost). Estimates HK market monthly pay from role/seniority/
# company tier/sector — distinct from disclosed salary_hkd_min/max.
_SALARY_INSTRUCTIONS = """\
For the salary_estimated_* fields, estimate a Hong Kong monthly BASE salary (HKD) using
this procedure, in order. This estimator has historically run about 30% TOO HIGH — when
in doubt, always bias LOW, never high.

STEP 1 — Detect ROLE TYPE from BOTH the title AND description, and set caps:
- INTERNSHIP — flag ONLY when the role is genuinely an internship / student / fresh-grad
  programme. Match WHOLE WORDS only: "intern", "interns", "internship", "summer intern",
  "summer analyst", "summer associate", "graduate intern", "graduate programme/program",
  "graduate trainee", "trainee programme/program", "industrial placement", "暑期實習",
  "實習生", "實習".
  CRITICAL: do NOT treat a role as an internship just because a word CONTAINS the letters
  "intern" — words like "Internal" (e.g. "Internal Audit"), "International", "Internet" are
  NOT internships. A "Director, Internal Audit" or "International Wealth Manager" is a
  full-time senior role, NOT an internship.
  When it IS an internship: cap at HK$3,000-12,000/month regardless of company tier;
  bulge-bracket (Goldman, JPMorgan, HSBC) may reach HK$10,000-15,000/month — never exceed
  HK$15,000/month for an internship/graduate programme.
- PART-TIME (keywords: part-time, part time, 兼職): cap at HK$8,000-20,000/month.
- CONTRACT / TEMP (keywords: contract, temporary, temp, fixed-term):
  do not discount base salary because a Role is contract. Price the same function, grade,
  and responsibilities on the same monthly base-salary range as the equivalent permanent
  Role; contract duration is an employment term, not evidence of lower market pay.
- FULL-TIME PERMANENT: no cap — use the reference table in Step 3.

STEP 2 — Scan the FULL description for an explicitly stated salary. Look for patterns like
"HK$X-Y/month", "base pay HK$X", "salary range ...", "monthly salary", "底薪", "月薪".
If found, use those EXACT figures as the estimate — they OVERRIDE the Step 1 caps and the
Step 3 reference table. (e.g. description says "HK$3,000-5,000/month" → min 3000, max 5000.)

STEP 2a — NOT every number next to a currency sign is a stated salary. Three traps:
- "UP TO" IS A CEILING, NOT A RANGE. "up to HK$30K", "月薪可高达$100,000 - $130,000",
  "最高可 $X", "as high as $X" state only an upper bound. Return salary_hkd_min = null and
  salary_hkd_max = that figure. NEVER invent a lower bound, and never treat the two numbers
  of an "up to $X - $Y" phrase as a range — the qualifier governs both.
- COMMISSION AND AGENCY EARNINGS CLAIMS ARE NOT SALARY. Insurance-agency and wealth-
  management "trainee"/"advisor" recruitment adverts advertise total achievable EARNINGS
  (commission, 花紅/花红, 獎金/奖金, 佣金, bonus-inclusive). If the figure is an earnings
  potential rather than a base salary, return null for BOTH salary_hkd fields and estimate
  from the reference table instead. A HK$100,000/month "salary" for a trainee is the
  clearest possible signal that the number is commission.
- TOTAL COMP IS NOT BASE. "TC: 1.5-1.8M", "package", "OTE", "total compensation" are
  bonus-inclusive. This board's basis is monthly BASE, so return null for both salary_hkd
  fields rather than storing a total-comp figure as if it were base pay.

STEP 2b — COORDINATE PRICING (v13). Only if NO salary was found in Step 2, try this BEFORE
writing your own band in Step 3 below. This board prices a job EXACTLY, with no dollar figures
from you at all, when it can name the (tier, role, grade) coordinate a job belongs to — the
table below then supplies the number deterministically, the same way `/fix-s` already prices
the board offline. A coordinate you name here is thrown away silently if it turns out invalid,
so Step 3 below is NOT optional — always complete it too — but a clean coordinate pick here is
cheaper and more precise than a generated band, so give it a real, careful attempt first.

This is a CLASSIFICATION task, not a pricing one: no dollar figures are shown below on purpose.
Pick the row that matches what the job DOES and what grade its title/responsibilities describe
— never let a salary figure you already have in mind steer which grade looks "right".

- Detect the FUNCTION TIER exactly as Step 3b below describes (default to the modest tier when
  unclear; front office ONLY for a title that clearly names an IB/PE/HF/AM/trading/private-
  banking-RM desk).
- Within that tier, find the SPECIFIC NAMED ROLE below whose label most closely matches this
  posting's title + description. Return it as "salary_role", exactly as printed in brackets
  (e.g. "audit_banking") — or null if nothing clearly fits.
- Within that role, find the SPECIFIC GRADE — matched from the posting's title wording, years of
  experience, scope, and who the role reports to, not from the title alone (HK titles inflate;
  a two-year analyst is often called "AVP"). Return it as "salary_grade", copied VERBATIM from
  the list below — or null if no single row is a confident, exact match. Declining is free and
  costs nothing; a wrong coordinate is silently discarded if it does not match a real row, so
  there is no reason to force a pick you are not sure of.
- If you name both a "salary_role" and "salary_grade" this way, set salary_estimated_confidence
  to "medium" (this is a confident estimate, not a disclosed figure — "high" stays reserved for
  Step 2's stated-salary case).

COORDINATE VOCABULARY — tier -> [role_key] -> grade names, NO dollar figures:
{blinded_salary_reference}

STEP 3 — Regardless of whether Step 2b succeeded, ALSO estimate a band from the REFERENCE TABLE
below — it is the figure actually used whenever the coordinate above does not resolve to a real
table cell, so treat it as required, not optional. (If Step 2b gave you a confident, exact
coordinate, this band only needs to be a reasonable, brief estimate for that same title/tier/
grade — you do not need to re-derive a full justification from scratch.) It is a weighted merge
of three 2025/2026 HK recruiter salary guides (Hays, PERSOLKELLY, Adecco), in monthly HK$ BASE,
broken down into ~95 NAMED ROLES with per-grade rows. These bands are GROUND TRUTH: your estimate
MUST fall inside the matching named role's row.

STEP 3a — Map the title to a GRADE row. Most banking roles use the corporate ladder
  Analyst (0-3y) / Associate (3-7y) / VP (7-10y) / Director (10y+) / MD (15y+):
  Analyst/Officer → Analyst ; Associate/AVP/Assistant Manager/Manager → Associate ;
  VP/SVP/Senior Manager → VP ; Director/Head of function → Director ; MD/C-suite → MD.
  Insurance roles use Officer-Senior Analyst / AsstMgr-Manager / SrMgr-SrDirector / Head.
  Some roles keep their own exact title labels — match the closest one.

STEP 3b — Detect the FUNCTION TIER from the title AND description. Most postings are NOT front
office. When the tier is unclear or the role could fit two tiers, DEFAULT to the LOWER-paying
tier (back office / operations, retail, middle office) — NEVER default to front office. Return
the tier you used as "salary_tier", using EXACTLY one of these keys: front_office,
commercial_corporate_banking, retail_banking, corporate_finance_accounting, middle_office,
insurance, back_office_operations. A role that is not a finance desk at all (e.g. facilities,
workplace/interior design, general IT, HR, admin) is NOT front office — use
back_office_operations or middle_office for it (they now contain dedicated IT / HR / admin /
customer-service / marketing role ladders — prefer those over guessing).

Within that tier, find the SPECIFIC NAMED ROLE below (e.g. "audit_banking", "treasury",
"private_banking_rm") whose title labels most closely match this posting's title + description,
and read the row for the grade from Step 3a. Return the role key you used as "salary_role"
(e.g. "audit_banking") — or null if nothing in the tier's named roles clearly fits, in which
case fall back to the closest grade row of the most similar role you can see for that tier.

CRITICAL DISAMBIGUATION — "Team Head" / "Team Lead" / "Head of" titles:
- A "Team Head"/"Team Lead" is NOT automatically the top of a ladder. Read what the team DOES.
  Head of a REVENUE-GENERATING front-office team (RM team of top private bankers, trading desk,
  IB coverage team) → the Director row of that front-office role.
  Head of a SUPPORT / SERVICE / CLIENT-RELATIONSHIP (CR/CRM) / operations / admin team — of
  which a bank has MANY — is a manager-grade position: use the Associate or VP row of the
  matching role, NOT Director. Example: "Team Head, Client Relationship Management, Private
  Bank" is client SERVICING, not a banker team head → private_banking_rm Associate/VP row
  (roughly 50k-100k), never the Director/MD rows.
- "Head of [entire function/business]" (e.g. Head of Private Banking, Head of Compliance,
  Head of IT) → Director or MD row of that role, as the reference shows.
- When you cannot tell which kind of team it is, use the LOWER interpretation.
- BUT (Morris H., 2026-08-20) a "Team Head" that is NOT a service/CR/support/operations team
  is a DIRECTOR-grade role at a bank — HK$100,000-150,000. The carve-out above is specifically
  about the service/CR variety, which a bank has many of; it is not a rule about every Team Head.
- "Division Head" is a big role, equal to the MANAGING DIRECTOR grade (HK$180,000-250,000).
- "Product Manager" / "Senior Product Manager" is a FUNCTION, not automatic Director-grade
  evidence. Only use a Director-level reading when the responsibilities clearly establish
  Director scope; ordinary mobile, digital and general product Roles should remain in the
  normal product-management range. "Assistant"/"Junior" Product Manager is not Director grade.
- Chinese banks favour "General Manager" and "Deputy GM"; both are DIRECTOR / "Head of"
  grade there (HK$100,000-150,000) and are senior roles, not middle management.

REFERENCE — monthly HK$ BASE, by function tier → named role → title level (higher tiers first;
"[role_key]" is the exact string to return as "salary_role"):
{salary_reference}

STEP 3c — Set salary_estimated_min at the LOWER part of the matched named role's row and
salary_estimated_max no higher than that row's upper figure. Do NOT exceed it, and do NOT add
a further 20-40% on top. Apply the Step-1 role-type caps FIRST — they override this table.

STEP 3d — Employer nudge WITHIN the matched band only (never above its max): Tier-1 / bulge-bracket
(Goldman, JPMorgan, Morgan Stanley, HSBC, BlackRock) → upper part of the band; Tier-2 (Standard
Chartered, DBS, Macquarie, Citi) → middle; Tier-3 / regional / virtual banks / fintech → lower part.
Digital assets / crypto are wide and volatile: 30,000-200,000 by seniority.

STEP 4 — HARD CEILINGS. Apply LAST, after Steps 1-3. These can only LOWER your estimate, never
raise it, and they override every band above:
- ABSOLUTE MAXIMUM: never estimate above HK$200,000/month for ANY role, at ANY company, at ANY
  seniority. There are no exceptions.
- BANKS — TITLE-GRADE BANDS. If the company is a bank and the title clearly names one of these
  management grades, use the BAND as your whole answer (both endpoints), not merely as a cap.
  At a bank the title IS the pay grade; it outranks whatever the tier/role tables suggested.
  Hierarchy, highest to lowest, with the band for each:
    Global Head:                                      HK$200,000-300,000
    Regional Head / Managing Director:                HK$180,000-250,000
    Executive Director / Head of:                     HK$130,000-180,000
    Director / Head of / Team Head:                   HK$100,000-150,000
    Section Head:                                     HK$80,000-150,000
    Senior Vice President (= senior manager / associate director):  HK$80,000-100,000
    Vice President (= Manager / Senior Manager):      HK$60,000-80,000
    Assistant Vice President (= Manager):             HK$50,000-70,000
    Senior Associate:                                 HK$45,000-60,000
  A bare "Manager" is ambiguous between the VP and AVP bands — use the AVP band. A bare
  "Associate" (not "Senior Associate") is likewise ambiguous — many non-banking titles use
  "Associate" too ("Research Associate", "Client Associate") — fall back to the tier/role
  tables in that case rather than forcing a grade-word match.
  These two grades are the ONLY place you may exceed the HK$200,000 absolute maximum, and only
  at a bank on a clear title match: Managing Director and Global Head.
- INSURANCE COMPANIES — TITLE-GRADE BANDS, and note the hierarchy is INVERTED relative to banks:
  at insurers Vice President and Assistant Vice President are the TOP grades, not mid-level ones.
  Highest to lowest:
    Vice President:                                   (no band specified — do not guess; fall
                                                       back to the tier/role tables)
    Assistant Vice President / Head of:               HK$150,000-200,000
    Senior Director / Director / Head of:             HK$120,000-150,000
    Associate Director:                               HK$80,000-120,000
    Principal / Senior Manager:                       HK$65,000-80,000
    Manager:                                          HK$50,000-60,000
    Assistant Manager:                                HK$35,000-45,000
  Reviewed size exception: at a Prudential-sized insurer, Senior Manager and Senior Group
  Manager are both HK$55,000-80,000. This applies to the reviewed group/functional titles,
  including IFRS, agency performance and partnership distribution.
  Compound-title exception: when a title combines competing labels such as Senior Consultant,
  Manager and Associate Director, keep the range broad at HK$55,000-80,000 rather than letting
  the highest-sounding token dictate the estimate.
  Big Four grade calibration: at EY, KPMG, Deloitte and PwC, Manager is HK$50,000-60,000,
  Associate Director is HK$85,000-120,000, and Forensics + Senior roles are HK$40,000-55,000.
  Associate Director wins when both labels appear; explicit Director/Partner/Head/VP titles
  also retain their higher grade rather than using the functional forensics band.
  Deloitte-specific calibration: ordinary Manager roles remain HK$50,000-60,000, Manager in
  M&A is HK$50,000-90,000, and Senior Consultant is HK$40,000-55,000. Explicit higher grades
  retain their higher band.
  JPMorgan calibration: Vice President at JPMorgan is HK$85,000-120,000 in Hong Kong, including
  Wealth Management Solutions. Do not use the generic HK$150,000+ estimate for this grade.
  HSBC-scale bank calibration: Lead Product Owner, Lead Product Manager and equivalent product-
  lead titles at HSBC-scale banks are HK$75,000-100,000. This does not apply to ordinary Product
  Manager titles. At DBS-scale comparable banks, Cash Product Manager and Relationship Manager are
  HK$35,000-50,000, while Senior Product Manager is HK$80,000-110,000; these narrower title
  bands override the broader lead-product band when matched.
  Spread Products Banker at VP level at Citi and comparable HSBC-scale banks is HK$100,000-125,000.
  JPMorgan remains on its separate HK$85,000-120,000 VP calibration.
  Market-infrastructure calibration: at HKEX and comparable exchange/clearing firms, Vice
  President is HK$80,000-120,000 and Assistant Vice President is HK$50,000-90,000.
  ICBC-scale bank calibration: senior Digital/Solutions/Application/Technology Product Manager
  roles at ICBC-comparable Chinese banks are HK$70,000-85,000. This is a senior functional band,
  not the generic Product Manager = Director rule; CMB Wing Lung remains separately calibrated.
  At the same banks, Global Markets Sales and Global Markets Senior Sales are HK$45,000-55,000,
  while Investment Consultant is HK$57,000-70,000.
  FWD-sized insurer calibration: Director is HK$80,000-110,000, Underwriter is HK$70,000-100,000,
  and Assistant Vice President is HK$90,000-150,000. Sun Life and Prudential use their own reviewed
  insurer-size bands.
  Deutsche Bank mixed-grade calibration: titles combining Director and VP use HK$70,000-120,000.
  Standalone Director and VP titles are not changed by this exception.
{insurance_tier_policy}
- SMALLER / MEDIUM EMPLOYERS. The bands above assume a listed multinational bank or insurer.
  For a smaller or mid-sized firm, apply a 30% discount to both endpoints.
- CMB WING LUNG — REVIEWED SMALLER-BANK CALIBRATION. CMB Wing Lung Bank Limited is a
  smaller bank even though its Listings arrive through a mainstream source. For all other
  estimated bands apply a 20% discount and round endpoints to normal HK$5,000 band steps.
  Two function/grade bands have been reviewed directly and OVERRIDE the generic bank rules:
    Product Manager and Team Lead: HK$45,000-60,000
    AVP and unambiguous Manager grade: HK$40,000-55,000
  "Product Manager" here is a function, not automatic Director-grade evidence. An explicit
  corporate grade in the same title still outranks the function.
- FRONT OFFICE IS EXEMPT from all of the title-grade bands above. A trading, investment-banking,
  private-equity, hedge-fund, asset-management or private-banking-RM desk runs its own, much
  higher ladder: a markets Vice President is not an operations Vice President. Use the
  front_office tables for those and ignore this section.

salary_estimated_max: the upper bound of a stated range if found in Step 2, otherwise AT MOST the
matched band's upper figure after Step 4's caps — never above it. These are BASE SALARY only (in
HK finance total comp is ~1.5-3x base at senior levels) — do NOT estimate total comp. Return null
for all three fields if truly unable to estimate.

Step 6. HUMAN CORRECTIONS. If a "HUMAN CORRECTIONS" block appears below, our team has already
reviewed roles of this shape and replaced the estimate with the figure shown. Those figures
OUTRANK the anchor tables above: where a correction covers a role like this one, price this role
consistently with it, even if Steps 3-5 would have landed elsewhere. The block is often absent,
which simply means nobody has corrected a role like this yet — proceed with Steps 1-5.

salary_estimated_confidence:
- "high"   = salary explicitly stated in the description (exact figures found in Step 2)
- "medium" = not stated, but function tier + seniority + company are clear
- "low"    = not stated, and function tier or seniority is ambiguous (when low, bias to the
             BOTTOM of the band)

CLASSIFICATION-FIRST OVERRIDE (v14): the per-job ANCHOR CANDIDATES block after the
posting is authoritative. Choose salary_tier, salary_role and salary_grade ONLY from
that short list; do not invent a coordinate and do not select from the broad reference
catalogue above. The runtime, not you, supplies the estimated salary endpoints from a
valid coordinate. Therefore, whenever no explicit salary is disclosed, return null for
salary_estimated_min and salary_estimated_max. If no candidate is clearly correct,
return null for all three coordinate fields and leave the estimate null. A safe review
fallback is better than a plausible but untraceable number.""".replace(
    "{blinded_salary_reference}", _BLINDED_SALARY_REFERENCE
).replace("{salary_reference}", _SALARY_REFERENCE).replace(
    "{insurance_tier_policy}", _INSURANCE_TIER_POLICY
)

# v14's execution policy.  The preceding v13 text is retained temporarily as
# migration history; this smaller policy is what reaches the model. Salary
# bands, employer exceptions and caps live only in the typed anchors/clamp that
# actually prices a listing, never in a second prose copy that can drift.
_SALARY_INSTRUCTIONS = """\
SALARY CLASSIFICATION (v14)

The board estimates Hong Kong monthly BASE salary. Do not infer or return an
AI salary amount: salary_estimated_min and salary_estimated_max must be null
unless an explicit base-salary range is disclosed in the posting. The runtime
derives any estimate deterministically from your selected coordinate.

1. Extract a disclosed monthly BASE salary into salary_hkd_min/max only when it
is genuinely base pay. Never treat commission, bonus, OTE, package/total
compensation, or an "up to" earnings claim as base salary. For an upper-bound-
only disclosure, set salary_hkd_min to null and salary_hkd_max to the stated cap.
2. Read the posting and the ANCHOR CANDIDATES block after it. Select exactly one
salary_tier / salary_role / salary_grade combination from that block only when
the function and grade clearly fit responsibilities, scope and experience.
Return the grade spelling exactly as shown. Do not invent a coordinate.
3. If the role is ambiguous, has no suitable candidate, or offers a menu of
possible grades, return null for salary_tier, salary_role, salary_grade,
salary_estimated_min and salary_estimated_max. This is a review fallback, not a
reason to guess. Keep salary_estimated_confidence low or null.
4. If a coordinate is selected and no salary is disclosed, leave both
salary_estimated_* endpoints null and use medium confidence. The deterministic
pricing layer owns every endpoint, employer cohort adjustment and cap.
5. Contract status does not lower base pay. Intern/trainee, part-time and all
title-grade exceptions are enforced by the deterministic runtime after the
coordinate is selected.
"""


# The version this enricher stamps on every row it writes.
#
# It used to be a hand-edited string, with a comment asking whoever changed the
# model, the prompt, OR the clamp in hk_jobs.salary_clamp to remember to bump it
# — a rule spanning three modules and enforced by nobody. It failed exactly as
# you would expect: the 2026-07-21 boutique-discount and single-value-range
# fixes silently skipped ~200 already-"fresh"-marked rows until a one-off manual
# patch caught them.
#
# Derived from the model, prompt text, every shared anchor rule and the clamp's
# executable behaviour, so a change to any of them creates an explicit replay
# decision. hk_jobs.salary.MANUAL_TAG remains for an external change none of
# those can see.
PROMPT_VERSION = salary.version(_MODEL, _SALARY_INSTRUCTIONS)

# Translation instructions. Many boutique/"Exclusive" HK postings are written in
# Traditional Chinese (Cantonese) or Mandarin, sometimes mixed with English. Every
# text field the model RETURNS must be in English; the ORIGINAL title/description
# stored in the DB are never touched.
_TRANSLATION_INSTRUCTIONS = """\
LANGUAGE — read carefully. The title and description may be in Traditional Chinese
(Cantonese), Simplified Chinese (Mandarin), or a mix of Chinese and English.
- "title_en": an accurate, natural English version of the job TITLE.
  * If the title is already entirely in English, copy it VERBATIM — do not paraphrase,
    reword, expand, or "improve" it.
  * If it contains ANY Chinese, translate the whole title faithfully into idiomatic
    English (e.g. "財富管理客戶經理" → "Wealth Management Relationship Manager",
    "高級核數師" → "Senior Auditor"). Translate the meaning, do not transliterate.
  * Keep well-known company names, product names, and industry acronyms (AML, CFA, VP,
    HKMA, SFC) as-is. Do not add a location or seniority that is not in the original.
- Every OTHER text value you return (skills, description_summary) must ALSO be in
  English, translated from the Chinese where necessary."""

# Description-summary instructions. Produced in the SAME call as everything else
# (no extra API pass). Kept deliberately short so it fits ~3 lines on a job card.
# v4: also acts as a light "review" pass — the summary must be clean English even
# when the source description is Chinese, mixed-language, or garbled.
_SUMMARY_INSTRUCTIONS = """\
For "description_summary": write a condensed summary of the job description in plain,
natural ENGLISH prose — translating from Chinese where the description is not in English.
STRICT rules:
- Maximum 3 sentences AND no more than about 50 words total. Keep it short enough for ~3 card lines.
- Plain prose only: no bullet points, no markdown, no line breaks, no headings.
- Factual and neutral: summarise the actual role and key responsibilities. Do NOT add hype,
  adjectives of praise, opinions, or any detail not present in the description.
- REVIEW the source text: if it is partly garbled, has broken encoding, or mixes languages,
  summarise only the parts you can read clearly and confidently — never copy garbled fragments,
  raw HTML, or untranslated Chinese into the summary.
- If the description is empty, missing, or nothing in it is legible, return an empty string ""
  — never invent, guess, or hallucinate a summary."""

# Prompt layout note (v10): ALL static content (schema, rules, the big reference table)
# comes FIRST and is byte-identical across every call; the variable job data (company/
# title/description) comes LAST. DeepSeek automatically caches identical prompt prefixes
# and bills cache-hits at ~1/10th the input rate, so the large reference block costs
# almost nothing marginal across a run. Do not reorder — putting job data first (the old
# layout) silently disables the prefix cache and multiplies input cost.
_PROMPT_WITH_DESC = """\
You extract structured data from Hong Kong job postings at financial firms. The posting
appears at the END of this prompt. Return ONLY valid JSON, no markdown, in exactly this shape:
{{
  "title_en": "<English job title, see LANGUAGE rules below>",
  "seniority": "junior|mid|senior|lead",
  "years_experience": <integer or null>,
  "skills": ["skill1", "skill2", ...],
  "remote_type": "on-site|hybrid|remote",
  "salary_hkd_min": <integer or null>,
  "salary_hkd_max": <integer or null>,
  "job_category": "Engineering|Finance|Operations|Sales|HR|Other",
  "salary_estimated_min": <integer or null>,
  "salary_estimated_max": <integer or null>,
  "salary_estimated_confidence": "low|medium|high" or null,
  "salary_tier": "front_office|commercial_corporate_banking|retail_banking|corporate_finance_accounting|middle_office|insurance|back_office_operations",
  "salary_role": "<role_key from the matched named role in the reference table, or null>",
  "salary_grade": "<exact grade name from the coordinate vocabulary in Step 2b, or null>",
  "description_summary": "<short neutral English summary, see rules below>"
}}

{translation_instructions}

For "skills": extract 7-10 specific skills from the description. Cover all categories present:
- Technical/domain: AML, derivatives, IFRS, credit analysis, actuarial, treasury, FX, fixed income
- Software/tools: Bloomberg, Aladdin, SAP, Murex, Calypso, Excel, Python, SQL, Power BI
- Certifications: CFA, CPA, ACCA, FRM, HKSI, SFC licence, MPF
- Methodologies: Agile, SWIFT, Basel III, FATCA, MiFID, Solvency II
- Management: team leadership, stakeholder management, project management
List each as a short phrase. Do NOT pad with vague generics (e.g. "strong communication") unless explicitly required by the job.

{salary_instructions}

{summary_instructions}

======== THE JOB POSTING TO EXTRACT ========
Company: {company}
Title: {title}
Description:
{description}

======== ANCHOR CANDIDATES (classification only) ========
{salary_context}"""

_PROMPT_TITLE_ONLY = """\
You extract structured data from Hong Kong job postings at financial firms. The posting
appears at the END of this prompt (title only — no description was available). Return ONLY
valid JSON, no markdown, in exactly this shape:
{{
  "title_en": "<English job title, see LANGUAGE rules below>",
  "seniority": "junior|mid|senior|lead",
  "years_experience": <integer or null>,
  "skills": ["skill1", "skill2", ...],
  "remote_type": "on-site|hybrid|remote",
  "salary_hkd_min": <integer or null>,
  "salary_hkd_max": <integer or null>,
  "job_category": "Engineering|Finance|Operations|Sales|HR|Other",
  "salary_estimated_min": <integer or null>,
  "salary_estimated_max": <integer or null>,
  "salary_estimated_confidence": "low|medium|high" or null,
  "salary_tier": "front_office|commercial_corporate_banking|retail_banking|corporate_finance_accounting|middle_office|insurance|back_office_operations",
  "salary_role": "<role_key from the matched named role in the reference table, or null>",
  "salary_grade": "<exact grade name from the coordinate vocabulary in Step 2b, or null>",
  "description_summary": ""
}}

{translation_instructions}

For "skills": infer 3-5 skills from the title — domain expertise, likely tools or certifications.

Set "description_summary" to an empty string "" — no job description was provided, so do not
write or invent one.

{salary_instructions}

======== THE JOB POSTING TO EXTRACT ========
Company: {company}
Title: {title}

======== ANCHOR CANDIDATES (classification only) ========
{salary_context}"""


class DeepSeekEnricher:
    def __init__(
        self,
        api_key: str | None = None,
        run_budget: "RunBudget | None" = None,
        salary_corrections: "list[Correction] | None" = None,
    ) -> None:
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY", "")
        if not self.api_key:
            raise ValueError(
                "DeepSeek API key not set. Export DEEPSEEK_API_KEY=<key> first."
            )
        self.usage_totals: dict[str, int] = {
            "calls": 0,
            "cache_hit": 0,
            "cache_miss": 0,
            "completion": 0,
        }
        # A hard per-run spend cap. `DEEPSEEK_DAILY_ENRICH_LIMIT` bounds how many
        # Roles a run touches, which is only a proxy for cost — and with thinking
        # on it is a proxy that understates by ~100x. See hk_jobs/ai_budget.py.
        self.run_budget = run_budget or RunBudget.from_environment()
        # Loaded ONCE per run by the caller and held here, not re-queried per
        # job: 6,000 enrichments would otherwise be 6,000 reads of a table whose
        # contents cannot change while the run is in flight. Empty by default, so
        # a caller that knows nothing about corrections (a test, enrich_single
        # from a REPL) behaves exactly as before.
        self.salary_corrections = list(salary_corrections or ())
        self._usage_lock = threading.Lock()

    def close(self) -> None:
        pass

    def __enter__(self) -> "DeepSeekEnricher":
        return self

    def __exit__(self, *_: object) -> None:
        pass

    # ── public API ────────────────────────────────────────────────────────────

    def enrich_batch(
        self,
        jobs: list[tuple[str, str, str, str]],  # (source, source_id, title, description_clean)
    ) -> dict[tuple[str, str], dict[str, Any] | None]:
        """
        Enrich jobs sequentially. Callers wrap this in ThreadPoolExecutor for parallelism.
        description_clean should be plain text (HTML already stripped).
        """
        results: dict[tuple[str, str], dict[str, Any] | None] = {}
        for source, source_id, title, description in jobs:
            key = (source, source_id)
            if self.run_budget.exhausted:
                # Stop cleanly and keep what was already bought. Everything not
                # reached simply stays stale and is picked up by a later run —
                # the enrichment selector is driven by prompt_version, so an
                # unenriched Role is not lost, only deferred.
                self._note_budget_stop()
                logger.error(
                    "BUDGET STOP — $%.2f of $%.2f spent over %d calls. %d Roles "
                    "left for the next run.",
                    self.run_budget.spent_usd, self.run_budget.limit_usd,
                    self.run_budget.calls, len(jobs) - len(results),
                )
                break
            result = self._enrich_with_retry(title, description=description or "")
            results[key] = result
            if result:
                logger.info(
                    "✓ %s/%s → %s  skills=%d",
                    source, source_id,
                    result.get("seniority"),
                    len(result.get("skills") or []),
                )
            else:
                logger.error("✗ %s/%s: all retries failed", source, source_id)
        return results

    def enrich_single(
        self,
        title: str,
        company: str = "",
        description: str = "",
        seniority: str | None = None,
        company_slug: str | None = None,
    ) -> dict[str, Any]:
        """Single API call. Raises on error."""
        company = company or "(unknown)"
        # Appended to the salary instructions rather than formatted into the
        # prompt template as its own slot: PROMPT_VERSION hashes
        # _SALARY_INSTRUCTIONS, and this block is per-JOB. Baking it into the
        # module-level constant would make the stored version churn with every
        # admin correction and re-bill the back catalogue each time — the exact
        # failure hk_jobs/salary_corrections.py's docstring exists to avoid.
        # `evidence_for` returns "" when nothing is relevant, so the common case
        # is a prompt byte-identical to the one this built before.
        salary_instructions = _SALARY_INSTRUCTIONS + salary_corrections.evidence_for(
            self.salary_corrections, title=title, seniority=seniority,
        )
        salary_context = build_salary_context(
            title=title,
            description=description,
            company_slug=company_slug,
        ).render()
        if description.strip():
            desc_text = description.strip()[:_DESC_MAX_CHARS]
            prompt = _PROMPT_WITH_DESC.format(
                company=company, title=title, description=desc_text,
                translation_instructions=_TRANSLATION_INSTRUCTIONS,
                salary_instructions=salary_instructions,
                summary_instructions=_SUMMARY_INSTRUCTIONS,
                salary_context=salary_context,
            )
            max_tokens = MAX_TOKENS_WITH_DESCRIPTION
        else:
            prompt = _PROMPT_TITLE_ONLY.format(
                company=company, title=title,
                translation_instructions=_TRANSLATION_INSTRUCTIONS,
                salary_instructions=salary_instructions,
                salary_context=salary_context,
            )
            max_tokens = MAX_TOKENS_TITLE_ONLY

        # Refuse BEFORE spending, not after. A guard that only reports is a
        # receipt, not a cap.
        self.run_budget.check()

        with httpx.Client(timeout=120.0) as client:
            resp = client.post(
                _API_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": _MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    # v12: thinking back on. It was removed in v11 to stop paying for
                    # reasoning traces, which was the right cost diagnosis and the wrong
                    # cure — the v9 A/B test showed thinking picks tiers and roles
                    # measurably better, and tier/role selection is what decides which
                    # of the 471 anchor cells prices the job.
                    "thinking": {"type": "enabled"},
                    # reasoning_effort is deliberately OMITTED so it stays at the
                    # default. "max" was tried in v9.2 and burned the whole DeepSeek
                    # balance in ~9 minutes for no proven quality gain; the A/B test
                    # that justified thinking ran at default effort, so default is the
                    # validated setting, not a compromise.
                    #
                    # temperature/top_p are NOT sent: DeepSeek silently ignores them
                    # under thinking mode, and sending them implies a control we do not
                    # have. Both are pinned by tests/test_deepseek_request.py.
                },
            )

        if resp.status_code != 200:
            raise RuntimeError(f"API {resp.status_code}: {resp.text[:120]}")

        payload = resp.json()
        from hk_jobs.ai_usage import add_usage

        with self._usage_lock:
            add_usage(self.usage_totals, payload)
        usage = payload.get("usage") or {}
        self.run_budget.record(
            cache_hit=int(usage.get("prompt_cache_hit_tokens") or 0),
            cache_miss=int(usage.get("prompt_cache_miss_tokens") or 0),
            completion=int(usage.get("completion_tokens") or 0),
        )
        choice = payload["choices"][0]
        message = choice["message"]
        # Thinking mode returns this alongside `content`. Never persisted, but logged at
        # DEBUG so a mis-tiered job's reasoning can be read back afterwards.
        reasoning = message.get("reasoning_content")
        if reasoning:
            logger.debug("Reasoning for %r: %s", title[:60], reasoning[:2000])

        text = (message.get("content") or "").strip()

        # Truncation is checked BEFORE parsing, and is its own error. Two distinct
        # symptoms, one cause — the output budget ran out:
        #   * finish_reason "length" with a partial answer (what v11 produced), and
        #   * empty content, which is what happens when the reasoning trace alone
        #     consumes the whole budget (see the v9 changelog).
        # Parsing first turns both into a generic JSONDecodeError, which is precisely
        # how a two-day outage passed for ordinary flakiness.
        finish_reason = choice.get("finish_reason")
        if finish_reason == "length" or not text:
            self._note_truncation()
            raise TruncatedAnswer(
                f"answer truncated at max_tokens={max_tokens} "
                f"(finish_reason={finish_reason!r}, content={len(text)} chars). "
                "The output budget is too small for a reasoning trace plus the answer — "
                "see MAX_TOKENS_WITH_DESCRIPTION / MAX_TOKENS_TITLE_ONLY."
            )

        text = text.replace("```json", "").replace("```", "").strip()
        return json.loads(text)

    def _note_budget_stop(self) -> None:
        with self._usage_lock:
            self.usage_totals["budget_stopped"] = 1
            self.usage_totals["budget_spent_cents"] = int(
                round(self.run_budget.spent_usd * 100)
            )

    def _note_truncation(self) -> None:
        """Count truncations into the usage totals.

        `ai_usage.record()` reads its columns by name, so an extra key rides along
        harmlessly — but it means a run can finally SEE this. Nothing counted it
        before, which is why 906 truncated calls looked like a normal night.
        """
        with self._usage_lock:
            self.usage_totals["truncated"] = self.usage_totals.get("truncated", 0) + 1

    # ── helpers ───────────────────────────────────────────────────────────────

    def _enrich_with_retry(
        self, title: str, company: str = "", description: str = "", max_retries: int = 3,
        seniority: str | None = None,
        company_slug: str | None = None,
    ) -> dict[str, Any] | None:
        for attempt in range(max_retries):
            try:
                return self.enrich_single(
                    title, company, description, seniority=seniority, company_slug=company_slug,
                )
            except TruncatedAnswer as exc:
                # Not retried. A budget that is too small is deterministic: the next
                # two attempts fail identically and simply triple the bill, which is
                # exactly what happened on 2026-08-19 (906 calls for 302 roles, all
                # truncated, nothing written). Loud and once.
                logger.error(
                    "TRUNCATED %r — %s. Not retrying; raise the budget instead.",
                    title[:50], exc,
                )
                return None
            except Exception as exc:
                if attempt < max_retries - 1:
                    wait = 2 ** attempt
                    logger.warning(
                        "Attempt %d/%d failed for %r — retrying in %ds: %s",
                        attempt + 1, max_retries, title[:50], wait, exc,
                    )
                    time.sleep(wait)
                else:
                    logger.error(
                        "All %d retries failed for %r: %s", max_retries, title[:50], exc
                    )
        return None
