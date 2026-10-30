"""Direct fetchers for three mainland-owned banks' own careers back ends.

* CMB Wing Lung Bank (and its parent China Merchants Bank, the same feed): a JSON
  list endpoint of the bank's in-house "Job Centre". The server issues a CSRF
  token in an ``X-Csrf-Token`` response header (plus a cookie) and the SPA echoes
  it back as ``X-CSRF-TOKEN`` on every POST; we do the same. No login is used.
* Ping An: the group's public recruitment portal JSON API, Hong Kong filtered
  server-side by address code and again client-side.
* CCB (Asia): the bank's own server-rendered listing page plus one detail page
  per job (full text and a real "Job Posted" date). Stateless, no cookies needed.

All three are public pages that the sites' own front ends read anonymously.
"""

import logging
import re
import time
from datetime import datetime, timedelta, timezone

import httpx
from selectolax.parser import HTMLParser

from hk_jobs.adapters.workday import _strip_html
from hk_jobs.schema import Job

logger = logging.getLogger(__name__)

_SLEEP = 0.5
_PAGE_CAP = 10
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_HKT = timezone(timedelta(hours=8))  # Hong Kong and mainland China share UTC+8


def _hk_time(value: str | None, fmt: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), fmt).replace(tzinfo=_HKT)
    except ValueError:
        return None


# ── CMB Wing Lung Bank / China Merchants Bank ────────────────────────────────

CMB_API = "https://recruit.cmbwinglungbank.com/api/position/getPublishJobByParams"
CMB_PAGE_SIZE = 100
_CMB_EMPLOYMENT = {"permanent": "full-time", "contract": "contract"}
_CMB_RETRY_STATUS = {302, 401, 403, 406}


def _cmb_post(client: httpx.Client, state: dict, page: int) -> dict:
    """POST one page, echoing the CSRF token; retry once if the guard bounces us."""
    body = {"departName": None, "position": "", "type": "", "pageSize": CMB_PAGE_SIZE, "pageIndex": page}
    for attempt in range(2):
        headers = {"Content-Type": "application/json", "User-Agent": _UA}
        if state.get("token"):
            headers["X-CSRF-TOKEN"] = state["token"]
        response = client.post(CMB_API, json=body, headers=headers)
        token = response.headers.get("x-csrf-token")
        if token:
            state["token"] = token
        if response.status_code in _CMB_RETRY_STATUS and attempt == 0:
            time.sleep(_SLEEP * 3)
            continue
        response.raise_for_status()
        try:
            return response.json()
        except ValueError:
            if attempt == 0:
                time.sleep(_SLEEP * 3)
                continue
            raise ValueError("CMB job list did not return JSON") from None
    raise ValueError("CMB job list unavailable")  # pragma: no cover


def parse_cmb_row(row: dict, company: str, company_slug: str) -> Job | None:
    publish_id = str(row.get("publishId") or "").strip()
    title = (row.get("positionDisplay") or "").strip()
    if not publish_id or not title:
        return None
    raw = "".join(row.get(k) or "" for k in ("responsibility", "jobRequirement"))
    return Job(
        source="direct_site",
        source_id=f"{company_slug}:{publish_id}",
        company=company,
        company_slug=company_slug,
        url=f"https://recruit.cmbwinglungbank.com/#/jobDetail?publishId={publish_id}",
        title=title,
        description_raw=raw,
        description_clean=_strip_html(raw),
        scraped_under_slug=company_slug,
        locations=["Hong Kong"],  # the feed has no location field; it is the HK bank's board
        department=(row.get("deptName") or "").strip() or None,
        employment_type=_CMB_EMPLOYMENT.get(str(row.get("employmentType") or "").strip().lower()),
        posted_at=_hk_time(row.get("publishTime"), "%Y-%m-%d %H:%M:%S"),
    )


def fetch_cmb(client: httpx.Client, company: str, company_slug: str) -> list[Job]:
    state: dict = {}
    jobs: dict[str, Job] = {}
    total = None
    for page in range(1, _PAGE_CAP + 1):
        if page > 1:
            time.sleep(_SLEEP)
        payload = _cmb_post(client, state, page)
        result = payload.get("Result") if isinstance(payload, dict) else None
        if not isinstance(result, dict) or not isinstance(result.get("list"), list) or "total" not in result:
            raise ValueError("CMB job list has an unexpected shape")
        rows = result["list"]
        total = int(result["total"])
        if not rows:
            if total and page == 1:
                raise ValueError(f"CMB reports {total} jobs but returned an empty first page")
            break
        added = 0
        for row in rows:
            job = parse_cmb_row(row, company, company_slug)
            if job and job.source_id not in jobs:
                jobs[job.source_id] = job
                added += 1
        if not added or len(jobs) >= total:
            break
    return list(jobs.values())


# ── Ping An ──────────────────────────────────────────────────────────────────

PINGAN_BASE = "https://talent.pingan.com/zztj-recruit-talent-webserver/rctt"
PINGAN_TENANT = "CHDUIE8QRPG16AJFM2B9NL0OS3TK574"  # constant in the portal's public JS bundle
PINGAN_HK_CODE = "0/4/595/538135297"
PINGAN_HK_NAME = "香港"
PINGAN_PAGE_SIZE = 50


def parse_pingan_row(row: dict, company: str, company_slug: str) -> Job | None:
    if row.get("addressCode") != PINGAN_HK_CODE and row.get("addressName") != PINGAN_HK_NAME:
        return None
    position_id = str(row.get("positionId") or "").strip()
    title = (row.get("positionShowName") or "").strip()
    if not position_id or not title:
        return None
    raw = "\n".join(p for p in ((row.get("duty") or "").strip(), (row.get("qualification") or "").strip()) if p)
    unit = (row.get("businessUnitName") or "").strip()
    team = (row.get("structureShowName") or "").strip()
    return Job(
        source="direct_site",
        source_id=f"{company_slug}:{position_id}",
        company=company,
        company_slug=company_slug,
        url=f"https://talent.pingan.com/recruit/position.html?positionId={position_id}",
        title=title,
        description_raw=raw,
        description_clean=_strip_html(raw),
        locations=["Hong Kong"],
        scraped_under_slug=company_slug,
        department=" / ".join(p for p in (unit, team) if p) or None,
        # `updatedDate` is a last-edited stamp, not a posting date, so posted_at stays None.
    )


def fetch_pingan(client: httpx.Client, company: str, company_slug: str) -> list[Job]:
    jobs: dict[str, Job] = {}
    for page in range(1, _PAGE_CAP + 1):
        if page > 1:
            time.sleep(_SLEEP)
        response = client.post(
            f"{PINGAN_BASE}/candidate/position/getPositionList",
            headers={"User-Agent": _UA},
            json={
                "keyword": "",
                "businessUnitId": "",
                "addressCode": PINGAN_HK_CODE,
                "postCategory": "",
                "wecruitPlatform": False,
                "tenantId": PINGAN_TENANT,
                "pageNum": page,
                "pageSize": PINGAN_PAGE_SIZE,
                "countTotal": True,
            },
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict) or not isinstance(data.get("list"), list):
            raise ValueError("Ping An position list has an unexpected shape")
        rows = data["list"]
        added = 0
        for row in rows:
            job = parse_pingan_row(row, company, company_slug)
            if job and job.source_id not in jobs:
                jobs[job.source_id] = job
                added += 1
        total_pages = int(data.get("totalPage") or 0)
        if not rows or not added or page >= total_pages:
            break
    return list(jobs.values())


# ── CCB (Asia) ───────────────────────────────────────────────────────────────

CCB_BASE = "https://online.asia.ccb.com/PersonalHKWeb/careeropportunity"
CCB_LIST_URL = f"{CCB_BASE}/CareerOpportunityController.jpf"
CCB_DETAIL_URL = f"{CCB_BASE}/actGetCareerJobList.do"
_CCB_STATUS = {"C": "contract", "F": "full-time", "P": "part-time"}
_CCB_JOB_CAP = 150


def parse_ccb_listing(html: str) -> list[dict]:
    """Rows of the listing table; the cells are filled by inline DisplayValue("...") calls."""
    rows = []
    for tr in HTMLParser(html).css("table.search_result_tab tr"):
        link = tr.css_first("a[href*='OpenDetailWindow']")
        if link is None:
            continue
        ref = re.search(r"OpenDetailWindow\('([^']+)'\)", link.attributes.get("href") or "")
        cells = re.findall(r'DisplayValue\("([^"]*)"\)', tr.html or "")
        if not ref or len(cells) < 2:
            continue
        code = re.search(r'if \("(.?)"=="C"\)', tr.html or "")
        rows.append(
            {
                "ref": ref.group(1),
                "title": link.text(strip=True),
                "department": cells[0].strip(),
                "location": cells[1].strip(),
                "status": code.group(1) if code else "",
            }
        )
    return rows


def parse_ccb_detail(html: str) -> dict:
    """Label/value rows plus the Main Responsibilities and Requirements bodies."""
    out: dict = {}
    section = None
    for row in HTMLParser(html).css("#main div.row"):
        left, right = row.css_first("div.left_col"), row.css_first("div.right_col")
        if left is not None and right is not None:
            out[left.text(strip=True)] = right.text(strip=True)
            continue
        heading = row.css_first("h2")
        if heading is not None:
            name = heading.text(strip=True)
            section = name if name in ("Main Responsibilities", "Requirements") else None
            continue
        body = row.css_first("span.font14")
        if section and body is not None and section not in out:
            out[section] = body.html or ""
    return out


def fetch_ccb(client: httpx.Client, company: str, company_slug: str) -> list[Job]:
    response = client.get(CCB_LIST_URL, params={"lang": "english"}, headers={"User-Agent": _UA})
    response.raise_for_status()
    listed: dict[str, dict] = {}
    for row in parse_ccb_listing(response.text):
        if row["location"].lower() == "hong kong":
            listed.setdefault(row["ref"], row)
    if len(listed) > _CCB_JOB_CAP:
        raise ValueError(f"CCB (Asia) listing has {len(listed)} jobs; refusing to crawl that many")

    jobs = []
    for ref, row in listed.items():
        time.sleep(_SLEEP)
        detail_response = client.get(
            CCB_DETAIL_URL, params={"lang": "english", "posno": ref}, headers={"User-Agent": _UA}
        )
        if detail_response.status_code >= 400:
            logger.warning("CCB (Asia) detail %s returned %s; skipped", ref, detail_response.status_code)
            continue
        detail = parse_ccb_detail(detail_response.text)
        if detail.get("Reference Number", ref) != ref:
            raise ValueError(f"CCB (Asia) detail page mismatch for {ref}")
        if (detail.get("Location") or row["location"]).lower() != "hong kong":
            continue
        raw = "<br>".join(detail[k] for k in ("Main Responsibilities", "Requirements") if detail.get(k))
        jobs.append(
            Job(
                source="direct_site",
                source_id=f"{company_slug}:{ref}",
                company=company,
                company_slug=company_slug,
                url=str(detail_response.url),
                title=(detail.get("Job Title") or row["title"]).strip(),
                description_raw=raw,
                description_clean=_strip_html(raw),
                locations=["Hong Kong"],
                scraped_under_slug=company_slug,
                department=row["department"] if row["department"] not in ("", "-") else None,
                employment_type=_CCB_STATUS.get(row["status"]),
                posted_at=_hk_time(detail.get("Job Posted"), "%Y/%m/%d"),
            )
        )
    return jobs


SITE_FETCHERS = {
    "cmb-wing-lung": fetch_cmb,
    "china-merchants-bank": fetch_cmb,  # same Job Centre feed as CMB Wing Lung
    "ping-an": fetch_pingan,
    "ccb-asia": fetch_ccb,
}
