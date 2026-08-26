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


def test_credit_risk_ladder_uses_recorded_base_salary_market_evidence() -> None:
    expected = {
        "Analyst": [25_000, 40_000],
        "Associate": [35_000, 55_000],
        "AVP": [40_000, 60_000],
        "Manager": [40_000, 60_000],
        "Senior Manager": [65_000, 100_000],
        "VP": [65_000, 100_000],
        "Associate Director": [80_000, 120_000],
        "Director": [100_000, 150_000],
        "Head of Department": [100_000, 150_000],
    }
    table = salary_anchors.TABLES["middle_office"]["roles"]["risk_credit"]
    assert {grade: table[grade] for grade in expected} == expected

    analyst = salary_anchors.provenance_for("middle_office", "risk_credit", "Analyst")
    assert analyst is not None
    assert analyst["kind"] == "expert_correction"
    assert analyst["sources"] == ["credit_risk_research_2026_08_26"]
    assert analyst["semantic_status"] == "market_base_evidence_with_package_sanity_check"


def test_insurance_strategic_operations_uses_base_evidence_but_keeps_coo_open() -> None:
    expected = {
        "Analyst": [25_000, 40_000],
        "Manager": [45_000, 65_000],
        "Associate Director / Senior Manager": [70_000, 120_000],
        "Director / AVP": [90_000, 140_000],
    }
    table = salary_anchors.TABLES["insurance"]["roles"]["strategic_operations"]
    assert {grade: table[grade] for grade in expected} == expected

    manager = salary_anchors.provenance_for("insurance", "strategic_operations", "Manager")
    assert manager is not None
    assert manager["kind"] == "expert_correction"
    assert manager["sources"] == ["insurance_strategic_operations_research_2026_08_26"]

    coo = salary_anchors.provenance_for("insurance", "strategic_operations", "COO")
    assert coo is not None
    assert coo["kind"] == "hays_package_proxy"
    assert coo["requires_market_evidence"] is True


def test_provenance_defines_compensation_semantics_as_structured_data() -> None:
    ledger = salary_anchors.ANCHOR_PROVENANCE
    assert ledger["meta"]["schema_version"] == 2
    assert ledger["meta"]["published_target"] == {
        "period": "monthly",
        "currency": "HKD",
        "compensation_basis": "mixed_calibration_not_strict_base_salary",
    }

    catalog = ledger["meta"]["source_catalog"]
    required = {
        "label",
        "compensation_basis",
        "native_period",
        "currency",
        "normalization_to_published_monthly_hkd",
        "inclusions_exclusions",
        "aws_13th_month_treatment",
        "source_artifact",
        "evidence_pages",
    }
    assert all(required <= set(source) for source in catalog.values())
    assert catalog["hays_2026"]["compensation_basis"] == "annual_total_package"
    assert catalog["persolkelly_2025"]["compensation_basis"] == "annual_base_salary"
    assert (
        catalog["adecco_2026"]["compensation_basis"]
        == "monthly_salary_excluding_variable_pay_and_allowances"
    )
    assert catalog["retail_relationship_management_research_2026_08_26"][
        "aws_13th_month_treatment"
    ] == "excluded by Randstad where stated"
    assert catalog["professional_practice_research_2026_08_26"][
        "aws_13th_month_treatment"
    ] == "excluded where Randstad states AWS exclusion; otherwise unspecified"


def test_every_provenance_cell_carries_mapping_and_semantic_state() -> None:
    required = {
        "published_period",
        "currency",
        "semantic_status",
        "compensation_semantics",
        "source_transformations",
        "native_source_coordinates",
        "native_source_rows",
        "mapping_rationale",
    }
    for coordinate, cell in salary_anchors.ANCHOR_PROVENANCE["cells"].items():
        assert required <= set(cell), coordinate
        assert cell["published_period"] == "monthly", coordinate
        assert cell["currency"] == "HKD", coordinate
        assert set(cell["compensation_semantics"]) == set(cell["sources"]), coordinate
        assert set(cell["source_transformations"]) == set(cell["sources"]), coordinate
        assert set(cell["native_source_coordinates"]) == set(cell["sources"]), coordinate
        for source_coordinate in cell["native_source_coordinates"].values():
            assert set(source_coordinate) == {
                "native_role",
                "native_experience_band",
                "mapping_status",
            }


def test_every_reproducible_or_human_source_link_is_mapped() -> None:
    ledger = salary_anchors.ANCHOR_PROVENANCE
    assert ledger["meta"]["native_mapping_coverage"] == {
        "confirmed_source_links": 679,
        "mapped_source_links": 508,
        "unmapped_source_links": 171,
    }
    for coordinate, cell in ledger["cells"].items():
        if cell["kind"] == "same_role_interpolation":
            continue
        for mapping in cell["native_source_coordinates"].values():
            assert mapping["native_role"] is not None, coordinate
            assert mapping["native_experience_band"] is not None, coordinate


def test_provenance_never_labels_hays_package_evidence_as_base_compatible() -> None:
    hays_only = salary_anchors.provenance_for(
        "back_office_operations", "collateral_management", "AVP"
    )
    assert hays_only is not None
    assert hays_only["semantic_status"] == "total_package_proxy_not_base_compatible"
    assert hays_only["source_transformations"]["hays_2026"] == (
        "annual_total_package_hkd / 14 temporary proxy"
    )

    mixed = salary_anchors.provenance_for(
        "back_office_operations", "customer_service", "cs_senior_manager"
    )
    assert mixed is not None
    assert mixed["semantic_status"] == "candidate_source_match_unconfirmed"
    assert mixed["sources"] == []
    assert mixed["candidate_sources"] == ["hays_2026", "persolkelly_2025"]

    persol = salary_anchors.provenance_for(
        "back_office_operations", "client_services_am", "Analyst"
    )
    assert persol is not None
    assert persol["semantic_status"] == "base_compatible"
    assert persol["source_transformations"]["persolkelly_2025"] == (
        "annual_base_salary_hkd / 12"
    )


def test_hays_does_not_contribute_to_a_weighted_base_compatible_cell() -> None:
    contaminated = {
        coordinate: cell
        for coordinate, cell in salary_anchors.ANCHOR_PROVENANCE["cells"].items()
        if cell["kind"] == "weighted_blend"
        and "hays_2026" in cell["sources"]
        and len(cell["sources"]) > 1
    }
    assert contaminated == {}


def test_equal_band_matches_are_candidates_not_confirmed_sources() -> None:
    candidates = {
        coordinate: cell
        for coordinate, cell in salary_anchors.ANCHOR_PROVENANCE["cells"].items()
        if cell["kind"] == "source_match_requires_confirmation"
    }
    assert len(candidates) == 70
    for coordinate, cell in candidates.items():
        assert cell["sources"] == [], coordinate
        assert cell["candidate_sources"], coordinate
        assert cell["semantic_status"] == "candidate_source_match_unconfirmed", coordinate


def test_confirmed_guide_sources_preserve_native_row_coordinates() -> None:
    direct = salary_anchors.provenance_for(
        "front_office", "equity_research", "Analyst"
    )
    assert direct is not None
    assert direct["native_source_coordinates"]["persolkelly_2025"] == {
        "native_role": "banking_financial_services_annual_hkd/equity_research",
        "native_experience_band": "analyst",
        "mapping_status": "declared_build_mapping",
    }

    blended = salary_anchors.provenance_for(
        "middle_office", "audit_banking", "Analyst"
    )
    assert blended is not None
    assert blended["native_source_coordinates"]["persolkelly_2025"] == {
        "native_role": "banking_financial_services_annual_hkd/internal_audit_banking",
        "native_experience_band": "analyst",
        "mapping_status": "declared_build_mapping",
    }
    assert blended["native_source_coordinates"]["adecco_2026"] == {
        "native_role": "accounting_finance_monthly_hkd/audit",
        "native_experience_band": "auditor",
        "mapping_status": "declared_build_mapping",
    }


def test_hays_derived_interpolations_are_explicit_market_gaps() -> None:
    derived = {
        coordinate: cell
        for coordinate, cell in salary_anchors.ANCHOR_PROVENANCE["cells"].items()
        if cell["kind"] == "same_role_interpolation" and "hays_2026" in cell["sources"]
    }
    assert len(derived) == 3
    for coordinate, cell in derived.items():
        assert cell["semantic_status"] == (
            "derived_from_total_package_fallback_not_base_compatible"
        ), coordinate
        assert cell["requires_market_evidence"] is True, coordinate


def test_five_highest_volume_market_blocks_are_replaced_with_recorded_evidence() -> None:
    expected = {
        "corporate_finance_accounting/professional_practice_advisory": {
            "Consultant / Associate": [25_000, 40_000],
            "Senior Associate / Assistant Manager": [32_000, 50_000],
            "Manager": [45_000, 60_000],
            "Senior Manager": [60_000, 85_000],
            "Director / Partner": [85_000, 250_000],
            "Analyst / Graduate Associate": [20_000, 30_000],
        },
        "middle_office/product_management": {
            "Analyst": [25_000, 40_000],
            "Associate": [35_000, 55_000],
            "Senior Manager": [75_000, 100_000],
            "Director / Head of Product": [100_000, 150_000],
        },
        "retail_banking/relationship_management": {
            "Sales Manager": [45_000, 65_000],
            "Head of Personal Banking": [90_000, 130_000],
        },
        "front_office/financial_markets_sales": {
            "Associate": [35_000, 55_000],
            "VP": [65_000, 100_000],
            "Director": [100_000, 160_000],
            "MD": [150_000, 250_000],
        },
        "insurance/product_development": {
            "Assistant Manager": [38_000, 55_000],
            "Product Manager": [50_000, 68_000],
            "Senior Manager": [75_000, 95_000],
            "Director / Head of Products": [120_000, 230_000],
        },
    }
    sources = {
        "corporate_finance_accounting/professional_practice_advisory": (
            "professional_practice_research_2026_08_26"
        ),
        "middle_office/product_management": "product_management_research_2026_08_26",
        "retail_banking/relationship_management": (
            "retail_relationship_management_research_2026_08_26"
        ),
        "front_office/financial_markets_sales": "financial_markets_sales_research_2026_08_26",
        "insurance/product_development": "insurance_product_development_research_2026_08_26",
    }
    for coordinate, grades in expected.items():
        tier, role = coordinate.split("/", 1)
        table = salary_anchors.TABLES[tier]["roles"][role]
        assert {grade: table[grade] for grade in grades} == grades
        source = sources[coordinate]
        for grade in grades:
            provenance = salary_anchors.provenance_for(tier, role, grade)
            assert provenance is not None
            assert provenance["kind"] == "expert_correction"
            assert provenance["sources"] == [source]
            assert provenance["semantic_status"] == (
                "market_base_evidence_with_package_sanity_check"
            )
