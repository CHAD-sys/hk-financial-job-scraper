#!/usr/bin/env python3
"""Apply the temporary Hays-only package divisor to the anchor table.

The 2026 Hays Hong Kong guide reports total annual package, not base salary.
Until those cells can be rebuilt from base-compatible sources, owner direction
is to scale only the cells that were carried from Hays alone by 12/14.  Cells
that were blended with PERSOLKELLY/Adecco, and later interpolated cells, are
explicitly out of scope.

The script defaults to a dry run.  ``--apply`` creates a timestamped backup,
records the exact scope in anchor metadata, and refuses to run twice.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

GUIDE_DIR = Path(__file__).resolve().parents[1] / "salary_guidlines"
ANCHORS_PATH = GUIDE_DIR / "hk_salary_anchors.json"
BASELINE_PATH = GUIDE_DIR / "hk_salary_anchors.json.bak-20260821-112443"
PRIOR_DIVISOR = 12
TEMPORARY_DIVISOR = 14
EXPECTED_TARGET_CELLS = 136
METADATA_KEY = "temporary_hays_only_package_divisor"

# These are the roles which the reproducible 2026-07-21 merge carried directly
# from Hays.  The baseline snapshot fixes the eligible grades, so later
# granularity additions to these roles cannot accidentally be rescaled too.
HAYS_ONLY_ROLES: dict[str, frozenset[str]] = {
    "front_office": frozenset(
        {
            "financial_markets_sales",
            "corporate_finance_ma_ecm_dcm",
            "private_equity",
            "hedge_fund_investment",
            "investment_counsellor",
        }
    ),
    "commercial_corporate_banking": frozenset(
        {
            "commercial_banking_rm",
            "sme_banking_rm",
            "fi_banking_rm",
            "transaction_banking_rm",
            "wealth_management",
        }
    ),
    "retail_banking": frozenset(
        {
            "branch_management",
            "branch_operation",
            "relationship_management",
            "mortgage",
            "insurance_investment",
        }
    ),
    "middle_office": frozenset(
        {
            "risk_credit",
            "risk_market",
            "risk_climate_modeling_validation",
            "trade_support",
            "product_management",
            "performance_investment_risk",
        }
    ),
    "back_office_operations": frozenset({"collateral_management"}),
    "corporate_finance_accounting": frozenset(
        {
            "tax",
            "shared_service_centre",
            "accounting_support",
            "professional_practice_advisory",
        }
    ),
    "insurance": frozenset(
        {
            "actuarial_pricing",
            "investment",
            "strategic_operations",
            "product_development",
            "pension_operations",
        }
    ),
}


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _valid_band(value: object) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 2
        and all(isinstance(number, int) and number > 0 for number in value)
    )


def target_cells(baseline: dict) -> list[tuple[str, str, str]]:
    """The original Hays-only coordinates, fixed by the saved merge baseline."""
    cells: list[tuple[str, str, str]] = []
    for tier, roles in HAYS_ONLY_ROLES.items():
        baseline_roles = baseline["tables_monthly_hkd"][tier]["roles"]
        for role in roles:
            for grade, band in baseline_roles[role].items():
                if _valid_band(band):
                    cells.append((tier, role, grade))
    return sorted(cells)


def round_to_500(value: int) -> int:
    return int(500 * round(value / 500))


def adjusted_band(band: list[int]) -> list[int]:
    return [round_to_500(value * PRIOR_DIVISOR / TEMPORARY_DIVISOR) for value in band]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the adjustment")
    args = parser.parse_args(argv)

    anchors = _read(ANCHORS_PATH)
    baseline = _read(BASELINE_PATH)
    cells = target_cells(baseline)
    if len(cells) != EXPECTED_TARGET_CELLS:
        raise RuntimeError(f"Expected {EXPECTED_TARGET_CELLS} Hays-only cells, found {len(cells)}")
    if METADATA_KEY in anchors.get("meta", {}):
        raise RuntimeError("The temporary Hays-only divisor was already applied")

    changes: list[tuple[str, str, str, list[int], list[int]]] = []
    for tier, role, grade in cells:
        current = anchors["tables_monthly_hkd"][tier]["roles"][role][grade]
        if not _valid_band(current):
            raise RuntimeError(f"{tier}/{role}/{grade} is not a valid current band")
        changes.append((tier, role, grade, current, adjusted_band(current)))

    print(f"Hays-only cells: {len(changes)}")
    print(f"Temporary conversion: annual / {PRIOR_DIVISOR} -> annual / {TEMPORARY_DIVISOR}")
    if not args.apply:
        print("Dry run only. Re-run with --apply to write the adjustment.")
        return

    backup = ANCHORS_PATH.with_suffix(f".json.bak-{datetime.now():%Y%m%d-%H%M%S}")
    backup.write_text(ANCHORS_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    for tier, role, grade, _before, after in changes:
        anchors["tables_monthly_hkd"][tier]["roles"][role][grade] = after
    anchors.setdefault("meta", {})[METADATA_KEY] = {
        "applied_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "target_cells": len(changes),
        "prior_divisor": PRIOR_DIVISOR,
        "temporary_divisor": TEMPORARY_DIVISOR,
        "baseline": BASELINE_PATH.name,
        "scope": "Direct Hays-only baseline cells; blended and interpolated cells excluded.",
        "rationale": (
            "Temporary numerical proxy: Hays 2026 reports total annual package, not base salary."
        ),
    }
    ANCHORS_PATH.write_text(
        json.dumps(anchors, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"Applied {len(changes)} changes; backup: {backup.name}")


if __name__ == "__main__":
    main()
