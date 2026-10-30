"""Readers for three small Hong Kong employers' own careers pages.

* HashKey Group: WordPress/Elementor post-category listing (``/page/N/`` until a 404), one
  detail page per role for the description. No posting date on the site.
* Hong Kong Life Insurance: one static CMS page grouped by department, ``dd-mm-yyyy``
  dates, one detail page per role. Single-site Hong Kong employer.
* Wizpresso: careers-page.com hosted board, server-rendered ``?page=N`` listing, one
  detail page per role. No posting date.

All parsing is plain httpx + selectolax. Everything read from a site is treated as data.
"""

import html
import logging
import re
import time
from datetime import UTC, datetime
from urllib.parse import urljoin

import httpx
from selectolax.parser import HTMLParser

from hk_jobs.adapters.workday import _strip_html
from hk_jobs.schema import Job

logger = logging.getLogger(__name__)

_SLEEP = 0.5  # seconds between requests (>= 0.3 required)
_PAGE_CAP = 15
_WIZ_SLEEP = 1.5  # careers-page.com answers 429 at 2 requests/second


def _make_job(
    *,
    company: str,
    company_slug: str,
    native_id: str,
    url: str,
    title: str,
    raw: str,
    locations: list[str],
    department: str | None = None,
    posted_at: datetime | None = None,
) -> Job:
    return Job(
        source="direct_site",
        source_id=f"{company_slug}:{native_id}",
        company=company,
        company_slug=company_slug,
        url=url,
        title=title.strip(),
        description_raw=raw,
        description_clean=_strip_html(raw),
        locations=locations,
        department=department or None,
        posted_at=posted_at,
        scraped_under_slug=company_slug,
    )


def _get(client: httpx.Client, url: str, *, pause: float | None = None, **kw) -> httpx.Response:
    """Polite GET: sleep first, and back off (twice at most) when the host answers 429."""
    for attempt in range(3):
        time.sleep(_SLEEP if pause is None else pause)
        response = client.get(url, **kw)
        if response.status_code != 429 or attempt == 2:
            return response
        try:
            wait = min(float(response.headers.get("retry-after", "")), 30)
        except ValueError:
            wait = 5.0
        time.sleep(wait * (_SLEEP > 0))
    return response


def _unescape_if_escaped(raw: str) -> str:
    """html.unescape once, only when the markup arrived entity-escaped."""
    return html.unescape(raw) if "&lt;" in raw and "<" not in raw else raw


# ── HashKey ───────────────────────────────────────────────────────────────────

HASHKEY_LIST = "https://group.hashkey.com/en/category/roles/"


def parse_hashkey_listing(page_html: str) -> list[dict]:
    rows = []
    for item in HTMLParser(page_html).css("div.e-loop-item"):
        post_id = next(
            (c[5:] for c in (item.attributes.get("class") or "").split() if c.startswith("post-") and c[5:].isdigit()),
            None,
        )
        cells = [n.text(strip=True) for n in item.css(".in_disclosure_date")]
        title = item.css_first(".in_disclosure_tit")
        link = item.css_first(".in_disclosure_but a")
        if not (post_id and title and link and len(cells) >= 3 and link.attributes.get("href")):
            raise ValueError("HashKey listing card has an unexpected structure")
        rows.append(
            {
                "id": post_id,
                "department": cells[0],
                "location": cells[1],
                "type": cells[2],
                "title": title.text(strip=True),
                "url": link.attributes["href"],
            }
        )
    return rows


def is_hashkey_hong_kong(row: dict) -> bool:
    return row["location"].strip().lower() == "hong kong"


def parse_hashkey_description(page_html: str) -> str:
    """HTML of the text widget that follows the 'Job description' heading, or ''."""
    for h3 in HTMLParser(page_html).css("h3"):
        if h3.text(strip=True).lower() != "job description" or h3.parent is None:
            continue
        node = h3.parent.next
        while node is not None:
            if "elementor-widget-text-editor" in (node.attributes.get("class") or ""):
                return node.html or ""
            node = node.next
    return ""


def _hashkey_list_all(client: httpx.Client) -> list[dict]:
    rows: dict[str, dict] = {}
    for page in range(1, _PAGE_CAP + 1):
        response = _get(client, HASHKEY_LIST if page == 1 else f"{HASHKEY_LIST}page/{page}/")
        if response.status_code == 404 and page > 1:
            break
        response.raise_for_status()
        fresh = [r for r in parse_hashkey_listing(response.text) if r["id"] not in rows]
        if not fresh:  # empty or repeated page
            break
        for row in fresh:
            rows[row["id"]] = row
    else:
        raise ValueError("HashKey listing did not end within the page cap")
    return list(rows.values())


def fetch_hashkey(client: httpx.Client, company: str, company_slug: str) -> list[Job]:
    jobs = []
    for row in (r for r in _hashkey_list_all(client) if is_hashkey_hong_kong(r)):
        response = _get(client, row["url"])
        response.raise_for_status()
        raw = parse_hashkey_description(response.text)
        jobs.append(
            _make_job(
                company=company,
                company_slug=company_slug,
                native_id=row["id"],
                url=row["url"],
                title=row["title"],
                raw=raw,
                locations=["Hong Kong"],
                department=row["department"],
            )
        )
    return jobs


# ── Hong Kong Life Insurance ──────────────────────────────────────────────────

HKLIFE_BASE = "https://www.hklife.com.hk/en/join-us/"
_HKLIFE_ID = re.compile(r"index-id-(\d+)\.html")


def parse_hklife_listing(page_html: str) -> list[dict]:
    rows = []
    for item in HTMLParser(page_html).css("#joinUsJobs .accordionItem"):
        dept_node = item.css_first(".accordionTitle span")
        department = dept_node.text(strip=True) if dept_node else None
        for tr in item.css("tr"):
            link = tr.css_first("td a")
            match = _HKLIFE_ID.search(link.attributes.get("href") or "") if link else None
            if not match:
                continue
            th = tr.css_first("th")
            rows.append(
                {
                    "id": match.group(1),
                    "title": link.text(strip=True),
                    "department": department,
                    "date": th.text(strip=True) if th else "",
                    "url": urljoin(HKLIFE_BASE, link.attributes["href"]),
                }
            )
    return rows


def parse_hklife_date(text: str) -> datetime | None:
    try:
        return datetime.strptime(text.strip(), "%d-%m-%Y").replace(tzinfo=UTC)
    except ValueError:
        return None


def parse_hklife_description(page_html: str) -> str:
    """Inner HTML of the #detail block without the title, apply/share widget or scripts."""
    detail = HTMLParser(page_html).css_first("#detail")
    if detail is None:
        return ""
    for node in detail.css("h2, .btnWrap, script, #terms"):
        node.decompose()
    return "".join(c.html or "" for c in detail.iter(include_text=True)).strip()


def fetch_hklife(client: httpx.Client, company: str, company_slug: str) -> list[Job]:
    response = _get(client, HKLIFE_BASE + "index.html")
    response.raise_for_status()
    rows = {r["id"]: r for r in parse_hklife_listing(response.text)}
    if not rows and "joinUsJobs" not in response.text:
        raise ValueError("Hong Kong Life careers page no longer has the job list")
    jobs = []
    for row in rows.values():
        detail = _get(client, row["url"])
        detail.raise_for_status()
        raw = parse_hklife_description(detail.text)
        jobs.append(
            _make_job(
                company=company,
                company_slug=company_slug,
                native_id=row["id"],
                url=row["url"],
                title=row["title"],
                raw=raw,
                locations=["Hong Kong"],
                department=row["department"],
                posted_at=parse_hklife_date(row["date"]),
            )
        )
    return jobs


# ── Wizpresso (careers-page.com) ──────────────────────────────────────────────

WIZPRESSO_BASE = "https://wizpresso.careers-page.com"
_PAGE_OF = re.compile(r"Page\s+(\d+)\s+of\s+(\d+)")
_OPEN_POSITIONS = re.compile(r"(\d+)\s+Open Positions?")


def parse_wizpresso_listing(page_html: str) -> list[dict]:
    rows = []
    for card in HTMLParser(page_html).css("article.job-card"):
        link = card.css_first('a[href^="/jobs/"][data-job-id]')
        if link is None:
            continue
        rows.append(
            {
                "id": link.attributes["data-job-id"],
                "title": (link.attributes.get("data-job-title") or link.text(strip=True)).strip(),
                "city": link.attributes.get("data-job-city") or "",
                "country": link.attributes.get("data-job-country") or "",
                "url": WIZPRESSO_BASE + link.attributes["href"],
            }
        )
    return rows


def is_wizpresso_hong_kong(row: dict) -> bool:
    return (row["country"] or row["city"]).strip().lower() == "hong kong"


def parse_wizpresso_description(page_html: str) -> str:
    node = HTMLParser(page_html).css_first("div.job-post-description")
    return (node.html or "") if node else ""


def _wizpresso_list_all(client: httpx.Client) -> list[dict]:
    rows: dict[str, dict] = {}
    total = None
    for page in range(1, _PAGE_CAP + 1):
        response = _get(client, WIZPRESSO_BASE + "/", pause=_WIZ_SLEEP, params={"page": page})
        response.raise_for_status()
        text = response.text
        match = _OPEN_POSITIONS.search(text)
        if match:
            total = int(match.group(1))
        fresh = [r for r in parse_wizpresso_listing(text) if r["id"] not in rows]
        if not fresh:
            break
        for row in fresh:
            rows[row["id"]] = row
        of = _PAGE_OF.search(text)
        if of and int(of.group(1)) >= int(of.group(2)):
            break
    else:
        raise ValueError("Wizpresso listing did not end within the page cap")
    if total is not None and len(rows) != total:
        raise ValueError(f"Wizpresso listing is incomplete: collected {len(rows)} of {total}")
    return list(rows.values())


def fetch_wizpresso(client: httpx.Client, company: str, company_slug: str) -> list[Job]:
    jobs = []
    for row in (r for r in _wizpresso_list_all(client) if is_wizpresso_hong_kong(r)):
        response = _get(client, row["url"], pause=_WIZ_SLEEP)
        response.raise_for_status()
        raw = _unescape_if_escaped(parse_wizpresso_description(response.text))
        jobs.append(
            _make_job(
                company=company,
                company_slug=company_slug,
                native_id=row["id"],
                url=row["url"],
                title=row["title"],
                raw=raw,
                locations=["Hong Kong"],
            )
        )
    return jobs


SITE_FETCHERS = {
    "hashkey": fetch_hashkey,
    "hong-kong-life-insurance-limited": fetch_hklife,
    "wizpresso": fetch_wizpresso,
}
