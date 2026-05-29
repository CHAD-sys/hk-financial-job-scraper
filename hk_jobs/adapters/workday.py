"""
Workday ATS adapter.

Workday is the most common ATS among large HK financial firms. Rather than
loading the careers webpage in a browser, we call Workday's internal JSON
API directly — the same URL the page's own JavaScript uses. This is faster
and more reliable than browser automation.

API shape (both URLs use the same hostname):
  Listing:  POST /wday/cxs/{tenant}/{site}/jobs
  Detail:   GET  /wday/cxs/{tenant}/{site}/job{externalPath}

where {externalPath} comes from the listing response, e.g.:
  /en-US/External/job/Hong-Kong/Software-Engineer_JR-001

ASSUMPTION: the exact field names below (jobReqId, locationsText,
jobPostingInfo.jobDescription, etc.) match what real tenants return.
The human will run scripts/try_workday_live.py to verify this and
we will tighten the mapping if any fields differ.
"""

import html as _html
import logging
import re
import time
from datetime import datetime

import httpx

from hk_jobs.adapters.base import BaseAdapter
from hk_jobs.http_utils import with_retry
from hk_jobs.schema import Job

logger = logging.getLogger(__name__)

_PAGE_SIZE = 20
_PAGE_CAP = 50  # hard ceiling: 50 × 20 = 1 000 jobs; prevents infinite loops
_DETAIL_SLEEP = 0.3  # seconds to wait between detail calls — be polite to source servers

# Maps Workday's free-text "timeType" field to our canonical Literal values.
_TIME_TYPE_MAP: dict[str, str] = {
    "full time": "full-time",
    "part time": "part-time",
    "contract": "contract",
    "intern": "internship",
    "internship": "internship",
}


def _strip_html(html: str) -> str:
    """
    Convert an HTML job description to clean plain text.

    Block-level tags (p, br, li, div, headings, tr) become newlines so the
    resulting text stays readable without a browser. All other tags are
    stripped. HTML entities (&amp;, &nbsp;, &ndash;, etc.) are decoded.
    Runs of excess blank lines are collapsed to at most two.

    This function is importable by other adapters that also receive HTML
    descriptions (e.g. SuccessFactors).
    """
    if not html:
        return ""
    # Block-level tags → newlines to preserve paragraph / list structure
    text = re.sub(r"<(?:br|p|li|div|h[1-6]|tr)[^>]*>", "\n", html, flags=re.IGNORECASE)
    # Strip every remaining tag
    text = re.sub(r"<[^>]+>", "", text)
    # Decode HTML entities: &amp; → &, &nbsp; → space, &ndash; → –, etc.
    text = _html.unescape(text)
    # Collapse runs of horizontal whitespace
    text = re.sub(r"[ \t]+", " ", text)
    # Collapse 3+ consecutive newlines to 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _parse_locations(locations_text: str) -> list[str]:
    """
    Split Workday's locationsText into a list.

    Workday uses pipe-separation for multiple offices, e.g.
    "Hong Kong | Singapore". Single locations are returned as-is.
    """
    if not locations_text:
        return []
    return [p.strip() for p in re.split(r"\s*\|\s*", locations_text) if p.strip()]


def _map_time_type(time_type: str) -> str | None:
    """Map Workday's timeType string to our canonical employment_type value."""
    return _TIME_TYPE_MAP.get(time_type.lower().strip())


class WorkdayAdapter(BaseAdapter):
    """
    Fetches jobs from Workday's internal JSON API.

    Each company that uses Workday has a 'tenant' (their identifier inside
    Workday's system, e.g. 'hsbc') and a 'site' (the name of their public
    careers portal, often 'External'). Both come from companies.yaml.

    The 'wd' parameter is the Workday platform subdomain — most modern
    tenants use 'wd3', but some older ones still use 'wd1' or 'wd5'.
    If you get connection errors, check the tenant's actual careers URL
    to confirm the right subdomain.
    """

    source_name = "workday"

    def __init__(
        self,
        company: str,
        company_slug: str,
        tenant: str,
        site: str,
        wd: str = "wd3",
        location_filter: str = "Hong Kong",
        fetch_details: bool = True,
        **kwargs,
    ) -> None:
        super().__init__(company, company_slug, tenant=tenant, site=site, wd=wd, **kwargs)
        self.tenant = tenant
        self.site = site
        self.wd = wd
        self.location_filter = location_filter
        self.fetch_details = fetch_details

        self._base_url = f"https://{tenant}.{wd}.myworkdayjobs.com"
        self._api_base = f"{self._base_url}/wday/cxs/{tenant}/{site}"
        # Some Workday tenants verify that requests originated from their careers
        # page by checking the HTTP Referer header. We send the human-facing URL.
        self._referer = f"{self._base_url}/{tenant}/{site}/en-US/{site}"

    def fetch_jobs(self) -> list[Job]:
        """Public entry point — wraps _fetch_all in _safe_fetch for error isolation."""
        return self._safe_fetch(self._fetch_all)

    # ── private helpers ────────────────────────────────────────────────────

    def _fetch_all(self) -> list[Job]:
        jobs: list[Job] = []
        with self._client() as client:
            client.headers["Referer"] = self._referer
            offset = 0
            for _ in range(_PAGE_CAP):
                data = self._fetch_page(client, offset)
                total = data.get("total", 0)
                postings = data.get("jobPostings") or []
                if not postings:
                    break
                for posting in postings:
                    job = self._map_listing(posting)
                    if self.fetch_details:
                        job = self._fetch_detail(client, job, posting)
                    jobs.append(job)
                offset += _PAGE_SIZE
                if offset >= total:
                    break
        return jobs

    def _fetch_page(self, client: httpx.Client, offset: int) -> dict:
        body = {
            "appliedFacets": {},
            "limit": _PAGE_SIZE,
            "offset": offset,
            "searchText": self.location_filter,
        }
        resp = with_retry(lambda: client.post(f"{self._api_base}/jobs", json=body))
        resp.raise_for_status()
        return resp.json()

    def _map_listing(self, posting: dict) -> Job:
        external_path = posting.get("externalPath") or ""
        # Prefer jobReqId as the stable identifier; fall back to externalPath
        source_id = posting.get("jobReqId") or external_path or "unknown"
        # externalPath from AIA (and likely all modern Workday tenants) is
        # "/job/{loc-slug}/{title-slug}_JR-XXXXX" — it does NOT include "/en-US/{site}".
        # The human-facing URL is therefore: {base}/en-US/{site}{externalPath}.
        url = f"{self._base_url}/en-US/{self.site}{external_path}" if external_path else ""
        return Job(
            source=self.source_name,
            source_id=source_id,
            company=self.company,
            company_slug=self.company_slug,
            url=url,
            title=posting.get("title") or "",
            locations=_parse_locations(posting.get("locationsText") or ""),
        )

    def _fetch_detail(self, client: httpx.Client, job: Job, posting: dict) -> Job:
        external_path = posting.get("externalPath") or ""
        if not external_path:
            return job

        time.sleep(_DETAIL_SLEEP)

        try:
            # The detail API path is {api_base}{externalPath}.
            # externalPath already starts with "/job/...", so do NOT add "/job" here —
            # that produced "/job/job/..." which Workday rejected with HTTP 422.
            resp = with_retry(lambda: client.get(f"{self._api_base}{external_path}"))
            resp.raise_for_status()
            info = resp.json().get("jobPostingInfo") or {}
        except Exception:
            logger.warning(
                "Could not fetch Workday detail for '%s' (%s) — using listing data only.",
                job.title,
                self.company,
            )
            return job

        # Combine the two description fields some tenants split across
        raw_html = (info.get("jobDescription") or "") + (info.get("additionalJobDescription") or "")

        # Build deduplicated location list: primary location first, then extras
        locations: list[str] = []
        if info.get("location"):
            locations.append(info["location"])
        for extra in info.get("additionalLocations") or []:
            if extra and extra not in locations:
                locations.append(extra)
        if not locations:
            locations = job.locations  # fall back to listing-level data

        # Workday's startDate is ISO-like: "2024-03-01T00:00:00.000Z"
        posted_at: datetime | None = None
        if raw_date := info.get("startDate"):
            try:
                posted_at = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
            except ValueError:
                logger.debug("Could not parse startDate %r for '%s'", raw_date, job.title)

        return job.model_copy(
            update=dict(
                source_id=info.get("jobReqId") or job.source_id,
                description_raw=raw_html,
                description_clean=_strip_html(raw_html),
                locations=locations,
                employment_type=_map_time_type(info.get("timeType") or ""),
                posted_at=posted_at,
            )
        )
