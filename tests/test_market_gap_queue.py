from __future__ import annotations

from scripts.build_market_gap_queue import build_queue


def test_market_gap_queue_prioritises_live_role_usage_without_claiming_a_grade() -> None:
    provenance = {
        "cells": {
            "middle_office/risk_credit/VP": {
                "band_monthly_hkd": [50_000, 70_000],
                "requires_market_evidence": True,
                "market_gap_reason": "replace_hays_package_proxy",
                "semantic_status": "total_package_proxy_not_base_compatible",
            },
            "front_office/research/Analyst": {
                "band_monthly_hkd": [30_000, 40_000],
                "requires_market_evidence": False,
            },
        }
    }
    usage = {("middle_office", "risk_credit"): {"role_active": 27, "exact_active": 2}}
    queue = build_queue(provenance, usage)

    assert queue["summary"] == {"market_gaps": 1, "critical": 1, "high": 0, "medium": 0, "low": 0}
    assert queue["entries"][0] == {
        "coordinate": "middle_office/risk_credit/VP",
        "tier": "middle_office",
        "role": "risk_credit",
        "grade": "VP",
        "current_band_monthly_hkd": [50_000, 70_000],
        "market_gap_reason": "replace_hays_package_proxy",
        "semantic_status": "total_package_proxy_not_base_compatible",
        "role_active_primary_listings": 27,
        "exact_grade_active_primary_listings": 2,
        "priority": "critical",
    }
