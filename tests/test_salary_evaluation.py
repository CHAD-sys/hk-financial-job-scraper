from __future__ import annotations

from hk_jobs.salary_evaluation import build_cohort


def _row(source: str, source_id: str, tier: str) -> dict[str, str]:
    return {"source": source, "source_id": source_id, "salary_tier": tier}


def test_cohort_is_deterministic_stratified_and_has_a_400_600_split() -> None:
    rows = [
        *[_row("jobsdb", str(n), "middle_office") for n in range(800)],
        *[_row("linkedin", str(n), "front_office") for n in range(200)],
        *[_row("workday", str(n), "insurance") for n in range(200)],
    ]

    cohort = build_cohort(rows, target=1_000, seed="fixed")

    assert cohort == build_cohort(rows, target=1_000, seed="fixed")
    assert len(cohort) == 1_000
    assert sum(row["batch"] == "pilot_400" for row in cohort) == 400
    assert sum(row["batch"] == "continuation_600" for row in cohort) == 600
    assert {row["source"] for row in cohort} == {"jobsdb", "linkedin", "workday"}
