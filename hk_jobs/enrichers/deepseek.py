"""
DeepSeek LLM enricher.

Sends job title + description to DeepSeek's chat API and parses structured
fields (seniority, skills, remote_type, salary, category) from the response.

API key: set the DEEPSEEK_API_KEY environment variable.
Model: deepseek-chat via https://api.deepseek.com/chat/completions
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
_REQUEST_DELAY = 0.5  # seconds between calls — polite to the API

_PROMPT_TEMPLATE = """\
Extract structured data from this Hong Kong job posting. \
Return ONLY valid JSON with no markdown fences or extra text.

Title: {title}
Description: {description}

Return exactly this JSON shape:
{{
  "seniority": "junior|mid|senior|lead",
  "years_experience": <integer or null>,
  "skills": ["skill1", "skill2"],
  "remote_type": "on-site|hybrid|remote",
  "salary_hkd_min": <integer or null>,
  "salary_hkd_max": <integer or null>,
  "job_category": "Engineering|Finance|Operations|Sales|HR|Other"
}}"""


class DeepSeekEnricher:
    """
    Calls the DeepSeek chat API to extract structured fields from a job posting.

    Reads the API key from the DEEPSEEK_API_KEY environment variable.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        if not self.api_key:
            raise ValueError(
                "DeepSeek API key not set. "
                "Export DEEPSEEK_API_KEY=<your-key> before running enrichment."
            )
        self._client = httpx.Client(timeout=30)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "DeepSeekEnricher":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ── public API ────────────────────────────────────────────────────────────

    def enrich_batch(
        self,
        jobs: list[tuple[str, str, str, str]],
    ) -> dict[tuple[str, str], dict[str, Any] | None]:
        """
        Enrich a batch of jobs.

        Args:
            jobs: list of (source, source_id, title, description)

        Returns:
            dict keyed by (source, source_id) → enrichment dict | None on failure
        """
        results: dict[tuple[str, str], dict[str, Any] | None] = {}
        for source, source_id, title, description in jobs:
            key = (source, source_id)
            try:
                enrichment = self.enrich_single(title, description or "")
                results[key] = enrichment
                logger.info("✓ %s/%s → seniority=%s", source, source_id, enrichment.get("seniority"))
            except Exception as exc:
                logger.error("✗ %s/%s: %s", source, source_id, exc)
                results[key] = None
            time.sleep(_REQUEST_DELAY)
        return results

    def enrich_single(self, title: str, description: str) -> dict[str, Any]:
        """
        Call the DeepSeek API for one job and return parsed JSON.
        Raises on non-200 response or JSON parse failure.
        """
        prompt = _PROMPT_TEMPLATE.format(
            title=title,
            description=description[:2000] if description else "(no description — infer from title)",
        )

        resp = self._client.post(
            _API_URL,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": _MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 500,
            },
        )

        if resp.status_code != 200:
            raise RuntimeError(f"DeepSeek API {resp.status_code}: {resp.text[:200]}")

        text = resp.json()["choices"][0]["message"]["content"].strip()

        # Strip markdown fences if the model wraps output despite instructions
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]

        return json.loads(text.strip())
