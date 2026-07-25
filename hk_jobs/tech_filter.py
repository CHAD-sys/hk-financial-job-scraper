"""
Tech-role filter — keep the board FINANCE-only by dropping hard tech/IT roles.

This board is for finance-sector jobs. Pure technology roles (software engineers,
DevOps, cloud, data engineers, ML/AI engineers, cybersecurity, IT infrastructure,
DBAs, etc.) are noise and are soft-deleted (is_active=0, reversible) — but finance
roles that merely mention tech (IT audit, quant analyst, fintech product manager)
are kept.

Runs on every pipeline run (see pipeline.run). Token-optimised & durable:
  • A persistent `tech_title_cache(title, is_tech)` table remembers every verdict,
    so each run only sends NEW unique titles to DeepSeek — titles seen before cost
    zero tokens.
  • Titles are classified once and the verdict applied to all jobs sharing them.
  • Only titles matching a broad tech keyword net are ever sent (obvious finance
    titles never cost a token); the model prunes finance false-positives.
  • If no DEEPSEEK_API_KEY is available (e.g. out of credits), new titles are left
    unclassified but ALL cached tech verdicts are still enforced — so a tech role
    that reappears is still removed without any API call.

Public entry point: run_tech_filter(db_path, api_key=None) -> (n_classified, n_removed)
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import time

import httpx

logger = logging.getLogger(__name__)

# deepseek-chat/deepseek-reasoner retired 2026-07-24 (see hk_jobs/enrichers/deepseek.py's
# changelog, which migrated production enrichment off them). This module's model was left
# stale and started hard-failing every call the moment the cutoff hit.
_MODEL = "deepseek-v4-flash"
_API = "https://api.deepseek.com/chat/completions"
_BATCH = 60

# Broad recall net — anything plausibly tech. The model prunes finance false hits.
_NET = re.compile(
    r"(software|developer|programmer|engineer|full[- ]?stack|back[- ]?end|front[- ]?end|"
    r"devops|sre|cloud|kubernetes|data scien|data engineer|machine learning|\bml\b|\bai\b|"
    r"artificial intel|cyber|infosec|information security|\bit\b|infrastructure|network|"
    r"sysadmin|system admin|architect|automation|python|java|golang|react|platform|technolog|"
    r"technical|blockchain|analyst programmer|application support|helpdesk|help desk|qa\b|"
    r"\btest\b|database|dba)",
    re.I,
)

_SYSTEM = (
    "You label Hong Kong finance-sector job titles as TECH or NOT. Be CONSERVATIVE: "
    "only label TECH when the role's PRIMARY job is personally building, running, or "
    "securing software/IT systems as an engineer/developer/administrator.\n"
    "TECH (remove): software/backend/frontend/full-stack engineer, developer, programmer, "
    "DevOps/SRE, cloud/platform ENGINEER, data ENGINEER, ML/AI ENGINEER, database admin/DBA, "
    "systems/network administrator or engineer, IT infrastructure engineer, QA/test automation "
    "engineer, cybersecurity/information-security engineer or analyst (hands-on), "
    "solution/technical/enterprise architect, application/IT support engineer.\n"
    "NOT TECH (keep) — even if the title contains words like technology, platform, digital, "
    "automation, IT, cyber, or data: any AUDIT role incl. IT audit / technology-risk assurance "
    "/ accountant; tax technology; RISK, resilience, or governance MANAGEMENT; compliance; "
    "quant / quantitative analyst / strategist / trading desk roles; data ANALYST or business "
    "analyst; product manager; project/program/delivery manager; consultant; ANY 'Head of', "
    "'Director', 'ED', 'VP of' business/platform/wealth/operations leadership role; digital "
    "transformation / digitization business roles; relationship/wealth management; operations; "
    "sales. When unsure, answer NOT TECH."
)

_CACHE_DDL = """
CREATE TABLE IF NOT EXISTS tech_title_cache (
    title    TEXT PRIMARY KEY,
    is_tech  INTEGER NOT NULL,
    decided_at TEXT DEFAULT (datetime('now'))
)
"""


def _classify_batch(titles: list[str], key: str) -> set[int]:
    """Return indices (into `titles`) the model labels TECH."""
    numbered = "\n".join(f"{i}. {t}" for i, t in enumerate(titles))
    user = ("Which of these job titles are TECH (per the rules)? "
            "Return ONLY a JSON array of their numbers, e.g. [0,3,7].\n\n" + numbered)
    for attempt in range(4):
        try:
            r = httpx.post(
                _API,
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": _MODEL,
                    "messages": [{"role": "system", "content": _SYSTEM},
                                 {"role": "user", "content": user}],
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                    "max_tokens": 400,
                },
                timeout=60,
            )
        except httpx.HTTPError:
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code != 200:
            time.sleep(2 * (attempt + 1))
            continue
        content = r.json()["choices"][0]["message"]["content"]
        return {int(n) for n in re.findall(r"\d+", content) if int(n) < len(titles)}
    logger.warning("tech-filter: DeepSeek batch failed after retries — leaving these unclassified")
    return set()


def run_tech_filter(db_path: str, api_key: str | None = None) -> tuple[int, int]:
    """
    Classify any NEW tech-candidate titles, then soft-delete active jobs whose
    title is known-tech. Returns (newly_classified, rows_soft_deleted).
    """
    key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
    conn = sqlite3.connect(db_path, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute(_CACHE_DDL)

    cached = {r["title"]: r["is_tech"]
              for r in conn.execute("SELECT title, is_tech FROM tech_title_cache")}

    # Unique active-job candidate titles (broad net).
    rows = conn.execute("SELECT DISTINCT title FROM jobs WHERE is_active=1").fetchall()
    candidates = [(r["title"] or "").strip() for r in rows
                  if (r["title"] or "").strip() and _NET.search(r["title"] or "")]

    new_titles = [t for t in candidates if t not in cached]
    classified = 0
    if new_titles and key:
        for start in range(0, len(new_titles), _BATCH):
            batch = new_titles[start:start + _BATCH]
            tech_idx = _classify_batch(batch, key)
            with conn:
                for i, t in enumerate(batch):
                    verdict = 1 if i in tech_idx else 0
                    conn.execute(
                        "INSERT OR REPLACE INTO tech_title_cache (title, is_tech) VALUES (?, ?)",
                        (t, verdict),
                    )
                    cached[t] = verdict
            classified += len(batch)
        logger.info("tech-filter: classified %d new title(s) via DeepSeek", classified)
    elif new_titles and not key:
        logger.warning(
            "tech-filter: %d new candidate title(s) but no DEEPSEEK_API_KEY — "
            "enforcing cached verdicts only.", len(new_titles),
        )

    # Enforce: soft-delete active jobs whose title is known-tech.
    tech_titles = [t for t, v in cached.items() if v == 1]
    removed = 0
    if tech_titles:
        ph = ",".join("?" * len(tech_titles))
        with conn:
            cur = conn.execute(
                f"UPDATE jobs SET is_active=0 WHERE is_active=1 AND TRIM(title) IN ({ph})",
                tech_titles,
            )
            removed = cur.rowcount
    if removed:
        logger.info("tech-filter: soft-deleted %d hard-tech job row(s) (is_active=0)", removed)
    conn.close()
    return classified, removed
