"""Evidence-backed employer destinations for active Management Trainee Roles.

An aggregator can tell FinEx that a Role exists, but it should not become the
default applicant journey where the employer publishes a usable destination of
its own.  This registry is deliberately small and explicit: every entry must
name the employer, title pattern, official URL and what the visitor can expect
there.  It is not a collection of guessed home pages.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from hk_jobs.mt_classifier import classify_mt_role


EmployerDestinationKind = Literal["employer_role", "employer_vacancies"]


@dataclass(frozen=True, slots=True)
class EmployerDestination:
    """An official employer page suitable for an MT applicant's next step."""

    url: str
    kind: EmployerDestinationKind
    label: str
    evidence: str
    checked_at: str


def employer_destination_for(company: str, title: str) -> EmployerDestination | None:
    """Return a verified official destination for one exact MT programme.

    Match against the classifier's canonical watchlist company, never a loose
    company substring.  That keeps an official page for one BOCHK programme
    from being accidentally reused for a similarly named role elsewhere.
    """
    classification = classify_mt_role(company, title)
    if not classification.is_mt:
        return None

    canonical_company = classification.watchlist_company
    normalised_title = title.lower()

    if canonical_company == "Hong Kong Monetary Authority (HKMA)" and "manager trainee" in normalised_title:
        return EmployerDestination(
            url="https://www.hkma.gov.hk/eng/about-us/join-us/current-vacancies/",
            kind="employer_vacancies",
            label="View HKMA vacancies",
            evidence="HKMA current-vacancies page lists Manager Trainee (2027 Intake).",
            checked_at="2026-09-15",
        )

    if canonical_company == "Bank of China (Hong Kong) [BOCHK]" and "2027 management trainee" in normalised_title:
        return EmployerDestination(
            url="https://www.bochk.com/en/career/ustudentprogramme/mgttrainee.html",
            kind="employer_role",
            label="View BOCHK MT programme",
            evidence="BOCHK Campus Recruitment publishes its Management Trainee Programme on this official page.",
            checked_at="2026-09-15",
        )

    if canonical_company == "Bank of China (Hong Kong) [BOCHK]" and "wealth management trainee" in normalised_title:
        return EmployerDestination(
            url="https://www.bochk.com/en/career/opportunities.html",
            kind="employer_vacancies",
            label="View BOCHK vacancies",
            evidence="BOCHK's official Job Openings page is its employer-run route to current applications.",
            checked_at="2026-09-15",
        )

    return None
