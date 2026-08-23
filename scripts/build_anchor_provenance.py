#!/usr/bin/env python3
"""Build/check the cell-level provenance ledger for the salary anchor table.

The salary table is deliberately compact because it is sent to the classifier.
This sidecar is its audit ledger: every ``tier/role/grade`` cell records the
guide datasets that materially contributed to it, or the human/derivation that
replaced guide evidence.  It is not read by the model and never changes a
salary; it makes every displayed calibration explainable.

For the 2026-07-21 merged baseline, provenance is measured by rebuilding the
table in a disposable directory and perturbing one guide at a time.  If an
output cell changes, that guide was a real input to that cell's merge recipe.
This is less error-prone than maintaining a second, handwritten copy of the
large mapping in build_merged_salary_anchors.py.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
GUIDE_DIR = ROOT / "salary_guidlines"
ANCHORS_PATH = GUIDE_DIR / "hk_salary_anchors.json"
BASELINE_PATH = GUIDE_DIR / "hk_salary_anchors.json.bak-20260821-112443"
RAW_HAYS_PATH = GUIDE_DIR / "hk_salary_anchors.json.bak-20260721-234513"
PERSOL_PATH = GUIDE_DIR / "persolkelly_2025.json"
ADECCO_PATH = GUIDE_DIR / "adecco_2026.json"
BUILDER_PATH = ROOT / "scripts" / "build_merged_salary_anchors.py"
OUTPUT_PATH = GUIDE_DIR / "hk_salary_anchor_provenance.json"

SOURCE_FILES = {
    "hays_2026": RAW_HAYS_PATH,
    "persolkelly_2025": PERSOL_PATH,
    "adecco_2026": ADECCO_PATH,
}

# These figures are human calibration evidence, not extracted guide rows.  Keep
# them here rather than inferring them from their value: two sources may happen
# to publish the same range, but that coincidence is not provenance.
MORRIS_RELATIONSHIP_COORDINATES = {
    "commercial_corporate_banking/corporate_banking_rm/Assistant RM",
    "commercial_corporate_banking/corporate_banking_rm/RM",
    "commercial_corporate_banking/corporate_banking_rm/Senior RM",
    "commercial_corporate_banking/commercial_banking_rm/Assistant RM",
    "commercial_corporate_banking/commercial_banking_rm/RM",
    "commercial_corporate_banking/commercial_banking_rm/Senior RM",
    "commercial_corporate_banking/sme_banking_rm/Assistant RM",
    "commercial_corporate_banking/sme_banking_rm/RM",
    "commercial_corporate_banking/sme_banking_rm/Senior RM",
    "retail_banking/relationship_management/Assistant RM",
    "retail_banking/relationship_management/RM",
    "retail_banking/relationship_management/Senior RM",
}
MORRIS_PRICING_TEST_COORDINATES = {
    "middle_office/private_banking_business_management/Manager",
    "front_office/investment_management/Senior Manager",
    "retail_banking/mortgage/Team Head",
    "back_office_operations/exchange_clearing_operations/AVP",
    "back_office_operations/investment_operations/Senior Manager",
    "corporate_finance_accounting/strategy_business_consulting/Consultant",
    "corporate_finance_accounting/strategy_business_consulting/Senior Consultant",
    "corporate_finance_accounting/strategy_business_consulting/Senior Associate",
    "insurance/underwriting/Underwriter",
    "insurance/agency_distribution/Director",
}


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _cells(anchors: dict[str, Any]) -> dict[str, list[int]]:
    return {
        f"{tier}/{role}/{grade}": band
        for tier, table in anchors["tables_monthly_hkd"].items()
        for role, grades in table["roles"].items()
        for grade, band in grades.items()
        if isinstance(band, list) and len(band) == 2
    }


def _perturb(value: Any) -> Any:
    """Make a guide's numeric values visibly different without changing shape."""
    if isinstance(value, dict):
        return {key: _perturb(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_perturb(item) for item in value]
    if isinstance(value, int):
        # A large downshift pierces the merger's HK$200k cap while preserving
        # monotonic ladders and every key the builder expects.
        return max(1, value // 100)
    return value


def _build_baseline(perturb_source: str | None = None) -> dict[str, Any]:
    """Run the existing merger in isolation, optionally perturbing one guide."""
    with tempfile.TemporaryDirectory(prefix="finex-anchor-provenance-") as tmp:
        root = Path(tmp)
        guide_dir = root / "salary_guidlines"
        script_dir = root / "scripts"
        guide_dir.mkdir()
        script_dir.mkdir()
        shutil.copy2(BUILDER_PATH, script_dir / BUILDER_PATH.name)

        copied = {
            "hays_2026": guide_dir / "hk_salary_anchors.json",
            "persolkelly_2025": guide_dir / PERSOL_PATH.name,
            "adecco_2026": guide_dir / ADECCO_PATH.name,
        }
        shutil.copy2(RAW_HAYS_PATH, copied["hays_2026"])
        shutil.copy2(PERSOL_PATH, copied["persolkelly_2025"])
        shutil.copy2(ADECCO_PATH, copied["adecco_2026"])
        if perturb_source:
            path = copied[perturb_source]
            path.write_text(
                json.dumps(_perturb(_load(path)), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

        subprocess.run(
            [sys.executable, str(script_dir / BUILDER_PATH.name)],
            check=True,
            capture_output=True,
            text=True,
        )
        return _load(copied["hays_2026"])


def _hays_only_coordinates() -> set[str]:
    """The independently guarded set affected by the temporary Hays /14 proxy."""
    import importlib.util

    script = ROOT / "scripts" / "apply_hays_only_divisor.py"
    spec = importlib.util.spec_from_file_location("hays_divisor", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {"/".join(cell) for cell in module.target_cells(_load(BASELINE_PATH))}


def _normalised_source_bands() -> dict[tuple[int, int], set[str]]:
    """Directly published bands, normalised as the merger normalises them."""
    bands: dict[tuple[int, int], set[str]] = {}

    def add(source: str, low: int, high: int | None, *, annual: bool = False) -> None:
        hi = high if high is not None else round(low * 1.25)
        if annual:
            low, hi = round(low / 12), round(hi / 12)
        low, hi = round(low / 500) * 500, round(hi / 500) * 500
        bands.setdefault((low, hi), set()).add(source)

    def visit(source: str, value: Any, *, annual: bool = False) -> None:
        if isinstance(value, dict):
            for nested in value.values():
                visit(source, nested, annual=annual)
        elif isinstance(value, list) and len(value) == 2 and isinstance(value[0], int):
            add(source, value[0], value[1], annual=annual)

    # Raw Hays was already monthly in the preserved pre-merge table.  It is not
    # used for later direct additions today, but keeping it here makes the rule
    # complete if a future addition copies one of its cells verbatim.
    visit("hays_2026", _load(RAW_HAYS_PATH)["tables_monthly_hkd"])
    visit("persolkelly_2025", _load(PERSOL_PATH), annual=True)
    visit("adecco_2026", _load(ADECCO_PATH))
    return bands


def build_ledger() -> dict[str, Any]:
    current = _load(ANCHORS_PATH)
    baseline = _load(BASELINE_PATH)
    current_cells = _cells(current)
    baseline_cells = _cells(baseline)

    rebuilt = _cells(_build_baseline())
    if rebuilt != baseline_cells:
        raise RuntimeError(
            "The preserved 2026-07-21 merger no longer reproduces its baseline; "
            "update the merger or baseline before generating provenance."
        )

    perturbed = {source: _cells(_build_baseline(source)) for source in SOURCE_FILES}
    hays_only = _hays_only_coordinates()
    direct_bands = _normalised_source_bands()

    records: dict[str, dict[str, Any]] = {}
    for coordinate, band in current_cells.items():
        if coordinate in MORRIS_RELATIONSHIP_COORDINATES:
            kind, sources, note = (
                "owner_calibration",
                ["owner_2026_08_21"],
                "Commercial/corporate RM reference; SME and retail use its stated 20% discount.",
            )
        elif coordinate in MORRIS_PRICING_TEST_COORDINATES:
            kind, sources, note = (
                "expert_correction",
                ["morris_h_2026_08_21"],
                "Pricing Test WhatsApp correction for this exact function and grade.",
            )
        elif coordinate in baseline_cells:
            sources = sorted(
                source
                for source, variant_cells in perturbed.items()
                if variant_cells.get(coordinate) != rebuilt[coordinate]
            )
            if not sources:
                raise RuntimeError(f"No guide contribution detected for baseline cell {coordinate}")
            if coordinate in hays_only:
                kind = "hays_package_proxy"
                note = "Hays total annual package divided by 14 temporarily; not base-pay evidence."
            elif len(sources) == 1:
                kind = "direct_published"
                note = "One published guide supplied this merged baseline cell."
            else:
                kind = "weighted_blend"
                note = "Published-guide inputs merged by conservative midpoint weighting."
        else:
            published_sources = sorted(direct_bands.get(tuple(band), set()))
            role_prefix = coordinate.rsplit("/", 1)[0] + "/"
            parent_sources = {
                source
                for parent, record in records.items()
                if parent.startswith(role_prefix)
                for source in record["sources"]
                if source in SOURCE_FILES
            }
            if published_sources:
                kind, sources, note = (
                    "source_match_requires_confirmation",
                    published_sources,
                    "Later addition exactly matches one or more normalised guide bands, but the "
                    "original row mapping was not preserved. This is a candidate source match, "
                    "not claimed direct evidence.",
                )
            elif parent_sources:
                kind, sources, note = (
                    "same_role_interpolation",
                    sorted(parent_sources),
                    "Later granularity addition interpolated from this role's published "
                    "anchor rows.",
                )
            else:
                kind, sources, note = (
                    "unmapped_legacy_addition",
                    [],
                    "Added after the reproducible baseline without a preserved guide-row mapping.",
                )

        records[coordinate] = {
            "band_monthly_hkd": band,
            "kind": kind,
            "sources": sources,
            "note": note,
        }

    counts = Counter(record["kind"] for record in records.values())
    return {
        "meta": {
            "schema_version": 1,
            "description": (
                "Cell-level provenance for salary_guidlines/hk_salary_anchors.json. "
                "This ledger is audit data only; it never changes an anchor value."
            ),
            "source_catalog": {
                "hays_2026": (
                    "Hays Asia Salary Guide 2026 HK; total annual package for the direct "
                    "Hays-only proxy cells."
                ),
                "persolkelly_2025": (
                    "PERSOLKELLY Salary Guide 2025 HK; annual base salary, converted /12."
                ),
                "adecco_2026": (
                    "Adecco Hong Kong Salary Guide 2026; monthly salary excluding overtime, "
                    "commissions, allowances and bonuses."
                ),
                "owner_2026_08_21": "Owner-provided Relationship Manager calibration.",
                "morris_h_2026_08_21": "Morris H. Pricing Test WhatsApp corrections.",
            },
            "counts_by_kind": dict(sorted(counts.items())),
            "baseline": BASELINE_PATH.name,
            "generation": (
                "Guide contribution is measured by isolated rebuild sensitivity; later cells "
                "are classified as candidate source matches, same-role interpolation, or named "
                "human corrections."
            ),
        },
        "cells": dict(sorted(records.items())),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="fail if the checked-in ledger is stale"
    )
    args = parser.parse_args()
    ledger = build_ledger()
    rendered = json.dumps(ledger, indent=2, ensure_ascii=False) + "\n"
    if args.check:
        if not OUTPUT_PATH.exists() or OUTPUT_PATH.read_text(encoding="utf-8") != rendered:
            print("Salary-anchor provenance is stale. Run scripts/build_anchor_provenance.py.")
            return 1
        print(f"Salary-anchor provenance is current ({len(ledger['cells'])} cells).")
        return 0
    OUTPUT_PATH.write_text(rendered, encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH.relative_to(ROOT)} ({len(ledger['cells'])} cells).")
    counts = ledger["meta"]["counts_by_kind"]
    print("Kinds:", ", ".join(f"{kind}={count}" for kind, count in counts.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
