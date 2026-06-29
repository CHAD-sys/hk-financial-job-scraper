"""
DeepSeek LLM enricher — v3: includes job description for richer skill extraction.

v1: title-only, 500 max_tokens
v2: title-only, 250 max_tokens, 20 concurrent workers
v3: title + description (capped 2 000 chars clean text), 350 max_tokens
    — skills coverage expected to jump from 75% → 90%+

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
For the salary_estimated_* fields: estimate a realistic Hong Kong monthly BASE salary
(HKD) for this role from title, seniority, company tier and sector. Reference benchmarks
(monthly HKD base, banking/investment-banking baseline, 2026 market):
- Junior analyst / associate: 25,000-45,000
- Mid-level / AVP: 60,000-100,000
- Senior / VP: 150,000-300,000
- Director / ED: 300,000-600,000
- MD / C-suite: 400,000-900,000
Sector adjustments vs that IB baseline (same level):
- Insurance / asset management: ~25% lower
- Big 4 / professional services: ~35% lower
- Virtual banks / fintech: ~10-20% lower
- Digital assets / crypto: wide, 30,000-200,000 by seniority
Company-tier scaling within a band:
- Tier 1 (Goldman, JPMorgan, HSBC, BlackRock, Morgan Stanley): upper 30% of band
- Tier 2 (Standard Chartered, DBS, Macquarie, Citi): mid band
- Tier 3 (smaller / regional / virtual banks): lower 30% of band
If the description signals strong pay ("competitive package", "top-tier compensation"),
adjust upward. salary_estimated_max should be 20-40% above salary_estimated_min.
These are estimated BASE SALARY ranges only. In HK finance, total compensation
(base + bonus + benefits) is typically 1.5-3x the base for senior roles. Do NOT attempt
to estimate total comp — only base.
Confidence: "high" = clear seniority + known company + standard role; "medium" = some
ambiguity; "low" = vague title / unusual role / thin context. If you genuinely cannot
estimate (no title, no seniority signal), return null for all three salary_estimated_* fields."""

_PROMPT_WITH_DESC = """\
Extract structured data from this Hong Kong job posting. Return ONLY valid JSON, no markdown.

Company: {company}
Title: {title}
Description:
{description}

Return exactly this JSON:
{{
  "seniority": "junior|mid|senior|lead",
  "years_experience": <integer or null>,
  "skills": ["skill1", "skill2", ...],
  "remote_type": "on-site|hybrid|remote",
  "salary_hkd_min": <integer or null>,
  "salary_hkd_max": <integer or null>,
  "job_category": "Engineering|Finance|Operations|Sales|HR|Other",
  "salary_estimated_min": <integer or null>,
  "salary_estimated_max": <integer or null>,
  "salary_estimated_confidence": "low|medium|high" or null
}}

For "skills": extract 7-10 specific skills from the description. Cover all categories present:
- Technical/domain: AML, derivatives, IFRS, credit analysis, actuarial, treasury, FX, fixed income
- Software/tools: Bloomberg, Aladdin, SAP, Murex, Calypso, Excel, Python, SQL, Power BI
- Certifications: CFA, CPA, ACCA, FRM, HKSI, SFC licence, MPF
- Methodologies: Agile, SWIFT, Basel III, FATCA, MiFID, Solvency II
- Management: team leadership, stakeholder management, project management
List each as a short phrase. Do NOT pad with vague generics (e.g. "strong communication") unless explicitly required by the job.

{salary_instructions}"""

_PROMPT_TITLE_ONLY = """\
Extract structured data from this Hong Kong job posting. Return ONLY valid JSON, no markdown.

Company: {company}
Title: {title}

Return exactly this JSON:
{{
  "seniority": "junior|mid|senior|lead",
  "years_experience": <integer or null>,
  "skills": ["skill1", "skill2", ...],
  "remote_type": "on-site|hybrid|remote",
  "salary_hkd_min": <integer or null>,
  "salary_hkd_max": <integer or null>,
  "job_category": "Engineering|Finance|Operations|Sales|HR|Other",
  "salary_estimated_min": <integer or null>,
  "salary_estimated_max": <integer or null>,
  "salary_estimated_confidence": "low|medium|high" or null
}}

For "skills": infer 3-5 skills from the title — domain expertise, likely tools or certifications.

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
                salary_instructions=_SALARY_INSTRUCTIONS,
            )
            max_tokens = 450   # +salary fields; headroom over ~300 actual output
        else:
            prompt = _PROMPT_TITLE_ONLY.format(
                company=company, title=title, salary_instructions=_SALARY_INSTRUCTIONS,
            )
            max_tokens = 350

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
