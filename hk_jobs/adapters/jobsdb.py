"""
JobsDB fallback adapter.

╔══════════════════════════════════════════════════════════════════════════╗
║  LEGAL WARNING                                                           ║
║                                                                          ║
║  Scraping hk.jobsdb.com violates JobsDB's Terms of Service.             ║
║  This adapter exists ONLY as a prototype fallback for companies          ║
║  whose own ATS (Taleo, iCIMS, etc.) is hostile to direct scraping.      ║
║                                                                          ║
║  Do NOT use in production without either:                                ║
║    (a) written permission from JobsDB / SEEK, or                        ║
║    (b) a paid data-feed arrangement.                                     ║
║                                                                          ║
║  If this project ever leaves prototype stage, replace this adapter       ║
║  with direct ATS access or a licensed data source.                       ║
╚══════════════════════════════════════════════════════════════════════════╝

Why this exists: some large HK financial firms use Taleo or iCIMS, both of
which actively fight scraping (aggressive CAPTCHAs, bot detection). Those
same companies almost always post on JobsDB as well, so we fall back there.
JobsDB's HTML uses `data-automation` attributes which are more stable than
their hashed CSS class names and survive most redesigns.
"""

import logging
import time

import httpx
from selectolax.parser import HTMLParser

from hk_jobs.adapters.base import BaseAdapter
from hk_jobs.adapters.workday import _strip_html
from hk_jobs.http_utils import with_retry
from hk_jobs.schema import Job

logger = logging.getLogger(__name__)

_BASE_URL = "https://hk.jobsdb.com"
_REQUEST_SLEEP = 1.0  # seconds between every request — hard floor, not negotiable

# Anti-bot signals we look for in the response body
_CHALLENGE_SIGNALS = ("captcha", "cf-challenge", "just a moment", "checking your browser")


def _is_challenge(resp: httpx.Response) -> bool:
    """Return True if JobsDB (or a CDN in front of it) is blocking us."""
    if resp.status_code in (403, 429):
        return True
    body_lower = resp.text.lower()
    return any(sig in body_lower for sig in _CHALLENGE_SIGNALS)


class JobsDBAdapter(BaseAdapter):
    """
    Scrapes job listings for one company from hk.jobsdb.com.

    JobsDB is used as a fallback only — see the legal warning at the top of
    this file. The adapter keeps a hard ≥1 s gap between every HTTP request
    to reduce load on the source server.

    'jobsdb_company_slug' is the URL slug JobsDB uses for this company, e.g.
    'bank-of-china-hong-kong' for the listing at
    hk.jobsdb.com/bank-of-china-hong-kong-jobs.
    """

    source_name = "jobsdb"

    def __init__(
        self,
        company: str,
        company_slug: str,
        jobsdb_company_slug: str,
        max_pages: int = 5,
        **kwargs,
    ) -> None:
        super().__init__(
            company,
            company_slug,
            jobsdb_company_slug=jobsdb_company_slug,
            max_pages=max_pages,
            **kwargs,
        )
        self.jobsdb_company_slug = jobsdb_company_slug
        self.max_pages = max_pages
        self._listing_url = f"{_BASE_URL}/{jobsdb_company_slug}-jobs"

    def fetch_jobs(self) -> list[Job]:
        """Public entry point — wraps _fetch_all in _safe_fetch for error isolation."""
        return self._safe_fetch(self._fetch_all)

    # ── private helpers ────────────────────────────────────────────────────

    def _fetch_all(self) -> list[Job]:
        jobs: list[Job] = []
        with self._client() as client:
            for page in range(1, self.max_pages + 1):
                cards = self._fetch_listing_page(client, page)
                if not cards:
                    break
                for card in cards:
                    job = self._fetch_detail(client, card)
                    jobs.append(job)
        return jobs

    def _fetch_listing_page(self, client: httpx.Client, page: int) -> list[dict]:
        """
        Fetch one page of the company's JobsDB listing and return a list of
        raw card dicts with title, url, location, and teaser.
        """
        params = {"page": page} if page > 1 else {}
        time.sleep(_REQUEST_SLEEP)
        resp = with_retry(lambda: client.get(self._listing_url, params=params))

        if _is_challenge(resp):
            logger.error(
                "JobsDB challenged us for %s (page %d, status %d) — "
                "needs a proxy or try later. Stopping early.",
                self.company,
                page,
                resp.status_code,
            )
            return []

        resp.raise_for_status()
        return _parse_listing_html(resp.text)

    def _fetch_detail(self, client: httpx.Client, card: dict) -> Job:
        """
        Fetch the full job detail page and merge it into a Job.

        Falls back to listing-only data if the detail page is unavailable.
        """
        detail_url = card["url"]
        time.sleep(_REQUEST_SLEEP)
        try:
            resp = client.get(detail_url)
            if _is_challenge(resp):
                logger.warning(
                    "JobsDB challenged us on detail page %s — using listing data only.",
                    detail_url,
                )
                return _card_to_job(self, card, raw_html="")
            resp.raise_for_status()
            raw_html, location, employment_type = _parse_detail_html(resp.text)
        except Exception:
            logger.warning(
                "Could not fetch JobsDB detail %s for %s — using listing data only.",
                detail_url,
                self.company,
            )
            return _card_to_job(self, card, raw_html="")

        # Detail location overrides listing location when present
        resolved_location = location or card.get("location", "")
        locations = [resolved_location] if resolved_location else []

        return Job(
            source=self.source_name,
            source_id=_extract_source_id(detail_url),
            company=self.company,
            company_slug=self.company_slug,
            url=detail_url,
            title=card["title"],
            locations=locations,
            employment_type=_map_employment_type(employment_type),
            description_raw=raw_html,
            description_clean=_strip_html(raw_html),
        )


# ── module-level parsing helpers ───────────────────────────────────────────────

def _parse_listing_html(html: str) -> list[dict]:
    """
    Extract job cards from a JobsDB company listing page.

    Targets data-automation attributes rather than CSS classes — JobsDB's
    class names are hashed and change on every deploy, but data-automation
    values are tied to automated testing and stay stable.
    """
    tree = HTMLParser(html)
    cards = []

    # Each job card has data-automation starting with "job-card-"
    for article in tree.css("[data-automation^='job-card']"):
        title_node = article.css_first("[data-automation='job-title'] a, "
                                       "[data-automation='job-link']")
        location_node = article.css_first("[data-automation='job-location']")
        teaser_node = article.css_first("[data-automation='job-teaser']")

        if not title_node:
            continue

        href = title_node.attributes.get("href", "")
        # href may be relative ("/hk/en/job/...") or absolute
        url = href if href.startswith("http") else f"{_BASE_URL}{href}"

        cards.append(
            {
                "title": title_node.text(strip=True),
                "url": url,
                "location": location_node.text(strip=True) if location_node else "",
                "teaser": teaser_node.text(strip=True) if teaser_node else "",
            }
        )

    return cards


def _parse_detail_html(html: str) -> tuple[str, str, str]:
    """
    Extract (raw_html, location, employment_type) from a JobsDB detail page.

    Returns empty strings for any field that can't be found so callers can
    fall back to listing data gracefully.
    """
    tree = HTMLParser(html)

    # Full job description lives in [data-automation='jobAdDetails']
    details_node = tree.css_first("[data-automation='jobAdDetails']")
    raw_html = details_node.html or "" if details_node else ""

    location = ""
    loc_node = tree.css_first("[data-automation='job-detail-location']")
    if loc_node:
        location = loc_node.text(strip=True)

    employment_type = ""
    et_node = tree.css_first("[data-automation='job-detail-employment-type']")
    if et_node:
        employment_type = et_node.text(strip=True)

    return raw_html, location, employment_type


def _extract_source_id(url: str) -> str:
    """
    Pull the numeric job ID from a JobsDB URL.

    JobsDB job URLs end with a numeric ID, e.g.:
      /hk/en/job/credit-risk-analyst-100003456789  →  "100003456789"
    Falls back to the full URL if no numeric suffix is found.
    """
    parts = url.rstrip("/").split("-")
    if parts and parts[-1].isdigit():
        return parts[-1]
    return url


def _card_to_job(adapter: "JobsDBAdapter", card: dict, raw_html: str) -> Job:
    """Build a Job from listing-card data only (no detail page available)."""
    loc = card.get("location", "")
    return Job(
        source=adapter.source_name,
        source_id=_extract_source_id(card["url"]),
        company=adapter.company,
        company_slug=adapter.company_slug,
        url=card["url"],
        title=card["title"],
        locations=[loc] if loc else [],
        description_raw=raw_html,
        description_clean=_strip_html(raw_html),
    )


_EMPLOYMENT_TYPE_MAP: dict[str, str] = {
    "full time": "full-time",
    "full-time": "full-time",
    "part time": "part-time",
    "part-time": "part-time",
    "contract": "contract",
    "internship": "internship",
    "intern": "internship",
}


def _map_employment_type(raw: str) -> str | None:
    return _EMPLOYMENT_TYPE_MAP.get(raw.lower().strip())
