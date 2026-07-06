"""
Canonical Job schema.

Every adapter — regardless of source ATS — maps its raw data into this
model before handing it to the rest of the pipeline. Nothing outside the
adapters should ever deal with ATS-native formats.
"""

import hashlib
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field


class Job(BaseModel):
    # ── Identity ──────────────────────────────────────────────────────────
    source: str = Field(
        description=(
            "Which ATS or website this job came from, e.g. 'workday', 'eightfold', "
            "'jobsdb_fallback'. Stored as a plain string so adding a new source never "
            "requires changing this model."
        )
    )
    source_id: str = Field(
        description=(
            "The job's unique ID inside the source ATS. "
            "Used with `source` to detect duplicates."
        )
    )
    company: str = Field(description="Human-readable company name, e.g. 'HSBC'.")
    company_slug: str = Field(
        description="URL-safe identifier for the company, e.g. 'hsbc'. Used in dedup_hash()."
    )
    url: str = Field(description="Direct link to the job posting on the source site.")

    # ── Descriptive ───────────────────────────────────────────────────────
    title: str

    description_raw: str = Field(
        default="",
        description=(
            "The job description exactly as it came from the source, including HTML tags. "
            "We keep this so we can re-run feature extraction later without re-scraping — "
            "if we improve our skill-detection logic, we can replay it on every stored job."
        ),
    )
    description_clean: str = Field(
        default="",
        description=(
            "Plain text version of description_raw with all HTML stripped. "
            "This is what gets fed to search indexes and embedding models."
        ),
    )

    # ── Location ──────────────────────────────────────────────────────────
    locations: list[str] = Field(
        default_factory=list,
        description="Where the role is based, e.g. ['Hong Kong', 'Singapore']. "
        "List because many postings advertise multiple offices.",
    )
    remote_type: Literal["remote", "hybrid", "onsite"] | None = None

    # ── Classification ────────────────────────────────────────────────────
    department: str | None = None
    seniority: Literal["intern", "junior", "mid", "senior", "lead", "executive"] | None = None
    employment_type: Literal["full-time", "part-time", "contract", "internship"] | None = None

    # ── Compensation ──────────────────────────────────────────────────────
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str | None = None

    # ── Skills ────────────────────────────────────────────────────────────
    skills_required: list[str] = Field(default_factory=list)
    skills_preferred: list[str] = Field(default_factory=list)
    years_experience_min: int | None = None

    # ── Metadata ──────────────────────────────────────────────────────────
    posted_at: datetime | None = None
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    is_active: bool = True

    # ── Provenance ────────────────────────────────────────────────────────
    scraped_under_slug: str | None = Field(
        default=None,
        description=(
            "The company_slug of the page this job was found on. "
            "For Workday/Eightfold this equals company_slug. "
            "For JobsDB it may differ when an employer page surfaces third-party "
            "listings: a job with company='AIA International Limited' can have "
            "scraped_under_slug='manulife-hk' if found on Manulife's page."
        ),
    )

    # ── Extraction track ──────────────────────────────────────────────────
    source_tier: str = Field(
        default="mainstream",
        description=(
            "'mainstream' for structured sources (Workday/Eightfold/JobsDB/Indeed) "
            "or 'boutique' for longtail companies scraped via LLM extraction. "
            "Lets downstream queries filter, e.g. WHERE source_tier='boutique'."
        ),
    )
    extraction_confidence: float | None = Field(
        default=None,
        description=(
            "0.0-1.0 confidence from LLM-based extraction (longtail sources). "
            "None for deterministic, non-LLM sources."
        ),
    )

    def dedup_hash(self) -> str:
        """
        Return a 12-character fingerprint that identifies this job posting.

        Why this exists: the same vacancy sometimes appears on a company's own
        careers page AND on jobsdb.com. Without a stable fingerprint we'd store
        it twice. The hash is built from the company slug, the lowercased title,
        and the first listed location — three things that are very unlikely to
        differ between two copies of the same role.

        The hash is intentionally short (12 hex chars) so it fits comfortably in
        a database column while still being collision-resistant enough for our
        scale (~10,000 jobs at most).
        """
        first_loc = self.locations[0].lower() if self.locations else ""
        key = f"{self.company_slug}|{self.title.lower()}|{first_loc}"
        return hashlib.sha256(key.encode()).hexdigest()[:12]


def jobs_to_jsonl(jobs: list[Job], path: str) -> None:
    """
    Write a list of Job objects to a newline-delimited JSON file (one job per line).

    Datetimes are serialised as ISO 8601 strings (e.g. '2024-03-01T09:00:00+00:00').
    The file can be read back with:

        jobs = [Job.model_validate_json(line) for line in open(path) if line.strip()]
    """
    with open(path, "w", encoding="utf-8") as fh:
        for job in jobs:
            fh.write(job.model_dump_json() + "\n")


def jobs_from_jsonl(path: str) -> list[Job]:
    """Read a JSONL file written by jobs_to_jsonl and return Job objects."""
    with open(path, encoding="utf-8") as fh:
        return [Job.model_validate_json(line) for line in fh if line.strip()]
