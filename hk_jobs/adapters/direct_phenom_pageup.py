"""Deterministic readers for four employers' own career feeds.

* Allianz and QBE: Phenom People ``POST /widgets`` (``ddoKey=refineSearch``). One shared
  fetcher, two tenants. The listing row has only a teaser, so each Hong Kong job costs one
  detail-page GET whose JSON-LD ``JobPosting`` carries the full (entity-escaped) description.
  Allianz honours the server-side country facet; QBE ignores it, so QBE is swept in full
  (about 240 jobs, 3 requests) and filtered on the row's own ``country``.
* Bank of China (Hong Kong): PageUp People RSS (``/798/cw/en/rss``) holds every open job with
  the full description and a real advertised date. Department comes from the HTML listing.
* Amundi Hong Kong: Cegid Talentsoft country-filtered RSS. Its ``pubDate`` is only a
  modified stamp (old requisitions get bumped), so ``posted_at`` is left None.
"""

import html
import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from functools import partial

import httpx
from selectolax.parser import HTMLParser

from hk_jobs.adapters.workday import _strip_html
from hk_jobs.schema import Job

logger = logging.getLogger(__name__)

_SLEEP = 0.4  # seconds between requests
_PAGE_CAP = 30

_LD_JSON = re.compile(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', re.S)

_EMPLOYMENT = {
    "full time": "full-time",
    "full_time": "full-time",
    "part time": "part-time",
    "part_time": "part-time",
    "contract": "contract",
    "contractor": "contract",
    "temporary": "contract",
    "intern": "internship",
    "internship": "internship",
}


def _employment_type(value) -> str | None:
    if isinstance(value, list):
        value = value[0] if len(value) == 1 else None
    return _EMPLOYMENT.get(str(value or "").strip().lower())


def _is_hk_label(label: str) -> bool:
    return (label or "").strip().lower().startswith("hong kong")


def _place(label: str) -> str:
    """'Hong Kong, China' -> 'Hong Kong'; 'Frankfurt, Germany, 60323' -> 'Frankfurt, Germany'."""
    parts = [p.strip() for p in (label or "").split(",") if p.strip()]
    if parts and parts[0].lower() == "hong kong":
        return "Hong Kong"
    return ", ".join(dict.fromkeys(parts[:2]))


# ── Phenom People ─────────────────────────────────────────────────────────────

_PHENOM_BASE = {
    "deviceType": "desktop",
    "pageName": "search-results",
    "ddoKey": "refineSearch",
    "sortBy": "",
    "subsearch": "",
    "jobs": True,
    "counts": True,
    "clearAll": False,
    "jdsource": "facets",
    "isSliderEnable": False,
    "siteType": "external",
    "global": True,
    "keywords": "",
    "locationData": {},
    "sort": {"order": "desc", "field": "postedDate"},
}


def phenom_is_hong_kong(row: dict) -> bool:
    """True if Hong Kong is any of the row's offices.

    Multi-location roles can carry a primary city elsewhere (or blank), so look at
    ``multi_location`` as well as the primary ``country``/``location`` fields.
    """
    labels = [row.get("country"), row.get("location"), *(row.get("multi_location") or [])]
    return any(_is_hk_label(label) for label in labels if label)


def parse_phenom_detail(page_html: str) -> dict:
    """The JobPosting JSON-LD object of a detail page, or {} if absent/unreadable."""
    for block in _LD_JSON.findall(page_html):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("@type") == "JobPosting":
            return data
    return {}


def _phenom_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%f%z")
        except ValueError:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def map_phenom_row(
    row: dict, detail: dict, company: str, company_slug: str, site_root: str
) -> Job:
    job_id = str(row["jobId"])
    raw = html.unescape(detail.get("description") or "") or row.get("descriptionTeaser") or ""
    offices = [_place(x) for x in (row.get("multi_location") or [])] or [_place(row.get("location"))]
    offices = list(dict.fromkeys(o for o in offices if o))
    offices.sort(key=lambda o: o != "Hong Kong")  # Hong Kong first, stable otherwise
    return Job(
        source="direct_site",
        source_id=f"{company_slug}:{job_id}",
        company=company,
        company_slug=company_slug,
        url=f"{site_root}/job/{job_id}",
        title=re.sub(r"\s+", " ", row.get("title") or "").strip(),
        description_raw=raw,
        description_clean=_strip_html(raw),
        locations=offices or ["Hong Kong"],
        department=(row.get("category") or "").strip() or None,
        employment_type=_employment_type(detail.get("employmentType") or row.get("type")),
        posted_at=_phenom_date(row.get("postedDate")),
        scraped_under_slug=company_slug,
    )


def _phenom_list(client: httpx.Client, host: str, tenant: dict, selected: dict) -> list[dict]:
    body = {**_PHENOM_BASE, **tenant, "selected_fields": selected, "size": 100}
    rows: dict[str, dict] = {}
    total = None
    for page in range(_PAGE_CAP):
        response = client.post(f"https://{host}/widgets", json={**body, "from": len(rows)})
        response.raise_for_status()
        result = response.json().get("refineSearch") or {}
        total = result.get("totalHits", total)
        page_rows = (result.get("data") or {}).get("jobs") or []
        fresh = [r for r in page_rows if str(r.get("jobId")) not in rows]
        if not fresh:
            break
        for r in fresh:
            rows[str(r["jobId"])] = r
        if total is not None and len(rows) >= total:
            break
        time.sleep(_SLEEP)
    if total is not None and len(rows) != total:
        raise ValueError(f"{host} listing is incomplete: collected {len(rows)} of {total}")
    return list(rows.values())


def fetch_phenom(
    client: httpx.Client,
    company: str,
    company_slug: str,
    *,
    host: str,
    locale: str,
    country: str,
    page_id: str,
    site_path: str,
    selected: dict | None = None,
) -> list[Job]:
    tenant = {
        "lang": locale,
        "country": country,
        "pageId": page_id,
        "all_fields": ["category", "country", "state", "city", "type"],
    }
    site_root = f"https://{host}/{site_path}"
    jobs = []
    rows = [r for r in _phenom_list(client, host, tenant, selected or {}) if phenom_is_hong_kong(r)]
    for row in rows:
        time.sleep(_SLEEP)
        detail = {}
        try:
            page = client.get(f"{site_root}/job/{row['jobId']}")
            page.raise_for_status()
            detail = parse_phenom_detail(page.text)
        except httpx.HTTPError as exc:
            logger.warning("%s detail %s failed (%s); using listing teaser", host, row["jobId"], exc)
        jobs.append(map_phenom_row(row, detail, company, company_slug, site_root))
    return jobs


fetch_allianz = partial(
    fetch_phenom,
    host="careers.allianz.com",
    locale="en_global",
    country="global",
    page_id="page13",
    site_path="global/en",
    selected={"country": ["Hong Kong, China"]},
)
fetch_qbe = partial(
    fetch_phenom,
    host="careers.qbe.com",
    locale="en_gb",
    country="gb",
    page_id="page12",
    site_path="gb/en",
)


# ── Bank of China (Hong Kong): PageUp People ──────────────────────────────────

BOCHK_BASE = "https://careers.pageuppeople.com/798/cw/en"
_PAGEUP_NS = {"job": "http://pageuppeople.com/"}


def _pageup_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value.strip().replace(" Z", " GMT")).astimezone(UTC)
    except (TypeError, ValueError):
        return None


def parse_bochk_rss(xml_bytes: bytes, company: str, company_slug: str) -> list[Job]:
    root = ET.fromstring(xml_bytes)
    jobs: dict[str, Job] = {}
    for item in root.findall("./channel/item"):

        def get(tag: str) -> str:
            return (item.findtext(tag, namespaces=_PAGEUP_NS) or "").strip()

        if get("job:location").lower() != "hong kong":
            continue
        job_id = get("job:refNo")
        if not job_id or job_id in jobs:
            continue
        functions = []
        for cat in item.findall("job:category", _PAGEUP_NS):
            for part in (cat.text or "").split(","):
                if "|" in part:
                    functions.append(part.split("|", 1)[1].strip())
        functions = list(dict.fromkeys(functions))
        raw = item.findtext("job:description", namespaces=_PAGEUP_NS) or ""
        closing = _pageup_date(get("job:closingDate"))
        jobs[job_id] = Job(
            source="direct_site",
            source_id=f"{company_slug}:{job_id}",
            company=company,
            company_slug=company_slug,
            url=get("link") or f"{BOCHK_BASE}/job/{job_id}",
            title=re.sub(r"\s+", " ", get("title")),
            description_raw=raw,
            description_clean=_strip_html(raw),
            locations=["Hong Kong"],
            department=functions[0] if functions else None,
            employment_type=_employment_type(get("job:workType")),
            posted_at=_pageup_date(get("pubDate")),
            scraped_under_slug=company_slug,
            board_signals={
                "entity": get("job:businessLayer1") or None,
                "job_functions": functions,
                "closing_date": closing.isoformat() if closing else None,
            },
        )
    return list(jobs.values())


def parse_bochk_departments(listing_html: str) -> tuple[dict[str, str], bool]:
    """({job id: department}, has_more_pages) from one HTML listing page."""
    tree = HTMLParser(listing_html)
    out: dict[str, str] = {}
    for tr in tree.css("#recent-jobs-content tr"):
        link = tr.css_first("a.job-link")
        cells = tr.css("td")
        match = re.search(r"/job/(\d+)", (link.attributes.get("href") or "") if link else "")
        if match and len(cells) > 1 and cells[1].text(strip=True):
            out[match.group(1)] = cells[1].text(strip=True)
    return out, tree.css_first("a.more-link") is not None


def _bochk_departments(client: httpx.Client) -> dict[str, str]:
    departments: dict[str, str] = {}
    for page in range(1, 8):
        time.sleep(_SLEEP)
        response = client.get(f"{BOCHK_BASE}/listing/", params={"page": page, "page-items": 100})
        response.raise_for_status()
        found, more = parse_bochk_departments(response.text)
        if not found or set(found) <= set(departments):
            break
        departments.update(found)
        if not more:
            break
    return departments


def fetch_bochk(client: httpx.Client, company: str, company_slug: str) -> list[Job]:
    response = client.get(f"{BOCHK_BASE}/rss")
    response.raise_for_status()
    jobs = parse_bochk_rss(response.content, company, company_slug)
    if not jobs:
        return jobs
    try:
        departments = _bochk_departments(client)
    except httpx.HTTPError as exc:
        logger.warning("BOCHK department listing failed (%s); keeping job function", exc)
        departments = {}
    for job in jobs:
        dept = departments.get(job.source_id.split(":", 1)[1])
        if dept:
            job.department = dept
    return jobs


# ── Amundi Hong Kong: Cegid Talentsoft RSS ────────────────────────────────────

AMUNDI_BASE = "https://jobs.amundi.com"
AMUNDI_HK_COUNTRY_ID = 1693
_AMUNDI_RSS_CAP = 20  # the handler silently truncates at 20 items
_AMUNDI_TYPE_PREFIX = "Types de métiers Crédit Agricole S.A./"
_AMUNDI_CONTRACT = {
    "cdi": "full-time",
    "cdd": "contract",
    "stage": "internship",
    "alternance": "internship",
}


def parse_amundi_rss(xml_bytes: bytes, company: str, company_slug: str) -> list[Job]:
    items = ET.fromstring(xml_bytes).findall("./channel/item")
    if len(items) >= _AMUNDI_RSS_CAP:
        raise ValueError(f"Amundi RSS reached its {_AMUNDI_RSS_CAP}-item cap; feed is truncated")
    jobs: dict[str, Job] = {}
    for item in items:
        link = (item.findtext("link") or "").strip()
        match = re.search(r"idOffre=(\d+)", link)
        cats = [(c.text or "").strip() for c in item.findall("category")]
        if not match or len(cats) < 3 or cats[2].replace("-", " ").lower() != "hong kong":
            continue
        job_id = match.group(1)
        if job_id in jobs:
            continue
        title = (item.findtext("title") or "").strip()
        _, sep, rest = title.partition(" - ")
        raw = item.findtext("description") or ""
        jobs[job_id] = Job(
            source="direct_site",
            source_id=f"{company_slug}:{job_id}",
            company=company,
            company_slug=company_slug,
            url=link,
            title=re.sub(r"\s+", " ", rest if sep else title).strip(),
            description_raw=raw,
            description_clean=_strip_html(raw),
            locations=["Hong Kong"],
            department=cats[0].removeprefix(_AMUNDI_TYPE_PREFIX) or None,
            employment_type=_AMUNDI_CONTRACT.get(cats[1].lower()),
            posted_at=None,  # pubDate is a modified stamp, not a posting date
            scraped_under_slug=company_slug,
        )
    return list(jobs.values())


def fetch_amundi(client: httpx.Client, company: str, company_slug: str) -> list[Job]:
    response = client.get(
        f"{AMUNDI_BASE}/handlers/offerRss.ashx",
        params={"LCID": 1036, "Rss_JobCountry": AMUNDI_HK_COUNTRY_ID},
    )
    response.raise_for_status()
    return parse_amundi_rss(response.content, company, company_slug)


SITE_FETCHERS = {
    "allianz": fetch_allianz,
    "qbe": fetch_qbe,
    "bochk": fetch_bochk,
    "amundi-hk": fetch_amundi,
}
