"""Contract tests for bounded, local resume extraction."""

from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import pytest
from reportlab.pdfgen import canvas

BACKEND = Path(__file__).resolve().parent.parent / "webapp" / "backend"
sys.path.insert(0, str(BACKEND))

from resume_intelligence import (  # noqa: E402
    DOCX_MEDIA_TYPE,
    MAX_RESUME_BYTES,
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
