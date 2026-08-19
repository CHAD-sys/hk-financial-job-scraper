"""Contract tests for bounded, local resume extraction."""

from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path
from datetime import datetime, timezone
from xml.sax.saxutils import escape

import pytest
from reportlab.pdfgen import canvas

BACKEND = Path(__file__).resolve().parent.parent / "webapp" / "backend"
sys.path.insert(0, str(BACKEND))

from resume_intelligence import (  # noqa: E402
    DOCX_MEDIA_TYPE,
    _dated_spans,
    _heading_kind,
    MAX_RESUME_BYTES,
    MAX_SKILLS,
    ResumeValidationError,
    analyse_resume,
    evidence_from_storage,
    parse_resume,
    rank_resume_matches,
    score_resume_fit,
)
from job_read import JobSummary  # noqa: E402


def make_docx(text: str) -> bytes:
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f'<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>'
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", "<Types />")
        package.writestr("word/document.xml", document)
    return buffer.getvalue()


def make_pdf(text: str) -> bytes:
    buffer = io.BytesIO()
    document = canvas.Canvas(buffer)
    document.drawString(72, 760, text)
    document.save()
    return buffer.getvalue()


def role(source_id: str, **over) -> JobSummary:
    data = {
        "source": "workday",
        "source_id": source_id,
        "company": "HSBC",
        "sector": "Banking",
        "title": "Analyst",
        "source_tier": "mainstream",
        "url": f"https://example.test/{source_id}",
        "posted_at": "2026-08-09T00:00:00+00:00",
    }
    data.update(over)
    return JobSummary(**data)


def test_docx_extraction_returns_bounded_first_party_text():
    data = make_docx(
        "Credit Risk Analyst with five years of banking experience, SQL, Python and Basel III."
    )

    parsed = parse_resume("Ada Resume.docx", DOCX_MEDIA_TYPE, data)

    assert parsed.filename == "Ada Resume.docx"
    assert parsed.media_type == DOCX_MEDIA_TYPE
    assert parsed.size_bytes == len(data)
    assert len(parsed.content_sha256) == 64
    assert "Credit Risk Analyst" in parsed.text


def test_pdf_extraction_accepts_a_text_based_resume():
    data = make_pdf(
        "Actuarial Manager with eight years of insurance modelling experience and Python."
    )

    parsed = parse_resume("resume.pdf", "application/pdf", data)

    assert parsed.media_type == "application/pdf"
    assert "Actuarial Manager" in parsed.text


@pytest.mark.parametrize(
    ("filename", "content_type", "data", "message"),
    [
        ("resume.txt", "text/plain", b"plain text" * 20, "Only PDF and DOCX"),
        ("resume.pdf", "application/pdf", b"not a pdf" * 20, "is not a PDF"),
        ("resume.docx", DOCX_MEDIA_TYPE, b"not a docx" * 20, "is not a DOCX"),
        ("resume.docx", DOCX_MEDIA_TYPE, make_docx("tiny"), "selectable text"),
    ],
)
def test_unsupported_damaged_or_empty_files_are_rejected(
    filename: str, content_type: str, data: bytes, message: str
):
    with pytest.raises(ResumeValidationError, match=message):
        parse_resume(filename, content_type, data)


def test_resume_size_limit_is_enforced_before_parsing():
    with pytest.raises(ResumeValidationError, match="5 MB or smaller"):
        parse_resume("resume.pdf", "application/pdf", b"%PDF-" + b"x" * MAX_RESUME_BYTES)


def test_analysis_surfaces_reviewable_skills_role_sector_and_experience():
    parsed = parse_resume(
        "resume.docx",
        DOCX_MEDIA_TYPE,
        make_docx(
            "Senior Credit Risk Manager with 8 years of experience in banking. "
            "Skilled in credit risk, Basel III, SQL, Python, Excel and regulatory compliance."
        ),
    )

    analysis = analyse_resume(parsed)

    assert {"credit risk", "basel iii", "sql", "python", "excel"} <= set(analysis.skills)
    assert {"credit", "risk"} <= set(analysis.role_families)
    assert analysis.sectors == ("Banking",)
    assert analysis.years_experience == 8
    assert analysis.seniority == "senior"


def test_current_students_club_titles_do_not_read_as_senior():
    # HKUST-style undergrad CV: student-society titles ("Vice President", "Head of
    # ...") read exactly like corporate seniority to a naive keyword scan, and with
    # no explicit years of experience the classifier had nothing to weigh against them.
    parsed = parse_resume(
        "resume.docx",
        DOCX_MEDIA_TYPE,
        make_docx(
            "Second Year Computer Science Student, HKUST. Expected Graduation: 2028. "
            "Vice President, HKUST Data Science Society. Head of Data Analytics, "
            "Case Competition Club. Skilled in Python, SQL and Data Analysis."
        ),
    )

    analysis = analyse_resume(parsed)

    assert analysis.seniority == "junior"


def test_leadership_titles_outside_experience_section_do_not_inflate_seniority():
    # A genuinely junior professional (2 stated years) who also sits on a
    # volunteer board with a "Vice President"/"Head of" title. The bug isn't
    # student-specific: any title-keyword scan over the whole flattened resume
    # will misread a non-professional section as corporate seniority.
    parsed = parse_resume(
        "resume.docx",
        DOCX_MEDIA_TYPE,
        make_docx(
            "EXPERIENCE\n"
            "Data Analyst, ABC Bank, 2023-2025 (2 years of experience). "
            "Built dashboards with Python and SQL.\n"
            "VOLUNTEERING\n"
            "Vice President, Hong Kong Youth Alumni Association. "
            "Head of Fundraising, Local Charity Drive."
        ),
    )

    analysis = analyse_resume(parsed)

    assert analysis.years_experience == 2
    assert analysis.seniority == "junior"


def test_strong_matches_prioritise_observable_evidence_and_diversify_employers():
    parsed = parse_resume(
        "resume.docx",
        DOCX_MEDIA_TYPE,
        make_docx(
            "Credit Risk Analyst with 5 years of experience in banking, credit risk, "
            "financial modelling, SQL and Python."
        ),
    )
    analysis = analyse_resume(parsed)
    evidence = evidence_from_storage(parsed.text, analysis.as_dict())
    matching = role(
        "risk",
        company="Hang Seng Bank",
        title="Senior Credit Risk Analyst",
        seniority="mid",
        required_skills=["credit risk", "financial modelling", "SQL"],
        years_experience_required=4,
    )
    same_employer = role(
        "risk-2",
        company="Hang Seng Bank",
        title="Credit Risk Manager",
        required_skills=["credit risk", "SQL"],
    )
    second_employer = role(
        "model",
        company="Bank of China",
        title="Risk Modelling Analyst",
        required_skills=["financial modelling", "Python"],
    )
    unrelated = role(
        "actuary",
        company="AIA",
        sector="Insurance",
        title="Actuarial Manager",
        required_skills=["actuarial modelling"],
    )

    fit = score_resume_fit(matching, evidence)
    matches = rank_resume_matches(
        [unrelated, same_employer, second_employer, matching], evidence, limit=2
    )

    assert fit.score >= 80
    assert "credit risk" in fit.matched_skills
    assert any(reason.startswith("Skills aligned") for reason in fit.reasons)
    assert [item.job.source_id for item in matches] == ["risk", "model"]
    assert unrelated.source_id not in [item.job.source_id for item in matches]


def test_lead_seniority_roles_are_included_in_level_comparison():
    # "lead" is ~6% of live board seniority values (hk_jobs/schema.py's Literal
    # includes it) but was absent from the old junior/mid/senior/executive-only
    # levels map, so role.seniority == "lead" resolved to None and every match
    # against it silently skipped the level check entirely, in both directions.
    parsed = parse_resume(
        "resume.docx",
        DOCX_MEDIA_TYPE,
        make_docx(
            "Senior Risk Manager with 9 years of experience in banking. "
            "Skilled in credit risk and Python."
        ),
    )
    analysis = analyse_resume(parsed)
    assert analysis.seniority == "senior"
    evidence = evidence_from_storage(parsed.text, analysis.as_dict())
    # Title and sector deliberately avoid the family/sector bonuses so the
    # level-comparison reason isn't crowded out of the top-3 by other signals.
    lead_role = role(
        "lead-risk",
        sector="Insurance",
        title="Lead Data Platform Owner",
        seniority="lead",
        required_skills=["credit risk", "python"],
    )

    fit = score_resume_fit(lead_role, evidence)

    assert "Career level is close" in fit.reasons


def test_severe_seniority_mismatch_is_penalised_and_excluded_from_matches():
    # A junior candidate's resume can still rack up skill-keyword points against
    # a role several levels above them. Before this fix, seniority distance
    # beyond one level contributed a flat 0 — never a penalty — so a keyword
    # match alone was enough to rank a graduate resume against a C-suite role.
    parsed = parse_resume(
        "resume.docx",
        DOCX_MEDIA_TYPE,
        make_docx(
            "EXPERIENCE\n"
            "Graduate Analyst, ABC Bank. Skilled in Python and SQL."
        ),
    )
    analysis = analyse_resume(parsed)
    assert analysis.seniority == "junior"
    evidence = evidence_from_storage(parsed.text, analysis.as_dict())
    executive_role = role(
        "cto",
        sector="Insurance",
        title="Chief Technology Officer",
        seniority="executive",
        required_skills=["python", "sql"],
    )

    fit = score_resume_fit(executive_role, evidence)
    matches = rank_resume_matches([executive_role], evidence)

    assert "Career level looks like a mismatch" in fit.reasons
    assert fit.score < 25
    assert matches == ()


# --- Realistic-CV regression fixtures -------------------------------------
#
# The two tests above this block pass only because their fixtures are phrased
# to the regexes ("Second Year ... Student", "Expected Graduation: 2028",
# "(2 years of experience)"). Real CVs state date ranges and put titles on
# their own lines, which is what these fixtures do instead.

STUDENT_CV = """Jane Doe
Hong Kong | jane.doe@connect.hku.hk

EDUCATION
The University of Hong Kong
BBA (Hons) in Finance, Year 2
2024 - 2028

WORK EXPERIENCE
Goldman Sachs, Hong Kong
Summer Analyst Intern, Investment Banking Division
Jun 2026 - Aug 2026
- Built financial models and supported valuation work on M&A deals
- Reported directly to the Vice President covering capital markets

Deloitte, Hong Kong
Audit Intern
Jan 2026 - Mar 2026
- Assisted the Head of Assurance on IFRS financial reporting engagements

EXTRACURRICULAR ACTIVITIES & LEADERSHIP
HKU Finance Society
Vice President, External Affairs
- Led a team of 12 and managed a HKD 200,000 budget

SKILLS
Excel, Python, SQL, Bloomberg, financial modelling
"""

TREASURER_CV = """John Smith
Hong Kong

PROFESSIONAL EXPERIENCE
The Hong Kong Jockey Club
Treasurer
Feb 2024 - Dec 2024
- Owned group treasury operations, liquidity and cash flow analysis
- Managed FX and interest rate hedging across a HKD 30bn balance sheet

HSBC, Hong Kong
Treasury Manager, Asset and Liability Management
2018 - 2024
- Led balance sheet management and funding strategy

EDUCATION
CUHK, BBA Finance, 2014 - 2018
"""

SOCIETY_TREASURER_CV = """Amy Chan
Hong Kong

EDUCATION
CUHK, BBA in Accounting
2025 - 2029

INTERNSHIP EXPERIENCE
PwC Hong Kong
Assurance Intern
Jul 2027 - Aug 2027
- Supported IFRS financial reporting workstreams

POSITIONS OF RESPONSIBILITY
CUHK Accounting Society
Treasurer
- Managed the society budget and annual accounts
"""


def _analyse(text: str):
    # make_docx interpolates straight into XML, so "&" in headings and "M&A"
    # has to be escaped before it becomes a document part.
    payload = make_docx(escape(text))
    return analyse_resume(parse_resume("resume.docx", DOCX_MEDIA_TYPE, payload))


def test_second_year_student_with_only_internships_is_not_senior():
    # The reported bug: a 2nd-year undergraduate whose CV states "Year 2" and
    # "2024 - 2028" rather than the stock phrase "Second Year Student".
    analysis = _analyse(STUDENT_CV)

    assert analysis.seniority == "junior"


def test_supervisor_titles_in_bullets_do_not_set_seniority():
    # "Reported directly to the Vice President" and "Assisted the Head of
    # Assurance" name the candidate's supervisors, not the candidate.
    analysis = _analyse(STUDENT_CV)

    assert analysis.seniority != "senior"
    assert analysis.seniority != "executive"


def test_years_experience_is_derived_from_dated_roles():
    # No CV in the wild writes "6 years of experience"; they write "2018 - 2024".
    analysis = _analyse(TREASURER_CV)

    assert analysis.years_experience is not None
    assert 6 <= analysis.years_experience <= 8


def test_an_internship_only_student_has_no_meaningful_years():
    analysis = _analyse(STUDENT_CV)

    assert (analysis.years_experience or 0) <= 1


def test_treasury_is_a_recognised_role_family_and_skill_set():
    analysis = _analyse(TREASURER_CV)

    assert "treasury" in analysis.role_families
    assert "treasury operations" in analysis.skills
    assert "liquidity management" in analysis.skills


def test_a_career_treasurer_reads_as_senior():
    analysis = _analyse(TREASURER_CV)

    assert analysis.seniority in {"senior", "executive"}


def test_employer_names_imply_sector():
    analysis = _analyse(TREASURER_CV)

    assert "Banking" in analysis.sectors


def test_student_society_treasurer_is_not_senior():
    # "Treasurer" is a senior corporate officer AND the most common student
    # society title in Hong Kong. Section context is what separates them.
    analysis = _analyse(SOCIETY_TREASURER_CV)

    assert analysis.seniority == "junior"


# --- Layouts taken from two real Hong Kong finance CVs --------------------
#
# Both are anonymised rewrites that keep the structure that broke extraction:
# a stated career total sitting in a Summary/Career Profile section (which is
# not experience text), a "PROFESSIONAL CAREER" heading, and Hong Kong
# day-first dates. The real files are not committed.

SUMMARY_LED_CV = """EXECUTIVE SUMMARY & CORE COMPETENCES
Finance and Treasury Executive with 20 years of progressive leadership
experience spanning corporate treasury, asset management and business
development.

PROFESSIONAL CAREER
Group Treasurer
A Hong Kong Sports Club July 2024 - April 2025
- Owned group treasury, liquidity and capital management
Head of Treasury
Standard Chartered Bank Oct 2021 - Jul 2024
- Led regional cash management and funding strategy
"""

DAY_FIRST_DATES_CV = """CAREER PROFILE
16+ years of experiences in financial institutions space
Expertise in banking, treasury operations and liquidity management

EMPLOYMENT HISTORY
Manulife 31/07/2023 - now
Position: Director - Asia Treasury
- Managing regional banking relationships
Hang Seng Bank Limited 14/10/2015 - 02/10/2017
Position: Manager, Treasury
- Balance sheet management
"""


@pytest.mark.parametrize(
    "line,expected",
    [
        ("PROFESSIONAL CAREER", "experience"),
        ("EMPLOYMENT HISTORY", "experience"),
        ("CAREER PROFILE", "profile"),
        ("PROFESSIONAL QUALIFICATION", "education"),
        ("EXECUTIVE SUMMARY & CORE COMPETENCES", "profile"),
        # Wrapped body text ending on a bare heading word must not close a
        # section; a heading is never a sentence.
        ("activities.", None),
        ("- RFP", None),
        ("Standard Chartered Bank Oct 2021 - Jul 2024", None),
    ],
)
def test_heading_classification_matches_real_cv_headings(line, expected):
    assert _heading_kind(line) == expected


def test_a_stated_career_total_outside_the_experience_section_is_read():
    # Both real CVs state the total in a summary block. Reading years only
    # from the experience section threw the one number they actually give.
    analysis = _analyse(SUMMARY_LED_CV)

    assert analysis.years_experience == 20
    assert analysis.seniority in {"senior", "executive"}
    assert "treasury" in analysis.role_families


def test_hong_kong_day_first_dates_and_plural_experiences_are_read():
    analysis = _analyse(DAY_FIRST_DATES_CV)

    assert analysis.years_experience >= 16
    assert analysis.seniority == "senior"
    assert "treasury" in analysis.role_families


def test_day_first_and_month_first_ranges_both_parse():
    now = datetime(2026, 8, 1, tzinfo=timezone.utc)

    def months(text):
        return [end - start for start, end in _dated_spans(text, now)]

    assert months("22/04/2019 - 30/07/2023") == [51]   # Apr 2019 -> Jul 2023
    assert months("03/2019 - 11/2021") == [32]         # Mar 2019 -> Nov 2021
    assert months("31/07/2023 - now") == [37]          # Jul 2023 -> Aug 2026
    # A phone number, a salary band and a percentage range are not durations.
    assert _dated_spans("+852 9042 8479", now) == []
    assert _dated_spans("HKD 200,000 - 300,000", now) == []
    assert _dated_spans("achieved 15-20% growth", now) == []


def test_stored_evidence_keeps_every_skill_analysis_produces():
    # analyse_resume() writes the list and evidence_from_storage() reads it
    # back; when the two caps drifted apart the tail was silently dropped.
    skills = [f"skill {index}" for index in range(MAX_SKILLS)]
    evidence = evidence_from_storage("text", {"skills": skills})

    assert len(evidence.analysis.skills) == MAX_SKILLS


def test_a_technical_candidate_keeps_their_stack():
    analysis = _analyse(
        "Experience\n"
        "AI Engineer (Intern) May 2026 - Present\n"
        "- Built services with Python, FastAPI, Docker and PostgreSQL\n"
        "- Trained models with PyTorch, scikit-learn, pandas and NumPy\n"
    )

    assert {"python", "fastapi", "docker", "postgresql", "pytorch"} <= set(analysis.skills)


def test_a_project_blurb_does_not_award_a_role_family():
    # "for a portfolio manager" describes who a side project serves, not a job
    # the candidate held — and a role family is worth +20 in score_resume_fit.
    analysis = _analyse(
        "Experience\n"
        "Finance Intern Nov 2023 - Dec 2023\n"
        "- Supported budgeting and cash-flow monitoring\n"
        "Projects\n"
        "- Surfaces cited long/short signals for a portfolio manager\n"
    )

    assert "portfolio management" not in analysis.role_families


def test_hong_kong_finance_credentials_are_extracted():
    analysis = _analyse(
        "Experience\n"
        "Treasury Manager, A Bank 2015 - 2024\n"
        "- CFA and FRM certified; HKICPA member; CTP for treasury\n"
    )

    assert {"cfa", "frm", "cpa", "ctp"} <= set(analysis.certifications)


def test_a_credential_the_role_asks_for_is_named_in_the_reasons():
    analysis = _analyse(
        "Experience\nAnalyst, A Bank 2018 - 2024\n- CFA charterholder\n"
    )
    evidence = evidence_from_storage("cfa charterholder", analysis.as_dict())
    fit = score_resume_fit(role("r1", required_skills=["CFA", "valuation"]), evidence)

    assert any("CFA" in reason for reason in fit.reasons)


def test_stored_analysis_written_before_certifications_still_loads():
    # Rows saved by the previous version have no "certifications" key at all.
    evidence = evidence_from_storage("text", {"skills": ["python"]})

    assert evidence.analysis.certifications == ()


def test_an_accounting_firms_name_is_not_a_credential():
    # "Morison Heng CPA" is an employer. Hong Kong practices are routinely
    # named "<Partner> CPA", and reading that as a qualification credits the
    # candidate with a credential they never claimed.
    analysis = _analyse(
        "PROFESSIONAL CAREER\n"
        "Audit Associate\n"
        "Morison Heng CPA Jul 2002 - Dec 2003\n"
        "- Statutory audit engagements\n"
    )

    assert "cpa" not in analysis.certifications


def test_credentials_beside_the_name_are_kept():
    analysis = _analyse(
        "Morris H CFA, FCCA, CTP, LSSBB\n"
        "Mobile: +852 0000 0000\n"
        "PROFESSIONAL CAREER\n"
        "Group Treasurer\n"
        "A Sports Club July 2024 - April 2025\n"
    )

    assert {"cfa", "acca", "ctp"} <= set(analysis.certifications)
