"""
Recruiter watchlist configuration loader.

Reads recruiters.yaml and returns validated RecruiterConfig objects.

Unlike load_companies() (which raises on the first bad entry and aborts the
whole load), this loader skips and logs a malformed entry and keeps going.
recruiters.yaml is an actively-growing, semi-automated list (LP-1 bootstrap,
LP-6 weekly discovery queue) — one typo'd row shouldn't be able to take the
other ~30 recruiters' daily fetch down with it. See PLAN_LINKEDIN_POSTS.md
decision record and the LP-2 build notes for the reasoning.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_DEFAULT_YAML = Path(__file__).parent / "recruiters.yaml"

VALID_TIERS = frozenset({"agency_recruiter", "independent", "agency_page"})
_REQUIRED_KEYS = ("name", "slug", "tier", "profile_url")


@dataclass
class RecruiterConfig:
    """One validated entry from recruiters.yaml."""

    name: str
    slug: str
    tier: str
    profile_url: str
    agency: str | None = None
    enabled: bool = True
    added_by: str | None = None
    notes: str | None = None


def load_recruiters(
    path: Path | str | None = None,
    *,
    include_disabled: bool = False,
) -> list[RecruiterConfig]:
    """
    Parse recruiters.yaml and return validated RecruiterConfig objects.

    A malformed entry (missing required key, unknown tier, duplicate slug) is
    logged as an error and SKIPPED — it does not abort the rest of the load.
    Only a file-level problem (missing file, invalid YAML, non-list `recruiters:`
    value) raises.

    Args:
        path:             Override the default recruiters.yaml location.
        include_disabled: When True, also return entries with enabled=false.
    """
    yaml_path = Path(path) if path else _DEFAULT_YAML
    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))

    entries = raw.get("recruiters") if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        raise ValueError(
            f"{yaml_path}: expected a top-level 'recruiters:' list, got {type(raw).__name__}"
        )

    configs: list[RecruiterConfig] = []
    seen_slugs: set[str] = set()
    for i, entry in enumerate(entries):
        cfg = _parse_entry(entry, index=i, seen_slugs=seen_slugs)
        if cfg is None:
            continue
        seen_slugs.add(cfg.slug)
        configs.append(cfg)

    enabled = [c for c in configs if c.enabled]
    skipped = [c.name for c in configs if not c.enabled]
    if skipped:
        logger.info("Skipping disabled recruiters: %s", ", ".join(skipped))

    return configs if include_disabled else enabled


def _parse_entry(
    entry: Any, *, index: int, seen_slugs: set[str]
) -> RecruiterConfig | None:
    """Validate one raw entry. Returns None (and logs) if it's malformed."""
    if not isinstance(entry, dict):
        logger.error("recruiters.yaml entry #%d: not a mapping — skipped", index)
        return None

    label = entry.get("name") or entry.get("slug") or f"entry #{index}"

    missing = [k for k in _REQUIRED_KEYS if not entry.get(k)]
    if missing:
        logger.error(
            "Recruiter %r: missing required key(s) %s — skipped", label, missing
        )
        return None

    if entry["tier"] not in VALID_TIERS:
        logger.error(
            "Recruiter %r: unknown tier %r (must be one of %s) — skipped",
            label, entry["tier"], sorted(VALID_TIERS),
        )
        return None

    slug = entry["slug"]
    if slug in seen_slugs:
        logger.error("Recruiter %r: duplicate slug %r — skipped", label, slug)
        return None

    return RecruiterConfig(
        name=entry["name"],
        slug=slug,
        tier=entry["tier"],
        profile_url=entry["profile_url"],
        agency=entry.get("agency"),
        enabled=bool(entry.get("enabled", True)),
        added_by=entry.get("added_by"),
        notes=entry.get("notes"),
    )
