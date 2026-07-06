"""
Company configuration loader.

Reads companies.yaml and returns validated CompanyConfig objects.
Validation fails loudly — a misconfigured entry raises ValueError with
the company name so the problem is immediately obvious rather than
producing a silent empty run.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from hk_jobs.adapters import ADAPTERS

logger = logging.getLogger(__name__)

_DEFAULT_YAML = Path(__file__).parent / "companies.yaml"

# Keys that MUST be present in config: for each adapter type.
# Optional keys (wd, location_filter, max_pages) have defaults in the
# adapter __init__ so they are not listed here.
_REQUIRED_CONFIG_KEYS: dict[str, list[str]] = {
    "workday": ["tenant", "site"],
    "eightfold": ["tenant", "domain"],
    "jobsdb": ["jobsdb_slug"],
    "indeed": ["indeed_slug"],
    "longtail": ["careers_url"],
}

# Top-level entry keys that are NOT adapter config. Everything else at the top
# level of an entry (e.g. careers_url in companies_longtail.yaml) is folded into
# the adapter config so both the nested `config:` style and the flat longtail
# style work.
_RESERVED_ENTRY_KEYS = frozenset({"name", "slug", "adapter", "enabled", "config"})


@dataclass
class CompanyConfig:
    """One validated entry from companies.yaml."""

    name: str
    slug: str
    adapter: str
    enabled: bool
    config: dict[str, Any] = field(default_factory=dict)

    def build_adapter(self):
        """
        Instantiate and return the adapter for this company.

        Returns a BaseAdapter subclass instance, ready to call fetch_jobs().
        """
        cls = ADAPTERS[self.adapter]
        return cls(company=self.name, company_slug=self.slug, **self.config)


def load_companies(
    path: Path | str | None = None,
    *,
    include_disabled: bool = False,
) -> list[CompanyConfig]:
    """
    Parse companies.yaml and return a list of validated CompanyConfig objects.

    By default only enabled entries are returned. Pass include_disabled=True
    to get all entries (useful for config-validation tests).

    Raises ValueError immediately if any entry — enabled or disabled — has an
    unknown adapter name or is missing required config keys. This ensures a
    bad config is caught at startup rather than silently producing empty runs.

    Args:
        path:             Override the default companies.yaml location.
        include_disabled: When True, also return entries with enabled=false.
    """
    yaml_path = Path(path) if path else _DEFAULT_YAML
    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))

    # Accept both the main format ({companies: [...]}) and a bare top-level list
    # (companies_longtail.yaml).
    entries = raw if isinstance(raw, list) else raw.get("companies", [])

    configs: list[CompanyConfig] = []
    for entry in entries:
        # Fold any non-reserved top-level keys (e.g. careers_url) into config, so
        # the flat longtail style and the nested `config:` style both work.
        config = {k: v for k, v in entry.items() if k not in _RESERVED_ENTRY_KEYS}
        config.update(dict(entry.get("config", {})))
        cfg = CompanyConfig(
            name=entry["name"],
            slug=entry["slug"],
            adapter=entry["adapter"],
            enabled=bool(entry.get("enabled", True)),
            config=config,
        )
        _validate(cfg)  # raises on any problem, enabled or not
        configs.append(cfg)

    enabled = [c for c in configs if c.enabled]
    skipped = [c.name for c in configs if not c.enabled]
    if skipped:
        logger.info("Skipping disabled companies: %s", ", ".join(skipped))

    return configs if include_disabled else enabled


def _validate(cfg: CompanyConfig) -> None:
    """Raise ValueError with the company name if the config is invalid."""
    if cfg.adapter not in ADAPTERS:
        registered = sorted(ADAPTERS)
        raise ValueError(
            f"Company {cfg.name!r}: unknown adapter {cfg.adapter!r}. "
            f"Registered adapters: {registered}. "
            f"Either add the adapter to ADAPTERS or fix the YAML."
        )

    missing = [
        key
        for key in _REQUIRED_CONFIG_KEYS.get(cfg.adapter, [])
        if key not in cfg.config
    ]
    if missing:
        raise ValueError(
            f"Company {cfg.name!r}: adapter {cfg.adapter!r} requires "
            f"config keys {missing} but they are absent from the 'config:' "
            f"block in companies.yaml."
        )
