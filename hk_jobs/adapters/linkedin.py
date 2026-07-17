"""
LinkedIn fallback adapter (public *guest* jobs API — no login).

╔══════════════════════════════════════════════════════════════════════════╗
║  LEGAL WARNING                                                           ║
║                                                                          ║
║  Scraping linkedin.com violates LinkedIn's Terms of Service.            ║
║  This adapter exists ONLY as a prototype fallback source, on the same    ║
║  legal footing as the JobsDB and Indeed adapters.                       ║
║                                                                          ║
║  Do NOT use in production without either:                                ║
║    (a) written permission from LinkedIn, or                             ║
║    (b) a paid data-feed / partner API arrangement (e.g. LinkedIn        ║
║        Talent Solutions).                                               ║
║                                                                          ║
║  Public pages only: this adapter uses LinkedIn's UNAUTHENTICATED guest   ║
║  jobs endpoint. It never logs in, never submits credentials, and never   ║
║  attempts to cross the "authwall" sign-in gate. If LinkedIn returns an   ║
║  authwall or a rate-limit block, that page is skipped gracefully.        ║
╚══════════════════════════════════════════════════════════════════════════╝

How it works: LinkedIn's public job search has a guest endpoint that returns a
plain HTML fragment (a list of <li> job cards) with NO JavaScript rendering and
NO Cloudflare — so, unlike JobsDB/Indeed, a normal httpx GET is enough (no
headless browser). We scope to one employer with the `f_C` company filter:

    GET https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search
        ?f_C={company_id}&location={location}&geoId={geo_id}&start={N}

Each card carries: the job's numeric id (in `data-entity-urn="urn:li:jobPosting:N"`),
title, company, location, a canonical /jobs/view/{id} link, and a posted date.

Pagination: `start` advances in steps of 10 (start=0, 10, 20, …). LinkedIn
re-surfaces some cards across pages, so we dedup by job id.

Listing-only: like the Indeed adapter, we fetch listing pages only and never the
per-job detail page, so these rows have NO full description. (A later phase can
add description fetching via the guest jobPosting/{id} endpoint.)
"""

import logging
import random
import re
import time
from datetime import UTC, datetime

from selectolax.parser import HTMLParser

from hk_jobs.adapters.base import BaseAdapter
from hk_jobs.schema import Job

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.linkedin.com"
_SEARCH_PATH = "/jobs-guest/jobs/api/seeMoreJobPostings/search"

# LinkedIn's guest search returns up to 10 cards per request and paginates via
# ?start=<multiple of 10>.
_PAGE_SIZE = 10

# A rate-limit block or network blip on one page is usually transient: a second or
# third attempt (after a growing back-off) often gets through. Mirrors the Indeed
# adapter's retry policy.
_MAX_PAGE_RETRIES = 3
_RETRY_BACKOFF_BASE = 5.0  # seconds; multiplied by attempt number, plus jitter

# Status codes that mean "backed off / blocked" and are worth retrying. 999 is
# LinkedIn's non-standard block code for automated/datacenter traffic.
_BLOCK_STATUS = frozenset({429, 999, 503})

# Signals of the sign-in "authwall" we must NOT try to cross. Public guest pages
# never contain these; a gated response does.
_AUTHWALL_SIGNALS = (
    "authwall",
    "sign in to continue",
    "join linkedin to",
    "please sign in",
)


def _is_authwall(status: int, html: str) -> bool:
    """True if LinkedIn gated us behind sign-in / a rate-limit block."""
    if status in _BLOCK_STATUS or status == 403:
        return True
    # The guest fragment is small; only scan short bodies so a huge real page
    # (with an incidental "sign in" nav link) never false-positives.
    if len(html) < 40_000:
        low = html.lower()
        return any(sig in low for sig in _AUTHWALL_SIGNALS)
    return False


class LinkedInAdapter(BaseAdapter):
    """
    Scrapes one employer's public guest job listings from linkedin.com.

    Plain httpx (no headless browser). Reads the HTML card fragment from the
    guest `seeMoreJobPostings/search` endpoint and fetches listing pages only —
    never per-job detail pages.

    Config keys (from companies.yaml):
        linkedin_company_id: the numeric LinkedIn company id used as `f_C`,
                             e.g. "1382" for Goldman Sachs. Resolve it with
                             scripts/resolve_linkedin_ids.py (Phase 2).
        location_filter:     location string (default "Hong Kong").
        geo_id:              optional numeric LinkedIn geoId for a tighter
                             location filter (e.g. "103291313" for Hong Kong).
        max_pages:           pagination cap (default 8 → up to 80 jobs).
        proxy:               optional "http://user:pass@host:port".
    """

    source_name = "linkedin"

    def __init__(
        self,
        company: str,
        company_slug: str,
        linkedin_company_id: str,
        location_filter: str = "Hong Kong",
        geo_id: str | None = None,
        max_pages: int = 8,
        proxy: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(
            company, company_slug,
            linkedin_company_id=linkedin_company_id, location_filter=location_filter,
            geo_id=geo_id, max_pages=max_pages, proxy=proxy,
            **kwargs,
        )
        self.linkedin_company_id = str(linkedin_company_id)
        self.location_filter = location_filter
        self.geo_id = geo_id
        self.max_pages = max_pages
        self._proxy = proxy

    def fetch_jobs(self) -> list[Job]:
        return self._safe_fetch(self._fetch_all)

    # ── fetch seam (mock this in tests) ─────────────────────────────────────

    def _fetch_url(self, url: str) -> tuple[int, str]:
        """
        Fetch url and return (http_status, html_string).

        Single mockable seam — patch this in tests to inject fixture HTML without
        making a real network call.
        """
        client_kwargs: dict = {}
        if self._proxy:
            client_kwargs["proxy"] = self._proxy
        with self._client(**client_kwargs) as client:
            resp = client.get(url)
        return resp.status_code, resp.text

    # ── private helpers ─────────────────────────────────────────────────────

    def _page_url(self, start: int) -> str:
        from urllib.parse import urlencode

        params = {
            "f_C": self.linkedin_company_id,
            "location": self.location_filter,
            "start": start,
        }
        if self.geo_id:
            params["geoId"] = self.geo_id
        return f"{_BASE_URL}{_SEARCH_PATH}?{urlencode(params)}"

    def _fetch_all(self) -> list[Job]:
        jobs: list[Job] = []
        seen_ids: set[str] = set()  # dedup across pages — LinkedIn repeats cards
        for page_num in range(self.max_pages):
            start = page_num * _PAGE_SIZE
            try:
                new_cards = self._fetch_listing_page(start)
            except Exception as exc:
                # A page raised even after retries (e.g. the network dropped
                # mid-run). Keep whatever pages we already collected rather than
                # losing the whole company — partial data beats none.
                logger.warning(
                    "%s: start=%d failed (%s) — stopping pagination, keeping %d jobs so far.",
                    self.company, start, type(exc).__name__, len(jobs),
                )
                break
            if not new_cards:
                break

            fresh = [c for c in new_cards if c.get("job_id") and c["job_id"] not in seen_ids]
            if not fresh:
                logger.debug(
                    "%s start=%d: all %d cards already seen — stopping pagination.",
                    self.company, start, len(new_cards),
                )
                break
            for c in fresh:
                seen_ids.add(c["job_id"])
                jobs.append(self._card_to_job(c))
        return jobs

    def _fetch_with_retries(self, url: str, start: int) -> tuple[int, str]:
        """
        Fetch one listing page, retrying on transient failures / block responses.

        Mirrors the Indeed adapter: a network exception is retried and re-raised
        only after the final attempt; a block/authwall response is retried and the
        last one returned so the caller can log a clear error. A good response is
        returned immediately.
        """
        status, html = 0, ""
        for attempt in range(1, _MAX_PAGE_RETRIES + 1):
            try:
                status, html = self._fetch_url(url)
            except Exception as exc:
                logger.warning(
                    "%s start=%d: fetch raised %s on attempt %d/%d",
                    self.company, start, type(exc).__name__, attempt, _MAX_PAGE_RETRIES,
                )
                if attempt == _MAX_PAGE_RETRIES:
                    raise  # exhausted — let _fetch_all keep partial results
                time.sleep(_RETRY_BACKOFF_BASE * attempt + random.uniform(0, 3))
                continue

            if not _is_authwall(status, html):
                return status, html
            logger.warning(
                "%s start=%d: authwall/block (status %d) on attempt %d/%d — backing off",
                self.company, start, status, attempt, _MAX_PAGE_RETRIES,
            )
            if attempt < _MAX_PAGE_RETRIES:
                time.sleep(_RETRY_BACKOFF_BASE * attempt + random.uniform(0, 3))
        return status, html

    def _fetch_listing_page(self, start: int) -> list[dict]:
        url = self._page_url(start)
        status, html = self._fetch_with_retries(url, start)

        # Public pages only: if LinkedIn gates us behind sign-in or a block, we
        # stop here and skip the page. We never attempt to authenticate.
        if _is_authwall(status, html):
            logger.error(
                "LinkedIn gated %s at start=%d (status %d) — skipping (public guest "
                "pages only; we do not sign in or cross the authwall).",
                self.company, start, status,
            )
            return []

        if status != 200:
            logger.error("LinkedIn returned HTTP %d for %s start=%d", status, self.company, start)
            return []

        cards = _parse_cards(html)
        if not cards:
            logger.debug(
                "No job cards found for %s at start=%d — stopping pagination.",
                self.company, start,
            )
        return cards

    def _card_to_job(self, card: dict) -> Job:
        job_id = card.get("job_id", "")
        loc = card.get("location", "")

        # On an employer-scoped (f_C) search each card's company is the employer,
        # but we stamp the configured name for consistency across sources.
        company = card.get("company") or self.company

        return Job(
            source=self.source_name,
            source_id=job_id,
            company=company,
            company_slug=self.company_slug,
            url=card.get("url") or f"{_BASE_URL}/jobs/view/{job_id}",
            title=card.get("title", ""),
            locations=[loc] if loc else [],
            description_raw="",    # listing page carries no full description
            description_clean="",
            posted_at=card.get("posted_at"),
            scraped_under_slug=self.company_slug,
            board_signals=card.get("signals") or {},
        )


# ── module-level parsing helpers ───────────────────────────────────────────────

_URN_RE = re.compile(r"urn:li:jobPosting:(\d+)")
_VIEW_ID_RE = re.compile(r"/jobs/view/(?:[^/?]*-)?(\d+)")
_APPLICANTS_RE = re.compile(r"([\d,]+)\s+applicants?", re.I)


def parse_detail_signals(html: str) -> dict:
    """
    Extract P2 market signals from a LinkedIn guest job-detail page.

    Returns {applicant_count, reposted} (only what's present). The applicant count
    comes from the "N applicants" / "Over 200 applicants" caption; "Be among the
    first 25 applicants" is treated as ~25.
    """
    sig: dict = {}
    tree = HTMLParser(html)
    cap = tree.css_first(".num-applicants__caption")
    if cap:
        m = _APPLICANTS_RE.search(cap.text())
        if m:
            sig["applicant_count"] = int(m.group(1).replace(",", ""))
    if "reposted" in html.lower():
        sig["reposted"] = True
    return sig


def _extract_job_id(node) -> str:
    """Pull the numeric job id from the card's entity-urn, falling back to its link."""
    urn = node.attributes.get("data-entity-urn") or ""
    m = _URN_RE.search(urn)
    if m:
        return m.group(1)
    link = node.css_first("a.base-card__full-link") or node.css_first("a[href*='/jobs/view/']")
    if link:
        m = _VIEW_ID_RE.search(link.attributes.get("href") or "")
        if m:
            return m.group(1)
    return ""


def _parse_date(node) -> datetime | None:
    """Read the ISO date from the card's <time datetime="YYYY-MM-DD"> element."""
    t = node.css_first("time")
    if not t:
        return None
    raw = (t.attributes.get("datetime") or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw).replace(tzinfo=UTC)
    except ValueError:
        return None


def _clean_view_url(href: str) -> str:
    """Strip tracking query params from a /jobs/view/ link."""
    return href.split("?", 1)[0] if href else ""


def _parse_cards(html: str) -> list[dict]:
    """
    Extract job cards from a LinkedIn guest-search HTML fragment.

    Each card is a <div class="base-card"> (usually inside an <li>). We read the
    entity-urn job id, title, company, location, canonical link and posted date.

    If this returns 0 on a real page, run scripts/probe_linkedin.py to inspect the
    current live HTML shape (LinkedIn rotates class names periodically).
    """
    tree = HTMLParser(html)
    cards: list[dict] = []
    for node in tree.css("div.base-card"):
        job_id = _extract_job_id(node)
        if not job_id:
            continue  # no stable id → cannot dedup or link; skip

        title_el = node.css_first("h3.base-search-card__title")
        company_el = node.css_first("h4.base-search-card__subtitle")
        loc_el = node.css_first(".job-search-card__location")
        link_el = (
            node.css_first("a.base-card__full-link")
            or node.css_first("a[href*='/jobs/view/']")
        )

        url = _clean_view_url(link_el.attributes.get("href") or "") if link_el else ""

        # Listing-level signals. The applicant-count and full "reposted" flag live on
        # the detail page (captured by the description fetcher); the card exposes the
        # "new"/"reposted" badge via a listdate--new class or explicit text.
        sig: dict = {}
        if node.css_first("time.job-search-card__listdate--new"):
            sig["new_job"] = True
        if "reposted" in (node.text() or "").lower():
            sig["reposted"] = True

        cards.append({
            "job_id": job_id,
            "title": title_el.text(strip=True) if title_el else "",
            "company": company_el.text(strip=True) if company_el else "",
            "location": loc_el.text(strip=True) if loc_el else "",
            "url": url or f"{_BASE_URL}/jobs/view/{job_id}",
            "posted_at": _parse_date(node),
            "signals": sig,
        })
    return cards
