"""High-precision discovery rules for the Management Trainee catalogue.

The supplied workbook is represented by the existing frontend programme registry.
Reading that single checked-in source keeps the public watchlist and the database
discovery gate aligned without creating a second, hand-maintained company list.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
_CANONICAL_PROGRAMMES_FILE = ROOT / "webapp/frontend/src/content/managementTraineePrograms.ts"
# Railway uploads webapp/backend as /app, so the checked-in frontend source is
# staged beside the runtime package during deployment (see prepare script).
PROGRAMMES_FILE = (
    _CANONICAL_PROGRAMMES_FILE
    if _CANONICAL_PROGRAMMES_FILE.is_file()
    else ROOT / "mt_watchlist/managementTraineePrograms.ts"
)

# Broad enough only to reduce the SQLite candidate set.  Final inclusion always
# goes through ``classify_mt_role`` below.
MT_CANDIDATE_TITLE_TERMS = (
    "%management trainee%",
    "%manager trainee%",
)

_ROW_COMPANY = re.compile(r"\['([^']+)',\s*'[^']+'(?:,\s*true)?\]")
_OBJECT_COMPANY = re.compile(r"^\s*company:\s*'([^']+)'", re.MULTILINE)
_PAREN_CONTENT = re.compile(r"[\[(]([^\])]+)[\])]")
_PAREN_REMOVAL = re.compile(r"[\[(][^\])]*[\])]")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_LEGAL_SUFFIX = re.compile(r"\b(?:limited|ltd|inc|incorporated|company|co|llc)\b$")
_SPACE = re.compile(r"\s+")
_STRICT_TITLE = re.compile(
    r"\b(?:management|manager)\s+trainee"
    r"(?:\s+(?:programme|program|scheme))?\b|"
    r"\b(?:management|manager)\s+trainee\s*\(\s*mt\s*\)\b",
    re.IGNORECASE,
)
_REJECT_TITLE = re.compile(
    r"\b(?:graduate|intern|internship|apprentice|apprenticeship|programme\s+manager|program\s+manager|"
    r"training\s+manager|recruit(?:ment|er))\b",
    re.IGNORECASE,
)
_NON_HK_LOCATION = re.compile(r"\b(?:macau|singapore|london|new\s+york|mainland\s+china)\b", re.IGNORECASE)


@dataclass(frozen=True)
class MTClassification:
    """The explainable outcome of applying FinEx's precision-first MT policy."""

    is_mt: bool
    watchlist_company: str | None
    reason: str


def _normalise(value: str) -> str:
    value = value.lower().replace("&", " and ")
    value = _NON_ALNUM.sub(" ", value)
    value = _SPACE.sub(" ", value).strip()
    while _LEGAL_SUFFIX.search(value):
        value = _LEGAL_SUFFIX.sub("", value).strip()
    return value


def _aliases(company: str) -> set[str]:
    """Return deliberate textual aliases, never a fuzzy partial-company match."""
    candidates = {company, _PAREN_REMOVAL.sub(" ", company)}
    for content in _PAREN_CONTENT.findall(company):
        candidates.add(content)
    if "(" in company:
        candidates.add(company.split("(", 1)[0])
    if "[" in company:
        candidates.add(company.split("[", 1)[0])
    return {normalised for candidate in candidates if (normalised := _normalise(candidate))}


@lru_cache(maxsize=1)
def watchlist_company_aliases() -> dict[str, str]:
    """Map an exact normalised company alias to its workbook display name."""
    content = PROGRAMMES_FILE.read_text(encoding="utf-8")
    companies = [*_ROW_COMPANY.findall(content), *_OBJECT_COMPANY.findall(content)]
    aliases: dict[str, str] = {}
    for company in companies:
        for alias in _aliases(company):
            existing = aliases.get(alias)
            if existing and existing != company:
                raise ValueError(f"Ambiguous MT watchlist alias: {alias!r}")
            aliases[alias] = company
    return aliases


def classify_mt_role(company: str, title: str) -> MTClassification:
    """Accept only explicit MT titles from an exact supplied-workbook company.

    This intentionally misses some potential programmes.  A false inclusion is
    worse for this catalogue than an omission, so graduate programmes, generic
    early-careers pages, internships, and companies outside the supplied
    workbook always stay out.
    """
    if _REJECT_TITLE.search(title):
        return MTClassification(False, None, "Graduate, internship, apprenticeship, or non-role title")
    if _NON_HK_LOCATION.search(title):
        return MTClassification(False, None, "Title explicitly names a non-Hong-Kong location")

    watchlist_company = watchlist_company_aliases().get(_normalise(company))
    if not watchlist_company:
        return MTClassification(False, None, "Company is not on the supplied MT watchlist")
    if not _STRICT_TITLE.search(title):
        return MTClassification(False, watchlist_company, "Title is not an explicit Management Trainee title")
    return MTClassification(True, watchlist_company, "Exact watchlist company and explicit programme title")


def review_ambiguous_mt_role(company: str, title: str) -> MTClassification | None:
    """Return only workbook-backed near-matches that deserve human review.

    Hard rejections (internships and non-Hong-Kong roles) do not create admin
    noise.  This is a review queue, not a broader public discovery rule.
    """
    if _REJECT_TITLE.search(title) or _NON_HK_LOCATION.search(title):
        return None
    watchlist_company = watchlist_company_aliases().get(_normalise(company))
    if not watchlist_company or _STRICT_TITLE.search(title):
        return None
    if "trainee" not in title.lower() and "graduate" not in title.lower():
        return None
    return MTClassification(False, watchlist_company, "Workbook company with a trainee/graduate title that is not explicit enough to publish")
