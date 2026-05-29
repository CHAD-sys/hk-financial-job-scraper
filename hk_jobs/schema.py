"""
Canonical Job schema.

Every adapter — regardless of source ATS — maps its raw data into this
model before handing it to the rest of the pipeline. Nothing outside the
adapters should ever deal with ATS-native formats.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class ATSSource(StrEnum):
    WORKDAY = "workday"
    EIGHTFOLD = "eightfold"
    SUCCESSFACTORS = "successfactors"
    JOBSDB_FALLBACK = "jobsdb_fallback"  # used when the company's own ATS is hostile


class Seniority(StrEnum):
    INTERN = "intern"
    JUNIOR = "junior"        # 0-3 yrs typically
    MID = "mid"              # 3-7 yrs
    SENIOR = "senior"        # 7+ yrs
    MANAGER = "manager"
    DIRECTOR = "director"
    EXECUTIVE = "executive"
    UNKNOWN = "unknown"


class Job(BaseModel):
    # ── Identity ──────────────────────────────────────────────────────────
    source_id: str = Field(
        description="Unique job ID as assigned by the source ATS (used for dedup)."
    )
    source_ats: ATSSource
    company: str = Field(description="Company name, e.g. 'HSBC'.")
    url: str = Field(description="Direct link to the job posting.")

    # ── Core fields ───────────────────────────────────────────────────────
    title: str
    location: str = ""
    department: str = ""
    employment_type: str = ""        # Full-time, Part-time, Contract, …

    # ── Content ───────────────────────────────────────────────────────────
    description_raw: str = Field(
        default="",
        description="Original HTML from the ATS. Preserved for re-extraction.",
    )
    description_clean: str = Field(
        default="",
        description="Plain text stripped from description_raw. Used for search/embedding.",
    )

    # ── Extracted features (populated by enrich.py) ───────────────────────
    seniority: Seniority = Seniority.UNKNOWN
    skills: list[str] = Field(default_factory=list)

    # ── Lifecycle ─────────────────────────────────────────────────────────
    is_active: bool = True
    first_seen_at: datetime = Field(default_factory=datetime.utcnow)
    last_seen_at: datetime = Field(default_factory=datetime.utcnow)
    posted_at: datetime | None = None   # when the company says it was posted
