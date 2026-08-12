"""Private, deterministic resume extraction and Role-fit evidence.

The external seam is intentionally small: callers hand this module one upload
and receive validated text plus structured evidence. HTTP, sessions and SQLite
stay outside. Matching is added through the same seam below, so no route ever
needs to know how PDF streams, DOCX packages or career vocabulary work.

No resume content leaves this process. There is no LLM call and no third-party
parser: PDF text is read with pypdf and DOCX XML is read directly from the ZIP
package after bounded-size checks.
"""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePath
from typing import Iterable
from xml.etree import ElementTree

from pypdf import PdfReader

from job_read import JobSummary

MAX_RESUME_BYTES = 5 * 1024 * 1024
MATCH_MODEL_VERSION = "resume-signals-v1"
MAX_PDF_PAGES = 40
MAX_DOCX_ENTRIES = 2_000
MAX_DOCX_UNCOMPRESSED_BYTES = 20 * 1024 * 1024
MAX_EXTRACTED_CHARS = 120_000
MIN_EXTRACTED_CHARS = 40

PDF_MEDIA_TYPE = "application/pdf"
DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SPACE_RE = re.compile(r"[ \t\f\v]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")
_WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_TOKEN_RE = re.compile(r"[a-z0-9+#.]{2,}")
_EXPERIENCE_PATTERNS = (
    re.compile(r"\b(\d{1,2})\+?\s*(?:years?|yrs?)\s+of\s+(?:relevant\s+)?experience\b"),
    re.compile(r"\b(?:over|more than)\s+(\d{1,2})\s+years?\s+(?:of\s+)?experience\b"),
    re.compile(r"\bexperience\s+of\s+(\d{1,2})\+?\s+years?\b"),
)
_SKILL_ALIASES = {
    "accounting": ("accounting",),
    "actuarial modelling": ("actuarial modelling", "actuarial modeling"),
    "anti-money laundering": ("anti-money laundering", "anti money laundering", "aml"),
    "audit": ("audit", "auditing"),
    "basel iii": ("basel iii", "basel 3"),
    "bloomberg": ("bloomberg",),
    "capital markets": ("capital markets",),
    "cash flow analysis": ("cash flow analysis", "cashflow analysis"),
    "credit analysis": ("credit analysis",),
    "credit risk": ("credit risk",),
    "data analysis": ("data analysis", "data analytics"),
    "derivatives": ("derivatives",),
    "due diligence": ("due diligence",),
    "equity research": ("equity research",),
    "excel": ("microsoft excel", "excel"),
    "financial modelling": ("financial modelling", "financial modeling"),
    "financial reporting": ("financial reporting",),
    "fixed income": ("fixed income",),
    "fund accounting": ("fund accounting",),
    "ifrs": ("ifrs",),
    "investment banking": ("investment banking",),
    "know your customer": ("know your customer", "kyc"),
    "liquidity risk": ("liquidity risk",),
    "market risk": ("market risk",),
    "portfolio management": ("portfolio management",),
    "power bi": ("power bi", "powerbi"),
    "private banking": ("private banking",),
    "project management": ("project management",),
    "python": ("python",),
    "regulatory compliance": ("regulatory compliance", "compliance"),
    "risk management": ("risk management",),
    "sql": ("sql",),
    "stakeholder management": ("stakeholder management",),
    "tableau": ("tableau",),
    "valuation": ("valuation",),
    "vba": ("vba",),
    "wealth management": ("wealth management",),
}
_ROLE_FAMILIES = {
    "actuarial": ("actuary", "actuarial"),
    "audit": ("auditor", "audit"),
    "compliance": ("compliance officer", "compliance"),
    "consulting": ("consultant", "consulting"),
    "credit": ("credit analyst", "credit manager", "credit risk"),
    "data": ("data analyst", "data scientist", "data engineer", "analytics"),
    "finance": ("finance manager", "financial analyst", "accountant", "controller"),
    "investment banking": ("investment banker", "investment banking", "m&a"),
    "portfolio management": ("portfolio manager", "portfolio management"),
    "relationship management": ("relationship manager", "client relationship"),
    "risk": ("risk analyst", "risk manager", "risk management"),
    "technology": ("software engineer", "developer", "systems manager", "technology"),
    "trading": ("trader", "trading"),
}
_SECTOR_ALIASES = {
    "Asset Management": ("asset management", "fund management"),
    "Banking": ("banking", "commercial bank", "retail bank"),
    "Insurance": ("insurance", "insurer"),
    "Investment Banking": ("investment banking", "capital markets", "m&a"),
    "Professional Services": ("professional services", "consulting", "advisory"),
}
_TITLE_STOPWORDS = {
    "and", "for", "the", "with", "from", "senior", "junior", "assistant",
    "associate", "manager", "officer", "vice", "president", "lead", "head",
    "hong", "kong",
}
#: A degree still in progress. Student-society titles ("Vice President", "Head of
#: ...") read exactly like corporate seniority to the keyword scan below, so a
#: current student is capped to "junior" regardless of what titles their CV lists
#: unless they also state real years of experience (see `analyse_resume`).
_CURRENTLY_STUDYING_RE = re.compile(
    r"\bexpected\s+(?:graduation|to\s+graduate)\b"
    r"|\banticipated\s+graduation\b"
    r"|\bcurrently\s+pursuing\b"
    r"|\bundergraduate\s+student\b"
    r"|\bfreshman\b"
    r"|\bsophomore\b"
    r"|\b(?:1st|2nd|3rd|4th|first|second|third|fourth)\s+year\s+student\b"
    r"|\byear\s*[1-4]\s+student\b"
)

#: Section headings that hold paid/professional work — years-of-experience and
#: seniority-title signals are only trustworthy inside these. A "Vice President"
#: or "Head of ..." under Leadership/Volunteering/Education is a club or
#: non-profit title, not a job title, and must not read as corporate seniority.
_EXPERIENCE_SECTION_HEADINGS = frozenset({
    "experience", "work experience", "professional experience",
    "relevant experience", "employment history", "work history",
    "internship", "internships", "internship experience",
})
#: Headings that end an experience section without starting a new one. Plain
#: text extraction keeps line breaks but drops all other formatting (no bold,
#: no font size), so a heading line is the only structural signal available.
_OTHER_SECTION_HEADINGS = frozenset({
    "education", "leadership", "leadership experience", "activities",
    "leadership & activities", "leadership and activities",
    "extracurricular activities", "extracurriculars", "volunteering",
    "volunteer experience", "certifications", "awards", "honors", "honours",
    "skills", "technical skills", "core competencies", "projects",
    "summary", "objective", "profile", "publications", "interests",
    "references", "languages",
})
_HEADING_TRAILER_RE = re.compile(r"[:\-–—]+$")


def _experience_section_text(text: str) -> str:
    """Restrict `text` to Experience-type sections, if any are recognisable.

    The preamble before the first heading (often a "results-driven analyst
    with N years..." summary line) counts as experience-relevant by default.
    A resume with no recognisable headings at all falls back to the full
    text unchanged — single-block resumes get today's behaviour, not a
    silent loss of signal.
    """
    lines = text.split("\n")
    include = True
    saw_heading = False
    collected: list[str] = []
    for line in lines:
        heading = _HEADING_TRAILER_RE.sub("", line.strip())
        if heading in _EXPERIENCE_SECTION_HEADINGS:
            include, saw_heading = True, True
            continue
        if heading in _OTHER_SECTION_HEADINGS:
            include, saw_heading = False, True
            continue
        if include:
            collected.append(line)
    return "\n".join(collected) if saw_heading else text


class ResumeValidationError(ValueError):
    """A safe, user-displayable rejection of an uploaded resume."""


@dataclass(frozen=True)
class ParsedResume:
    filename: str
    media_type: str
    size_bytes: int
    content_sha256: str
    text: str


@dataclass(frozen=True)
class ResumeAnalysis:
    skills: tuple[str, ...]
    role_families: tuple[str, ...]
    sectors: tuple[str, ...]
    years_experience: int | None
    seniority: str | None

    def as_dict(self) -> dict:
        return {
            "skills": list(self.skills),
            "role_families": list(self.role_families),
            "sectors": list(self.sectors),
            "years_experience": self.years_experience,
            "seniority": self.seniority,
        }


@dataclass(frozen=True)
class ResumeEvidence:
    text: str
    analysis: ResumeAnalysis


@dataclass(frozen=True)
class ResumeFit:
    score: int
    reasons: tuple[str, ...]
    matched_skills: tuple[str, ...]


@dataclass(frozen=True)
class ResumeMatch:
    job: JobSummary
    score: int
    reasons: tuple[str, ...]


def _safe_filename(filename: str) -> str:
    # Backslashes are separators on Windows but not to PurePath on POSIX.
    leaf = PurePath((filename or "").replace("\\", "/")).name.strip()
    leaf = _CONTROL_RE.sub("", leaf)
    if not leaf or len(leaf) > 150:
        raise ResumeValidationError("Use a filename between 1 and 150 characters.")
    return leaf


def _clean_text(value: str) -> str:
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL_RE.sub("", text)
    text = "\n".join(_SPACE_RE.sub(" ", line).strip() for line in text.splitlines())
    return _BLANK_LINES_RE.sub("\n\n", text).strip()[:MAX_EXTRACTED_CHARS]


def _extract_pdf(data: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(data), strict=True)
    except Exception as exc:  # pypdf exposes several parser-specific failures
        raise ResumeValidationError("That PDF is damaged or is not a valid PDF file.") from exc
    if reader.is_encrypted:
        raise ResumeValidationError("Password-protected PDFs are not supported.")
    if len(reader.pages) > MAX_PDF_PAGES:
        raise ResumeValidationError(f"PDF resumes can contain at most {MAX_PDF_PAGES} pages.")
    chunks: list[str] = []
    try:
        for page in reader.pages:
            chunks.append(page.extract_text() or "")
            if sum(len(chunk) for chunk in chunks) >= MAX_EXTRACTED_CHARS:
                break
    except Exception as exc:
        raise ResumeValidationError("We could not read the text in that PDF.") from exc
    return "\n".join(chunks)


def _extract_docx(data: bytes) -> str:
    try:
        package = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ResumeValidationError("That DOCX is damaged or is not a valid Word file.") from exc

    with package:
        entries = package.infolist()
        if len(entries) > MAX_DOCX_ENTRIES:
            raise ResumeValidationError("That Word file contains too many embedded parts.")
        if sum(entry.file_size for entry in entries) > MAX_DOCX_UNCOMPRESSED_BYTES:
            raise ResumeValidationError("That Word file expands beyond the safe processing limit.")
        names = {entry.filename for entry in entries}
        if "word/document.xml" not in names:
            raise ResumeValidationError("That file is not a valid DOCX resume.")

        xml_names = [
            name
            for name in names
            if name == "word/document.xml"
            or re.fullmatch(r"word/(header|footer)\d+\.xml", name)
        ]
        chunks: list[str] = []
        try:
            for name in sorted(xml_names):
                root = ElementTree.fromstring(package.read(name))
                for paragraph in root.iter(f"{_WORD_NS}p"):
                    text = "".join(
                        node.text or "" for node in paragraph.iter(f"{_WORD_NS}t")
                    ).strip()
                    if text:
                        chunks.append(text)
                    if sum(len(chunk) for chunk in chunks) >= MAX_EXTRACTED_CHARS:
                        break
        except (ElementTree.ParseError, KeyError, RuntimeError) as exc:
            raise ResumeValidationError("We could not read the text in that DOCX.") from exc
    return "\n".join(chunks)


def parse_resume(filename: str, content_type: str | None, data: bytes) -> ParsedResume:
    """Validate one upload and return bounded extracted text.

    The extension, claimed MIME type and file signature must agree. Successful
    parsing says nothing about storage; callers can therefore validate a
    replacement fully before atomically superseding the previous resume.
    """
    safe_name = _safe_filename(filename)
    if not data:
        raise ResumeValidationError("Choose a PDF or DOCX resume to upload.")
    if len(data) > MAX_RESUME_BYTES:
        raise ResumeValidationError("Your resume must be 5 MB or smaller.")

    extension = PurePath(safe_name).suffix.casefold()
    claimed = (content_type or "").split(";", 1)[0].strip().casefold()
    if extension == ".pdf":
        if not data.startswith(b"%PDF-"):
            raise ResumeValidationError("The file extension says PDF, but the file is not a PDF.")
        if claimed and claimed not in {PDF_MEDIA_TYPE, "application/octet-stream"}:
            raise ResumeValidationError("Upload PDF files with the PDF file type.")
        media_type = PDF_MEDIA_TYPE
        extracted = _extract_pdf(data)
    elif extension == ".docx":
        if not data.startswith(b"PK"):
            raise ResumeValidationError("The file extension says DOCX, but the file is not a DOCX.")
        if claimed and claimed not in {DOCX_MEDIA_TYPE, "application/octet-stream"}:
            raise ResumeValidationError("Upload DOCX files with the Word document file type.")
        media_type = DOCX_MEDIA_TYPE
        extracted = _extract_docx(data)
    else:
        raise ResumeValidationError("Only PDF and DOCX resumes are supported.")

    text = _clean_text(extracted)
    if len(text) < MIN_EXTRACTED_CHARS:
        raise ResumeValidationError(
            "We could not find enough selectable text. Try a text-based PDF or DOCX."
        )
    return ParsedResume(
        filename=safe_name,
        media_type=media_type,
        size_bytes=len(data),
        content_sha256=hashlib.sha256(data).hexdigest(),
        text=text,
    )


def _contains_phrase(text: str, phrase: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", text) is not None


def analyse_resume(parsed: ParsedResume) -> ResumeAnalysis:
    """Turn extracted text into compact, reviewable career evidence."""
    text = parsed.text.casefold()
    skills = tuple(
        canonical
        for canonical, aliases in _SKILL_ALIASES.items()
        if any(_contains_phrase(text, alias) for alias in aliases)
    )[:24]
    families = tuple(
        family
        for family, aliases in _ROLE_FAMILIES.items()
        if any(_contains_phrase(text, alias) for alias in aliases)
    )[:10]
    sectors = tuple(
        sector
        for sector, aliases in _SECTOR_ALIASES.items()
        if any(_contains_phrase(text, alias) for alias in aliases)
    )[:8]

    experience_text = _experience_section_text(text)
    experience_values = [
        int(match.group(1))
        for pattern in _EXPERIENCE_PATTERNS
        for match in pattern.finditer(experience_text)
        if 0 <= int(match.group(1)) <= 40
    ]
    years = max(experience_values, default=None)
    if any(
        term in experience_text
        for term in ("managing director", "chief ", "c-suite", "partner")
    ):
        seniority = "executive"
    elif (years is not None and years >= 7) or any(
        term in experience_text
        for term in ("senior manager", "director", "vice president", "head of")
    ):
        seniority = "senior"
    elif (years is not None and years <= 2) or any(
        term in experience_text for term in ("graduate", "intern", "junior analyst")
    ):
        seniority = "junior"
    elif years is not None or families:
        seniority = "mid"
    else:
        seniority = None
    if (years is None or years < 5) and _CURRENTLY_STUDYING_RE.search(text):
        seniority = "junior"
    return ResumeAnalysis(skills, families, sectors, years, seniority)


def evidence_from_storage(text: str, analysis: dict) -> ResumeEvidence:
    """Rehydrate stored evidence without exposing storage details to rankers."""
    return ResumeEvidence(
        text=text.casefold(),
        analysis=ResumeAnalysis(
            skills=tuple(str(value) for value in analysis.get("skills", [])[:24]),
            role_families=tuple(
                str(value) for value in analysis.get("role_families", [])[:10]
            ),
            sectors=tuple(str(value) for value in analysis.get("sectors", [])[:8]),
            years_experience=analysis.get("years_experience")
            if isinstance(analysis.get("years_experience"), int)
            else None,
            seniority=str(analysis["seniority"])
            if analysis.get("seniority")
            else None,
        ),
    )


def _normalise(value: object) -> str:
    return " ".join(str(value or "").casefold().split())


def _skill_in_resume(skill: str, evidence: ResumeEvidence) -> bool:
    value = _normalise(skill)
    if not value:
        return False
    if _contains_phrase(evidence.text, value):
        return True
    aliases = _SKILL_ALIASES.get(value, ())
    return any(_contains_phrase(evidence.text, alias) for alias in aliases)


def score_resume_fit(role: JobSummary, evidence: ResumeEvidence) -> ResumeFit:
    """Score observable resume-to-Role alignment from 0–100, without eligibility claims."""
    matched_skills = tuple(
        dict.fromkeys(
            _normalise(skill)
            for skill in role.required_skills[:20]
            if _skill_in_resume(skill, evidence)
        )
    )
    score = min(60, len(matched_skills) * 15)
    reasons: list[tuple[int, str]] = []
    if matched_skills:
        label = ", ".join(matched_skills[:3])
        reasons.append((min(60, len(matched_skills) * 15), f"Skills aligned: {label}"))

    title_haystack = _normalise(f"{role.title} {role.title_en or ''} {role.job_category or ''}")
    matched_families = [
        family
        for family in evidence.analysis.role_families
        if family in title_haystack
        or any(alias in title_haystack for alias in _ROLE_FAMILIES.get(family, ()))
    ]
    if matched_families:
        score += 20
        reasons.append((20, f"Relevant {matched_families[0]} experience"))
    else:
        title_tokens = {
            token
            for token in _TOKEN_RE.findall(_normalise(role.title))
            if token not in _TITLE_STOPWORDS and len(token) >= 3
        }
        resume_tokens = set(_TOKEN_RE.findall(evidence.text))
        overlap = sorted(title_tokens & resume_tokens)
        if overlap:
            title_score = min(15, len(overlap) * 5)
            score += title_score
            reasons.append((title_score, f"Related role experience: {', '.join(overlap[:3])}"))

    if role.sector in evidence.analysis.sectors:
        score += 10
        reasons.append((10, f"Experience in {role.sector}"))

    years = evidence.analysis.years_experience
    if years is not None and role.years_experience_required is not None:
        if role.years_experience_required <= years + 1:
            score += 10
            reasons.append((10, "Experience level aligns"))
    elif evidence.analysis.seniority and role.seniority:
        levels = {"junior": 0, "mid": 1, "senior": 2, "executive": 3}
        candidate_level = levels.get(evidence.analysis.seniority)
        role_level = levels.get(_normalise(role.seniority))
        if candidate_level is not None and role_level is not None:
            level_score = 10 if candidate_level == role_level else (
                5 if abs(candidate_level - role_level) == 1 else 0
            )
            if level_score:
                score += level_score
                reasons.append((level_score, "Career level is close"))

    ordered = tuple(
        reason for _, reason in sorted(reasons, key=lambda item: (-item[0], item[1]))[:3]
    )
    return ResumeFit(min(100, score), ordered, matched_skills)


def _posted_timestamp(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment.timestamp()
    except ValueError:
        return 0.0


def rank_resume_matches(
    candidates: Iterable[JobSummary], evidence: ResumeEvidence, *, limit: int = 6
) -> tuple[ResumeMatch, ...]:
    """Return the strongest current Roles, diversified by employer."""
    scored = [
        ResumeMatch(role, fit.score, fit.reasons)
        for role in candidates
        if not role.closed and (fit := score_resume_fit(role, evidence)).score >= 25
    ]
    scored.sort(
        key=lambda item: (
            -item.score,
            -_posted_timestamp(item.job.posted_at),
            item.job.company.casefold(),
            item.job.source,
            item.job.source_id,
        )
    )
    selected: list[ResumeMatch] = []
    seen_employers: set[str] = set()
    safe_limit = max(1, min(int(limit), 12))
    for item in scored:
        employer = _normalise(item.job.company)
        if employer in seen_employers:
            continue
        seen_employers.add(employer)
        selected.append(item)
        if len(selected) == safe_limit:
            break
    if len(selected) < safe_limit:
        selected_refs = {(item.job.source, item.job.source_id) for item in selected}
        selected.extend(
            item
            for item in scored
            if (item.job.source, item.job.source_id) not in selected_refs
        )
    return tuple(selected[:safe_limit])
