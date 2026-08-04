"""
Soft-delete "hard tech" roles from jobs.db, using DeepSeek to decide.

This job board is for FINANCE-sector roles. Pure technology/IT/engineering jobs
(software engineers, DevOps, cloud, data engineers, ML/AI engineers, cyber-
security, IT infrastructure, etc.) are noise here and should be dropped — but we
must NOT drop finance roles that merely mention tech (IT audit, quant analyst,
fintech product manager, "digital transformation" business roles…).

Token-optimised design:
  • Only titles that match a broad tech keyword net are sent to the model
    (obvious finance titles never cost a token).
  • Each UNIQUE title is classified once (titles repeat across firms), then the
    verdict is applied to every job row sharing that title.
  • Titles are batched many-per-call; the model returns only the indices of the
    tech ones (minimal completion tokens). No descriptions are sent — the title
    alone decides hard-tech vs not.

Soft-delete only (is_active=0) per project rule — reversible. A .bak backup of
jobs.db is written first.

Usage:
    set -a; source config/api_keys.env; set +a
    python scripts/remove_tech_roles.py --dry-run     # classify + report, write nothing
    python scripts/remove_tech_roles.py               # soft-delete the tech roles
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sqlite3
import sys
import time

import httpx

_DB = "data/jobs.db"
_MODEL = "deepseek-chat"
_BATCH = 60          # titles per DeepSeek call
_API = "https://api.deepseek.com/chat/completions"

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
    "You label Hong Kong finance-sector job titles as TECH or NOT. "
    "TECH = hands-on technology/IT/engineering roles whose core work is building, running, "
    "or securing software or IT systems: software/backend/frontend/full-stack engineer, "
    "developer, programmer, DevOps/SRE, cloud/platform engineer, data engineer, ML/AI engineer, "
    "cybersecurity/information security, IT infrastructure/network/systems/database admin (DBA), "
    "QA/test automation, solution/technical architect, application/IT support. "
    "NOT TECH = finance, banking, investment, quant/quantitative analyst, trading, risk, "
    "audit (including IT audit), compliance, operations, sales, relationship/wealth management, "
    "product manager, project/program manager, business analyst, data analyst, and any "
    "managerial or business role not primarily about building/running technology. "
    "When unsure, answer NOT TECH."
)


def _classify_batch(titles: list[str], key: str) -> set[int]:
    """Return the set of indices (into `titles`) the model labels TECH."""
    numbered = "\n".join(f"{i}. {t}" for i, t in enumerate(titles))
    user = (
        "Which of these job titles are TECH (per the rules)? "
        "Return ONLY a JSON array of their numbers, e.g. [0,3,7].\n\n" + numbered
    )
    for attempt in range(4):
        try:
            r = httpx.post(
                _API,
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": _MODEL,
                    "messages": [
                        {"role": "system", "content": _SYSTEM},
                        {"role": "user", "content": user},
                    ],
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
        nums = re.findall(r"\d+", content)
        return {int(n) for n in nums if int(n) < len(titles)}
    raise RuntimeError("DeepSeek batch failed after retries")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default=_DB)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        print("DEEPSEEK_API_KEY not set — `set -a; source config/api_keys.env; set +a` first.",
              file=sys.stderr)
        return 1

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT j.source AS source, j.source_id AS source_id,
                  j.title AS title, COALESCE(e.title_en,'') AS te
             FROM jobs j LEFT JOIN job_enrichments e
               ON j.source=e.source AND j.source_id=e.source_id
            WHERE j.is_active=1"""
    ).fetchall()

    # unique candidate titles (broad net)
    uniq: list[str] = []
    seen: set[str] = set()
    for r in rows:
        t = (r["title"] or "").strip()
        if not t or t in seen:
            continue
        if _NET.search(t + " " + (r["te"] or "")):
            seen.add(t)
            uniq.append(t)
    print(f"{len(rows)} active jobs | {len(uniq)} unique candidate titles to classify",
          file=sys.stderr)

    tech_titles: set[str] = set()
    for start in range(0, len(uniq), _BATCH):
        batch = uniq[start:start + _BATCH]
        idxs = _classify_batch(batch, key)
        for i in idxs:
            tech_titles.add(batch[i])
        print(f"  batch {start//_BATCH+1}/{(len(uniq)+_BATCH-1)//_BATCH}: "
              f"{len(idxs)} tech / {len(batch)}", file=sys.stderr)

    # rows affected
    affected = [r for r in rows if (r["title"] or "").strip() in tech_titles]
    print(f"\nTECH titles: {len(tech_titles)} unique  →  {len(affected)} job rows", file=sys.stderr)
    print("\nsample TECH titles being removed:", file=sys.stderr)
    for t in sorted(tech_titles)[:25]:
        print(f"  - {t[:75]}", file=sys.stderr)

    if args.dry_run:
        print("\n[dry-run] nothing written.", file=sys.stderr)
        return 0

    shutil.copy2(args.db, args.db + ".bak-pretech")
    refs = [(r["source"], r["source_id"]) for r in affected]
    conn.close()

    # Through JobStore.deactivate() rather than a raw UPDATE, so this one-off
    # admin pass re-elects primaries like every other writer. A raw UPDATE here
    # could hide a cross-posted Role from the board until the next nightly run.
    from hk_jobs.storage import JobStore

    with JobStore(args.db) as store:
        removed = store.deactivate(refs, reason="hard-tech-manual")
        remaining = store.stats()["active"]

    print(f"\n✅ Soft-deleted {removed} tech job rows (is_active=0). "
          f"Backup: {args.db}.bak-pretech", file=sys.stderr)
    print(f"   Active jobs now: {remaining}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
