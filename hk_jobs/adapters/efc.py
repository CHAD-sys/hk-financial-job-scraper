"""
eFinancialCareers adapter (per-company, JSON API).

╔══════════════════════════════════════════════════════════════════════════╗
║  LEGAL WARNING                                                           ║
║                                                                          ║
║  Programmatic access to eFinancialCareers (DHI Group) data is governed   ║
║  by their Terms of Service. The public HTML site is bot-walled (405 to   ║
║  non-browsers); this adapter instead calls the same backend JSON API the ║
║  site itself uses (job-search-api.efinancialcareers.com), which IS       ║
║  reachable with a normal HTTP client. Use for prototype/verification     ║
║  only. For production, obtain written permission / their licensed        ║
║  Job API (recruiterhub.efinancialcareers.com) or a paid data feed.       ║
╚══════════════════════════════════════════════════════════════════════════╝

Why this exists: the project is migrating apply-link priority from JobsDB to
eFinancialCareers (a finance-specialised board). We scrape both; when the same
vacancy is found on both, storage.reconcile_cross_posted() points apply_url at
the eFC copy (see hk_jobs/storage.py::_SOURCE_PRIORITY).

Data source (verified live, Bank of China, 2026-07-14):
    GET https://job-search-api.efinancialcareers.com/v1/efc/jobs/search
        ?countryCode2=HK&culture=en&pageSize=250&currentPage=1
        &filters.clientBrandNameFilter={exact eFC brand}
  Employer-scoped by the clientBrandNameFilter, so results are exactly this
  employer's HK jobs. One request with a large pageSize returns them all
  (meta.pageCount tells us if we need more). Each job carries jobId (→ source_id),
  title, detailsPageUrl (→ apply link with .id), clientBrandName, jobLocation,
  postedDate (real ISO timestamp), employmentType, and a full description — so no
  separate description-fetch pass is needed for eFC rows.

Unlike Workday/Eightfold this is a specialist board rather than one company's
ATS, but the shape is the same: hit a JSON endpoint, map to canonical Job. No
Scrapling / headless browser required.
"""

from __future__ import annotations

import logging
import random
import re
import time
from datetime import datetime
from typing import Any

import httpx

from hk_jobs.adapters.base import _DEFAULT_HEADERS, BaseAdapter
from hk_jobs.adapters.workday import _strip_html
from hk_jobs.schema import Job

logger = logging.getLogger(__name__)

_API_URL = "https://job-search-api.efinancialcareers.com/v1/efc/jobs/search"
# Job detailsPageUrl values are relative to the market site; prepend this to get
# a clickable apply link. HK market → efinancialcareers.hk.
_SITE_URL = "https://www.efinancialcareers.hk"

_MAX_RETRIES = 3
_RETRY_BACKOFF = 3.0  # seconds × attempt, plus jitter; the API throttles bursts

# eFC employmentType strings → our canonical Job.employment_type literal.
_EMP_TYPE_MAP = {
    "full time": "full-time",
    "part time": "part-time",
    "contract": "contract",
    "temporary": "contract",
    "internship": "internship",
    "intern": "internship",
}


class EfcAdapter(BaseAdapter):
    """
    Fetches one employer's HK jobs from the eFinancialCareers JSON API.

    Config keys (companies.yaml):
        efc_employer   (str, REQUIRED) employer display name; also the default
                       brand filter and the fallback company name.
        efc_brand      (str, optional) the EXACT clientBrandNameFilter value eFC
                       uses (e.g. "Bank Of China (Hong Kong) Limited"). Defaults
                       to efc_employer. Set this — eFC's canonical brand often
                       differs from our name (casing, legal entity). Resolve it
                       via the /v1/efc/jobs/search API (see scripts/try_efc_live.py).
        country_code   (str, default "HK") the countryCode2 request param. NOTE:
                       the API ignores it for brand-filtered queries, so it is
                       advisory only — the real scoping is country_name below.
        country_name   (str, default "Hong Kong") jobs are hard-filtered to this
                       jobLocation.country. This is what actually keeps a global
                       brand's non-HK jobs out of the DB.
        page_size      (int, default 250) results per request; large so one call
                       usually suffices. Remaining pages are followed if needed.
        max_pages      (int, default 8) hard cap on pages (page_size × max_pages
                       jobs) so a mis-set filter can't paginate forever.
        proxy          (str, optional) HTTP proxy URL.
    """

    source_name = "efinancialcareers"

    def __init__(
        self,
        company: str,
        company_slug: str,
        efc_employer: str,
        efc_brand: str | None = None,
        country_code: str = "HK",
        country_name: str = "Hong Kong",
        page_size: int = 250,
        max_pages: int = 8,
        proxy: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            company, company_slug,
            efc_employer=efc_employer, efc_brand=efc_brand, country_code=country_code,
            country_name=country_name, page_size=page_size, max_pages=max_pages,
            proxy=proxy, **kwargs,
        )
        self.efc_employer = efc_employer
        self.efc_brand = efc_brand or efc_employer
        self.country_code = country_code
        self.country_name = country_name
        self.page_size = page_size
        self.max_pages = max_pages
        self._proxy = proxy

    # ── public ───────────────────────────────────────────────────────────────

    def fetch_jobs(self) -> list[Job]:
        return self._safe_fetch(self._fetch_all)

    # ── internals ──────────────────────────────────────────────────────────────

    def _client(self, timeout: float = 25.0) -> httpx.Client:
        # The API is a JSON backend; it wants a browser-like UA plus the site's
        # Origin/Referer. Reuse the shared browser headers and add JSON + origin.
        headers = {
            **_DEFAULT_HEADERS,
            "Accept": "application/json",
            "Origin": _SITE_URL,
            "Referer": _SITE_URL + "/",
        }
        kwargs: dict = dict(headers=headers, timeout=timeout, follow_redirects=True)
        if self._proxy:
            kwargs["proxy"] = self._proxy
        return httpx.Client(**kwargs)

    def _fetch_all(self) -> list[Job]:
        # NB: the API's countryCode2 param is NOT honoured for brand-filtered
        # queries — a global employer ("Deloitte", "JPMorgan Chase & Co.") comes
        # back with worldwide jobs. We therefore hard-filter to the target country
        # by each job's own jobLocation. For HK-specific brands ("Bank Of China
        # (Hong Kong) Limited") every job passes; for global brands only the HK
        # ones are kept (often zero — those employers just aren't on eFC HK).
        jobs: list[Job] = []
        with self._client() as client:
            page = 1
            while page <= self.max_pages:
                data, page_count = self._fetch_page(client, page)
                if not data:
                    break
                jobs.extend(self._map(d) for d in data if self._in_country(d))
                if page >= (page_count or 1):
                    break
                page += 1
        return jobs

    def _in_country(self, d: dict) -> bool:
        loc = d.get("jobLocation") or {}
        return (loc.get("country") or "") == self.country_name

    def _fetch_page(self, client: httpx.Client, page: int) -> tuple[list[dict], int]:
        """Fetch one API page; return (job_dicts, total_page_count). Retries throttles."""
        params = {
            "countryCode2": self.country_code,
            "culture": "en",
            "pageSize": self.page_size,
            "currentPage": page,
            "filters.clientBrandNameFilter": self.efc_brand,
        }
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                resp = client.get(_API_URL, params=params)
            except Exception as exc:
                logger.warning("%s: eFC API request raised %s (attempt %d/%d)",
                               self.company, type(exc).__name__, attempt, _MAX_RETRIES)
                if attempt == _MAX_RETRIES:
                    raise
                time.sleep(_RETRY_BACKOFF * attempt + random.uniform(0, 2))
                continue

            if resp.status_code == 200:
                body = resp.json()
                meta = body.get("meta") or {}
                return body.get("data") or [], int(meta.get("pageCount") or 1)

            if resp.status_code in (403, 429, 503):
                logger.warning("%s: eFC API throttled (HTTP %d) attempt %d/%d — backing off",
                               self.company, resp.status_code, attempt, _MAX_RETRIES)
                if attempt < _MAX_RETRIES:
                    time.sleep(_RETRY_BACKOFF * attempt + random.uniform(0, 2))
                continue

            logger.error("%s: eFC API returned HTTP %d", self.company, resp.status_code)
            return [], 1
        return [], 1

    def _map(self, d: dict) -> Job:
        loc = d.get("jobLocation") or {}
        locname = loc.get("displayName") or loc.get("city") or ""
        url = d.get("detailsPageUrl") or ""
        if url.startswith("/"):
            url = _SITE_URL + url
        desc = d.get("description") or ""
        return Job(
            source=self.source_name,
            source_id=str(d.get("jobId") or d.get("id") or url),
            company=d.get("clientBrandName") or d.get("companyName") or self.company,
            company_slug=self.company_slug,
            url=url,
            title=d.get("title") or "",
            description_raw=desc,
            description_clean=_strip_html(desc) if desc else "",
            locations=[locname] if locname else [],
            employment_type=_map_employment_type(d.get("employmentType")),
            salary_min=d.get("minSalary") or None,   # 0 = undisclosed → None
            salary_max=d.get("maxSalary") or None,
            salary_currency=(d.get("salaryCurrency") or None) if d.get("minSalary") else None,
            posted_at=_parse_iso(d.get("postedDate")),
            scraped_under_slug=self.company_slug,
            board_signals=_efc_signals(d),
        )


# ── module-level helpers ───────────────────────────────────────────────────────

def _efc_signals(d: dict) -> dict:
    """P2/P3 market signals from one eFC job object (only non-empty ones)."""
    sig: dict = {}
    # PAID = advertiser paid to post; isHighlighted = premium/featured placement.
    paid = str(d.get("jobPaymentType") or "").upper() == "PAID"
    highlighted = str(d.get("isHighlighted")).lower() == "true"
    if paid or highlighted:
        sig["sponsored"] = True
    exp = d.get("expirationDate")
    if exp:
        sig["expires_at"] = exp
    parent = d.get("fullCompanyName")
    if parent and parent != (d.get("clientBrandName") or d.get("companyName")):
        sig["parent_company"] = parent
    if str(d.get("positionType") or "").strip():
        sig["position_type"] = d.get("positionType")   # Permanent / Contract
    return sig


def _map_employment_type(raw: str | None) -> str | None:
    if not raw:
        return None
    return _EMP_TYPE_MAP.get(raw.strip().lower())


def _parse_iso(raw: str | None) -> datetime | None:
    """Parse an ISO 8601 timestamp (e.g. '2026-07-14T10:15:01.567Z') to aware UTC."""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


_ID_RE = re.compile(r"\.id(\d+)")


def _extract_efc_id(url: str) -> str:
    """Extract the trailing `.id{NUMBER}` from a detailsPageUrl; fall back to url."""
    m = _ID_RE.search(url)
    return m.group(1) if m else url
