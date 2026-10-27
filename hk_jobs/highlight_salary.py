"""Salary quality rule for Roles promoted on the public landing page."""

from hk_jobs import salary_anchors

MIN_MONTHLY_SALARY = 60_000
MAX_ABSOLUTE_WIDTH = 35_000
MAX_RELATIVE_WIDTH = 0.40
SAFE_PROVENANCE = frozenset({
    "base_compatible",
    "monthly_salary_with_explicit_exclusions",
    "base_and_base_like_sources",
    "market_base_evidence_with_package_sanity_check",
})


def suitable_highlight_salary(low: int | None, high: int | None) -> bool:
    """Require a strong floor and a range useful in absolute and relative terms."""
    if low is None or high is None or low < MIN_MONTHLY_SALARY or high <= low:
        return False
    width = high - low
    return width <= MAX_ABSOLUTE_WIDTH and width <= low * MAX_RELATIVE_WIDTH


def suitable_highlight_estimate(
    tier: str | None, role: str | None, grade: str | None, confidence: str | None,
) -> bool:
    """A promoted estimate needs an exact, source-backed cell and a clear model pick."""
    if confidence not in {"high", "medium"} or not all((tier, role, grade)):
        return False
    record = salary_anchors.provenance_for(tier, role, grade)
    return bool(record and record["semantic_status"] in SAFE_PROVENANCE)
