"""
Minimal DeepSeek chat wrapper (OpenAI-compatible chat/completions endpoint).

Used by the Longtail adapter for LLM-based job extraction. Kept deliberately tiny:
one POST, JSON in / text out, plus a helper that parses a JSON reply. The
enrichment pipeline has its own DeepSeek call tuned for enrichment; this is the
general-purpose client for the extraction track.

API key: set DEEPSEEK_API_KEY (see .env.example).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_API_URL = "https://api.deepseek.com/chat/completions"
_DEFAULT_MODEL = "deepseek-chat"


class LLMClient:
    """Thin DeepSeek client. `chat()` returns text; `extract_json()` parses a JSON reply."""

    def __init__(self, api_key: str | None = None, model: str = _DEFAULT_MODEL) -> None:
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY", "")
        if not self.api_key:
            raise ValueError(
                "DeepSeek API key not set. Export DEEPSEEK_API_KEY=<key> first "
                "(see .env.example)."
            )
        self.model = model

    def chat(
        self,
        prompt: str,
        *,
        max_tokens: int = 2000,
        temperature: float = 0.2,
        timeout: float = 90.0,
    ) -> str:
        """Single completion. Returns the assistant message content. Raises on HTTP error."""
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(
                _API_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
        if resp.status_code != 200:
            raise RuntimeError(f"DeepSeek API {resp.status_code}: {resp.text[:200]}")
        return resp.json()["choices"][0]["message"]["content"].strip()

    def extract_json(self, prompt: str, **kwargs: Any) -> Any:
        """Call chat() and parse the reply as JSON (tolerates ```json fences)."""
        text = self.chat(prompt, **kwargs)
        text = text.replace("```json", "").replace("```", "").strip()
        return json.loads(text)
