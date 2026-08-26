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
HISTORICAL_BASELINE_PATH = GUIDE_DIR / "hk_salary_anchors.json.bak-20260821-112443"
RAW_HAYS_PATH = GUIDE_DIR / "hays_2026.json"
PERSOL_PATH = GUIDE_DIR / "persolkelly_2025.json"
ADECCO_PATH = GUIDE_DIR / "adecco_2026.json"
BUILDER_PATH = ROOT / "scripts" / "build_merged_salary_anchors.py"
OUTPUT_PATH = GUIDE_DIR / "hk_salary_anchor_provenance.json"

SOURCE_FILES = {
    "hays_2026": RAW_HAYS_PATH,
    "persolkelly_2025": PERSOL_PATH,
    "adecco_2026": ADECCO_PATH,
}

SOURCE_CATALOG: dict[str, dict[str, Any]] = {
    "hays_2026": {
        "label": "Hays Asia Salary Guide 2026 — Hong Kong SAR",
        "compensation_basis": "annual_total_package",
        "native_period": "annual",
        "currency": "HKD",
        "normalization_to_published_monthly_hkd": (
            "Legacy baseline contributions retain annual package / 12; isolated "
            "Hays-only cells use the temporary / 14 proxy. Neither is base salary."
        ),
        "inclusions_exclusions": "Package components are not defined by the publisher.",
        "aws_13th_month_treatment": "unspecified",
        "source_artifact": "salary_guidlines/2026 Hays Asia Salary Guide HK (1).pdf",
        "evidence_pages": [20, "38-46"],
    },
    "persolkelly_2025": {
        "label": "PERSOLKELLY Hong Kong Salary Guide 2025",
        "compensation_basis": "annual_base_salary",
        "native_period": "annual",
        "currency": "HKD",
        "normalization_to_published_monthly_hkd": "annual_base_salary_hkd / 12",
        "inclusions_exclusions": "Benefits and bonuses excluded.",
        "aws_13th_month_treatment": "unspecified",
        "source_artifact": (
            "salary_guidlines/1734427316-final_hk-salary-guide-2025_singlepage.pdf"
        ),
        "evidence_pages": [3, "12-17", 20, "41-44"],
        "open_upper_bound_treatment": (
            "Preserved as open in the source; bounded only by the published anchor "
            "envelope, never by a manufactured percentage."
        ),
    },
    "adecco_2026": {
        "label": "Adecco Hong Kong Salary Guide 2026",
        "compensation_basis": "monthly_salary_excluding_variable_pay_and_allowances",
        "native_period": "monthly",
        "currency": "HKD",
        "normalization_to_published_monthly_hkd": "identity",
        "inclusions_exclusions": (
            "Overtime, commissions, allowances and bonuses excluded; the publisher "
            "does not call the remainder contractual base salary."
        ),
        "aws_13th_month_treatment": "unspecified",
        "source_artifact": "salary_guidlines/044fa74e-de92-456e-b352-a498fecd27fa.pdf",
        "evidence_pages": [16, "18-20", 46, 63],
        "open_upper_bound_treatment": (
            "Preserved as open in the source; bounded only by the published anchor "
            "envelope, never by a manufactured percentage."
        ),
    },
    "owner_2026_08_21": {
        "label": "Owner-provided Relationship Manager calibration",
        "compensation_basis": "human_monthly_calibration_basis_not_documented",
        "native_period": "monthly",
        "currency": "HKD",
        "normalization_to_published_monthly_hkd": "identity",
        "inclusions_exclusions": "not_documented",
        "aws_13th_month_treatment": "unspecified",
        "source_artifact": "salary_guidlines/hk_salary_anchor_overrides.json",
        "evidence_pages": [],
    },
    "morris_h_2026_08_21": {
        "label": "Morris H. Pricing Test corrections",
        "compensation_basis": "human_monthly_calibration_basis_not_documented",
        "native_period": "monthly",
        "currency": "HKD",
        "normalization_to_published_monthly_hkd": "identity",
        "inclusions_exclusions": "not_documented",
        "aws_13th_month_treatment": "unspecified",
        "source_artifact": "salary_guidlines/hk_salary_anchor_overrides.json",
        "evidence_pages": [],
    },
    "product_management_research_2026_08_26": {
        "label": "Hong Kong bank Product Manager market-evidence calibration",
        "compensation_basis": "market_base_evidence_with_total_package_sanity_check",
        "native_period": "monthly",
        "currency": "HKD",
        "normalization_to_published_monthly_hkd": "identity",
        "inclusions_exclusions": (
            "Glassdoor submissions identify base pay where available; Hays annual total "
            "package is used only as a non-converted sanity envelope."
        ),
        "aws_13th_month_treatment": "unspecified",
        "source_artifact": "docs/research/hong-kong-bank-product-manager-seniority-market.md",
        "evidence_pages": ["Randstad 2025", "current Hong Kong postings", 67],
    },
    "credit_risk_research_2026_08_26": {
        "label": "Hong Kong banking Credit Risk market-evidence calibration",
        "compensation_basis": "market_base_evidence_with_total_package_sanity_check",
        "native_period": "monthly",
        "currency": "HKD",
        "normalization_to_published_monthly_hkd": "identity",
        "inclusions_exclusions": (
            "Randstad basic monthly pay, PERSOLKELLY annual base salary / 12, and "
            "Robert Half annual starting salary / 12 exclude bonus or benefits where "
            "stated; Hays total annual package is only a non-converted sanity envelope."
        ),
        "aws_13th_month_treatment": "unspecified",
        "source_artifact": "docs/research/hong-kong-bank-credit-risk-market.md",
        "evidence_pages": ["Randstad 2025", "PERSOLKELLY p.16", "Robert Half web"],
    },
    "insurance_strategic_operations_research_2026_08_26": {
        "label": "Hong Kong insurance Strategic Operations market-evidence calibration",
        "compensation_basis": "market_base_evidence_with_total_package_sanity_check",
        "native_period": "monthly",
        "currency": "HKD",
        "normalization_to_published_monthly_hkd": "identity",
        "inclusions_exclusions": (
            "Randstad permanent monthly salary, PERSOLKELLY annual base salary / 12, "
            "and Adecco monthly salary exclude variable compensation where stated; Hays "
            "total annual package is only a non-converted seniority sanity envelope."
        ),
        "aws_13th_month_treatment": "unspecified",
        "source_artifact": "docs/research/hong-kong-insurance-strategic-operations-market.md",
        "evidence_pages": ["Randstad 2025", "PERSOLKELLY pp.41-44", "Adecco 2026"],
    },
    "professional_practice_research_2026_08_26": {
        "label": "Hong Kong Professional Practice / Advisory market-evidence calibration",
        "compensation_basis": "market_base_evidence_with_total_package_sanity_check",
        "native_period": "monthly",
        "currency": "HKD",
        "normalization_to_published_monthly_hkd": "identity",
        "inclusions_exclusions": (
            "Randstad basic monthly and PERSOLKELLY annual base / 12 are used as "
            "generic professional-practice comparators; Hays total package is only a "
            "non-converted service-line sanity envelope."
        ),
        "aws_13th_month_treatment": "excluded where Randstad states AWS exclusion; otherwise unspecified",
        "source_artifact": "docs/research/hong-kong-professional-practice-base-market.md",
        "evidence_pages": ["Randstad 2025 pp.12-13", "PERSOLKELLY 2025 pp.17,20"],
    },
    "retail_relationship_management_research_2026_08_26": {
        "label": "Hong Kong Retail Relationship Management market-evidence calibration",
        "compensation_basis": "market_base_evidence_with_total_package_sanity_check",
        "native_period": "monthly",
        "currency": "HKD",
        "normalization_to_published_monthly_hkd": "identity",
        "inclusions_exclusions": (
            "Randstad basic monthly retail-bank pay is primary; Hays total package is "
            "only a non-converted seniority check."
        ),
        "aws_13th_month_treatment": "excluded by Randstad where stated",
        "source_artifact": "docs/research/hong-kong-retail-relationship-management-market.md",
        "evidence_pages": ["Randstad 2025 p.16", "VTC Occupation Dictionary"],
    },
    "financial_markets_sales_research_2026_08_26": {
        "label": "Hong Kong Financial Markets Sales market-evidence calibration",
        "compensation_basis": "market_base_evidence_with_total_package_sanity_check",
        "native_period": "monthly",
        "currency": "HKD",
        "normalization_to_published_monthly_hkd": "identity",
        "inclusions_exclusions": (
            "Hong Kong Talent Engage reports salary separately from bonus and total "
            "compensation; Hays total package is used only as a non-converted check."
        ),
        "aws_13th_month_treatment": "unspecified",
        "source_artifact": "docs/research/hong-kong-financial-markets-sales-market.md",
        "evidence_pages": ["HKTE 2024 Financial Services Compensation Survey"],
    },
    "insurance_product_development_research_2026_08_26": {
        "label": "Hong Kong Insurance Product Development market-evidence calibration",
        "compensation_basis": "market_base_evidence_with_total_package_sanity_check",
        "native_period": "monthly",
        "currency": "HKD",
        "normalization_to_published_monthly_hkd": "identity",
        "inclusions_exclusions": (
            "Hong Kong Talent Engage publishes a monthly salary index; Hays total "
            "package is used only as a non-converted seniority check."
        ),
        "aws_13th_month_treatment": "unspecified",
        "source_artifact": "docs/research/hong-kong-insurance-product-development-market.md",
        "evidence_pages": ["HKTE salary index", "Robert Walters 2025 posting"],
    },
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
PRODUCT_MANAGEMENT_RESEARCH_COORDINATES = {
    "middle_office/product_management/Analyst",
    "middle_office/product_management/Associate",
    "middle_office/product_management/Manager",
    "middle_office/product_management/Senior Manager",
    "middle_office/product_management/Director / Head of Product",
}
CREDIT_RISK_RESEARCH_COORDINATES = {
    "middle_office/risk_credit/Analyst",
    "middle_office/risk_credit/Associate",
    "middle_office/risk_credit/AVP",
    "middle_office/risk_credit/Manager",
    "middle_office/risk_credit/Senior Manager",
    "middle_office/risk_credit/VP",
    "middle_office/risk_credit/Associate Director",
    "middle_office/risk_credit/Director",
    "middle_office/risk_credit/Head of Department",
}
INSURANCE_STRATEGIC_OPERATIONS_RESEARCH_COORDINATES = {
    "insurance/strategic_operations/Analyst",
    "insurance/strategic_operations/Manager",
    "insurance/strategic_operations/Associate Director / Senior Manager",
    "insurance/strategic_operations/Director / AVP",
}
PROFESSIONAL_PRACTICE_RESEARCH_COORDINATES = {
    "corporate_finance_accounting/professional_practice_advisory/Analyst / Graduate Associate",
    "corporate_finance_accounting/professional_practice_advisory/Consultant / Associate",
    "corporate_finance_accounting/professional_practice_advisory/Director / Partner",
    "corporate_finance_accounting/professional_practice_advisory/Manager",
    "corporate_finance_accounting/professional_practice_advisory/Partner",
    "corporate_finance_accounting/professional_practice_advisory/Senior Associate / Assistant Manager",
    "corporate_finance_accounting/professional_practice_advisory/Senior Manager",
}
RETAIL_RELATIONSHIP_MANAGEMENT_RESEARCH_COORDINATES = {
    "retail_banking/relationship_management/Sales Manager",
    "retail_banking/relationship_management/Head of Personal Banking",
}
FINANCIAL_MARKETS_SALES_RESEARCH_COORDINATES = {
    "front_office/financial_markets_sales/Associate",
    "front_office/financial_markets_sales/VP",
    "front_office/financial_markets_sales/Director",
    "front_office/financial_markets_sales/MD",
}
INSURANCE_PRODUCT_DEVELOPMENT_RESEARCH_COORDINATES = {
    "insurance/product_development/Assistant Manager",
    "insurance/product_development/Product Manager",
    "insurance/product_development/Senior Manager",
    "insurance/product_development/Director / Head of Products",
}
MARKET_BASE_RESEARCH_SOURCES = {
    "product_management_research_2026_08_26",
    "credit_risk_research_2026_08_26",
    "insurance_strategic_operations_research_2026_08_26",
    "professional_practice_research_2026_08_26",
    "retail_relationship_management_research_2026_08_26",
    "financial_markets_sales_research_2026_08_26",
    "insurance_product_development_research_2026_08_26",
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
        package_dir = root / "hk_jobs"
        guide_dir.mkdir()
        script_dir.mkdir()
        package_dir.mkdir()
        shutil.copy2(BUILDER_PATH, script_dir / BUILDER_PATH.name)
        shutil.copy2(ROOT / "hk_jobs" / "__init__.py", package_dir / "__init__.py")
        shutil.copy2(
            ROOT / "hk_jobs" / "salary_anchor_schema.py",
            package_dir / "salary_anchor_schema.py",
        )

        copied = {
            "hays_2026": guide_dir / RAW_HAYS_PATH.name,
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
            [
                sys.executable,
                str(script_dir / BUILDER_PATH.name),
                "--without-overrides",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return _load(guide_dir / ANCHORS_PATH.name)


def _hays_only_coordinates() -> set[str]:
    """The independently guarded set affected by the temporary Hays /14 proxy."""
    import importlib.util

    script = ROOT / "scripts" / "apply_hays_only_divisor.py"
    spec = importlib.util.spec_from_file_location("hays_divisor", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {
        "/".join(cell)
        for cell in module.target_cells(_load(HISTORICAL_BASELINE_PATH))
    }


def _declared_native_source_rows() -> dict[str, list[dict[str, str]]]:
    """Load the row mappings carried through the reproducible build itself."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("salary_anchor_builder", BUILDER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.declared_native_source_rows()


def _normalised_source_bands() -> dict[tuple[int, int], set[str]]:
    """Directly published bands, normalised as the merger normalises them."""
    bands: dict[tuple[int, int], set[str]] = {}

    def add(source: str, low: int, high: int | None, *, annual: bool = False) -> None:
        if annual:
            low = round(low / 12)
            hi = 200_000 if high is None else round(high / 12)
        else:
            hi = 200_000 if high is None else high
        low, hi = round(low / 500) * 500, round(hi / 500) * 500
        bands.setdefault((low, hi), set()).add(source)

    def visit(source: str, value: Any, *, annual: bool = False) -> None:
        if isinstance(value, dict):
            for nested in value.values():
                visit(source, nested, annual=annual)
        elif isinstance(value, list) and len(value) == 2 and isinstance(value[0], int):
            add(source, value[0], value[1], annual=annual)

    # hays_2026.json contains legacy monthly values produced by dividing the
    # publisher's annual *package* figures by 12. They are retained here only
    # to identify candidate value matches; this does not make them base pay.
    visit("hays_2026", _load(RAW_HAYS_PATH)["tables_monthly_hkd"])
    visit("persolkelly_2025", _load(PERSOL_PATH), annual=True)
    visit("adecco_2026", _load(ADECCO_PATH))
    return bands


def _source_transformation(source: str, kind: str) -> str:
    if source == "hays_2026":
        if kind == "hays_package_proxy":
            return "annual_total_package_hkd / 14 temporary proxy"
        return "legacy annual_total_package_hkd / 12 contribution"
    if source == "persolkelly_2025":
        return "annual_base_salary_hkd / 12"
    return "identity"


def _semantic_status(sources: list[str], kind: str) -> str:
    if kind == "source_match_requires_confirmation":
        return "candidate_source_match_unconfirmed"
    source_set = set(sources)
    if not source_set:
        return "evidence_unmapped"
    if "hays_2026" in source_set:
        if len(source_set) > 1:
            return "mixed_basis_contains_total_package"
        if kind == "same_role_interpolation":
            return "derived_from_total_package_fallback_not_base_compatible"
        if kind == "hays_package_proxy":
            return "total_package_proxy_not_base_compatible"
        return "total_package_not_base_compatible"
    if source_set == {"persolkelly_2025"}:
        return "base_compatible"
    if source_set == {"adecco_2026"}:
        return "monthly_salary_with_explicit_exclusions"
    if source_set == {"persolkelly_2025", "adecco_2026"}:
        return "base_and_base_like_sources"
    if source_set <= MARKET_BASE_RESEARCH_SOURCES:
        return "market_base_evidence_with_package_sanity_check"
    return "human_calibration_basis_not_documented"


def _mapping_status(kind: str) -> str:
    if kind in {"owner_calibration", "expert_correction"}:
        return "human_calibration_exact_coordinate"
    if kind == "source_match_requires_confirmation":
        return "candidate_band_match_unconfirmed"
    if kind == "same_role_interpolation":
        return "derived_from_same_role_anchors"
    return "legacy_native_mapping_not_preserved"


def _native_source_coordinates(
    coordinate: str,
    sources: list[str],
    kind: str,
    declared_rows: dict[str, list[dict[str, str]]],
) -> dict[str, dict[str, str | None]]:
    _, role, grade = coordinate.split("/", 2)
    human = kind in {"owner_calibration", "expert_correction"}
    rows_by_source = {
        source: [row for row in declared_rows.get(coordinate, []) if row["source"] == source]
        for source in sources
    }
    result = {}
    for source in sources:
        rows = rows_by_source[source]
        if rows:
            result[source] = {
                "native_role": rows[0]["native_role"],
                "native_experience_band": rows[0]["native_experience_band"],
                "mapping_status": "declared_build_mapping",
            }
        else:
            result[source] = {
                "native_role": role if human else None,
                "native_experience_band": grade if human else None,
                "mapping_status": _mapping_status(kind),
            }
    return result


def build_ledger() -> dict[str, Any]:
    current = _load(ANCHORS_PATH)
    current_cells = _cells(current)
    rebuilt = _cells(_build_baseline())
    baseline_cells = rebuilt

    perturbed = {source: _cells(_build_baseline(source)) for source in SOURCE_FILES}
    hays_only = _hays_only_coordinates()
    direct_bands = _normalised_source_bands()
    declared_rows = _declared_native_source_rows()

    records: dict[str, dict[str, Any]] = {}
    for coordinate, band in current_cells.items():
        candidate_sources: list[str] = []
        if coordinate in MORRIS_RELATIONSHIP_COORDINATES:
            kind, sources, note = (
                "owner_calibration",
                ["owner_2026_08_21"],
                "Commercial/corporate RM reference; SME and retail use its stated 20% discount.",
            )
        elif coordinate in PRODUCT_MANAGEMENT_RESEARCH_COORDINATES:
            kind, sources, note = (
                "expert_correction",
                ["product_management_research_2026_08_26"],
                "Hong Kong bank Product Manager calibration from recorded market base-pay "
                "evidence, with Hays p. 67 total-package evidence retained only as a "
                "sanity envelope; no universal annual-package divisor was used.",
            )
        elif coordinate in CREDIT_RISK_RESEARCH_COORDINATES:
            kind, sources, note = (
                "expert_correction",
                ["credit_risk_research_2026_08_26"],
                "Hong Kong banking Credit Risk calibration from recorded base-pay "
                "evidence. Hays annual total-package data is retained only as a "
                "seniority sanity envelope; no universal annual-package divisor was used.",
            )
        elif coordinate in INSURANCE_STRATEGIC_OPERATIONS_RESEARCH_COORDINATES:
            kind, sources, note = (
                "expert_correction",
                ["insurance_strategic_operations_research_2026_08_26"],
                "Hong Kong insurance Strategic Operations calibration from recorded "
                "base-pay evidence. Hays total annual-package data is retained only as "
                "a seniority sanity envelope; no annual-package divisor was used."
            )
        elif coordinate in PROFESSIONAL_PRACTICE_RESEARCH_COORDINATES:
            kind, sources, note = (
                "expert_correction",
                ["professional_practice_research_2026_08_26"],
                "Generic Professional Practice calibration from recorded Hong Kong base-pay "
                "comparators. The conflated Director / Partner coordinate remains deliberately "
                "wide because a closed Partner base-pay cap was not evidenced; Hays package "
                "data was not converted.",
            )
        elif coordinate in RETAIL_RELATIONSHIP_MANAGEMENT_RESEARCH_COORDINATES:
            kind, sources, note = (
                "expert_correction",
                ["retail_relationship_management_research_2026_08_26"],
                "Retail relationship-management calibration from recorded base-pay evidence. "
                "This is a functional/local-scope fallback; explicit corporate grades and "
                "division-wide heads require their more-specific policies.",
            )
        elif coordinate in FINANCIAL_MARKETS_SALES_RESEARCH_COORDINATES:
            kind, sources, note = (
                "expert_correction",
                ["financial_markets_sales_research_2026_08_26"],
                "Financial-markets-sales calibration from a Hong Kong salary-versus-bonus "
                "survey cross-check; employer-specific and scope-specific rules override it. "
                "Hays total package was not converted.",
            )
        elif coordinate in INSURANCE_PRODUCT_DEVELOPMENT_RESEARCH_COORDINATES:
            kind, sources, note = (
                "expert_correction",
                ["insurance_product_development_research_2026_08_26"],
                "Insurance product-development calibration from the Hong Kong Talent Engage "
                "monthly salary index. The combined Director / Head coordinate preserves the "
                "two directly published title bands rather than manufacturing a midpoint.",
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
                kind, sources, candidate_sources, note = (
                    "source_match_requires_confirmation",
                    [],
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
            "candidate_sources": candidate_sources,
            "note": note,
            "published_period": "monthly",
            "currency": "HKD",
            "semantic_status": _semantic_status(sources, kind),
            "compensation_semantics": {
                source: SOURCE_CATALOG[source]["compensation_basis"] for source in sources
            },
            "candidate_compensation_semantics": {
                source: SOURCE_CATALOG[source]["compensation_basis"]
                for source in candidate_sources
            },
            "source_transformations": {
                source: _source_transformation(source, kind) for source in sources
            },
            "native_source_coordinates": _native_source_coordinates(
                coordinate, sources, kind, declared_rows
            ),
            "native_source_rows": {
                source: [
                    {
                        "native_role": row["native_role"],
                        "native_experience_band": row["native_experience_band"],
                    }
                    for row in declared_rows.get(coordinate, [])
                    if row["source"] == source
                ]
                for source in sources
            },
            "mapping_rationale": note,
        }
        semantic_status = records[coordinate]["semantic_status"]
        market_gap_reasons = {
            "total_package_proxy_not_base_compatible": "replace_hays_package_proxy",
            "total_package_not_base_compatible": "replace_hays_package_evidence",
            "derived_from_total_package_fallback_not_base_compatible": (
                "rebuild_interpolation_from_market_evidence"
            ),
            "evidence_unmapped": "map_or_replace_unattributed_anchor",
        }
        records[coordinate]["requires_market_evidence"] = (
            semantic_status in market_gap_reasons
        )
        records[coordinate]["market_gap_reason"] = market_gap_reasons.get(
            semantic_status
        )

    counts = Counter(record["kind"] for record in records.values())
    confirmed_links = sum(len(record["sources"]) for record in records.values())
    mapped_links = sum(
        coordinate["native_role"] is not None
        for record in records.values()
        for coordinate in record["native_source_coordinates"].values()
    )
    return {
        "meta": {
            "schema_version": 2,
            "description": (
                "Cell-level provenance for salary_guidlines/hk_salary_anchors.json. "
                "This ledger is audit data only; it never changes an anchor value."
            ),
            "published_target": {
                "period": "monthly",
                "currency": "HKD",
                "compensation_basis": "mixed_calibration_not_strict_base_salary",
            },
            "semantic_warning": (
                "Hays contributions are annual total-package evidence and cannot be "
                "treated as monthly base salary. Reproducible baseline rows now carry "
                "declared native guide mappings; later legacy interpolations remain null."
            ),
            "source_catalog": SOURCE_CATALOG,
            "counts_by_kind": dict(sorted(counts.items())),
            "native_mapping_coverage": {
                "confirmed_source_links": confirmed_links,
                "mapped_source_links": mapped_links,
                "unmapped_source_links": confirmed_links - mapped_links,
            },
            "baseline": "generated package-free build without reviewed overrides",
            "hays_proxy_scope_baseline": HISTORICAL_BASELINE_PATH.name,
            "generation": (
                "Guide contribution is measured by isolated package-free rebuild sensitivity; "
                "later cells are classified as candidate source matches, same-role interpolation, "
                "or named human corrections."
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
