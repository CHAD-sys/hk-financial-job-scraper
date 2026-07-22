"""
LP-3 two-stage extractor: is this LinkedIn post a genuine job mandate, and if
so, what are its fields?

The LP-0 bake-off found keyword matching alone overstates precision (~65-70%
manual-read vs 100% keyword-match on discovery search results — see
docs/BAKEOFF_RESULTS.md) — this is why a classifier is necessary, not
optional. Implemented as ONE combined DeepSeek call per post rather than two
separate API calls: the model returns `is_job_post` first, and every other
field is null when it's false. This halves the per-post DeepSeek spend
versus a literal two-call pipeline while still performing the two logical
stages the plan calls for (classify, then extract).

Does NOT reuse hk_jobs/llm_client.py's `LLMClient` — that client's `chat()`
has no `response_format`/system-message support, and hk_jobs/tech_filter.py
already establishes the precedent of rolling a direct httpx call for
JSON-mode classification in this codebase (tech_filter.py:79-108). Same
precedent followed here: system+user split, `response_format:
{"type":"json_object"}`, direct httpx POST.

⚠  Model: `deepseek-chat`/`deepseek-reasoner` are scheduled for retirement
   2026-07-24 (see hk_jobs/enrichers/deepseek.py's changelog). This module
   deliberately uses `deepseek-v4-flash` — the model hk_jobs/enrichers/
   deepseek.py already migrated production enrichment to — rather than
   llm_client.py's stale `deepseek-chat` default.

Single mockable seam: `_call_deepseek()`. Tests monkeypatch this (same
pattern as ApifyClient._call_actor in vendor_client.py) — no real network
call in the test suite.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

_API_URL = "https://api.deepseek.com/chat/completions"
_MODEL = "deepseek-v4-flash"

# Bump whenever the prompt or model changes materially — stored per-post
# (linkedin_posts.extraction_prompt_version, phase 27) so a prompt change can
# be detected and re-run later, same self-healing pattern as
# job_enrichments.prompt_version (hk_jobs/enrichers/deepseek.py).
PROMPT_VERSION = "2026-07-22-v1-combined-classify-extract"

_SYSTEM_PROMPT = """You classify and extract job-mandate information from LinkedIn posts \
written by recruiters and headhunters in Hong Kong's financial sector.

A post is a genuine job mandate if it describes a specific, currently-open role someone \
could apply for or be referred to — not a thought-leadership article, a congratulations \
post, a personal update, or a vague "let's chat about opportunities" post with no \
identifiable role.

Return ONLY a JSON object with this exact shape (no markdown fences, no commentary):
{
  "is_job_post": true or false,
  "confidence": <float 0.0-1.0>,
  "title": "<job title>" or null,
  "employer_named": true or false,
  "employer_hint": "<the real employer name IF explicitly stated, else a short generic \
description like 'international private bank' if the post gives one, else null>",
  "location": "<location as stated>" or null,
  "hk_plausible": true or false,
  "seniority": one of "intern","junior","mid","senior","lead","executive", or null,
  "salary_min": <integer, monthly HKD> or null,
  "salary_max": <integer, monthly HKD> or null,
  "salary_currency": "<currency code as stated>" or null,
  "skills": [<short skill/keyword strings>]
}

Rules:
- If is_job_post is false, every other field except confidence must be null (skills: []).
- NEVER invent an employer name. employer_named is true ONLY if a specific company/bank/\
fund name is explicitly written in the post. A phrase like "a leading private bank" or \
"my client" is NOT a named employer — set employer_named false and put that phrase (if \
any) in employer_hint instead.
- hk_plausible is true if the post states or clearly implies Hong Kong (including \
"Greater China", "APAC" ONLY when paired with an explicit HK mention elsewhere in the \
post). A post naming only Singapore/Shanghai/Beijing with no HK mention is hk_plausible \
false.
- A post naming SEVERAL distinct mandates: extract only the FIRST/primary one. Multi-\
mandate posts are handled by a separate pass, not this call.
- confidence reflects how certain you are this is a genuine, currently-open mandate \
(not the salary/seniority extraction accuracy)."""


@dataclass
class ExtractionResult:
    is_job_post: bool
    confidence: float
    title: str | None = None
    employer_named: bool = False
    employer_hint: str | None = None
    location: str | None = None
    hk_plausible: bool = False
    seniority: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str | None = None
    skills: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


class ExtractorAuthError(RuntimeError):
    """Raised when DEEPSEEK_API_KEY is missing. Never retried."""


def extract_post(post_text: str, *, api_key: str | None = None) -> ExtractionResult | None:
    """
    Classify + extract one post. Returns None if the post is empty/whitespace,
    or if the DeepSeek call fails after retries (mirrors enrichers/deepseek.py's
    enrich_single -> _enrich_with_retry -> None convention: the caller treats
    None as "skip this post, log it, move on" rather than crashing the run).
    """
    if not post_text or not post_text.strip():
        return None

    key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        raise ExtractorAuthError(
            "DEEPSEEK_API_KEY not set. Export it or add it to config/api_keys.env."
        )

    for attempt in range(1, 3):  # same low retry cap as vendor_client.py — billable calls
        try:
            content = _call_deepseek(post_text, api_key=key)
            data = json.loads(content.replace("```json", "").replace("```", "").strip())
            return _to_result(data)
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            if code in (401, 403):
                raise ExtractorAuthError(f"DeepSeek rejected the API key (HTTP {code})") from exc
            if attempt == 2:
                logger.error("Extraction failed after retries: HTTP %d", code)
                return None
            logger.warning("Extraction attempt %d failed (HTTP %d) — retrying", attempt, code)
        except (httpx.TimeoutException, httpx.NetworkError, json.JSONDecodeError, KeyError) as exc:
            if attempt == 2:
                logger.error("Extraction failed after retries: %s", exc)
                return None
            logger.warning("Extraction attempt %d failed (%s) — retrying", attempt, exc)
    return None


def _to_result(data: dict) -> ExtractionResult:
    is_job_post = bool(data.get("is_job_post"))
    confidence = float(data.get("confidence") or 0.0)
    confidence = max(0.0, min(1.0, confidence))  # same clamp convention as longtail.py
    return ExtractionResult(
        is_job_post=is_job_post,
        confidence=confidence,
        title=data.get("title") if is_job_post else None,
        employer_named=bool(data.get("employer_named")) if is_job_post else False,
        employer_hint=data.get("employer_hint") if is_job_post else None,
        location=data.get("location") if is_job_post else None,
        hk_plausible=bool(data.get("hk_plausible")) if is_job_post else False,
        seniority=data.get("seniority") if is_job_post else None,
        salary_min=data.get("salary_min") if is_job_post else None,
        salary_max=data.get("salary_max") if is_job_post else None,
        salary_currency=data.get("salary_currency") if is_job_post else None,
        skills=list(data.get("skills") or []) if is_job_post else [],
        raw=data,
    )


def _call_deepseek(post_text: str, *, api_key: str) -> str:
    """Single mockable seam — patch this in tests to inject a canned reply."""
    resp = httpx.post(
        _API_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": _MODEL,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": post_text},
            ],
            "temperature": 0,
            "max_tokens": 800,
            "response_format": {"type": "json_object"},
        },
        timeout=90.0,
    )
    if resp.status_code in (401, 403):
        raise httpx.HTTPStatusError(
            f"DeepSeek auth error {resp.status_code}", request=resp.request, response=resp
        )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]
