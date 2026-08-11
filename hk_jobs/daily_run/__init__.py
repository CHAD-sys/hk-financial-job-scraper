"""One canonical interface for local and hosted Daily Runs."""

from hk_jobs.daily_run.execution import CommandPhaseExecutor, RuntimePaths, collect_database_facts
from hk_jobs.daily_run.model import (
    DailyRunRecord,
    PhaseResult,
    PhaseStatus,
    ReportingResult,
    RunStatus,
)
from hk_jobs.daily_run.registry import (
    ExecutionProfile,
    PhaseDefinition,
    PhaseRequirement,
    profile_for,
)
from hk_jobs.daily_run.reporting import (
    EmailReporter,
    GitHubSummaryReporter,
    RailwayRecordReporter,
    render_markdown,
    run_reporters,
)
from hk_jobs.daily_run.runner import PhaseOutput, run_daily

__all__ = [
    "DailyRunRecord",
    "ExecutionProfile",
    "PhaseDefinition",
    "PhaseRequirement",
    "PhaseResult",
    "PhaseStatus",
    "PhaseOutput",
    "ReportingResult",
    "RunStatus",
    "profile_for",
    "run_daily",
    "EmailReporter",
    "GitHubSummaryReporter",
    "RailwayRecordReporter",
    "render_markdown",
    "run_reporters",
    "CommandPhaseExecutor",
    "RuntimePaths",
    "collect_database_facts",
]
