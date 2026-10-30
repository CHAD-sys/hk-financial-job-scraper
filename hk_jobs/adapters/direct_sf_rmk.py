"""Readers for employer career sites built on SAP SuccessFactors Recruiting Marketing (RMK).

EY, Zurich and Swiss Re all run the same server-rendered template: ``/search/`` lists
``tr.data-row`` rows 25 at a time (``startrow`` offset) and accepts a ``locationsearch``
filter that matches *any* of a posting's locations; each ``/job/<slug>/<id>/`` page
carries schema.org microdata (``datePosted``, one address group per office) and the
body in ``span.jobdescription``.

One shared parser/fetcher is configured per tenant (``SfTenant``) and exposed through
thin ``functools.partial`` wrappers. A posting is kept when its listing location or any
location on its detail page is Hong Kong (multi-office postings only show their first
office in the listing). The fetcher raises ``ValueError`` if the collected rows disagree
with the total printed by the listing.
"""

import functools
import logging
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urljoin

import httpx
from selectolax.parser import HTMLParser

from hk_jobs.adapters.workday import _strip_html
from hk_jobs.schema import Job

logger = logging.getLogger(__name__)

_PAGE_SIZE = 25
_PAGE_CAP = 40  # 40 x 25 = 1000 HK-filtered postings; the real counts are < 50
_SLEEP = 0.5  # seconds between requests (robots.txt allows /search/ and /job/)
_TOTAL = re.compile(r"of\s*(?:<b>)?\s*(\d+)\s*(?:</b>)?", re.I)
_ID = re.compile(r"/(\d+)/?$")
_NOISE_LOCATION = re.compile(r"\+\s*\d+\s*more.*$", re.I | re.S)


@dataclass(frozen=True)
class SfTenant:
    base: str  # scheme + host, no path
    search_path: str  # e.g. "/search/" or "/ey/search/"
    date_formats: tuple[str, ...]  # listing date formats (fallback when no detail date)
    department: str  # "column" -> listing colDepartment, "segment" -> detail industry, "" -> none


EY = SfTenant("https://careers.ey.com", "/ey/search/", ("%b %d, %Y",), "")
ZURICH = SfTenant("https://www.careers.zurich.com", "/search/", ("%b %d, %Y",), "column")
SWISS_RE = SfTenant("https://careers.swissre.com", "/search/", ("%d %b %Y",), "segment")


def is_hong_kong_text(text: str) -> bool:
    low = (text or "").strip().lower()
    return "hong kong" in low or bool(re.search(r",\s*hk\b", low)) or low == "hk"


def _text(node) -> str:
    return " ".join(node.text().split()) if node is not None else ""


def parse_total(page_html: str) -> int | None:
    label = HTMLParser(page_html).css_first("span.paginationLabel")
    if label is None:
        return None
    match = _TOTAL.search(label.html)
    return int(match.group(1)) if match else None


def parse_listing(page_html: str) -> list[dict]:
    """One dict per distinct posting id on a results page (desktop + phone anchors collapse)."""
    rows: dict[str, dict] = {}
    for tr in HTMLParser(page_html).css("tr.data-row"):
        anchor = tr.css_first("a.jobTitle-link")
        if anchor is None:
            continue
        href = anchor.attributes.get("href") or ""
        match = _ID.search(href)
        if not match or match.group(1) in rows:
            continue
        loc = tr.css_first("td.colLocation span.jobLocation") or tr.css_first("span.jobLocation")
        more = loc.css_first("small") if loc is not None else None
        location = _text(loc)
        if more is not None:
            location = _NOISE_LOCATION.sub("", location).strip()
        rows[match.group(1)] = {
            "id": match.group(1),
            "title": anchor.text(strip=True),
            "href": href,
            "location": location,
            "has_more_locations": more is not None,
            "department": _text(tr.css_first("td.colDepartment span.jobDepartment")),
            "date": _text(tr.css_first("td.colDate span.jobDate")),
        }
    return list(rows.values())


def parse_detail_date(value: str | None) -> datetime | None:
    """``Thu Oct 22 02:00:00 UTC 2026`` -> aware UTC datetime."""
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%a %b %d %H:%M:%S UTC %Y").replace(tzinfo=UTC)
    except ValueError:
        return None


def _normalise_location(text: str) -> str:
    return "Hong Kong" if is_hong_kong_text(text) else text.strip()


def _inner_html(node) -> str:
    if node is None:
        return ""
    return "".join(child.html or "" for child in node.iter(include_text=True)).strip()


def parse_detail(page_html: str) -> dict:
    tree = HTMLParser(page_html)
    locations: list[str] = []
    for meta in tree.css("meta[itemprop]"):
        prop, content = meta.attributes.get("itemprop"), (meta.attributes.get("content") or "")
        if prop == "streetAddress" and content.strip():
            locations.append(_normalise_location(content))
        elif prop == "addressLocality" and content.strip():
            locations.append(_normalise_location(content))
    seen: set[str] = set()
    locations = [x for x in locations if not (x in seen or seen.add(x))]
    desc = tree.css_first("span.jobdescription") or tree.css_first("[itemprop=description]")
    date_meta = tree.css_first('meta[itemprop="datePosted"]')
    segment = tree.css_first("[itemprop=industry]")
    return {
        "locations": locations,
        "description": _inner_html(desc),
        "posted_at": parse_detail_date(date_meta.attributes.get("content") if date_meta else None),
        "segment": " ".join(segment.text().split()) if segment is not None else "",
    }


def _parse_listing_date(value: str, formats: tuple[str, ...]) -> datetime | None:
    for fmt in formats:
        try:
            return datetime.strptime(value.strip(), fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def map_job(row: dict, detail: dict, tenant: SfTenant, company: str, company_slug: str) -> Job:
    raw = detail["description"]
    locations = detail["locations"] or ([_normalise_location(row["location"])] if row["location"] else [])
    if "Hong Kong" in locations:  # Hong Kong first, the rest of the real office list after it
        locations = ["Hong Kong"] + [x for x in locations if x != "Hong Kong"]
    department = row["department"] if tenant.department == "column" else None
    if tenant.department == "segment":
        department = detail["segment"]
    return Job(
        source="direct_site",
        source_id=f"{company_slug}:{row['id']}",
        company=company,
        company_slug=company_slug,
        url=urljoin(tenant.base, row["href"]),
        title=row["title"].strip(),
        description_raw=raw,
        description_clean=_strip_html(raw),
        locations=locations,
        department=department or None,
        posted_at=detail["posted_at"] or _parse_listing_date(row["date"], tenant.date_formats),
        scraped_under_slug=company_slug,
    )


def _list_hong_kong(client: httpx.Client, tenant: SfTenant) -> list[dict]:
    rows: dict[str, dict] = {}
    total: int | None = None
    for page in range(_PAGE_CAP):
        response = client.get(
            urljoin(tenant.base, tenant.search_path),
            params={
                "createNewAlert": "false",
                "q": "",
                "locationsearch": "Hong Kong",
                "startrow": page * _PAGE_SIZE,
            },
        )
        response.raise_for_status()
        total = parse_total(response.text) if total is None else total
        fresh = [r for r in parse_listing(response.text) if r["id"] not in rows]
        if not fresh:
            break
        for row in fresh:
            rows[row["id"]] = row
        if total is not None and len(rows) >= total:
            break
        time.sleep(_SLEEP)
    if total is not None and len(rows) != total:
        raise ValueError(f"{tenant.base} listing is incomplete: collected {len(rows)} of {total}")
    return list(rows.values())


def fetch_sf_rmk(
    client: httpx.Client, company: str, company_slug: str, *, tenant: SfTenant
) -> list[Job]:
    jobs: list[Job] = []
    for row in _list_hong_kong(client, tenant):
        time.sleep(_SLEEP)
        response = client.get(urljoin(tenant.base, row["href"]))
        response.raise_for_status()
        detail = parse_detail(response.text)
        listed_hk = is_hong_kong_text(row["location"])
        if not listed_hk and "Hong Kong" not in detail["locations"]:
            continue  # the server filter matched, but no office of this posting is Hong Kong
        jobs.append(map_job(row, detail, tenant, company, company_slug))
    return jobs


fetch_ey = functools.partial(fetch_sf_rmk, tenant=EY)
fetch_zurich_hk = functools.partial(fetch_sf_rmk, tenant=ZURICH)
fetch_swiss_re = functools.partial(fetch_sf_rmk, tenant=SWISS_RE)

SITE_FETCHERS = {
    "ey": fetch_ey,
    "zurich-hk": fetch_zurich_hk,
    "swiss-re": fetch_swiss_re,
}
