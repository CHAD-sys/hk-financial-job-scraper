"""
The command line: what was asked for, and which mode answers it.

WHY THIS EXISTS
---------------
`pipeline.main()` was a 225-line router. Sixteen near-identical blocks of the
same four lines — test a flag, import a module, call one function, return —
each one also hand-picking the migrations it thought it needed. Below them sat
the default: run the scrape.

Two things that shape fixed in place, and this module is both of them stated
once.

**Nobody could see the modes.** They were sixteen `if` statements in reading
order, and that order is load-bearing: `--enrich --backup` runs the backup and
silently ignores the enrichment, because backup's block comes first. `MODES`
makes the list — and its precedence — something you can read, count, and test.

**`args` was an untyped Namespace.** `run()` read about twenty settings off it
via `getattr(args, name, default)`; the test suite built one with eight fields.
Nothing connected the two, so a field the tests forgot defaulted to `False`
instead of failing, and the test's world quietly differed from production's.
That is not hypothetical — it is the direct cause of two bugs fixed on
2026-08-03 (see `tests/test_pipeline.py`). `PipelineArgs` gives every setting
one declared type and one default, shared by both.

Migrations are no longer a mode's business. `main()` calls
`migrations.migrate()` once, which brings the database to the latest phase
whatever mode follows — so a mode cannot under-migrate, which is how phases 27
and 28 came to be missing from the startup path.
"""

from __future__ import annotations

import argparse
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, fields
from pathlib import Path

logger = logging.getLogger(__name__)


# ── What was asked for ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PipelineArgs:
    """
    Every pipeline setting, typed, with the default the CLI would have given it.

    Frozen because nothing downstream should be editing what the operator asked
    for. Constructing one directly is the supported way to drive the pipeline
    from a test or another program — `PipelineArgs(db=path, no_enrich=True)`
    gets production's defaults for the other thirty-six settings, which is the
    whole point.
    """

    db: str = "data/jobs.db"

    # Scrape
    config: str | None = None
    company: tuple[str, ...] = ()
    longtail_only: bool = False
    no_longtail: bool = False
    dry_run: bool = False
    no_enrich: bool = False
    no_tech_filter: bool = False
    parallel_workers: int = 10
    retry_failed: bool = True
    export: str | None = None

    # Logging
    verbose: bool = False
    log_level: str = "INFO"

    # Reporting / ops modes
    weekly_report: bool = False
    notify_summary: bool = False
    backup: bool = False
    report: str | None = None
    export_trends: str | None = None

    # Enrichment
    enrich: bool = False
    enrich_limit: int | None = None
    re_enrich: bool = False
    enrich_boutique: bool = False
    incremental: bool = False

    # Salary audit
    audit_salaries: bool = False
    audit_limit: int | None = None
    audit_full: bool = False

    # Descriptions
    fetch_descriptions: bool = False
    fetch_limit: int | None = None
    repair_companies: bool = False

    # Secret Market (LinkedIn posts)
    fetch_posts: bool = False
    posts_force: bool = False
    fetch_posts_backfill: bool = False
    posts_discovery: bool = False
    promote_posts: bool = False
    posts_pilot_report: str | None = None
    harvest_recruiter_emails: bool = False
    force_refresh: bool = False
    deactivate_stale_posts: int | None = None
    check_ghost_jobs: bool = False
    repair_post_employers: bool = False
    repair_internship_salaries: bool = False
    repair_grade_ceilings: bool = False
    replay_salary_rules: bool = False
    repair_all_rows: bool = False
    repair_apply: bool = False

    @classmethod
    def from_namespace(cls, ns: argparse.Namespace) -> PipelineArgs:
        """
        Build from whatever argparse produced.

        Reads only the fields declared above, so an argparse dest that nothing
        consumes cannot smuggle itself through, and a field the parser does not
        set gets its declared default rather than vanishing.
        """
        known = {f.name for f in fields(cls)}
        values = {k: v for k, v in vars(ns).items() if k in known}

        # --only/--company uses action='append', so argparse hands back None or
        # a list. One tuple either way means `run()` no longer has to ask which
        # of three shapes it received.
        raw = values.get("company")
        if raw is None:
            values["company"] = ()
        elif isinstance(raw, str):
            values["company"] = (raw,)
        else:
            values["company"] = tuple(raw)

        # --verbose implies DEBUG regardless of --log-level.
        if values.get("verbose"):
            values["log_level"] = "DEBUG"

        return cls(**values)


# ── Parsing ───────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    """The argument parser. Separate from `parse_args` so `--help` is testable."""
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
        "--repair-post-employers",
        dest="repair_post_employers",
        action="store_true",
        help=(
            "Re-apply the employer-name plausibility rule to Recruiter Post rows "
            "already on the board. Rows promoted before the rule existed kept "
            "whatever the extractor claimed, including prose it mislabelled as an "
            "employer ('business leaders to'); those are rewritten to the "
            "'Confidential via {recruiter}' form. Reads each post's STORED "
            "extraction result — no DeepSeek calls, no cost. Reports what it would "
            "change and does nothing unless --repair-apply is also given."
        ),
    )
    p.add_argument(
        "--repair-internship-salaries",
        dest="repair_internship_salaries",
        action="store_true",
        help=(
            "Clamp published internship/graduate-programme estimates down to the "
            "HK$15,000 ceiling the salary prompt sets for them. The 2026-08-18 audit "
            "found 58 of 153 live internship listings above that cap, the worst a 2027 "
            "summer analyst at HK$41,500-83,500. Recomputed deterministically from the "
            "stored row \u2014 no DeepSeek calls, no cost \u2014 and idempotent, so a repeat "
            "run changes nothing. Reports what it would change and does nothing unless "
            "--repair-apply is also given."
        ),
    )
    p.add_argument(
        "--repair-grade-ceilings",
        dest="repair_grade_ceilings",
        action="store_true",
        help=(
            "Re-apply the title-grade ceiling (bank/insurance AVP, VP, Director \u2026) to "
            "published estimates. The 2026-08-19 pass found 62 live rows above the "
            "ceiling their own title implies \u2014 clamp_salary's floor raise adopted a "
            "matched role band outright and handed back a maximum the ceiling had "
            "already lowered. Front-office desks are exempt, exactly as the clamp "
            "exempts them. Deterministic, no model calls, idempotent. Reports what it "
            "would change and does nothing unless --repair-apply is also given."
        ),
    )
    p.add_argument(
        "--replay-salary-rules",
        dest="replay_salary_rules",
        action="store_true",
        help=(
            "Re-apply the current deterministic salary clamp to stored estimates, including "
            "active suppressed cross-post copies, without calling DeepSeek. Employer-disclosed "
            "figures and Ultimate Admin edits are skipped. Reports what it would change and "
            "does nothing unless --repair-apply is also given."
        ),
    )
    p.add_argument(
        "--repair-all-rows",
        dest="repair_all_rows",
        action="store_true",
        help=(
            "Repair every row, not just the live board. A soft-deleted Role keeps its "
            "estimate and comes back with it when a later scrape re-activates it, so a "
            "board-only backfill leaves a backlog that drips onto the board over time "
            "(92 such rows, found the night the internship cap shipped)."
        ),
    )
    p.add_argument(
        "--repair-apply",
        dest="repair_apply",
        action="store_true",
        help="Actually write the changes a --repair-* pass reports. Off by default.",
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
            "Self-enforces the $30/mo budget cap (hk_jobs.posts.budget). "
            "Runs on one pipeline run in hk_jobs.posts.cadence.POSTS_RUN_INTERVAL "
            "(currently every run) — a skipped run is a success, not an error; "
            "use --posts-force to poll anyway."
        ),
    )
    p.add_argument(
        "--posts-force",
        dest="posts_force",
        action="store_true",
        help=(
            "Poll the watchlist even when this run is not its turn. Still counts as "
            "a run, so forcing shifts the cycle rather than sitting outside it. "
            "Only meaningful with --fetch-posts."
        ),
    )
    p.add_argument(
        "--fetch-posts-backfill",
        dest="fetch_posts_backfill",
        action="store_true",
        help=(
            "One-time deep pull per recruiter: no date filter, up to max_posts "
            "(default 50) each, instead of --fetch-posts's normal 'since last "
            "success' incremental window. Use this once (or after adding new "
            "recruiters) to actually populate real post history — every normal "
            "--fetch-posts call, including each recruiter's very first, was "
            "already scoped to a 48h floor, so raising max_posts alone never "
            "increased real volume. Requires APIFY_API_TOKEN."
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
    p.add_argument(
        "--promote-posts",
        dest="promote_posts",
        action="store_true",
        help=(
            "LP-3: classify+extract every pending linkedin_posts row via DeepSeek and "
            "promote the ones that pass the gate (concrete title + HK-plausible location) "
            "into the jobs table as source='linkedin_posts'. Requires DEEPSEEK_API_KEY. "
            "Prints the Secret Market metrics (promoted, %% truly hidden, %% high-confidence) "
            "after the run."
        ),
    )
    p.add_argument(
        "--posts-pilot-report",
        dest="posts_pilot_report",
        metavar="PATH",
        nargs="?",
        const="-",
        help=(
            "LP-4: print the pilot go/no-go report (promoted count, %% truly hidden, "
            "cost so far, extrapolated monthly, a random sample for manual precision "
            "spot-check). No scraping/vendor calls. Pass a path to also write the "
            "markdown to a file; omit the path to print only."
        ),
    )
    p.add_argument(
        "--harvest-recruiter-emails",
        dest="harvest_recruiter_emails",
        action="store_true",
        help=(
            "LP-5: one-time-per-recruiter (then quarterly-refresh) email harvest via "
            "harvestapi/linkedin-profile-scraper's $10/1k email-search mode. Skips "
            "recruiters with an email fetched in the last 90 days unless --force-refresh. "
            "Also backfills board_signals.recruiter_email on already-promoted jobs. "
            "Requires APIFY_API_TOKEN. Self-enforces the $30/mo budget cap."
        ),
    )
    p.add_argument(
        "--force-refresh",
        dest="force_refresh",
        action="store_true",
        help=(
            "With --harvest-recruiter-emails: re-fetch every recruiter's email, "
            "ignoring the 90-day freshness skip."
        ),
    )
    p.add_argument(
        "--deactivate-stale-posts",
        dest="deactivate_stale_posts",
        type=int,
        nargs="?",
        const=90,
        metavar="DAYS",
        help=(
            "Soft-delete (is_active=0) active linkedin_posts jobs whose posted_at "
            "is older than DAYS (default 90 / ~3 months). No scraping/vendor calls. "
            "linkedin_posts-only: --fetch-posts-backfill can promote posts from "
            "months/years ago since it pulls full history with no date filter."
        ),
    )
    p.add_argument(
        "--check-ghost-jobs",
        dest="check_ghost_jobs",
        action="store_true",
        help=(
            "Flag active linkedin_posts jobs that are actually the same real vacancy "
            "as one already on the mainstream/boutique board (invisible to the "
            "company_slug-based reconcile_cross_posted() since confidential posts "
            "never carry a real employer slug). Free fuzzy-title pre-filter, then one "
            "cheap DeepSeek call per candidate post. Sets "
            "board_signals.not_a_ghost_job=true on confirmed matches. No scraping/"
            "Apify calls. Requires DEEPSEEK_API_KEY."
        ),
    )
    return p


def parse_args(argv: list[str] | None = None) -> PipelineArgs:
    """Parse `argv` into the typed settings the rest of the pipeline reads."""
    return PipelineArgs.from_namespace(build_parser().parse_args(argv))


# ── The modes ─────────────────────────────────────────────────────────────────
#
# Each mode is one thing the pipeline can be asked to do INSTEAD of scraping.
# `selected` decides whether this invocation is asking for it; `run` does it.
#
# A predicate rather than a flag name because two modes deliberately answer to
# two flags: `--report` and `--export-trends` share one analytics pass, and
# `--enrich-boutique` implies `--enrich`.


@dataclass(frozen=True)
class Mode:
    name: str
    selected: Callable[[PipelineArgs], bool]
    run: Callable[[PipelineArgs], None]


def _weekly_report(args: PipelineArgs) -> None:
    from hk_jobs.reports.weekly import generate_weekly_report

    generate_weekly_report(db_path=args.db)


def _notify_summary(args: PipelineArgs) -> None:
    from hk_jobs.notifications import send_daily_summary

    send_daily_summary(db_path=args.db)


def _backup(args: PipelineArgs) -> None:
    from hk_jobs.backup import backup_database

    backup_database(db_path=args.db)


def _analytics(args: PipelineArgs) -> None:
    from hk_jobs import analytics

    if args.report == "trends":
        analytics.print_trends_report(args.db)
    elif args.report == "velocity":
        analytics.print_velocity_report(args.db)
    if args.export_trends:
        count = analytics.export_trends_jsonl(args.db, args.export_trends)
        logger.info("Exported %d trend records → %s", count, args.export_trends)


def _rebuild_search_index(args: PipelineArgs) -> None:
    """
    Refresh jobs_fts/search_vocab after a mode that touched what they index.

    Modes call this directly rather than relying on the next scrape's own
    rebuild (pipeline.run) because `--enrich`/`--fetch-descriptions` are
    routinely run standalone, hours or days apart from a scrape — search would
    serve stale skills/descriptions for however long that gap is otherwise.
    """
    import sqlite3

    from hk_jobs.search_index import rebuild_search_index

    conn = sqlite3.connect(args.db)
    try:
        rebuild_search_index(conn)
    finally:
        conn.close()


def _enrich(args: PipelineArgs) -> None:
    from hk_jobs.enrichment import EnrichmentPipeline

    EnrichmentPipeline(db_path=args.db).run(
        limit=args.enrich_limit,
        incremental=args.incremental,
        re_enrich=args.re_enrich,
        boutique_only=args.enrich_boutique,
    )
    _rebuild_search_index(args)


def _audit_salaries(args: PipelineArgs) -> None:
    from hk_jobs.salary_audit import run_audit

    run_audit(args.db, limit=args.audit_limit, full=args.audit_full)


def _fetch_descriptions(args: PipelineArgs) -> None:
    from hk_jobs.description_fetcher import DescriptionFetcher

    DescriptionFetcher(db_path=args.db).run(
        limit=args.fetch_limit,
        incremental=args.incremental,
    )
    _rebuild_search_index(args)


def _fetch_posts(args: PipelineArgs) -> None:
    """
    The watchlist poll, on one pipeline run in `cadence.POSTS_RUN_INTERVAL`.

    The gate is here rather than in `daily_run.sh` because the cost is a property
    of the poll, not of one caller's crontab: a hand-run `--fetch-posts` spends
    the same money as the nightly one, and a shell-side check would not have
    covered it.

    A skipped run exits 0 whenever the interval leaves one to skip — it is not
    an error, and `daily_run.sh` already treats a non-zero exit from this phase
    as a warning to surface, so failing here would put a false alarm in the log.
    At the current interval (1: every run) nothing is ever skipped, but the gate
    stays in case that changes again.
    """
    from hk_jobs.posts import cadence
    from hk_jobs.posts.fetcher import fetch_watchlist

    # `interval=` explicit rather than relying on claim_run's own default: a
    # Python default is bound once, at import time, so a test (or a future
    # caller) that wants to override `cadence.POSTS_RUN_INTERVAL` after import
    # needs this read to happen at CALL time to see it.
    decision = cadence.claim_run(
        args.db, force=args.posts_force, interval=cadence.POSTS_RUN_INTERVAL
    )
    if not decision.due:
        logger.info(
            "Watchlist poll skipped — %s. Nothing is lost: the next poll is scoped "
            "to each recruiter's own last_fetched_at, so it covers the whole gap. "
            "Use --posts-force to poll now.",
            decision.describe(),
        )
        return

    logger.info("Watchlist poll %s.", decision.describe())
    summary = fetch_watchlist(args.db)
    if summary.errors and not summary.recruiters_polled:
        raise SystemExit(f"Posts watchlist poll failed entirely: {summary.errors}")


def _fetch_posts_backfill(args: PipelineArgs) -> None:
    from hk_jobs.posts.fetcher import fetch_watchlist

    summary = fetch_watchlist(args.db, backfill=True)
    if summary.errors and not summary.recruiters_polled:
        raise SystemExit(f"Posts backfill failed entirely: {summary.errors}")


def _posts_discovery(args: PipelineArgs) -> None:
    from hk_jobs.posts.fetcher import fetch_discovery

    summary = fetch_discovery(args.db)
    if summary.errors and not summary.recruiters_polled:
        raise SystemExit(f"Posts discovery search failed entirely: {summary.errors}")


def _promote_posts(args: PipelineArgs) -> None:
    from hk_jobs.posts.metrics import compute_metrics, format_metrics
    from hk_jobs.posts.promote import run_promotion

    summary = run_promotion(args.db)
    logger.info(format_metrics(compute_metrics(args.db)))
    if summary.errors and not summary.promoted and summary.processed:
        raise SystemExit(f"Posts promotion failed entirely: {summary.errors}")


def _posts_pilot_report(args: PipelineArgs) -> None:
    from hk_jobs.posts.pilot_report import format_report, generate_pilot_report

    report = format_report(generate_pilot_report(args.db))
    print(report)
    if args.posts_pilot_report != "-":
        Path(args.posts_pilot_report).write_text(report, encoding="utf-8")
        logger.info("Pilot report written to %s", args.posts_pilot_report)


def _harvest_recruiter_emails(args: PipelineArgs) -> None:
    from hk_jobs.posts.email_harvest import run_email_harvest

    summary = run_email_harvest(args.db, force=args.force_refresh)
    if summary.errors and not summary.harvested and summary.checked:
        raise SystemExit(f"Recruiter email harvest failed entirely: {summary.errors}")


def _deactivate_stale_posts(args: PipelineArgs) -> None:
    from hk_jobs.posts.expiry import deactivate_stale_jobs

    deactivate_stale_jobs(args.db, max_age_days=args.deactivate_stale_posts)


def _check_ghost_jobs(args: PipelineArgs) -> None:
    from hk_jobs.posts.ghost_check import run_ghost_check

    summary = run_ghost_check(args.db)
    logger.info(
        "Ghost check: %d checked, %d with candidates, %d AI calls, %d matched, %d errors",
        summary.checked, summary.with_candidates, summary.ai_calls,
        summary.matched, summary.errors,
    )


def _repair_post_employers(args: PipelineArgs) -> None:
    from hk_jobs.posts.promote import repair_employer_names

    summary = repair_employer_names(args.db, dry_run=not args.repair_apply)
    verb = "would rewrite" if not args.repair_apply else "rewrote"
    print(f"{summary.examined} promoted posts examined; {verb} {summary.repaired}.")
    for name in summary.names:
        print(f"  refused as an employer name: {name!r}")
    if summary.repaired and not args.repair_apply:
        print("Nothing was written. Re-run with --repair-apply to apply.")


def _repair_internship_salaries(args: PipelineArgs) -> None:
    from hk_jobs.salary_repair import repair_internship_salaries

    summary = repair_internship_salaries(
        args.db,
        dry_run=not args.repair_apply,
        live_board_only=not args.repair_all_rows,
    )
    verb = "would lower" if not args.repair_apply else "lowered"
    print(
        f"{summary.examined} estimates examined; {summary.matched} internship titles; "
        f"{verb} {summary.repaired}."
    )
    for title, old_max, new_max in summary.examples:
        print(f"  {old_max:>7,} -> {new_max:>6,}  {title[:60]}")
    for entry in summary.pinned:
        print(f"  SKIPPED - hand-corrected by an admin: {entry}")
    for entry in summary.suspicious:
        print(f"  REVIEW - matched but not stored as junior: {entry}")
    if summary.repaired and not args.repair_apply:
        print("Nothing was written. Re-run with --repair-apply to apply.")


def _repair_grade_ceilings(args: PipelineArgs) -> None:
    from hk_jobs.salary_repair import repair_grade_ceiling_salaries

    summary = repair_grade_ceiling_salaries(
        args.db,
        dry_run=not args.repair_apply,
        live_board_only=not args.repair_all_rows,
    )
    verb = "would lower" if not args.repair_apply else "lowered"
    print(
        f"{summary.examined} estimates examined; {summary.matched} above their grade "
        f"ceiling; {verb} {summary.repaired}."
    )
    for title, old_max, new_max in summary.examples:
        print(f"  {old_max:>7,} -> {new_max:>6,}  {title[:60]}")
    for entry in summary.pinned:
        print(f"  SKIPPED - hand-corrected by an admin: {entry}")
    for entry in summary.disclosed:
        print(f"  SKIPPED - employer stated a figure: {entry}")
    if summary.repaired and not args.repair_apply:
        print("Nothing was written. Re-run with --repair-apply to apply.")


def _replay_salary_rules(args: PipelineArgs) -> None:
    from hk_jobs.salary_repair import replay_salary_rules

    summary = replay_salary_rules(
        args.db,
        dry_run=not args.repair_apply,
        active_only=not args.repair_all_rows,
    )
    verb = "would rewrite" if not args.repair_apply else "rewrote"
    print(
        f"{summary.examined} estimates examined; {verb} {summary.repaired}; "
        f"aligned {summary.aligned} secondary cross-post copies."
    )
    for title, old_max, new_max in summary.examples:
        print(f"  {old_max:>7,} -> {new_max:>6,}  {title[:60]}")
    for entry in summary.pinned:
        print(f"  SKIPPED - hand-corrected by an admin: {entry}")
    for entry in summary.disclosed:
        print(f"  SKIPPED - employer stated a figure: {entry}")
    if summary.repaired and not args.repair_apply:
        print("Nothing was written. Re-run with --repair-apply to apply.")


def _repair_companies(args: PipelineArgs) -> None:
    from hk_jobs.description_fetcher import DescriptionFetcher

    DescriptionFetcher(db_path=args.db).run(
        limit=args.fetch_limit,
        repair_companies=True,
    )


#: Every non-scrape mode, in precedence order — the FIRST match wins, and the
#: order is exactly the old `if`-chain's, so no invocation that worked before
#: behaves differently now. When none match, the pipeline scrapes.
MODES: tuple[Mode, ...] = (
    Mode("weekly-report", lambda a: a.weekly_report, _weekly_report),
    Mode("notify-summary", lambda a: a.notify_summary, _notify_summary),
    Mode("backup", lambda a: a.backup, _backup),
    Mode("analytics", lambda a: bool(a.report or a.export_trends), _analytics),
    Mode("enrich", lambda a: a.enrich or a.enrich_boutique, _enrich),
    Mode("audit-salaries", lambda a: a.audit_salaries, _audit_salaries),
    Mode("fetch-descriptions", lambda a: a.fetch_descriptions, _fetch_descriptions),
    Mode("fetch-posts", lambda a: a.fetch_posts, _fetch_posts),
    Mode("fetch-posts-backfill", lambda a: a.fetch_posts_backfill, _fetch_posts_backfill),
    Mode("posts-discovery", lambda a: a.posts_discovery, _posts_discovery),
    Mode("promote-posts", lambda a: a.promote_posts, _promote_posts),
    Mode("posts-pilot-report", lambda a: bool(a.posts_pilot_report), _posts_pilot_report),
    Mode("harvest-recruiter-emails",
         lambda a: a.harvest_recruiter_emails, _harvest_recruiter_emails),
    # `is not None`, not truthiness: --deactivate-stale-posts 0 means "older
    # than zero days", not "do nothing".
    Mode("deactivate-stale-posts",
         lambda a: a.deactivate_stale_posts is not None, _deactivate_stale_posts),
    Mode("check-ghost-jobs", lambda a: a.check_ghost_jobs, _check_ghost_jobs),
    Mode("repair-post-employers",
         lambda a: a.repair_post_employers, _repair_post_employers),
    Mode("repair-internship-salaries",
         lambda a: a.repair_internship_salaries, _repair_internship_salaries),
    Mode("repair-grade-ceilings",
         lambda a: a.repair_grade_ceilings, _repair_grade_ceilings),
    Mode("replay-salary-rules",
         lambda a: a.replay_salary_rules, _replay_salary_rules),
    Mode("repair-companies", lambda a: a.repair_companies, _repair_companies),
)


def select_mode(args: PipelineArgs) -> Mode | None:
    """
    The mode this invocation asks for, or `None` to scrape.

    Warns when more than one is selected. The old `if`-chain resolved that
    silently — `--enrich --backup` ran the backup and dropped the enrichment
    with no output at all. Same winner, said out loud.
    """
    selected = [m for m in MODES if m.selected(args)]
    if len(selected) > 1:
        logger.warning(
            "%d modes requested (%s); running only --%s. Run the others separately.",
            len(selected), ", ".join(m.name for m in selected), selected[0].name,
        )
    return selected[0] if selected else None


# ── Entry point ───────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    _configure_logging(args)
    if not args.dry_run:
        os.environ["FINEX_AI_USAGE_DB_PATH"] = args.db

    # One migration call for every mode. A mode used to name the phases it
    # believed it needed, which is how the startup path came to be missing
    # phases 27 and 28 while five modes each hand-picked phase 26.
    #
    # Skipped under --dry-run, which promises to leave the database alone —
    # including not creating it. Note this is a tightening: a few post modes
    # used to migrate even under --dry-run, so `--dry-run --fetch-posts` against
    # a database with no Secret Market tables now fails loudly instead of
    # silently building them.
    if not args.dry_run:
        from hk_jobs.migrations import migrate

        Path(args.db).parent.mkdir(parents=True, exist_ok=True)
        migrate(args.db)

    mode = select_mode(args)
    if mode is not None:
        mode.run(args)
        return

    from hk_jobs.pipeline import run

    started = time.monotonic()
    try:
        run(args)
    except Exception as exc:
        if not args.dry_run:
            try:
                from hk_jobs.notifications import send_failure_alert

                send_failure_alert(
                    phase="Pipeline",
                    error=str(exc),
                    duration_seconds=int(time.monotonic() - started),
                )
            except Exception:
                pass
        raise


def _configure_logging(args: PipelineArgs) -> None:
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


if __name__ == "__main__":
    main()
