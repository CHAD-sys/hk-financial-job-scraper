"""
SAP SuccessFactors (Recruiting Marketing / RMK) adapter.

SuccessFactors is the third ATS named in CLAUDE.md's domain-knowledge table,
and until now the only one with no adapter. Unlike Workday and Eightfold it
exposes no public JSON API on the candidate-facing site — the search results
are rendered server-side into an HTML table — so this adapter parses HTML.

That is still a FIRST-PARTY source: we read the employer's own careers site,
the same page a candidate sees, with no login and no authwall crossed. This
is NOT the JobsDB/Indeed legal posture — there is no aggregator ToS being
violated here. Be polite (we rate-limit between pages) and nothing more.

How to recognise a SuccessFactors career site
---------------------------------------------
The search URL carries RMK's signature query parameters::

    https://careers.hkjc.com/search/?createNewAlert=false&q=Finance
        &locationsearch=&optionsFacetsDD_facility=
        &optionsFacetsDD_location=&optionsFacetsDD_shifttype=

`createNewAlert`, `locationsearch` and the `optionsFacetsDD_*` facet keys are
the tell. The page body then contains ``<tr class="data-row">`` rows, one per
posting, and links of the form ``/job/{slug}/{numeric-id}/``.

Page shape (verified against careers.hkjc.com on 2026-07-29)
------------------------------------------------------------
Each ``tr.data-row`` holds:
    a.jobTitle-link            title + href (href ends /{numeric id}/)
    td.colFacility  .jobFacility    department, e.g. "Finance"
    td.colLocation  .jobLocation    e.g. "Causeway Bay, Hong Kong Island, HK"
    td.colShifttype .jobShifttype   e.g. "Full-time"
    td.colDate      .jobDate        e.g. "26 Jul 2026"

Pagination is ``?startrow=N`` in steps of 25 (`_PAGE_SIZE`).

Why we paginate the WHOLE listing instead of searching (important)
-------------------------------------------------------------------
The obvious approach — ``?q=Finance`` — is wrong twice over, both verified
against careers.hkjc.com on 2026-07-29:

1. ``q=`` is a FULL-TEXT match over the whole posting, not a department
   filter. ``q=Finance`` returned 44 rows of which only 9 sat in the Finance
   facility; 21 were "Charities and Community" grant-making roles that merely
   mention the word "finance" in their body text.
2. Worse, it can MISS. A Finance-facility posting whose body never happens to
   say "finance" would not appear at all. On HKJC the two counts coincide at 9
   today, but that is luck, not a guarantee — and a silent under-collection is
   far more damaging than a noisy over-collection we can filter.

The server-side facet (``?optionsFacetsDD_facility=Finance``) IS authoritative
and returns exactly those 9 — but it does not OR: passing the parameter twice
(Finance + Audit) still returns 9, so it cannot express "these three
departments". Since most employers want more than one department, relying on
it would force one request per department and still miss the empty-facility
rows.

So this adapter does the reliable thing: paginate the full listing with an
empty ``q=`` and filter client-side on ``facility_allowlist``. HKJC is 321
postings = 13 pages, once a day. Set ``max_pages`` high enough to cover the
whole site or you will silently truncate — that is the one footgun here.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import UTC, datetime
from urllib.parse import quote_plus, urljoin

from selectolax.parser import HTMLParser

from hk_jobs.adapters.base import BaseAdapter
from hk_jobs.adapters.workday import _strip_html
from hk_jobs.schema import Job

logger = logging.getLogger(__name__)

_PAGE_SIZE = 25          # SuccessFactors RMK renders 25 rows per search page
_PAGE_SLEEP = 1.0        # politeness delay between listing pages
_DETAIL_SLEEP = 0.5      # politeness delay between detail pages
_MAX_DETAIL = 200        # safety ceiling on per-job detail fetches in one run

# SuccessFactors' free-text "shift type" column → our canonical employment_type.
_SHIFT_TYPE_MAP: dict[str, str] = {
    "full-time": "full-time",
    "full time": "full-time",
    "part-time": "part-time",
    "part time": "part-time",
    "contract": "contract",
    "temporary": "contract",
    "fixed term": "contract",
    "intern": "internship",
    "internship": "internship",
    "trainee": "internship",
}

# Trailing numeric segment of /job/{slug}/{id}/ — the posting's stable RMK id.
_JOB_ID_RE = re.compile(r"/job/[^/]+/(\d+)/?")


def _extract_source_id(href: str) -> str:
    """
    Pull the numeric posting id out of a SuccessFactors job link.

    '/job/Causeway-Bay-Deputy-Executive-Manager%2C-Finance-Hong/1358056566/'
    -> '1358056566'

    Falls back to the full href so a link we cannot parse still yields a
    stable (if ugly) identity rather than colliding with every other job.
    """
    if not href:
        return ""
    m = _JOB_ID_RE.search(href)
    return m.group(1) if m else href


def _parse_listing_date(text: str) -> datetime | None:
    """
    Parse the jobDate column, e.g. '26 Jul 2026' -> 2026-07-26 UTC.

    Returns None (never raises) on anything unrecognised — a missing posted_at
    is survivable, a crashed run is not.
    """
    text = (text or "").strip()
    if not text:
        return None
    for fmt in ("%d %b %Y", "%d %B %Y", "%b %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    logger.debug("Unrecognised SuccessFactors date %r", text)
    return None


def _map_shift_type(text: str) -> str | None:
    """Map the jobShifttype column to our canonical employment_type value."""
    return _SHIFT_TYPE_MAP.get((text or "").strip().lower())


def _cell(row, *selectors: str) -> str:
    """First non-empty text among `selectors` within `row`, else ''."""
    for sel in selectors:
        node = row.css_first(sel)
        if node:
            text = node.text(strip=True)
            if text:
                return text
    return ""


def _parse_listing_html(html: str, base_url: str) -> list[dict]:
    """
    Extract job cards from one SuccessFactors search-results page.

    Returns a list of plain dicts (not Job objects) so this function stays
    trivially testable against a recorded fixture. Rows without a title link
    are skipped — RMK emits a header row that shares some column classes.
    """
    if not html:
        return []
    tree = HTMLParser(html)
    cards: list[dict] = []
    for row in tree.css("tr.data-row"):
        link = row.css_first("a.jobTitle-link")
        if link is None:
            continue
        title = link.text(strip=True)
        href = link.attributes.get("href") or ""
        if not title or not href:
            continue
        cards.append(
            {
                "title": title,
                "url": urljoin(base_url, href),
                "source_id": _extract_source_id(href),
                # Prefer the desktop column; the visible-phone span duplicates it.
                "facility": _cell(row, "td.colFacility span.jobFacility", "span.jobFacility"),
                "location": _cell(row, "td.colLocation span.jobLocation", "span.jobLocation"),
                "shift_type": _cell(row, "td.colShifttype span.jobShifttype", "span.jobShifttype"),
                "posted": _cell(row, "td.colDate span.jobDate", "span.jobDate"),
            }
        )
    return cards


def _extract_description(html: str) -> str:
    """
    Pull the description HTML out of a SuccessFactors job detail page.

    The description lives in ``div.job``, but RMK inlines <style> and <script>
    blocks inside that same div (share-link handlers, print CSS). Those are
    removed first, otherwise the "clean" text ends up carrying CSS rules and
    JavaScript — which would then be fed to the enricher and the embedder.
    """
    if not html:
        return ""
    tree = HTMLParser(html)
    node = tree.css_first("div.job") or tree.css_first(".job")
    if node is None:
        return ""
    for junk in node.css("script, style, noscript"):
        junk.decompose()
    return node.html or ""


def _tidy_text(text: str) -> str:
    """
    Drop whitespace-only lines from stripped RMK text.

    SuccessFactors lays its detail pages out with deeply nested empty block
    elements, so the shared _strip_html() turns one posting into ~130 lines of
    which ~100 hold nothing but a space or a non-breaking space. Its
    ``\\n{3,}`` collapse can't see those — the lines aren't empty, they contain
    whitespace. Left alone this inflates description_clean by roughly a third,
    bills those tokens to the enricher, and shows up as a ragged excerpt on the
    job card.

    Applied only to SuccessFactors output: Workday and JobsDB share
    _strip_html() and their expectations shouldn't shift underneath them.
    """
    if not text:
        return ""
    text = text.replace("\xa0", " ")
    lines = [ln.rstrip() for ln in text.split("\n")]
    kept = [ln for ln in lines if ln.strip()]
    return "\n".join(kept).strip()


class SuccessFactorsAdapter(BaseAdapter):
    """
    Scrapes one employer's SAP SuccessFactors (RMK) careers search.

    companies.yaml config:
        sf_host:            careers hostname, e.g. "careers.hkjc.com"
        search_query:       RMK free-text `q=` value, e.g. "Finance" ("" = all jobs)
        facility_allowlist: optional list of department names to keep; the
                            free-text search is imprecise, so this is usually
                            what you actually want. Omit to keep everything.
        max_pages:          pagination cap (default 10 -> up to 250 postings)
        fetch_details:      set false to skip per-job description fetches
    """

    source_name = "successfactors"

    def __init__(
        self,
        company: str,
        company_slug: str,
        sf_host: str,
        search_query: str = "",
        facility_allowlist: list[str] | None = None,
        max_pages: int = 10,
        fetch_details: bool = True,
        **kwargs,
    ) -> None:
        super().__init__(
            company,
            company_slug,
            sf_host=sf_host,
            search_query=search_query,
            **kwargs,
        )
        self.sf_host = sf_host.strip().rstrip("/").replace("https://", "").replace("http://", "")
        self.search_query = search_query
        # Compare case-insensitively — RMK facet casing is not guaranteed stable.
        self.facility_allowlist = (
            {f.strip().lower() for f in facility_allowlist} if facility_allowlist else None
        )
        self.max_pages = max_pages
        self.fetch_details = fetch_details
        self._base_url = f"https://{self.sf_host}"

    # ── public entry point ────────────────────────────────────────────────────

    def fetch_jobs(self) -> list[Job]:
        """Public entry point — wraps _fetch_all in _safe_fetch for error isolation."""
        return self._safe_fetch(self._fetch_all)

    # ── mockable HTTP seam ────────────────────────────────────────────────────

    def _fetch_url(self, url: str) -> tuple[int, str]:
        """
        Fetch url and return (http_status, html_string).

        Single mockable seam — tests monkeypatch this so no network call is
        ever made. Returns (0, "") on transport error rather than raising, so
        one dead page cannot abort the whole company.
        """
        try:
            with self._client() as client:
                resp = client.get(url)
                return resp.status_code, resp.text
        except Exception as exc:
            logger.warning("%s: fetch failed for %s (%s)", self.company, url, type(exc).__name__)
            return 0, ""

    def _listing_url(self, startrow: int) -> str:
        """Page 1 -> startrow=0; page N -> startrow=(N-1)*25."""
        url = f"{self._base_url}/search/?q={quote_plus(self.search_query)}"
        if startrow:
            url += f"&startrow={startrow}"
        return url

    # ── private helpers ───────────────────────────────────────────────────────

    def _fetch_all(self) -> list[Job]:
        cards: list[dict] = []
        seen_ids: set[str] = set()

        for page_num in range(self.max_pages):
            url = self._listing_url(page_num * _PAGE_SIZE)
            status, html = self._fetch_url(url)
            if status != 200 or not html:
                logger.warning(
                    "%s: SuccessFactors page %d returned status %s — stopping.",
                    self.company, page_num + 1, status,
                )
                break

            page_cards = _parse_listing_html(html, self._base_url)
            if not page_cards:
                break

            # Dedup across pages. If a whole page is rows we've already seen,
            # pagination has started looping — stop rather than spin to max_pages.
            fresh = [c for c in page_cards if c["source_id"] not in seen_ids]
            if not fresh:
                logger.info(
                    "%s: page %d repeated %d already-seen rows — stopping pagination.",
                    self.company, page_num + 1, len(page_cards),
                )
                break
            for c in fresh:
                seen_ids.add(c["source_id"])
            cards.extend(fresh)

            # A short page means we've reached the end of the result set.
            if len(page_cards) < _PAGE_SIZE:
                break
            time.sleep(_PAGE_SLEEP)
        else:
            # Loop ran to max_pages without a short page — there is almost
            # certainly more. Silent truncation would look exactly like "that's
            # all the jobs", so say so loudly.
            logger.warning(
                "%s: hit max_pages=%d (%d rows) without reaching the end of the "
                "listing — results are TRUNCATED. Raise max_pages in companies.yaml.",
                self.company, self.max_pages, len(cards),
            )

        kept = self._apply_facility_filter(cards)
        jobs = [self._map_card(c) for c in kept]

        if self.fetch_details:
            jobs = self._add_descriptions(jobs)

        logger.info(
            "%s: SuccessFactors returned %d posting(s), kept %d after facility filter.",
            self.company, len(cards), len(jobs),
        )
        return jobs

    def _apply_facility_filter(self, cards: list[dict]) -> list[dict]:
        """
        Drop rows whose department isn't in facility_allowlist.

        RMK's q= is full-text, so a search for "Finance" also matches postings
        that merely mention the word. When an allowlist is configured the
        facility column — which is a real structured facet — decides instead.
        """
        if not self.facility_allowlist:
            return cards
        kept, dropped = [], []
        for c in cards:
            if (c.get("facility") or "").strip().lower() in self.facility_allowlist:
                kept.append(c)
            else:
                dropped.append(c.get("facility") or "(none)")
        if dropped:
            logger.info(
                "%s: dropped %d posting(s) outside facility allowlist %s (facilities seen: %s)",
                self.company, len(dropped), sorted(self.facility_allowlist),
                ", ".join(sorted(set(dropped))),
            )
        return kept

    def _map_card(self, card: dict) -> Job:
        location = card.get("location") or ""
        return Job(
            source=self.source_name,
            source_id=card["source_id"],
            company=self.company,
            company_slug=self.company_slug,
            url=card["url"],
            title=card["title"],
            # A single office rendered as "Causeway Bay, Hong Kong Island, HK".
            # Kept whole: splitting on commas would fabricate three locations
            # out of one.
            locations=[location] if location else [],
            department=card.get("facility") or None,
            employment_type=_map_shift_type(card.get("shift_type", "")),
            posted_at=_parse_listing_date(card.get("posted", "")),
        )

    def _add_descriptions(self, jobs: list[Job]) -> list[Job]:
        """
        Fetch each posting's detail page and fill description_raw/_clean.

        Best-effort: a job whose detail page fails keeps its listing data and
        an empty description rather than being dropped.
        """
        out: list[Job] = []
        for i, job in enumerate(jobs):
            if i >= _MAX_DETAIL:
                logger.warning(
                    "%s: detail-fetch ceiling (%d) reached — remaining %d job(s) "
                    "keep listing data only.",
                    self.company, _MAX_DETAIL, len(jobs) - i,
                )
                out.extend(jobs[i:])
                break
            if i:
                time.sleep(_DETAIL_SLEEP)
            status, html = self._fetch_url(job.url)
            if status != 200 or not html:
                logger.warning(
                    "%s: no detail page for '%s' (status %s) — listing data only.",
                    self.company, job.title, status,
                )
                out.append(job)
                continue
            raw = _extract_description(html)
            out.append(
                job.model_copy(
                    update={
                        "description_raw": raw,
                        "description_clean": _tidy_text(_strip_html(raw)),
                    }
                )
            )
        return out
