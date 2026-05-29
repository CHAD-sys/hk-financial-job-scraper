"""
Eightfold AI ATS adapter.

Eightfold is used by HSBC, Hang Seng Bank, and HSBC Life (all part of the
HSBC Group), among others. Like Workday, it exposes a JSON API that the
careers page's JavaScript calls — we use the same URL directly.

API shape:
  GET https://{tenant}.eightfold.ai/api/apply/v2/jobs
      ?domain={domain}&start={N}&num={page_size}&location={location_filter}

  Response fields of interest (ASSUMPTION — verify with live script):
    count               total number of matching positions
    positions[].id                   → source_id
    positions[].name                 → title
    positions[].department           → department
    positions[].locations            → locations  (list of strings)
    positions[].job_description      → description_raw (HTML)
    positions[].t_create             → posted_at  (Unix milliseconds)
    positions[].canonicalPositionUrl → url
"""

import logging
import time
from datetime import UTC, datetime

import httpx

from hk_jobs.adapters.base import BaseAdapter
from hk_jobs.adapters.workday import _strip_html
from hk_jobs.http_utils import with_retry
from hk_jobs.schema import Job

logger = logging.getLogger(__name__)

_PAGE_SIZE = 10
_PAGE_CAP = 100  # hard ceiling: 100 × 10 = 1 000 jobs
_PAGE_SLEEP = 0.3  # seconds between page requests — be polite to source servers


class EightfoldAdapter(BaseAdapter):
    """
    Fetches jobs from Eightfold AI's public JSON API.

    'tenant' is the subdomain prefix of the company's Eightfold portal
    (e.g. 'hsbc' for hsbc.eightfold.ai). 'domain' is the company's
    internet domain used by Eightfold to scope results (e.g. 'hsbc.com').
    Both come from companies.yaml.
    """

    source_name = "eightfold"

    def __init__(
        self,
        company: str,
        company_slug: str,
        tenant: str,
        domain: str,
        location_filter: str = "Hong Kong",
        **kwargs,
    ) -> None:
        super().__init__(company, company_slug, tenant=tenant, domain=domain, **kwargs)
        self.tenant = tenant
        self.domain = domain
        self.location_filter = location_filter
        self._api_base = f"https://{tenant}.eightfold.ai/api/apply/v2/jobs"

    def fetch_jobs(self) -> list[Job]:
        """Public entry point — wraps _fetch_all in _safe_fetch for error isolation."""
        return self._safe_fetch(self._fetch_all)

    # ── private helpers ────────────────────────────────────────────────────

    def _fetch_all(self) -> list[Job]:
        jobs: list[Job] = []
        start = 0
        with self._client() as client:
            for _ in range(_PAGE_CAP):
                data = self._fetch_page(client, start)
                total = data.get("count", 0)
                positions = data.get("positions") or []
                if not positions:
                    break
                for pos in positions:
                    jobs.append(self._map_position(pos))
                start += _PAGE_SIZE
                if start >= total:
                    break
                time.sleep(_PAGE_SLEEP)
        return jobs

    def _fetch_page(self, client: httpx.Client, start: int) -> dict:
        params = {
            "domain": self.domain,
            "start": start,
            "num": _PAGE_SIZE,
            "location": self.location_filter,
        }
        resp = with_retry(lambda: client.get(self._api_base, params=params))
        resp.raise_for_status()
        return resp.json()

    def _map_position(self, pos: dict) -> Job:
        raw_html = pos.get("job_description") or ""

        # t_create is Unix time in milliseconds; convert to UTC datetime
        posted_at: datetime | None = None
        if t_ms := pos.get("t_create"):
            try:
                posted_at = datetime.fromtimestamp(int(t_ms) / 1000, tz=UTC)
            except (ValueError, OSError):
                logger.debug("Could not parse t_create %r for '%s'", t_ms, pos.get("name"))

        # locations is already a list in Eightfold's response
        locations: list[str] = pos.get("locations") or []

        return Job(
            source=self.source_name,
            source_id=str(pos.get("id") or ""),
            company=self.company,
            company_slug=self.company_slug,
            url=pos.get("canonicalPositionUrl") or "",
            title=pos.get("name") or "",
            department=pos.get("department") or None,
            locations=locations,
            description_raw=raw_html,
            description_clean=_strip_html(raw_html),
            posted_at=posted_at,
        )
