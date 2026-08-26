"""Schema helpers for role salary tables.

Role tables have two fundamentally different shapes:

``grade_ladder``
    Rows are corporate grades. A coarse seniority may select a specifically
    declared row.

``title_catalog``
    Rows are different job titles/functions. Their JSON order carries no salary
    meaning; only an exact ``(tier, role, grade/title)`` coordinate may select one.

Keeping this module independent of ``salary_anchors`` lets both the offline
builder and the runtime loader enforce the same contract without an import cycle.
"""
from __future__ import annotations

from typing import Any

SENIORITY_LEVELS: tuple[str, ...] = ("junior", "mid", "senior", "lead")

# First match wins. These are the standardized rows deliberately created by the
# three-source merger. Idiosyncratic labels are title-catalog entries unless a
# future reviewed build explicitly standardizes them.
STANDARD_GRADE_ROWS: dict[str, tuple[str, ...]] = {
    "junior": ("Analyst", "Officer / Senior Analyst"),
    "mid": ("Associate", "Assistant Manager / Manager"),
    "senior": ("VP", "Senior Manager / Senior Director"),
    "lead": ("Director", "Head"),
}


def _valid_band(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 2
        and isinstance(value[0], int)
        and isinstance(value[1], int)
        and value[0] > 0
        and value[1] > value[0]
    )


def derive_role_table_semantics(tables: dict[str, Any]) -> dict[str, Any]:
    """Return an explicit type and seniority map for every role table.

    Two or more recognized rows establish a standardized grade ladder. One
    coincidental grade-like title is not enough evidence to let coarse seniority
    select from an otherwise idiosyncratic catalogue.
    """
    tiers: dict[str, dict[str, dict[str, Any]]] = {}
    for tier, table in tables.items():
        roles: dict[str, dict[str, Any]] = {}
        for role, rows in (table.get("roles") or {}).items():
            mapping: dict[str, str] = {}
            if isinstance(rows, dict):
                for level in SENIORITY_LEVELS:
                    row_name = next(
                        (
                            candidate
                            for candidate in STANDARD_GRADE_ROWS[level]
                            if _valid_band(rows.get(candidate))
                        ),
                        None,
                    )
                    if row_name is not None:
                        mapping[level] = row_name
            if len(mapping) >= 2:
                roles[role] = {
                    "kind": "grade_ladder",
                    "seniority_to_grade": mapping,
                }
            else:
                roles[role] = {"kind": "title_catalog"}
        tiers[tier] = roles
    return {
        "_desc": (
            "Generated role-table contract. grade_ladder rows may be selected by the "
            "explicit seniority_to_grade map; title_catalog row order has no meaning "
            "and requires an exact coordinate."
        ),
        "tiers": tiers,
    }


def validate_role_table_semantics(
    tables: dict[str, Any], semantics: dict[str, Any]
) -> list[str]:
    """Return every schema violation; an empty list means the artifact is safe."""
    errors: list[str] = []
    semantic_tiers = semantics.get("tiers") if isinstance(semantics, dict) else None
    if not isinstance(semantic_tiers, dict):
        return ["role_table_semantics.tiers must be an object"]

    table_coordinates = {
        (tier, role)
        for tier, table in tables.items()
        for role in (table.get("roles") or {})
    }
    semantic_coordinates = {
        (tier, role)
        for tier, roles in semantic_tiers.items()
        if isinstance(roles, dict)
        for role in roles
    }
    for tier, role in sorted(table_coordinates - semantic_coordinates):
        errors.append(f"missing role-table semantics for {tier}/{role}")
    for tier, role in sorted(semantic_coordinates - table_coordinates):
        errors.append(f"orphan role-table semantics for {tier}/{role}")

    for tier, role in sorted(table_coordinates):
        rows = tables[tier]["roles"][role]
        coordinate = f"{tier}/{role}"
        if not isinstance(rows, dict):
            errors.append(f"{coordinate} rows must be an object")
            continue
        for row_name, band in rows.items():
            if not _valid_band(band):
                errors.append(f"{coordinate}/{row_name} must be a positive ascending band")

        role_semantics = (semantic_tiers.get(tier) or {}).get(role)
        if not isinstance(role_semantics, dict):
            continue
        kind = role_semantics.get("kind")
        mapping = role_semantics.get("seniority_to_grade")
        if kind == "title_catalog":
            if mapping not in (None, {}):
                errors.append(f"{coordinate} title_catalog must not define a seniority map")
            continue
        if kind != "grade_ladder":
            errors.append(f"{coordinate} has unknown role-table kind {kind!r}")
            continue
        if not isinstance(mapping, dict) or len(mapping) < 2:
            errors.append(f"{coordinate} grade_ladder needs at least two explicit mappings")
            continue

        ceilings: list[int] = []
        for level in SENIORITY_LEVELS:
            row_name = mapping.get(level)
            if row_name is None:
                continue
            if level not in STANDARD_GRADE_ROWS:
                errors.append(f"{coordinate} maps unknown seniority {level!r}")
                continue
            band = rows.get(row_name)
            if not _valid_band(band):
                errors.append(f"{coordinate} maps {level} to missing/invalid row {row_name!r}")
                continue
            ceilings.append(band[1])
        unknown_levels = sorted(set(mapping) - set(SENIORITY_LEVELS))
        for level in unknown_levels:
            errors.append(f"{coordinate} maps unknown seniority {level!r}")
        if ceilings != sorted(ceilings):
            errors.append(f"{coordinate} grade ceilings descend with seniority: {ceilings}")

    return errors
