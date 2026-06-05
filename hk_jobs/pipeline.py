"""
Pipeline orchestrator.

Reads companies.yaml, instantiates the right adapter for each company,
fetches jobs, enriches them, upserts to the database, and soft-deletes
any jobs that disappeared from the source since the last run.

Usage:
    python -m hk_jobs.pipeline [options]
    python -m hk_jobs.pipeline --help
"""

from __future__ import annotations

import argparse
import concurrent.futures
import logging
import sys
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from threading import Lock

from hk_jobs.config import load_companies
from hk_jobs.enrich import enrich_all
from hk_jobs.storage import JobStore

logger = logging.getLogger(__name__)

# Maximum wall-clock seconds allowed per company. A company that hangs
# (e.g. a very slow server or an infinite pagination loop) will be killed
# and skipped so the other 29 companies still complete on schedule.
COMPANY_TIMEOUT_SECS = 1200  # 10 pages × 90 s/page + Cloudflare solve time


@dataclass
class CompanyResult:
    """One row in the end-of-run report."""

    name: str
    slug: str
    total_fetched: int = 0
    inserted: int = 0
    updated: int = 0
    deactivated: int = 0
    elapsed_secs: float = 0.0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def run(args: argparse.Namespace) -> list[CompanyResult]:
    """
    Execute the full scrape-enrich-store pipeline.

    Returns the list of per-company results so callers (and tests) can
    inspect outcomes without having to re-read the database.
    """
    dry_run: bool = getattr(args, "dry_run", False)

    companies = load_companies(args.config)

    raw_filter = getattr(args, "company", None)
    if raw_filter:
        # Accept either a single slug (str) or a list of slugs (from action='append')
        slugs = set(raw_filter) if isinstance(raw_filter, list) else {raw_filter}
        companies = [c for c in companies if c.slug in slugs]
        if not companies:
            sys.exit(f"No enabled companies matching {sorted(slugs)} in companies.yaml")

    # In dry-run mode use an in-memory DB so JobStore / stats still work
    # internally but nothing is written to disk.
    db_path = ":memory:" if dry_run else args.db
    if not dry_run:
        Path(args.db).parent.mkdir(parents=True, exist_ok=True)

    if dry_run:
        logger.info("DRY RUN — adapters will run but nothing will be written to disk.")

    results: list[CompanyResult] = []

    # Company-level parallelism.
    # Each worker runs one company's full scrape (both listing pages + DB write).
    # Eightfold/Workday: ~1 min each.  JobsDB/Scrapling: ~3 min each (browser/page).
    # With 10 workers and 21 JobsDB companies: ceil(21/10)×3 min ≈ 9 min total.
    # Hard cap: >15 workers stacks too many Scrapling browser instances (~300 MB RAM each)
    # and risks Cloudflare rate-limiting on JobsDB.
    DEFAULT_WORKERS = 10
    _requested = getattr(args, "parallel_workers", None) or DEFAULT_WORKERS
    if _requested > 15:
        logger.warning(
            "--parallel-workers %d exceeds safe limit for Scrapling (each browser ~300 MB RAM). "
            "Capping at 15 to avoid memory exhaustion and Cloudflare bans.",
            _requested,
        )
        _requested = 15
    n_workers = _requested
    logger.info("Pipeline running with %d parallel company workers", n_workers)

    with JobStore(db_path) as store:
        run_time = datetime.now(UTC)
        db_lock  = Lock()  # SQLite doesn't allow concurrent writes

        def _run_locked(cfg):
            result = _run_company(cfg, store, run_time, args, db_lock=db_lock)
            return result

        with concurrent.futures.ThreadPoolExecutor(max_workers=n_workers) as pool:
            futures = {pool.submit(_run_locked, cfg): cfg for cfg in companies}
            for future in concurrent.futures.as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as exc:
                    cfg = futures[future]
                    logger.error("%s: unexpected error: %s", cfg.name, exc)
                    results.append(CompanyResult(cfg.name, cfg.slug, error=str(exc)))

        if not dry_run and getattr(args, "export", None):
            count = store.export_active_jsonl(args.export)
            logger.info("Exported %d active jobs → %s", count, args.export)

        _print_report(results, store, dry_run=dry_run)

    # Record a daily snapshot into job_history / company_metrics.
    # Skipped in dry-run mode because dry-run uses an in-memory DB and
    # intentionally writes nothing to disk.
    if not dry_run:
        from hk_jobs.analytics import record_scrape_snapshot
        record_scrape_snapshot(args.db, results, date.today())
        _log_trend_changes(results, args.db)

    return results


def _run_company(cfg, store: JobStore, run_time: datetime, args, db_lock=None) -> CompanyResult:
    """
    Fetch, enrich, and store jobs for one company. Returns a CompanyResult.

    db_lock: optional threading.Lock that serialises SQLite writes when
    multiple companies run concurrently via ThreadPoolExecutor.
    """
    t0 = time.monotonic()
    adapter = cfg.build_adapter()

    # Fetch jobs (network-bound; runs without the db_lock so other companies
    # can write to the DB while this one is still fetching).
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(adapter.fetch_jobs)
        try:
            jobs = future.result(timeout=COMPANY_TIMEOUT_SECS)
        except concurrent.futures.TimeoutError:
            logger.error(
                "%s: timed out after %d s — skipping. "
                "Consider increasing COMPANY_TIMEOUT_SECS or setting enabled: false.",
                cfg.name, COMPANY_TIMEOUT_SECS,
            )
            return CompanyResult(
                cfg.name, cfg.slug,
                elapsed_secs=time.monotonic() - t0,
                error=f"timeout after {COMPANY_TIMEOUT_SECS}s",
            )
        except Exception as exc:
            logger.error("%s: adapter raised %s: %s", cfg.name, type(exc).__name__, exc)
            return CompanyResult(
                cfg.name, cfg.slug,
                elapsed_secs=time.monotonic() - t0,
                error=f"{type(exc).__name__}: {exc}",
            )

    jobs = [job.model_copy(update={"fetched_at": run_time}) for job in jobs]

    if not getattr(args, "no_enrich", False):
        jobs = enrich_all(jobs)

    if getattr(args, "verbose", False) and jobs:
        for job in jobs:
            logger.debug(
                "  [%s]  %-55s  %s",
                job.source_id,
                job.title[:55],
                ", ".join(job.locations) or "—",
            )

    dry_run: bool = getattr(args, "dry_run", False)

    # Serialise all DB writes so concurrent threads don't corrupt SQLite.
    _lock = db_lock or _NullLock()
    with _lock:
        if dry_run:
            inserted, _ = store.upsert_many(jobs)
            elapsed = time.monotonic() - t0
            if not jobs:
                logger.warning("%s: returned 0 jobs (dry run)", cfg.name)
            else:
                logger.info("%s: %d jobs fetched — DRY RUN, not persisted", cfg.name, len(jobs))
            return CompanyResult(cfg.name, cfg.slug, len(jobs), inserted, 0, 0, elapsed)

        inserted, updated = store.upsert_many(jobs)
        deactivated = store.mark_inactive_for_run(cfg.slug, run_time)
    elapsed = time.monotonic() - t0

    if not jobs:
        logger.warning(
            "%s: returned 0 jobs — check config. "
            "Wrong tenant/slug? ATS URL changed? Anti-bot block? "
            "Run scripts/try_*_live.py to diagnose.",
            cfg.name,
        )
    else:
        logger.info(
            "%s: %d jobs (%d new, %d updated, %d deactivated) in %.1fs",
            cfg.name, len(jobs), inserted, updated, deactivated, elapsed,
        )

    return CompanyResult(cfg.name, cfg.slug, len(jobs), inserted, updated, deactivated, elapsed)


class _NullLock:
    """Drop-in for threading.Lock when no concurrency is needed."""
    def __enter__(self): return self
    def __exit__(self, *_): pass


def _print_report(
    results: list[CompanyResult],
    store: JobStore,
    *,
    dry_run: bool = False,
) -> None:
    """Print a concise end-of-run summary to stdout."""
    total_fetched = sum(r.total_fetched for r in results)
    total_new = sum(r.inserted for r in results)
    total_updated = sum(r.updated for r in results)
    zero_ok = [r for r in results if r.ok and r.total_fetched == 0]
    errors = [r for r in results if not r.ok]

    stats = store.stats()
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    print()
    print("=" * 62)
    if dry_run:
        print(f"  DRY RUN  {timestamp}  (nothing written to disk)")
    else:
        print(f"  RUN COMPLETE  {timestamp}")
    print("=" * 62)
    print(f"  Companies run  : {len(results)}")
    if dry_run:
        print(f"  Jobs fetched   : {total_fetched:,}  ({total_new:,} would be new)")
    else:
        new_updated = f"{total_new:,} new, {total_updated:,} updated"
        print(f"  Jobs fetched   : {total_fetched:,}  ({new_updated})")
        print(f"  Active in DB   : {stats['active']:,} / {stats['total']:,} total")

    if zero_ok:
        print()
        print(f"  ⚠  {len(zero_ok)} companies returned 0 jobs — check config:")
        for r in zero_ok:
            print(f"       {r.name}  ({r.slug})")

    if errors:
        print()
        print(f"  ✗  {len(errors)} companies failed:")
        for r in errors:
            print(f"       {r.name}: {r.error}")

    print("=" * 62)
    print()


def _log_trend_changes(results: list[CompanyResult], db_path: str) -> None:
    """Log companies whose trend changed significantly after the snapshot was recorded."""
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        today = date.today().isoformat()
        rows = conn.execute(
            """SELECT company_name, trend_direction, trend_percent, jobs_added, jobs_removed
               FROM job_history WHERE scraped_date = ?
               AND trend_direction IN ('growing', 'declining')
               ORDER BY ABS(trend_percent) DESC""",
            (today,),
        ).fetchall()
        for r in rows:
            direction = "↑" if r["trend_direction"] == "growing" else "↓"
            logger.info(
                "Trend %s %s: %s%+.1f%% (%+d jobs)",
                direction, r["company_name"], "",
                r["trend_percent"], r["jobs_added"] - r["jobs_removed"],
            )
    finally:
        conn.close()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="python -m hk_jobs.pipeline",
        description="Scrape HK financial job postings and store them in SQLite.",
    )
    p.add_argument(
        "--db",
        default="data/jobs.db",
        metavar="PATH",
        help="SQLite database path (default: data/jobs.db)",
    )
    p.add_argument(
        "--export",
        metavar="PATH",
        help="Export active jobs to JSONL after the run (e.g. data/jobs.jsonl)",
    )
    p.add_argument(
        "--only", "--company",
        dest="company",
        metavar="SLUG",
        action="append",
        help=(
            "Run only this company slug. Repeat to run several: "
            "--only aia-hk --only blackrock-hk"
        ),
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Fetch and enrich jobs but do NOT write to the database. "
            "Useful for verifying a new adapter config without touching stored data."
        ),
    )
    p.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Print each fetched job (title, location, source_id). Implies DEBUG logging.",
    )
    p.add_argument(
        "--no-enrich",
        action="store_true",
        help="Skip the rule-based enrichment step (faster, but seniority/skills won't be set)",
    )
    p.add_argument(
        "--config",
        metavar="PATH",
        default=None,
        help="Override the default companies.yaml path",
    )
    p.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO)",
    )
    p.add_argument(
        "--notify-summary",
        dest="notify_summary",
        action="store_true",
        help="Send daily summary email after run (requires SMTP_USER/SMTP_PASS env vars).",
    )
    p.add_argument(
        "--backup",
        action="store_true",
        help="Backup jobs.db to data/backups/jobs_YYYY-MM-DD.db with 30-day retention.",
    )
    p.add_argument(
        "--incremental",
        action="store_true",
        help=(
            "Only process jobs whose fetched_at is today (i.e. found in today's scrape). "
            "Makes --fetch-descriptions and --enrich much faster on routine daily runs — "
            "skips all existing jobs, processes only newly discovered ones."
        ),
    )
    p.add_argument(
        "--parallel-workers",
        dest="parallel_workers",
        type=int,
        metavar="N",
        default=10,
        help=(
            "Number of companies to scrape in parallel (default: 10). "
            "Each JobsDB worker launches a Scrapling browser (~300 MB RAM). "
            "Values above 15 are capped automatically to prevent memory exhaustion "
            "and Cloudflare rate-limiting."
        ),
    )
    p.add_argument(
        "--fetch-descriptions",
        dest="fetch_descriptions",
        action="store_true",
        help=(
            "Fetch full job description HTML from each job's detail page and store "
            "in description_raw / description_clean. Skips JobsDB jobs (Cloudflare). "
            "Use --fetch-limit to cap the number of requests."
        ),
    )
    p.add_argument(
        "--fetch-limit",
        dest="fetch_limit",
        type=int,
        metavar="N",
        help="Max number of descriptions to fetch (default: all).",
    )
    p.add_argument(
        "--enrich",
        action="store_true",
        help=(
            "Run Phase 12 LLM enrichment: send unenriched jobs to DeepSeek and "
            "store structured results in job_enrichments. Requires DEEPSEEK_API_KEY env var."
        ),
    )
    p.add_argument(
        "--enrich-limit",
        dest="enrich_limit",
        type=int,
        metavar="N",
        help="Max number of jobs to enrich in this run (useful for testing).",
    )
    p.add_argument(
        "--report",
        choices=["trends", "velocity"],
        metavar="{trends,velocity}",
        help=(
            "Print an analytics report without running the scrapers. "
            "'trends' shows per-company 7/30d averages; "
            "'velocity' ranks companies by hiring growth rate."
        ),
    )
    p.add_argument(
        "--export-trends",
        dest="export_trends",
        metavar="PATH",
        help="Export the latest trend snapshot for every company to a JSONL file.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    # --verbose implies DEBUG regardless of --log-level
    if args.verbose:
        args.log_level = "DEBUG"
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )
    if args.verbose:
        # httpcore/httpx emit a log line for every TCP event at DEBUG level —
        # that noise drowns the per-job output we actually want to see.
        for noisy in ("httpcore", "httpx", "hpack", "h11"):
            logging.getLogger(noisy).setLevel(logging.WARNING)

    # Ensure phase 11 + 12 tables exist on every real-DB run (idempotent).
    if not getattr(args, "dry_run", False):
        from hk_jobs.migrations import migrate_to_phase_11, migrate_to_phase_12
        Path(args.db).parent.mkdir(parents=True, exist_ok=True)
        migrate_to_phase_11(args.db)
        migrate_to_phase_12(args.db)

    # --notify-summary: send daily summary email (no scraping).
    if getattr(args, "notify_summary", False):
        from hk_jobs.notifications import send_daily_summary
        send_daily_summary(db_path=args.db)
        return

    # --backup: create a dated copy of jobs.db, prune old backups.
    if getattr(args, "backup", False):
        from hk_jobs.backup import backup_database
        backup_database(db_path=args.db)
        return

    # --report / --export-trends: analytics-only mode, no scraping.
    if args.report or getattr(args, "export_trends", None):
        from hk_jobs import analytics
        if args.report == "trends":
            analytics.print_trends_report(args.db)
        elif args.report == "velocity":
            analytics.print_velocity_report(args.db)
        if getattr(args, "export_trends", None):
            count = analytics.export_trends_jsonl(args.db, args.export_trends)
            logger.info("Exported %d trend records → %s", count, args.export_trends)
        return

    # --enrich: LLM enrichment pass, no scraping.
    if getattr(args, "enrich", False):
        from hk_jobs.enrichment import EnrichmentPipeline
        EnrichmentPipeline(db_path=args.db).run(
            limit=getattr(args, "enrich_limit", None),
            incremental=getattr(args, "incremental", False),
        )
        return

    # --fetch-descriptions: pull full description text from detail pages.
    if getattr(args, "fetch_descriptions", False):
        from hk_jobs.description_fetcher import DescriptionFetcher
        DescriptionFetcher(db_path=args.db).run(
            limit=getattr(args, "fetch_limit", None),
            incremental=getattr(args, "incremental", False),
        )
        return

    _start = time.monotonic()
    try:
        run(args)
    except Exception as exc:
        if not getattr(args, "dry_run", False):
            try:
                from hk_jobs.notifications import send_failure_alert
                send_failure_alert(
                    phase="Pipeline",
                    error=str(exc),
                    duration_seconds=int(time.monotonic() - _start),
                )
            except Exception:
                pass
        raise


if __name__ == "__main__":
    main()
