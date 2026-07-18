"""Tests for the deterministic salary clamp (hk_jobs.salary_clamp)."""
from hk_jobs.salary_clamp import _LADDERS, clamp_salary


def _band(tier: str, level: str) -> list[int]:
    return _LADDERS[tier][level]


def test_over_band_max_is_capped_to_ceiling():
    lo, ceil = _band("middle_office", "senior")
    assert clamp_salary("middle_office", "senior", lo, ceil + 50_000) == (lo, ceil)


def test_within_band_is_left_untouched():
    lo, ceil = _band("middle_office", "senior")
    assert clamp_salary("middle_office", "senior", lo, ceil - 5_000) == (lo, ceil - 5_000)


def test_below_band_is_never_raised():
    # Down-only: a conservative estimate below the band floor stays as-is.
    lo, _ = _band("middle_office", "senior")
    assert clamp_salary("middle_office", "senior", lo - 20_000, lo - 5_000) == (lo - 20_000, lo - 5_000)


def test_min_is_pulled_down_when_it_exceeds_capped_max():
    lo, ceil = _band("back_office_operations", "junior")
    # Both endpoints above the ceiling -> collapse to the ceiling, range never inverts.
    out_min, out_max = clamp_salary("back_office_operations", "junior", ceil + 20_000, ceil + 40_000)
    assert out_max == ceil
    assert out_min == ceil


def test_unknown_tier_passes_through():
    assert clamp_salary("not_a_tier", "senior", 90_000, 180_000) == (90_000, 180_000)


def test_missing_seniority_passes_through():
    assert clamp_salary("middle_office", None, 90_000, 180_000) == (90_000, 180_000)


def test_none_estimates_pass_through():
    assert clamp_salary("front_office", "lead", None, None) == (None, None)


def test_front_office_lead_ceiling_enforced():
    # A lead role the model priced above even the front-office ceiling gets capped.
    lo, ceil = _band("front_office", "lead")
    assert clamp_salary("front_office", "lead", lo, ceil + 100_000) == (lo, ceil)


def test_lower_tier_has_a_lower_ceiling_than_front_office():
    # Sanity: the clamp meaningfully differentiates tiers at the same seniority.
    assert _band("back_office_operations", "lead")[1] < _band("front_office", "lead")[1]
