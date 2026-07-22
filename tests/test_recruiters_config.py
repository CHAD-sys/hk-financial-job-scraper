"""Tests for hk_jobs/recruiters_config.py."""

from pathlib import Path

import pytest
import yaml

from hk_jobs.recruiters_config import RecruiterConfig, load_recruiters


def _write_yaml(tmp_path: Path, entries: list[dict]) -> Path:
    p = tmp_path / "recruiters.yaml"
    p.write_text(yaml.dump({"recruiters": entries}), encoding="utf-8")
    return p


VALID_ENTRY = {
    "name": "Jane Doe",
    "slug": "jane-doe",
    "tier": "agency_recruiter",
    "agency": "Selby Jennings",
    "profile_url": "https://www.linkedin.com/in/janedoe",
    "enabled": True,
    "added_by": "manual",
}


def test_loads_valid_entries(tmp_path):
    path = _write_yaml(tmp_path, [VALID_ENTRY])
    configs = load_recruiters(path)
    assert len(configs) == 1
    assert configs[0] == RecruiterConfig(
        name="Jane Doe", slug="jane-doe", tier="agency_recruiter",
        profile_url="https://www.linkedin.com/in/janedoe",
        agency="Selby Jennings", enabled=True, added_by="manual", notes=None,
    )


def test_disabled_entries_excluded_by_default(tmp_path):
    entry = {**VALID_ENTRY, "enabled": False}
    path = _write_yaml(tmp_path, [entry])
    assert load_recruiters(path) == []
    assert len(load_recruiters(path, include_disabled=True)) == 1


def test_missing_required_key_is_skipped_not_raised(tmp_path):
    bad = {"name": "No Slug", "tier": "agency_recruiter", "profile_url": "https://x"}
    good = dict(VALID_ENTRY)
    path = _write_yaml(tmp_path, [bad, good])
    configs = load_recruiters(path)
    # The malformed entry is skipped; the valid one still loads.
    assert len(configs) == 1
    assert configs[0].slug == "jane-doe"


def test_unknown_tier_is_skipped(tmp_path):
    bad = {**VALID_ENTRY, "slug": "bad-tier", "tier": "in_house_ta"}
    path = _write_yaml(tmp_path, [bad, VALID_ENTRY])
    configs = load_recruiters(path)
    assert len(configs) == 1
    assert configs[0].slug == "jane-doe"


def test_duplicate_slug_second_one_skipped(tmp_path):
    dup = dict(VALID_ENTRY)
    path = _write_yaml(tmp_path, [VALID_ENTRY, dup])
    configs = load_recruiters(path, include_disabled=True)
    assert len(configs) == 1


def test_non_mapping_entry_is_skipped(tmp_path):
    path = _write_yaml(tmp_path, ["not-a-dict", VALID_ENTRY])
    configs = load_recruiters(path)
    assert len(configs) == 1


def test_file_level_problem_raises(tmp_path):
    path = tmp_path / "recruiters.yaml"
    path.write_text(yaml.dump({"recruiters": "not-a-list"}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_recruiters(path)
