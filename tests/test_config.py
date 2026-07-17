"""Tests for hk_jobs/config.py — companies.yaml loader and validator."""

import textwrap
from pathlib import Path

import pytest
import yaml

from hk_jobs.adapters import ADAPTERS
from hk_jobs.config import _REQUIRED_CONFIG_KEYS, CompanyConfig, load_companies

# Path to the real companies.yaml (not a test fixture)
_YAML_PATH = Path(__file__).parent.parent / "hk_jobs" / "companies.yaml"


# ── Real YAML — structural checks ────────────────────────────────────────────

def test_yaml_has_entries():
    raw = yaml.safe_load(_YAML_PATH.read_text())
    count = len(raw["companies"])
    assert count >= 30, (
        f"Suspiciously few companies ({count}). "
        "Did a bulk delete accidentally remove real entries?"
    )


def test_all_adapter_names_are_registered():
    raw = yaml.safe_load(_YAML_PATH.read_text())
    unknown = [
        e["name"]
        for e in raw["companies"]
        if e["adapter"] not in ADAPTERS
    ]
    assert not unknown, (
        f"Companies with unregistered adapters: {unknown}. "
        f"Registered: {sorted(ADAPTERS)}"
    )


def test_required_config_keys_present_for_every_entry():
    raw = yaml.safe_load(_YAML_PATH.read_text())
    errors = []
    for entry in raw["companies"]:
        required = _REQUIRED_CONFIG_KEYS.get(entry["adapter"], [])
        config = entry.get("config", {})
        missing = [k for k in required if k not in config]
        if missing:
            errors.append(f"{entry['name']!r}: missing {missing}")
    assert not errors, "Config key errors:\n" + "\n".join(errors)


def test_slug_adapter_pairs_are_unique():
    """
    A company may be scraped from more than one source under the SAME slug (e.g.
    a JobsDB entry AND an eFinancialCareers entry both slug 'man-group-hk') so
    that a role found on both boards is matched by dedup_hash and its apply_url
    routed to the preferred source. The slug therefore need not be globally
    unique — but each (slug, adapter) pair must be, so we never define the same
    source twice for one company.
    """
    raw = yaml.safe_load(_YAML_PATH.read_text())
    pairs = [(e["slug"], e["adapter"]) for e in raw["companies"]]
    dupes = {p for p in pairs if pairs.count(p) > 1}
    assert not dupes, f"Duplicate (slug, adapter) pair(s): {sorted(dupes)}"


def test_every_entry_has_enabled_field():
    raw = yaml.safe_load(_YAML_PATH.read_text())
    missing = [e["name"] for e in raw["companies"] if "enabled" not in e]
    assert not missing, f"Missing 'enabled' field: {missing}"


def test_adapter_distribution():
    """Sanity-check we have a reasonable mix — not all jobsdb fallbacks."""
    raw = yaml.safe_load(_YAML_PATH.read_text())
    by_adapter: dict[str, int] = {}
    for e in raw["companies"]:
        by_adapter[e["adapter"]] = by_adapter.get(e["adapter"], 0) + 1
    # At least 2 Eightfold and some jobsdb entries expected.
    # Workday count can vary as we migrate companies to other sources.
    assert by_adapter.get("eightfold", 0) >= 2, "Expected ≥2 Eightfold entries"
    assert by_adapter.get("jobsdb", 0) >= 10, "Expected ≥10 JobsDB entries"


# ── load_companies() — behaviour ─────────────────────────────────────────────

def test_load_companies_returns_only_enabled():
    all_cfgs = load_companies(_YAML_PATH, include_disabled=True)
    enabled_cfgs = load_companies(_YAML_PATH)
    disabled = [c for c in all_cfgs if not c.enabled]
    assert len(enabled_cfgs) == len(all_cfgs) - len(disabled)


def test_load_companies_returns_company_config_objects():
    cfgs = load_companies(_YAML_PATH)
    assert all(isinstance(c, CompanyConfig) for c in cfgs)


def test_load_companies_config_dict_populated():
    cfgs = load_companies(_YAML_PATH)
    for c in cfgs:
        required = _REQUIRED_CONFIG_KEYS.get(c.adapter, [])
        for key in required:
            assert key in c.config, f"{c.name!r} missing config key {key!r}"


def test_load_companies_include_disabled_returns_all():
    cfgs = load_companies(_YAML_PATH, include_disabled=True)
    assert len(cfgs) >= 30, (
        f"Only {len(cfgs)} total entries — expected at least 30."
    )


# ── Validation errors ─────────────────────────────────────────────────────────

def _write_yaml(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "companies.yaml"
    p.write_text(textwrap.dedent(body))
    return p


def test_unknown_adapter_raises(tmp_path):
    p = _write_yaml(tmp_path, """
        companies:
          - name: TestCo
            slug: testco
            adapter: oracle_taleo
            enabled: true
            config: {}
    """)
    with pytest.raises(ValueError, match="TestCo"):
        load_companies(p)


def test_missing_required_key_raises(tmp_path):
    # workday requires "tenant" and "site"; omit "site"
    p = _write_yaml(tmp_path, """
        companies:
          - name: TestBank
            slug: testbank
            adapter: workday
            enabled: true
            config:
              tenant: testbank
    """)
    with pytest.raises(ValueError, match="TestBank"):
        load_companies(p)


def test_disabled_entry_still_validated(tmp_path):
    # Even a disabled entry with a bad adapter should raise immediately
    p = _write_yaml(tmp_path, """
        companies:
          - name: BadCo
            slug: badco
            adapter: no_such_adapter
            enabled: false
            config: {}
    """)
    with pytest.raises(ValueError, match="BadCo"):
        load_companies(p)


def test_empty_yaml_returns_empty_list(tmp_path):
    p = _write_yaml(tmp_path, "companies: []\n")
    assert load_companies(p) == []


# ── build_adapter() ───────────────────────────────────────────────────────────

def test_build_adapter_returns_correct_type():
    from hk_jobs.adapters.workday import WorkdayAdapter

    cfg = CompanyConfig(
        name="AIA",
        slug="aia",
        adapter="workday",
        enabled=True,
        config={"tenant": "aia", "site": "External"},
    )
    adapter = cfg.build_adapter()
    assert isinstance(adapter, WorkdayAdapter)
    assert adapter.company == "AIA"
    assert adapter.company_slug == "aia"
    assert adapter.tenant == "aia"
