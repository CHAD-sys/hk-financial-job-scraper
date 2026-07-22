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
  indeed    → NOT fetched (removed 2026-07-19). Indeed's Cloudflare turnstile
              started demanding repeated interactive solves per job and stalled
              the whole step for hours at near-zero throughput. Indeed rows keep
              their listing data only — description_raw/clean stay empty, same
              as CLAUDE.md's original "listing-only" design for this source.

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

_MAX_WORKERS = 3    # conservative for JobsDB GraphQL rate limits; bump to 10 when not throttled
_REQUEST_DELAY = 1.0
_WRITE_BATCH = 200  # commit to the DB every N fetched jobs so progress survives a kill/crash
_HTTP_TIMEOUT = 15.0  # hard per-request timeout (s); a single hung request can never freeze the run

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
# Include advertiser.name alongside the description so we can repair company
# names for rows that were mislabeled when the scraper assigned self.company
# to all cards regardless of who actually posted them (Fix A, Phase 13).
_JOBSDB_QUERY = '{ jobDetails(id: "%s") { job { id content abstract advertiser { name } } } }'

# Lightweight query used by --repair-companies: fetches only the advertiser
# name without the full description content (~95% fewer bytes per request).
_JOBSDB_ADVERTISER_QUERY = '{ jobDetails(id: "%s") { job { id advertiser { name } } } }'


class FetchResult(NamedTuple):
    source: str
    source_id: str
    raw_html: str | None
    clean_text: str | None
    skipped: bool = False
    advertiser_name: str | None = None   # populated for jobsdb source (Phase 13)


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

    def run(self, limit: int | None = None, incremental: bool = False,
            repair_companies: bool = False, sources: set[str] | None = None,
            max_workers: int | None = None) -> None:
        if repair_companies:
            self._run_company_repair(limit)
            return

        # timeout=60 + busy_timeout so two description runs (e.g. linkedin via httpx
        # and indeed via headless browser) can write to the same DB concurrently
        # without hitting "database is locked".
        conn = sqlite3.connect(self.db_path, timeout=60)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=60000")
        try:
            jobs = self._fetch_unenriched(conn, limit, incremental=incremental, sources=sources)
            if not jobs:
                logger.info("No jobs with empty descriptions — nothing to do")
                return

            by_source = {}
            for j in jobs:
                by_source.setdefault(j["source"], 0)
                by_source[j["source"]] += 1
            workers = max_workers or _MAX_WORKERS
            mode = "incremental (today's new jobs only)" if incremental else "full"
            logger.info(
                "Fetching descriptions for %d jobs [%s] (%d workers) — %s",
                len(jobs), mode, workers,
                ", ".join(f"{s}:{n}" for s, n in sorted(by_source.items())),
            )

            # Fetch + commit in batches so progress is durable: if the process is
            # killed or crashes mid-run, everything already committed stays written
            # (previously results were only persisted once, at the very end).
            total = len(jobs)
            written = skipped = failed = 0
            for start in range(0, total, _WRITE_BATCH):
                batch = jobs[start:start + _WRITE_BATCH]
                results = self._fetch_parallel(batch, max_workers=workers)
                s, sk, f = self._write_results(conn, results)
                written += s
                skipped += sk
                failed += f
                logger.info(
                    "descriptions: committed batch, total %d/%d written so far (%d skipped, %d failed)",
                    written, total, skipped, failed,
                )

            logger.info(
                "✅ Descriptions complete: %d written, %d skipped (no API), %d failed (of %d)",
                written, skipped, failed, total,
            )
        finally:
            conn.close()

    # ── helpers ───────────────────────────────────────────────────────────────

    def _fetch_unenriched(
        self, conn: sqlite3.Connection, limit: int | None, incremental: bool = False,
        sources: set[str] | None = None,
    ) -> list[sqlite3.Row]:
        today_filter = "AND DATE(fetched_at) = DATE('now')" if incremental else ""
        params: list = []
        source_filter = ""
        if sources:
            source_filter = "AND source IN (%s)" % ",".join("?" * len(sources))
            params = list(sources)
        sql = f"""
            SELECT source, source_id, company_slug, url
              FROM jobs
             WHERE is_active = 1
               AND (description_raw IS NULL OR description_raw = '')
               AND source != 'indeed'
               {source_filter}
               {today_filter}
             ORDER BY fetched_at DESC
        """
        if limit:
            sql += f" LIMIT {limit}"
        rows = conn.execute(sql, params).fetchall()
        if incremental:
            total = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE is_active=1 "
                "AND (description_raw IS NULL OR description_raw = '')"
            ).fetchone()[0]
            logger.info(
                "Incremental mode: %d new jobs to describe, skipping %d existing",
                len(rows), total - len(rows),
            )
        return rows

    def _fetch_parallel(self, jobs: list[sqlite3.Row],
                        max_workers: int | None = None) -> list[FetchResult]:
        results: list[FetchResult] = []
        with ThreadPoolExecutor(max_workers=max_workers or _MAX_WORKERS) as pool:
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
                return FetchResult(source, source_id, raw_html, _strip_html(raw_html) if raw_html else None)
            elif source == "eightfold":
                ef_cfg = self._ef_config.get(company_slug, {})
                tenant = ef_cfg.get("tenant", "hsbc")
                domain = ef_cfg.get("domain", "hsbc.com")
                raw_html = _fetch_eightfold_description(source_id, tenant, domain)
                return FetchResult(source, source_id, raw_html, _strip_html(raw_html) if raw_html else None)
            elif source == "jobsdb":
                raw_html, advertiser_name = _fetch_jobsdb_description(source_id)
                if not raw_html:
                    logger.warning("✗ %s/%s: empty description returned", source, source_id)
                    return FetchResult(source, source_id, None, None, advertiser_name=advertiser_name)
                clean = _strip_html(raw_html)
                logger.info(
                    "✓ %s/%s: %d chars raw, %d chars clean, advertiser=%r",
                    source, source_id, len(raw_html), len(clean), advertiser_name,
                )
                return FetchResult(source, source_id, raw_html, clean, advertiser_name=advertiser_name)
            elif source == "linkedin":
                raw_html = _fetch_linkedin_description(source_id)
                if raw_html:
                    logger.info("✓ %s/%s: %d chars", source, source_id, len(raw_html))
                clean = _strip_html(raw_html) if raw_html else None
                return FetchResult(source, source_id, raw_html, clean)
            elif source == "indeed":
                # Removed 2026-07-19: Indeed's Cloudflare turnstile started demanding
                # repeated interactive solves per job, stalling the whole description
                # step for hours with near-zero throughput. _fetch_unenriched() already
                # excludes 'indeed' at the query level so this branch shouldn't be
                # reached in normal operation — kept only as a defensive skip for any
                # direct caller. Indeed rows keep their listing data; description_raw
                # stays empty, matching CLAUDE.md's original "listing-only" design.
                return FetchResult(source, source_id, None, None, skipped=True)
            else:
                logger.warning("Unknown source '%s' — skipping %s", source, source_id)
                return FetchResult(source, source_id, None, None, skipped=True)

        except Exception as exc:
            logger.error("✗ %s/%s: %s", source, source_id, exc)
            return FetchResult(source, source_id, None, None)

    def _write_results(
        self, conn: sqlite3.Connection, results: list[FetchResult]
    ) -> tuple[int, int, int]:
        """Persist one batch of results. Returns (written, skipped, failed).

        Also updates the company column from advertiser_name when available
        (Phase 13 Fix A). COALESCE(NULLIF(...,''), jobs.company) means an
        empty/None advertiser_name leaves the existing company value intact.

        The ``with conn`` block commits this batch atomically, so each batch is
        durable the moment it returns — a later kill cannot undo it.
        """
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
                           description_clean = ?,
                           company           = COALESCE(NULLIF(?, ''), company)
                     WHERE source = ? AND source_id = ?
                    """,
                    (r.raw_html, r.clean_text, r.advertiser_name or "", r.source, r.source_id),
                )
                success += 1
        return success, skipped, failed

    # ── Company repair (Phase 13) ─────────────────────────────────────────────

    def _run_company_repair(self, limit: int | None = None) -> None:
        """
        Repair mislabeled company fields for existing JobsDB rows.

        Calls the lightweight GraphQL advertiser-only query for every active
        JobsDB job and updates company where the DB value differs from the
        authoritative advertiser.name.  Descriptions are NOT re-fetched —
        this is a pure metadata-correction pass.

        Designed for one-off use: after deploying Fix A, run
            python -m hk_jobs.pipeline --repair-companies
        to backfill all 2,356 existing rows.  Future scrapes will set the
        correct company on INSERT (via _card_to_job), so this only needs
        to run once per existing dataset.
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            sql = """
                SELECT source_id, company FROM jobs
                WHERE source = 'jobsdb' AND is_active = 1
                ORDER BY source_id
            """
            if limit:
                sql += f" LIMIT {limit}"
            rows = conn.execute(sql).fetchall()
            total = len(rows)
            logger.info("Company repair: checking %d JobsDB jobs", total)

            corrected = unchanged = failed = 0
            for row in rows:
                time.sleep(_REQUEST_DELAY)
                try:
                    _, advertiser_name = _fetch_jobsdb_description(
                        row["source_id"], query_override=_JOBSDB_ADVERTISER_QUERY
                    )
                except Exception as exc:
                    logger.warning("repair: %s — %s", row["source_id"], exc)
                    failed += 1
                    continue

                if not advertiser_name:
                    failed += 1
                    continue

                if advertiser_name != row["company"]:
                    with conn:
                        conn.execute(
                            "UPDATE jobs SET company = ? WHERE source = 'jobsdb' AND source_id = ?",
                            (advertiser_name, row["source_id"]),
                        )
                    logger.info(
                        "repair: %s  %r → %r",
                        row["source_id"], row["company"], advertiser_name,
                    )
                    corrected += 1
                else:
                    unchanged += 1

            logger.info(
                "✅ Company repair complete: %d corrected, %d unchanged, %d failed (of %d)",
                corrected, unchanged, failed, total,
            )
        finally:
            conn.close()


# ── ATS-specific fetchers ─────────────────────────────────────────────────────

# LinkedIn public guest job-detail endpoint. Returns an HTML fragment whose
# description lives in .show-more-less-html__markup (fallback .description__text).
# Plain httpx — no browser needed. Rate-limited (429), so we back off and retry.
_LINKEDIN_DETAIL_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{id}"


def _fetch_linkedin_description(source_id: str, max_retries: int = 4) -> str | None:
    """Fetch one LinkedIn job's description HTML via the guest jobPosting endpoint."""
    from selectolax.parser import HTMLParser

    url = _LINKEDIN_DETAIL_URL.format(id=source_id)
    for attempt in range(max_retries):
        wait = 2 ** (attempt + 1)   # 2, 4, 8, 16 s
        try:
            with httpx.Client(timeout=_HTTP_TIMEOUT, headers=_HEADERS,
                              follow_redirects=True) as client:
                resp = client.get(url)
        except httpx.HTTPError:
            time.sleep(wait)
            continue
        if resp.status_code in (429, 999, 503):   # rate-limited/blocked — back off
            time.sleep(wait)
            continue
        if resp.status_code != 200:
            return None
        tree = HTMLParser(resp.text)
        node = (tree.css_first("div.show-more-less-html__markup")
                or tree.css_first(".description__text"))
        return node.html if node else None
    return None


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


def _fetch_jobsdb_description(
    source_id: str,
    max_retries: int = 3,
    query_override: str | None = None,
) -> tuple[str | None, str | None]:
    """
    Fetch job description and advertiser name from JobsDB via their GraphQL API.

    Discovered 2026-06-04: hk.jobsdb.com/graphql accepts unauthenticated
    POST requests. The 'content' field contains the full HTML description
    (~1.5–2.5 KB per job). No Scrapling / Cloudflare bypass needed.

    Phase 13: the query now also requests advertiser.name so the caller can
    correct the company field for rows that were mislabeled by the scraper.
    Pass query_override=_JOBSDB_ADVERTISER_QUERY to fetch only the name
    (used by --repair-companies, avoids downloading descriptions again).

    Resilience (so one job can never freeze the whole run):
      - hard per-request timeout of _HTTP_TIMEOUT seconds on every call;
      - bounded exponential backoff (2 s, 4 s, 8 s) on HTTP 429 *and* on
        network/timeout errors;
      - after max_retries, give up on this job and return (None, None).

    Returns (raw_html | None, advertiser_name | None).
    """
    query = (query_override or _JOBSDB_QUERY) % source_id
    for attempt in range(max_retries):
        wait = 2 ** (attempt + 1)   # 2 s, 4 s, 8 s
        try:
            with httpx.Client(timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
                resp = client.post(
                    _JOBSDB_GQL_URL,
                    json={"query": query},
                    headers=_JOBSDB_GQL_HEADERS,
                )
        except httpx.HTTPError as exc:
            # Timeout, connection reset, DNS hiccup, etc. — transient; back off.
            logger.warning(
                "jobsdb/%s request error (%s) — retry %d/%d in %ds",
                source_id, type(exc).__name__, attempt + 1, max_retries, wait,
            )
            time.sleep(wait)
            continue

        if resp.status_code == 429:
            logger.warning(
                "429 for jobsdb/%s — retry %d/%d in %ds",
                source_id, attempt + 1, max_retries, wait,
            )
            time.sleep(wait)
            continue

        resp.raise_for_status()
        data = resp.json()
        jd = (data.get("data") or {}).get("jobDetails") or {}
        job = jd.get("job") or {}
        content = job.get("content") or job.get("abstract") or None
        advertiser_name = (job.get("advertiser") or {}).get("name") or None
        return content, advertiser_name

    logger.warning("jobsdb/%s: giving up after %d retries", source_id, max_retries)
    return None, None
