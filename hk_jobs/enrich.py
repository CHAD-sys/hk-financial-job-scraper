"""
Rule-based enrichment layer.

Takes a Job whose description_clean has already been populated by an adapter
and fills in derived fields: seniority, employment_type, remote_type,
years_experience_min, and skills_required.

All logic here is deterministic regex / keyword matching — fast, free, and
easy to audit. An optional LLM pass can run afterwards for cases that need
higher-quality extraction; see enrich_with_llm() below.

Why rule-based first:
  - Deterministic output is easy to test and explain to end-users.
  - The vocabulary below already covers 90%+ of HK finance job postings.
  - Re-running enrichment on stored jobs is instant and costs nothing.
"""

import re
from typing import Iterable

from hk_jobs.schema import Job

# ── Skill vocabulary ──────────────────────────────────────────────────────────
# Grouped by category for readability and future extensibility.
# Phrases with spaces must appear here as-is; they are matched as whole
# phrases (not split into words) against the job text.

SKILL_CATEGORIES: dict[str, list[str]] = {
    "languages": [
        "python", "r", "java", "scala", "c++", "c#", "javascript", "typescript",
        "sql", "plsql", "bash", "vba", "matlab", "sas",
    ],
    "data": [
        "spark", "hadoop", "kafka", "airflow", "dbt", "snowflake", "databricks",
        "tableau", "power bi", "qlik", "excel", "pandas", "numpy", "scikit-learn",
        "tensorflow", "pytorch",
    ],
    "cloud": [
        "aws", "azure", "gcp", "google cloud", "kubernetes", "docker", "terraform",
    ],
    "finance_general": [
        "bloomberg", "reuters", "factset", "ifrs", "ifrs 9", "ifrs 17",
        "us gaap", "gaap", "cfa", "frm", "cpa", "caia",
        "financial modelling", "financial modeling", "dcf", "lbo",
        "valuation", "m&a", "ipo",
    ],
    "risk": [
        "var", "cvar", "expected shortfall", "stress testing", "scenario analysis",
        "basel iii", "basel iv", "basel", "credit risk", "market risk",
        "operational risk", "liquidity risk", "counterparty risk",
        "risk management", "risk framework", "irrbb",
    ],
    "compliance": [
        "kyc", "aml", "cdd", "edd", "fatf", "sanctions", "pep screening",
        "regulatory reporting", "mifid", "gdpr", "fatca", "crs",
        "hkma", "sfc", "mas", "sec", "compliance monitoring",
        "transaction monitoring",
    ],
    "trading": [
        "murex", "calypso", "summit", "fidessa", "bloomberg terminal",
        "fixed income", "equities", "derivatives", "fx", "rates",
        "structured products", "asset management", "portfolio management",
        "front office", "middle office", "back office",
    ],
    "actuarial": [
        "actuarial", "prophet", "moses", "igloo", "emblem", "reserving",
        "pricing", "life insurance", "non-life insurance", "reinsurance",
        "solvency ii", "rbc",
    ],
    "wealth_mgmt": [
        "wealth management", "private banking", "family office",
        "relationship management", "aum", "onboarding", "client suitability",
        "product suitability", "mpf",
    ],
    "frameworks": [
        "agile", "scrum", "jira", "confluence", "git", "ci/cd",
        "devops", "mlops", "rest api", "microservices",
    ],
}

# Flat set used for O(1) membership tests — normalised to lowercase
ALL_SKILLS: set[str] = {s.lower() for skills in SKILL_CATEGORIES.values() for s in skills}


# ── Compiled regex patterns ────────────────────────────────────────────────────

# Seniority detection — checked against title first, then description.
# Order matters: most-specific first so "senior manager" → "lead" not "senior".
_SENIORITY_PATTERNS: list[tuple[str, str]] = [
    (r"\b(c[- ]?suite|chief|ceo|cfo|coo|cto|cro)\b", "executive"),
    (r"\b(managing director|md\b|executive director|ed\b)\b", "executive"),
    (r"\b(head of|group head)\b", "executive"),
    (r"\b(director)\b", "executive"),
    (r"\b(vice president|vp\b)\b", "lead"),
    (r"\b(senior manager|principal|staff engineer|lead)\b", "lead"),
    (r"\b(manager)\b", "lead"),
    (r"\b(senior|sr\.)\b", "senior"),
    (r"\b(intern(ship)?|graduate trainee|trainee|placement)\b", "intern"),
    (r"\b(junior|jr\.)\b", "junior"),
    (r"\b(associate\b(?!.*manager))\b", "junior"),  # "Associate" alone = junior
    (r"\b(analyst|specialist|officer|consultant|advisor|adviser)\b", "mid"),
]
_SENIORITY_RES = [(re.compile(p, re.IGNORECASE), level) for p, level in _SENIORITY_PATTERNS]

# Years of experience — allows up to 2 adjective words between "years of" and
# "experience" (e.g. "5 years of actuarial experience", "3+ years of relevant work
# experience") without matching unrelated uses like "5 years ago... experience".
#
# The optional `(?:[-–]\s*\d+)?` right after the captured number absorbs an
# explicit range ("8-10 years experience", "8 – 12+ years") without capturing
# its high end — group(1) is always the LOW number. Without it, "8-10 years
# experience" only matched starting at "10" (a bare number can't be preceded
# by "-\d" and still match `\d+` at that position), so `_detect_years` reported
# the top of the range as the minimum required — the opposite of what "at
# least 8-10 years" means.
_YEARS_RE = re.compile(
    r"(\d+)\s*(?:[-–]\s*\d+)?\+?\s*(?:or more\s*)?years?(?:\s+of)?(?:\s+\w+){0,2}\s*experience",
    re.IGNORECASE,
)

# Remote type
_REMOTE_RE = re.compile(r"\bremote\b", re.IGNORECASE)
_HYBRID_RE = re.compile(r"\bhybrid\b", re.IGNORECASE)
# Negation guard: catches "Remote work not available", "not remote", etc.
# Looks for "not/no" within 40 characters of "remote" in either direction.
_REMOTE_NEGATED_RE = re.compile(
    r"\b(not|no)\b.{0,40}\bremote\b|\bremote\b.{0,40}\b(not|unavailable|n[/]?a)\b",
    re.IGNORECASE | re.DOTALL,
)

# Employment type — only used when the adapter hasn't already set it
_INTERN_RE = re.compile(r"\b(intern(ship)?|trainee|placement)\b", re.IGNORECASE)
_CONTRACT_RE = re.compile(r"\b(contract|contractor|temp(orary)?|fixed[- ]term)\b", re.IGNORECASE)
_PART_TIME_RE = re.compile(r"\bpart[- ]time\b", re.IGNORECASE)


# ── Public API ─────────────────────────────────────────────────────────────────

def enrich(job: Job) -> Job:
    """
    Populate derived fields on a Job from its title and clean description.

    Mutates and returns the same object. Fields the adapter already set
    (e.g. employment_type from Workday's timeType) are left unchanged.
    """
    text = f"{job.title} {job.description_clean}"
    title = job.title

    # Seniority: check title first (more reliable), fall back to full text
    job.seniority = _detect_seniority(title) or _detect_seniority(text) or "mid"

    # Employment type: only fill in what the adapter left blank
    if job.employment_type is None:
        job.employment_type = _detect_employment_type(text)

    # Remote type
    job.remote_type = _detect_remote_type(text)

    # Years of experience: take the minimum when multiple numbers appear
    job.years_experience_min = _detect_years(text)

    # Skills: whole-word/phrase match against combined title + description
    job.skills_required = _detect_skills(text)

    return job


def enrich_all(jobs: Iterable[Job]) -> list[Job]:
    """Run enrich() over every job in the iterable and return the enriched list."""
    return [enrich(job) for job in jobs]


def enrich_with_llm(job: Job) -> Job:
    """
    Placeholder for a future LLM-based enrichment pass.

    Where this would slot in:
      After rule-based enrich(), call this to improve fields that regex
      struggles with — nuanced seniority for non-standard titles,
      skills_preferred vs skills_required distinction, salary extraction
      from free text, and multi-language descriptions.

    Implementation plan (not yet built):
      1. Build a prompt with job.title + job.description_clean (≤ 2 000 tokens).
      2. Ask the model to return structured JSON matching the Job fields.
      3. Validate response with Pydantic; fall back to rule-based values on
         any validation error so a bad LLM response never corrupts stored data.
      4. Use prompt caching (Anthropic / OpenAI) to amortise costs when
         re-enriching large backlogs.

    This function intentionally does nothing so the pipeline can be shipped
    before the LLM integration is ready.
    """
    raise NotImplementedError(
        "LLM enrichment is not yet implemented. "
        "Call enrich() for the rule-based pass instead."
    )


# ── Private helpers ────────────────────────────────────────────────────────────

def _detect_seniority(text: str) -> str | None:
    """Return the first matching seniority level, or None if nothing matches."""
    for pattern, level in _SENIORITY_RES:
        if pattern.search(text):
            return level
    return None


def _detect_employment_type(text: str) -> str | None:
    if _INTERN_RE.search(text):
        return "internship"
    if _CONTRACT_RE.search(text):
        return "contract"
    if _PART_TIME_RE.search(text):
        return "part-time"
    # Default to full-time only when other signals are present to avoid
    # falsely tagging every job that doesn't mention employment type.
    return "full-time"


def _detect_remote_type(text: str) -> str | None:
    if _REMOTE_RE.search(text) and not _REMOTE_NEGATED_RE.search(text):
        return "remote"
    if _HYBRID_RE.search(text):
        return "hybrid"
    return "onsite"


def _detect_years(text: str) -> int | None:
    """Return the smallest years-of-experience number found, or None."""
    matches = [int(m.group(1)) for m in _YEARS_RE.finditer(text)]
    return min(matches) if matches else None


#: "R&D", "R&S" (Routing & Switching), "R & R" (rights & responsibilities) —
#: a bare `\br\b` word-boundary match cannot rule any of these out on its own,
#: because "&" is a non-word character, same as the space either side of a
#: genuine "Python, R" mention. Matches ANY two-letter "X&Y" acronym rather
#: than naming "D" specifically, and from either side — "R & R" has an R on
#: BOTH sides of the "&", so a check that only looks forward from "R&" misses
#: the second one. Every "r" occurrence has to clear this before the token
#: counts, so a job that ALSO genuinely mentions R elsewhere (e.g. "Python/R"
#: earlier in the same posting) still gets tagged correctly.
_TWO_LETTER_ACRONYM_RE = re.compile(r"\b([a-z])\s*&\s*([a-z])\b", re.IGNORECASE)


def _mentions_r_language(lower_text: str) -> bool:
    """Whether "r" appears as the language, not inside an "X&Y" acronym."""
    excluded = [m.span() for m in _TWO_LETTER_ACRONYM_RE.finditer(lower_text)]
    for m in re.finditer(r"\br\b", lower_text):
        if not any(start <= m.start() < end for start, end in excluded):
            return True
    return False


def _detect_skills(text: str) -> list[str]:
    """
    Match ALL_SKILLS entries against text using whole-word / whole-phrase
    boundaries. Returns a sorted, deduplicated list of matched skill strings.

    Multi-word skills (e.g. "credit risk") are matched as full phrases.
    Single-word skills are matched with \\b word boundaries to prevent
    false positives (e.g. "r" matching inside "our").
    """
    lower = text.lower()
    found: set[str] = set()
    for skill in ALL_SKILLS:
        if " " in skill:
            # Phrase match — just substring; spaces act as natural boundaries
            if skill in lower:
                found.add(skill)
        elif skill == "r":
            if _mentions_r_language(lower):
                found.add(skill)
        else:
            # Single-token: require word boundaries
            if re.search(rf"\b{re.escape(skill)}\b", lower):
                found.add(skill)
    return sorted(found)
