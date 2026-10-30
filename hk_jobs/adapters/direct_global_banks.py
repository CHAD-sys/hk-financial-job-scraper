"""Deterministic readers for three global banks' own careers sites (Hong Kong only).

* Goldman Sachs: unauthenticated GraphQL gateway behind higher.gs.com. The list
  query filters on location server-side; the description needs one detail query
  per role. The site gives no usable posting date, so ``posted_at`` stays None.
* Bank of America: Adobe AEM ``jobssearchservlet`` JSON (``search=jobsByCountry``
  is required: any other ``search`` value silently ignores the country and
  returns every job worldwide, which the fetcher detects and refuses). The
  description and date come from the JobPosting JSON-LD of each detail page.
* Barclays: Radancy TalentBrew HTML, filtered by the Hong Kong country facet in
  the URL path. Only ``#search-results-list`` is read: the page also carries an
  unrelated "recommended jobs" block. Description and date come from each job
  page's JobPosting JSON-LD.

An empty result is a legitimate state; an internally inconsistent listing raises.
"""

import html
import json
import logging
import re
import time
from datetime import UTC, datetime

import httpx
from selectolax.parser import HTMLParser

from hk_jobs.adapters.workday import _strip_html
from hk_jobs.schema import Job

logger = logging.getLogger(__name__)

_SLEEP = 0.5  # seconds between requests (brief asks for >= 0.3)
_PAGE_CAP = 20
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_LD_JSON = re.compile(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', re.S)
_ZERO_WIDTH = re.compile("[​‌‍⁠﻿]")


def _unescape_once(raw: str) -> str:
    """html.unescape once, only when the body is entity-escaped markup."""
    if raw and "<" not in raw and "&lt;" in raw:
        return html.unescape(raw)
    return raw


def _job_posting_ld(page_html: str) -> dict:
    """The JobPosting JSON-LD object of a page, or {} if absent/unparseable."""
    for match in _LD_JSON.finditer(page_html):
        try:
            data = json.loads(match.group(1), strict=False)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("@type") == "JobPosting":
            return data
    return {}


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(v for v in values if v))


# ── Goldman Sachs ─────────────────────────────────────────────────────────────

GS_API = "https://api-higher.gs.com/gateway/api/v1/graphql"
GS_ROLE_URL = "https://higher.gs.com/roles/{}"
_GS_LIST_QUERY = (
    "query GetRoles($searchQueryInput: RoleSearchQueryInput!) { roleSearch(searchQueryInput: "
    "$searchQueryInput) { totalCount items { roleId corporateTitle jobTitle jobFunction "
    "locations { primary state country city } status division skills externalSource "
    "{ sourceId } } } }"
)
_GS_DETAIL_QUERY = (
    "query GetRoleById($externalSourceId: String!) { role(externalSourceId: $externalSourceId) "
    "{ roleId descriptionHtml applyActive externalSource { externalApplicationUrl sourceId } } }"
)
_GS_PAGE_SIZE = 20


def _gs_post(client: httpx.Client, operation: str, variables: dict, query: str) -> dict:
    response = client.post(
        GS_API,
        json={"operationName": operation, "variables": variables, "query": query},
        headers={"user-agent": _UA},
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("errors") or not isinstance(payload.get("data"), dict):
        raise ValueError(f"Goldman Sachs GraphQL {operation} failed: {str(payload.get('errors'))[:200]}")
    return payload["data"]


def gs_is_hong_kong(item: dict) -> bool:
    return any(
        (loc.get("country") or "").strip().lower() == "hong kong" for loc in item.get("locations") or []
    )


def gs_locations(item: dict) -> list[str]:
    locs = sorted(item.get("locations") or [], key=lambda loc: not loc.get("primary"))
    names = []
    for loc in locs:
        if (loc.get("country") or "").strip().lower() == "hong kong":
            names.append("Hong Kong")
        else:
            names.append(loc.get("city") or loc.get("state") or loc.get("country") or "")
    return _dedupe(names)


def gs_map_item(item: dict, detail: dict | None, company: str, company_slug: str) -> Job:
    source_id = (item.get("externalSource") or {}).get("sourceId") or ""
    raw = _unescape_once((detail or {}).get("descriptionHtml") or "")
    return Job(
        source="direct_site",
        source_id=f"{company_slug}:{item['roleId']}",
        company=company,
        company_slug=company_slug,
        url=GS_ROLE_URL.format(source_id or item["roleId"]),
        title=(item.get("jobTitle") or "").strip(),
        description_raw=raw,
        description_clean=_strip_html(raw),
        locations=gs_locations(item) or ["Hong Kong"],
        department=item.get("division") or None,
        scraped_under_slug=company_slug,
        board_signals={"corporate_title": item.get("corporateTitle"), "function": item.get("jobFunction")},
    )


def _gs_list(client: httpx.Client) -> list[dict]:
    items: dict[str, dict] = {}
    total = None
    for page in range(_PAGE_CAP):
        variables = {
            "searchQueryInput": {
                "page": {"pageSize": _GS_PAGE_SIZE, "pageNumber": page},
                "sort": {"sortStrategy": "RELEVANCE", "sortOrder": "DESC"},
                "filters": [
                    {"filterCategoryType": "LOCATION", "filters": [{"filter": "Hong Kong", "subFilters": []}]}
                ],
                "experiences": ["EARLY_CAREER", "PROFESSIONAL"],
                "searchTerm": "",
            }
        }
        result = _gs_post(client, "GetRoles", variables, _GS_LIST_QUERY)["roleSearch"]
        total = result.get("totalCount", total)
        fresh = [i for i in result.get("items") or [] if i.get("roleId") not in items]
        if not fresh:
            break
        for item in fresh:
            items[item["roleId"]] = item
        if total is not None and len(items) >= total:
            break
        time.sleep(_SLEEP)
    if total is not None and len(items) != total:
        raise ValueError(f"Goldman Sachs listing is inconsistent: collected {len(items)} of {total}")
    return list(items.values())


def fetch_goldman_sachs(client: httpx.Client, company: str, company_slug: str) -> list[Job]:
    jobs = []
    for item in (i for i in _gs_list(client) if gs_is_hong_kong(i)):
        source_id = (item.get("externalSource") or {}).get("sourceId")
        detail = None
        if source_id:
            time.sleep(_SLEEP)
            detail = _gs_post(client, "GetRoleById", {"externalSourceId": source_id}, _GS_DETAIL_QUERY).get(
                "role"
            )
        if not detail:
            logger.warning("Goldman Sachs role %s has no detail record", item["roleId"])
        jobs.append(gs_map_item(item, detail, company, company_slug))
    return jobs


# ── Bank of America ───────────────────────────────────────────────────────────

BOA_SITE = "https://careers.bankofamerica.com"
BOA_API = f"{BOA_SITE}/services/jobssearchservlet"
_BOA_ROWS = 50


def boa_is_hong_kong(row: dict) -> bool:
    return (row.get("country") or "").strip().lower() == "hong kong"


def boa_locations(row: dict) -> list[str]:
    """Hong Kong first, then the cities of any additional offices ("SG - Singapore - ...")."""
    names = ["Hong Kong"]
    for entry in (row.get("additionalLocations") or "").split(","):
        parts = [p.strip() for p in entry.split(" - ")]
        if len(parts) >= 2 and parts[1] and "hong kong" not in parts[1].lower():
            names.append(parts[1].title() if parts[1].isupper() else parts[1])
    return _dedupe(names)


def parse_us_date(value: str | None) -> datetime | None:
    try:
        return datetime.strptime((value or "").strip(), "%m/%d/%Y").replace(tzinfo=UTC)
    except ValueError:
        return None


def boa_map_row(row: dict, page_html: str, company: str, company_slug: str) -> Job:
    ld = _job_posting_ld(page_html)
    raw = _unescape_once(ld.get("description") or "")
    return Job(
        source="direct_site",
        source_id=f"{company_slug}:{row['jobRequisitionId']}",
        company=company,
        company_slug=company_slug,
        url=BOA_SITE + row["jcrURL"],
        title=_ZERO_WIDTH.sub("", row.get("postingTitle") or "").strip(),
        description_raw=raw,
        description_clean=_strip_html(raw),
        locations=boa_locations(row),
        department=row.get("lob") or None,
        posted_at=parse_us_date(row.get("postedDate")) or parse_us_date(ld.get("datePosted")),
        scraped_under_slug=company_slug,
    )


def _boa_list(client: httpx.Client) -> list[dict]:
    rows: dict[str, dict] = {}
    start = 0
    for _ in range(_PAGE_CAP):
        response = client.get(
            BOA_API,
            params={"start": start, "rows": _BOA_ROWS, "search": "jobsByCountry", "country": "Hong Kong"},
            headers={"User-Agent": _UA},
        )
        response.raise_for_status()
        data = response.json()
        page = data.get("jobsList") or []
        total = int(data.get("totalMatches") or 0)
        if page and not any(boa_is_hong_kong(r) for r in page):
            raise ValueError("Bank of America ignored the country filter (no Hong Kong rows returned)")
        fresh = [r for r in page if r.get("jobRequisitionId") not in rows]
        if not fresh:
            break
        for row in fresh:
            rows[row["jobRequisitionId"]] = row
        start += _BOA_ROWS
        if start >= total:
            break
        time.sleep(_SLEEP)
    return list(rows.values())


def fetch_bank_of_america(client: httpx.Client, company: str, company_slug: str) -> list[Job]:
    jobs = []
    for row in (r for r in _boa_list(client) if boa_is_hong_kong(r)):
        time.sleep(_SLEEP)
        page = client.get(BOA_SITE + row["jcrURL"], headers={"User-Agent": _UA})
        page.raise_for_status()
        jobs.append(boa_map_row(row, page.text, company, company_slug))
    return jobs


# ── Barclays ──────────────────────────────────────────────────────────────────

BARCLAYS_SITE = "https://search.jobs.barclays"
BARCLAYS_LIST = f"{BARCLAYS_SITE}/search-jobs/hong%20kong%20china/13015/2/1819730/22/114/2/2"
_BARCLAYS_PAGE_CAP = 10


def barclays_locations(text: str) -> list[str]:
    """'Hong Kong, Hong Kong China; London, United Kingdom' -> ['Hong Kong', 'London, United Kingdom']."""
    names = []
    for part in (text or "").split(";"):
        part = " ".join(part.split())
        names.append("Hong Kong" if part.lower().startswith("hong kong") else part)
    return _dedupe(names)


def parse_barclays_listing(page_html: str) -> tuple[list[dict], int, int]:
    """(cards, total_job_results, total_pages); cards come only from #search-results-list."""
    tree = HTMLParser(page_html)
    cards = []
    for link in tree.css("#search-results-list a.job-title--link"):
        loc_node = link.parent.css_first(".job-location") if link.parent else None
        cards.append(
            {
                "id": link.attributes.get("data-job-id") or "",
                "url": BARCLAYS_SITE + (link.attributes.get("href") or ""),
                "title": html.unescape(link.text(strip=True)),
                "location": loc_node.text(strip=True) if loc_node else "",
            }
        )
    total = re.search(r'data-total-job-results="(\d+)"', page_html)
    pages = re.search(r'data-total-pages="(\d+)"', page_html)
    if not total or not pages:
        raise ValueError("Barclays listing page has no result counters (layout changed?)")
    return cards, int(total.group(1)), int(pages.group(1))


def barclays_is_hong_kong(card: dict) -> bool:
    return "hong kong" in (card.get("location") or "").lower()


def parse_iso_date(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(value).replace(tzinfo=UTC) if value else None
    except ValueError:
        return None


def barclays_map_card(card: dict, page_html: str, company: str, company_slug: str) -> Job:
    ld = _job_posting_ld(page_html)
    raw = _unescape_once(ld.get("description") or "")
    return Job(
        source="direct_site",
        source_id=f"{company_slug}:{card['id']}",
        company=company,
        company_slug=company_slug,
        url=card["url"],
        title=card["title"].strip(),
        description_raw=raw,
        description_clean=_strip_html(raw),
        locations=barclays_locations(card["location"]) or ["Hong Kong"],
        department=(ld.get("industry") or "").strip() or None,
        posted_at=parse_iso_date(ld.get("datePosted")),
        scraped_under_slug=company_slug,
    )


def _barclays_list(client: httpx.Client) -> list[dict]:
    cards: dict[str, dict] = {}
    total = None
    for page in range(1, _BARCLAYS_PAGE_CAP + 1):
        response = client.get(BARCLAYS_LIST, params={"p": page} if page > 1 else None, headers={"User-Agent": _UA})
        response.raise_for_status()
        found, total, pages = parse_barclays_listing(response.text)
        fresh = [c for c in found if c["id"] and c["id"] not in cards]
        if not fresh:
            break
        for card in fresh:
            cards[card["id"]] = card
        if page >= pages:
            break
        time.sleep(_SLEEP)
    if total is not None and len(cards) != total:
        raise ValueError(f"Barclays listing is inconsistent: collected {len(cards)} of {total}")
    return list(cards.values())


def fetch_barclays(client: httpx.Client, company: str, company_slug: str) -> list[Job]:
    jobs = []
    for card in (c for c in _barclays_list(client) if barclays_is_hong_kong(c)):
        time.sleep(_SLEEP)
        page = client.get(card["url"], headers={"User-Agent": _UA})
        page.raise_for_status()
        jobs.append(barclays_map_card(card, page.text, company, company_slug))
    return jobs


SITE_FETCHERS = {
    "goldman-sachs": fetch_goldman_sachs,
    "bank-of-america": fetch_bank_of_america,
    "barclays": fetch_barclays,
}
