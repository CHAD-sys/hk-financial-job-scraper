"""The salary-anchor provenance ledger must cover every live payable cell."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from hk_jobs import salary_anchors

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_anchor_provenance.py"


def test_provenance_ledger_is_current_and_covers_every_anchor_cell() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    cells = salary_anchors.ANCHOR_PROVENANCE["cells"]
    live = {
        f"{tier}/{role}/{grade}": band
        for tier, table in salary_anchors.TABLES.items()
        for role, grades in table["roles"].items()
        for grade, band in grades.items()
        if isinstance(band, list) and len(band) == 2
    }
    assert set(cells) == set(live)
    assert {coordinate: cell["band_monthly_hkd"] for coordinate, cell in cells.items()} == live


def test_provenance_exposes_the_actual_hays_proxy_and_human_corrections() -> None:
    hays = salary_anchors.provenance_for("back_office_operations", "collateral_management", "AVP")
    assert hays is not None
    assert hays["kind"] == "hays_package_proxy"
    assert hays["sources"] == ["hays_2026"]

    correction = salary_anchors.provenance_for("insurance", "underwriting", "Underwriter")
    assert correction is not None
    assert correction["kind"] == "expert_correction"
    assert correction["sources"] == ["morris_h_2026_08_21"]
