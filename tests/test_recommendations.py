"""Behavioral contract for the explainable first-party Role ranker."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "webapp" / "backend"
sys.path.insert(0, str(BACKEND))

from job_read import JobSummary  # noqa: E402
from recommendations import rank_roles  # noqa: E402

NOW = datetime(2026, 8, 8, tzinfo=timezone.utc)


def _role(source_id: str, **over) -> JobSummary:
    data = {
        "source": "workday",
        "source_id": source_id,
        "company": "HSBC",
        "sector": "Banking",
        "title": "Analyst",
        "source_tier": "mainstream",
        "url": f"https://example.test/{source_id}",
        "posted_at": "2026-08-07T00:00:00+00:00",
    }
    data.update(over)
    return JobSummary(**data)


def _event(search: str = "", filters: dict | None = None, *, days_ago: int = 0) -> dict:
    moment = NOW.replace(day=NOW.day - days_ago)
    return {
        "search_query": search,
        "filters_json": json.dumps(filters or {}, separators=(",", ":")),
        "result_count": 12,
        "created_at": moment.isoformat(),
    }


def test_saved_roles_and_recent_discovery_push_related_roles_to_the_top():
    saved = _role(
        "saved",
        title="Credit Risk Analyst",
        seniority="mid",
        required_skills=["credit risk", "financial analysis"],
    )
    candidates = [
        _role(
            "risk",
            company="Hang Seng Bank",
            title="Senior Credit Risk Manager",
            seniority="mid",
            required_skills=["credit risk"],
        ),
        _role(
            "actuary",
            company="AIA",
            sector="Insurance",
            title="Actuarial Manager",
            seniority="senior",
            required_skills=["actuarial modelling"],
        ),
    ]

    result = rank_roles(
        candidates,
        saved_roles=[saved],
        discovery_events=[
            _event("credit risk", {"sectors": ["Banking"], "seniority": ["mid"]})
        ],
        saved_refs={(saved.source, saved.source_id)},
        page=1,
        page_size=6,
        now=NOW,
    )

    assert result.personalized is True
    assert result.items[0].job.source_id == "risk"
    assert result.items[0].score > result.items[1].score
    assert any("credit risk" in reason.lower() for reason in result.items[0].reasons)


def test_saved_roles_are_never_recommended_back_to_the_seeker():
    saved = _role("saved", title="Credit Risk Analyst")
    result = rank_roles(
        [saved, _role("other", company="AIA", sector="Insurance")],
        saved_roles=[saved],
        discovery_events=[],
        saved_refs={(saved.source, saved.source_id)},
        page=1,
        page_size=6,
        now=NOW,
    )
    assert [item.job.source_id for item in result.items] == ["other"]


def test_each_employer_gets_one_slot_before_a_repeat():
    candidates = [
        _role("hsbc-1", title="Credit Risk Manager"),
        _role("hsbc-2", title="Credit Risk Analyst"),
        _role("hsbc-3", title="Risk Governance Lead"),
        _role("aia", company="AIA", sector="Insurance", title="Risk Manager"),
        _role("axa", company="AXA", sector="Insurance", title="Risk Analyst"),
    ]
    result = rank_roles(
        candidates,
        saved_roles=[],
        discovery_events=[_event("risk")],
        saved_refs=set(),
        page=1,
        page_size=3,
        now=NOW,
    )
    assert len({item.job.company for item in result.items}) == 3


def test_cold_start_is_explicitly_market_based_and_still_diverse():
    candidates = [
        _role("hsbc-1"),
        _role("hsbc-2"),
        _role("aia", company="AIA", sector="Insurance"),
    ]
    result = rank_roles(
        candidates,
        saved_roles=[],
        discovery_events=[],
        saved_refs=set(),
        page=1,
        page_size=2,
        now=NOW,
    )
    assert result.personalized is False
    assert len({item.job.company for item in result.items}) == 2
    assert all(item.reasons == ("Recently listed",) for item in result.items)


def test_numeric_and_market_filter_preferences_affect_ranking():
    matching = _role(
        "matching",
        company="Zeta Capital",
        source_tier="boutique",
        salary_hkd_min=80_000,
        salary_hkd_max=95_000,
        years_experience_required=2,
        board_signals={
            "indeed": {"urgently_hiring": True, "applicant_count": 18}
        },
    )
    mismatch = _role(
        "mismatch",
        company="AIA",
        source_tier="mainstream",
        salary_hkd_min=40_000,
        salary_hkd_max=55_000,
        years_experience_required=8,
        board_signals={"indeed": {"applicant_count": 300}},
    )
    result = rank_roles(
        [mismatch, matching],
        saved_roles=[],
        discovery_events=[
            _event(
                filters={
                    "tier": "boutique",
                    "salary_min": 70_000,
                    "salary_disclosed_only": True,
                    "exp_max": 3,
                    "urgently_hiring": True,
                    "max_applicants": 50,
                    "is_internship": False,
                }
            )
        ],
        saved_refs=set(),
        page=1,
        page_size=2,
        now=NOW,
    )

    assert result.items[0].job.source_id == "matching"
    assert any("salary" in reason.lower() for reason in result.items[0].reasons)
