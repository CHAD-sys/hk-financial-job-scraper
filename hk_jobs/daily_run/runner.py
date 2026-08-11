"""Execute a selected Daily Run profile through one injected phase adapter."""

from __future__ import annotations

import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from hk_jobs.daily_run.model import DailyRunRecord, PhaseStatus
from hk_jobs.daily_run.registry import PhaseDefinition, profile_for


@dataclass(frozen=True, slots=True)
class PhaseOutput:
    status: PhaseStatus = PhaseStatus.SUCCESS
    detail: str | None = None
    facts: dict[str, Any] = field(default_factory=dict)


class PhaseExecutor(Protocol):
    def __call__(self, phase: PhaseDefinition, record: DailyRunRecord) -> PhaseOutput | None: ...


def _apply_facts(record: DailyRunRecord, facts: dict[str, Any]) -> None:
    scalar_fields = {
        "restore_source",
        "restore_sha256",
        "published_sha256",
        "published_at",
    }
    unknown = set(facts) - scalar_fields - {"quality", "source_health", "ai_usage"}
    if unknown:
        raise ValueError(f"unknown Daily Run facts: {', '.join(sorted(unknown))}")
    for key in scalar_fields:
        if key in facts:
            setattr(record, key, facts[key])
    if "quality" in facts:
        record.quality.update(facts["quality"])
    if "source_health" in facts:
        record.source_health = list(facts["source_health"])
    if "ai_usage" in facts:
        record.ai_usage.update(facts["ai_usage"])


def run_daily(
    profile_name: str,
    run_id: str,
    executor: PhaseExecutor,
    *,
    record_path: str | Path | None = None,
    source_run_url: str | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> DailyRunRecord:
    """Run one profile, stop on required failure, and always return a complete record."""
    profile = profile_for(profile_name)
    record = DailyRunRecord.start(run_id, profile, source_run_url=source_run_url)

    def checkpoint() -> None:
        if record_path is not None:
            record.write(record_path)

    checkpoint()
    for phase in profile.phases:
        record.begin_phase(phase.key)
        checkpoint()
        started = monotonic()
        try:
            output = executor(phase, record) or PhaseOutput()
            if output.status not in {PhaseStatus.SUCCESS, PhaseStatus.SKIPPED}:
                raise ValueError("phase executors may only return success or skipped")
            _apply_facts(record, output.facts)
            if output.status is PhaseStatus.SKIPPED:
                record.skip_phase(
                    phase.key,
                    output.detail or "Skipped by execution profile",
                    duration_seconds=max(0, round(monotonic() - started)),
                )
            else:
                record.finish_phase(
                    phase.key,
                    PhaseStatus.SUCCESS,
                    detail=output.detail,
                    duration_seconds=max(0, round(monotonic() - started)),
                )
        except Exception as exc:  # noqa: BLE001 - the record must survive every phase failure
            status = PhaseStatus.FAILED if phase.required else PhaseStatus.WARNING
            record.finish_phase(
                phase.key,
                status,
                detail=f"{type(exc).__name__}: {exc}",
                duration_seconds=max(0, round(monotonic() - started)),
            )
            record.diagnostics.append(traceback.format_exc())
            checkpoint()
            if phase.required:
                break
        checkpoint()

    record.finalize()
    checkpoint()
    return record
