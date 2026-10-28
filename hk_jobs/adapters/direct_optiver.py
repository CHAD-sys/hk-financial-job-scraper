"""Deterministic reader for Optiver's own careers JSON endpoint.

``GET /en/api/v1/jobs`` lists every vacancy, 16 per page (``from`` is the
offset; unknown query params are silently ignored and return page 1, so paging
stops on a repeated page rather than trusting the parameter). The list carries
no description or date: both come from the vacancy page — ``datePosted`` from
its JSON-LD and the body from the ``Components.RichText`` hydration payload.

Optiver has a Hong Kong office but no live Hong Kong vacancies when this was
written, so an empty result is the expected state, not a failure. The fetcher
raises if the endpoint's ``totalCount`` and the rows collected disagree.
"""

import json
import logging
import re
import time
from datetime import UTC, datetime

import httpx

from hk_jobs.adapters.workday import _strip_html
from hk_jobs.schema import Job

logger = logging.getLogger(__name__)

SITE = "https://www.optiver.com"
API_URL = f"{SITE}/en/api/v1/jobs"
_PAGE_CAP = 40  # 40 x 16 = 640 vacancies; Optiver lists ~160
_SLEEP = 0.5  # seconds between requests

_RICH_TEXT = re.compile(r"React\.createElement\(Components\.RichText,(\{.*?\})\)\);", re.S)
_LD_JSON = re.compile(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', re.S)


def is_hong_kong(item: dict) -> bool:
    return (item.get("location") or "").strip().lower() == "hong kong" or "/hong-kong/" in (
        item.get("href") or ""
    )


def parse_description(page_html: str) -> str:
    """Body HTML from the first RichText payload, or '' if the page changed."""
    match = _RICH_TEXT.search(page_html)
    if not match:
        return ""
    try:
        return json.loads(match.group(1)).get("text") or ""
    except json.JSONDecodeError:
        return ""


def parse_date_posted(page_html: str) -> datetime | None:
    match = _LD_JSON.search(page_html)
    if not match:
        return None
    try:
        raw = json.loads(match.group(1)).get("datePosted")
        return datetime.fromisoformat(raw).replace(tzinfo=UTC) if raw else None
    except (json.JSONDecodeError, ValueError, AttributeError):
        return None


def map_item(item: dict, page_html: str, company: str, company_slug: str) -> Job:
    raw = parse_description(page_html)
    return Job(
        source="direct_site",
        source_id=f"{company_slug}:{item['componentID']}",
        company=company,
        company_slug=company_slug,
        url=SITE + item["href"],
        title=(item.get("title") or "").strip(),
        description_raw=raw,
        description_clean=_strip_html(raw),
        locations=["Hong Kong"],
        department=item.get("domain") or None,
        posted_at=parse_date_posted(page_html),
        scraped_under_slug=company_slug,
        board_signals={"experience": item.get("experience")},
    )


def _list_all(client: httpx.Client) -> list[dict]:
    items: dict[int, dict] = {}
    total = None
    for page in range(_PAGE_CAP):
        response = client.get(API_URL, params={"from": page * 16})
        response.raise_for_status()
        data = response.json()
        total = data.get("totalCount", total)
        fresh = [i for i in data.get("items") or [] if i.get("componentID") not in items]
        if not fresh:
            break
        for item in fresh:
            items[item["componentID"]] = item
        if total is not None and len(items) >= total:
            break
        time.sleep(_SLEEP)
    if total is not None and len(items) != total:
        raise ValueError(f"Optiver listing is incomplete: collected {len(items)} of {total}")
    return list(items.values())


def fetch_optiver(client: httpx.Client, company: str, company_slug: str) -> list[Job]:
    jobs = []
    for item in (i for i in _list_all(client) if is_hong_kong(i)):
        time.sleep(_SLEEP)
        page = client.get(SITE + item["href"])
        page.raise_for_status()
        jobs.append(map_item(item, page.text, company, company_slug))
    return jobs
