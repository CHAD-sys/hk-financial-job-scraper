"""Deterministic parser for HKMC's public, server-rendered vacancies accordion.

The HKMC-owned website shows full descriptions; each card's Apply link points
to careers.hkmc.com.hk, its external application service provider, not a job
aggregator. The site legal statement governs access; no authwall is crossed.
"""

import logging
from urllib.parse import parse_qs, urlparse

import httpx
from selectolax.parser import HTMLParser

from hk_jobs.adapters.workday import _strip_html
from hk_jobs.schema import Job

logger = logging.getLogger(__name__)
OPENINGS_URL = "https://www.hkmc.com.hk/eng/careers/job_openings.html"


def parse_hkmc_openings(html: str, company: str, company_slug: str) -> list[Job]:
    """Map each rendered accordion item with a valid employer apply link."""
    tree = HTMLParser(html)
    jobs = []
    seen = set()
    for item in tree.css(".list-container .item"):
        detail = item.css_first(".job-detail")
        heading = detail.css_first("h4") if detail else None
        apply = detail.css_first("a.button-download[href]") if detail else None
        if heading is None or apply is None:
            continue
        title = heading.text(strip=True)
        url = apply.attributes.get("href", "")
        parsed = urlparse(url)
        ids = parse_qs(parsed.query).get("postId", [])
        if (
            not title
            or parsed.scheme != "https"
            or parsed.hostname != "careers.hkmc.com.hk"
            or not parsed.path.endswith("/posDetail.html")
            or not ids
            or not ids[0]
        ):
            continue
        source_id = f"{company_slug}:{ids[0]}"
        if source_id in seen:
            continue
        seen.add(source_id)
        category = item.css_first("h3.title")
        # The Apply paragraph is a route, not part of the role description.
        apply_parent = apply.parent
        if apply_parent is not None:
            apply_parent.decompose()
        for junk in detail.css("script, style, noscript"):
            junk.decompose()
        raw = detail.html or ""
        jobs.append(
            Job(
                source="direct_site",
                source_id=source_id,
                company=company,
                company_slug=company_slug,
                url=url,
                title=title,
                description_raw=raw,
                description_clean=_strip_html(raw),
                locations=["Hong Kong"],
                department=category.text(strip=True) if category else None,
                scraped_under_slug=company_slug,
            )
        )
    return jobs


def fetch_hkmc(client: httpx.Client, company: str, company_slug: str) -> list[Job]:
    """Read the single public openings page; warn if its markup changes."""
    response = client.get(OPENINGS_URL)
    response.raise_for_status()
    jobs = parse_hkmc_openings(response.text, company, company_slug)
    if not jobs:
        logger.warning("HKMC openings page yielded no jobs; check vacancy count or markup")
    return jobs
