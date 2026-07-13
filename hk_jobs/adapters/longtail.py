"""
Longtail adapter — LLM-based extraction for medium/boutique HK companies that
are NOT on mainstream job boards and have bespoke careers pages.

Each site has a unique structure, so CSS selectors don't generalise. Instead we:
  1. Fetch the careers page (httpx first; Scrapling headless fallback if the page
     is blocked or JS-rendered).
  2. Strip nav/footer/scripts and pull the visible text.
  3. Send that text to DeepSeek and ask for a JSON array of job postings.
  4. Map each posting to a canonical Job with source_tier='boutique' and the LLM's
     per-job extraction_confidence.

Pages that list jobs directly on the careers page with no listing/detail split
(e.g. Hung Sing) are handled naturally — the whole page text goes to the LLM,
which returns however many postings it finds (0, 1, or many).

Requires DEEPSEEK_API_KEY (see .env.example).
"""

from __future__ import annotations

import hashlib
import logging
import random
import threading
import time
from datetime import datetime

from selectolax.parser import HTMLParser

from hk_jobs.adapters.base import BaseAdapter
from hk_jobs.schema import Job

logger = logging.getLogger(__name__)

_TEXT_CAP = 15_000  # chars of visible text sent to the LLM — plenty for a careers page
_MIN_TEXT = 200     # below this, assume the page is JS-rendered/blocked → try a browser

# Rate-limit DeepSeek across the parallel batch (e.g. 55 companies × 1-2 calls). The
# pipeline runs companies concurrently, so this caps how many LLM calls are in flight
# at once and spaces them out to avoid hitting API rate limits. Shared across threads.
_LLM_MAX_CONCURRENCY = 5
_llm_semaphore = threading.Semaphore(_LLM_MAX_CONCURRENCY)

_EXTRACTION_PROMPT = (
    "Extract job postings from this careers page. Return JSON array with fields: "
    "title, location, description, posted_date, confidence (0-1). If no jobs found, "
    "return empty array. Page may be in Traditional Chinese or English.\n\n"
    "Careers page text:\n{text}"
)

# Tags whose text is chrome, not job content.
_STRIP_TAGS = ("script", "style", "noscript", "svg", "nav", "footer", "header", "form")

_CHALLENGE_SIGNALS = ("just a moment", "checking your browser", "cf-challenge", "captcha")


def _visible_text(html: str) -> str:
    """Strip nav/footer/scripts etc. and return the page's visible text."""
    if not html:
        return ""
    tree = HTMLParser(html)
    for tag in _STRIP_TAGS:
        for node in tree.css(tag):
            node.decompose()
    body = tree.body or tree
    text = body.text(separator="\n", strip=True) if body else ""
    # collapse runs of blank lines
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines)


def _needs_browser(status: int, html: str) -> bool:
    """True if the httpx response looks blocked or JS-rendered (empty of real text)."""
    if status in (403, 429) or status == 0:
        return True
    low = html.lower()
    if len(html) < 100_000 and any(sig in low for sig in _CHALLENGE_SIGNALS):
        return True
    return len(_visible_text(html)) < _MIN_TEXT


def _stable_source_id(slug: str, title: str, location: str) -> str:
    """
    Deterministic ID for a boutique posting.

    Longtail pages carry no stable job IDs, so we hash slug+title+location. Same
    posting → same ID across runs, so re-scrapes upsert (not duplicate).
    """
    key = f"{slug}|{title.strip().lower()}|{(location or '').strip().lower()}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _parse_posted_date(value) -> datetime | None:
    """Best-effort parse of the LLM's posted_date string. None if absent/unparseable."""
    if not value or not isinstance(value, str):
        return None
    v = value.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(v, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(v)
    except ValueError:
        return None


def _reveal_click_action(page) -> None:
    """
    Scrapling page_action for click-to-reveal careers pages (e.g. Pioneer): the job
    list only appears after clicking toggle/accordion buttons, so static and even
    plain-rendered HTML shows nothing. Click likely toggle elements, then wait for
    the revealed content to render. Best-effort — every click is guarded so a bad
    element never aborts the fetch. Runs against a SYNC Playwright page.
    """
    selectors = (
        "[aria-expanded='false']", "[data-toggle]", "[data-bs-toggle]",
        ".accordion-button", ".accordion-header", ".accordion-toggle",
        ".collapse-toggle", "summary", "a[href^='#']", "button",
    )
    for sel in selectors:
        try:
            elements = page.query_selector_all(sel)
        except Exception:  # noqa: BLE001
            continue
        for el in elements[:40]:  # cap — avoid pathological pages
            try:
                if el.is_visible():
                    el.click(timeout=1500, no_wait_after=True)
                    page.wait_for_timeout(120)
            except Exception:  # noqa: BLE001 — a failed click must not abort the fetch
                continue
    try:
        page.wait_for_timeout(1000)  # let revealed content settle before we grab HTML
    except Exception:  # noqa: BLE001
        pass


class LongtailAdapter(BaseAdapter):
    """LLM-extraction adapter for one boutique company's careers page."""

    source_name = "longtail"

    def __init__(
        self, company: str, company_slug: str, careers_url: str,
        category: str | None = None, click_to_reveal: bool = False, **kwargs,
    ) -> None:
        super().__init__(
            company, company_slug, careers_url=careers_url, category=category,
            click_to_reveal=click_to_reveal, **kwargs,
        )
        self.careers_url = careers_url
        self.category = category  # business category from config, not LLM-extracted
        self.click_to_reveal = click_to_reveal  # jobs hidden behind interactive toggles

    def fetch_jobs(self) -> list[Job]:
        return self._safe_fetch(self._fetch_all)

    def _fetch_httpx(self, url: str) -> tuple[int, str]:
        """Static fetch via httpx → (status, html); (0, '') on error. Mockable seam."""
        try:
            with self._client(timeout=25.0) as client:
                resp = client.get(url)
            return resp.status_code, resp.text
        except Exception as exc:  # noqa: BLE001 — handled by the browser fallback
            logger.warning("%s: httpx fetch failed (%s)", self.company, type(exc).__name__)
            return 0, ""

    def _fetch_browser(self, url: str, page_action=None) -> tuple[int, str]:
        """
        Rendered fetch via Scrapling's headless browser → (status, html). Mockable seam.
        Optional page_action (a callable taking the Playwright page) runs after
        navigation — used for click-to-reveal pages.
        """
        try:
            from scrapling.fetchers import StealthyFetcher
            kwargs: dict = dict(headless=True, solve_cloudflare=True, network_idle=False)
            if page_action is not None:
                kwargs["page_action"] = page_action
            page = StealthyFetcher.fetch(url, **kwargs)
            return page.status, str(page.html_content)
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s: Scrapling fetch failed (%s)", self.company, type(exc).__name__)
            return 0, ""

    def _extract_jobs(self, html: str) -> list[Job]:
        """Visible-text → DeepSeek → Job objects for one fetched page."""
        text = _visible_text(html)
        if len(text) < 20:
            return []
        postings = self._extract_with_llm(text)
        return [
            self._posting_to_job(p)
            for p in postings
            if isinstance(p, dict) and p.get("title")
        ]

    def _fetch_all(self) -> list[Job]:
        used_browser = False
        browser_failed = False  # Scrapling itself errored (blocked/timeout/crash)

        if self.click_to_reveal:
            # Jobs are hidden behind interactive toggles — static/rendered HTML shows
            # nothing, so drive the browser straight away and click to reveal them.
            status, html = 0, ""
            b_status, b_html = self._fetch_browser(
                self.careers_url, page_action=_reveal_click_action,
            )
            if b_status == 200 and b_html:
                status, html, used_browser = b_status, b_html, True
            elif b_status == 0:
                browser_failed = True
        else:
            # 1) Static fetch first (fast). Escalate to the browser up front only if the
            #    page is outright blocked or has no visible text at all.
            status, html = self._fetch_httpx(self.careers_url)
            if status != 200 or _needs_browser(status, html):
                logger.info(
                    "%s: static fetch thin/blocked (status=%s) — rendering with headless browser",
                    self.company, status,
                )
                b_status, b_html = self._fetch_browser(self.careers_url)
                if b_status == 200 and b_html:
                    status, html, used_browser = b_status, b_html, True
                elif b_status == 0:
                    browser_failed = True

        if status != 200 or not html:
            logger.error("%s: careers page unreachable (status %s)", self.company, status)
            self._log_summary([], used_browser, "scrapling_failed" if browser_failed else "unreachable")
            return []

        jobs = self._extract_jobs(html)

        # 2) Browser-retry-on-zero: JS-rendered SPAs return HTTP 200 with only a
        #    boilerplate shell over httpx, so the LLM finds nothing. If we haven't
        #    rendered with a browser yet, do so before declaring the page empty.
        if not jobs and not used_browser:
            logger.info(
                "%s: 0 jobs from static HTML — retrying via headless browser (JS render)",
                self.company,
            )
            b_status, b_html = self._fetch_browser(self.careers_url)
            if b_status == 200 and b_html:
                used_browser = True
                jobs = self._extract_jobs(b_html)
            elif b_status == 0:
                browser_failed = True

        if not jobs:
            logger.warning(
                "%s: 0 jobs extracted from %s (browser_rendered=%s) — no current openings, "
                "or a discovery issue (e.g. a static listing the model didn't recognise).",
                self.company, self.careers_url, used_browser,
            )
            self._log_summary([], used_browser, "scrapling_failed" if browser_failed else "zero")
            return []

        logger.info(
            "%s: extracted %d job(s) via LLM (browser_rendered=%s)",
            self.company, len(jobs), used_browser,
        )
        for jb in jobs:
            conf = "n/a" if jb.extraction_confidence is None else f"{jb.extraction_confidence:.2f}"
            loc = jb.locations[0] if jb.locations else "—"
            logger.info("  %s: [conf %s] %s (%s)", self.company, conf, jb.title, loc)
        self._log_summary(jobs, used_browser, "ok")
        return jobs

    def _log_summary(self, jobs: list[Job], used_browser: bool, status: str) -> None:
        """One machine-parseable per-company line for the end-of-batch report."""
        confs = [j.extraction_confidence for j in jobs if j.extraction_confidence is not None]
        avg = f"{sum(confs) / len(confs):.2f}" if confs else "n/a"
        logger.info(
            "LONGTAIL-SUMMARY | %s | category=%s | jobs=%d | avg_conf=%s | browser=%s | status=%s",
            self.company, self.category or "-", len(jobs), avg, used_browser, status,
        )

    def _extract_with_llm(self, text: str) -> list[dict]:
        """Send page text to DeepSeek; return the parsed list of posting dicts."""
        from hk_jobs.llm_client import LLMClient

        prompt = _EXTRACTION_PROMPT.format(text=text[:_TEXT_CAP])
        # Rate-limit: cap concurrent DeepSeek calls and space them out across the batch.
        with _llm_semaphore:
            time.sleep(random.uniform(0.2, 0.6))
            try:
                result = LLMClient().extract_json(prompt, max_tokens=3000, temperature=0.1)
            except Exception as exc:  # noqa: BLE001 — one bad company must not kill the run
                logger.error("%s: LLM extraction failed (%s)", self.company, exc)
                return []

        # The prompt asks for a bare array, but tolerate an object wrapper.
        if isinstance(result, dict):
            for key in ("jobs", "postings", "results", "data"):
                if isinstance(result.get(key), list):
                    return result[key]
            return []
        return result if isinstance(result, list) else []

    def _posting_to_job(self, p: dict) -> Job:
        title = str(p.get("title", "")).strip()
        location = str(p.get("location") or "").strip()
        description = str(p.get("description") or "").strip()

        conf = p.get("confidence")
        try:
            confidence = float(conf) if conf is not None else None
        except (TypeError, ValueError):
            confidence = None
        if confidence is not None:
            confidence = max(0.0, min(1.0, confidence))

        return Job(
            source=self.source_name,
            source_id=_stable_source_id(self.company_slug, title, location),
            company=self.company,
            company_slug=self.company_slug,
            url=self.careers_url,  # single page — no per-job detail URL
            title=title,
            locations=[location] if location else [],
            description_raw=description,
            description_clean=description,  # LLM output is already plain text
            posted_at=_parse_posted_date(p.get("posted_date")),
            scraped_under_slug=self.company_slug,
            source_tier="boutique",
            extraction_confidence=confidence,
            category=self.category,
        )
