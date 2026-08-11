"""Versioned, durable account of one Daily Run."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from hk_jobs.daily_run.registry import ExecutionProfile, profile_for


class PhaseStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    WARNING = "warning"
    FAILED = "failed"
    SKIPPED = "skipped"


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    WARNING = "warning"
    FAILED = "failed"


@dataclass(slots=True)
class PhaseResult:
    key: str
    label: str
    required: bool
    status: PhaseStatus = PhaseStatus.PENDING
    started_at: str | None = None
    finished_at: str | None = None
    duration_seconds: int | None = None
    detail: str | None = None


@dataclass(slots=True)
class ReportingResult:
    key: str
    status: PhaseStatus
    detail: str | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hong_kong_date(stamp: str) -> str:
    return (
        datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        .astimezone(ZoneInfo("Asia/Hong_Kong"))
        .date()
        .isoformat()
    )


@dataclass(slots=True)
class DailyRunRecord:
    run_id: str
    profile: str
    phases: list[PhaseResult]
    operating_date: str
    schema_version: int = 1
    status: RunStatus = RunStatus.RUNNING
    started_at: str = field(default_factory=_utc_now)
    finished_at: str | None = None
    source_run_url: str | None = None
    restore_source: str | None = None
    restore_sha256: str | None = None
    published_sha256: str | None = None
    published_at: str | None = None
    quality: dict[str, Any] = field(default_factory=dict)
    source_health: list[dict[str, Any]] = field(default_factory=list)
    ai_usage: dict[str, Any] = field(default_factory=dict)
    diagnostics: list[str] = field(default_factory=list)
    reporting: list[ReportingResult] = field(default_factory=list)

    @classmethod
    def start(
        cls,
        run_id: str,
        profile: ExecutionProfile,
        *,
        source_run_url: str | None = None,
        started_at: str | None = None,
    ) -> DailyRunRecord:
        run_started_at = started_at or _utc_now()
        return cls(
            run_id=run_id,
            profile=profile.name,
            operating_date=_hong_kong_date(run_started_at),
            source_run_url=source_run_url,
            started_at=run_started_at,
            phases=[
                PhaseResult(key=p.key, label=p.label, required=p.required) for p in profile.phases
            ],
        )

    def phase(self, key: str) -> PhaseResult:
        for phase in self.phases:
            if phase.key == key:
                return phase
        raise KeyError(f"phase {key!r} is not part of this Daily Run")

    def begin_phase(self, key: str, *, at: str | None = None) -> None:
        phase = self.phase(key)
        if phase.status is not PhaseStatus.PENDING:
            raise ValueError(f"phase {key!r} cannot start from {phase.status}")
        phase.status = PhaseStatus.RUNNING
        phase.started_at = at or _utc_now()

    def finish_phase(
        self,
        key: str,
        status: PhaseStatus,
        *,
        detail: str | None = None,
        at: str | None = None,
        duration_seconds: int | None = None,
    ) -> None:
        if status not in {PhaseStatus.SUCCESS, PhaseStatus.WARNING, PhaseStatus.FAILED}:
            raise ValueError(f"{status} is not a terminal executed-phase status")
        phase = self.phase(key)
        if phase.status is not PhaseStatus.RUNNING:
            raise ValueError(f"phase {key!r} cannot finish from {phase.status}")
        phase.status = status
        phase.finished_at = at or _utc_now()
        phase.duration_seconds = duration_seconds
        phase.detail = detail

    def skip_phase(
        self,
        key: str,
        detail: str,
        *,
        at: str | None = None,
        duration_seconds: int | None = None,
    ) -> None:
        phase = self.phase(key)
        if phase.status not in {PhaseStatus.PENDING, PhaseStatus.RUNNING}:
            raise ValueError(f"phase {key!r} cannot be skipped from {phase.status}")
        phase.status = PhaseStatus.SKIPPED
        phase.detail = detail
        if phase.started_at is not None:
            phase.finished_at = at or _utc_now()
            phase.duration_seconds = duration_seconds

    def add_reporting_result(
        self, key: str, status: PhaseStatus, detail: str | None = None
    ) -> None:
        if status not in {PhaseStatus.SUCCESS, PhaseStatus.FAILED, PhaseStatus.SKIPPED}:
            raise ValueError(f"invalid reporting status {status}")
        self.reporting.append(ReportingResult(key=key, status=status, detail=detail))

    def finalize(self, *, at: str | None = None) -> RunStatus:
        for phase in self.phases:
            if phase.status in {PhaseStatus.PENDING, PhaseStatus.RUNNING}:
                phase.status = PhaseStatus.SKIPPED
                phase.detail = phase.detail or "Not executed after a required phase failed"

        required_failed = any(
            phase.required and phase.status in {PhaseStatus.FAILED, PhaseStatus.SKIPPED}
            for phase in self.phases
        )
        warned = any(
            (not phase.required) and phase.status in {PhaseStatus.WARNING, PhaseStatus.FAILED}
            for phase in self.phases
        ) or any(result.status is PhaseStatus.FAILED for result in self.reporting)
        self.status = (
            RunStatus.FAILED
            if required_failed
            else RunStatus.WARNING
            if warned
            else RunStatus.SUCCESS
        )
        self.finished_at = at or _utc_now()
        return self.status

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> DailyRunRecord:
        if raw.get("schema_version") != 1:
            raise ValueError(f"unsupported Daily Run Record schema {raw.get('schema_version')!r}")
        values = dict(raw)
        values.setdefault("operating_date", _hong_kong_date(values["started_at"]))
        values["status"] = RunStatus(values["status"])
        values["phases"] = [
            PhaseResult(**{**phase, "status": PhaseStatus(phase["status"])})
            for phase in values.get("phases", [])
        ]
        values["reporting"] = [
            ReportingResult(**{**result, "status": PhaseStatus(result["status"])})
            for result in values.get("reporting", [])
        ]
        record = cls(**values)
        expected = profile_for(record.profile).phases
        actual = record.phases
        if [phase.key for phase in actual] != [phase.key for phase in expected]:
            raise ValueError("Daily Run phases do not match the selected profile")
        for phase, definition in zip(actual, expected, strict=True):
            if phase.label != definition.label or phase.required != definition.required:
                raise ValueError(f"Daily Run phase metadata is invalid for {phase.key!r}")
        return record

    @classmethod
    def read(cls, path: str | Path) -> DailyRunRecord:
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def write(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(self.to_dict(), stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            Path(temporary).replace(target)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
        return target
