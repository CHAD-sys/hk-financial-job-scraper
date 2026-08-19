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
#: v2 (2026-08-19): PDF text is read in layout mode, durations come from dated
#: roles, seniority is read from title lines only, and credentials are
#: extracted. Stored analyses from v1 stay wrong until scripts/reanalyse_resumes.py
#: is run — this constant only labels new recommendation_impressions rows.
MATCH_MODEL_VERSION = "resume-signals-v2"
MAX_PDF_PAGES = 40
MAX_DOCX_ENTRIES = 2_000
MAX_DOCX_UNCOMPRESSED_BYTES = 20 * 1024 * 1024
#: Kept in one place because analyse_resume() writes the list and
#: evidence_from_storage() reads it back; a mismatch drops skills on rehydration.
MAX_SKILLS = 32
MAX_CERTIFICATIONS = 12
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
#: "20 years of progressive leadership experience" and "16+ years of
#: experiences" are how real CVs phrase this; the original patterns allowed
#: only "N years of experience" with at most the word "relevant" in between.
_QUALIFIER = r"(?:[a-z][a-z\-]*\s+){0,3}"
_EXPERIENCE_PATTERNS = (
    re.compile(rf"\b(\d{{1,2}})\+?\s*(?:years?|yrs?)\s+of\s+{_QUALIFIER}experiences?\b"),
    re.compile(
        rf"\b(?:over|more than)\s+(\d{{1,2}})\s+years?\s+(?:of\s+)?{_QUALIFIER}experiences?\b"
    ),
    re.compile(r"\bexperiences?\s+of\s+(\d{1,2})\+?\s+years?\b"),
    re.compile(rf"\b(\d{{1,2}})\+?\s*(?:years?|yrs?)\s+{_QUALIFIER}experiences?\b"),
)
_SKILL_ALIASES = {
    "accounting": ("accounting",),
    "actuarial modelling": ("actuarial modelling", "actuarial modeling"),
    "anti-money laundering": ("anti-money laundering", "anti money laundering", "aml"),
    "asset liability management": (
        "asset and liability management", "asset liability management", "alm",
    ),
    "audit": ("audit", "auditing"),
    "balance sheet management": ("balance sheet management", "balance sheet"),
    "basel iii": ("basel iii", "basel 3"),
    "bloomberg": ("bloomberg",),
    "capital markets": ("capital markets",),
    "cash flow analysis": ("cash flow analysis", "cashflow analysis"),
    "cash management": ("cash management", "cash and liquidity management"),
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
    "foreign exchange": ("foreign exchange", "fx"),
    "fund accounting": ("fund accounting",),
    "funding": ("funding strategy", "wholesale funding", "funding"),
    "hedging": ("hedging", "hedge accounting"),
    "ifrs": ("ifrs",),
    "interest rate risk": ("interest rate risk", "irrbb", "interest rate"),
    "investment banking": ("investment banking",),
    "know your customer": ("know your customer", "kyc"),
    "liquidity management": ("liquidity management", "liquidity"),
    "liquidity risk": ("liquidity risk",),
    "market risk": ("market risk",),
    "portfolio management": ("portfolio management",),
    "power bi": ("power bi", "powerbi"),
    "private banking": ("private banking",),
    "project management": ("project management",),
    "airflow": ("airflow",),
    "aws": ("aws", "amazon web services"),
    "azure": ("azure",),
    "c++": ("c++", "c/c++"),
    "ci/cd": ("ci/cd", "continuous integration"),
    "docker": ("docker",),
    "fastapi": ("fastapi",),
    "gcp": ("gcp", "google cloud"),
    "git": ("git", "github", "gitlab"),
    "java": ("java",),
    "javascript": ("javascript",),
    "kafka": ("kafka",),
    "kubernetes": ("kubernetes", "k8s"),
    "linux": ("linux",),
    "machine learning": ("machine learning", "deep learning"),
    "matlab": ("matlab",),
    "mongodb": ("mongodb",),
    "natural language processing": ("natural language processing", "nlp"),
    "numpy": ("numpy",),
    "pandas": ("pandas",),
    "postgresql": ("postgresql", "postgres"),
    "prompt engineering": ("prompt engineering",),
    "python": ("python",),
    "pytorch": ("pytorch",),
    "react": ("react",),
    "retrieval augmented generation": (
        "retrieval-augmented generation", "retrieval augmented generation", "rag",
    ),
    "rest api": ("rest api", "rest apis", "restful"),
    "sas": ("sas",),
    "scala": ("scala",),
    "scikit-learn": ("scikit-learn", "scikit learn", "sklearn"),
    "spark": ("spark", "pyspark"),
    "tensorflow": ("tensorflow",),
    "terraform": ("terraform",),
    "typescript": ("typescript",),
    "regulatory compliance": ("regulatory compliance", "compliance"),
    "risk management": ("risk management",),
    "sql": ("sql",),
    "stakeholder management": ("stakeholder management",),
    "tableau": ("tableau",),
    "treasury operations": ("treasury operations", "treasury", "treasurer"),
    "valuation": ("valuation",),
    "vba": ("vba",),
    "wealth management": ("wealth management",),
}
#: Professional credentials. On a Hong Kong finance CV these are among the
#: most valuable tokens on the page — roles ask for them by name — and they
#: were previously extracted not at all. Kept separate from _SKILL_ALIASES so
#: a credential can be weighted as the hard qualification it is rather than
#: competing for one of the skill slots.
_CERTIFICATIONS = {
    "acca": ("acca", "fcca"),
    "caia": ("caia",),
    "cams": ("cams", "certified anti-money laundering specialist"),
    "cfa": ("cfa", "chartered financial analyst"),
    "cfp": ("cfp", "certified financial planner"),
    "cima": ("cima",),
    "cisa": ("cisa",),
    "cpa": ("cpa", "hkicpa", "certified public accountant"),
    "cqf": ("cqf",),
    "ctp": ("ctp", "certified treasury professional"),
    "frm": ("frm", "financial risk manager"),
    "hksi": ("hksi",),
    "lean six sigma": ("lean six sigma", "lssbb", "six sigma black belt"),
    "pmp": ("pmp",),
    "prm": ("prm",),
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
    "treasury": (
        "treasurer", "treasury", "treasury operations", "treasury manager",
        "asset and liability management", "cash management",
    ),
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
#: Mirrors hk_jobs/schema.py's `seniority` Literal so every level a role can
#: carry ("lead" included — ~6% of the live board) resolves to a rung here.
#: A candidate's own `analyse_resume()` label never produces "intern", but the
#: rung is kept so a role tagged "intern" still measures distance correctly
#: instead of silently dropping out of the comparison like "lead" used to.
_SENIORITY_LEVELS = {
    "intern": 0,
    "junior": 1,
    "mid": 2,
    "senior": 3,
    "lead": 4,
    "executive": 5,
}
#: A degree still in progress. Student-society titles ("Vice President", "Head of
#: ...") read exactly like corporate seniority to the keyword scan below, so a
#: current student is capped to "junior" regardless of what titles their CV lists
#: unless they also state real years of experience (see `analyse_resume`).
_CURRENTLY_STUDYING_RE = re.compile(
    r"\bexpected\s+(?:graduation|to\s+graduate)\b"
    r"|\bexpected[:\s]+[a-z]*\s*(?:19|20)\d{2}\b"
    r"|\banticipated\s+graduation\b"
    r"|\bclass\s+of\s+(?:19|20)\d{2}\b"
    r"|\bgraduating\b"
    r"|\bcurrently\s+(?:pursuing|studying|enrolled|reading)\b"
    r"|\bundergraduate\s+student\b"
    r"|\bfreshman\b"
    r"|\bsophomore\b"
    r"|\b(?:penultimate|final)\s+year\b"
    r"|\b(?:1st|2nd|3rd|4th|first|second|third|fourth)\s+year\s+student\b"
    r"|\byear\s*[1-4]\s+student\b"
)
#: Year-of-study and graduation-year signals, trusted only inside an Education
#: section. "Year 2" or "2024 - 2028" is how a real CV says "still studying";
#: neither phrase is safe to read anywhere else on the page.
_STUDY_YEAR_RE = re.compile(
    r"\b(?:1st|2nd|3rd|4th|first|second|third|fourth|final|penultimate)\s+year\b"
    r"|\byear\s*[1-4]\b"
)
_YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")

#: Duration is read from the dates a CV actually prints. The prose patterns
#: above ("5 years of experience") almost never appear on a real resume, so
#: without this every candidate arrived at the seniority ladder with
#: years_experience=None and was classified on title keywords alone.
_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*"
_DASH = r"(?:-|\u2010|\u2011|\u2012|\u2013|\u2014|to|until|through)"
_PRESENT = r"(?:present|current|now|to\s+date|ongoing|till\s+date)"
_MONTHS_INDEX = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
#: The lookbehinds keep this off a year that belongs to a numeric date, so
#: "31/07/2023 - now" is read once by _NUMERIC_RANGE_RE rather than a second
#: time here as a bare "2023 - now" that would overstate the span by six months.
_YEAR_START = r"(?<![/.\d])((?:19|20)\d{2})"
_DATE_RANGE_RE = re.compile(
    rf"(?:({_MONTH})\.?\s*,?\s*)?{_YEAR_START}"
    rf"\s*{_DASH}\s*"
    rf"(?:(?:({_MONTH})\.?\s*,?\s*)?{_YEAR_START}|({_PRESENT}))"
)
#: Accepts MM/YYYY and DD/MM/YYYY (the Hong Kong convention) with "/" or ".".
#: When three parts are present the middle one is the month.
_NUMERIC_RANGE_RE = re.compile(
    rf"(\d{{1,2}})[/.](?:(\d{{1,2}})[/.])?((?:19|20)\d{{2}})"
    rf"\s*{_DASH}\s*"
    rf"(?:(\d{{1,2}})[/.](?:(\d{{1,2}})[/.])?((?:19|20)\d{{2}})|({_PRESENT}))"
)
#: A bullet describes what someone did; a title line says who they were. Only
#: title lines carry seniority, which is what keeps "reported directly to the
#: Vice President" from promoting an intern.
_BULLET_RE = re.compile(r"^\s*(?:[-\u2013\u2014\u2022\u00b7\u25aa\u2023*o]\s+|\d+[.)]\s+)")
_TITLE_SCAN_CHARS = 90
_EXECUTIVE_TITLES = ("managing director", "chief ", "c-suite", "partner")
_SENIOR_TITLES = (
    "senior manager", "director", "vice president", "head of", "treasurer",
    "principal", "svp", "evp", "general manager",
)
_JUNIOR_TITLES = ("graduate", "intern", "junior analyst", "trainee", "placement")
#: Employer names carry sector far more reliably than a CV's prose does; the
#: generic aliases above only fire when someone literally writes "banking".
_EMPLOYER_SECTORS = {
    "Asset Management": (
        "blackrock", "fidelity", "invesco", "schroders", "pimco",
        "value partners", "amundi", "eastspring",
    ),
    "Banking": (
        "hsbc", "standard chartered", "hang seng bank", "bank of china",
        "bank of east asia", "dbs", "citibank", "icbc", "ocbc",
        "china construction bank", "boc hong kong",
    ),
    "Insurance": (
        "aia", "prudential", "manulife", "axa", "fwd", "chubb", "zurich",
        "sun life", "allianz",
    ),
    "Investment Banking": (
        "goldman sachs", "morgan stanley", "j.p. morgan", "jpmorgan", "nomura",
        "jefferies", "lazard", "rothschild", "ubs", "citic securities",
    ),
    "Professional Services": (
        "pwc", "pricewaterhousecoopers", "deloitte", "kpmg", "ernst and young",
        "ernst & young", "mckinsey", "bain", "boston consulting", "accenture",
    ),
}

#: Section headings that hold paid/professional work — years-of-experience and
#: seniority-title signals are only trustworthy inside these. A "Vice President"
#: or "Head of ..." under Leadership/Volunteering/Education is a club or
#: non-profit title, not a job title, and must not read as corporate seniority.
#: Words that mark a heading as paid/professional work. Years-of-experience and
#: seniority-title signals are only trustworthy inside these sections.
_HEADING_MARKERS_WORK = (
    "experience", "employment", "work history", "career", "internship",
    "professional background",
)
#: Words that end a work section. A "Vice President" or "Treasurer" under
#: Leadership, Activities or Positions of Responsibility is a club title, not a
#: job title. Matching is by marker word rather than whole-string equality so
#: combined headings ("EXTRACURRICULAR ACTIVITIES & LEADERSHIP") are caught too.
_HEADING_MARKERS_NONWORK = (
    "education", "academic", "qualification", "leadership", "activities",
    "extracurricular", "volunteer", "certification", "award", "honor", "honour",
    "skill", "project", "summary", "objective", "profile", "publication",
    "interest", "reference", "language", "responsibilit", "training", "hobbies",
)
_HEADING_MARKERS_EDUCATION = ("education", "academic", "qualification")
#: Summary / Profile / Skills blocks. These describe the candidate's own
#: career, so role families may be read from them — but seniority titles and
#: date ranges may not, because a summary is prose about a whole career rather
#: than a dated entry.
_HEADING_MARKERS_PROFILE = (
    "summary", "objective", "profile", "competenc", "skill", "expertise",
    "highlights", "strengths", "certification", "credential", "licen",
)
#: Words that confirm an acronym is a credential the candidate holds. Hong
#: Kong accounting firms are routinely named "<Partner> CPA", so a bare
#: acronym on an employer line is a company, not a qualification.
_CREDENTIAL_CONTEXT_RE = re.compile(
    r"certified|charterholder|charter\s+holder|qualified|member|licen[cs]ed"
    r"|designation|credential|holder|passed|charter\b"
)
#: Title-case headings that carry no marker capitalisation cue of their own.
_KNOWN_HEADINGS = frozenset({
    "experience", "work experience", "professional experience",
    "relevant experience", "employment history", "work history",
    "internship", "internships", "internship experience", "education",
    "leadership", "leadership experience", "activities", "volunteering",
    "certifications", "awards", "skills", "projects", "summary", "profile",
    "technical skills", "core competencies", "career profile",
    "professional career", "positions of responsibility",
    "extracurricular activities", "employment history",
})
_HEADING_TRAILER_RE = re.compile(r"[:\-–—]+$")
_HEADING_PUNCT_RE = re.compile(r"[^a-z0-9 ]+")


def _heading_kind(raw: str) -> str | None:
    """Classify one line as an "experience", "education" or "other" heading.

    Plain-text extraction drops every formatting cue except line breaks, so a
    heading is recognised by being either fully capitalised or a well-known
    heading phrase — and then by which marker words it carries.
    """
    line = _HEADING_TRAILER_RE.sub("", raw.strip())
    letters = [char for char in line if char.isalpha()]
    if not line or len(line) > 60 or not letters:
        return None
    # A heading is not a sentence. Wrapped body text whose last line happens to
    # be a single known-heading word ("...across the year's activities.") would
    # otherwise close the section it sits in.
    if line.endswith((".", ",", ";")):
        return None
    normalised = _HEADING_PUNCT_RE.sub(" ", line.replace("&", " and ").casefold())
    normalised = " ".join(normalised.split())
    if not normalised or len(normalised.split()) > 6:
        return None
    if not (all(char.isupper() for char in letters) or normalised in _KNOWN_HEADINGS):
        return None
    if any(marker in normalised for marker in _HEADING_MARKERS_NONWORK):
        if any(marker in normalised for marker in _HEADING_MARKERS_EDUCATION):
            return "education"
        if any(marker in normalised for marker in _HEADING_MARKERS_PROFILE):
            return "profile"
        return "other"
    if any(marker in normalised for marker in _HEADING_MARKERS_WORK):
        return "experience"
    return None


def _split_sections(text: str) -> tuple[str, str, str, str]:
    """Return (experience, education, profile, preamble) text, all casefolded.

    The preamble before the first heading (often a "results-driven analyst
    with N years..." summary line) counts as experience-relevant by default.
    A resume with no recognisable headings at all falls back to the full text
    unchanged — single-block resumes get the old behaviour, not a silent loss
    of signal.
    """
    bucket = "experience"
    saw_heading = False
    collected: dict[str, list[str]] = {
        "experience": [], "education": [], "profile": [], "preamble": [],
    }
    for line in text.split("\n"):
        kind = _heading_kind(line)
        if kind is not None:
            bucket, saw_heading = kind, True
            continue
        if not saw_heading:
            collected["preamble"].append(line)
        if bucket in collected:
            collected[bucket].append(line)
    if not saw_heading:
        return text.casefold(), "", "", text.casefold()
    return (
        "\n".join(collected["experience"]).casefold(),
        "\n".join(collected["education"]).casefold(),
        "\n".join(collected["profile"]).casefold(),
        "\n".join(collected["preamble"]).casefold(),
    )


def _month_index(year: int, month: int) -> int:
    return year * 12 + (month - 1)


def _dated_spans(text: str, now: datetime) -> list[tuple[int, int]]:
    """Every start→end month span the text states, as absolute month indices."""
    spans: list[tuple[int, int]] = []
    horizon = _month_index(now.year, now.month)

    def add(start: int, end: int) -> None:
        # A 45-year span is a parse accident (e.g. a phone number split by a
        # dash), not a career; drop it rather than let it dominate the sum.
        if 0 < end - start <= 12 * 45:
            spans.append((start, end))

    for match in _DATE_RANGE_RE.finditer(text):
        start_month, start_year, end_month, end_year, present = match.groups()
        start = _month_index(
            int(start_year), _MONTHS_INDEX.get((start_month or "jan")[:3], 1)
        )
        if present:
            end = horizon
        else:
            end = _month_index(
                int(end_year), _MONTHS_INDEX.get((end_month or "jan")[:3], 1)
            )
        add(start, end)

    for match in _NUMERIC_RANGE_RE.finditer(text):
        first, second, start_year, end_first, end_second, end_year, present = match.groups()
        start_month = int(second or first)
        if not 1 <= start_month <= 12:
            continue
        start = _month_index(int(start_year), start_month)
        if present:
            end = horizon
        else:
            end_month = int(end_second or end_first)
            if not 1 <= end_month <= 12:
                continue
            end = _month_index(int(end_year), end_month)
        add(start, end)
    return spans


def _years_from_spans(spans: list[tuple[int, int]]) -> int | None:
    """Total whole years covered, counting overlapping roles only once."""
    if not spans:
        return None
    merged: list[list[int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return sum(end - start for start, end in merged) // 12


def _certifications(text: str, credentials_zone: str) -> tuple[str, ...]:
    """Credentials the candidate holds, not ones their employer is named after."""
    found: list[str] = []
    for canonical, aliases in _CERTIFICATIONS.items():
        if any(_contains_phrase(credentials_zone, alias) for alias in aliases):
            found.append(canonical)
            continue
        for line in text.split("\n"):
            hits = [alias for alias in aliases if _contains_phrase(line, alias)]
            if not hits:
                continue
            # A spelled-out name is unambiguous anywhere; a bare acronym needs
            # something on the same line saying it is held.
            if any(" " in alias for alias in hits) or _CREDENTIAL_CONTEXT_RE.search(line):
                found.append(canonical)
                break
    return tuple(found)[:MAX_CERTIFICATIONS]


def _title_text(section: str) -> str:
    """The non-bullet lines of a section, where job titles actually live."""
    return "\n".join(
        line.strip()[:_TITLE_SCAN_CHARS]
        for line in section.split("\n")
        if line.strip() and not _BULLET_RE.match(line)
    )


def _is_currently_studying(text: str, education_text: str, now: datetime) -> bool:
    if _CURRENTLY_STUDYING_RE.search(text):
        return True
    if not education_text:
        return False
    if _STUDY_YEAR_RE.search(education_text):
        return True
    years = [int(year) for year in _YEAR_RE.findall(education_text)]
    return bool(years) and max(years) > now.year



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
    certifications: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {
            "skills": list(self.skills),
            "role_families": list(self.role_families),
            "sectors": list(self.sectors),
            "years_experience": self.years_experience,
            "seniority": self.seniority,
            "certifications": list(self.certifications),
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
    # "layout" keeps the visual line structure; the default mode shreds a
    # table-based CV into one word per line and glues headings onto the end of
    # whatever preceded them, which leaves nothing downstream can read. Real
    # CVs measured here went from 86% single-word lines to 5%, and one from
    # three lines to a hundred and eight.
    for mode in ("layout", "plain"):
        chunks: list[str] = []
        try:
            for page in reader.pages:
                chunks.append(page.extract_text(extraction_mode=mode) or "")
                if sum(len(chunk) for chunk in chunks) >= MAX_EXTRACTED_CHARS:
                    break
        except Exception as exc:
            if mode == "plain":
                raise ResumeValidationError("We could not read the text in that PDF.") from exc
            continue
        extracted = "\n".join(chunks)
        if len(extracted.strip()) >= MIN_EXTRACTED_CHARS:
            return extracted
    return ""


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
    now = datetime.now(timezone.utc)
    experience_text, education_text, profile_text, preamble_text = _split_sections(
        parsed.text
    )
    # Where a candidate speaks about their own career: dated work entries plus
    # any summary block. Deliberately excludes Projects, Leadership and
    # Education, where "...for a portfolio manager" describes someone else.
    career_text = f"{experience_text}\n{profile_text}"

    skills = tuple(
        canonical
        for canonical, aliases in _SKILL_ALIASES.items()
        if any(_contains_phrase(text, alias) for alias in aliases)
    )[:MAX_SKILLS]
    families = tuple(
        family
        for family, aliases in _ROLE_FAMILIES.items()
        if any(_contains_phrase(career_text, alias) for alias in aliases)
    )[:10]
    sectors = tuple(
        sector
        for sector, aliases in _SECTOR_ALIASES.items()
        if any(_contains_phrase(text, alias) for alias in aliases)
        or any(
            _contains_phrase(experience_text, employer)
            for employer in _EMPLOYER_SECTORS.get(sector, ())
        )
    )[:8]

    # Stated duration wins when a candidate claims more than their printed
    # dates cover; otherwise the dates are the only number most CVs offer.
    # A stated total ("20 years of ... experience") is a claim about the whole
    # career and is read from the whole page: both real CVs measured here put
    # it in a Summary or Career Profile section, which is not experience text.
    stated = [
        int(match.group(1))
        for pattern in _EXPERIENCE_PATTERNS
        for match in pattern.finditer(text)
        if 0 <= int(match.group(1)) <= 40
    ]
    dated = _years_from_spans(_dated_spans(experience_text, now))
    candidates = [value for value in (max(stated, default=None), dated) if value is not None]
    years = max(candidates) if candidates else None

    title_text = _title_text(experience_text)
    if any(term in title_text for term in _EXECUTIVE_TITLES):
        seniority = "executive"
    elif (years is not None and years >= 7) or any(
        term in title_text for term in _SENIOR_TITLES
    ):
        seniority = "senior"
    elif (years is not None and years <= 2) or any(
        term in title_text for term in _JUNIOR_TITLES
    ):
        seniority = "junior"
    elif years is not None or families:
        seniority = "mid"
    else:
        seniority = None

    if (years is None or years < 5) and _is_currently_studying(text, education_text, now):
        seniority = "junior"
    certifications = _certifications(
        text, f"{preamble_text}\n{profile_text}\n{education_text}"
    )
    return ResumeAnalysis(skills, families, sectors, years, seniority, certifications)


#: The fields a Seeker may correct by hand. Extraction is a heuristic over an
#: arbitrary PDF; when it is wrong the person who wrote the CV is the authority,
#: and their correction must survive a re-run of the extractor. Overrides are
#: therefore stored beside the extracted analysis, never merged into it — see
#: seekers_store.set_resume_analysis_override and scripts/reanalyse_resumes.py,
#: which rewrites only the extracted half.
OVERRIDABLE_FIELDS = ("seniority", "years_experience", "skills", "certifications")
#: Every rung the ladder can express, including the two analyse_resume() never
#: emits on its own — a Seeker who is genuinely an intern or a lead can say so.
SENIORITY_CHOICES = tuple(_SENIORITY_LEVELS)
MAX_OVERRIDE_VALUE_CHARS = 60


def sanitise_override(raw: dict) -> dict:
    """Validate one whole override object; `None` means "use the extraction".

    Whole-object PUT semantics: a field set to None is not stored, so clearing
    a correction is the same request shape as making one.
    """
    override: dict = {}

    seniority = raw.get("seniority")
    if seniority is not None:
        value = _normalise(seniority)
        if value not in SENIORITY_CHOICES:
            raise ResumeValidationError(
                "Choose a career level from the list."
            )
        override["seniority"] = value

    years = raw.get("years_experience")
    if years is not None:
        if isinstance(years, bool) or not isinstance(years, int) or not 0 <= years <= 60:
            raise ResumeValidationError(
                "Years of experience must be a whole number between 0 and 60."
            )
        override["years_experience"] = years

    for field, cap in (("skills", MAX_SKILLS), ("certifications", MAX_CERTIFICATIONS)):
        values = raw.get(field)
        if values is None:
            continue
        if not isinstance(values, list):
            raise ResumeValidationError(f"{field.replace('_', ' ').capitalize()} must be a list.")
        cleaned: list[str] = []
        for value in values:
            text = _normalise(value)[:MAX_OVERRIDE_VALUE_CHARS]
            if text and text not in cleaned:
                cleaned.append(text)
        if len(cleaned) > cap:
            raise ResumeValidationError(
                f"Keep {field.replace('_', ' ')} to {cap} entries or fewer."
            )
        override[field] = cleaned
    return override


def apply_override(analysis: dict, override: dict | None) -> dict:
    """The evidence as it should be used: extraction, with corrections on top."""
    effective = dict(analysis or {})
    for field in OVERRIDABLE_FIELDS:
        if override and field in override:
            effective[field] = override[field]
    return effective


def evidence_from_storage(text: str, analysis: dict) -> ResumeEvidence:
    """Rehydrate stored evidence without exposing storage details to rankers."""
    return ResumeEvidence(
        text=text.casefold(),
        analysis=ResumeAnalysis(
            skills=tuple(str(value) for value in analysis.get("skills", [])[:MAX_SKILLS]),
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
            certifications=tuple(
                str(value)
                for value in analysis.get("certifications", [])[:MAX_CERTIFICATIONS]
            ),
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

    # A credential the Role actually asks for is a harder qualification than a
    # keyword, and worth naming in the reasons rather than being folded
    # anonymously into "Skills aligned". Kept small because the skills block
    # above already counts it once.
    asked = _normalise(" ".join(role.required_skills[:20]))
    matched_certifications = tuple(
        credential
        for credential in evidence.analysis.certifications
        if _contains_phrase(asked, credential)
        or any(_contains_phrase(asked, alias) for alias in _CERTIFICATIONS.get(credential, ()))
    )
    if matched_certifications:
        score += 8
        label = ", ".join(value.upper() for value in matched_certifications[:2])
        reasons.append((8, f"Holds {label}"))

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

    # Independent of the years check above: two-thirds of live roles carry no
    # years_experience_required (LLM enrichment leaves it null far more often
    # than it leaves `seniority` null), so this is the signal that actually
    # runs for most roles. Distance is symmetric — it must catch a junior
    # candidate reading as a fit for a Director role via skill keywords alone
    # just as much as the reverse, which the old 0/5/10-only scale never did.
    candidate_level = _SENIORITY_LEVELS.get(evidence.analysis.seniority or "")
    role_level = _SENIORITY_LEVELS.get(_normalise(role.seniority))
    if candidate_level is not None and role_level is not None:
        distance = abs(candidate_level - role_level)
        if distance == 0:
            score += 10
            reasons.append((10, "Career level matches"))
        elif distance == 1:
            score += 4
            reasons.append((4, "Career level is close"))
        elif distance == 2:
            score -= 10
            reasons.append((-10, "Career level differs"))
        else:
            score -= 25
            reasons.append((-25, "Career level looks like a mismatch"))

    ordered = tuple(
        reason
        for _, reason in sorted(reasons, key=lambda item: (-abs(item[0]), item[1]))[:3]
    )
    return ResumeFit(max(0, min(100, score)), ordered, matched_skills)


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
