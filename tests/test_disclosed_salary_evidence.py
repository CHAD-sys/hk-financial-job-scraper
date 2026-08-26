"""Employer-disclosed evidence must be explicit and exactly scoped."""

from __future__ import annotations

from hk_jobs import disclosed_salary_evidence


def test_disclosed_evidence_registry_is_linked_to_exact_matching_overlays() -> None:
    assert set(disclosed_salary_evidence.RECORDS) == {
        "cmb_sanctions_advisor_team_head_disclosed",
        "cmb_private_banking_assistant_rm_disclosed",
    }
    assert disclosed_salary_evidence.validate_overlay_alignment() == ()
