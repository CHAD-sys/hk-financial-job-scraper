"""
Phase 12: LLM-based job enrichment pipeline.

Reads unenriched jobs from jobs.db, sends them to DeepSeek for structured
field extraction, and writes results to the job_enrichments table.

Usage:
    python -m hk_jobs.pipeline --enrich
    python -m hk_jobs.pipeline --enrich --enrich-limit 10
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, UTC

from hk_jobs.enrichers.deepseek import DeepSeekEnricher

logger = logging.getLogger(__name__)

_BATCH_SIZE = 20


class EnrichmentPipeline:
    """
    Fetches unenriched jobs, calls DeepSeek, and writes to job_enrichments.

    The jobs table uses (source, source_id) as its primary key — there is no
    integer 'id' column.  job_enrichments mirrors that composite key.
    """

    def __init__(self, db_path: str = "data/jobs.db", api_key: str | None = None) -> None:
        self.db_path = db_path
        self._api_key = api_key  # passed through to DeepSeekEnricher

    def run(self, batch_size: int = _BATCH_SIZE, limit: int | None = None) -> None:
        logger.info("Phase 12 enrichment — starting")

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            jobs = self._fetch_unenriched(conn, limit)
            if not jobs:
                logger.info("No unenriched jobs found — nothing to do")
                return

            logger.info("Found %d unenriched jobs", len(jobs))

            enriched = failed = 0
            with DeepSeekEnricher(api_key=self._api_key) as enricher:
                for batch_start in range(0, len(jobs), batch_size):
                    batch = jobs[batch_start: batch_start + batch_size]
                    batch_num = batch_start // batch_size + 1
                    logger.info("Batch %d / %d …", batch_num, -(-len(jobs) // batch_size))

                    results = enricher.enrich_batch(
                        [(r["source"], r["source_id"], r["title"], r["description_raw"])
                         for r in batch]
                    )

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
                                         job_category, enriched_at, model_used)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                    ON CONFLICT (source, source_id) DO UPDATE SET
                                        seniority                = excluded.seniority,
                                        years_experience_required= excluded.years_experience_required,
                                        required_skills          = excluded.required_skills,
                                        remote_type              = excluded.remote_type,
                                        salary_hkd_min           = excluded.salary_hkd_min,
                                        salary_hkd_max           = excluded.salary_hkd_max,
                                        job_category             = excluded.job_category,
                                        enriched_at              = excluded.enriched_at,
                                        model_used               = excluded.model_used
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
                                    ),
                                )
                                enriched += 1
                            except Exception as exc:
                                logger.error("Insert failed for %s/%s: %s", *key, exc)
                                failed += 1

                    logger.info("Batch done — running total: %d enriched, %d failed", enriched, failed)

            logger.info("✅ Phase 12 complete: %d enriched, %d failed", enriched, failed)
        finally:
            conn.close()

    # ── helpers ───────────────────────────────────────────────────────────────

    def _fetch_unenriched(
        self, conn: sqlite3.Connection, limit: int | None
    ) -> list[sqlite3.Row]:
        """
        Return jobs that have no row in job_enrichments yet.

        We enrich on title alone when description_raw is empty (which is the
        normal state since we only scrape listing pages, not detail pages).
        DeepSeek can still extract seniority, category, and remote_type from
        the title.
        """
        sql = """
            SELECT j.source, j.source_id, j.title, j.description_raw
              FROM jobs j
              LEFT JOIN job_enrichments e
                ON j.source = e.source AND j.source_id = e.source_id
             WHERE e.source_id IS NULL
               AND j.is_active = 1
             ORDER BY j.fetched_at DESC
        """
        if limit:
            sql += f" LIMIT {limit}"
        return conn.execute(sql).fetchall()
