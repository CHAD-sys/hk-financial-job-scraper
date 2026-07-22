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
import random
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

# Gap between sequential retries in the end-of-run retry pass only (not the main
# scrape, which runs at full speed). Spacing out re-attempts of a company that
# just returned 0 avoids hammering a source that's momentarily failing.
COMPANY_DELAY_MIN = 2.0
COMPANY_DELAY_MAX = 5.0


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

    # Merge the Longtail track (LLM-extraction boutique companies) from
    # companies_longtail.yaml so its entries route to LongtailAdapter in the same
    # run. --longtail-only isolates just this track for testing.
    _longtail_yaml = Path(__file__).parent / "companies_longtail.yaml"
    if _longtail_yaml.exists() and not getattr(args, "no_longtail", False):
        companies += load_companies(_longtail_yaml)
    if getattr(args, "longtail_only", False):
        companies = [c for c in companies if c.adapter == "longtail"]

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
    # Default 10: the original working value. The slow scraping was caused by the
    # network_idle=True hang in the adapter (since fixed), not concurrency, so the
    # earlier drop to 5 + inter-company/page delays was unnecessary throttling.
    # Hard cap: >15 workers stacks too many Scrapling browser instances (~300 MB RAM each).
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

        # Retry pass: companies that returned 0 jobs are almost always transient
        # Cloudflare blocks or network blips, not genuinely empty. Retry them once
        # — sequentially and slowly (one browser at a time) so we don't recreate
        # the synchronised burst that got us blocked in the first place. The
        # data-protection guard already kept each company's existing jobs, so this
        # only adds today's listings back if the retry succeeds.
        if not dry_run and getattr(args, "retry_failed", False):
            results = _retry_failed_companies(results, companies, store, run_time, args, db_lock)

        # Cross-source reconciliation: now that every source's jobs are stored,
        # detect vacancies posted on more than one board (same dedup_hash) and
        # point their apply_url at the preferred source (eFinancialCareers first).
        if not dry_run:
            with db_lock:
                x_groups, x_rows = store.reconcile_cross_posted()
            if x_groups:
                logger.info(
                    "Cross-source: %d vacancies found on multiple boards — "
                    "apply_url set to preferred source (%d rows updated).",
                    x_groups, x_rows,
                )

        # Finance-only guard: soft-delete hard tech/IT roles (software/DevOps/data/
        # cyber/etc.) so they never pollute the board. Uses a persistent title→verdict
        # cache, so each run only classifies NEW titles via DeepSeek (cheap), and
        # cached verdicts are enforced even with no API key. Opt out with --no-tech-filter.
        if not dry_run and not getattr(args, "no_tech_filter", False):
            try:
                from hk_jobs.tech_filter import run_tech_filter
                with db_lock:
                    _classified, _removed = run_tech_filter(args.db)
            except Exception as exc:  # never let the guard break a run
                logger.warning("tech-filter step failed (%s) — skipping", exc)

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

    # Per-company tier/category override. Some firms are conceptually BOUTIQUE even
    # though scraped via a mainstream adapter (e.g. a boutique that only posts on
    # JobsDB or LinkedIn). If the config sets source_tier/category, stamp them on
    # every job so those firms stay grouped as boutique regardless of source.
    _override = {}
    if cfg.config.get("source_tier"):
        _override["source_tier"] = cfg.config["source_tier"]
    if cfg.config.get("category"):
        _override["category"] = cfg.config["category"]
    if _override:
        jobs = [job.model_copy(update=_override) for job in jobs]

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
        # Scope soft-delete to this run's source so a company scraped from two
        # sources under one slug (e.g. a JobsDB entry AND an eFinancialCareers
        # entry both slug 'aia-hk') doesn't deactivate the other source's rows.
        deactivated = store.mark_inactive_for_run(
            cfg.slug, run_time, new_job_count=len(jobs),
            source=getattr(adapter, "source_name", None),
        )
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


def _retry_failed_companies(
    results: list[CompanyResult],
    companies: list,
    store: JobStore,
    run_time: datetime,
    args,
    db_lock,
) -> list[CompanyResult]:
    """
    Retry companies that returned 0 jobs, one at a time with a delay.

    A company that fetched 0 jobs is almost always a transient block (Cloudflare)
    or a network blip rather than a genuinely empty employer, so it's worth one
    more try. We do this sequentially — a single browser at a time, with a short
    random gap between companies — precisely so we don't recreate the parallel
    burst that caused the blocks. Successful retries are swapped into the results;
    companies that still come back empty keep their (protected) existing jobs.
    """
    failed = [r for r in results if r.total_fetched == 0]
    if not failed:
        return results

    slug_to_cfg = {c.slug: c for c in companies}
    logger.info(
        "Retry pass: %d companies returned 0 jobs, retrying one at a time: %s",
        len(failed), ", ".join(r.slug for r in failed),
    )

    by_slug = {r.slug: r for r in results}
    for r in failed:
        cfg = slug_to_cfg.get(r.slug)
        if cfg is None:
            continue
        time.sleep(random.uniform(COMPANY_DELAY_MIN, COMPANY_DELAY_MAX))
        retry = _run_company(cfg, store, run_time, args, db_lock=db_lock)
        if retry.total_fetched > 0:
            logger.info("Retry succeeded for %s: %d jobs", cfg.name, retry.total_fetched)
            by_slug[r.slug] = retry
        else:
            logger.warning("Retry still failed for %s (0 jobs)", cfg.name)

    return list(by_slug.values())


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
        "--longtail-only",
        dest="longtail_only",
        action="store_true",
        help="Run only the Longtail (LLM-extraction) boutique companies for isolated testing.",
    )
    p.add_argument(
        "--no-longtail",
        dest="no_longtail",
        action="store_true",
        help="Skip the Longtail track — run only the mainstream companies.yaml companies.",
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
        "--no-tech-filter",
        action="store_true",
        help="Skip the finance-only guard that soft-deletes hard tech/IT roles each run.",
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
        "--weekly-report",
        dest="weekly_report",
        action="store_true",
        help="Send weekly trend report email (run every Monday via cron).",
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
            "Values above 15 are capped automatically to avoid memory exhaustion."
        ),
    )
    p.add_argument(
        "--no-retry",
        dest="retry_failed",
        action="store_false",
        default=True,
        help=(
            "Disable the end-of-run retry pass. By default, companies that return "
            "0 jobs (usually a transient Cloudflare block) are retried once, "
            "sequentially and slowly, before the run finishes."
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
        "--re-enrich",
        dest="re_enrich",
        action="store_true",
        help=(
            "Re-enrich ALL active jobs, not just those missing an enrichment row. "
            "Use after changing the enrichment prompt (e.g. new salary-estimate fields) "
            "so every existing job is reprocessed. Upserts via ON CONFLICT."
        ),
    )
    p.add_argument(
        "--enrich-boutique",
        dest="enrich_boutique",
        action="store_true",
        help=(
            "Re-enrich only the boutique/\"Exclusive\" jobs (those with a category set). "
            "Reprocesses existing rows so the v4 translation prompt reaches the many "
            "Chinese-language boutique postings. Implies --enrich; upserts via ON CONFLICT."
        ),
    )
    p.add_argument(
        "--audit-salaries",
        dest="audit_salaries",
        action="store_true",
        help=(
            "Run the salary outlier audit agent (hk_jobs.salary_audit): re-judges the "
            "estimates most likely to be wrong (>=120k, cluster outliers, ambiguous "
            "'Team Head'-style titles), auto-applies DOWNWARD corrections with an audit "
            "log, and reports upward suggestions for review. Requires DEEPSEEK_API_KEY."
        ),
    )
    p.add_argument(
        "--audit-limit",
        dest="audit_limit",
        type=int,
        default=None,
        help="Max number of flagged jobs the salary audit reviews in this run.",
    )
    p.add_argument(
        "--audit-full",
        dest="audit_full",
        action="store_true",
        help=(
            "Review every active priced job, not just heuristic-flagged outliers. "
            "Only sensible while the dataset is small enough to make a full LLM pass "
            "affordable — use --audit-limit to cap cost/time if needed."
        ),
    )
    p.add_argument(
        "--repair-companies",
        dest="repair_companies",
        action="store_true",
        help=(
            "Phase 13 Fix A backfill: query JobsDB GraphQL for each active JobsDB job "
            "and update the company column from the authoritative advertiser.name field. "
            "Fixes rows that were mislabeled before the card-extraction fix was deployed. "
            "No descriptions are re-fetched — this is a metadata-only correction pass. "
            "Use --fetch-limit to process a subset for testing."
        ),
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
    p.add_argument(
        "--fetch-posts",
        dest="fetch_posts",
        action="store_true",
        help=(
            "LP-2 'Secret Market' pipeline: poll recruiters.yaml watchlist for new "
            "LinkedIn posts via Apify (raw ingestion only — no jobs/PocketBase yet, "
            "see docs/PLAN_LINKEDIN_POSTS.md). Requires APIFY_API_TOKEN. "
            "Self-enforces the $30/mo budget cap (hk_jobs.posts.budget)."
        ),
    )
    p.add_argument(
        "--posts-discovery",
        dest="posts_discovery",
        action="store_true",
        help=(
            "LP-2 weekly discovery search: keyword search for new job-bearing posts "
            "(hk_jobs.posts.fetcher.DEFAULT_DISCOVERY_QUERIES). Independent of "
            "--fetch-posts — run on a weekly cadence, not daily. Requires APIFY_API_TOKEN."
        ),
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

    # Ensure phase 11–13 tables/columns exist on every real-DB run (idempotent).
    if not getattr(args, "dry_run", False):
        from hk_jobs.migrations import (
            migrate_to_phase_11,
            migrate_to_phase_12,
            migrate_to_phase_13,
            migrate_to_phase_14,
            migrate_to_phase_15,
            migrate_to_phase_16,
            migrate_to_phase_17,
            migrate_to_phase_18,
            migrate_to_phase_19,
            migrate_to_phase_20,
            migrate_to_phase_21,
            migrate_to_phase_22,
            migrate_to_phase_23,
            migrate_to_phase_24,
            migrate_to_phase_25,
            migrate_to_phase_26,
        )
        Path(args.db).parent.mkdir(parents=True, exist_ok=True)
        migrate_to_phase_11(args.db)
        migrate_to_phase_12(args.db)
        migrate_to_phase_13(args.db)
        migrate_to_phase_14(args.db)
        migrate_to_phase_15(args.db)
        migrate_to_phase_16(args.db)
        migrate_to_phase_17(args.db)
        migrate_to_phase_18(args.db)
        migrate_to_phase_19(args.db)
        migrate_to_phase_20(args.db)
        migrate_to_phase_21(args.db)
        migrate_to_phase_22(args.db)
        migrate_to_phase_23(args.db)
        migrate_to_phase_24(args.db)
        migrate_to_phase_25(args.db)
        migrate_to_phase_26(args.db)

    # --weekly-report: send Monday trend report email (no scraping).
    if getattr(args, "weekly_report", False):
        from hk_jobs.reports.weekly import generate_weekly_report
        generate_weekly_report(db_path=args.db)
        return

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

    # --enrich / --enrich-boutique: LLM enrichment pass, no scraping.
    if getattr(args, "enrich", False) or getattr(args, "enrich_boutique", False):
        from hk_jobs.enrichment import EnrichmentPipeline
        EnrichmentPipeline(db_path=args.db).run(
            limit=getattr(args, "enrich_limit", None),
            incremental=getattr(args, "incremental", False),
            re_enrich=getattr(args, "re_enrich", False),
            boutique_only=getattr(args, "enrich_boutique", False),
        )
        return

    # --audit-salaries: outlier audit agent pass, no scraping.
    if getattr(args, "audit_salaries", False):
        from hk_jobs.migrations import migrate_to_phase_24
        from hk_jobs.salary_audit import run_audit
        migrate_to_phase_24(args.db)
        run_audit(args.db, limit=getattr(args, "audit_limit", None),
                  full=getattr(args, "audit_full", False))
        return

    # --fetch-descriptions: pull full description text from detail pages.
    if getattr(args, "fetch_descriptions", False):
        from hk_jobs.description_fetcher import DescriptionFetcher
        DescriptionFetcher(db_path=args.db).run(
            limit=getattr(args, "fetch_limit", None),
            incremental=getattr(args, "incremental", False),
        )
        return

    # --fetch-posts: LP-2 watchlist poll, raw ingestion only. No scraping.
    if getattr(args, "fetch_posts", False):
        from hk_jobs.migrations import migrate_to_phase_26
        from hk_jobs.posts.fetcher import fetch_watchlist
        migrate_to_phase_26(args.db)
        summary = fetch_watchlist(args.db)
        if summary.errors and not summary.recruiters_polled:
            raise SystemExit(f"Posts watchlist poll failed entirely: {summary.errors}")
        return

    # --posts-discovery: LP-2 weekly keyword discovery search. No scraping.
    if getattr(args, "posts_discovery", False):
        from hk_jobs.migrations import migrate_to_phase_26
        from hk_jobs.posts.fetcher import fetch_discovery
        migrate_to_phase_26(args.db)
        summary = fetch_discovery(args.db)
        if summary.errors and not summary.recruiters_polled:
            raise SystemExit(f"Posts discovery search failed entirely: {summary.errors}")
        return

    # --repair-companies: fix mislabeled company fields for existing JobsDB rows
    # using the GraphQL advertiser.name (Phase 13 Fix A backfill).
    if getattr(args, "repair_companies", False):
        from hk_jobs.description_fetcher import DescriptionFetcher
        DescriptionFetcher(db_path=args.db).run(
            limit=getattr(args, "fetch_limit", None),
            repair_companies=True,
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
