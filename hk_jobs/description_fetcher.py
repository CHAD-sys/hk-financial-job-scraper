"""
Fetch full job descriptions from ATS JSON APIs.

Why this is a separate step: the main scrapers hit listing pages only (fast,
no per-job detail fetches), leaving description_raw and description_clean empty.
This module fills them in by calling each ATS's detail endpoint.

Source routing:
  workday   → GET /wday/cxs/{tenant}/{site}/job{externalPath}
              (derived from the human-facing URL, no config needed)
  eightfold → GET https://{tenant}.eightfold.ai/api/apply/v2/jobs/{id}?domain={domain}
              (tenant + domain read from companies.yaml via the adapter config)
  jobsdb    → POST https://hk.jobsdb.com/graphql   ← discovered 2026-06-04
              Query: { jobDetails(id: ID!) { job { content abstract } } }
              Returns full HTML description in the 'content' field.
              No Scrapling needed — plain httpx, ~100 ms per job.

Usage:
  python -m hk_jobs.pipeline --fetch-descriptions
  python -m hk_jobs.pipeline --fetch-descriptions --fetch-limit 20
"""

from __future__ import annotations

import logging
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import NamedTuple

import httpx

from hk_jobs.adapters.workday import _strip_html
from hk_jobs.config import load_companies

logger = logging.getLogger(__name__)

_MAX_WORKERS = 20   # all sources now use plain httpx — safe to go higher
_REQUEST_DELAY = 0.1

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

# JobsDB GraphQL
_JOBSDB_GQL_URL = "https://hk.jobsdb.com/graphql"
_JOBSDB_GQL_HEADERS = {
    **_HEADERS,
    "Content-Type": "application/json",
    "X-Seek-Site": "JobsDB",
    "X-Seek-Locale": "en-HK",
}
_JOBSDB_QUERY = '{ jobDetails(id: "%s") { job { id content abstract } } }'


class FetchResult(NamedTuple):
    source: str
    source_id: str
    raw_html: str | None
    clean_text: str | None
    skipped: bool = False


class DescriptionFetcher:
    """
    Calls ATS JSON detail APIs to populate description_raw / description_clean.
    """

    def __init__(self, db_path: str = "data/jobs.db", config_path: str | None = None) -> None:
        self.db_path = db_path
        # Build company_slug → adapter config map for Eightfold tenant/domain lookup
        self._ef_config: dict[str, dict] = {}
        try:
            for cfg in load_companies(config_path):
                if cfg.adapter == "eightfold":
                    self._ef_config[cfg.slug] = cfg.config
        except Exception as exc:
            logger.warning("Could not load companies.yaml for Eightfold config: %s", exc)

    # ── public API ────────────────────────────────────────────────────────────

    def run(self, limit: int | None = None) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            jobs = self._fetch_unenriched(conn, limit)
            if not jobs:
                logger.info("No jobs with empty descriptions — nothing to do")
                return

            by_source = {}
            for j in jobs:
                by_source.setdefault(j["source"], 0)
                by_source[j["source"]] += 1
            logger.info(
                "Fetching descriptions for %d jobs via JSON APIs (%d workers) — %s",
                len(jobs), _MAX_WORKERS,
                ", ".join(f"{s}:{n}" for s, n in sorted(by_source.items())),
            )

            results = self._fetch_parallel(jobs)
            self._write_results(conn, results)
        finally:
            conn.close()

    # ── helpers ───────────────────────────────────────────────────────────────

    def _fetch_unenriched(
        self, conn: sqlite3.Connection, limit: int | None
    ) -> list[sqlite3.Row]:
        sql = """
            SELECT source, source_id, company_slug, url
              FROM jobs
             WHERE is_active = 1
               AND (description_raw IS NULL OR description_raw = '')
             ORDER BY fetched_at DESC
        """
        if limit:
            sql += f" LIMIT {limit}"
        return conn.execute(sql).fetchall()

    def _fetch_parallel(self, jobs: list[sqlite3.Row]) -> list[FetchResult]:
        results: list[FetchResult] = []
        with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
            futures = {
                pool.submit(
                    self._fetch_single,
                    row["source"], row["source_id"], row["company_slug"], row["url"],
                ): row
                for row in jobs
            }
            for future in as_completed(futures):
                results.append(future.result())
        return results

    def _fetch_single(
        self, source: str, source_id: str, company_slug: str, url: str
    ) -> FetchResult:
        try:
            time.sleep(_REQUEST_DELAY)
            if source == "workday":
                raw_html = _fetch_workday_description(url)
            elif source == "eightfold":
                ef_cfg = self._ef_config.get(company_slug, {})
                tenant = ef_cfg.get("tenant", "hsbc")
                domain = ef_cfg.get("domain", "hsbc.com")
                raw_html = _fetch_eightfold_description(source_id, tenant, domain)
            elif source == "jobsdb":
                raw_html = _fetch_jobsdb_description(source_id)
            else:
                logger.warning("Unknown source '%s' — skipping %s", source, source_id)
                return FetchResult(source, source_id, None, None, skipped=True)

            if not raw_html:
                logger.warning("✗ %s/%s: empty description returned", source, source_id)
                return FetchResult(source, source_id, None, None)

            clean = _strip_html(raw_html)
            logger.info(
                "✓ %s/%s: %d chars raw, %d chars clean",
                source, source_id, len(raw_html), len(clean),
            )
            return FetchResult(source, source_id, raw_html, clean)

        except Exception as exc:
            logger.error("✗ %s/%s: %s", source, source_id, exc)
            return FetchResult(source, source_id, None, None)

    def _write_results(self, conn: sqlite3.Connection, results: list[FetchResult]) -> None:
        success = skipped = failed = 0
        with conn:
            for r in results:
                if r.skipped:
                    skipped += 1
                    continue
                if r.raw_html is None:
                    failed += 1
                    continue
                conn.execute(
                    """
                    UPDATE jobs
                       SET description_raw   = ?,
                           description_clean = ?
                     WHERE source = ? AND source_id = ?
                    """,
                    (r.raw_html, r.clean_text, r.source, r.source_id),
                )
                success += 1
        logger.info(
            "✅ Descriptions: %d written, %d skipped (no API), %d failed",
            success, skipped, failed,
        )


# ── ATS-specific fetchers ─────────────────────────────────────────────────────

def _fetch_workday_description(human_url: str) -> str | None:
    """
    Derive the Workday JSON detail API URL from the human-facing URL and fetch.

    Human URL:  https://{tenant}.{wd}.myworkdayjobs.com/en-US/{site}/job/{slug}
    API URL:    https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/job/{slug}
    """
    # Split on "/en-US/" to find the base and path
    m = re.match(
        r"(https://[^/]+\.myworkdayjobs\.com)/en-US/([^/]+)/job(/.*)",
        human_url,
    )
    if not m:
        raise ValueError(f"Cannot parse Workday URL: {human_url}")

    base, site, job_path = m.groups()
    tenant = base.split("//")[1].split(".")[0]
    api_url = f"{base}/wday/cxs/{tenant}/{site}/job{job_path}"

    with httpx.Client(timeout=15, headers=_HEADERS, follow_redirects=True) as client:
        resp = client.get(api_url)
        resp.raise_for_status()

    data = resp.json()
    info = data.get("jobPostingInfo", {})
    return info.get("jobDescription") or None


def _fetch_eightfold_description(
    position_id: str, tenant: str, domain: str
) -> str | None:
    """
    Call the Eightfold per-job detail API.

    GET https://{tenant}.eightfold.ai/api/apply/v2/jobs/{id}?domain={domain}
    Returns job_description as raw HTML (can be several KB).
    """
    url = f"https://{tenant}.eightfold.ai/api/apply/v2/jobs/{position_id}"
    with httpx.Client(timeout=15, headers=_HEADERS, follow_redirects=True) as client:
        resp = client.get(url, params={"domain": domain})
        resp.raise_for_status()

    return resp.json().get("job_description") or None


def _fetch_jobsdb_description(source_id: str) -> str | None:
    """
    Fetch full job description from JobsDB via their GraphQL API.

    Discovered 2026-06-04: hk.jobsdb.com/graphql accepts unauthenticated
    POST requests. The 'content' field contains the full HTML description
    (~1.5–2.5 KB per job). No Scrapling / Cloudflare bypass needed.

    Returns raw HTML string, or None if the job is not found / expired.
    """
    query = _JOBSDB_QUERY % source_id
    with httpx.Client(timeout=15, follow_redirects=True) as client:
        resp = client.post(
            _JOBSDB_GQL_URL,
            json={"query": query},
            headers=_JOBSDB_GQL_HEADERS,
        )
        resp.raise_for_status()

    data = resp.json()
    jd = (data.get("data") or {}).get("jobDetails") or {}
    job = jd.get("job") or {}
    # 'content' = full HTML description; 'abstract' = brief teaser (fallback)
    return job.get("content") or job.get("abstract") or None
