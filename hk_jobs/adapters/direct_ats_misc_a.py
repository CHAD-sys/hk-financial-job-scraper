"""Deterministic readers for three employers' own career endpoints.

- AXA Hong Kong: iCIMS "Jibe" public JSON at careers.axa.com/api/jobs (robots crawl-delay 5s).
  The listing already carries the (plain text) description and the real posting date.
- Morgan Stanley: Eightfold PCSX search API (10 rows per page) plus one detail call per job
  for the HTML description. Own implementation; nothing shared with the eightfold adapter.
- WeLab Bank: BambooHR public careers JSON (``/careers/list`` + ``/careers/{id}/detail``).

Everything read from these sites is data. Each fetcher raises ValueError when a listing is
internally inconsistent (reported total differs from rows collected).
"""

import html
import logging
import re
import time
from datetime import UTC, datetime
from functools import partial

import httpx

from hk_jobs.adapters.workday import _strip_html
from hk_jobs.schema import Job

logger = logging.getLogger(__name__)

_PAGE_CAP = 30
_SLEEP = 0.5

# ── AXA (iCIMS Jibe) ─────────────────────────────────────────────────────────

AXA_API = "https://careers.axa.com/api/jobs"
AXA_PAGE_SIZE = 40
AXA_CRAWL_DELAY = 5.0  # robots.txt crawl-delay
AXA_TIMEOUT = httpx.Timeout(90.0)


def _parse_axa_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z")
    except ValueError:
        return None
    return parsed.astimezone(UTC)


def map_axa_row(row: dict, company: str, company_slug: str) -> Job:
    """One ``jobs[i]["data"]`` row. Recruiter names (tags6/tags7) are deliberately ignored."""
    req_id = str(row["req_id"])
    raw = row.get("description") or ""
    if "&lt;" in raw or "&amp;" in raw:
        raw = html.unescape(raw)
    categories = row.get("categories") or []
    url = ((row.get("meta_data") or {}).get("canonical_url")) or f"https://careers.axa.com/jobs/{req_id}"
    return Job(
        source="direct_site",
        source_id=f"{company_slug}:{req_id}",
        company=company,
        company_slug=company_slug,
        url=url,
        title=(row.get("title") or "").strip(),
        description_raw=raw,
        description_clean=_strip_html(raw),
        locations=["Hong Kong"],
        department=(categories[0].get("name") if categories else None) or None,
        posted_at=_parse_axa_date(row.get("posted_date")),
        scraped_under_slug=company_slug,
    )


def fetch_axa(
    client: httpx.Client, company: str, company_slug: str, *, delay: float = AXA_CRAWL_DELAY
) -> list[Job]:
    rows: dict[str, dict] = {}
    total = None
    for page in range(1, _PAGE_CAP + 1):
        response = client.get(
            AXA_API,
            params={"location": "Hong Kong", "limit": AXA_PAGE_SIZE, "page": page},
            headers={"Accept": "application/json"},
            timeout=AXA_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        total = data.get("totalCount", total)
        page_rows = [j.get("data") or {} for j in data.get("jobs") or []]
        fresh = [r for r in page_rows if r.get("req_id") and str(r["req_id"]) not in rows]
        if not page_rows or not fresh:
            break
        for r in fresh:
            rows[str(r["req_id"])] = r
        if total is not None and len(rows) >= total:
            break
        time.sleep(delay)
    if total is not None and len(rows) != total:
        raise ValueError(f"AXA listing is incomplete: collected {len(rows)} of {total}")
    return [
        map_axa_row(r, company, company_slug)
        for r in rows.values()
        if (r.get("country_code") or "").upper() == "HK"
    ]


# ── Morgan Stanley (Eightfold PCSX) ──────────────────────────────────────────

MS_HOST = "https://morganstanley.eightfold.ai"
MS_DOMAIN = "morganstanley.com"
MS_SEARCH = f"{MS_HOST}/api/pcsx/search"
MS_DETAIL = f"{MS_HOST}/api/pcsx/position_details"
MS_PAGE_SIZE = 10  # the API caps num at 10


def _ms_is_hk(position: dict) -> bool:
    return "HK" in [str(c).upper() for c in position.get("standardizedLocations") or []]


def _ms_locations(position: dict) -> list[str]:
    out: list[str] = []
    for label in position.get("locations") or []:
        name = "Hong Kong" if str(label).strip().lower().startswith("hong kong") else str(label).strip()
        if name and name not in out:
            out.append(name)
    return out or ["Hong Kong"]


def map_ms_position(position: dict, detail: dict, company: str, company_slug: str) -> Job:
    ident = str(position.get("displayJobId") or position.get("atsJobId") or position["id"])
    raw = detail.get("jobDescription") or ""
    posted = position.get("postedTs") or detail.get("postedTs")
    path = detail.get("publicUrl") or f"{MS_HOST}/careers/job/{position['id']}"
    return Job(
        source="direct_site",
        source_id=f"{company_slug}:{ident}",
        company=company,
        company_slug=company_slug,
        url=path if path.startswith("http") else MS_HOST + path,
        title=(position.get("name") or "").strip(),
        description_raw=raw,
        description_clean=_strip_html(raw),
        locations=_ms_locations(position),
        department=position.get("department") or None,
        posted_at=datetime.fromtimestamp(int(posted), UTC) if posted else None,
        scraped_under_slug=company_slug,
    )


def _ms_list(client: httpx.Client) -> list[dict]:
    positions: dict[int, dict] = {}
    total = None
    start = 0
    for _ in range(_PAGE_CAP * 2):
        response = client.get(
            MS_SEARCH,
            params={
                "domain": MS_DOMAIN,
                "query": "",
                "location": "Hong Kong",
                "start": start,
                "num": MS_PAGE_SIZE,
            },
        )
        response.raise_for_status()
        data = (response.json() or {}).get("data") or {}
        total = data.get("count", total)
        page = data.get("positions") or []
        fresh = [p for p in page if p.get("id") not in positions]
        if not fresh:
            break
        for p in fresh:
            positions[p["id"]] = p
        start += len(page)
        if total is not None and start >= total:
            break
        time.sleep(_SLEEP)
    if total is not None and len(positions) != total:
        raise ValueError(f"Morgan Stanley listing is incomplete: collected {len(positions)} of {total}")
    return list(positions.values())


def fetch_morgan_stanley(client: httpx.Client, company: str, company_slug: str) -> list[Job]:
    jobs = []
    for position in (p for p in _ms_list(client) if _ms_is_hk(p)):
        time.sleep(_SLEEP)
        response = client.get(
            MS_DETAIL,
            params={"position_id": position["id"], "domain": MS_DOMAIN, "hl": "en"},
        )
        response.raise_for_status()
        detail = (response.json() or {}).get("data") or {}
        jobs.append(map_ms_position(position, detail, company, company_slug))
    return jobs


# ── WeLab Bank (BambooHR) ────────────────────────────────────────────────────

BAMBOO_BASE = "https://welab.bamboohr.com"
_WELAB_PREFIX = re.compile(r"^\s*WeLab Bank\s*[-‐-―]\s*", re.I)


def _bamboo_is_hk(location: dict) -> bool:
    values = [str(location.get(k) or "").strip().lower() for k in ("state", "addressCountry")]
    return any(v in {"hong kong", "hk"} for v in values)


def clean_welab_title(title: str) -> str:
    return _WELAB_PREFIX.sub("", title or "").strip()


def _parse_bamboo_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        return None


def map_bamboo_job(row: dict, detail: dict, company: str, company_slug: str) -> Job:
    raw = detail.get("description") or ""
    return Job(
        source="direct_site",
        source_id=f"{company_slug}:{row['id']}",
        company=company,
        company_slug=company_slug,
        url=f"{BAMBOO_BASE}/careers/{row['id']}",
        title=clean_welab_title(row.get("jobOpeningName") or detail.get("jobOpeningName") or ""),
        description_raw=raw,
        description_clean=_strip_html(raw),
        locations=["Hong Kong"],
        department=row.get("departmentLabel") or None,
        posted_at=_parse_bamboo_date(detail.get("datePosted")),
        scraped_under_slug=company_slug,
    )


def fetch_welab(client: httpx.Client, company: str, company_slug: str) -> list[Job]:
    response = client.get(f"{BAMBOO_BASE}/careers/list", headers={"Accept": "application/json"})
    response.raise_for_status()
    data = response.json()
    rows = data.get("result") or []
    total = (data.get("meta") or {}).get("totalCount")
    if total is not None and total != len(rows):
        raise ValueError(f"WeLab listing is incomplete: collected {len(rows)} of {total}")
    unique: dict[str, dict] = {}
    for row in rows:
        unique.setdefault(str(row["id"]), row)
    jobs = []
    for row in (r for r in unique.values() if _bamboo_is_hk(r.get("location") or {})):
        time.sleep(_SLEEP)
        detail_resp = client.get(
            f"{BAMBOO_BASE}/careers/{row['id']}/detail", headers={"Accept": "application/json"}
        )
        detail_resp.raise_for_status()
        opening = ((detail_resp.json() or {}).get("result") or {}).get("jobOpening") or {}
        country = ((opening.get("location") or {}).get("addressCountry") or "").strip().lower()
        if country and country not in {"hong kong", "hk"}:
            continue  # detail country disagrees with the list label
        jobs.append(map_bamboo_job(row, opening, company, company_slug))
    return jobs


SITE_FETCHERS = {
    "axa-hk": partial(fetch_axa),
    "morgan-stanley": partial(fetch_morgan_stanley),
    "welab-bank": partial(fetch_welab),
}
