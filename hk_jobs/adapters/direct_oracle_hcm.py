"""Oracle HCM Cloud "Candidate Experience" reader (JPMorgan, Chubb, Schroders HK).

All three employers publish jobs through the same public, unauthenticated REST API
that their careers SPA calls: ``recruitingCEJobRequisitions`` (list, paged with
``limit``/``offset`` inside the ``finder`` string, total in ``TotalJobsCount``) and
``recruitingCEJobRequisitionDetails`` (one request per job: HTML description and the
exact posting timestamp).  One shared fetcher takes the tenant's host, site number and
Hong Kong location id; thin ``functools.partial`` wrappers hold those per company.

Hong Kong is filtered server-side by the geography id and again client-side on
``PrimaryLocationCountry == "HK"`` or an HK secondary location (JPMorgan has
Singapore-primary roles also open in HK).  Never use ``keyword=Hong Kong``: it is fuzzy.
"""

import functools
import html
import logging
import re
import time
from datetime import datetime, timezone

import httpx

from hk_jobs.adapters.workday import _strip_html
from hk_jobs.schema import Job

logger = logging.getLogger(__name__)

PAGE_SIZE = 25
MAX_PAGES = 40
REQUEST_DELAY = 0.3  # seconds between requests (jpmorgan's WAF dislikes bursts)
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json",
}


def _pause() -> None:
    time.sleep(REQUEST_DELAY)


def _api(host: str) -> str:
    return f"https://{host}/hcmRestApi/resources/latest"


def job_url(host: str, site: str, req_id: str) -> str:
    return f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{req_id}"


def _list_page(
    client: httpx.Client, host: str, site: str, facet: str, geo_id: str, offset: int
) -> dict:
    finder = (
        f"findReqs;siteNumber={site},facetsList=LOCATIONS,limit={PAGE_SIZE},"
        f"offset={offset},{facet}={geo_id},sortBy=POSTING_DATES_DESC"
    )
    response = client.get(
        f"{_api(host)}/recruitingCEJobRequisitions",
        params={
            "onlyData": "true",
            "expand": "requisitionList.secondaryLocations",
            "finder": finder,
        },
        headers=_HEADERS,
    )
    response.raise_for_status()
    items = response.json().get("items")
    if not items or not isinstance(items[0], dict):
        raise ValueError(f"Oracle HCM {host} {site}: response has no items; site moved?")
    return items[0]


def list_requisitions(
    client: httpx.Client, host: str, site: str, facet: str, geo_id: str
) -> list[dict]:
    """All Hong Kong list rows, de-duplicated by Id, in listing order."""
    rows: list[dict] = []
    seen: set[str] = set()
    total = None
    for page in range(MAX_PAGES):
        if page:
            _pause()
        offset = page * PAGE_SIZE
        item = _list_page(client, host, site, facet, geo_id, offset)
        count = item.get("TotalJobsCount")
        if not isinstance(count, int):
            raise ValueError(f"Oracle HCM {host} {site}: no TotalJobsCount; site moved?")
        total = count if total is None else total
        page_rows = item.get("requisitionList") or []
        if count and offset == 0 and not page_rows:
            raise ValueError(
                f"Oracle HCM {host} {site}: TotalJobsCount={count} but the page is empty"
            )
        new = 0
        for row in page_rows:
            req_id = str(row.get("Id") or "")
            if req_id and req_id not in seen:
                seen.add(req_id)
                rows.append(row)
                new += 1
        if not page_rows or not new or offset + PAGE_SIZE >= total:
            break
    else:
        raise ValueError(f"Oracle HCM {host} {site}: more than {MAX_PAGES} pages")
    if total is not None and len(rows) > total:
        raise ValueError(f"Oracle HCM {host} {site}: {len(rows)} rows exceed total {total}")
    return rows


def fetch_detail(client: httpx.Client, host: str, site: str, req_id: str) -> dict | None:
    response = client.get(
        f"{_api(host)}/recruitingCEJobRequisitionDetails",
        params={
            "expand": "all",
            "onlyData": "true",
            "finder": f'ById;Id="{req_id}",siteNumber={site}',
        },
        headers=_HEADERS,
    )
    response.raise_for_status()
    items = response.json().get("items") or []
    return items[0] if items and isinstance(items[0], dict) else None


def _unescape_once(raw: str) -> str:
    """Oracle sends real HTML; unescape only if it is entity-escaped markup."""
    if "<" not in raw and "&lt;" in raw:
        return html.unescape(raw)
    return raw


def _description(detail: dict | None, row: dict) -> str:
    parts = []
    for source in (detail or {}, row):
        parts = [
            source.get(key)
            for key in ("ExternalDescriptionStr", "ExternalResponsibilitiesStr",
                        "ExternalQualificationsStr")
            if source.get(key)
        ]
        if parts:
            break
    if not parts and row.get("ShortDescriptionStr"):
        parts = [row["ShortDescriptionStr"]]
    return _unescape_once("\n".join(parts)).strip()


def _posted_at(detail: dict | None, row: dict) -> datetime | None:
    for value in ((detail or {}).get("ExternalPostedStartDate"), row.get("PostedDate")):
        if not value:
            continue
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            continue
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def is_hong_kong(row: dict) -> bool:
    """Primary office in HK, or HK listed as a secondary location (country code)."""
    if (row.get("PrimaryLocationCountry") or "").upper() == "HK":
        return True
    return any(
        isinstance(x, dict) and (x.get("CountryCode") or "").upper() == "HK"
        for x in row.get("secondaryLocations") or []
    )


def _locations(row: dict) -> list[str]:
    names: list[str] = []
    candidates = [row.get("PrimaryLocation")]
    for extra in row.get("secondaryLocations") or []:
        candidates.append(extra.get("Name") if isinstance(extra, dict) else extra)
    for name in candidates:
        if isinstance(name, str) and name.strip() and name.strip() not in names:
            names.append(name.strip())
    return names or ["Hong Kong"]


def build_job(
    row: dict, detail: dict | None, host: str, site: str, company: str, company_slug: str
) -> Job | None:
    req_id = str(row.get("Id") or "")
    title = re.sub(r"\s+", " ", (row.get("Title") or (detail or {}).get("Title") or "")).strip()
    if not req_id or not title:
        return None
    raw = _description(detail, row)
    department = (detail or {}).get("Category") or row.get("JobFamily") or None
    return Job(
        source="direct_site",
        source_id=f"{company_slug}:{req_id}",
        company=company,
        company_slug=company_slug,
        url=job_url(host, site, req_id),
        title=title,
        description_raw=raw,
        description_clean=_strip_html(raw),
        locations=_locations(row),
        department=department,
        posted_at=_posted_at(detail, row),
        scraped_under_slug=company_slug,
    )


def fetch_oracle_hcm(
    client: httpx.Client,
    company: str,
    company_slug: str,
    *,
    host: str,
    site: str,
    facet: str,
    geo_id: str,
) -> list[Job]:
    rows = [
        r
        for r in list_requisitions(client, host, site, facet, geo_id)
        if is_hong_kong(r)
    ]
    jobs: list[Job] = []
    for row in rows:
        _pause()
        try:
            detail = fetch_detail(client, host, site, str(row["Id"]))
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("%s detail %s failed (%s); using list text", company_slug, row["Id"], exc)
            detail = None
        job = build_job(row, detail, host, site, company, company_slug)
        if job:
            jobs.append(job)
    return jobs


fetch_jpmorgan = functools.partial(
    fetch_oracle_hcm,
    host="jpmc.fa.oraclecloud.com",
    site="CX_1001",
    facet="selectedLocationsFacet",
    geo_id="300000000289330",
)
fetch_chubb = functools.partial(
    fetch_oracle_hcm,
    host="fa-ewgu-saasfaprod1.fa.ocs.oraclecloud.com",
    site="CX_2001",
    facet="locationId",
    geo_id="300000000467173",
)
fetch_schroders = functools.partial(
    fetch_oracle_hcm,
    host="ekbq.fa.em2.oraclecloud.com",
    site="CX_2",
    facet="selectedLocationsFacet",
    geo_id="300000000304314",
)

SITE_FETCHERS = {
    "jpmorgan": fetch_jpmorgan,
    "chubb": fetch_chubb,
    "schroders-hk": fetch_schroders,
}
