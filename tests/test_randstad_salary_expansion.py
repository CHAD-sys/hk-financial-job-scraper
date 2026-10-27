"""The extra coordinates must be real, traceable guide rows."""

from __future__ import annotations

import json
from pathlib import Path

from hk_jobs import salary_anchors

ROOT = Path(__file__).resolve().parents[1]


def test_finance_table_has_over_1000_source_backed_cells() -> None:
    source = json.loads(
        (ROOT / "salary_guidlines/randstad_2025_finance.json").read_text(encoding="utf-8")
    )
    cells = {
        (tier, role, grade): band
        for tier, table in salary_anchors.TABLES.items()
        for role, rows in table["roles"].items()
        for grade, band in rows.items()
    }
    assert len(cells) >= 1_000
    assert sum(len(entry["bands"]) for entry in source["roles"]) == 286
    for entry in source["roles"]:
        for grade, band in entry["bands"].items():
            coordinate = (entry["tier"], entry["role"], grade)
            assert cells[coordinate] == band
            record = salary_anchors.provenance_for(*coordinate)
            assert record is not None
            assert record["sources"] == ["randstad_2025"]
            assert record["native_source_coordinates"]["randstad_2025"][
                "native_experience_band"
            ] == grade


def test_investment_banking_specialisms_have_separate_direct_bands() -> None:
    roles = salary_anchors.TABLES["front_office"]["roles"]
    assert roles["investment_banking_dcm"]["3–6 years"] == [70_000, 110_000]
    assert roles["investment_banking_ipo_execution"]["3–6 years"] == [60_000, 95_000]
    assert roles["investment_banking_m_a"]["3–6 years"] == [80_000, 120_000]
