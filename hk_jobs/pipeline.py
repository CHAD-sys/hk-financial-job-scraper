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

from hk_jobs.config import load_companies
from hk_jobs.enrich import enrich_all
from hk_jobs.storage import JobStore

logger = logging.getLogger(__name__)

# Maximum wall-clock seconds allowed per company. A company that hangs
# (e.g. a very slow server or an infinite pagination loop) will be killed
# and skipped so the other 29 companies still complete on schedule.
COMPANY_TIMEOUT_SECS = 600  # JobsDB/Scrapling takes ~90 s/page; 2 pages + buffer fits here


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

    with JobStore(db_path) as store:
        run_time = datetime.now(UTC)

        for cfg in companies:
            result = _run_company(cfg, store, run_time, args)
            results.append(result)

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


def _run_company(cfg, store: JobStore, run_time: datetime, args) -> CompanyResult:
    """Fetch, enrich, and store jobs for one company. Returns a CompanyResult."""
    t0 = time.monotonic()
    adapter = cfg.build_adapter()

    # Run the adapter in a thread so we can enforce a wall-clock timeout.
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

    # Stamp every job with the run's start time so mark_inactive_for_run can
    # reliably distinguish "seen this run" (fetched_at == run_time) from "seen
    # a previous run" (fetched_at < run_time).  Without this, tiny clock skew
    # between job construction and run_time capture could mis-classify fresh
    # jobs as stale and immediately deactivate them.
    jobs = [job.model_copy(update={"fetched_at": run_time}) for job in jobs]

    if not getattr(args, "no_enrich", False):
        jobs = enrich_all(jobs)

    # --verbose: log each job title so the user can eyeball the results live
    if getattr(args, "verbose", False) and jobs:
        for job in jobs:
            logger.debug(
                "  [%s]  %-55s  %s",
                job.source_id,
                job.title[:55],
                ", ".join(job.locations) or "—",
            )

    dry_run: bool = getattr(args, "dry_run", False)

    if dry_run:
        # Upsert into the in-memory store so inserted/updated counts are accurate,
        # but skip mark_inactive_for_run (no "previous run" to diff against).
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

    # Ensure phase-11 tables exist on every real-DB run (idempotent).
    if not getattr(args, "dry_run", False):
        from hk_jobs.migrations import migrate_to_phase_11
        Path(args.db).parent.mkdir(parents=True, exist_ok=True)
        migrate_to_phase_11(args.db)

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

    run(args)


if __name__ == "__main__":
    main()
