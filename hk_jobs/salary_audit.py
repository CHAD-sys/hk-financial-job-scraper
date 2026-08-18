"""Outlier audit agent for salary estimates.

Runs AFTER enrichment (wired into the daily pipeline via --audit-salaries). It selects
the estimates most likely to be wrong, re-judges each with a fresh-context DeepSeek call
focused solely on "is this salary estimate right for this title?", and:

  - auto-applies corrections DOWNWARD only (over-estimation is the failure mode we fight;
    an agent error can therefore never inflate a salary), logging every change to the
    salary_audit_log table, and
  - reports upward suggestions for human review without applying them.

Every verdict is logged, including "ok" (2026-08-05) — not just the ones that changed
something. _select_outliers uses that log to skip a job whose last audit already
happened at-or-after its current enriched_at: nothing about its estimate could have
changed since, so re-judging it would only reproduce the same verdict. Before this, the
heuristic below re-selected the same ~550 stable outlier jobs every single night with no
memory of having already cleared them — the dominant share of the daily DeepSeek spend.

Selection heuristic (agreed 2026-07-21) — a job is flagged if ANY of:
  1. salary_estimated_max >= 120,000 (the senior range where errors concentrate and
     matter most to the board's credibility);
  2. salary_estimated_max > 1.5x the median of its (salary_tier-ish) cluster — we cluster
     by (seniority, job_category) since those are stored on the enrichment row;
  3. the title matches known-ambiguous patterns ("Team Head", "Team Lead", "Head of",
     "Principal") regardless of amount — the exact class of title whose meaning depends
     on context the first-pass estimator tends to resolve upward.

Usage:
    python -m hk_jobs.pipeline --audit-salaries          # normal (part of daily run)
    python -m hk_jobs.salary_audit --limit 20            # standalone / testing
    python -m hk_jobs.salary_audit --dry-run             # select + judge, write nothing
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime

from hk_jobs.enrichers.deepseek import DeepSeekEnricher, _SALARY_REFERENCE
from hk_jobs import salary

logger = logging.getLogger(__name__)

_MAX_WORKERS = 30
_HIGH_BAR = 120_000
_CLUSTER_MULTIPLE = 1.5
_AMBIGUOUS_TITLE = re.compile(r"\bteam head\b|\bteam lead\b|\bhead of\b|\bprincipal\b", re.I)

_AUDIT_PROMPT = """\
You are a salary auditor for a Hong Kong financial-sector job board. A first-pass system
estimated a monthly base salary range for the job at the END of this prompt. Your ONLY task
is to judge whether that estimate is realistic for THIS title at THIS company in Hong Kong,
using the reference table below, and correct it if it is too high.

The most common error you are looking for: a title matched to a band ABOVE its real grade.
Examples: a "Team Head" of a client-relationship/service/support team priced as if heading a
revenue-generating front-office team (a bank has MANY CR team heads at ~50k-100k, but few desk
heads at 150k+); a "Manager" priced as a Director; a support-function role priced on a
front-office ladder. Where the title's meaning is ambiguous, the LOWER interpretation is
correct.

REFERENCE — monthly HK$ BASE by tier -> named role -> grade row:
{salary_reference}

Return ONLY valid JSON, no markdown:
{{
  "verdict": "ok" | "too_high" | "too_low",
  "corrected_min": <integer or null — required when verdict is not "ok">,
  "corrected_max": <integer or null — required when verdict is not "ok">,
  "reason": "<one short sentence>"
}}
Rules: if the current estimate already sits in the right band, verdict "ok" (do not nitpick
small differences within the correct band — only flag when the WRONG band/grade was used).
Never propose a max above HK$200,000.

======== THE JOB TO AUDIT ========
Company: {company}
Title: {title}
Current estimate: HK${est_min:,} - HK${est_max:,} per month
Description (may be empty):
{description}"""


def _select_outliers(
    conn: sqlite3.Connection, limit: int | None = None, full: bool = False,
) -> list[sqlite3.Row]:
    # Excludes a job whose last audit already happened at-or-after its current
    # enriched_at — i.e. it was already judged against the exact estimate still on
    # the row. Nothing about that estimate can have changed since, so re-sending it
    # to the auditor would only ever reproduce the same verdict. This was the
    # dominant recurring cost: the heuristic below re-selected the same ~550 stable
    # high-salary/ambiguous-title jobs every single night regardless of whether they
    # were already cleared, because the old query had no memory of past audits.
    # A re-enrichment (new prompt_version, reactivated listing) bumps enriched_at
    # past the last audit and makes the job eligible again on its own — no manual
    # "revalidate" step needed. --full intentionally bypasses this: it exists to
    # sweep the whole dataset for a real accuracy number, not just what changed.
    #
    # manually_edited_at IS NULL is excluded unconditionally, --full included: a
    # hand-corrected salary (webapp/backend/job_edit.py, Ultimate Admin) is
    # exactly the shape of an "outlier" this function looks for, and would
    # otherwise be sent right back to the judge that just got overruled by a
    # human — reverting the correction the next time this runs.
    rows = conn.execute("""
        SELECT j.source, j.source_id, j.title, j.company, j.company_slug, j.source_tier,
               j.description_clean, e.seniority, e.job_category, e.salary_tier, e.salary_role,
               e.salary_estimated_min AS est_min, e.salary_estimated_max AS est_max
        FROM jobs j JOIN job_enrichments e
          ON j.source = e.source AND j.source_id = e.source_id
        LEFT JOIN (
            SELECT source, source_id, MAX(audited_at) AS last_audited_at
              FROM salary_audit_log GROUP BY source, source_id
        ) a ON j.source = a.source AND j.source_id = a.source_id
        WHERE j.is_active = 1 AND e.salary_estimated_max IS NOT NULL
          AND e.manually_edited_at IS NULL
          AND (:full OR a.last_audited_at IS NULL OR a.last_audited_at < e.enriched_at)
    """, {"full": full}).fetchall()

    if full:
        # Whole-dataset review (2026-07-22): cheap enough now (small dataset, prefix
        # caching) to run the judge over every priced active job instead of only the
        # heuristic-flagged subset — gives a real accuracy percentage across the board,
        # not just among the jobs already suspected of being wrong.
        rows = sorted(rows, key=lambda r: -(r["est_max"] or 0))
        return rows[:limit] if limit else rows

    # cluster medians for criterion 2
    clusters: dict[tuple, list[int]] = {}
    for r in rows:
        clusters.setdefault((r["seniority"], r["job_category"]), []).append(r["est_max"])
    medians = {k: statistics.median(v) for k, v in clusters.items()}

    flagged = []
    for r in rows:
        med = medians.get((r["seniority"], r["job_category"]), 0)
        if (
            r["est_max"] >= _HIGH_BAR
            or (med and r["est_max"] > _CLUSTER_MULTIPLE * med)
            or _AMBIGUOUS_TITLE.search(r["title"] or "")
        ):
            flagged.append(r)
    flagged.sort(key=lambda r: -(r["est_max"] or 0))
    return flagged[:limit] if limit else flagged


def _judge(enricher: DeepSeekEnricher, row: sqlite3.Row) -> dict | None:
    prompt = _AUDIT_PROMPT.format(
        salary_reference=_SALARY_REFERENCE,
        company=row["company"], title=row["title"],
        est_min=row["est_min"], est_max=row["est_max"],
        description=(row["description_clean"] or "")[:1500],
    )
    import httpx
    from hk_jobs.enrichers.deepseek import _API_URL, _MODEL
    with httpx.Client(timeout=120.0) as client:
        resp = client.post(
            _API_URL,
            headers={"Authorization": f"Bearer {enricher.api_key}",
                     "Content-Type": "application/json"},
            # Thinking mode off here for the same reason as the enricher (see the
            # v11 changelog in enrichers/deepseek.py): the reasoning trace is billed
            # as output and dwarfed the answer. The verdict is four short fields, so
            # 300 is already generous. temperature/top_p were silently ignored under
            # thinking and are live again; near-zero because this is a judgement
            # against a fixed reference table, not open-ended writing.
            #
            # Worth knowing: this judge is the backstop that catches the tier
            # mis-grading the enricher's own thinking mode was brought in to fix, and
            # it runs only over flagged outliers, so its share of the bill was always
            # small. If tier drift shows up after v11, this is the first place to
            # consider turning reasoning back on.
            json={"model": _MODEL,
                  "messages": [{"role": "user", "content": prompt}],
                  "max_tokens": 300,
                  "temperature": 0.1,
                  "top_p": 0.9},
        )
    if resp.status_code != 200:
        raise RuntimeError(f"API {resp.status_code}: {resp.text[:120]}")
    payload = resp.json()
    text = payload["choices"][0]["message"]["content"].strip()
    text = text.replace("```json", "").replace("```", "").strip()
    result = json.loads(text)
    result["_api_usage"] = payload.get("usage") or {}
    return result


def run_audit(db_path: str = "data/jobs.db", limit: int | None = None,
              dry_run: bool = False, api_key: str | None = None, full: bool = False) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        flagged = _select_outliers(conn, limit, full=full)
        if not flagged:
            logger.info("Salary audit: no outliers flagged — nothing to do")
            return
        logger.info("Salary audit: %d jobs %s%s",
                    len(flagged), "selected for full review" if full else "flagged for review",
                    " (DRY RUN)" if dry_run else "")

        enricher = DeepSeekEnricher(api_key=api_key)
        results: dict[tuple[str, str], dict | None] = {}
        with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
            futures = {pool.submit(_judge, enricher, r): r for r in flagged}
            for fut in as_completed(futures):
                r = futures[fut]
                key = (r["source"], r["source_id"])
                try:
                    results[key] = fut.result()
                except Exception as exc:
                    logger.warning("Audit failed for %r: %s", r["title"][:50], exc)
                    results[key] = None

        lowered = ok = flag_up = failed = 0
        usage_totals: dict[str, int] = {
            "calls": 0, "cache_hit": 0, "cache_miss": 0, "completion": 0,
        }
        from hk_jobs.ai_usage import add_usage, record

        up_report = []
        now = datetime.now(UTC).isoformat()
        with conn:
            for r in flagged:
                key = (r["source"], r["source_id"])
                verdict = results.get(key)
                if verdict is None:
                    failed += 1
                    continue
                add_usage(usage_totals, {"usage": verdict.pop("_api_usage", {})})
                v = verdict.get("verdict")
                if v == "too_high":
                    revised = salary.lowered(
                        verdict.get("corrected_min"),
                        verdict.get("corrected_max"),
                        current_max=r["est_max"],
                        tier=r["salary_tier"],
                        seniority=r["seniority"],
                        role=r["salary_role"],
                        company_slug=r["company_slug"],
                        title=r["title"],
                        source_tier=r["source_tier"],
                    )
                    if revised is None:
                        ok += 1  # not actually lower — treat as no-op
                        continue
                    new_min, new_max = revised
                    if dry_run:
                        lowered += 1
                        logger.info("[dry] would lower %r: %s-%s -> %s-%s (%s)",
                                    r["title"][:45], r["est_min"], r["est_max"],
                                    new_min, new_max, verdict.get("reason", ""))
                        continue
                    conn.execute(
                        """UPDATE job_enrichments
                              SET salary_estimated_min = ?, salary_estimated_max = ?
                            WHERE source = ? AND source_id = ?""",
                        (new_min, new_max, r["source"], r["source_id"]),
                    )
                    conn.execute(
                        """INSERT INTO salary_audit_log
                             (source, source_id, audited_at, old_min, old_max,
                              new_min, new_max, action, reason)
                           VALUES (?, ?, ?, ?, ?, ?, ?, 'lowered', ?)""",
                        (r["source"], r["source_id"], now, r["est_min"], r["est_max"],
                         new_min, new_max, verdict.get("reason", "")),
                    )
                    lowered += 1
                elif v == "too_low":
                    flag_up += 1
                    up_report.append((r, verdict))
                    if not dry_run:
                        conn.execute(
                            """INSERT INTO salary_audit_log
                                 (source, source_id, audited_at, old_min, old_max,
                                  new_min, new_max, action, reason)
                               VALUES (?, ?, ?, ?, ?, NULL, NULL, 'flag_up', ?)""",
                            (r["source"], r["source_id"], now, r["est_min"], r["est_max"],
                             verdict.get("reason", "")),
                        )
                else:
                    ok += 1
                    if not dry_run:
                        conn.execute(
                            """INSERT INTO salary_audit_log
                                 (source, source_id, audited_at, old_min, old_max,
                                  new_min, new_max, action, reason)
                               VALUES (?, ?, ?, ?, ?, NULL, NULL, 'ok', ?)""",
                            (r["source"], r["source_id"], now, r["est_min"], r["est_max"],
                             verdict.get("reason", "")),
                        )

        reviewed = len(flagged) - failed
        accuracy_pct = 100.0 * ok / reviewed if reviewed else 0.0
        logger.info("Salary audit complete: %d reviewed — %d lowered, %d ok, "
                    "%d flagged-too-low (NOT auto-raised), %d failed",
                    len(flagged), lowered, ok, flag_up, failed)
        logger.info("Accuracy (judged already-correct, no change needed): %.1f%% (%d/%d)",
                    accuracy_pct, ok, reviewed)
        if not dry_run:
            record(
                db_path,
                phase="salary_audit",
                model="deepseek-v4-flash",
                totals=usage_totals,
                roles_processed=len(flagged),
            )
        if up_report:
            logger.info("── upward suggestions for human review (never auto-applied) ──")
            for r, verdict in up_report[:20]:
                logger.info("  %s | %s | current %s-%s | suggested %s-%s | %s",
                            r["company"][:25], r["title"][:45], r["est_min"], r["est_max"],
                            verdict.get("corrected_min"), verdict.get("corrected_max"),
                            verdict.get("reason", ""))
    finally:
        conn.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="data/jobs.db")
    ap.add_argument("--limit", type=int, default=None, help="max jobs to audit")
    ap.add_argument("--dry-run", action="store_true", help="judge but write nothing")
    ap.add_argument("--full", action="store_true",
                    help="review every active priced job, not just heuristic-flagged outliers")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s %(message)s",
                        datefmt="%H:%M:%S")
    for noisy in ("httpcore", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    # The whole ledger, not the one phase this module happens to need. Naming
    # your own prerequisites is how the startup path came to be missing phases
    # 27 and 28 — see hk_jobs/migrations.py.
    from hk_jobs.migrations import migrate
    migrate(args.db)
    run_audit(args.db, limit=args.limit, dry_run=args.dry_run, full=args.full)


if __name__ == "__main__":
    main()
