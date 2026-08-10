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

import concurrent.futures
import logging
import os
import random
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from threading import Lock
from zoneinfo import ZoneInfo

from hk_jobs.cli import PipelineArgs
from hk_jobs.config import load_companies
from hk_jobs.enrich import enrich_all
from hk_jobs.storage import JobStore

logger = logging.getLogger(__name__)
_HONG_KONG = ZoneInfo("Asia/Hong_Kong")


def _hong_kong_today() -> date:
    """The reporting day used by the 02:00 HKT scheduled pipeline."""
    return datetime.now(_HONG_KONG).date()

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
    source: str = "unknown"

    @property
    def ok(self) -> bool:
        return self.error is None


def run(args: PipelineArgs) -> list[CompanyResult]:
    """
    Execute the full scrape-enrich-store pipeline.

    Returns the list of per-company results so callers (and tests) can
    inspect outcomes without having to re-read the database.

    `args` is a `PipelineArgs`, not an `argparse.Namespace`. It used to be the
    latter, read through ~20 `getattr(args, name, default)` calls — which meant
    a caller that omitted a setting got `False` rather than an error, and the
    tests' idea of the arguments drifted from production's without either side
    noticing. Construct `PipelineArgs(db=..., no_enrich=True)` and every other
    setting is production's default by construction.
    """
    dry_run = args.dry_run

    companies = load_companies(args.config)

    # Merge the Longtail track (LLM-extraction boutique companies) from
    # companies_longtail.yaml so its entries route to LongtailAdapter in the same
    # run. --longtail-only isolates just this track for testing.
    _longtail_yaml = Path(__file__).parent / "companies_longtail.yaml"
    if _longtail_yaml.exists() and not args.no_longtail:
        companies += load_companies(_longtail_yaml)
    if args.longtail_only:
        companies = [c for c in companies if c.adapter == "longtail"]

    if args.company:
        slugs = set(args.company)
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
    _requested = args.parallel_workers or DEFAULT_WORKERS
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
                    results.append(
                        CompanyResult(
                            cfg.name, cfg.slug, error=str(exc), source=cfg.adapter
                        )
                    )

        # Retry pass: companies that returned 0 jobs are almost always transient
        # Cloudflare blocks or network blips, not genuinely empty. Retry them once
        # — sequentially and slowly (one browser at a time) so we don't recreate
        # the synchronised burst that got us blocked in the first place. The
        # data-protection guard already kept each company's existing jobs, so this
        # only adds today's listings back if the retry succeeds.
        if not dry_run and args.retry_failed:
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
        if not dry_run and not args.no_tech_filter:
            try:
                from hk_jobs.tech_filter import run_tech_filter
                with db_lock:
                    _classified, _removed = run_tech_filter(args.db)
            except Exception as exc:  # never let the guard break a run
                logger.warning("tech-filter step failed (%s) — skipping", exc)

        if not dry_run and args.export:
            count = store.export_active_jsonl(args.export)
            logger.info("Exported %d active jobs → %s", count, args.export)

        # Rebuild search AFTER cross-source reconciliation and the tech filter,
        # so a Role the tech filter just soft-deleted (or whose apply_url the
        # reconciliation just moved) doesn't get indexed in a state the board
        # will never show it in. A fresh connection rather than store's own —
        # JobStore keeps that private — closed immediately after; this runs
        # once per pipeline run, not on a hot path. Skipped in dry-run for the
        # same reason everything else here is: an in-memory store, nothing to
        # persist.
        if not dry_run:
            from hk_jobs.search_index import rebuild_search_index

            with db_lock:
                fts_conn = sqlite3.connect(args.db)
                try:
                    rebuild_search_index(fts_conn)
                finally:
                    fts_conn.close()

        _print_report(results, store, dry_run=dry_run)

    # Record a daily snapshot into job_history / company_metrics.
    # Skipped in dry-run mode because dry-run uses an in-memory DB and
    # intentionally writes nothing to disk.
    if not dry_run:
        from hk_jobs.analytics import record_scrape_snapshot
        record_scrape_snapshot(args.db, results, _hong_kong_today())
        from hk_jobs.analytics import record_pipeline_company_runs

        record_pipeline_company_runs(
            args.db,
            results,
            _hong_kong_today(),
            run_id=os.environ.get("GITHUB_RUN_ID") or run_time.strftime("local-%Y%m%dT%H%M%SZ"),
        )
        _log_trend_changes(results, args.db)

    return results


def _run_company(
    cfg,
    store: JobStore,
    run_time: datetime,
    args: PipelineArgs,
    db_lock=None,
) -> CompanyResult:
    """
    Fetch, enrich, and store jobs for one company. Returns a CompanyResult.

    db_lock: optional threading.Lock that serialises SQLite writes when
    multiple companies run concurrently via ThreadPoolExecutor.
    """
    t0 = time.monotonic()
    adapter = cfg.build_adapter()
    source = getattr(adapter, "source_name", None) or cfg.adapter

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
                source=source,
            )
        except Exception as exc:
            logger.error("%s: adapter raised %s: %s", cfg.name, type(exc).__name__, exc)
            return CompanyResult(
                cfg.name, cfg.slug,
                elapsed_secs=time.monotonic() - t0,
                error=f"{type(exc).__name__}: {exc}",
                source=source,
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

    if not args.no_enrich:
        jobs = enrich_all(jobs)

    if args.verbose and jobs:
        for job in jobs:
            logger.debug(
                "  [%s]  %-55s  %s",
                job.source_id,
                job.title[:55],
                ", ".join(job.locations) or "—",
            )

    dry_run = args.dry_run

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
            return CompanyResult(
                cfg.name, cfg.slug, len(jobs), inserted, 0, 0, elapsed, source=source
            )

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

    return CompanyResult(
        cfg.name, cfg.slug, len(jobs), inserted, updated, deactivated, elapsed,
        source=source,
    )


def _retry_failed_companies(
    results: list[CompanyResult],
    companies: list,
    store: JobStore,
    run_time: datetime,
    args: PipelineArgs,
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
        today = _hong_kong_today().isoformat()
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


def main(argv: list[str] | None = None) -> None:
    """
    Kept so `python -m hk_jobs.pipeline` keeps working — the command in
    `daily_run.sh`, twenty README examples and a dozen docstrings.

    The CLI itself lives in `hk_jobs.cli`. Imported here rather than at module
    scope because `cli` imports `run` from this module.
    """
    from hk_jobs.cli import main as cli_main

    cli_main(argv)


if __name__ == "__main__":
    main()
