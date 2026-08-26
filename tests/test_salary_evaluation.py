from __future__ import annotations

from hk_jobs.salary_evaluation import build_cohort, score_holdout


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


def test_holdout_scores_range_overlap_midpoint_error_and_strata() -> None:
    report = score_holdout([
        {"estimate_min": 40_000, "estimate_max": 60_000, "truth_min": 45_000,
         "truth_max": 55_000, "tier": "middle_office", "cohort": "bank"},
        {"estimate_min": 20_000, "estimate_max": 30_000, "truth_min": 40_000,
         "truth_max": 50_000, "tier": "middle_office", "cohort": "bank"},
    ])
    assert report["overall"] == {
        "n": 2,
        "range_overlap_rate": 0.5,
        "truth_midpoint_covered_rate": 0.5,
        "midpoint_mae_hkd": 10_000,
        "midpoint_mape": 0.2222,
        "mean_estimate_width_hkd": 15_000,
    }
    assert report["by_tier"]["middle_office"]["n"] == 2
    assert report["by_cohort"]["bank"]["range_overlap_rate"] == 0.5
