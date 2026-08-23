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
    assert "mixed compensation semantics" in anchors["meta"]["source"].lower()
    assert "total annual package / 14" in anchors["meta"]["basis"].lower()
    override_coordinates = anchors["meta"]["post_hays_only_overrides"]
    overrides = {
        tuple(coordinate.split("/", 2))
        for coordinates in override_coordinates.values()
        for coordinate in coordinates
    }
    assert len(overrides) == 10

    cells = adjustment.target_cells(baseline)
    assert len(cells) == 136
    assert overrides <= set(cells)
    for tier, role, grade in cells:
        before = baseline["tables_monthly_hkd"][tier]["roles"][role][grade]
        actual = anchors["tables_monthly_hkd"][tier]["roles"][role][grade]
        if (tier, role, grade) not in overrides:
            assert actual == adjustment.adjusted_band(before)

    # The saved baseline predates the later granularity expansion.  Among the
    # coordinates shared by both files, this adjustment must be the *only*
    # change from that baseline: no blended or interpolated source cell moves.
    changed_cells = set()
    for tier, table in baseline["tables_monthly_hkd"].items():
        for role, grades in table["roles"].items():
            for grade, before in grades.items():
                actual = anchors["tables_monthly_hkd"][tier]["roles"][role][grade]
                if actual != before:
                    changed_cells.add((tier, role, grade))
    assert changed_cells == set(cells)
