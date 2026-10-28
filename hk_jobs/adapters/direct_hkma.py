"""Deterministic HKMA vacancies from its public, employer-hosted table.

HKMA also documents a recruitment JSON API, but it returned HTTP 405 during
live verification. The public vacancies page remained accessible and exposes
the same roles as table rows. No browser or third-party board is involved.
"""

import logging
import time
from datetime import datetime
from urllib.parse import urljoin, urlparse

import httpx
from selectolax.parser import HTMLParser

from hk_jobs.adapters.workday import _strip_html
from hk_jobs.schema import Job

logger = logging.getLogger(__name__)
OPENINGS_URL = "https://www.hkma.gov.hk/eng/about-us/join-us/current-vacancies/"
_DETAIL_PREFIX = "/eng/about-us/join-us/current-vacancies/recruit-"
_DELAY = 0.35  # at most 2.9 requests/second, including detail pages


def parse_hkma_openings(html: str, company: str, company_slug: str) -> list[Job]:
    """Map table rows with official vacancy links; ignore unrelated page links."""
    tree = HTMLParser(html)
    jobs = []
    seen = set()
    for row in tree.css("table.small-table tr"):
        link = row.css_first('a[href*="/current-vacancies/recruit-"]')
        if link is None:
            continue
        title = link.text(strip=True)
        url = urljoin(OPENINGS_URL, link.attributes.get("href", ""))
        parsed = urlparse(url)
        source_key = parsed.path.strip("/").split("/")[-1]
        if (
            not title
            or parsed.scheme != "https"
            or parsed.hostname != "www.hkma.gov.hk"
            or not parsed.path.startswith(_DETAIL_PREFIX)
            or not source_key
            or source_key in seen
        ):
            continue
        seen.add(source_key)
        cells = row.css("td")
        date_text = cells[1].text(strip=True) if len(cells) > 1 else ""
        try:
            # This column is the application closing date, not the posting date.
            closing = datetime.strptime(date_text, "%d %B %Y").date().isoformat()
        except (TypeError, ValueError):
            closing = None
        jobs.append(
            Job(
                source="direct_site",
                source_id=f"{company_slug}:{source_key}",
                company=company,
                company_slug=company_slug,
                url=url,
                title=title,
                locations=["Hong Kong"],
                board_signals={"closing_date": closing} if closing else {},
                scraped_under_slug=company_slug,
            )
        )
    return jobs


def parse_hkma_detail(html: str) -> tuple[str, str]:
    """Return raw and plain description from the official vacancy article."""
    node = HTMLParser(html).css_first(".template-text")
    if node is None:
        return "", ""
    for junk in node.css("script, style, noscript"):
        junk.decompose()
    raw = node.html or ""
    return raw, _strip_html(raw)


def fetch_hkma(client: httpx.Client, company: str, company_slug: str) -> list[Job]:
    """Fetch the vacancy table and detail pages with polite request spacing."""
    response = client.get(OPENINGS_URL)
    response.raise_for_status()
    jobs = parse_hkma_openings(response.text, company, company_slug)
    if not jobs:
        logger.warning("HKMA vacancies page yielded no rows; check vacancy count or markup")
    for job in jobs:
        time.sleep(_DELAY)
        try:
            response = client.get(job.url)
            response.raise_for_status()
            job.description_raw, job.description_clean = parse_hkma_detail(response.text)
            if not job.description_clean:
                logger.warning("HKMA vacancy detail had no known content block: %s", job.url)
        except httpx.HTTPError as exc:
            logger.warning("HKMA vacancy detail failed: %s (%s)", job.url, exc)
    return jobs
