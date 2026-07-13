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

API key: set DEEPSEEK_API_KEY env var.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_API_URL = "https://api.deepseek.com/chat/completions"
_MODEL = "deepseek-chat"
_DESC_MAX_CHARS = 2_000   # cap to keep prompt tight; descriptions are typically 1–4 KB

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
- FULL-TIME PERMANENT: no cap — use the full market benchmarks in Step 3.

STEP 2 — Scan the FULL description for an explicitly stated salary. Look for patterns like
"HK$X-Y/month", "base pay HK$X", "salary range ...", "monthly salary", "底薪", "月薪".
If found, use those EXACT figures as the estimate — they OVERRIDE the Step 1 caps and the
Step 3 benchmarks. (e.g. description says "HK$3,000-5,000/month" → min 3000, max 5000.)

STEP 3 — Only if NO salary is stated in the description, estimate from market. Apply the
Step 1 role-type cap FIRST. These are full-time monthly BASE benchmarks for Hong Kong,
calibrated to the 2026 Hays Asia Salary Guide (HK). Do NOT overshoot them — historically
this estimator ran too high, especially at senior levels.

STEP 3a — Detect the FUNCTION TIER (this matters as much as the level; the same title
pays very differently by desk):
- FRONT OFFICE — investment banking / M&A / corporate finance, private equity, hedge
  funds, asset management (fund manager / portfolio / research / buy-side sales), global
  markets / trading, private banking relationship managers. Highest pay.
- COMMERCIAL / RETAIL BANKING — corporate / commercial / SME / FI relationship managers,
  wealth managers, branch roles. Mid pay.
- MIDDLE OFFICE — risk (credit / market / operational / enterprise), compliance, internal
  audit. Below front office at the same title.
- BACK OFFICE / OPERATIONS — treasury / trade / payment / fund / securities operations,
  KYC / documentation, loan admin, settlements. Lowest of the professional bands.
- CORPORATE FINANCE & ACCOUNTING (in-house FP&A, controller, finance manager) and BIG 4 /
  PROFESSIONAL SERVICES / INSURANCE — use the middle-office ladder.
CRITICAL: most postings are NOT front-office IB. When the tier is unclear, DEFAULT to the
DEFAULT ladder below (middle/back-office & commercial), never the front-office one.

STEP 3b — DEFAULT ladder (monthly BASE HK$) — middle/back office, commercial/retail
banking, in-house finance, insurance, professional services (the majority of jobs):
- Entry / Analyst / Officer (0-2 yrs, seniority "junior"):     18,000-35,000
- Associate / Senior Analyst (2-5 yrs, "mid"):                 30,000-55,000
- AVP / Manager (5-8 yrs, "mid"-"senior"):                     45,000-80,000
- VP / Senior Manager (8-12 yrs, "senior"):                    65,000-110,000
- SVP / Director / Department Head (12-18 yrs, "lead"):        100,000-160,000
- MD / Head / C-suite (18+ yrs, "lead"):                       150,000-300,000
Pure operational / branch / teller / admin / insurance-agent floor: 16,000-30,000 entry.

STEP 3c — FRONT-OFFICE ladder (use ONLY when Step 3a says front office). Higher:
- Analyst (seniority "junior"):        40,000-85,000
- Associate ("mid"):                   75,000-130,000
- VP ("senior"):                       120,000-170,000
- Director / ED ("lead"):              165,000-250,000
- MD / Head ("lead"):                  250,000-500,000
(Fund managers, senior traders, senior private bankers sit at the top of these bands.)

STEP 3d — Employer adjustment within the chosen band: Tier-1 / bulge-bracket (Goldman,
JPMorgan, Morgan Stanley, HSBC, BlackRock) upper third; Tier-2 (Standard Chartered, DBS,
Macquarie, Citi) middle; Tier-3 / regional / virtual banks / fintech lower third.
Digital assets / crypto are wide and volatile: 30,000-200,000 by seniority.

salary_estimated_max: same three-step logic — upper bound of a stated range if found,
else 20-40% above salary_estimated_min; respect the same role-type caps.
These are BASE SALARY only (in HK finance total comp is ~1.5-3x base for senior roles) —
do NOT estimate total comp. Return null for all three fields if truly unable to estimate.

salary_estimated_confidence:
- "high"   = salary explicitly stated in the description (exact figures found in Step 2)
- "medium" = not stated, but role type + seniority + company are clear
- "low"    = not stated, and role type is ambiguous or context is thin"""

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
