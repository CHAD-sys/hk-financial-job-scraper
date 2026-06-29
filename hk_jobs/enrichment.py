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
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, UTC
from typing import Any

from hk_jobs.enrichers.deepseek import DeepSeekEnricher

logger = logging.getLogger(__name__)

_MAX_WORKERS = 20   # concurrent DeepSeek API calls; bump carefully — rate limits apply
_BATCH_SIZE = 50    # jobs fetched from DB per write cycle

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


class EnrichmentPipeline:
    def __init__(self, db_path: str = "data/jobs.db", api_key: str | None = None) -> None:
        self.db_path = db_path
        self._api_key = api_key

    def run(self, batch_size: int = _BATCH_SIZE, limit: int | None = None,
            incremental: bool = False, re_enrich: bool = False) -> None:
        logger.info("Phase 12 enrichment — starting (workers=%d%s)",
                    _MAX_WORKERS, ", RE-ENRICH ALL" if re_enrich else "")

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            jobs = self._fetch_unenriched(conn, limit, incremental=incremental, re_enrich=re_enrich)
            if not jobs:
                logger.info("No unenriched jobs — nothing to do")
                return

            total = len(jobs)
            mode = "incremental (today's new jobs only)" if incremental else "full"
            logger.info("Enriching %d jobs [%s] with %d concurrent workers …", total, mode, _MAX_WORKERS)

            enriched = failed = 0
            enricher = DeepSeekEnricher(api_key=self._api_key)

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
                            conn.execute(
                                """
                                INSERT INTO job_enrichments
                                    (source, source_id, seniority,
                                     years_experience_required, required_skills,
                                     remote_type, salary_hkd_min, salary_hkd_max,
                                     job_category, enriched_at, model_used,
                                     salary_estimated_min, salary_estimated_max,
                                     salary_estimated_confidence)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                                    salary_estimated_confidence = excluded.salary_estimated_confidence
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
                                    "deepseek-chat",
                                    _coerce_int(data.get("salary_estimated_min")),
                                    _coerce_int(data.get("salary_estimated_max")),
                                    _norm_confidence(data.get("salary_estimated_confidence")),
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
        finally:
            conn.close()

    def _fetch_unenriched(
        self, conn: sqlite3.Connection, limit: int | None,
        incremental: bool = False, re_enrich: bool = False,
    ) -> list[sqlite3.Row]:
        today_filter = "AND DATE(j.fetched_at) = DATE('now')" if incremental else ""
        # Default: only jobs with no enrichment row. re_enrich: every active job
        # (the ON CONFLICT DO UPDATE upserts), so a prompt change reaches all rows.
        enriched_filter = "" if re_enrich else "AND e.source_id IS NULL"
        sql = f"""
            SELECT j.source, j.source_id, j.title, j.company, j.description_clean
              FROM jobs j
              LEFT JOIN job_enrichments e
                ON j.source = e.source AND j.source_id = e.source_id
             WHERE j.is_active = 1
               {enriched_filter}
               {today_filter}
             ORDER BY j.fetched_at DESC
        """
        if limit:
            sql += f" LIMIT {limit}"
        rows = conn.execute(sql).fetchall()
        if incremental:
            total = conn.execute("""
                SELECT COUNT(*) FROM jobs j
                LEFT JOIN job_enrichments e ON j.source=e.source AND j.source_id=e.source_id
                WHERE e.source_id IS NULL AND j.is_active=1
            """).fetchone()[0]
            logger.info(
                "Incremental mode: %d new jobs to enrich, skipping %d existing",
                len(rows), total - len(rows),
            )
        return rows
