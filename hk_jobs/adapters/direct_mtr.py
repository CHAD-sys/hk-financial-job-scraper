"""MTR's public Taleo careers portal, read without a browser or login.

The old Taleo page keeps its job rows in ``api.fillList`` JavaScript data.
The displayed HTML is only an empty row template. A form POST requesting 100
jobs per page returns the same data, so we parse that known layout directly.
"""

from __future__ import annotations

import ast
import html as html_lib
import logging
import re
import time
from datetime import UTC, datetime
from urllib.parse import unquote

import httpx
from scrapling import Selector

from hk_jobs.adapters.workday import _strip_html
from hk_jobs.schema import Job

logger = logging.getLogger(__name__)
_BASE = "https://careers.mtr.com.hk/careersection/mtr_external"
_LIST = f"{_BASE}/joblist.ftl"
_ROW_WIDTH = 43  # Taleo listRequisition._hles, verified on the live portal
_LIST_RE = re.compile(
    r"api\.fillList\('requisitionListInterface',\s*'listRequisition',\s*(\[.*?\])\);",
    re.S,
)
_DETAIL_RE = re.compile(
    r"api\.fillList\('requisitionDescriptionInterface',\s*'descRequisition',\s*(\[.*?\])\);",
    re.S,
)


def _values(html: str, pattern: re.Pattern[str]) -> list[str]:
    match = pattern.search(html)
    if not match:
        return []
    # All values in this Taleo script are quoted strings. literal_eval parses
    # escaping without executing the page's JavaScript.
    values = ast.literal_eval(match.group(1))
    return values if isinstance(values, list) else []


def parse_mtr_listing(html: str) -> tuple[int, list[dict[str, str]]]:
    """Return total count and rows from a captured MTR joblist response."""
    page = Selector(content=html)
    total = page.css('input[name="listRequisition.nbElements"]::attr(value)').get()
    if total is None or not total.isdigit():
        raise ValueError("MTR Taleo total count missing from listing")
    total_count = int(total)
    values = _values(html, _LIST_RE)
    if len(values) % _ROW_WIDTH:
        raise ValueError("MTR Taleo row width changed")
    rows = []
    for start in range(0, len(values), _ROW_WIDTH):
        row = values[start : start + _ROW_WIDTH]
        # _hles order: Taleo internal ID, title, public requisition number,
        # work location, schedule, posting and closing dates.
        if not row[3].isdigit() or not row[4].strip():
            continue
        rows.append(
            {
                "id": row[3],
                "title": html_lib.unescape(unquote(row[4])).strip(),
                "requisition": row[12],
                "location": row[13],
                "schedule": row[19],
                "posted": row[20],
                "closes": row[21],
            }
        )
    return total_count, rows


def parse_taleo_detail(html: str) -> tuple[str, str]:
    """Decode the HTML description fields in Taleo's detail data array."""
    values = _values(html, _DETAIL_RE)
    parts: list[str] = []
    for value in values:
        if isinstance(value, str) and value.startswith("!*!%3C"):
            decoded = unquote(value[3:])
            if decoded not in parts:
                parts.append(decoded)
    raw = "\n".join(parts)
    return raw, _strip_html(raw).strip()


def _posted(text: str) -> datetime | None:
    try:
        return datetime.strptime(text, "%d/%b/%y").replace(tzinfo=UTC)
    except ValueError:
        return None


def fetch_mtr(client: httpx.Client, company: str, company_slug: str) -> list[Job]:
    """Fetch all MTR postings from its first-party Taleo site.

    A caller supplies the shared HTTP client. Errors propagate to the parent
    adapter's failure boundary, so an incomplete page is never mistaken for a
    complete empty listing that could close saved roles.
    """
    first = client.get(_LIST)
    first.raise_for_status()
    page = Selector(content=first.text)
    fields = {
        node.attrib["name"]: node.attrib.get("value", "")
        for node in page.css('input[type="hidden"][name]')
    }
    fields["dropListSize"] = "100"
    total, rows = 0, []
    seen: set[str] = set()
    for page_no in range(1, 21):
        fields["rlPager.currentPage"] = str(page_no)
        response = client.post(_LIST, data=fields, headers={"Referer": _LIST})
        response.raise_for_status()
        expected, page_rows = parse_mtr_listing(response.text)
        if page_no == 1:
            total = expected
        elif expected != total:
            raise ValueError("MTR Taleo total changed during pagination")
        if expected and not page_rows:
            raise ValueError("MTR Taleo returned no rows before listing completed")
        for row in page_rows:
            if row["id"] not in seen:
                seen.add(row["id"])
                rows.append(row)
        if len(rows) >= total:
            break
        if len(page_rows) < 100:
            raise ValueError("MTR Taleo listing ended before its stated total")
        time.sleep(0.5)
    if len(rows) < total:
        raise ValueError("MTR Taleo pagination limit reached")

    jobs = []
    for row in rows:
        url = f"{_BASE}/jobdetail.ftl?job={row['id']}"
        time.sleep(0.5)
        detail = client.get(url)
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
                locations=[row["location"]] if row["location"] else [],
                employment_type="full-time" if row["schedule"].lower() == "full-time" else None,
                posted_at=_posted(row["posted"]),
                board_signals={"requisition_no": row["requisition"], "closes": row["closes"]},
            )
        )
    logger.info("MTR direct portal: fetched %d jobs", len(jobs))
    return jobs
