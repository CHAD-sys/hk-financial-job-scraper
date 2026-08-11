"""Canonical Daily Run phases and the profiles that select them."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PhaseRequirement(StrEnum):
    REQUIRED = "required"
    OPTIONAL = "optional"


@dataclass(frozen=True, slots=True)
class PhaseDefinition:
    key: str
    label: str
    requirement: PhaseRequirement

    @property
    def required(self) -> bool:
        return self.requirement is PhaseRequirement.REQUIRED


@dataclass(frozen=True, slots=True)
class ExecutionProfile:
    name: str
    phases: tuple[PhaseDefinition, ...]

    def phase(self, key: str) -> PhaseDefinition:
        for phase in self.phases:
            if phase.key == key:
                return phase
        raise KeyError(f"phase {key!r} is not part of the {self.name!r} profile")


PHASES: dict[str, PhaseDefinition] = {
    phase.key: phase
    for phase in (
        PhaseDefinition("restore", "Restore", PhaseRequirement.REQUIRED),
        PhaseDefinition("scrape", "Scrape", PhaseRequirement.REQUIRED),
        PhaseDefinition("descriptions", "Descriptions", PhaseRequirement.REQUIRED),
        PhaseDefinition("deepseek", "DeepSeek", PhaseRequirement.REQUIRED),
        PhaseDefinition("salary_audit", "Salary audit", PhaseRequirement.OPTIONAL),
        PhaseDefinition("pocketbase", "PocketBase mirror", PhaseRequirement.OPTIONAL),
        PhaseDefinition("linkedin_fetch", "LinkedIn watchlist", PhaseRequirement.OPTIONAL),
        PhaseDefinition("linkedin_discovery", "LinkedIn discovery", PhaseRequirement.OPTIONAL),
        PhaseDefinition("linkedin_promote", "LinkedIn promotion", PhaseRequirement.OPTIONAL),
        PhaseDefinition("backup", "Backup", PhaseRequirement.REQUIRED),
        PhaseDefinition("publish", "Railway publish", PhaseRequirement.REQUIRED),
    )
}


def _profile(name: str, *keys: str) -> ExecutionProfile:
    return ExecutionProfile(name=name, phases=tuple(PHASES[key] for key in keys))


PROFILES: dict[str, ExecutionProfile] = {
    "hosted": _profile(
        "hosted",
        "restore",
        "scrape",
        "descriptions",
        "deepseek",
        "salary_audit",
        "linkedin_promote",
        "publish",
    ),
    "local": _profile(
        "local",
        "scrape",
        "descriptions",
        "deepseek",
        "salary_audit",
        "pocketbase",
        "linkedin_fetch",
        "linkedin_discovery",
        "linkedin_promote",
        "backup",
    ),
}


def profile_for(name: str) -> ExecutionProfile:
    try:
        return PROFILES[name]
    except KeyError as exc:
        choices = ", ".join(sorted(PROFILES))
        raise ValueError(f"unknown Daily Run profile {name!r}; choose {choices}") from exc
