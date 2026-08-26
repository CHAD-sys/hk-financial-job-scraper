"""Role-table typing prevents JSON order from becoming salary policy."""
from __future__ import annotations

from copy import deepcopy

from hk_jobs import salary_anchors
from hk_jobs.salary_anchor_schema import validate_role_table_semantics
from hk_jobs.salary_clamp import _role_ceiling, price_from_coordinate


def test_every_published_role_table_is_typed_and_valid() -> None:
    assert salary_anchors.ROLE_TABLE_SCHEMA_ERRORS == ()

    semantics = salary_anchors.ROLE_TABLE_SEMANTICS
    kinds = [
        role_semantics["kind"]
        for roles in semantics.values()
        for role_semantics in roles.values()
    ]
    assert len(kinds) == 105
    assert kinds.count("grade_ladder") == 62
    assert kinds.count("title_catalog") == 43


def test_title_catalog_needs_an_exact_coordinate_not_coarse_seniority() -> None:
    tier = "corporate_finance_accounting"
    role = "corporate_accounting_finance"
    assert salary_anchors.ROLE_TABLE_SEMANTICS[tier][role] == {
        "kind": "title_catalog"
    }

    assert [_role_ceiling(tier, role, level) for level in ("junior", "mid", "senior", "lead")] == [
        None,
        None,
        None,
        None,
    ]
    assert price_from_coordinate(tier, role, "Accountant") == (35_000, 42_000)


def test_schema_rejects_an_untyped_role() -> None:
    semantics = deepcopy(salary_anchors.ROLE_TABLE_SEMANTICS_CONFIG)
    semantics["tiers"]["middle_office"].pop("risk_credit")

    errors = validate_role_table_semantics(salary_anchors.TABLES, semantics)

    assert "missing role-table semantics for middle_office/risk_credit" in errors


def test_schema_rejects_a_descending_grade_ceiling() -> None:
    tables = {
        "test": {
            "roles": {
                "risk": {
                    "Analyst": [20_000, 40_000],
                    "Associate": [30_000, 60_000],
                    "VP": [35_000, 50_000],
                }
            }
        }
    }
    semantics = {
        "tiers": {
            "test": {
                "risk": {
                    "kind": "grade_ladder",
                    "seniority_to_grade": {
                        "junior": "Analyst",
                        "mid": "Associate",
                        "senior": "VP",
                    },
                }
            }
        }
    }

    errors = validate_role_table_semantics(tables, semantics)

    assert errors == ["test/risk grade ceilings descend with seniority: [40000, 60000, 50000]"]


def test_schema_rejects_a_flat_salary_cell() -> None:
    tables = {"test": {"roles": {"risk": {"Analyst": [40_000, 40_000]}}}}
    semantics = {"tiers": {"test": {"risk": {"kind": "title_catalog"}}}}

    errors = validate_role_table_semantics(tables, semantics)

    assert errors == ["test/risk/Analyst must be a positive ascending band"]
