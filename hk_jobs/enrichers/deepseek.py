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

API key: set DEEPSEEK_API_KEY env var.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_API_URL = "https://api.deepseek.com/chat/completions"
# v4-pro + thinking was A/B tested and produced measurably better tier/role selection
# (see v9 changelog), but at ~16s/job it would take ~21h to re-enrich the full active
# set even at 20 concurrent workers. v4-flash + thinking (this module's PROMPT_VERSION
# name still says "v4pro" from the first attempt — see below) is the fast tier with the
# same reasoning-mode toggle: same cheap base rate as the old deepseek-chat, told to
# reason harder via reasoning_effort="max" and given a large max_tokens budget so the
# reasoning trace never gets cut off before the final answer.
_MODEL = "deepseek-v4-flash"
_DESC_MAX_CHARS = 2_000   # cap to keep prompt tight; descriptions are typically 1–4 KB

# Bump whenever the model, the salary prompt, OR the deterministic clamp in
# hk_jobs.salary_clamp changes materially — not just model/prompt swaps. hk_jobs.enrichment
# stores this alongside each enrichment row and re-enriches any active job whose stored
# version doesn't match — on every regular run, not just an explicit --re-enrich — so a
# change reaches jobs that get soft-deleted and reactivated later, not just what's active
# the day the change ships. Missing this on a clamp-only change (no model/prompt edit) is
# exactly what let the 2026-07-21 boutique-discount and single-value-range fixes silently
# skip ~200 already-"fresh"-marked rows until a one-off manual patch caught them.
PROMPT_VERSION = "2026-07-21-v10-merged-3source-granular-prefix-cached"

# Salary anchor table — the single source of truth, extracted from the 2026 Hays
# Asia Salary Guide (HK) into a structured JSON. Loaded and rendered into the prompt
# ONCE at import so every call carries the calibrated bands without re-reading the file.
_ANCHORS_PATH = Path(__file__).resolve().parents[2] / "salary_guidlines" / "hk_salary_anchors.json"

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
        data = json.loads(_ANCHORS_PATH.read_text(encoding="utf-8"))
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


_SALARY_REFERENCE = _load_salary_reference()

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
- CONTRACT / TEMP (keywords: contract, temporary, temp, fixed-term): apply a 10-20%
  discount vs the equivalent permanent role.
- FULL-TIME PERMANENT: no cap — use the reference table in Step 3.

STEP 2 — Scan the FULL description for an explicitly stated salary. Look for patterns like
"HK$X-Y/month", "base pay HK$X", "salary range ...", "monthly salary", "底薪", "月薪".
If found, use those EXACT figures as the estimate — they OVERRIDE the Step 1 caps and the
Step 3 reference table. (e.g. description says "HK$3,000-5,000/month" → min 3000, max 5000.)

STEP 3 — Only if NO salary is stated in the description, estimate from the REFERENCE TABLE
below. It is a weighted merge of three 2025/2026 HK recruiter salary guides (Hays, PERSOLKELLY,
Adecco), in monthly HK$ BASE, broken down into ~95 NAMED ROLES with per-grade rows. These bands
are GROUND TRUTH: your estimate MUST fall inside the matching named role's row.

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
- BANKS — if the company is a bank and the title clearly names one of these management grades
  (hierarchy, highest to lowest: Managing Director > Executive Director > Director > Associate
  Director > Vice President > Assistant Vice President; "Manager"/"Assistant Manager" titles
  are the Assistant Vice President grade), cap at:
    Assistant Vice President / AVP / Manager: max HK$70,000
    Vice President / VP:                     max HK$80,000
    Associate Director / AD:                 max HK$110,000
    Director:                                max HK$160,000
    Executive Director:                      max HK$200,000
    Managing Director:                       max HK$200,000
- BIG INSURANCE COMPANIES (e.g. AIA, Manulife, Prudential, AXA, Zurich, FWD, Sun Life,
  Generali, China Life, Ping An, Chubb, Allianz, Swiss Re) — if the title clearly names one of
  these grades, cap at:
    Senior Manager / Principal: max HK$80,000
    Associate Director / AD:    max HK$150,000
    Director:                   max HK$200,000
  Specifically at FWD, Sun Life, and Manulife the order is reversed at the top: Vice
  President > Assistant Vice President > Director > Associate Director > Senior Manager >
  Manager. VP/AVP roles at these three still never exceed the HK$200,000 absolute maximum.

salary_estimated_max: the upper bound of a stated range if found in Step 2, otherwise AT MOST the
matched band's upper figure after Step 4's caps — never above it. These are BASE SALARY only (in
HK finance total comp is ~1.5-3x base at senior levels) — do NOT estimate total comp. Return null
for all three fields if truly unable to estimate.

salary_estimated_confidence:
- "high"   = salary explicitly stated in the description (exact figures found in Step 2)
- "medium" = not stated, but function tier + seniority + company are clear
- "low"    = not stated, and function tier or seniority is ambiguous (when low, bias to the
             BOTTOM of the band)""".replace("{salary_reference}", _SALARY_REFERENCE)

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
{description}"""

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
  "description_summary": ""
}}

{translation_instructions}

For "skills": infer 3-5 skills from the title — domain expertise, likely tools or certifications.

Set "description_summary" to an empty string "" — no job description was provided, so do not
write or invent one.

{salary_instructions}

======== THE JOB POSTING TO EXTRACT ========
Company: {company}
Title: {title}"""


class DeepSeekEnricher:
    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY", "")
        if not self.api_key:
            raise ValueError(
                "DeepSeek API key not set. Export DEEPSEEK_API_KEY=<key> first."
            )

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

    def enrich_single(self, title: str, company: str = "", description: str = "") -> dict[str, Any]:
        """Single API call. Raises on error."""
        company = company or "(unknown)"
        if description.strip():
            desc_text = description.strip()[:_DESC_MAX_CHARS]
            prompt = _PROMPT_WITH_DESC.format(
                company=company, title=title, description=desc_text,
                translation_instructions=_TRANSLATION_INSTRUCTIONS,
                salary_instructions=_SALARY_INSTRUCTIONS,
                summary_instructions=_SUMMARY_INSTRUCTIONS,
            )
            # Thinking mode's reasoning trace is billed as output and must complete
            # before the model writes the final JSON — a small budget here truncates
            # the reasoning and leaves `content` empty (see v9 changelog).
            max_tokens = 12_000
        else:
            prompt = _PROMPT_TITLE_ONLY.format(
                company=company, title=title,
                translation_instructions=_TRANSLATION_INSTRUCTIONS,
                salary_instructions=_SALARY_INSTRUCTIONS,
            )
            max_tokens = 12_000

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
                    "thinking": {"type": "enabled"},
                    # reasoning_effort intentionally omitted (defaults to "high") — "max"
                    # burned through the DeepSeek balance in ~9 minutes for no proven
                    # quality gain over default; the A/B test that actually validated
                    # thinking mode's tier/role improvements used default effort, not max.
                    # temperature/top_p are unsupported under thinking mode (silently
                    # ignored per DeepSeek's docs) — omitted for clarity, not because
                    # they'd error.
                },
            )

        if resp.status_code != 200:
            raise RuntimeError(f"API {resp.status_code}: {resp.text[:120]}")

        message = resp.json()["choices"][0]["message"]
        # Thinking mode adds this alongside `content` — not persisted to the DB, but
        # logged at DEBUG so a mis-tiered job's reasoning can be inspected after the fact
        # (set logging to DEBUG for hk_jobs.enrichers.deepseek to see it).
        reasoning = message.get("reasoning_content")
        if reasoning:
            logger.debug("Reasoning for %r: %s", title[:60], reasoning[:2000])

        text = message["content"].strip()
        text = text.replace("```json", "").replace("```", "").strip()
        return json.loads(text)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _enrich_with_retry(
        self, title: str, company: str = "", description: str = "", max_retries: int = 3
    ) -> dict[str, Any] | None:
        for attempt in range(max_retries):
            try:
                return self.enrich_single(title, company, description)
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
