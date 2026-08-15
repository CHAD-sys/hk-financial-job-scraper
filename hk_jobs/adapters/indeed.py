"""
Indeed fallback adapter.

╔══════════════════════════════════════════════════════════════════════════╗
║  LEGAL WARNING                                                           ║
║                                                                          ║
║  Scraping hk.indeed.com violates Indeed's Terms of Service.             ║
║  This adapter exists ONLY as a prototype fallback for a few large HK     ║
║  employers whose own ATS is hard to reach and who have near-zero clean   ║
║  presence on JobsDB (Goldman Sachs, JPMorgan, DBS).                     ║
║                                                                          ║
║  Do NOT use in production without either:                                ║
║    (a) written permission from Indeed, or                               ║
║    (b) a paid data-feed / partner API arrangement.                      ║
║                                                                          ║
║  If this project ever leaves prototype stage, replace this adapter       ║
║  with direct ATS access or a licensed data source.                       ║
╚══════════════════════════════════════════════════════════════════════════╝

Why this exists: Goldman Sachs, JPMorgan and DBS have near-zero clean listings on
JobsDB, but each maintains an employer-scoped Indeed company page
(`hk.indeed.com/cmp/<slug>/jobs`) that lists their HK roles. A Phase-1 probe
confirmed those pages clear Cloudflare, carry clean structured JSON, and — because
they are employer-scoped — carry effectively zero cross-company contamination.

Cloudflare bypass: like the JobsDB adapter, this uses Scrapling's StealthyFetcher
(headless Playwright with fingerprint spoofing + Turnstile solving). Each fetch
takes ~15 s, so we fetch listing pages only — never per-job detail pages.

Extraction: Indeed does NOT render cards into the DOM. The full card list ships
inline in a <script> as:

    window.mosaic.providerData["mosaic-provider-jobcards"] = { ... };

We read that JSON directly (the equivalent of the JobsDB GraphQL find) rather than
scraping rendered HTML. The job list lives at
`metaData.mosaicProviderJobCardsModel.results`.

Pagination: `?start=N` in steps of 20 (page 2 = ?start=20, page 3 = ?start=40, …).
NOTE: ?start=10 is rounded back to page 1 — only multiples of 20 advance the page.
Indeed re-surfaces some sponsored/featured cards across pages, so we dedup by
`jobkey`.

Public pages only: this adapter never logs in, never submits credentials, and never
attempts to cross a human-verification or login wall. If a page returns a login
wall or an unsolved Cloudflare challenge, that page is skipped gracefully.

Requirements (beyond requirements.txt):
    pip install "scrapling[fetchers]"
    scrapling install
"""

import json
import logging
import random
import time
from datetime import UTC, datetime

from hk_jobs.adapters.base import BaseAdapter
from hk_jobs.schema import Job

logger = logging.getLogger(__name__)

_BASE_URL = "https://hk.indeed.com"

# Indeed company pages list 20 cards per page and paginate with ?start=<multiple of 20>.
_PAGE_SIZE = 20

# A Cloudflare block or network blip on one page is usually transient: a second or
# third attempt (after a growing back-off) often gets through. Mirrors the JobsDB
# adapter's retry policy.
_MAX_PAGE_RETRIES = 3
_RETRY_BACKOFF_BASE = 5.0  # seconds; multiplied by attempt number, plus jitter

# Wall-clock budget for ONE company, checked between pages.
#
# This is damage control, not a cure. A single StealthyFetcher.fetch() call is
# itself unbounded — Scrapling's _cloudflare_solver ends in `return
# self._cloudflare_solver(page)` with no attempt counter (still true in 0.4.14),
# so when a "managed" Turnstile never clears the call simply does not return,
# and the `timeout` argument only bounds individual Playwright operations. We
# cannot cap that from out here; what we CAN do is refuse to start further pages
# once a company has already burned this much, so a blocked employer costs one
# bad page instead of max_pages of them.
#
# 300 s sits under the pipeline's COMPANY_TIMEOUT_SECS (1200) with room for the
# in-flight page to finish, and comfortably above a healthy company (the four
# measured live take 34-163 s for their full pagination).
_COMPANY_BUDGET_SECS = 300.0

# Signals that mean we're still hitting a bot-protection challenge page.
_CHALLENGE_SIGNALS = ("just a moment", "checking your browser", "cf-challenge")

# Signals of a genuine login / human-verification wall we must NOT try to cross.
# Deliberately narrow: the benign header "Sign in" link (secure.indeed.com/auth?…)
# and the Cloudflare token echoed into its continue= param appear on every good
# content page, so keying off those gives false positives. Only real wall *text*
# counts here.
_LOGIN_WALL_SIGNALS = (
    "verify you are human",
    "additional verification required",
    "enter the characters you see",
    "prove you're not a robot",
)


def _is_challenge(status: int, html: str) -> bool:
    """
    Return True if we got a Cloudflare or bot-protection response.

    Only scans for challenge text on short pages — a real Indeed content page is
    ~550 KB, so challenge phrases inside JS bundles never false-positive.
    """
    if status in (403, 429):
        return True
    if len(html) < 100_000:
        return any(sig in html.lower() for sig in _CHALLENGE_SIGNALS)
    return False


def _is_login_wall(html: str) -> bool:
    """True if the page is a login / human-verification wall we must not cross."""
    low = html.lower()
    return any(sig in low for sig in _LOGIN_WALL_SIGNALS)


class IndeedAdapter(BaseAdapter):
    """
    Scrapes the employer-scoped listing pages for one company from hk.indeed.com.

    Uses Scrapling's StealthyFetcher for Cloudflare bypass. Reads the embedded
    `mosaic-provider-jobcards` JSON (not the DOM) and fetches listing pages only —
    never per-job detail pages.

    Config keys (from companies.yaml):
        indeed_slug: the /cmp/<slug>/jobs slug, e.g. "Goldman-Sachs",
                     "Jpmorganchase-2", "Dbs-Bank".
        max_pages:   pagination cap (default 8 → up to 160 jobs). Raise for
                     employers with more roles (e.g. DBS lists ~300 → ~15 pages).
        proxy:       optional "http://user:pass@host:port".
    """

    source_name = "indeed"

    def __init__(
        self,
        company: str,
        company_slug: str,
        indeed_slug: str,
        max_pages: int = 8,  # 8 × 20 = 160 jobs; stops early when a page is empty.
                             # Capped low to limit Cloudflare exposure per run; raise
                             # per-company in companies.yaml for larger employers.
        proxy: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(
            company, company_slug,
            indeed_slug=indeed_slug, max_pages=max_pages, proxy=proxy,
            **kwargs,
        )
        self.indeed_slug = indeed_slug
        self.max_pages = max_pages
        self._proxy = proxy
        self._listing_url = f"{_BASE_URL}/cmp/{indeed_slug}/jobs"

    def fetch_jobs(self) -> list[Job]:
        return self._safe_fetch(self._fetch_all)

    def _fetch_url(self, url: str) -> tuple[int, str]:
        """
        Fetch url and return (http_status, html_string).

        Single mockable seam — patch this in tests to inject fixture HTML without
        launching a real Playwright browser.
        """
        from scrapling.fetchers import StealthyFetcher

        # network_idle stays False for the same reason as JobsDB: Indeed pages run
        # continuous background traffic (ads, analytics beacons) that never goes
        # idle, so network_idle=True would hang until Playwright's timeout even
        # though the mosaic JSON is already present in the initial HTML.
        kwargs: dict = dict(headless=True, solve_cloudflare=True, network_idle=False)
        if self._proxy:
            kwargs["proxy"] = self._proxy
        page = StealthyFetcher.fetch(url, **kwargs)
        return page.status, str(page.html_content)

    # ── private helpers ────────────────────────────────────────────────────

    def _page_url(self, page_num: int) -> str:
        """page 1 → base URL; page N → ?start=(N-1)*20 (steps of 20, never 10)."""
        if page_num <= 1:
            return self._listing_url
        return f"{self._listing_url}?start={(page_num - 1) * _PAGE_SIZE}"

    def _fetch_all(self) -> list[Job]:
        jobs: list[Job] = []
        seen_keys: set[str] = set()  # dedup across pages — Indeed repeats sponsored cards
        deadline = time.monotonic() + _COMPANY_BUDGET_SECS
        for page_num in range(1, self.max_pages + 1):
            # Stop before starting a page we can't afford. Scrapling's Cloudflare
            # solver can spend 5-20 minutes on a single page when the challenge
            # never clears (measured 2026-08-15: 333 s, 492 s, 671 s, 1170 s), and
            # nothing inside it is bounded — see _fetch_url. Without this, one
            # blocked employer eats its whole 1200 s pipeline slot and starves
            # every other company of a worker.
            if page_num > 1 and time.monotonic() >= deadline:
                logger.warning(
                    "%s: hit the %d s per-company budget after %d page(s) — "
                    "stopping with %d jobs. Source is likely Cloudflare-blocked.",
                    self.company, _COMPANY_BUDGET_SECS, page_num - 1, len(jobs),
                )
                break
            try:
                new_cards = self._fetch_listing_page(page_num)
            except Exception as exc:
                # A page raised even after retries (e.g. the network dropped
                # mid-run). Keep whatever pages we already collected rather than
                # losing the whole company — partial data beats none.
                logger.warning(
                    "%s: page %d failed (%s) — stopping pagination, keeping %d jobs so far.",
                    self.company, page_num, type(exc).__name__, len(jobs),
                )
                break
            if not new_cards:
                break

            # Dedup by jobkey. If a whole page is jobs we've already seen, Indeed has
            # started looping the same cards — stop rather than spin to max_pages.
            fresh = [c for c in new_cards if c.get("jobkey") and c["jobkey"] not in seen_keys]
            if not fresh:
                logger.debug(
                    "%s page %d: all %d cards already seen — stopping pagination.",
                    self.company, page_num, len(new_cards),
                )
                break
            for c in fresh:
                seen_keys.add(c["jobkey"])
                jobs.append(self._card_to_job(c))
        return jobs

    def _fetch_with_retries(self, url: str, page_num: int) -> tuple[int, str]:
        """
        Fetch one listing page, retrying on transient failures.

        Mirrors the JobsDB adapter: network blips are retried and re-raised only
        after the final attempt; a Cloudflare *challenge* response is retried and
        the last challenge response returned so the caller can log a clear error.
        A genuinely good response is returned immediately.
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

    def _fetch_listing_page(self, page_num: int) -> list[dict]:
        url = self._page_url(page_num)
        status, html = self._fetch_with_retries(url, page_num)

        # Public pages only: if Indeed puts up a login / human-verify wall, we stop
        # here and skip the page. We never attempt to authenticate or solve it.
        if _is_login_wall(html):
            logger.error(
                "Indeed showed a login / human-verification wall for %s page %d — "
                "skipping (public pages only; we do not log in or cross verify walls).",
                self.company, page_num,
            )
            return []

        if _is_challenge(status, html):
            logger.error(
                "Indeed still blocking %s page %d (status %d) after %d attempts — "
                "Scrapling could not bypass Cloudflare. Try updating Scrapling.",
                self.company, page_num, status, _MAX_PAGE_RETRIES,
            )
            return []

        if status != 200:
            logger.error("Indeed returned HTTP %d for %s page %d", status, self.company, page_num)
            return []

        cards = _parse_listing_json(html)
        if not cards:
            logger.debug(
                "No job cards found on %s page %d — stopping pagination.",
                self.company, page_num,
            )
        return cards

    def _card_to_job(self, card: dict) -> Job:
        jobkey = card.get("jobkey", "")
        loc = card.get("location", "")

        # On an employer-scoped /cmp/<slug>/jobs page each card's own `company`
        # field is blank (the employer is implied by the page), so we stamp the
        # configured company name. If Indeed ever populates it, we keep that.
        company = card.get("company") or self.company

        return Job(
            source=self.source_name,
            source_id=jobkey,
            company=company,
            company_slug=self.company_slug,
            url=f"{_BASE_URL}/viewjob?jk={jobkey}" if jobkey else self._listing_url,
            title=card.get("title", ""),
            locations=[loc] if loc else [],
            description_raw="",    # listing page carries no full description
            description_clean="",
            posted_at=card.get("posted_at"),
            scraped_under_slug=self.company_slug,
            board_signals=card.get("signals") or {},
        )


# ── module-level parsing helpers ───────────────────────────────────────────────

def _extract_mosaic_json(html: str) -> dict | None:
    """
    Pull the `mosaic-provider-jobcards` JSON object out of the page.

    Indeed assigns it inline:
        window.mosaic.providerData["mosaic-provider-jobcards"] = { ... };

    We locate the assignment, then brace-match to the object's true end rather than
    regex-ing to the first "};" — the object is large and nested and a naive
    non-greedy match can stop early inside a nested string. Returns the parsed dict,
    or None if the blob is absent or unparseable.
    """
    marker = 'window.mosaic.providerData["mosaic-provider-jobcards"]'
    idx = html.find(marker)
    if idx == -1:
        return None
    brace = html.find("{", idx)
    if brace == -1:
        return None

    depth = 0
    in_str = False
    escape = False
    for i in range(brace, len(html)):
        ch = html[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                blob = html[brace:i + 1]
                try:
                    return json.loads(blob)
                except json.JSONDecodeError:
                    logger.warning("mosaic-provider-jobcards JSON failed to parse")
                    return None
    return None


def _epoch_ms_to_dt(value) -> datetime | None:
    """Convert an Indeed epoch-milliseconds timestamp to a UTC datetime."""
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    try:
        return datetime.fromtimestamp(value / 1000, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _parse_listing_json(html: str) -> list[dict]:
    """
    Extract job cards from an Indeed company listing page's embedded JSON.

    The card list lives at:
        mosaic-provider-jobcards → metaData.mosaicProviderJobCardsModel.results

    Each result carries: jobkey, title, company (blank on /cmp/ pages),
    formattedLocation, pubDate/createDate (epoch ms), indeedApplyable.

    If this returns 0 on a real page, run scripts/probe_indeed.py to inspect the
    current live JSON shape.
    """
    data = _extract_mosaic_json(html)
    if not data:
        return []
    results = (
        data.get("metaData", {})
        .get("mosaicProviderJobCardsModel", {})
        .get("results", [])
    )
    cards: list[dict] = []
    for r in results:
        if not isinstance(r, dict):
            continue
        jobkey = r.get("jobkey")
        if not jobkey:
            continue  # no stable ID → cannot dedup or link; skip
        posted_at = _epoch_ms_to_dt(r.get("pubDate")) or _epoch_ms_to_dt(r.get("createDate"))
        cards.append({
            "jobkey": jobkey,
            "title": (r.get("title") or r.get("displayTitle") or "").strip(),
            "company": (r.get("company") or "").strip(),  # blank on employer pages
            "location": (r.get("formattedLocation") or "").strip(),
            "posted_at": posted_at,
            "signals": _extract_signals(r),
        })
    return cards


def _extract_signals(r: dict) -> dict:
    """Pull P2/P3 market signals out of one Indeed mosaic card (only non-empty ones)."""
    def _int(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    sig: dict = {}
    started = _int(r.get("organicApplyStartCount"))
    if started and started > 0:
        sig["applicant_count"] = started              # demand: candidates who started applying
    if r.get("sponsored") or r.get("showSponsoredLabel"):
        sig["sponsored"] = True                        # paid placement
    if r.get("urgentlyHiring"):
        sig["urgently_hiring"] = True
    rating = r.get("companyRating")
    if rating and float(rating) > 0:
        sig["company_rating"] = float(rating)          # employer reputation
    reviews = _int(r.get("companyReviewCount"))
    if reviews and reviews > 0:
        sig["review_count"] = reviews
    if r.get("featuredEmployer") or r.get("isTopRatedEmployer"):
        sig["featured_employer"] = True
    if r.get("employerResponsive"):
        sig["employer_responsive"] = True
    if r.get("jobTypes"):
        sig["job_types"] = r.get("jobTypes")           # Full-time / Contract / Internship
    if r.get("newJob"):
        sig["new_job"] = True
    if r.get("expired"):
        sig["expired"] = True
    sig["apply_on_indeed"] = bool(r.get("indeedApplyable"))
    return sig
