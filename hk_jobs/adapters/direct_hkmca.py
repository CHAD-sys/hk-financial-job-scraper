"""Deterministic extraction from HKMC Annuity's own static careers page.

The page embeds each opening in a ``.set_job`` block. Its category heading is
in the surrounding dropdown; the page has no per-role URL or source job ID.

Rights review: https://www.hkmca.hk/eng/legal_statement.html restricts
unauthorised copying, display, and reuse; do not enable publication without
the owner's permission review.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx
from selectolax.parser import HTMLParser

from hk_jobs.schema import Job

CAREERS_URL = "https://www.hkmca.hk/eng/about_us/careers.html"
_CLOSING_DATE = re.compile(r"Closing Date:\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})", re.I)


def parse_hkmca(
    html: str,
    company: str,
    company_slug: str,
    *,
    today: date | None = None,
) -> list[Job]:
    """Return currently open roles; no page chrome or invented posting dates."""
    today = today or datetime.now(ZoneInfo("Asia/Hong_Kong")).date()
    tree = HTMLParser(html)
    jobs: list[Job] = []
    for group in tree.css(".cms_toggle_dropdown"):
        heading = group.css_first(".cms_dropdown_inner h2")
        department = heading.text(strip=True) if heading else None
        for block in group.css(".set_job"):
            title_node = block.css_first("h3.career_title")
            if not title_node:
                continue
            title = title_node.text(strip=True)
            if not title:
                continue
            raw = block.html
            clean = block.text(separator="\n", strip=True)
            closing = _CLOSING_DATE.search(clean)
            if closing:
                try:
                    if datetime.strptime(closing.group(1), "%d %B %Y").date() < today:
                        continue
                except ValueError:
                    pass  # Keep the visible role when a date is malformed.
            key = f"{company_slug}|{department or ''}|{title}".casefold()
            source_id = f"{company_slug}:{hashlib.sha256(key.encode()).hexdigest()[:16]}"
            jobs.append(
                Job(
                    source="direct_site",
                    source_id=source_id,
                    company=company,
                    company_slug=company_slug,
                    url=CAREERS_URL,
                    title=title,
                    department=department,
                    description_raw=raw,
                    description_clean=clean,
                    locations=["Hong Kong"],
                )
            )
    return jobs


def fetch_hkmca(client: httpx.Client, company: str, company_slug: str) -> list[Job]:
    """Fetch a single first-party HTML page and parse its opening blocks."""
    response = client.get(CAREERS_URL)
    response.raise_for_status()
    return parse_hkmca(response.text, company, company_slug)
