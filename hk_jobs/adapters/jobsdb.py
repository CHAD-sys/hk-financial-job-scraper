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
Playwright with fingerprint spoofing). Each fetch takes ~60 s, so we do NOT
fetch per-job detail pages — the listing page already contains title,
location, teaser, and a link, which is sufficient for search/matching.

Requirements (beyond requirements.txt):
    pip install "scrapling[fetchers]"
    scrapling install
"""

import logging
import re
import time
from datetime import UTC, datetime, timedelta

from selectolax.parser import HTMLParser

from hk_jobs.adapters.base import BaseAdapter
from hk_jobs.adapters.workday import _strip_html  # noqa: F401 — kept for re-use by other code
from hk_jobs.schema import Job

logger = logging.getLogger(__name__)

_BASE_URL = "https://hk.jobsdb.com"
_PAGE_SLEEP = 1.0  # polite gap between listing page fetches

# Signals that mean we're still hitting a bot-protection challenge page
_CHALLENGE_SIGNALS = ("captcha", "cf-challenge", "just a moment", "checking your browser")


def _is_challenge(status: int, html: str) -> bool:
    """
    Return True if we got a Cloudflare or bot-protection response.

    Only scans for challenge text on short pages — a real content page
    (typically > 100 KB) won't be a Cloudflare challenge. This prevents
    false positives when challenge phrases appear inside JS bundles.
    """
    if status in (403, 429):
        return True
    if len(html) < 100_000:
        return any(sig in html.lower() for sig in _CHALLENGE_SIGNALS)
    return False


class JobsDBAdapter(BaseAdapter):
    """
    Scrapes listing pages for one company from hk.jobsdb.com.

    Uses Scrapling's StealthyFetcher for Cloudflare bypass. Because each
    Scrapling fetch takes ~60 s, this adapter only fetches the listing page
    (not individual job detail pages). Title, location, teaser, and URL are
    extracted directly from the listing — enough for job matching.

    Optional 'proxy' config key:
        proxy: "http://user:pass@proxy-host:port"
    """

    source_name = "jobsdb"

    def __init__(
        self,
        company: str,
        company_slug: str,
        jobsdb_slug: str,
        max_pages: int = 5,  # Scrapling ~90 s/page; stops early if page is empty
        proxy: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(
            company, company_slug,
            jobsdb_slug=jobsdb_slug, max_pages=max_pages, proxy=proxy,
            **kwargs,
        )
        self.jobsdb_slug = jobsdb_slug
        self.max_pages = max_pages
        self._proxy = proxy
        self._listing_url = f"{_BASE_URL}/{jobsdb_slug}-jobs"

    def fetch_jobs(self) -> list[Job]:
        return self._safe_fetch(self._fetch_all)

    def _fetch_url(self, url: str) -> tuple[int, str]:
        """
        Fetch url and return (http_status, html_string).

        Single mockable seam — patch this in tests to inject fixture HTML
        without launching a real Playwright browser.
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
            new_jobs = self._fetch_listing_page(page_num)
            if not new_jobs:
                break
            jobs.extend(new_jobs)
            if page_num < self.max_pages:
                time.sleep(_PAGE_SLEEP)
        return jobs

    def _fetch_listing_page(self, page_num: int) -> list[Job]:
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
            return []

        return [self._card_to_job(card) for card in cards]

    def _card_to_job(self, card: dict) -> Job:
        loc = card.get("location", "")
        return Job(
            source=self.source_name,
            source_id=_extract_source_id(card["url"]),
            company=self.company,
            company_slug=self.company_slug,
            url=card["url"],
            title=card["title"],
            locations=[loc] if loc else [],
            description_raw="",    # listing page doesn't include full description
            description_clean="",
            posted_at=_parse_listing_date(card.get("listing_date", "")),
        )


# ── module-level parsing helpers ───────────────────────────────────────────────

def _parse_listing_html(html: str) -> list[dict]:
    """
    Extract job cards from a JobsDB company listing page.

    data-automation values confirmed from live page (2026-05):
      normalJob                — job card container (article)
      jobTitle                 — the <a> tag that carries both the title text and href
      job-list-view-job-link   — invisible full-card overlay <a> (href only, no text)
      jobCardLocation          — first location span
      jobShortDescription      — short teaser text
      jobListingDate           — relative posting date ("19d ago", "1h ago")

    IMPORTANT: jobTitle is an attribute ON the <a> tag (a[data-automation='jobTitle']),
    NOT a parent container. The old selector "[data-automation='jobTitle'] a" was wrong.

    If this returns 0, run scripts/test_scrapling_jobsdb.py to inspect current live HTML.
    """
    tree = HTMLParser(html)
    cards = []

    for article in tree.css("[data-automation='normalJob']"):
        # Title link: a[data-automation='jobTitle'] holds both title text and href
        title_node = article.css_first("a[data-automation='jobTitle']")
        # Fallback link for href only (no visible text — invisible card overlay)
        link_node = article.css_first("[data-automation='job-list-view-job-link']")

        if not title_node and not link_node:
            continue

        href_node = title_node or link_node
        href = href_node.attributes.get("href", "")
        url = href if href.startswith("http") else f"{_BASE_URL}{href}"
        # Strip tracking params from href to get a clean job URL
        url = url.split("?")[0] if "?" in url else url

        location_node = article.css_first(
            "[data-automation='jobCardLocation'], [data-automation='jobLocation']"
        )
        teaser_node = article.css_first("[data-automation='jobShortDescription']")
        date_node = article.css_first("[data-automation='jobListingDate']")

        cards.append({
            "title": title_node.text(strip=True) if title_node else "",
            "url": url,
            "location": location_node.text(strip=True) if location_node else "",
            "teaser": teaser_node.text(strip=True) if teaser_node else "",
            "listing_date": date_node.text(strip=True) if date_node else "",
        })

    return cards


def _parse_listing_date(text: str) -> datetime | None:
    """
    Parse a JobsDB relative date string into a UTC datetime.

    Live page formats (2026-05): "19d ago", "2h ago", "30m ago",
    and long-form "Listed N days ago", "Posted today".
    Returns None for unrecognised formats.
    """
    if not text:
        return None
    now = datetime.now(UTC)
    lower = text.lower()
    # "today", "just now", "1h ago" with h=0, etc.
    if re.search(r"\btoday\b|\bjust now\b", lower):
        return now
    # Short form: "19d ago"
    m = re.search(r"(\d+)d\b", lower)
    if m:
        return now - timedelta(days=int(m.group(1)))
    # Short form: "2h ago"
    m = re.search(r"(\d+)h\b", lower)
    if m:
        return now - timedelta(hours=int(m.group(1)))
    # Short form: "30m ago"
    m = re.search(r"(\d+)m\b", lower)
    if m:
        return now - timedelta(minutes=int(m.group(1)))
    # Long form: "Posted 3 days ago" / "Listed 3 days ago"
    m = re.search(r"(\d+)\s+day", lower)
    if m:
        return now - timedelta(days=int(m.group(1)))
    m = re.search(r"(\d+)\s+hour", lower)
    if m:
        return now - timedelta(hours=int(m.group(1)))
    return None


def _extract_source_id(url: str) -> str:
    """Extract trailing numeric job ID from a JobsDB URL; fall back to full URL."""
    # Modern JobsDB URLs: /job/92249354?type=standard&...
    m = re.search(r"/job/(\d+)", url)
    if m:
        return m.group(1)
    # Legacy format: /hk/en/job/title-100003456789
    parts = url.rstrip("/").split("?")[0].split("-")
    if parts and parts[-1].isdigit():
        return parts[-1]
    return url
