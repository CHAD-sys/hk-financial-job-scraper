"""
Abstract base class that every ATS adapter must implement.

An adapter's sole job is to fetch raw data from one source type and
return a list of canonical Job objects. It knows nothing about enrichment
or storage — those are separate pipeline steps.
"""

from abc import ABC, abstractmethod

from hk_jobs.schema import Job


class BaseAdapter(ABC):
    """
    Subclass this for each ATS (Workday, Eightfold, etc.).

    Minimal contract: implement fetch_jobs() and return Job objects.
    On any error, log it and return [] so one broken company never
    crashes the whole pipeline run.
    """

    @abstractmethod
    def fetch_jobs(self) -> list[Job]:
        """Fetch all active jobs from this source and return them as Job objects."""
        ...
