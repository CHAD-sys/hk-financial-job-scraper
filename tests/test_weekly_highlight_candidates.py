"""The Sunday email is a shortlist for the next banner edit, not raw job spam."""

from __future__ import annotations

from datetime import date, timedelta

from hk_jobs.weekly_highlight_candidates import (
    build_weekly_highlight_email,
    select_weekly_highlight_candidates,
)
from tests.support import enrichment, job, make_jobs_db


def _role(
    source_id: str,
    *,
    company: str,
    title: str,
    category: str,
    salary_min: int,
    posted_at: str | None = None,
    **job_overrides,
):
    return (
        job(
            source="workday",
            source_id=source_id,
            company=company,
            title=title,
            posted_at=posted_at or date.today().isoformat(),
            **job_overrides,
        ),
        enrichment(
            source="workday",
            source_id=source_id,
            job_category=category,
            seniority="senior",
            salary_estimated_min=salary_min,
            salary_estimated_max=salary_min + 20_000,
            salary_estimated_confidence="high",
            description_summary=f"A strong {category.lower()} opportunity.",
        ),
    )


def test_selects_recent_visible_roles_above_the_40k_floor_across_pay_levels(tmp_path):
    rows = [
        _role(
            "executive",
            company="JPMorgan",
            title="Private Bank MD",
            category="Finance",
            salary_min=150_000,
        ),
        _role("senior", company="Citi", title="Credit VP", category="Risk", salary_min=85_000),
        _role(
            "established",
            company="Deloitte",
            title="Risk Manager",
            category="Operations",
            salary_min=45_000,
        ),
        _role(
            "too-low", company="Small Co", title="Analyst", category="Finance", salary_min=39_999
        ),
        _role(
            "closed",
            company="Closed Co",
            title="Director",
            category="Finance",
            salary_min=130_000,
            is_active=0,
        ),
        _role(
            "hidden",
            company="Hidden Co",
            title="Director",
            category="Finance",
            salary_min=130_000,
            admin_hidden=1,
        ),
        _role(
            "duplicate",
            company="Duplicate Co",
            title="Director",
            category="Finance",
            salary_min=130_000,
            is_primary=0,
        ),
        _role(
            "old",
            company="Old Co",
            title="Director",
            category="Finance",
            salary_min=130_000,
            posted_at=(date.today() - timedelta(days=45)).isoformat(),
        ),
    ]
    db = tmp_path / "jobs.db"
    make_jobs_db(db, jobs=[pair[0] for pair in rows], enrichments=[pair[1] for pair in rows])

    candidates = select_weekly_highlight_candidates(db, as_of=date.today(), limit=3)

    assert [candidate.salary_band for candidate in candidates] == [
        "Executive",
        "Senior",
        "Established",
    ]
    assert {candidate.source_id for candidate in candidates} == {
        "executive",
        "senior",
        "established",
    }
    assert all(candidate.salary_min >= 40_000 for candidate in candidates)


def test_shortlist_limits_one_employer_dominating_the_email(tmp_path):
    rows = [
        _role(
            f"mega-{index}",
            company="Mega Bank",
            title=f"Mega Role {index}",
            category="Finance",
            salary_min=150_000 - index * 1_000,
        )
        for index in range(6)
    ] + [
        _role("citi", company="Citi", title="Credit VP", category="Risk", salary_min=90_000),
        _role("ubs", company="UBS", title="Wealth Director", category="Sales", salary_min=80_000),
        _role("pwc", company="PwC", title="Risk Manager", category="Operations", salary_min=50_000),
    ]
    db = tmp_path / "jobs.db"
    make_jobs_db(db, jobs=[pair[0] for pair in rows], enrichments=[pair[1] for pair in rows])

    candidates = select_weekly_highlight_candidates(db, as_of=date.today(), limit=6)

    assert sum(candidate.company == "Mega Bank" for candidate in candidates) <= 2
    assert len({candidate.company for candidate in candidates}) >= 3


def test_email_names_the_upcoming_week_and_links_to_the_open_role(tmp_path):
    row, enriched = _role(
        "role-1",
        company="Bank & Co",
        title="Private Banking <Director>",
        category="Finance",
        salary_min=120_000,
    )
    db = tmp_path / "jobs.db"
    make_jobs_db(db, jobs=[row], enrichments=[enriched])
    candidates = select_weekly_highlight_candidates(db, as_of=date.today())

    subject, html, text = build_weekly_highlight_email(
        candidates,
        as_of=date(2026, 9, 6),
        site_url="https://www.finexcareers.com",
    )

    assert "7–13 Sep 2026" in subject
    assert "Private Banking &lt;Director&gt;" in html
    assert "role_source=workday" in html
    assert "role_id=role-1" in html
    assert "role_lookup=Private+Banking+%3CDirector%3E" in html
    assert "Private Banking <Director>" in text
    assert "HK$120k–140k/mo" in text


def test_daily_workflow_sends_only_mohamed_the_sunday_shortlist():
    workflow = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "daily.yml"
    ).read_text(encoding="utf-8")

    assert "TZ=Asia/Hong_Kong date +%u" in workflow
    assert "python -m hk_jobs.weekly_highlight_candidates" in workflow
    assert "NOTIFY_EMAILS: mohamedaminechahid@gmail.com" in workflow
