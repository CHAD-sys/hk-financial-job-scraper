"""
Ghost-job detection for Secret Market posts.

Why this exists: hk_jobs.storage.reconcile_cross_posted() is the existing
cross-source dedup mechanism, but it matches on company_slug — and every
Secret Market post's company_slug is `confidential-{recruiter-slug}` by
design (promote.py:_build_job), which can never equal a real employer's
slug. So a Secret Market post that happens to be the SAME real vacancy as
one already listed on the mainstream/boutique board is structurally
invisible to reconcile_cross_posted() — it looks like a brand-new,
board-unique opening ("ghost job") even when it isn't.

Two-stage pipeline to keep the DeepSeek spend down (explicit ask: "as cheap
as possible, no deep thinking"):
  1. Free algorithmic pre-filter — reuses storage.py's fuzzy title-token
     matching (same _title_tokens/_LEVEL_TOKENS machinery as
     _cluster_by_title), at a more lenient Jaccard threshold than
     storage.py's own 0.85, since this stage only gathers plausible
     candidates for the AI to judge rather than making the final call.
  2. One cheap DeepSeek call (deepseek-v4-flash, temperature 0, tiny
     max_tokens, no reasoning mode) per Secret Market post that has at
     least one candidate. The prompt carries title/seniority/location/a
     short description snippet only — never company names — so the model
     has no employer identity to leak even by accident.

A confirmed match sets board_signals.not_a_ghost_job = true. Deliberately
NEVER stores which board job matched (source/source_id/company/title) on
the row itself: board_signals is served to the frontend client verbatim
(webapp/backend/main.py:_own_signals), so persisting the matched listing's
identity there would let a client-side inspection de-anonymize a
confidential post — a direct violation of the plan's "never guess/reveal
employer" rule. The match target is logged server-side only, for human
auditing, never persisted to the jobs table.

Manual-only, same as --harvest-recruiter-emails / --deactivate-stale-posts:
not wired into daily_run.sh. Run via `--check-ghost-jobs`.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from dataclasses import dataclass

import httpx

from hk_jobs.storage import _LEVEL_TOKENS, _title_tokens

logger = logging.getLogger(__name__)

_API_URL = "https://api.deepseek.com/chat/completions"
_MODEL = "deepseek-v4-flash"

# Lower than storage.py's _FUZZY_TITLE_THRESHOLD (0.85) on purpose: this is a
# recall-oriented pre-filter to gather plausible candidates for the AI to
# judge, not a final same-vacancy decision.
PREFILTER_JACCARD_THRESHOLD = 0.4
MAX_CANDIDATES = 5
MATCH_CONFIDENCE_CUTOFF = 0.65
_DESC_SNIPPET_CHARS = 280

_SYSTEM_PROMPT = """You check whether a confidential "Secret Market" job post from a \
recruiter describes the SAME real, currently-open vacancy as one of several candidate \
listings already on a public job board.

Compare role/function, seniority, and location. The confidential post never names its \
employer — do not use company names to decide; none are given to you.

Return ONLY a JSON object (no markdown fences, no commentary):
{"match_index": <0-based index into the candidates array> or null, "confidence": <float 0.0-1.0>}

Rules:
- match_index is the SINGLE candidate that is almost certainly the same real opening as \
the target post — same function, same seniority, same location. A similar-sounding job \
that might be at a different employer is NOT a match.
- If no candidate is confidently the same vacancy, match_index must be null and confidence \
still reflects your certainty that NONE of them match (0.0-1.0, not left at 0 by default).
- When genuinely unsure, prefer null over a low-confidence guess."""


@dataclass
class GhostCheckSummary:
    checked: int = 0
    with_candidates: int = 0
    ai_calls: int = 0
    matched: int = 0
    errors: int = 0


class GhostCheckAuthError(RuntimeError):
    """Raised when DEEPSEEK_API_KEY is missing. Never retried."""


def _fetch_active_secret_market_jobs(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT source, source_id, title, description_clean, locations, board_signals "
        "FROM jobs WHERE source = 'linkedin_posts' AND is_active = 1"
    ).fetchall()


def _fetch_active_board_jobs(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT source, source_id, title, company, description_clean, locations "
        "FROM jobs WHERE source_tier IN ('mainstream', 'boutique') AND is_active = 1"
    ).fetchall()


def find_candidates(db_path: str) -> dict[str, list[tuple[sqlite3.Row, float]]]:
    """
    Free pre-filter: for each active Secret Market job, return up to
    MAX_CANDIDATES active mainstream/boutique jobs whose title fuzzy-matches
    (lenient Jaccard + same seniority tokens), sorted by score descending.
    Keyed by the Secret Market job's source_id.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        sm_jobs = _fetch_active_secret_market_jobs(conn)
        board_jobs = _fetch_active_board_jobs(conn)
    finally:
        conn.close()

    board_toks = [_title_tokens(b["title"]) for b in board_jobs]
    board_lvls = [t & _LEVEL_TOKENS for t in board_toks]

    result: dict[str, list[tuple[sqlite3.Row, float]]] = {}
    for sm in sm_jobs:
        sm_tok = _title_tokens(sm["title"])
        if not sm_tok:
            continue
        sm_lvl = sm_tok & _LEVEL_TOKENS
        scored = []
        for board, b_tok, b_lvl in zip(board_jobs, board_toks, board_lvls):
            if not b_tok or sm_lvl != b_lvl:
                continue
            score = len(sm_tok & b_tok) / len(sm_tok | b_tok)
            if score >= PREFILTER_JACCARD_THRESHOLD:
                scored.append((board, score))
        if scored:
            scored.sort(key=lambda pair: pair[1], reverse=True)
            result[sm["source_id"]] = scored[:MAX_CANDIDATES]
    return result


def _first_location(locations_json: str) -> str:
    try:
        locs = json.loads(locations_json or "[]")
    except json.JSONDecodeError:
        return ""
    return locs[0] if locs else ""


def _snippet(text: str) -> str:
    return (text or "").strip()[:_DESC_SNIPPET_CHARS]


def _build_candidate_prompt(sm: sqlite3.Row, board_candidates: list[sqlite3.Row]) -> str:
    lines = [
        "TARGET (confidential Secret Market post):",
        f"- title: {sm['title']}",
        f"- location: {_first_location(sm['locations'])}",
        f"- description: {_snippet(sm['description_clean'])}",
        "",
        "CANDIDATES (public board listings, 0-indexed):",
    ]
    for i, board in enumerate(board_candidates):
        lines.append(
            f"[{i}] title: {board['title']} | location: {_first_location(board['locations'])} "
            f"| description: {_snippet(board['description_clean'])}"
        )
    return "\n".join(lines)


def _ask_deepseek(
    sm: sqlite3.Row, board_candidates: list[sqlite3.Row], *, api_key: str
) -> tuple[int | None, float] | None:
    user_content = _build_candidate_prompt(sm, board_candidates)
    for attempt in range(1, 3):  # same low retry cap as extractor.py — billable calls
        try:
            content = _call_deepseek(user_content, api_key=api_key)
            data = json.loads(content.replace("```json", "").replace("```", "").strip())
            match_index = data.get("match_index")
            confidence = float(data.get("confidence") or 0.0)
            confidence = max(0.0, min(1.0, confidence))
            return (match_index if isinstance(match_index, int) else None, confidence)
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            if code in (401, 403):
                raise GhostCheckAuthError(f"DeepSeek rejected the API key (HTTP {code})") from exc
            if attempt == 2:
                logger.error("Ghost check AI call failed after retries: HTTP %d", code)
                return None
            logger.warning("Ghost check attempt %d failed (HTTP %d) — retrying", attempt, code)
        except (
            httpx.TimeoutException, httpx.NetworkError, json.JSONDecodeError, KeyError, ValueError,
        ) as exc:
            if attempt == 2:
                logger.error("Ghost check AI call failed after retries: %s", exc)
                return None
            logger.warning("Ghost check attempt %d failed (%s) — retrying", attempt, exc)
    return None


def _call_deepseek(user_content: str, *, api_key: str) -> str:
    """Single mockable seam — patch this in tests to inject a canned reply."""
    resp = httpx.post(
        _API_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": _MODEL,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0,
            # deepseek-v4-flash always emits reasoning_content before the
            # final `content`, and both count against max_tokens together
            # (confirmed live: reasoning alone ran 350-500 tokens on a
            # 5-candidate comparison, with real run-to-run variance even at
            # temperature 0). Tighter budgets (60, 300, 800) all left
            # content empty often enough to matter — reasoning ate the whole
            # cap before the model could emit the JSON reply. 1200 gives
            # comfortable headroom above the worst case observed live.
            "max_tokens": 1200,
            "response_format": {"type": "json_object"},
        },
        timeout=60.0,
    )
    if resp.status_code in (401, 403):
        raise httpx.HTTPStatusError(
            f"DeepSeek auth error {resp.status_code}", request=resp.request, response=resp
        )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def run_ghost_check(
    db_path: str, *, api_key: str | None = None, limit: int | None = None
) -> GhostCheckSummary:
    """
    Run the full pre-filter + AI-confirm pass over active Secret Market jobs.
    Idempotent: jobs already flagged not_a_ghost_job are re-checked (cheap to
    skip would need a separate "checked" marker not worth adding yet) but
    re-flagging is a no-op UPDATE.
    """
    key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        raise GhostCheckAuthError(
            "DEEPSEEK_API_KEY not set. Export it or add it to config/api_keys.env."
        )

    candidates = find_candidates(db_path)
    summary = GhostCheckSummary()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        sm_jobs = {row["source_id"]: row for row in _fetch_active_secret_market_jobs(conn)}
        summary.checked = len(sm_jobs)
        summary.with_candidates = len(candidates)

        items = list(candidates.items())
        if limit is not None:
            items = items[:limit]

        with conn:
            for source_id, scored in items:
                sm = sm_jobs.get(source_id)
                if sm is None:
                    continue
                board_candidates = [board for board, _ in scored]
                verdict = _ask_deepseek(sm, board_candidates, api_key=key)
                summary.ai_calls += 1
                if verdict is None:
                    summary.errors += 1
                    continue
                match_index, confidence = verdict
                if match_index is None or confidence < MATCH_CONFIDENCE_CUTOFF:
                    continue
                if not (0 <= match_index < len(scored)):
                    logger.warning(
                        "Ghost check: out-of-range match_index %r for %s", match_index, source_id
                    )
                    continue
                matched_board, title_score = scored[match_index]
                logger.info(
                    "Ghost check match: linkedin_posts/%s -> %s/%s %r "
                    "(title-overlap %.2f, ai-confidence %.2f)",
                    source_id, matched_board["source"], matched_board["source_id"],
                    matched_board["title"], title_score, confidence,
                )
                signals = json.loads(sm["board_signals"] or "{}")
                if signals.get("not_a_ghost_job") is True:
                    continue
                signals["not_a_ghost_job"] = True
                conn.execute(
                    "UPDATE jobs SET board_signals = ? "
                    "WHERE source = 'linkedin_posts' AND source_id = ?",
                    (json.dumps(signals, ensure_ascii=False), source_id),
                )
                summary.matched += 1
    finally:
        conn.close()

    logger.info(
        "Ghost check done: %d active posts, %d had candidates, %d AI calls, "
        "%d matched, %d errors",
        summary.checked, summary.with_candidates, summary.ai_calls,
        summary.matched, summary.errors,
    )
    return summary
