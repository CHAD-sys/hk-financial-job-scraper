"""Always-run adapters that publish one authoritative Daily Run Record."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Protocol

import httpx

from hk_jobs.daily_run.model import DailyRunRecord, PhaseStatus


class Reporter(Protocol):
    key: str

    def __call__(self, record: DailyRunRecord) -> str | None: ...


def render_markdown(record: DailyRunRecord) -> str:
    """Render the same record used by Railway and email for GitHub's summary."""
    lines = [
        f"## Daily Run · {record.operating_date}",
        "",
        f"**Outcome:** {record.status.value.upper()}  ",
        f"**Profile:** {record.profile}  ",
        f"**Run ID:** `{record.run_id}`",
        "",
        "| Phase | Requirement | Outcome | Runtime | Detail |",
        "|---|---|---|---:|---|",
    ]
    for phase in record.phases:
        duration = "—" if phase.duration_seconds is None else f"{phase.duration_seconds}s"
        detail = (phase.detail or "—").replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| {phase.label} | {'required' if phase.required else 'optional'} | "
            f"{phase.status.value} | {duration} | {detail} |"
        )
    if record.restore_source or record.published_sha256:
        lines.extend(
            [
                "",
                "### Publication",
                "",
                f"- Restore source: `{record.restore_source or 'not recorded'}`",
                f"- Restored SHA-256: `{record.restore_sha256 or 'not recorded'}`",
                f"- Published SHA-256: `{record.published_sha256 or 'not published'}`",
            ]
        )
    if record.reporting:
        lines.extend(["", "### Reporting", ""])
        lines.extend(
            f"- {result.key}: **{result.status.value}**"
            + (f" — {result.detail}" if result.detail else "")
            for result in record.reporting
        )
    return "\n".join(lines) + "\n"


class GitHubSummaryReporter:
    key = "github_summary"

    def __init__(self, path: str | Path | None = None):
        configured = path or os.getenv("GITHUB_STEP_SUMMARY")
        self.path = Path(configured) if configured else None

    def __call__(self, record: DailyRunRecord) -> str:
        if self.path is None:
            raise RuntimeError("GITHUB_STEP_SUMMARY is not configured")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(render_markdown(record))
        return str(self.path)


class RailwayRecordReporter:
    key = "railway_record"

    def __init__(
        self,
        url: str,
        token: str,
        *,
        post: Callable[..., httpx.Response] = httpx.post,
    ):
        self.url = url
        self.token = token
        self._post = post

    def __call__(self, record: DailyRunRecord) -> str:
        if not self.token:
            raise RuntimeError("PIPELINE_SYNC_TOKEN is not configured")
        response = self._post(
            self.url,
            headers={"X-Pipeline-Sync-Token": self.token},
            content=json.dumps(record.to_dict()),
            timeout=30,
        )
        response.raise_for_status()
        return f"HTTP {response.status_code}"


class EmailReporter:
    key = "email"

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)

    def __call__(self, record: DailyRunRecord) -> str:
        from hk_jobs.notifications import send_daily_run_result

        sent = send_daily_run_result(record, self.db_path)
        if not sent:
            raise RuntimeError("result email was not sent")
        return "sent"


def run_reporters(
    record: DailyRunRecord,
    reporters: Iterable[Reporter],
    *,
    record_path: str | Path,
) -> DailyRunRecord:
    """Run every reporter independently and checkpoint each outcome."""
    for reporter in reporters:
        try:
            detail = reporter(record)
            record.add_reporting_result(reporter.key, PhaseStatus.SUCCESS, detail)
        except Exception as exc:  # noqa: BLE001 - later reporters must still run
            record.add_reporting_result(
                reporter.key,
                PhaseStatus.FAILED,
                f"{type(exc).__name__}: {exc}",
            )
        record.finalize()
        record.write(record_path)
    return record
