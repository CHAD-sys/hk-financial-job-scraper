"""Small command-line surface shared by GitHub Actions and the local wrapper."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from hk_jobs.daily_run.execution import (
    CommandPhaseExecutor,
    RuntimePaths,
    collect_database_facts,
)
from hk_jobs.daily_run.model import PhaseStatus, RunStatus
from hk_jobs.daily_run.registry import profile_for
from hk_jobs.daily_run.reporting import (
    EmailReporter,
    GitHubSummaryReporter,
    RailwayRecordReporter,
    render_markdown,
    run_reporters,
)
from hk_jobs.daily_run.runner import run_daily


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the FinEx Careers Daily Run")
    parser.add_argument("--profile", choices=("hosted", "local"), required=True)
    parser.add_argument("--run-id", default=os.getenv("GITHUB_RUN_ID"))
    parser.add_argument("--record", default="data/daily-run.json")
    parser.add_argument("--database", default="data/jobs.db")
    parser.add_argument("--export", default="data/jobs.jsonl")
    parser.add_argument("--company", default="")
    parser.add_argument("--email", action="store_true")
    parser.add_argument("--report-railway", action="store_true")
    parser.add_argument("--plan", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.plan:
        for phase in profile_for(args.profile).phases:
            print(f"{phase.key}\t{'required' if phase.required else 'optional'}\t{phase.label}")
        return 0

    run_id = args.run_id or datetime.now(timezone.utc).strftime("local-%Y%m%dT%H%M%SZ")
    # Every subprocess ledger uses the same correlation key as this record.
    os.environ["GITHUB_RUN_ID"] = run_id
    repo = Path.cwd().resolve()
    paths = RuntimePaths(repo, (repo / args.database).resolve(), (repo / args.export).resolve())
    record_path = (repo / args.record).resolve()
    source_url = None
    if os.getenv("GITHUB_SERVER_URL") and os.getenv("GITHUB_REPOSITORY"):
        source_url = (
            f"{os.environ['GITHUB_SERVER_URL']}/{os.environ['GITHUB_REPOSITORY']}"
            f"/actions/runs/{run_id}"
        )

    record = run_daily(
        args.profile,
        run_id,
        CommandPhaseExecutor(paths, company=args.company or None),
        record_path=record_path,
        source_run_url=source_url,
    )
    collect_database_facts(record, paths.database)
    record.write(record_path)

    reporters = []
    if args.email:
        reporters.append(EmailReporter(paths.database))
    if args.report_railway:
        reporters.append(
            RailwayRecordReporter(
                os.getenv(
                    "PIPELINE_OPERATIONS_URL",
                    "https://finex-careers.up.railway.app/api/admin/pipeline/operations",
                ),
                os.getenv("PIPELINE_SYNC_TOKEN", ""),
            )
        )
    if os.getenv("GITHUB_STEP_SUMMARY"):
        reporters.append(GitHubSummaryReporter())
    record = run_reporters(record, reporters, record_path=record_path)

    if not os.getenv("GITHUB_STEP_SUMMARY"):
        print(render_markdown(record))
    reporting_failed = any(item.status is PhaseStatus.FAILED for item in record.reporting)
    return 1 if record.status is RunStatus.FAILED or reporting_failed else 0


if __name__ == "__main__":
    sys.exit(main())
