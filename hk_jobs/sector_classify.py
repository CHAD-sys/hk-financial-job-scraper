"""
Deterministic (no-AI, no-network) sector classification for a job posting.

The `sector` badge shown on every job card used to be guessed purely from the
EMPLOYER's name: every job posted by UBS, Morgan Stanley, JPMorgan Chase etc.
was stamped "Investment Banking" even when the posting itself was for Private
Banking, Wealth Management, KYC, or any other function at that firm. Real HK
titles at those firms say so explicitly —

    "International Private Bank, Wealth Advisory, ... Associate"  (JPMorgan Chase)
    "Investment Consultant – Private Banking"                     (UBS)

— so a keyword check against the job's own TITLE catches this for free. No
LLM call, no schema migration, no backfill: pure string matching, safe to run
over the whole database in milliseconds, and cheap enough to recompute on
every read.

Rules are checked in order; the first match wins. Company-name matching is
kept as a fallback for jobs whose title gives no signal of its own (e.g. a
bare "Analyst" or "Associate").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

BANKING_FALLBACK = "Banking"


@dataclass(frozen=True)
class SectorRule:
    sector: str
    #: which side of the posting this rule reads — "title" or "company"
    column: str
    like_terms: Sequence[str] = field(default_factory=tuple)
    exact_terms: Sequence[str] = field(default_factory=tuple)

    def matches(self, title_lower: str, company_lower: str) -> bool:
        value = title_lower if self.column == "title" else company_lower
        return any(t in value for t in self.like_terms) or value in self.exact_terms

    def sql(self, title_col: str, company_col: str) -> str:
        col = title_col if self.column == "title" else company_col
        parts = [f"LOWER({col}) LIKE '%{t}%'" for t in self.like_terms]
        parts += [f"LOWER({col}) = '{t}'" for t in self.exact_terms]
        return "(" + " OR ".join(parts) + ")"


# Title-keyword rules are checked FIRST and apply regardless of employer —
# a private-banking title at ANY firm should read as Private Banking, not
# whatever bucket that firm's other business lines fall into.
_TITLE_RULES: tuple[SectorRule, ...] = (
    SectorRule(
        "Private Banking", "title",
        like_terms=("private bank", "wealth manag", "wealth advis"),
    ),
)

# Company-name rules (the original behaviour) — kept as the fallback for
# titles that give no signal of their own (e.g. "Analyst", "Associate").
# Professional services (Big 4): EY's advertiser is literally "EY", matched
# EXACTLY (exact_terms) — a "%ey%" LIKE would wrongly match money/survey/key.
_COMPANY_RULES: tuple[SectorRule, ...] = (
    SectorRule("Digital Assets", "company", like_terms=("hashkey",)),
    SectorRule(
        "Professional Services", "company",
        like_terms=("kpmg", "pwc", "pricewaterhouse", "deloitte", "ernst & young", "ernst and young"),
        exact_terms=("ey",),
    ),
    SectorRule(
        "Investment Banking", "company",
        like_terms=(
            "goldman", "morgan stanley", "deutsche bank", "barclays",
            "jpmorgan chase", "bank of america", "ubs",
            "hong kong exchanges",          # HKEX — market operator
            "futu", "cicc", "china international capital",
            "citic futures",                # CITIC Futures (brokerage); China CITIC Bank stays Banking
        ),
    ),
    SectorRule(
        "Insurance", "company",
        like_terms=(
            "manulife", "axa", "aia", "prudential", "fwd", "sun life",
            "zurich", "generali", "china life", "china pacific", "ping an",
            "chubb", "swiss re", "samsung life", "allianz", "nippon", "metlife",
        ),
    ),
    SectorRule(
        "Asset Management", "company",
        like_terms=(
            "blackrock", "value partners", "macquarie", "fidelity",
            "state street", "invesco", "bnp paribas am", "man group",
            "schroders", "northern trust", "jpm am", "pimco", "kkr",
            "franklin", "amundi",
        ),
    ),
)

#: Single ordered source of truth — both `classify_sector` (Python) and
#: `sector_case_sql` (SQL) are built from this list, so they cannot drift the
#: way the old hand-written negation used to.
RULES: tuple[SectorRule, ...] = _TITLE_RULES + _COMPANY_RULES

ALL_SECTORS: tuple[str, ...] = tuple(r.sector for r in RULES) + (BANKING_FALLBACK,)


def classify_sector(title: str | None, company: str | None) -> str:
    """
    Classify a job's sector deterministically from its own title first,
    falling back to the employer's name, ending in "Banking" as the
    catch-all. No network calls, no AI.
    """
    title_lower = (title or "").lower()
    company_lower = (company or "").lower()
    for rule in RULES:
        if rule.matches(title_lower, company_lower):
            return rule.sector
    return BANKING_FALLBACK


def sector_case_sql(title_col: str = "j.title", company_col: str = "j.company") -> str:
    """A SQL `CASE` expression reproducing `classify_sector` exactly."""
    whens = " ".join(f"WHEN {r.sql(title_col, company_col)} THEN '{r.sector}'" for r in RULES)
    return f"CASE {whens} ELSE '{BANKING_FALLBACK}' END"


def sector_condition_sql(name: str, title_col: str = "j.title", company_col: str = "j.company") -> str:
    """
    The WHERE fragment selecting one sector.

    Banking is the fallthrough bucket, so filtering for it means negating
    every other rule — derived from the same `RULES` list `sector_case_sql`
    is built from, so the two can't disagree the way the old hand-written
    negation could when a sector was added and the negation wasn't updated.
    """
    for rule in RULES:
        if rule.sector == name:
            return rule.sql(title_col, company_col)
    return "(" + " AND ".join(f"NOT {r.sql(title_col, company_col)}" for r in RULES) + ")"
