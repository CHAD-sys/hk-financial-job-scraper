"""Canonical membership for reusable employer compensation cohorts.

Pricing cohorts intentionally overlap.  A bank can be HSBC-scale for one product
rule and DBS-scale for another; that is explicit membership, not an accidental
second company-size classifier.  Anchor data retains its cohort-local slug lists
for now, and :func:`validate_anchor_alignment` makes any divergence a test failure.
"""
from __future__ import annotations

import json
from pathlib import Path


_ROOT = Path(__file__).resolve().parent.parent
_PATH = _ROOT / "salary_guidlines" / "employer_compensation_segments.json"
_ANCHORS_PATH = _ROOT / "salary_guidlines" / "hk_salary_anchors.json"


def _load() -> dict:
    data = json.loads(_PATH.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("cohorts"), dict):
        raise ValueError("Invalid employer compensation cohort registry")
    for name, cohort in data["cohorts"].items():
        slugs = cohort.get("slugs")
        if not isinstance(slugs, list) or len(slugs) != len(set(slugs)):
            raise ValueError(f"Invalid or duplicate slugs for cohort {name!r}")
        if any(not isinstance(slug, str) or slug != slug.lower() for slug in slugs):
            raise ValueError(f"Cohort {name!r} contains a non-canonical slug")
    return data


REGISTRY = _load()
COHORTS: dict[str, frozenset[str]] = {
    name: frozenset(spec["slugs"])
    for name, spec in REGISTRY["cohorts"].items()
}


def slugs_for(cohort: str) -> frozenset[str]:
    """Return an immutable canonical membership set for a named cohort."""
    try:
        return COHORTS[cohort]
    except KeyError as exc:
        raise KeyError(f"Unknown employer compensation cohort: {cohort}") from exc


def cohorts_for(company_slug: str | None) -> frozenset[str]:
    """Return all reusable cohorts an employer intentionally belongs to."""
    if not company_slug:
        return frozenset()
    return frozenset(name for name, slugs in COHORTS.items() if company_slug in slugs)


_ANCHOR_COHORT_PATHS: dict[str, tuple[str, ...]] = {
    "big_four": ("employer_groups", "big_four"),
    "jpmorgan": ("employer_groups", "jpmorgan"),
    "hsbc_sized_banks": ("employer_groups", "hsbc_sized_banks"),
    "dbs_sized_banks": ("employer_groups", "dbs_sized_banks"),
    "market_infrastructure": ("employer_groups", "market_infrastructure"),
    "icbc_sized_banks": ("employer_groups", "icbc_sized_banks"),
    "fwd_sized_insurers": ("employer_groups", "fwd_sized_insurers"),
    "deutsche_bank_mixed_director_vp": ("employer_groups", "deutsche_bank_mixed_director_vp"),
    "smaller_banks": ("title_grade_bands_monthly_hkd", "bank", "smaller_bank"),
    "mid_sized_bank_department_heads": ("title_grade_bands_monthly_hkd", "bank", "mid_sized_bank_large_department_head"),
    "bea_sized_banks": ("title_grade_bands_monthly_hkd", "bank", "bea_sized_bank_functional_assistant_manager"),
    "sun_life_sized_insurers": ("title_grade_bands_monthly_hkd", "insurance", "sun_life_sized_insurer_grades"),
    "mid_sized_insurers": ("title_grade_bands_monthly_hkd", "insurance", "mid_sized_insurer_senior_manager"),
    "chinese_banks": ("title_grade_bands_monthly_hkd", "bank"),
    "insurance_tier_1": ("title_grade_bands_monthly_hkd", "insurance"),
    "insurance_tier_2": ("title_grade_bands_monthly_hkd", "insurance"),
}


def validate_anchor_alignment() -> tuple[str, ...]:
    """Report any legacy anchor slug list that diverges from this registry."""
    anchors = json.loads(_ANCHORS_PATH.read_text(encoding="utf-8"))
    errors: list[str] = []
    for cohort, path in _ANCHOR_COHORT_PATHS.items():
        node = anchors
        for key in path:
            node = node.get(key, {})
        field = (
            "chinese_bank_slugs" if cohort == "chinese_banks"
            else f"tier_{cohort[-1]}_slugs" if cohort.startswith("insurance_tier_")
            else "slugs"
        )
        actual = frozenset(node.get(field, ()))
        if actual != slugs_for(cohort):
            errors.append(
                f"{cohort}: registry={sorted(slugs_for(cohort))}, anchors={sorted(actual)}"
            )
    return tuple(errors)
