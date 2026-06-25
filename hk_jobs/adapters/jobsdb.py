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
import random
import re
import time
from datetime import UTC, datetime, timedelta

from selectolax.parser import HTMLParser

from hk_jobs.adapters.base import BaseAdapter
from hk_jobs.adapters.workday import _strip_html  # noqa: F401 — kept for re-use by other code
from hk_jobs.schema import Job

logger = logging.getLogger(__name__)

_BASE_URL = "https://hk.jobsdb.com"

# ── Advertiser-name selector candidates ───────────────────────────────────────
# JobsDB renders each card's hiring company with one of these data-automation
# attributes.  We try them in preference order and take the first non-empty hit.
#
# The fixture HTML (tests/fixtures/jobsdb/listing.html) uses "jobAdvertiser"
# — the most common value observed.  If live scraping finds a different
# attribute, add it here; the fallback chain means no card is ever silently
# skipped.
#
# IMPORTANT: these selectors could not be verified against live Cloudflare-
# protected HTML without a running Scrapling browser.  If card extraction
# yields nothing in production (you'll see "no advertiser" WARNING logs),
# run scripts/test_scrapling_jobsdb.py and inspect the raw HTML to find the
# correct attribute, then prepend it to this list.
_ADVERTISER_SELECTORS = [
    "[data-automation='jobAdvertiser']",
    "[data-automation='advertiser']",
    "[data-automation='jobCompany']",
    "[data-automation='companyName']",
    "[data-automation='advertiserName']",
]

# A Cloudflare block or network blip on one page is usually transient: a second
# or third attempt (after a growing back-off) often gets through. We retry a
# single page up to this many times before giving up on it.
_MAX_PAGE_RETRIES = 3
_RETRY_BACKOFF_BASE = 5.0  # seconds; multiplied by attempt number, plus jitter

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
        use_company_profile: bool = True,   # default true → /at-this-company (employer-only)
                                             # set false in config for companies without a profile
        max_pages: int = 6,  # ~30 jobs/page → up to 180; stops early if page is empty.
                             # Capped at 6 (not 10) to limit Cloudflare exposure on the
                             # big first-time scrape; raise per-company for >180-job firms.
        proxy: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(
            company, company_slug,
            jobsdb_slug=jobsdb_slug, use_company_profile=use_company_profile,
            max_pages=max_pages, proxy=proxy,
            **kwargs,
        )
        self.jobsdb_slug = jobsdb_slug
        self.use_company_profile = use_company_profile
        self.max_pages = max_pages
        self._proxy = proxy
        base = f"{_BASE_URL}/{jobsdb_slug}-jobs"
        self._listing_url = f"{base}/at-this-company" if use_company_profile else base

    def fetch_jobs(self) -> list[Job]:
        return self._safe_fetch(self._fetch_all)

    def _fetch_url(self, url: str) -> tuple[int, str]:
        """
        Fetch url and return (http_status, html_string).

        Single mockable seam — patch this in tests to inject fixture HTML
        without launching a real Playwright browser.
        """
        from scrapling.fetchers import StealthyFetcher

        # network_idle MUST stay False. JobsDB listing pages run continuous
        # background traffic (ads, analytics beacons) that never goes idle, so
        # network_idle=True makes Playwright block until its internal timeout —
        # the page returns HTTP 200 in ~60s but the call then hangs for the full
        # COMPANY_TIMEOUT_SECS and the company is lost. With network_idle=False
        # the same page (which already contains all job cards) parses in 10–20s.
        kwargs: dict = dict(headless=True, solve_cloudflare=True, network_idle=False)
        if self._proxy:
            kwargs["proxy"] = self._proxy
        page = StealthyFetcher.fetch(url, **kwargs)
        return page.status, str(page.html_content)

    # ── private helpers ────────────────────────────────────────────────────

    def _fetch_all(self) -> list[Job]:
        jobs: list[Job] = []
        for page_num in range(1, self.max_pages + 1):
            try:
                new_jobs = self._fetch_listing_page(page_num)
            except Exception as exc:
                # A page raised even after retries (e.g. the network dropped
                # mid-run). Keep whatever pages we already collected rather than
                # losing the whole company — partial data beats none, and the
                # company-level retry pass can fill the rest in later.
                logger.warning(
                    "%s: page %d failed (%s) — stopping pagination, keeping %d jobs so far.",
                    self.company, page_num, type(exc).__name__, len(jobs),
                )
                break
            if not new_jobs:
                break
            jobs.extend(new_jobs)
        return jobs

    def _fetch_with_retries(self, url: str, page_num: int) -> tuple[int, str]:
        """
        Fetch one listing page, retrying on transient failures.

        Two kinds of transient failure are handled, because both were observed
        killing whole companies in production:

          • Network blips — timeouts, DNS errors, connection resets raised by
            the headless browser. Retried; re-raised only after the final
            attempt (then _fetch_all preserves the pages collected so far).
          • Cloudflare challenges — a challenge *response* (403/429 or a short
            challenge page). Retried; the last challenge response is returned so
            the caller can log a clear "still blocked" error.

        A genuinely good response (200, or any non-challenge status like 404) is
        returned immediately. Each retry waits a growing, jittered back-off so we
        never hammer the source in a tight loop.
        """
        status, html = 0, ""
        for attempt in range(1, _MAX_PAGE_RETRIES + 1):
            try:
                status, html = self._fetch_url(url)
            except Exception as exc:
                logger.warning(
                    "%s page %d: fetch raised %s on attempt %d/%d",
                    self.company, page_num, type(exc).__name__, attempt, _MAX_PAGE_RETRIES,
                )
                if attempt == _MAX_PAGE_RETRIES:
                    raise  # exhausted — let _fetch_all keep partial results
                time.sleep(_RETRY_BACKOFF_BASE * attempt + random.uniform(0, 3))
                continue

            if not _is_challenge(status, html):
                return status, html
            logger.warning(
                "%s page %d: Cloudflare challenge on attempt %d/%d — backing off",
                self.company, page_num, attempt, _MAX_PAGE_RETRIES,
            )
            if attempt < _MAX_PAGE_RETRIES:
                time.sleep(_RETRY_BACKOFF_BASE * attempt + random.uniform(0, 3))
        return status, html

    def _fetch_listing_page(self, page_num: int) -> list[Job]:
        url = f"{self._listing_url}?page={page_num}" if page_num > 1 else self._listing_url
        status, html = self._fetch_with_retries(url, page_num)

        if _is_challenge(status, html):
            logger.error(
                "JobsDB still blocking %s page %d (status %d) after %d attempts — "
                "Scrapling could not bypass Cloudflare. Try updating Scrapling.",
                self.company, page_num, status, _MAX_PAGE_RETRIES,
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

        # Use the advertiser name extracted from the card HTML (Fix A).
        # Fall back to the config company name only when the node is absent —
        # this can happen on hand-crafted fixtures or if JobsDB changes its HTML.
        advertiser = card.get("advertiser") or ""
        if not advertiser:
            logger.warning(
                "%s: no advertiser node found in card for job %s "
                "— falling back to config company name. "
                "If this appears frequently in production, check _ADVERTISER_SELECTORS "
                "against live HTML via scripts/test_scrapling_jobsdb.py.",
                self.company,
                _extract_source_id(card["url"]),
            )
            advertiser = self.company

        return Job(
            source=self.source_name,
            source_id=_extract_source_id(card["url"]),
            company=advertiser,
            company_slug=self.company_slug,
            url=card["url"],
            title=card["title"],
            locations=[loc] if loc else [],
            description_raw="",    # listing page doesn't include full description
            description_clean="",
            posted_at=_parse_listing_date(card.get("listing_date", "")),
            scraped_under_slug=self.company_slug,
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

        # Fix A: extract the real advertiser/hiring company from the card.
        # Try selector candidates in order; take first non-empty text match.
        advertiser: str | None = None
        for sel in _ADVERTISER_SELECTORS:
            node = article.css_first(sel)
            if node:
                text = node.text(strip=True)
                if text:
                    advertiser = text
                    break

        cards.append({
            "title": title_node.text(strip=True) if title_node else "",
            "url": url,
            "location": location_node.text(strip=True) if location_node else "",
            "teaser": teaser_node.text(strip=True) if teaser_node else "",
            "listing_date": date_node.text(strip=True) if date_node else "",
            "advertiser": advertiser,   # None when node is absent → fallback in _card_to_job
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
