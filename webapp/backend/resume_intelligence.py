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
from functools import lru_cache
from pathlib import PurePath
from typing import Iterable
from xml.etree import ElementTree

import finance_vocabulary as vocabulary
from job_read import JobSummary
from pypdf import PdfReader

MAX_RESUME_BYTES = 5 * 1024 * 1024
#: v2 (2026-08-19): PDF text is read in layout mode, durations come from dated
#: roles, seniority is read from title lines only, and credentials are
#: extracted. Stored analyses from v1 stay wrong until scripts/reanalyse_resumes.py
#: is run — this constant only labels new recommendation_impressions rows.
MATCH_MODEL_VERSION = "resume-signals-v3"
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
#: Both halves of the vocabulary now live in `finance_vocabulary`: a
#: handwritten taxonomy of what a CANDIDATE writes (1,580 phrases across quant,
#: markets, risk, technology, banking, buy-side, accounting, compliance,
#: operations and platforms) and a mined table of what EMPLOYERS ask for
#: (10,047 terms with their document frequencies, built by
#: `scripts/mine_vocabulary.py`). This file used to carry 88 hand-typed skills
#: with no quant terms at all, which is how a Morgan Stanley Quantitative
#: Strategist read as `[data analysis, liquidity management, java, machine
#: learning, python, risk management]`.
_SKILL_ALIASES = vocabulary.skill_aliases()
#: Professional credentials. On a Hong Kong finance CV these are among the
#: most valuable tokens on the page — roles ask for them by name — and they
#: were previously extracted not at all. Kept separate from _SKILL_ALIASES so
#: a credential can be weighted as the hard qualification it is rather than
#: competing for one of the skill slots.
_CERTIFICATIONS = vocabulary.CERTIFICATIONS
_ROLE_FAMILIES = vocabulary.ROLE_FAMILIES
_SECTOR_ALIASES = vocabulary.SECTOR_ALIASES
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
_EMPLOYER_SECTORS = vocabulary.EMPLOYER_SECTORS

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
        searchable = _terms(canonical, aliases)
        if any(_contains_phrase(credentials_zone, alias) for alias in searchable):
            found.append(canonical)
            continue
        for line in text.split("\n"):
            hits = [alias for alias in searchable if _contains_phrase(line, alias)]
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
    #: The work-history-and-summary slice of the CV, casefolded — where a
    #: candidate writes about their OWN career, excluding Education and
    #: Projects. Carried on the evidence rather than re-derived per Role
    #: because `score_resume_fit` runs once for each of a 1,000-Role candidate
    #: window, and section-splitting the whole document 1,000 times to ask the
    #: same question is a thousandfold waste.
    career_text: str = ""


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


#: No English word reaches this length; `internationalisation` is 20 and is
#: about as long as real prose ever gets. An alphabetic run this long is a
#: rendering artefact, not a word, which makes it safe to treat as damaged.
GLUE_RUN_CHARS = 21
_GLUE_RUN_RE = re.compile(rf"[A-Za-z]{{{GLUE_RUN_CHARS},}}")
_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z])(?=[A-Z])")
#: A token carrying at least one internal lower->upper transition.
_CAMEL_TOKEN_RE = re.compile(r"\b[A-Za-z]*[a-z][A-Z][A-Za-z]*\b")
_SQUEEZE_RE = re.compile(r"[^a-z0-9]+")
#: A phrase must be at least this long, with its spaces removed, before we will
#: look for it INSIDE a glued run. Short phrases turn up inside long character
#: sequences by accident — "ratetrading" is a substring of "corporatetrading".
MIN_SQUEEZED_PHRASE = 11


def _squeeze(value: str) -> str:
    return _SQUEEZE_RE.sub("", value.casefold())


def glue_score(text: str) -> int:
    """How many words-run-together artefacts this extraction contains."""
    return len(_GLUE_RUN_RE.findall(text))


def _deglue(text: str) -> str:
    """Repair words run together by PDF extraction, and say what was recovered.

    Some PDFs — LaTeX output especially — render a styled run with no space
    glyphs between words, and every extractor hands that back as one token:
    `MorganStanley`, `BNPParibasCIB`,
    `Developedtheportfoliooptimisationframeworkusedtomanageovernightinventory`.
    Nothing downstream can match inside those, so a Morgan Stanley quant read
    as having no employer, no sector and no portfolio-optimisation experience.

    Two repairs, in order of how much they can be trusted:

    1. **Case boundaries.** `MorganStanley` -> `Morgan Stanley`. Deterministic,
       and it recovers the proper nouns — employers, institutions, headings —
       which is exactly where sector evidence lives.

    2. **Vocabulary probing.** A run that is still glued after (1) is all
       lowercase, so there is no structure left to split on. Instead we ask the
       finance vocabulary what it can find in there: squeeze the run to bare
       letters and test whether any known phrase, squeezed the same way, sits
       inside it. Every hit is appended, spaced, so the ordinary matcher can
       see it. We only ever do this INSIDE a run already established to be
       damaged, and only for phrases of `MIN_SQUEEZED_PHRASE` characters or
       more, which is what keeps an accidental substring from scoring.

    The original text is never edited in place — repairs are appended. A CV's
    own words stay exactly as written for every other reader of this text.
    """
    recovered: list[str] = []

    # (1) Case boundaries, at ANY length. `MorganStanley` is 13 characters, far
    # short of a "suspiciously long run", yet losing it costs the entire sector
    # signal. Splitting is safe at any length precisely because repairs are
    # APPENDED and never substituted: if a split is wrong, the original spelling
    # is still sitting in the text for the matcher to find. The >=3 guard just
    # keeps the noise down — it stops `PwC` becoming `Pw C`.
    for token in _CAMEL_TOKEN_RE.findall(text):
        parts = _CAMEL_BOUNDARY_RE.split(token)
        if len(parts) > 1 and all(len(part) >= 3 for part in parts):
            recovered.append(" ".join(parts))

    # (2) Vocabulary probing, for runs long enough to be certainly damaged.
    for run in _GLUE_RUN_RE.findall(text):
        squeezed = _squeeze(run)
        if len(squeezed) < MIN_SQUEEZED_PHRASE:
            continue
        for phrase, squeezed_phrase in _probe_phrases():
            if len(squeezed_phrase) >= MIN_SQUEEZED_PHRASE and squeezed_phrase in squeezed:
                recovered.append(phrase)

    if not recovered:
        return text
    unique = tuple(dict.fromkeys(recovered))
    return f"{text}\n{' '.join(unique)}"


@lru_cache(maxsize=1)
def _probe_phrases() -> tuple[tuple[str, str], ...]:
    """(phrase, squeezed phrase) for everything worth finding in a broken run.

    Handwritten phrases plus mined employer-written terms. Longest first, so a
    run yields `statistical arbitrage` rather than stopping at `arbitrage`.
    """
    phrases = set(vocabulary.all_phrases())
    phrases.update(vocabulary.mined().get("terms", {}))
    pairs = ((phrase, _squeeze(phrase)) for phrase in phrases)
    return tuple(
        sorted(
            ((phrase, squeezed) for phrase, squeezed in pairs if squeezed),
            key=lambda pair: (-len(pair[1]), pair[0]),
        )
    )


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
    #
    # But layout mode positions glyphs by coordinate, and on a PDF whose fonts
    # carry no usable advance widths — LaTeX output, typically — it emits whole
    # phrases with no spaces at all. A real CV measured here produced 10 glued
    # runs in layout mode and ZERO in plain, losing both employer names with
    # them. The old code returned layout the moment it cleared 40 characters,
    # so `plain` was unreachable for any PDF that yielded text at all.
    #
    # So: extract BOTH, and keep the one with fewer glue artefacts. Ties go to
    # layout, which is the better extraction whenever it is not broken.
    candidates: list[tuple[int, int, str]] = []
    for rank, mode in enumerate(("layout", "plain")):
        chunks: list[str] = []
        try:
            for page in reader.pages:
                chunks.append(page.extract_text(extraction_mode=mode) or "")
                if sum(len(chunk) for chunk in chunks) >= MAX_EXTRACTED_CHARS:
                    break
        except Exception:
            continue
        extracted = "\n".join(chunks)
        if len(extracted.strip()) >= MIN_EXTRACTED_CHARS:
            candidates.append((glue_score(extracted), rank, extracted))

    if not candidates:
        return ""
    return min(candidates)[2]


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

    text = _deglue(_clean_text(extracted))
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


#: An employer name must be at least this long, squeezed, before we will look
#: for it in a squeezed copy of the CV. Long and distinctive enough that an
#: accidental hit is not a realistic concern; `ey` and `citi` are matched by
#: the ordinary word-boundary path only.
MIN_SQUEEZED_EMPLOYER = 9


def _employer_named(experience: str, squeezed_experience: str, employer: str) -> bool:
    """Is this employer named in the work history — even if the PDF glued it?

    `_deglue` splits `MorganStanley` on its case boundary, but it cannot help
    with `BNPParibasCIB`, where the split lands in the wrong place and leaves
    `BNPParibas`. Employer names are a curated list of 225 long, distinctive
    strings, so for these — and only these — we also test against a copy of the
    text with every non-alphanumeric removed. `bnp paribas` -> `bnpparibas`
    then matches whatever the extractor did to the spacing.

    This is deliberately NOT how skills are matched: an arbitrary phrase
    squeeze-matched against arbitrary text collides too easily ("ratetrading"
    is inside "corporatetrading"). A closed list of proper nouns is a different
    risk profile from an open vocabulary.
    """
    if _contains_phrase(experience, employer):
        return True
    squeezed = _squeeze(employer)
    return len(squeezed) >= MIN_SQUEEZED_EMPLOYER and squeezed in squeezed_experience


def _terms(canonical: str, aliases: tuple[str, ...]) -> tuple[str, ...]:
    """A canonical term and its aliases, as one searchable tuple.

    `finance_vocabulary` does not repeat a key inside its own alias tuple —
    `"cfa": ("chartered financial analyst", ...)`, not `("cfa", "chartered
    ...")` — because 1,580 phrases is too many to keep duplicated by hand.
    Every consumer must therefore search the key as well, and this is the one
    place that knows it.
    """
    return (canonical, *aliases)


@lru_cache(maxsize=16_384)
def _phrase_pattern(phrase: str) -> re.Pattern[str]:
    """Compiled whole-phrase matcher, cached.

    Ranking one Seeker against a ~1,100-Role candidate pool runs ~81,000 phrase
    tests. `re`'s own cache holds 512 patterns and this vocabulary has
    thousands, so it thrashed: half the ranking time was spent RE-COMPILING
    patterns it had already compiled. Measured at 3.0s per ranking before,
    which is not a number an API request can carry.
    """
    return re.compile(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])")


def _contains_phrase(text: str, phrase: str) -> bool:
    return _phrase_pattern(phrase).search(text) is not None


@lru_cache(maxsize=512)
def _any_phrase_pattern(phrases: tuple[str, ...]) -> re.Pattern[str] | None:
    """One whole-word alternation over a whole set of phrases.

    A role family carries ~10 aliases and a Seeker carries ~7 families, so
    testing them one at a time cost ~70 regex searches per Role and ~75,000
    per ranking pass — by far the hot path. One alternation answers the same
    question in a single search, and the engine shares prefix work across the
    branches while it does it.
    """
    if not phrases:
        return None
    body = "|".join(re.escape(phrase) for phrase in sorted(set(phrases), key=len, reverse=True))
    return re.compile(rf"(?<![a-z0-9])(?:{body})(?![a-z0-9])")


def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    pattern = _any_phrase_pattern(phrases)
    return pattern is not None and pattern.search(text) is not None


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
    squeezed_experience = _squeeze(experience_text)

    skills = tuple(
        canonical
        for canonical, aliases in _SKILL_ALIASES.items()
        if any(_contains_phrase(text, alias) for alias in _terms(canonical, aliases))
    )[:MAX_SKILLS]
    families = tuple(
        family
        for family, aliases in _ROLE_FAMILIES.items()
        if any(_contains_phrase(career_text, alias) for alias in _terms(family, aliases))
    )[:10]
    sectors = tuple(
        sector
        for sector, aliases in _SECTOR_ALIASES.items()
        if any(_contains_phrase(text, alias) for alias in aliases)
        or any(
            _employer_named(experience_text, squeezed_experience, employer)
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
    experience_text, _education, profile_text, _preamble = _split_sections(text)
    return ResumeEvidence(
        text=text.casefold(),
        career_text=f"{experience_text}\n{profile_text}",
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


@lru_cache(maxsize=8_192)
def _skill_in_resume(skill: str, evidence: ResumeEvidence) -> bool:
    """Does this Role's required skill appear in the CV?

    Cached on (skill, evidence): one ranking pass asks the same question for
    the same CV hundreds of times, because `python` and `risk management` are
    required by hundreds of the Roles being scored. `ResumeEvidence` is a
    frozen dataclass of strings and tuples, so it hashes by value and two
    reads of the same stored resume share a cache entry.
    """
    value = _normalise(skill)
    if not value:
        return False
    if _contains_phrase(evidence.text, value):
        return True
    aliases = _SKILL_ALIASES.get(value, ())
    return any(_contains_phrase(evidence.text, alias) for alias in aliases)


#: The most one matched skill can be worth, before its rarity scales it down.
#: A single genuine specialism (`statistical arbitrage`, `q/kdb`) is worth more
#: than three generic ones, which is the whole point.
SKILL_POINTS = 22
#: Total the skills term can contribute, however many match.
SKILL_BUDGET = 55
#: A role-family (title) match, before recency scales it.
FAMILY_POINTS = 25
#: Below this, a role family found only at the BOTTOM of a work history — the
#: job someone left years ago — still counts, but not like their current one.
#: Never zero: a career changer's old field is real experience, just not what
#: they are doing now.
FAMILY_RECENCY_FLOOR = 0.45
#: Years of experience beyond which an internship is not a career step but a
#: category error, whatever its keywords say.
INTERNSHIP_IRRELEVANT_YEARS = 3
#: Below this many characters of work history, "where in the CV" carries no
#: recency signal — there is no sequence to hold a position within — so the
#: discount is not applied at all. Roughly one substantial role's worth.
MIN_CAREER_CHARS_FOR_RECENCY = 700


def _family_recency(career_text: str, terms: tuple[str, ...]) -> float:
    """How recent is the evidence for this role family? 1.0 (current) down to
    `FAMILY_RECENCY_FLOOR` (the bottom of the work history).

    CVs are written newest-first, so position in the experience section is a
    free, reliable recency signal — no date parsing, no assumption that every
    role carries a parseable range. The Morgan Stanley quant this was written
    for reads as `quantitative, trading, research, risk, data, product,
    consulting`: the `data` family comes from a Data Scientist job he left in
    2018, and scoring it like his current desk put HR Technology & Analytics
    roles among his best matches.

    Deliberately a soft weight, not a filter. A minority of CVs are not
    reverse-chronological, and being wrong about one should cost a few points,
    not erase real experience.
    """
    if len(career_text) < MIN_CAREER_CHARS_FOR_RECENCY:
        return 1.0
    positions = [
        match.start()
        for term in terms
        for match in [re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", career_text)]
        if match
    ]
    if not positions:
        return 1.0
    share = min(positions) / max(len(career_text), 1)
    return 1.0 - (1.0 - FAMILY_RECENCY_FLOOR) * share


def score_resume_fit(role: JobSummary, evidence: ResumeEvidence) -> ResumeFit:
    """Score observable resume-to-Role alignment from 0–100, without eligibility claims."""
    # Every matched skill is worth what it actually TELLS US, not one flat
    # fifteen points. `stakeholder management` is in 18.2% of HK postings and
    # `statistical arbitrage` in 0.02% — see `finance_vocabulary.rarity`. Under
    # the old flat scoring a Morgan Stanley quant's strongest matches were
    # "english" (his Languages line), "training" (from "strength training", in
    # his hobbies), "leadership" (his MPhil title) and "mathematics" (his
    # degree), which put a Compliance Manager above every real quant role.
    scored_skills = sorted(
        (
            (_normalise(skill), vocabulary.rarity(skill))
            for skill in dict.fromkeys(
                _normalise(value) for value in role.required_skills[:20]
            )
            if _skill_in_resume(skill, evidence)
        ),
        key=lambda pair: (-pair[1], pair[0]),
    )
    matched_skills = tuple(skill for skill, _ in scored_skills)
    telling = [skill for skill, weight in scored_skills if weight > 0]
    score = min(
        SKILL_BUDGET, round(sum(SKILL_POINTS * weight for _, weight in scored_skills))
    )
    reasons: list[tuple[int, str]] = []
    if telling:
        # Name the RAREST matches, not the first three alphabetically: they are
        # both the reason for the score and the only ones worth a Seeker's eye.
        reasons.append((score, f"Skills aligned: {', '.join(telling[:3])}"))

    # A credential the Role actually asks for is a harder qualification than a
    # keyword, and worth naming in the reasons rather than being folded
    # anonymously into "Skills aligned". Kept small because the skills block
    # above already counts it once.
    asked = _normalise(" ".join(role.required_skills[:20]))
    matched_certifications = tuple(
        credential
        for credential in evidence.analysis.certifications
        if _contains_phrase(asked, credential)
        or any(
            _contains_phrase(asked, alias)
            for alias in _CERTIFICATIONS.get(credential, ())
        )
    )
    if matched_certifications:
        score += 8
        label = ", ".join(value.upper() for value in matched_certifications[:2])
        reasons.append((8, f"Holds {label}"))

    title_haystack = _normalise(f"{role.title} {role.title_en or ''} {role.job_category or ''}")
    matched_families = [
        family
        for family in evidence.analysis.role_families
        if _contains_any(title_haystack, _terms(family, _ROLE_FAMILIES.get(family, ())))
    ]
    if matched_families:
        # Raised from 20. For a specialist the TITLE is the single strongest
        # signal available — "Quantitative Strategist" against a quant title
        # says more than any three keyword hits — and it was worth a third of
        # the keyword soup that used to dominate.
        #
        # Scaled by how recently the CV shows that family, so the desk someone
        # runs today outweighs the one they left eight years ago. Ranked by
        # weight, so the reason names their strongest family, not whichever
        # came first out of the dict.
        best_family, family_weight = max(
            (
                (
                    family,
                    _family_recency(
                        evidence.career_text,
                        _terms(family, _ROLE_FAMILIES.get(family, ())),
                    ),
                )
                for family in matched_families
            ),
            key=lambda pair: pair[1],
        )
        family_points = round(FAMILY_POINTS * family_weight)
        score += family_points
        reasons.append((family_points, f"Relevant {best_family} experience"))
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

    stated_years = evidence.analysis.years_experience
    if stated_years is not None and role.years_experience_required is not None:
        if role.years_experience_required <= stated_years + 1:
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

    # An internship is not a junior rung an experienced person could step down
    # to — it is a different kind of posting, usually closed to them outright.
    # The seniority ladder cannot express that: it scored the 2027 Global
    # Markets Summer Analyst as merely two levels away and left it second among
    # a Morgan Stanley VP's matches, on "programming" and "engineering".
    # `is_internship` is already derived on every Role (job_read.INTERNSHIP_COND);
    # nothing was reading it here.
    years = evidence.analysis.years_experience or 0
    if role.is_internship and years >= INTERNSHIP_IRRELEVANT_YEARS:
        return ResumeFit(0, ("Internship, and you are past that stage",), matched_skills)

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


# The bar a match must clear to count as a confident recommendation. Below it,
# `rank_resume_matches` still prefers RESUME_MATCH_FLOOR over showing nothing.
CONFIDENT_MATCH_SCORE = 25

# The floor below which a "match" carries no real signal and would mislead a
# Seeker rather than help them — the fallback tier below never dips under it.
# A single matched skill or a role-family match alone (worth 15 and 20 in
# score_resume_fit) clear it; a severe seniority mismatch does not, even after
# skill points, because that penalty is large enough to land well under 15
# (see test_severe_seniority_mismatch_is_penalised_and_excluded_from_matches).
RESUME_MATCH_FLOOR = 15


def rank_resume_matches(
    candidates: Iterable[JobSummary], evidence: ResumeEvidence, *, limit: int = 6
) -> tuple[ResumeMatch, ...]:
    """Return the strongest current Roles, diversified by employer.

    Never empty while an open candidate clears RESUME_MATCH_FLOOR. A resume
    whose only alignment with a Role is professional family — the field
    matches but no required_skill phrase appears verbatim on the page, e.g.
    "Actuarial Manager" against a Role requiring "actuarial modelling" — used
    to score exactly 20, one point short of the 25-point confident-match bar,
    and get thrown away entirely: a real, several-page finance resume could
    surface zero matches even though it named the right profession on line
    one (2026-09-07). Below the floor a candidate has no real signal (a severe
    seniority mismatch is penalised into single digits) and stays excluded —
    "never empty" does not mean "show anything".
    """
    fits = [
        (role, fit)
        for role in candidates
        if not role.closed and (fit := score_resume_fit(role, evidence)).score >= RESUME_MATCH_FLOOR
    ]
    confident = [(role, fit) for role, fit in fits if fit.score >= CONFIDENT_MATCH_SCORE]
    scored = [
        ResumeMatch(role, fit.score, fit.reasons) for role, fit in (confident or fits)
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


#: How many of a Seeker's skills to retrieve against. Each becomes an OR'd
#: EXISTS over `json_each(required_skills)`, so this is a query-cost knob as
#: much as a relevance one.
MAX_RETRIEVAL_TERMS = 24


def retrieval_terms(evidence: ResumeEvidence, limit: int = MAX_RETRIEVAL_TERMS) -> tuple[str, ...]:
    """The Seeker's most distinctive skills, spelled the way the BOARD spells them.

    Used to fetch candidates rather than to score them. Two translations have
    to happen, and both matter:

    * **Rarity first.** Retrieving on `risk management` returns 2,064 postings
      and tells us nothing; retrieving on `statistical arbitrage` returns four,
      and they are the four this person should see. We spend the budget on
      terms that discriminate.

    * **Their words into the employers'.** The board filter matches skill
      strings exactly (`LOWER(sk.value) = LOWER(?)`). A CV says `q/kdb`; the
      catalogue says `kdb`. So every skill is expanded through its aliases and
      only the spellings the catalogue actually uses are kept — anything else
      is a guaranteed-empty term burning a slot in the query.
    """
    mined_terms = vocabulary.mined().get("terms", {})
    aliases = vocabulary.skill_aliases()

    # One entry per SKILL, not per spelling. Ranking spellings directly spent
    # all 24 slots on `backtesting`/`back-testing` and `kdb`/`kdb+`/`q language`
    # — twelve skills wearing twenty-four hats — and never reached
    # `statistical arbitrage`. Within a skill the catalogue's commonest
    # spelling goes first, because it is the one most likely to hit.
    by_skill: list[tuple[float, str, list[str]]] = []
    for skill in evidence.analysis.skills:
        canonical = _normalise(skill)
        weight = vocabulary.rarity(canonical)
        if weight <= 0:
            continue
        spellings = sorted(
            (term for term in _terms(canonical, aliases.get(canonical, ())) if term in mined_terms),
            key=lambda term: (-mined_terms[term], term),
        )
        if spellings:
            by_skill.append((weight, canonical, spellings))

    by_skill.sort(key=lambda entry: (-entry[0], entry[1]))

    # Round-robin: every skill gets its best spelling before any skill gets a
    # second one, so a narrow budget still spans the whole specialism.
    chosen: list[str] = []
    for depth in range(max((len(entry[2]) for entry in by_skill), default=0)):
        for _weight, _canonical, spellings in by_skill:
            if depth < len(spellings) and len(chosen) < limit:
                chosen.append(spellings[depth])
    return tuple(chosen)
