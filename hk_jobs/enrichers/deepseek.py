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
_MODEL = "deepseek-chat"
_DESC_MAX_CHARS = 2_000   # cap to keep prompt tight; descriptions are typically 1–4 KB

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
    return f"{_fmt_k(lo)}-{_fmt_k(hi)}" if hi else f"{_fmt_k(lo)}+"


def _load_salary_reference() -> str:
    """Render the JSON anchor ladders into a compact prompt block (high tier → low)."""
    try:
        data = json.loads(_ANCHORS_PATH.read_text(encoding="utf-8"))
        ladders = data["ladders_monthly_hkd"]
        order = data["tier_order_low_to_high"][::-1]  # display highest-paid first
        lines = []
        for tier in order:
            lvl = ladders[tier]
            lines.append(f"- {_TIER_LABELS.get(tier, tier)}:")
            lines.append(
                f"    junior {_fmt_band(lvl['junior'])} | mid {_fmt_band(lvl['mid'])} | "
                f"senior {_fmt_band(lvl['senior'])} | lead {_fmt_band(lvl['lead'])}"
            )
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
this THREE-STEP procedure, in order:

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
below. It is the 2026 Hays Asia Salary Guide (HK), converted to monthly HK$ BASE. These bands
are GROUND TRUTH: your estimate MUST fall inside the matching band. This estimator has
historically run TOO HIGH — so when in doubt, bias LOW, never high.

STEP 3a — Map the seniority field to a level:
  Analyst/Officer → junior ; Associate/AVP/Assistant Manager → mid ;
  VP/SVP/Senior Manager → senior ; Director/MD/Head/Chief/C-suite → lead.

STEP 3b — Detect the FUNCTION TIER from the title AND description, then read that tier's band
for the level from Step 3a. Most postings are NOT front office. When the tier is unclear or the
role could fit two tiers, DEFAULT to the LOWER-paying tier (back office / operations, retail,
middle office) — NEVER default to front office. Return the tier you used as "salary_tier",
using EXACTLY one of these keys: front_office, commercial_corporate_banking, retail_banking,
corporate_finance_accounting, middle_office, insurance, back_office_operations. A role that is
not a finance desk at all (e.g. facilities, workplace/interior design, general IT, HR, admin)
is NOT front office — use back_office_operations or middle_office for it.

REFERENCE — monthly HK$ BASE by function tier and level (higher-paid tiers first):
{salary_reference}

STEP 3c — Set salary_estimated_min at the LOWER part of the matched band and
salary_estimated_max no higher than that band's upper figure. Do NOT exceed the band max, and
do NOT add a further 20-40% on top. Apply the Step-1 role-type caps FIRST — they override this table.

STEP 3d — Employer nudge WITHIN the band only (never above its max): Tier-1 / bulge-bracket
(Goldman, JPMorgan, Morgan Stanley, HSBC, BlackRock) → upper part of the band; Tier-2 (Standard
Chartered, DBS, Macquarie, Citi) → middle; Tier-3 / regional / virtual banks / fintech → lower part.
Digital assets / crypto are wide and volatile: 30,000-200,000 by seniority.

salary_estimated_max: the upper bound of a stated range if found in Step 2, otherwise AT MOST the
matched band's upper figure — never above it. These are BASE SALARY only (in HK finance total comp
is ~1.5-3x base at senior levels) — do NOT estimate total comp. Return null for all three fields if
truly unable to estimate.

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

_PROMPT_WITH_DESC = """\
Extract structured data from this Hong Kong job posting. Return ONLY valid JSON, no markdown.

Company: {company}
Title: {title}
Description:
{description}

Return exactly this JSON:
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

{summary_instructions}"""

_PROMPT_TITLE_ONLY = """\
Extract structured data from this Hong Kong job posting. Return ONLY valid JSON, no markdown.

Company: {company}
Title: {title}

Return exactly this JSON:
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
  "description_summary": ""
}}

{translation_instructions}

For "skills": infer 3-5 skills from the title — domain expertise, likely tools or certifications.

Set "description_summary" to an empty string "" — no job description was provided, so do not
write or invent one.

{salary_instructions}"""


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
            max_tokens = 620   # +title_en +salary +~50-word summary; headroom over actual output
        else:
            prompt = _PROMPT_TITLE_ONLY.format(
                company=company, title=title,
                translation_instructions=_TRANSLATION_INSTRUCTIONS,
                salary_instructions=_SALARY_INSTRUCTIONS,
            )
            max_tokens = 400

        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                _API_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": _MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                    "max_tokens": max_tokens,
                    "top_p": 0.9,
                },
            )

        if resp.status_code != 200:
            raise RuntimeError(f"API {resp.status_code}: {resp.text[:120]}")

        text = resp.json()["choices"][0]["message"]["content"].strip()
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
