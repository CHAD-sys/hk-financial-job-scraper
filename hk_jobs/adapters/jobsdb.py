"""
JobsDB fallback adapter.

╔══════════════════════════════════════════════════════════════════════════╗
║  LEGAL WARNING                                                           ║
║                                                                          ║
║  Reading hk.jobsdb.com's job-search API violates JobsDB's Terms of       ║
║  Service. This adapter exists ONLY as a prototype fallback for           ║
║  companies whose own ATS (Taleo, iCIMS, etc.) is hostile to direct       ║
║  scraping.                                                               ║
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

WHY THIS IS A JSON API ADAPTER AND NOT A BROWSER SCRAPER
--------------------------------------------------------
It used to drive a headless browser (Scrapling's StealthyFetcher) against the
human-facing `/{slug}-jobs/at-this-company` HTML page. That stopped working:

  * The HTML page now returns **HTTP 403 with a Cloudflare Turnstile
    challenge** to any non-browser client, and the "managed" challenge is not
    reliably solvable headlessly.
  * Scrapling's Cloudflare solver (`_cloudflare_solver`, still true as of
    0.4.14) ends with `return self._cloudflare_solver(page)` — an **unbounded
    self-recursion with no attempt counter**. When a challenge never clears,
    that call never returns.
  * `StealthyFetcher.fetch()`'s `timeout` bounds individual Playwright
    operations, not the solver's total wall clock, so nothing capped it.

The 2026-08-14 and 2026-08-15 runs are the evidence: all 65 enabled JobsDB
companies hit the pipeline's 1200 s per-company ceiling, 57 of them returned
zero jobs, and both runs were killed by the CI job timeout before enrichment
or publication ever ran. Raising the CI timeout did not help — the second run
simply took 5 hours to fail more completely.

JobsDB's own search API — the one its website's JavaScript calls — is not
behind Cloudflare and answers a plain `httpx` GET in well under a second:

    GET https://hk.jobsdb.com/api/jobsearch/v5/search
        ?siteKey=HK-Main&sourcesystem=houston
        &advertiserid={id}&page={n}&pageSize=100

Measured on the same companies that previously timed out: 0.4–3.9 s each,
with equal or better coverage than the browser path ever returned (e.g. Bank
of China 365 via API vs 304 stored from the old scraper). No browser, no
Cloudflare, no Playwright, no Scrapling.

The API is also *better* data: an exact ISO `listingDate` instead of a
relative "19d ago" string, and a structured `advertiser` object instead of a
guessed-at DOM attribute.

Employer scoping: `advertiserid` restricts results to one advertiser account,
which is what the old `/at-this-company` URL did. We resolve those ids per run
from a keyword search (see `_resolve_advertiser_ids`) so no per-company config
change was needed; set `advertiser_id` in companies.yaml to pin them.

One employer often owns MANY advertiser accounts — measured live: Manulife 18,
AXA 9, ICBC 2, HSBC 1 — because each hiring desk buys its own JobsDB posting
account under the same legal name. Resolving only the busiest one silently
loses most of the employer (Manulife returned 8 jobs instead of 41, AXA 84
instead of 129), so we collect every account whose name matches and fetch them
all. Small accounts cost one request each, so the whole employer still lands
in a few seconds.

Still listing-only: like the Indeed adapter, this returns no full description
(`description_raw`/`description_clean` stay empty). The search API carries only
a teaser, and there is no detail endpoint that isn't Cloudflare-protected.
"""

import logging
import random
import re
import time
from collections import Counter
from datetime import UTC, datetime

import httpx

from hk_jobs.adapters.base import _DEFAULT_HEADERS, BaseAdapter
from hk_jobs.adapters.workday import _strip_html  # noqa: F401 — kept for re-use by other code
from hk_jobs.schema import Job

logger = logging.getLogger(__name__)

_BASE_URL = "https://hk.jobsdb.com"
_SEARCH_API = f"{_BASE_URL}/api/jobsearch/v5/search"

# Query constants the JobsDB site itself sends. siteKey selects the HK site;
# sourcesystem is required — the API returns an error page without it.
_SITE_KEY = "HK-Main"
_SOURCE_SYSTEM = "houston"

# The API caps a page at 100 results. The old HTML page held ~30, so existing
# `max_pages` values in companies.yaml now buy 3× more headroom than they used
# to — which is the right direction, and pagination stops early on totalCount
# anyway, so nothing over-fetches.
_PAGE_SIZE = 100

# Be polite: CLAUDE.md sets ≤3 req/s for every source. One page every 0.35 s
# is well inside that, and a whole company is only a handful of pages.
_PAGE_DELAY_SECS = 0.35

# How many pages of keyword results to scan when discovering an employer's
# advertiser accounts. 3 × 100 results is enough to surface every account for
# the widest-spread employer measured (Manulife, 18 accounts); raising it costs
# one request per page per company for coverage nothing currently needs.
_LOOKUP_PAGES = 3

# ── Advertiser-name matching ──────────────────────────────────────────────────
# Corporate-suffix / location noise words stripped before comparing advertiser
# names, so "China CITIC Bank International Limited", "China CITIC Bank", and
# "CITIC Bank Int'l Ltd." all reduce to the same distinctive token set.
_ADVERTISER_NOISE_TOKENS = frozenset({
    "ltd", "limited", "co", "company", "corporation", "corp", "inc",
    "incorporated", "plc", "llc", "the", "branch",
})


def _normalize_advertiser_tokens(name: str) -> frozenset[str]:
    """Lowercase, strip punctuation + corporate-suffix noise, return token set."""
    cleaned = re.sub(r"[^a-z0-9\s]", " ", name.lower())
    return frozenset(
        t for t in cleaned.split() if t and t not in _ADVERTISER_NOISE_TOKENS
    )


def _advertiser_accepted(advertiser: str, accepted: list[frozenset[str]]) -> bool:
    """
    True if `advertiser` matches any accepted name.

    Match is token-subset in either direction, so a short genuine form
    ("China CITIC Bank") matches a longer legal entity ("China CITIC Bank
    International Limited") and vice-versa, while unrelated banks (Hang Seng,
    Nanyang, Hua Xia, …) share too few tokens and are rejected.
    """
    card = _normalize_advertiser_tokens(advertiser)
    if not card:
        return False
    return any(acc and (acc <= card or card <= acc) for acc in accepted)


# A transient 5xx or network blip is usually just that: a second or third
# attempt (after a growing back-off) normally gets through. Unlike the old
# browser path, every attempt here is bounded by httpx's own timeout, so a
# retry loop can no longer hang the company.
_MAX_PAGE_RETRIES = 3
_RETRY_BACKOFF_BASE = 2.0  # seconds; multiplied by attempt number, plus jitter

# HTTP timeout for one API call. Generous for a JSON endpoint that normally
# answers in under a second, but small enough that three attempts plus
# back-off can never approach the pipeline's per-company ceiling.
_HTTP_TIMEOUT_SECS = 20.0


class JobsDBAdapter(BaseAdapter):
    """
    Fetches one company's jobs from hk.jobsdb.com's JSON search API.

    Listing-only by design: the search API carries a teaser but no full
    description, and there is no detail endpoint outside Cloudflare. Title,
    advertiser, location, and an exact posting date are enough for matching.

    Config keys (companies.yaml):
        jobsdb_slug:          the company's JobsDB URL slug. Used as the
                              keyword when resolving `advertiser_id`.
        advertiser_id:        optional id, or list of ids. Pins the JobsDB
                              advertiser account(s) so no resolution query
                              runs. Set this for companies whose name doesn't
                              resolve cleanly.
        accepted_advertisers: optional extra names accepted when resolving and
                              when filtering results.
        max_pages:            safety cap on pages fetched (100 jobs/page).
        proxy:                optional "http://user:pass@host:port".
    """

    source_name = "jobsdb"

    def __init__(
        self,
        company: str,
        company_slug: str,
        jobsdb_slug: str,
        use_company_profile: bool = True,   # accepted and ignored: the API is
                                             # always advertiser-scoped, so the
                                             # old profile-vs-plain-listing
                                             # distinction no longer exists.
                                             # Kept so existing configs load.
        accepted_advertisers: list[str] | None = None,
        advertiser_id: str | list[str] | None = None,
        max_pages: int = 6,
        proxy: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(
            company, company_slug,
            jobsdb_slug=jobsdb_slug, use_company_profile=use_company_profile,
            accepted_advertisers=accepted_advertisers, advertiser_id=advertiser_id,
            max_pages=max_pages, proxy=proxy,
            **kwargs,
        )
        self.jobsdb_slug = jobsdb_slug
        self.max_pages = max_pages
        self._proxy = proxy
        # Accepts a single id or a list — an employer with several advertiser
        # accounts can pin all of them without needing a second config key.
        if advertiser_id is None:
            self.advertiser_ids: list[str] = []
        elif isinstance(advertiser_id, (list, tuple)):
            self.advertiser_ids = [str(a) for a in advertiser_id if a]
        else:
            self.advertiser_ids = [str(advertiser_id)]

        # Names we accept as "really this company". The configured company name
        # and the JobsDB slug both count, plus anything explicitly listed. This
        # drives BOTH advertiser resolution and the post-fetch safety filter.
        candidates = [company, (jobsdb_slug or "").replace("-", " ")]
        candidates += list(accepted_advertisers or [])
        self._accepted_adv: list[frozenset[str]] = [
            toks for c in candidates if (toks := _normalize_advertiser_tokens(c))
        ]

    def fetch_jobs(self) -> list[Job]:
        return self._safe_fetch(self._fetch_all)

    # ── the single mockable seam ───────────────────────────────────────────

    def _api_client(self) -> httpx.Client:
        """
        HTTP client for one API call: BaseAdapter's browser-like headers plus
        a JSON Accept, and the optional per-company proxy.
        """
        headers = {**_DEFAULT_HEADERS, "Accept": "application/json"}
        kwargs = {"proxy": self._proxy} if self._proxy else {}
        return httpx.Client(
            headers=headers, timeout=_HTTP_TIMEOUT_SECS, follow_redirects=True, **kwargs
        )

    def _get(self, params: dict) -> tuple[int, dict]:
        """
        GET the search API with `params`; return (http_status, decoded_json).

        Single mockable seam — patch this in tests to inject fixture JSON
        without making a network call. Returns {} as the body for any
        non-200 response or undecodable payload.
        """
        query = {
            "siteKey": _SITE_KEY,
            "sourcesystem": _SOURCE_SYSTEM,
            "pageSize": _PAGE_SIZE,
            **params,
        }
        with self._api_client() as client:
            resp = client.get(_SEARCH_API, params=query)
            if resp.status_code != 200:
                return resp.status_code, {}
            try:
                return 200, resp.json()
            except ValueError:
                logger.warning(
                    "%s: JobsDB API returned non-JSON body (%d bytes)",
                    self.company, len(resp.content),
                )
                return 200, {}

    # ── private helpers ────────────────────────────────────────────────────

    def _get_with_retries(self, params: dict, what: str) -> tuple[int, dict]:
        """
        Call `_get`, retrying transient failures with a jittered back-off.

        Every attempt is bounded by the HTTP client's own timeout, so the
        worst case here is a few tens of seconds — never the open-ended hang
        the old headless-browser path could produce.
        """
        status, body = 0, {}
        for attempt in range(1, _MAX_PAGE_RETRIES + 1):
            try:
                status, body = self._get(params)
            except Exception as exc:
                logger.warning(
                    "%s %s: request raised %s on attempt %d/%d",
                    self.company, what, type(exc).__name__, attempt, _MAX_PAGE_RETRIES,
                )
                if attempt == _MAX_PAGE_RETRIES:
                    raise
                time.sleep(_RETRY_BACKOFF_BASE * attempt + random.uniform(0, 1))
                continue

            # 4xx is a real answer (bad advertiser id, removed employer) — do
            # not burn retries on it. Only 5xx and 429 are worth another go.
            if status == 200 or (400 <= status < 500 and status != 429):
                return status, body
            logger.warning(
                "%s %s: HTTP %d on attempt %d/%d — backing off",
                self.company, what, status, attempt, _MAX_PAGE_RETRIES,
            )
            if attempt < _MAX_PAGE_RETRIES:
                time.sleep(_RETRY_BACKOFF_BASE * attempt + random.uniform(0, 1))
        return status, body

    def _resolve_advertiser_ids(self) -> list[str]:
        """
        Find every JobsDB advertiser account belonging to this company.

        JobsDB scopes an employer's own postings by `advertiserid`, which is
        what the old `/at-this-company` URL resolved to internally. Rather than
        requiring new ids in companies.yaml for all 65 companies, we look them
        up: search the company's name, then keep every advertiser whose name
        token-matches ours (the same matching the allowlist uses).

        Returns every match, not just the busiest one. One employer routinely
        owns many accounts (Manulife 18, AXA 9), and taking only the top one
        silently drops most of their jobs — see the module docstring.

        Returns [] when nothing matches — which, checked against the live API,
        means the company genuinely has no current JobsDB postings rather than
        that the lookup failed.
        """
        keywords = (self.jobsdb_slug or self.company).replace("-", " ").replace("&", " ")
        found: dict[str, str] = {}

        for page_num in range(1, _LOOKUP_PAGES + 1):
            status, body = self._get_with_retries(
                {"page": page_num, "keywords": keywords}, "advertiser lookup",
            )
            if status != 200 or not body:
                if page_num == 1:
                    logger.warning(
                        "%s: advertiser lookup failed (HTTP %d) — no jobs fetched.",
                        self.company, status,
                    )
                break

            items = body.get("data") or []
            if not items:
                break
            for item in items:
                adv = item.get("advertiser") or {}
                adv_id, adv_name = adv.get("id"), adv.get("description") or ""
                if adv_id and _advertiser_accepted(adv_name, self._accepted_adv):
                    found.setdefault(str(adv_id), adv_name)
            if len(items) < _PAGE_SIZE:
                break
            time.sleep(_PAGE_DELAY_SECS)

        if not found:
            logger.info(
                "%s: no JobsDB advertiser matched '%s' — treating as no current "
                "JobsDB presence. Pin `advertiser_id` in companies.yaml if this is wrong.",
                self.company, keywords,
            )
            return []

        logger.debug(
            "%s: resolved %d JobsDB advertiser account(s): %s",
            self.company, len(found),
            ", ".join(f"{name} ({aid})" for aid, name in list(found.items())[:5]),
        )
        return list(found)

    def _fetch_all(self) -> list[Job]:
        advertiser_ids = self.advertiser_ids or self._resolve_advertiser_ids()
        if not advertiser_ids:
            return []

        seen: dict[str, dict] = {}
        for advertiser_id in advertiser_ids:
            self._fetch_advertiser(advertiser_id, seen)

        items = self._apply_advertiser_allowlist(list(seen.values()))
        return [self._item_to_job(item) for item in items]

    def _fetch_advertiser(self, advertiser_id: str, seen: dict[str, dict]) -> None:
        """
        Page through one advertiser account, adding its jobs to `seen`.

        Accumulating into a shared dict (rather than returning a list) dedups
        across accounts for free: an employer occasionally cross-posts the same
        job id under two of its own accounts.
        """
        total_count: int | None = None
        start_count = len(seen)

        for page_num in range(1, self.max_pages + 1):
            try:
                status, body = self._get_with_retries(
                    {"page": page_num, "advertiserid": advertiser_id},
                    f"advertiser {advertiser_id} page {page_num}",
                )
            except Exception as exc:
                # Keep whatever pages we already collected rather than losing
                # the whole company — partial data beats none, and the
                # pipeline's retry pass can fill the rest in later.
                logger.warning(
                    "%s: advertiser %s page %d failed (%s) — stopping pagination, "
                    "keeping %d jobs so far.",
                    self.company, advertiser_id, page_num, type(exc).__name__, len(seen),
                )
                return

            if status != 200:
                logger.error(
                    "JobsDB API returned HTTP %d for %s advertiser %s page %d — "
                    "stopping pagination, keeping %d jobs so far.",
                    status, self.company, advertiser_id, page_num, len(seen),
                )
                return

            items = body.get("data") or []
            if not items:
                return
            if total_count is None:
                total_count = body.get("totalCount")

            for item in items:
                job_id = str(item.get("id") or "")
                if job_id:
                    seen[job_id] = item

            # Stop as soon as we hold everything this account says it has, so a
            # 40-job advertiser costs one request rather than `max_pages`.
            if total_count is not None and (len(seen) - start_count) >= total_count:
                return
            time.sleep(_PAGE_DELAY_SECS)

    def _apply_advertiser_allowlist(self, items: list[dict]) -> list[dict]:
        """
        Drop any posting whose advertiser isn't recognisably this company.

        `advertiserid` already scopes the query to a single advertiser, so this
        is a safety net rather than the primary filter — it catches the case
        where resolution latched onto the wrong account. Logs what it dropped
        so a bad resolution is visible rather than silent.
        """
        if not self._accepted_adv:
            return items

        kept, dropped = [], []
        for item in items:
            adv = (item.get("advertiser") or {}).get("description") or ""
            if _advertiser_accepted(adv, self._accepted_adv):
                kept.append(item)
            else:
                dropped.append(adv or "(no advertiser)")

        if dropped:
            summary = ", ".join(f"{n}× {name}" for name, n in Counter(dropped).most_common())
            logger.info(
                "%s: allowlist dropped %d/%d cross-advertiser postings [%s]",
                self.company, len(dropped), len(items), summary,
            )
        return kept

    def _item_to_job(self, item: dict) -> Job:
        adv = (item.get("advertiser") or {}).get("description") or ""
        source_id = str(item.get("id") or "")
        locations = [
            label
            for loc in (item.get("locations") or [])
            if (label := (loc.get("label") or "").strip())
        ]
        return Job(
            source=self.source_name,
            source_id=source_id,
            # Prefer the advertiser's own name, as the HTML adapter did; fall
            # back to the configured name only when the API omits it.
            company=adv or self.company,
            company_slug=self.company_slug,
            url=f"{_BASE_URL}/job/{source_id}",
            title=(item.get("title") or "").strip(),
            locations=locations,
            description_raw="",    # listing-only: the search API has no description
            description_clean="",
            posted_at=_parse_listing_date(item.get("listingDate") or ""),
            scraped_under_slug=self.company_slug,
        )


# ── module-level helpers ──────────────────────────────────────────────────────

def _parse_listing_date(text: str) -> datetime | None:
    """
    Parse the API's `listingDate` into a UTC datetime.

    The JSON API returns an exact ISO-8601 timestamp ("2026-08-14T04:29:42Z"),
    which is strictly better than the relative strings ("19d ago") the old HTML
    listing carried. Returns None for anything unparseable.
    """
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        logger.debug("Unparseable JobsDB listingDate: %r", text)
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


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
