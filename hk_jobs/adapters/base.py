"""
Abstract base class that every ATS adapter must implement.

An adapter's sole job is to fetch raw data from one source type and
return a list of canonical Job objects. It knows nothing about enrichment
or storage — those are separate pipeline steps.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Callable

import httpx

from hk_jobs.schema import Job

logger = logging.getLogger(__name__)

# Realistic browser User-Agent + zh-HK in Accept-Language.
# Many enterprise ATS portals (and some CDN WAFs in front of them) return 403
# for requests that look like automation tools. A browser-like UA is the
# cheapest fix and avoids the need for a headless browser in most cases.
_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,zh-HK;q=0.8,zh;q=0.7",
}


class BaseAdapter(ABC):
    """
    Subclass this once per ATS type (Workday, Eightfold, etc.).

    Subclasses set ``source_name`` at the class level and implement
    ``fetch_jobs()``. Everything else — HTTP client setup, error
    swallowing — is provided here so individual adapters stay lean.
    """

    source_name: str = ""  # subclasses must override, e.g. "workday"

    def __init__(self, company: str, company_slug: str, **kwargs: Any) -> None:
        """
        Args:
            company:      Human-readable name, e.g. "HSBC".
            company_slug: URL-safe identifier, e.g. "hsbc".
            **kwargs:     Any extra keys from companies.yaml (tenant, site, …)
                          are stored as self.config for the subclass to use.
        """
        self.company = company
        self.company_slug = company_slug
        self.config: dict[str, Any] = kwargs

    @abstractmethod
    def fetch_jobs(self) -> list[Job]:
        """Fetch all active jobs from this source and return them as Job objects."""
        ...

    def _client(self, timeout: float = 20.0) -> httpx.Client:
        """
        Return a pre-configured httpx.Client.

        Use as a context manager in adapters:

            with self._client() as client:
                resp = client.get(url)
        """
        return httpx.Client(headers=_DEFAULT_HEADERS, timeout=timeout, follow_redirects=True)

    def _safe_fetch(self, fn: Callable[..., list[Job]], *args: Any, **kwargs: Any) -> list[Job]:
        """
        Call fn(*args, **kwargs) and return its result.

        If fn raises for any reason, log the exception and return [] so that
        one broken company never stops the whole pipeline run. The error is
        logged at ERROR level so it shows up clearly in logs without crashing.
        """
        try:
            return fn(*args, **kwargs)
        except Exception:
            logger.exception(
                "Adapter %s failed for %s — skipping this company.",
                self.__class__.__name__,
                self.company,
            )
            return []
