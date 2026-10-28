"""Deterministic reader for Two Sigma's Avature careers portal.

``/careers/OpenRoles`` is server-rendered, fixed at 10 articles per page
(``jobOffset`` advances it) and ends with a page that has no JobDetail links.
Each vacancy's body is plain HTML on its ``JobDetail/<slug>/<id>`` page. There is
no JSON API and no posting date, so ``posted_at`` stays None.

Two Sigma has a Hong Kong office but no live Hong Kong vacancies when this was
written; the exact Hong Kong location string is unverified, so the filter matches
"hong kong" in the location text or URL slug. robots.txt disallows ``qtvc=``;
this never sends it.
"""

import logging
import re
import time

import httpx
from selectolax.parser import HTMLParser

from hk_jobs.adapters.workday import _strip_html
from hk_jobs.schema import Job

logger = logging.getLogger(__name__)

LIST_URL = "https://careers.twosigma.com/careers/OpenRoles"
_PAGE = 10
_PAGE_CAP = 30
_SLEEP = 0.5
_ID = re.compile(r"/JobDetail/[^?#]+/(\d+)/?$")


def parse_listing(html: str) -> list[dict]:
    """Vacancies on one list page: id, url, title, location, function, level."""
    rows = []
    for article in HTMLParser(html).css("article.article--result"):
        link = article.css_first("h3 a.link[href]")
        if link is None:
            continue
        url = link.attributes.get("href", "")
        match = _ID.search(url)
        if not match:
            continue
        spans = [s.text(strip=True) for s in article.css("span.paragraph_inner-span")]
        rows.append(
            {
                "id": match.group(1),
                "url": url,
                "title": link.text(strip=True),
                "location": re.sub(r"\s+", " ", spans[0]) if spans else "",
                "function": spans[1] if len(spans) > 1 else None,
                "level": spans[2] if len(spans) > 2 else None,
            }
        )
    return rows


def is_hong_kong(row: dict) -> bool:
    return "hong kong" in row["location"].lower() or "/hong-kong" in row["url"].lower()


def parse_description(html: str) -> str:
    """Inner HTML of every value block in the last section that holds a list."""
    sections = [s for s in HTMLParser(html).css("section.js_views") if s.css_first("li")]
    if not sections:
        return ""
    values = sections[-1].css("div.article__content__view__field__value")
    return "\n".join(v.html or "" for v in values)


def fetch_twosigma(client: httpx.Client, company: str, company_slug: str) -> list[Job]:
    listed: dict[str, dict] = {}
    for page in range(_PAGE_CAP):
        response = client.get(LIST_URL, params={"jobRecordsPerPage": _PAGE, "jobOffset": page * _PAGE})
        response.raise_for_status()
        rows = [r for r in parse_listing(response.text) if r["id"] not in listed]
        if not rows:
            break
        listed.update({r["id"]: r for r in rows})
        time.sleep(_SLEEP)

    jobs = []
    for row in (r for r in listed.values() if is_hong_kong(r)):
        time.sleep(_SLEEP)
        detail = client.get(row["url"])
        detail.raise_for_status()
        raw = parse_description(detail.text)
        jobs.append(
            Job(
                source="direct_site",
                source_id=f"{company_slug}:{row['id']}",
                company=company,
                company_slug=company_slug,
                url=row["url"],
                title=row["title"],
                description_raw=raw,
                description_clean=_strip_html(raw),
                locations=["Hong Kong"],
                department=row["function"],
                scraped_under_slug=company_slug,
                board_signals={"experience": row["level"]},
            )
        )
    if not listed:
        logger.warning("Two Sigma listing yielded no vacancies at all; check Avature markup")
    return jobs
