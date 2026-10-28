"""Hong Kong Airport Authority's public Taleo JSON search endpoint.

Its search page is an empty JavaScript shell. The site's own SearchHandler.js
POSTs to ``/rest/jobboard/searchjobs``; this module makes the same request and
maps its JSON results to canonical jobs without browser automation.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import UTC, datetime

import httpx

from hk_jobs.adapters.direct_mtr import _DETAIL_RE, _values, parse_taleo_detail
from hk_jobs.schema import Job

logger = logging.getLogger(__name__)
_BASE = "https://careers.hkairport.com"
_SEARCH_PAGE = f"{_BASE}/careersection/ex/jobsearch.ftl"
_PORTAL_RE = re.compile(r"portalNo:\s*'([0-9]+)'")


def parse_airport_listing(payload: dict) -> tuple[int, list[dict[str, str]]]:
    """Map the live Taleo JSON shape; fail if required fields disappear."""
    paging = payload["pagingData"]
    total = int(paging["totalCount"])
    rows = []
    for item in payload["requisitionList"]:
        columns = item["column"]
        rows.append(
            {
                "id": str(item["jobId"]),
                "requisition": str(item["contestNo"]),
                "title": str(columns[0]).strip(),
                "closes": str(columns[1]),
            }
        )
    return total, rows


def _posted(detail_html: str) -> datetime | None:
    # The Airport's descRequisition array stores posting date at field 13.
    values = _values(detail_html, _DETAIL_RE)
    if len(values) > 13 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", values[13]):
        return datetime.strptime(values[13], "%Y-%m-%d").replace(tzinfo=UTC)
    return None


def fetch_hkairport(client: httpx.Client, company: str, company_slug: str) -> list[Job]:
    """Fetch all postings from the Airport Authority's first-party portal."""
    landing = client.get(_SEARCH_PAGE)
    landing.raise_for_status()
    portal = _PORTAL_RE.search(landing.text)
    if not portal:
        raise ValueError("Airport Taleo portal ID missing from search page")
    endpoint = f"{_BASE}/careersection/rest/jobboard/searchjobs?lang=en&portal={portal.group(1)}"
    headers = {
        "Origin": _BASE,
        "Referer": _SEARCH_PAGE,
        "tz": "Asia/Hong_Kong",
        "tzname": "Hong Kong Standard Time",
    }
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    total = 0
    for page_no in range(1, 21):
        response = client.post(endpoint, json={"pageNo": page_no}, headers=headers)
        response.raise_for_status()
        expected, page_rows = parse_airport_listing(response.json())
        if page_no == 1:
            total = expected
        elif expected != total:
            raise ValueError("Airport Taleo total changed during pagination")
        if expected and not page_rows:
            raise ValueError("Airport Taleo returned no rows before listing completed")
        for row in page_rows:
            if row["id"] not in seen:
                seen.add(row["id"])
                rows.append(row)
        if len(rows) >= total:
            break
        if len(page_rows) < int(response.json()["pagingData"]["pageSize"]):
            raise ValueError("Airport Taleo listing ended before its stated total")
        time.sleep(0.5)
    if len(rows) < total:
        raise ValueError("Airport Taleo pagination limit reached")

    jobs = []
    for row in rows:
        url = f"{_BASE}/careersection/ex/jobdetail.ftl?job={row['id']}"
        time.sleep(0.5)
        detail = client.get(url, headers={"Referer": _SEARCH_PAGE})
        detail.raise_for_status()
        raw, clean = parse_taleo_detail(detail.text)
        jobs.append(
            Job(
                source="direct_site",
                source_id=f"{company_slug}:{row['id']}",
                company=company,
                company_slug=company_slug,
                url=url,
                title=row["title"],
                description_raw=raw,
                description_clean=clean,
                posted_at=_posted(detail.text),
                board_signals={"requisition_no": row["requisition"], "closes": row["closes"]},
            )
        )
    logger.info("Airport direct portal: fetched %d jobs", len(jobs))
    return jobs
