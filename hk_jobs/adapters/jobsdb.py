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

Cloudflare bypass: this adapter uses Scrapling's StealthyFetcher (headless
Playwright with fingerprint spoofing) to bypass JobsDB's Cloudflare block.
The httpx-based path returned 403 on every request from datacenter IPs.

Requirements (beyond requirements.txt):
    pip install "scrapling[fetchers]"
    scrapling install
"""

import logging
import time

from selectolax.parser import HTMLParser

from hk_jobs.adapters.base import BaseAdapter
from hk_jobs.adapters.workday import _strip_html
from hk_jobs.schema import Job

logger = logging.getLogger(__name__)

_BASE_URL = "https://hk.jobsdb.com"

# Scrapling's solve_cloudflare has a built-in wait; we still sleep a little
# between page fetches to avoid hammering the server.
_PAGE_SLEEP = 1.0

# Signals in the HTML body that mean we still got blocked somehow
_CHALLENGE_SIGNALS = ("captcha", "cf-challenge", "just a moment", "checking your browser")


def _is_challenge(status: int, html: str) -> bool:
    """Return True if we got a Cloudflare or bot-protection response."""
    if status in (403, 429):
        return True
    return any(sig in html.lower() for sig in _CHALLENGE_SIGNALS)


class JobsDBAdapter(BaseAdapter):
    """
    Scrapes job listings for one company from hk.jobsdb.com.

    Uses Scrapling's StealthyFetcher to bypass Cloudflare. Each page fetch
    launches a headless Playwright browser with randomised fingerprints and
    solves any Cloudflare challenge automatically.

    'jobsdb_slug' is the URL slug JobsDB uses for the company, e.g.
    'bank-of-china-hong-kong' → hk.jobsdb.com/bank-of-china-hong-kong-jobs.

    Optional 'proxy' config key — a proxy URL passed straight to Scrapling:
        proxy: "http://user:pass@proxy-host:port"
    Not required for Cloudflare bypass (Scrapling handles that via browser
    fingerprinting), but useful for IP rotation on high-volume runs.
    """

    source_name = "jobsdb"

    def __init__(
        self,
        company: str,
        company_slug: str,
        jobsdb_slug: str,
        max_pages: int = 5,
        proxy: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(
            company,
            company_slug,
            jobsdb_slug=jobsdb_slug,
            max_pages=max_pages,
            proxy=proxy,
            **kwargs,
        )
        self.jobsdb_slug = jobsdb_slug
        self.max_pages = max_pages
        self._proxy = proxy
        self._listing_url = f"{_BASE_URL}/{jobsdb_slug}-jobs"

    def fetch_jobs(self) -> list[Job]:
        """Public entry point — wraps _fetch_all in _safe_fetch for error isolation."""
        return self._safe_fetch(self._fetch_all)

    def _fetch_url(self, url: str) -> tuple[int, str]:
        """
        Fetch url and return (http_status, html_string).

        Uses Scrapling's StealthyFetcher for Cloudflare bypass.
        This method is the single seam for tests — monkeypatch it to inject
        fixture HTML without launching a real browser.
        """
        from scrapling.fetchers import StealthyFetcher

        kwargs: dict = dict(headless=True, solve_cloudflare=True, network_idle=True)
        if self._proxy:
            kwargs["proxy"] = self._proxy

        page = StealthyFetcher.fetch(url, **kwargs)
        return page.status, str(page.html_content)

    # ── private helpers ────────────────────────────────────────────────────

    def _fetch_all(self) -> list[Job]:
        jobs: list[Job] = []
        for page_num in range(1, self.max_pages + 1):
            cards = self._fetch_listing_page(page_num)
            if not cards:
                break
            for card in cards:
                job = self._fetch_detail(card)
                jobs.append(job)
            if page_num < self.max_pages:
                time.sleep(_PAGE_SLEEP)
        return jobs

    def _fetch_listing_page(self, page_num: int) -> list[dict]:
        url = f"{self._listing_url}?page={page_num}" if page_num > 1 else self._listing_url
        status, html = self._fetch_url(url)

        if _is_challenge(status, html):
            logger.error(
                "JobsDB still blocking %s page %d (status %d) — "
                "Scrapling could not bypass Cloudflare. Try updating Scrapling.",
                self.company, page_num, status,
            )
            return []

        if status != 200:
            logger.error("JobsDB returned HTTP %d for %s page %d", status, self.company, page_num)
            return []

        cards = _parse_listing_html(html)
        if not cards:
            logger.debug(
                "No job cards found on %s page %d — stopping pagination.",
                self.company, page_num,
            )
        return cards

    def _fetch_detail(self, card: dict) -> Job:
        """Fetch the full job detail page; fall back to listing data on any failure."""
        try:
            status, html = self._fetch_url(card["url"])
            if _is_challenge(status, html) or status != 200:
                return _card_to_job(self, card, raw_html="")
            raw_html, location, employment_type = _parse_detail_html(html)
        except Exception:
            logger.warning(
                "Could not fetch JobsDB detail %s for %s — using listing data only.",
                card["url"], self.company,
            )
            return _card_to_job(self, card, raw_html="")

        resolved_location = location or card.get("location", "")
        locations = [resolved_location] if resolved_location else []

        return Job(
            source=self.source_name,
            source_id=_extract_source_id(card["url"]),
            company=self.company,
            company_slug=self.company_slug,
            url=card["url"],
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

    Targets data-automation attributes — more stable than hashed CSS classes.
    NOTE: JobsDB's exact attribute values may change across deploys. If this
    returns 0 cards on a live page, run scripts/test_scrapling_jobsdb.py to
    inspect the current HTML structure and update the selectors here.
    """
    tree = HTMLParser(html)
    cards = []

    for article in tree.css("[data-automation^='job-card']"):
        title_node = article.css_first(
            "[data-automation='job-title'] a, [data-automation='job-link']"
        )
        location_node = article.css_first("[data-automation='job-location']")
        teaser_node = article.css_first("[data-automation='job-teaser']")

        if not title_node:
            continue

        href = title_node.attributes.get("href", "")
        url = href if href.startswith("http") else f"{_BASE_URL}{href}"

        cards.append({
            "title": title_node.text(strip=True),
            "url": url,
            "location": location_node.text(strip=True) if location_node else "",
            "teaser": teaser_node.text(strip=True) if teaser_node else "",
        })

    return cards


def _parse_detail_html(html: str) -> tuple[str, str, str]:
    """Return (raw_html, location, employment_type) from a JobsDB job detail page."""
    tree = HTMLParser(html)

    details_node = tree.css_first("[data-automation='jobAdDetails']")
    raw_html = details_node.html or "" if details_node else ""

    loc_node = tree.css_first("[data-automation='job-detail-location']")
    location = loc_node.text(strip=True) if loc_node else ""

    et_node = tree.css_first("[data-automation='job-detail-employment-type']")
    employment_type = et_node.text(strip=True) if et_node else ""

    return raw_html, location, employment_type


def _extract_source_id(url: str) -> str:
    """Extract trailing numeric job ID from a JobsDB URL; fall back to full URL."""
    parts = url.rstrip("/").split("-")
    if parts and parts[-1].isdigit():
        return parts[-1]
    return url


def _card_to_job(adapter: "JobsDBAdapter", card: dict, raw_html: str) -> Job:
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
