"""The reusable compensation cohorts must have one checked source of membership."""

from __future__ import annotations

from hk_jobs import employer_segments


def test_known_employers_receive_all_intended_overlapping_cohorts() -> None:
    assert employer_segments.cohorts_for("dbs-hk") == frozenset(
        {"hsbc_sized_banks", "dbs_sized_banks"}
    )
    assert employer_segments.cohorts_for("cmb-wing-lung") == frozenset(
        {"smaller_banks", "chinese_banks"}
    )
    assert employer_segments.cohorts_for("sun-life-hk") == frozenset(
        {"insurance_tier_1", "sun_life_sized_insurers"}
    )


def test_anchor_group_membership_cannot_drift_from_the_canonical_registry() -> None:
    assert employer_segments.validate_anchor_alignment() == ()
