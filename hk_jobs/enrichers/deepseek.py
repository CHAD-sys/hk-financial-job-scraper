"""
DeepSeek LLM enricher — optimized for speed.

Changes vs v1:
  - Title-only prompt (shorter → faster inference, ~1 s/call vs ~2 s)
  - max_tokens 500 → 250 (enough for the JSON schema)
  - temperature 0.3 → 0.2 (more deterministic JSON output)
  - timeout 30 s → 60 s (headroom for occasional slow responses)
  - Exponential-backoff retry (3 attempts: 0 s, 1 s, 2 s back-off)
  - No per-call sleep — callers use ThreadPoolExecutor instead

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

_PROMPT = """\
Job title: {title}

Return ONLY this JSON, no markdown:
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
    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY", "")
        if not self.api_key:
            raise ValueError(
                "DeepSeek API key not set. Export DEEPSEEK_API_KEY=<key> first."
            )

    def close(self) -> None:
        pass  # stateless — httpx clients are created per-call for thread safety

    def __enter__(self) -> "DeepSeekEnricher":
        return self

    def __exit__(self, *_: object) -> None:
        pass

    # ── public API ────────────────────────────────────────────────────────────

    def enrich_batch(
        self,
        jobs: list[tuple[str, str, str, str]],  # (source, source_id, title, description)
    ) -> dict[tuple[str, str], dict[str, Any] | None]:
        """
        Enrich jobs sequentially. Callers should wrap this in a ThreadPoolExecutor
        if they want parallel execution across batches.
        """
        results: dict[tuple[str, str], dict[str, Any] | None] = {}
        for source, source_id, title, _description in jobs:
            key = (source, source_id)
            result = self._enrich_with_retry(title)
            results[key] = result
            if result:
                logger.info("✓ %s/%s → %s", source, source_id, result.get("seniority"))
            else:
                logger.error("✗ %s/%s: all retries failed", source, source_id)
        return results

    def enrich_single(self, title: str) -> dict[str, Any]:
        """Single API call. Raises on error."""
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                _API_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": _MODEL,
                    "messages": [{"role": "user", "content": _PROMPT.format(title=title)}],
                    "temperature": 0.2,
                    "max_tokens": 250,
                    "top_p": 0.9,
                },
            )

        if resp.status_code != 200:
            raise RuntimeError(f"API {resp.status_code}: {resp.text[:120]}")

        text = resp.json()["choices"][0]["message"]["content"].strip()
        # Strip markdown fences if model ignores instructions
        text = text.replace("```json", "").replace("```", "").strip()
        return json.loads(text)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _enrich_with_retry(
        self, title: str, max_retries: int = 3
    ) -> dict[str, Any] | None:
        for attempt in range(max_retries):
            try:
                return self.enrich_single(title)
            except Exception as exc:
                if attempt < max_retries - 1:
                    wait = 2 ** attempt  # 1 s, 2 s
                    logger.warning(
                        "Attempt %d/%d failed for %r — retrying in %ds: %s",
                        attempt + 1, max_retries, title[:50], wait, exc,
                    )
                    time.sleep(wait)
                else:
                    logger.error("All %d retries failed for %r: %s", max_retries, title[:50], exc)
        return None
