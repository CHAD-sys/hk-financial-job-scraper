"""Tests for hk_jobs/enrich.py — rule-based enrichment."""

import pytest

from hk_jobs.enrich import ALL_SKILLS, SKILL_CATEGORIES, enrich, enrich_all, enrich_with_llm
from hk_jobs.schema import Job


def _job(title: str = "Analyst", description_clean: str = "", **overrides) -> Job:
    defaults = dict(
        source="test",
        source_id="TEST-1",
        company="TestCo",
        company_slug="testco",
        url="https://example.com/job/1",
        title=title,
        description_clean=description_clean,
    )
    defaults.update(overrides)
    return Job(**defaults)


# ── Vocabulary sanity ─────────────────────────────────────────────────────────

def test_all_skills_is_nonempty():
    assert len(ALL_SKILLS) > 50


def test_all_skills_are_lowercase():
    assert all(s == s.lower() for s in ALL_SKILLS)


def test_skill_categories_keys():
    expected = {"languages", "data", "cloud", "finance_general", "risk",
                "compliance", "trading", "actuarial", "wealth_mgmt", "frameworks"}
    assert set(SKILL_CATEGORIES.keys()) == expected


def test_finance_terms_present():
    for term in ("ifrs 17", "basel iii", "var", "kyc", "aml", "hkma", "sfc",
                 "mas", "cfa", "frm", "actuarial", "murex", "calypso"):
        assert term in ALL_SKILLS, f"Expected finance term {term!r} in ALL_SKILLS"


# ── Seniority ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("title,expected", [
    ("Chief Risk Officer", "executive"),
    ("Managing Director, Sales", "executive"),
    ("Head of Compliance", "executive"),
    ("Director, Finance", "executive"),
    ("Vice President, Risk Analytics", "lead"),
    ("Senior Manager, Technology", "lead"),
    ("Manager, Operations", "lead"),
    ("Senior Software Engineer", "senior"),
    ("Senior Analyst, AML", "senior"),
    ("Intern, Data Science", "intern"),
    ("Graduate Trainee Programme", "intern"),
    ("Junior Developer", "junior"),
    ("Associate, Compliance", "junior"),
    ("Credit Risk Analyst", "mid"),
    ("Compliance Officer", "mid"),
    ("Specialist, Wealth Management", "mid"),
])
def test_seniority_from_title(title, expected):
    job = enrich(_job(title=title))
    assert job.seniority == expected, (
        f"title={title!r}: expected {expected!r}, got {job.seniority!r}"
    )


def test_seniority_inferred_from_description_when_title_neutral():
    job = enrich(_job(title="Open Role", description_clean="We seek a senior candidate."))
    assert job.seniority == "senior"


def test_seniority_defaults_to_mid_when_nothing_matches():
    job = enrich(_job(title="Open Role", description_clean="No level indicated."))
    assert job.seniority == "mid"


def test_title_seniority_beats_description():
    # "Analyst" in title should give "mid"; description says "senior" — title wins
    job = enrich(_job(title="Analyst", description_clean="3 senior colleagues reporting in"))
    assert job.seniority == "mid"


# ── Employment type ───────────────────────────────────────────────────────────

def test_employment_type_not_overwritten_when_set():
    job = _job(employment_type="contract")
    enrich(job)
    assert job.employment_type == "contract"


def test_employment_type_internship_from_title():
    job = enrich(_job(title="Summer Internship, Technology"))
    assert job.employment_type == "internship"


def test_employment_type_contract_from_description():
    job = enrich(_job(description_clean="This is a 12-month fixed-term contract role."))
    assert job.employment_type == "contract"


def test_employment_type_part_time():
    job = enrich(_job(description_clean="Part-time position, 20 hours per week."))
    assert job.employment_type == "part-time"


def test_employment_type_defaults_full_time():
    job = enrich(_job())
    assert job.employment_type == "full-time"


# ── Remote type ───────────────────────────────────────────────────────────────

def test_remote_type_remote():
    job = enrich(_job(description_clean="This is a fully remote position."))
    assert job.remote_type == "remote"


def test_remote_type_hybrid():
    job = enrich(_job(description_clean="We offer a hybrid working arrangement."))
    assert job.remote_type == "hybrid"


def test_remote_type_defaults_onsite():
    job = enrich(_job(description_clean="Office-based in Hong Kong."))
    assert job.remote_type == "onsite"


# ── Years of experience ───────────────────────────────────────────────────────

def test_years_single():
    job = enrich(_job(description_clean="Requires 5 years experience in credit risk."))
    assert job.years_experience_min == 5


def test_years_plus_syntax():
    job = enrich(_job(description_clean="Minimum 3+ years of relevant experience."))
    assert job.years_experience_min == 3


def test_years_takes_minimum():
    job = enrich(_job(description_clean="3 years experience preferred; 7 years for senior track."))
    assert job.years_experience_min == 3


def test_years_none_when_absent():
    job = enrich(_job(description_clean="Great opportunity for motivated candidates."))
    assert job.years_experience_min is None


# ── Skills ────────────────────────────────────────────────────────────────────

def test_skills_single_word():
    job = enrich(_job(description_clean="Proficiency in Python and SQL required."))
    assert "python" in job.skills_required
    assert "sql" in job.skills_required


def test_skills_multi_word_phrase():
    job = enrich(_job(description_clean="Knowledge of credit risk and market risk frameworks."))
    assert "credit risk" in job.skills_required
    assert "market risk" in job.skills_required


def test_skills_finance_vocab():
    job = enrich(_job(description_clean="Experience with Basel III, VaR, and KYC/AML procedures."))
    assert "basel iii" in job.skills_required
    assert "var" in job.skills_required
    assert "kyc" in job.skills_required
    assert "aml" in job.skills_required


def test_skills_no_false_positive_r():
    # The single-letter skill "r" should NOT match inside the word "our" or "for"
    job = enrich(_job(description_clean="This role is for our compliance team."))
    assert "r" not in job.skills_required


def test_skills_r_matches_standalone():
    job = enrich(_job(description_clean="Programming in R and Python."))
    assert "r" in job.skills_required


def test_skills_are_sorted():
    job = enrich(_job(description_clean="Python, SQL, and AWS experience required."))
    assert job.skills_required == sorted(job.skills_required)


def test_skills_no_duplicates():
    # "aml" appears twice in text
    job = enrich(_job(description_clean="AML and anti-money-laundering (AML) work."))
    assert job.skills_required.count("aml") == 1


def test_skills_from_title_too():
    # Title is included in the search text
    job = enrich(_job(title="AML Compliance Officer"))
    assert "aml" in job.skills_required


# ── Finance-specific end-to-end case ─────────────────────────────────────────

def test_actuarial_analyst_case():
    """
    Actuarial Analyst role with IFRS 17 and 5 years experience.
    Verifies the finance vocabulary and all field extractions work together.
    """
    job = enrich(
        _job(
            title="Actuarial Analyst",
            description_clean=(
                "We are looking for an Actuarial Analyst to join our Life Insurance team. "
                "The successful candidate will work on IFRS 17 implementation and reserving. "
                "Requirements: 5 years of actuarial experience, knowledge of Prophet and "
                "Excel. Hybrid working available. This is a permanent full-time role."
            ),
        )
    )
    assert job.seniority == "mid"
    assert job.years_experience_min == 5
    assert job.remote_type == "hybrid"
    assert job.employment_type == "full-time"
    assert "actuarial" in job.skills_required
    assert "ifrs 17" in job.skills_required
    assert "prophet" in job.skills_required
    assert "excel" in job.skills_required


def test_compliance_vp_case():
    job = enrich(
        _job(
            title="Vice President, AML Compliance",
            description_clean=(
                "Lead the AML transaction monitoring team. The VP will oversee KYC, "
                "CDD and EDD processes in line with HKMA and SFC requirements. "
                "Minimum 8 years of relevant experience. Remote work not available."
            ),
        )
    )
    assert job.seniority == "lead"
    assert job.years_experience_min == 8
    assert job.remote_type == "onsite"
    assert "aml" in job.skills_required
    assert "kyc" in job.skills_required
    assert "hkma" in job.skills_required
    assert "sfc" in job.skills_required
    assert "transaction monitoring" in job.skills_required


# ── enrich_all ────────────────────────────────────────────────────────────────

def test_enrich_all_returns_all_jobs():
    jobs = [_job(title=f"Analyst {i}") for i in range(5)]
    result = enrich_all(jobs)
    assert len(result) == 5
    assert all(j.seniority is not None for j in result)


# ── enrich_with_llm stub ──────────────────────────────────────────────────────

def test_enrich_with_llm_raises_not_implemented():
    with pytest.raises(NotImplementedError):
        enrich_with_llm(_job())
