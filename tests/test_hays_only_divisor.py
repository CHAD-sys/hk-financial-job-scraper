"""Regression guard for the temporary /14 Hays-only anchor adjustment."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "apply_hays_only_divisor.py"
ANCHORS_PATH = ROOT / "salary_guidlines" / "hk_salary_anchors.json"
BASELINE_PATH = ROOT / "salary_guidlines" / "hk_salary_anchors.json.bak-20260821-112443"


def _module():
    spec = importlib.util.spec_from_file_location("hays_divisor", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_temporary_hays_only_divisor_adjusts_exactly_the_original_136_cells() -> None:
    adjustment = _module()
    anchors = json.loads(ANCHORS_PATH.read_text(encoding="utf-8"))
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))

    metadata = anchors["meta"][adjustment.METADATA_KEY]
    assert metadata["target_cells"] == adjustment.EXPECTED_TARGET_CELLS == 136
    assert metadata["prior_divisor"] == 12
    assert metadata["temporary_divisor"] == 14
    assert "package-free merge" in anchors["meta"]["source"].lower()
    assert "temporary fallback" in anchors["meta"]["source"].lower()
    assert "not base salary" in metadata["rationale"].lower()
    override_coordinates = anchors["meta"]["post_hays_only_overrides"]
    overrides = {
        tuple(coordinate.split("/", 2))
        for coordinates in override_coordinates.values()
        for coordinate in coordinates
    }
    normalized_md = ("front_office", "corporate_finance_ma_ecm_dcm", "MD")
    assert normalized_md in overrides

    cells = adjustment.target_cells(baseline)
    assert len(cells) == 136
    assert overrides <= set(cells)
    assert metadata["currently_unoverridden_proxy_cells"] == len(cells) - len(overrides)
    for tier, role, grade in cells:
        before = baseline["tables_monthly_hkd"][tier]["roles"][role][grade]
        actual = anchors["tables_monthly_hkd"][tier]["roles"][role][grade]
        if (tier, role, grade) not in overrides:
            assert actual == adjustment.adjusted_band(before)

    # Other baseline cells may now move under ADR 0026's package-free merge.
    # This guard owns only the historical Hays-only target set and its /14 rule.
