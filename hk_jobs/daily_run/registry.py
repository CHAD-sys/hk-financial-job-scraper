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
        PhaseDefinition("salary_repair", "Salary repair", PhaseRequirement.REQUIRED),
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
    # Enrichment on its own, for clearing a backlog without a scrape.
    #
    # It exists because the DeepSeek key is a GitHub secret, so enrichment can
    # only run inside Actions — and the only way to reach it there used to be a
    # full `hosted` run. That meant a one-line data repair cost a scrape of all
    # 213 sources, and a manual dispatch queued alongside the nightly cron put two
    # such scrapes inside two hours, which is the burst this repo has already been
    # rate-limited by once (see the workflow's concurrency comment, 2026-08-13).
    #
    # restore and publish are not optional decoration: `restore` pulls the live
    # database down from Railway and `publish` hands it back, so without them the
    # phase would enrich a database nobody reads. The three together are the
    # smallest set that changes production.
    "enrich_only": _profile(
        "enrich_only",
        "restore",
        "deepseek",
        "publish",
    ),
    # A deterministic data repair, with no scrape and no model call.
    #
    # A clamp change only affects estimates written after it (deliberately — see
    # salary.py on what version() does and does not fingerprint), so rows already
    # published keep whatever the old clamp allowed. This profile is how such a
    # repair reaches production: restore pulls the live database down from Railway,
    # salary_repair recomputes the affected rows in Python, publish hands it back.
    #
    # Costs nothing and is idempotent, so re-running it is always safe. It is NOT in
    # the hosted profile on purpose: once the clamp is in place no new bad rows are
    # written, which makes this a backfill rather than a nightly chore.
    "repair": _profile(
        "repair",
        "restore",
        "salary_repair",
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
