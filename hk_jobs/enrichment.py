"""
Phase 12: LLM-based job enrichment pipeline — optimized.

Uses ThreadPoolExecutor to fire multiple DeepSeek API calls concurrently.
Each worker handles one job (one API round-trip) independently, so 20 workers
means ~20 calls in-flight at once. DB writes are kept sequential (SQLite
doesn't support concurrent writes).

Estimated throughput: ~13 jobs/s → 1,043 remaining jobs in ~80 s.

Usage:
    python -m hk_jobs.pipeline --enrich
    python -m hk_jobs.pipeline --enrich --enrich-limit 50
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from typing import Any

from hk_jobs.board_visibility import board_visible_sql
from hk_jobs.enrichers.deepseek import _MODEL, PROMPT_VERSION, DeepSeekEnricher
from hk_jobs import salary, salary_corrections

logger = logging.getLogger(__name__)

_MAX_WORKERS = 90   # concurrent DeepSeek API calls; bump carefully — rate limits apply.
                    # Bumped 20->60->150->90 for the v9 thinking-mode backfill. 150 hit no
                    # 429s but caused a much higher rate of garbled/empty responses (~11%
                    # of jobs needed a retry, vs ~1.7% at 60) — DeepSeek straining under
                    # load rather than cleanly rejecting, which burns retries/tokens
                    # without a clear backoff signal. 90 is a middle ground; re-check the
                    # retry rate before pushing higher again.
_BATCH_SIZE = 90    # jobs fetched from DB per write cycle — matches _MAX_WORKERS so a
                    # full batch saturates the worker pool

_VALID_CONFIDENCE = {"low", "medium", "high"}


def _coerce_int(value: Any) -> int | None:
    """Salary estimates may come back as int, float, str, or null — coerce to int|None."""
    if value is None:
        return None
    try:
        return int(float(str(value).replace(",", "").strip()))
    except (ValueError, TypeError):
        return None


def _norm_confidence(value: Any) -> str | None:
    """Normalise the model's confidence to low|medium|high, else None."""
    if not value:
        return None
    v = str(value).strip().lower()
    return v if v in _VALID_CONFIDENCE else None


def _clean_title_en(value: Any) -> str | None:
    """
    Normalise the model's English title.

    Collapse whitespace and drop any stray markdown/quote noise. Returns None
    (not "") when empty so the frontend's `title_en || title` fallback shows the
    original title rather than a blank line.
    """
    if not value:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip().strip('"').strip()
    return text or None


_MAX_SUMMARY_SENTENCES = 3
_MAX_SUMMARY_WORDS = 55  # ~50 with a little slack; hard safety net if the model overshoots


def _clean_summary(value: Any) -> str:
    """
    Normalise the model's description_summary for card display.

    The prompt already asks for <=3 sentences / ~50 words of plain prose, but we
    defensively enforce it so a card can never overflow: strip markdown/bullets,
    collapse all whitespace and line breaks to single spaces, keep at most the
    first 3 sentences, then cap word count. Empty/absent → "" (never hallucinated).
    """
    if not value:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    # Drop markdown markers and bullet glyphs; collapse newlines/whitespace to spaces.
    text = re.sub(r"[*_`#>]+", "", text)
    text = re.sub(r"^\s*[-•]\s*", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    # Keep at most the first N sentences.
    sentences = re.findall(r"[^.!?]+[.!?]+|[^.!?]+$", text)
    if len(sentences) > _MAX_SUMMARY_SENTENCES:
        text = "".join(sentences[:_MAX_SUMMARY_SENTENCES]).strip()
    # Hard word cap as a final safety net.
    words = text.split()
    if len(words) > _MAX_SUMMARY_WORDS:
        text = " ".join(words[:_MAX_SUMMARY_WORDS]).rstrip(",;:") + "…"
    return text


class EnrichmentPipeline:
    def __init__(self, db_path: str = "data/jobs.db", api_key: str | None = None) -> None:
        self.db_path = db_path
        self._api_key = api_key

    def run(self, batch_size: int = _BATCH_SIZE, limit: int | None = None,
            incremental: bool = False, re_enrich: bool = False,
            boutique_only: bool = False) -> None:
        logger.info(
            "Phase 12 enrichment — starting (workers=%d%s%s)",
            _MAX_WORKERS,
            ", RE-ENRICH ALL" if re_enrich else "",
            ", BOUTIQUE ONLY" if boutique_only else "",
        )

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            jobs = self._fetch_unenriched(
                conn, limit, incremental=incremental,
                re_enrich=re_enrich, boutique_only=boutique_only,
            )
            if not jobs:
                logger.info("No unenriched jobs — nothing to do")
                return

            total = len(jobs)
            mode = "incremental (today's new jobs only)" if incremental else "full"
            logger.info("Enriching %d jobs [%s] with %d concurrent workers …", total, mode, _MAX_WORKERS)

            enriched = failed = 0
            # Read once, on this run's own connection, and handed to the
            # enricher. What admins have already corrected by hand becomes
            # evidence in front of the model for Roles of the same shape — see
            # hk_jobs/salary_corrections.py, including why this deliberately
            # does NOT invalidate estimates already stored.
            corrections = salary_corrections.load(conn)
            if corrections:
                logger.info(
                    "Salary calibration: %d human correction(s) available to the estimator",
                    len(corrections),
                )
            enricher = DeepSeekEnricher(
                api_key=self._api_key, salary_corrections=corrections,
            )

            for batch_start in range(0, total, batch_size):
                batch = jobs[batch_start: batch_start + batch_size]
                batch_num = batch_start // batch_size + 1
                n_batches = -(-total // batch_size)
                logger.info("Batch %d/%d (%d jobs) …", batch_num, n_batches, len(batch))

                # ── parallel API calls ─────────────────────────────────────
                results: dict[tuple[str, str], dict[str, Any] | None] = {}
                with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
                    futures = {
                        pool.submit(
                            enricher._enrich_with_retry,
                            row["title"], row["company"], row["description_clean"] or "",
                            seniority=row["seniority"] if "seniority" in row.keys() else None,
                            company_slug=row["company_slug"],
                        ): row
                        for row in batch
                    }
                    for future in as_completed(futures):
                        row = futures[future]
                        key = (row["source"], row["source_id"])
                        try:
                            results[key] = future.result()
                        except Exception as exc:
                            logger.error("Future error %s/%s: %s", *key, exc)
                            results[key] = None

                # ── sequential DB writes ───────────────────────────────────
                with conn:
                    for row in batch:
                        key = (row["source"], row["source_id"])
                        data = results.get(key)
                        if data is None:
                            failed += 1
                            continue
                        try:
                            # Magnitude fix then the deterministic clamp — one
                            # call, so the estimator and the nightly audit cannot
                            # drift on how a model answer becomes a stored one.
                            est_salary_min, est_salary_max = salary.finalise(
                                _coerce_int(data.get("salary_estimated_min")),
                                _coerce_int(data.get("salary_estimated_max")),
                                tier=data.get("salary_tier"),
                                seniority=data.get("seniority"),
                                role=data.get("salary_role"),
                                grade=data.get("salary_grade"),
                                company_slug=row["company_slug"],
                                title=row["title"],
                                source_tier=row["source_tier"],
                                coordinate_only=True,
                            )
                            est_confidence = data.get("salary_estimated_confidence")
                            # Recruiter posts used to have their estimate discarded here —
                            # "never an AI guess, a post with no figure stated should show
                            # no salary, not a fabricated one". Reversed by owner decision
                            # (2026-08-05): they now estimate like every other source.
                            #
                            # What changed is not the risk but where it is answered. The
                            # objection was that a number derived from a title and a few
                            # lines of social copy would be read as a disclosed figure.
                            # It is not: the UI renders an estimate muted, in mono, behind
                            # an explicit "AI est." tag, and a disclosed salary always wins
                            # over it (webapp/frontend/src/components/JobCard.tsx →
                            # CardFooter). Withholding the number entirely told a Seeker
                            # nothing at all about a fifth of the Secret Market; labelling
                            # it tells them what it is worth.
                            #
                            # The estimate still goes through salary.finalise() above like
                            # every other row, so the clamp and the magnitude fix apply —
                            # these are not raw model output.
                            conn.execute(
                                """
                                INSERT INTO job_enrichments
                                    (source, source_id, seniority,
                                     years_experience_required, required_skills,
                                     remote_type, salary_hkd_min, salary_hkd_max,
                                     job_category, enriched_at, model_used,
                                     salary_estimated_min, salary_estimated_max,
                                     salary_estimated_confidence, description_summary,
                                     title_en, prompt_version, salary_tier, salary_role,
                                    salary_grade)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                ON CONFLICT (source, source_id) DO UPDATE SET
                                    seniority                 = excluded.seniority,
                                    years_experience_required = excluded.years_experience_required,
                                    required_skills           = excluded.required_skills,
                                    remote_type               = excluded.remote_type,
                                    salary_hkd_min            = excluded.salary_hkd_min,
                                    salary_hkd_max            = excluded.salary_hkd_max,
                                    job_category              = excluded.job_category,
                                    enriched_at               = excluded.enriched_at,
                                    model_used                = excluded.model_used,
                                    salary_estimated_min        = excluded.salary_estimated_min,
                                    salary_estimated_max        = excluded.salary_estimated_max,
                                    salary_estimated_confidence = excluded.salary_estimated_confidence,
                                    description_summary         = excluded.description_summary,
                                    title_en                    = excluded.title_en,
                                    prompt_version               = excluded.prompt_version,
                                    salary_tier                  = excluded.salary_tier,
                                    salary_role                  = excluded.salary_role,
                                    salary_grade                 = excluded.salary_grade
                                """,
                                (
                                    row["source"], row["source_id"],
                                    data.get("seniority"),
                                    data.get("years_experience"),
                                    json.dumps(data.get("skills", [])),
                                    data.get("remote_type"),
                                    data.get("salary_hkd_min"),
                                    data.get("salary_hkd_max"),
                                    data.get("job_category"),
                                    datetime.now(UTC).isoformat(),
                                    _MODEL,
                                    est_salary_min,
                                    est_salary_max,
                                    _norm_confidence(est_confidence),
                                    _clean_summary(data.get("description_summary")),
                                    _clean_title_en(data.get("title_en")),
                                    PROMPT_VERSION,
                                    data.get("salary_tier"),
                                    data.get("salary_role"),
                                    data.get("salary_grade"),
                                ),
                            )
                            enriched += 1
                        except Exception as exc:
                            logger.error("Insert failed %s/%s: %s", *key, exc)
                            failed += 1

                logger.info(
                    "Batch %d done — total so far: %d enriched, %d failed",
                    batch_num, enriched, failed,
                )

            logger.info("✅ Phase 12 complete: %d enriched, %d failed", enriched, failed)
            from hk_jobs.ai_usage import record

            record(
                self.db_path,
                phase="deepseek_enrichment",
                model=_MODEL,
                totals=getattr(
                    enricher,
                    "usage_totals",
                    {"calls": 0, "cache_hit": 0, "cache_miss": 0, "completion": 0},
                ),
                roles_processed=enriched + failed,
            )
        finally:
            conn.close()

    def _fetch_unenriched(
        self, conn: sqlite3.Connection, limit: int | None,
        incremental: bool = False, re_enrich: bool = False,
        boutique_only: bool = False,
    ) -> list[sqlite3.Row]:
        today_filter = "AND DATE(j.fetched_at) = DATE('now')" if incremental else ""
        # boutique_only restricts to the "Exclusive" section (jobs whose category
        # was set from the company config) and always reprocesses them — those
        # rows already have enrichment, so we must upsert, not skip them.
        boutique_filter = "AND j.category IS NOT NULL" if boutique_only else ""
        # Default: jobs with no enrichment row, OR whose enrichment predates the current
        # PROMPT_VERSION — this is what lets a job reactivated after soft-delete (or any
        # job enriched under an older prompt/model) get automatically refreshed by a
        # regular run, not just an explicit --re-enrich. re_enrich/boutique_only still
        # reprocess everything matching (the ON CONFLICT DO UPDATE upserts) — EXCEPT a
        # row Ultimate Admin has hand-edited (job_enrichments.manually_edited_at, phase
        # 33), which the WHERE clause below excludes unconditionally, re_enrich/
        # boutique_only included: those flags exist to force everything ELSE to be
        # reconsidered, not to erase a correction a human already made.
        # A version is "current enough" if it IS the current one, or if an operator
        # has grandfathered it in salary.ACCEPTED_PRIOR_VERSIONS — see that constant
        # for why. Without this, editing one sentence of the prompt re-enriches the
        # entire active board (~$40 at the observed rate), which is a decision, not
        # something that should happen as a side effect of a wording change.
        accepted = {PROMPT_VERSION, *salary.ACCEPTED_PRIOR_VERSIONS}
        accepted_sql = ", ".join("'" + v.replace("'", "''") + "'" for v in sorted(accepted))
        enriched_filter = (
            ""
            if (re_enrich or boutique_only)
            else f"AND (e.source_id IS NULL OR e.prompt_version IS NULL "
                 f"OR e.prompt_version NOT IN ({accepted_sql}))"
        )
        # ADR 0034: estimation never targets a Role that isn't on the board.
        # board_visible_sql() is the exact predicate webapp/backend/job_read.py's
        # BOARD_WHERE uses — is_active, is_primary, not admin_hidden, posted
        # within the last month, and (ADR 0035) among the freshest 60 Roles for
        # its employer — so the two cannot drift the way they did when only the
        # read side had a definition: a $5.24 bulk run once spent 66% of its
        # budget on duplicate copies of a cross-posted vacancy, postings over a
        # month old, and rows with no posting date at all, none of which a
        # Seeker could ever have seen. The per-company cap (ADR 0035) brought
        # the pool from ~3,250 to ~2,100 so a nightly run can cover all of it.
        board_filter = board_visible_sql()
        sql = f"""
            SELECT j.source, j.source_id, j.title, j.company, j.company_slug,
                   j.source_tier, j.description_clean
              FROM jobs j
              LEFT JOIN job_enrichments e
                ON j.source = e.source AND j.source_id = e.source_id
             WHERE {board_filter}
               AND e.manually_edited_at IS NULL
               {enriched_filter}
               {boutique_filter}
               {today_filter}
             ORDER BY j.fetched_at DESC
        """
        if limit:
            sql += f" LIMIT {limit}"
        rows = conn.execute(sql).fetchall()
        if incremental:
            total = conn.execute(f"""
                SELECT COUNT(*) FROM jobs j
                LEFT JOIN job_enrichments e ON j.source=e.source AND j.source_id=e.source_id
                WHERE e.source_id IS NULL AND {board_filter}
            """).fetchone()[0]
            logger.info(
                "Incremental mode: %d new jobs to enrich, skipping %d existing",
                len(rows), total - len(rows),
            )
        return rows
