"""
Feature extraction from raw job postings.

Takes a Job with description_raw/description_clean set and fills in
derived fields: seniority, skills. Keeps fetching and enrichment
separate so we can re-run enrichment on already-stored jobs without
re-scraping.
"""

from hk_jobs.schema import Job


def enrich(job: Job) -> Job:
    """Populate derived fields on a Job. Returns the same object mutated in-place."""
    # Phase 1 stub — enrichment logic added in a later phase.
    return job
