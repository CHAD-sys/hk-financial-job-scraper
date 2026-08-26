"""Regression guards for rebuilding the published salary-anchor table."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from scripts import build_merged_salary_anchors as builder

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_merged_salary_anchors.py"
GUIDE_DIR = ROOT / "salary_guidlines"


def _payable_cells(anchors: dict) -> set[str]:
    return {
        f"{tier}/{role}/{grade}"
        for tier, table in anchors["tables_monthly_hkd"].items()
        for role, grades in table["roles"].items()
        for grade, band in grades.items()
        if isinstance(band, list) and len(band) == 2
    }


def _isolated_rebuild(tmp_path: Path) -> tuple[dict, bytes, bytes]:
    """Run the real builder twice without letting it touch the repository."""
    isolated_root = tmp_path / "repo"
    isolated_scripts = isolated_root / "scripts"
    isolated_guides = isolated_root / "salary_guidlines"
    isolated_package = isolated_root / "hk_jobs"
    isolated_scripts.mkdir(parents=True)
    isolated_guides.mkdir()
    isolated_package.mkdir()
    shutil.copy2(SCRIPT, isolated_scripts / SCRIPT.name)
    shutil.copy2(ROOT / "hk_jobs" / "__init__.py", isolated_package / "__init__.py")
    shutil.copy2(
        ROOT / "hk_jobs" / "salary_anchor_schema.py",
        isolated_package / "salary_anchor_schema.py",
    )
    for source in GUIDE_DIR.glob("*.json"):
        shutil.copy2(source, isolated_guides / source.name)

    target = isolated_guides / "hk_salary_anchors.json"
    published = json.loads(target.read_text(encoding="utf-8"))
    command = [sys.executable, str(isolated_scripts / SCRIPT.name)]

    subprocess.run(command, cwd=isolated_root, check=True, capture_output=True, text=True)
    first = target.read_bytes()
    subprocess.run(command, cwd=isolated_root, check=True, capture_output=True, text=True)
    second = target.read_bytes()
    return published, first, second


def test_rebuild_preserves_every_published_anchor_and_is_idempotent(tmp_path: Path) -> None:
    published, first_bytes, second_bytes = _isolated_rebuild(tmp_path)
    rebuilt = json.loads(first_bytes)

    assert _payable_cells(rebuilt) == _payable_cells(published)
    assert rebuilt == published
    assert second_bytes == first_bytes


def test_total_package_is_only_used_when_no_package_free_source_exists() -> None:
    hays_package = (20_000, 30_000)
    package_free = [(40_000, 50_000), (50_000, 60_000)]

    assert builder.merge_package_fallback(hays_package, package_free) == builder.merge(
        package_free
    )
    assert builder.merge_package_fallback(hays_package, []) == [20_000, 30_000]


def test_overlapping_bank_ladder_uses_persol_base_instead_of_hays_package() -> None:
    ladder = builder.bank_ladder(
        ("front_office", "research_strategy_ficc_equity"),
        [("banking_financial_services_annual_hkd", "equity_research")],
    )

    assert ladder["Analyst"] == [41_500, 71_000]


def test_persol_open_upper_bound_uses_the_published_anchor_envelope() -> None:
    assert builder.pk_annual(
        "banking_financial_services_annual_hkd", "am_research", "md"
    ) == [100_000, builder.GLOBAL_MAX]
