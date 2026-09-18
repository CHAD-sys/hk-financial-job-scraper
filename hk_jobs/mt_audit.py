"""Conservative evidence extraction for Management Trainee programme pages.

This module deliberately does not turn a reachable early-careers landing page
into an "open" claim. A status is only publishable when the page itself makes
that statement; everything else remains unknown for a human reviewer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import re


Status = str


@dataclass(frozen=True)
class PageClassification:
    status: Status
    deadline: date | None
    evidence: str


_SPACE = re.compile(r"\s+")
_RELEVANT_PROGRAMME = re.compile(
    r"\b(management\s+trainee|graduate(?:\s+(?:programme|program|scheme))?|internship)\b",
    re.IGNORECASE,
)
_CLOSED = re.compile(
    r"\b(applications?(?:\s+for\s+(?:this\s+)?(?:programme|program|role|position))?\s+(?:are\s+)?closed|"
    r"no\s+longer\s+(?:accepting\s+)?applications?|"
    r"(?:position|job)\s+(?:is\s+)?no\s+longer\s+available|position\s+has\s+been\s+filled|"
    r"job\s+has\s+expired)\b",
    re.IGNORECASE,
)
_OPEN = re.compile(
    r"\b(applications?\s+(?:are|is)\s+(?:now\s+)?open|"
    r"now\s+accepting\s+applications?)\b",
    re.IGNORECASE,
)
_DEADLINE_CONTEXT = re.compile(
    r"\b(?:apply\s+by|applications?\s+(?:close|closes|closing|deadline|due|(?:are\s+)?now\s+open\s+until))\b",
    re.IGNORECASE,
)
_DATE = re.compile(
    r"\b(?:"
    r"\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}|"
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}"
    r")\b",
    re.IGNORECASE,
)


def _sentence_containing(text: str, match: re.Match[str]) -> str:
    """Return a compact, reviewable excerpt around a recognised signal."""
    start = max(text.rfind(".", 0, match.start()) + 1, text.rfind("\n", 0, match.start()) + 1)
    end_candidates = [position for position in (text.find(".", match.end()), text.find("\n", match.end())) if position >= 0]
    end = min(end_candidates) + 1 if end_candidates else min(len(text), match.end() + 180)
    return _SPACE.sub(" ", text[start:end]).strip()[:280]


def parse_deadline(text: str) -> date | None:
    """Extract a date only when explicit application-deadline language precedes it."""
    for context in _DEADLINE_CONTEXT.finditer(text):
        window = text[context.start(): context.start() + 160]
        date_match = _DATE.search(window)
        if not date_match:
            continue
        value = date_match.group(0).replace(",", "")
        for fmt in ("%d %B %Y", "%B %d %Y"):
            try:
                return datetime.strptime(value.title(), fmt).date()
            except ValueError:
                pass
    return None


def classify_page(text: str, *, http_status: int, today: date | None = None) -> PageClassification:
    """Classify a fetched page without inferring recruitment status from reachability.

    ``unavailable`` says the supplied link cannot be read, not that the
    programme itself is closed.  ``unknown`` is the intended result for broad
    careers landing pages and JavaScript-only ATS pages without usable evidence.
    """
    clean = _SPACE.sub(" ", text).strip()
    if http_status >= 400:
        return PageClassification("unavailable", None, f"HTTP {http_status}")

    closed = _CLOSED.search(clean)
    if closed:
        return PageClassification("closed", None, _sentence_containing(clean, closed))

    if not _RELEVANT_PROGRAMME.search(clean):
        return PageClassification("unknown", None, "No programme-specific status found on the fetched page")

    open_match = _OPEN.search(clean)
    deadline = parse_deadline(clean)
    if open_match:
        evidence = _sentence_containing(clean, open_match)
        # A malformed HTML page can concatenate the relevant sentence with a
        # long preceding block. Inspect a short forward window as well, so a
        # year such as "2021 Internship Program" cannot fall outside the excerpt.
        current_context = clean[open_match.start():open_match.start() + 1_000]
        years = [int(year) for year in re.findall(r"\b(20\d{2})\b", current_context)]
        if any(year < (today or date.today()).year for year in years):
            return PageClassification("unknown", None, "Open wording appears in a past recruitment cycle")
        # A past deadline means the fetched copy is stale. It must not be
        # published as open just because an old page still contains an Apply by line.
        if deadline and deadline < (today or date.today()):
            return PageClassification("unknown", None, "Application wording is paired with a past deadline")
        return PageClassification("open", deadline, evidence)

    return PageClassification("unknown", None, "No explicit open or closed application status found")
