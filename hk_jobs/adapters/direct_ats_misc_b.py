"""Three unrelated employer sites that need their own small readers.

* UBS (``ubs-am-hk``): IBM BrassRing "Talent Gateway" at jobs.ubs.com. One
  careers backend serves every UBS division, so this reads the UBS-wide Hong
  Kong feed (the "Professionals" and "Students and graduates" sites) and records
  the business division in ``department``. Asset Management currently has no
  Hong Kong roles, so those rows are rare; the rest are other UBS divisions.
* CICC (``cicc``): Beisen (zhiye.com) portal. The list endpoint returns a real
  work-location array (``LocNames``) only when the request names the portal's
  display fields; Hong Kong is ``香港特别行政区``. No keyword guessing is used.
* ICBC (Asia) (``icbc-asia``): seven static JSON files with no id, date, location
  or apply URL. Every role is Hong Kong. The id is synthesised from the
  department id and title (plus a description hash only for repeated or empty
  keys); it was identical across repeated fetches.
"""

import hashlib
import html
import json
import logging
import re
import time
from datetime import UTC, datetime, timedelta

import httpx

from hk_jobs.adapters.workday import _strip_html
from hk_jobs.schema import Job

logger = logging.getLogger(__name__)

_SLEEP = 0.5  # seconds between requests to one site

# ── UBS (IBM BrassRing) ───────────────────────────────────────────────────────

UBS_BASE = "https://jobs.ubs.com"
UBS_PARTNER = "25008"
UBS_SITES = (("5012", "15231"), ("5131", "15232"))  # Professionals, Students/graduates
UBS_PAGE = 50  # the search returns at most this many rows
_UBS_SECTIONS = (
    "Key responsibilities",
    "The team",
    "Your skills and experience",
    "About us",
    "How we hire",
    "Join us",
)
_UBS_TOKEN = re.compile(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"')
_UBS_SESSION = re.compile(r'id="CookieValue"[^>]*value="([^"]+)"')
_UBS_PRELOAD = re.compile(r'<input id="preLoadJSON" type="hidden" value="(.*?)" capture-escaped-parsed-value', re.S)


def _ubs_fields(job: dict) -> dict[str, str]:
    return {q.get("QuestionName"): q.get("Value") or "" for q in job.get("Questions") or []}


def _ubs_locations(label: str) -> list[str]:
    out = []
    for part in label.split(","):
        part = part.strip()
        if part:
            out.append("Hong Kong" if part.lower().startswith("hong kong") else part)
    return out


def is_ubs_hong_kong(fields: dict[str, str]) -> bool:
    """Office check: the displayed location label (always present); the City value
    (only echoed when the City facet is applied) is the fallback if the label is empty."""
    label = fields.get("formtext23") or fields.get("formtext2") or ""
    return "hong kong" in label.lower()


def parse_ubs_jobs(
    rows: list[dict],
    company: str,
    company_slug: str,
    details: dict[str, str] | None = None,
) -> list[Job]:
    """Map BrassRing search rows; ``details`` is reqid -> full description HTML."""
    details = details or {}
    jobs: dict[str, Job] = {}
    for row in rows:
        f = _ubs_fields(row)
        reqid = f.get("reqid", "").strip()
        title = html.unescape(f.get("jobtitle", "")).strip()
        if not reqid or not title or not is_ubs_hong_kong(f) or reqid in jobs:
            continue
        raw = details.get(reqid) or html.unescape(f.get("jobdescription", ""))
        function = html.unescape(f.get("formtext21", "")).strip()
        jobs[reqid] = Job(
            source="direct_site",
            source_id=f"{company_slug}:{reqid}",
            company=company,
            company_slug=company_slug,
            url=row.get("Link") or "",
            title=title,
            description_raw=raw,
            description_clean=_strip_html(raw),
            locations=_ubs_locations(f.get("formtext23", "")) or ["Hong Kong"],
            department=(f.get("department") or "").strip() or None,
            scraped_under_slug=company_slug,
            board_signals={"function": function} if function else {},
        )
    return [j for j in jobs.values() if j.url]


def _ubs_detail_html(detail: dict) -> str:
    """Join the job-detail sections that describe the role, in page order."""
    parts = []
    for q in (detail.get("JobDetailQuestions") or []):
        if q.get("QuestionName") in _UBS_SECTIONS and q.get("AnswerValue"):
            parts.append(f"<h3>{q['QuestionName']}</h3>{q['AnswerValue']}")
    return "\n".join(parts)


def _ubs_search(client: httpx.Client, site: str, link_id: str) -> tuple[list[dict], dict[str, str]]:
    """Bootstrap one BrassRing site and return its Hong Kong rows and the request headers."""
    home = (
        f"{UBS_BASE}/TGnewUI/Search/home/HomeWithPreLoad?partnerid={UBS_PARTNER}&siteid={site}"
        f"&PageType=searchResults&SearchType=linkquery&LinkID={link_id}"
    )
    page = client.get(home)
    page.raise_for_status()
    token = _UBS_TOKEN.search(page.text)
    session = _UBS_SESSION.search(page.text)
    preload = _UBS_PRELOAD.search(page.text)
    if not (token and session and preload):
        raise ValueError("UBS BrassRing bootstrap page changed: token/session/preload missing")
    smart = json.loads(json.loads(html.unescape(preload.group(1)))["SmartSearchJSONValue"])
    headers = {
        "RFT": token.group(1),
        "Referer": home,
        "Origin": UBS_BASE,
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/plain, */*",
    }
    body = {
        "PartnerId": UBS_PARTNER,
        "SiteId": site,
        "Keyword": "",
        "Location": "",
        "KeywordCustomSolrFields": smart["KeywordCustomSolrFields"],
        "LocationCustomSolrFields": smart["LocationCustomSolrFields"],
        "TurnOffHttps": False,
        "LinkID": link_id,
        "Latitude": 0,
        "Longitude": 0,
        "EncryptedSessionValue": session.group(1),
        "SortType": "LastUpdated",
        "PowerSearchOptions": {"PowerSearchOption": []},
        "FacetFilterFields": {
            "Facet": [
                {
                    "Name": "formtext2",
                    "Description": "City",
                    "Options": [
                        {
                            "OptionName": "Hong Kong SAR",
                            "OptionValue": "Hong Kong",
                            "Count": 1,
                            "Selected": True,
                        }
                    ],
                }
            ]
        },
    }
    time.sleep(_SLEEP)
    response = client.post(f"{UBS_BASE}/TgNewUI/Search/Ajax/MatchedJobs", json=body, headers=headers)
    response.raise_for_status()
    data = response.json()
    rows = (data.get("Jobs") or {}).get("Job") or []
    total = data.get("JobsCount", len(rows))
    if total != len(rows) or len(rows) >= UBS_PAGE:
        # A full page means the Hong Kong slice needs paging, which is unstable
        # on this portal (tied sort keys); fail loudly rather than lose jobs.
        raise ValueError(f"UBS Hong Kong list is not a single page: {len(rows)} rows of {total}")
    return rows, headers


def _ubs_details(
    client: httpx.Client, rows: list[dict], site: str, headers: dict[str, str]
) -> dict[str, str]:
    details: dict[str, str] = {}
    for row in rows:
        f = _ubs_fields(row)
        reqid = f.get("reqid", "").strip()
        if not reqid or not is_ubs_hong_kong(f) or reqid in details:
            continue
        time.sleep(_SLEEP)
        try:
            response = client.post(
                f"{UBS_BASE}/TgNewUI/Search/Ajax/JobDetails",
                json={
                    "partnerId": UBS_PARTNER,
                    "siteId": site,
                    "jobid": reqid,
                    "configMode": "",
                    "jobSiteId": site,
                    "turnOffHttps": False,
                },
                headers=headers,
            )
            response.raise_for_status()
            details[reqid] = _ubs_detail_html(response.json()["ServiceResponse"]["Jobdetails"])
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            logger.warning("UBS detail for %s failed (%s); using the search summary", reqid, exc)
    return details


def fetch_ubs(client: httpx.Client, company: str, company_slug: str) -> list[Job]:
    rows: list[dict] = []
    details: dict[str, str] = {}
    for site, link_id in UBS_SITES:
        site_rows, headers = _ubs_search(client, site, link_id)
        details.update(_ubs_details(client, site_rows, site, headers))  # while this session is live
        rows += site_rows
        time.sleep(_SLEEP)
    return parse_ubs_jobs(rows, company, company_slug, details)


# ── CICC (Beisen) ─────────────────────────────────────────────────────────────

CICC_BASE = "https://cicc.zhiye.com"
CICC_PORTAL = "1bb97a43-1bb9-42c2-b5c6-19ddc82c0cb9"
CICC_PAGE = 50
_CICC_PAGE_CAP = 20
_CICC_FIELDS = ["jobAdName", "Duty", "Require", "Category", "Kind", "LocId", "PostDate", "Org"]
CICC_HK = "香港"  # substring of the portal's location value 香港特别行政区
_CICC_TITLE_CODE = re.compile(r"\s*\((J\d+)\)\s*$")
_CICC_KIND = {"全职": "full-time", "兼职": "part-time", "实习": "internship"}
_CICC_PLACES = {
    "香港特别行政区": "Hong Kong",
    "北京市": "Beijing",
    "上海市": "Shanghai",
    "广东省·深圳市": "Shenzhen",
    "新加坡共和国": "Singapore",
}
_CST = timedelta(hours=8)  # the portal stores Beijing time


def is_cicc_hong_kong(item: dict) -> bool:
    return any(CICC_HK in (name or "") for name in item.get("LocNames") or [])


def _cicc_posted(value: str | None) -> datetime | None:
    try:
        parsed = datetime.fromisoformat((value or "")[:19])
    except ValueError:
        return None
    if parsed.year < 2000:  # 0001-01-01 means "no date"
        return None
    stamp = (parsed - _CST).replace(tzinfo=UTC)
    return None if stamp > datetime.now(UTC) else stamp


def parse_cicc_jobs(rows: list[dict], company: str, company_slug: str) -> list[Job]:
    jobs: dict[int, Job] = {}
    for item in rows:
        if not is_cicc_hong_kong(item) or item.get("JobAdId") in jobs:
            continue
        raw_title = (item.get("JobAdName") or "").strip()
        code = _CICC_TITLE_CODE.search(raw_title)
        title = _CICC_TITLE_CODE.sub("", raw_title).strip()
        guid = item.get("Id") or ""
        if not title or not guid:
            continue
        intern = str(item.get("CategoryId")) == "3"
        raw = "\n\n".join(p.strip() for p in (item.get("Duty"), item.get("Require")) if p and p.strip())
        places = [_CICC_PLACES.get(n, n) for n in item.get("LocNames") or []]
        places.sort(key=lambda p: p != "Hong Kong")  # Hong Kong first, rest in portal order
        jobs[item["JobAdId"]] = Job(
            source="direct_site",
            source_id=f"{company_slug}:{item['JobAdId']}",
            company=company,
            company_slug=company_slug,
            url=f"{CICC_BASE}/{'intern' if intern else 'social'}/detail?jobAdId={guid}",
            title=title,
            description_raw=raw,
            description_clean=_strip_html(raw),
            locations=places,
            department=(item.get("Org") or "").strip() or None,
            employment_type="internship" if intern else _CICC_KIND.get(item.get("Kind") or ""),
            posted_at=_cicc_posted(item.get("PostDate")),
            scraped_under_slug=company_slug,
            board_signals={"requisition": code.group(1)} if code else {},
        )
    return list(jobs.values())


def fetch_cicc(client: httpx.Client, company: str, company_slug: str) -> list[Job]:
    """Page the whole portal (social 1 and project-intern 3) and filter locally."""
    rows: dict[str, dict] = {}
    for category in (1, 3):
        seen_in_category = 0
        total = None
        for page in range(_CICC_PAGE_CAP):
            response = client.post(
                f"{CICC_BASE}/api/Jobad/GetJobAdPageList",
                json={
                    "PageIndex": page,
                    "PageSize": CICC_PAGE,
                    "KeyWords": "",
                    "SpecialType": 0,
                    "PortalId": CICC_PORTAL,
                    "DisplayFields": _CICC_FIELDS,
                    "Category": category,
                },
                headers={"Referer": f"{CICC_BASE}/social"},
            )
            response.raise_for_status()
            data = response.json()
            if data.get("Code") != 200:
                raise ValueError(f"CICC list returned code {data.get('Code')}")
            total = data.get("Count", total)
            page_rows = data.get("Data") or []
            fresh = [r for r in page_rows if r.get("Id") not in rows]
            if not fresh:
                break
            for r in fresh:
                rows[r["Id"]] = r
            seen_in_category += len(fresh)
            if total is not None and seen_in_category >= total:
                break
            time.sleep(_SLEEP)
        if total is not None and seen_in_category != total:
            raise ValueError(f"CICC listing is incomplete: {seen_in_category} of {total}")
    return parse_cicc_jobs(list(rows.values()), company, company_slug)


# ── ICBC (Asia) ───────────────────────────────────────────────────────────────

ICBC_JSON = "https://v.icbc.com.cn/userfiles/resources/icbc/asia/temp/json/career/en/{cat}.json"
ICBC_PAGE = "https://www.icbcasia.com/hk/en/about-us/career-opportunities/{slug}.html"
# graduate_hires.json is an expired campaign (deadline 28 Feb 2026) and is not read.
ICBC_CATEGORIES = (
    "branches",
    "corporate_banking",
    "financial_technology",
    "global_markets_and_investment_banking",
    "operations",
    "retail_banking",
    "risk_control_and_management",
)


def _icbc_leaves(children: list[dict]):
    """A leaf has ``ans``; otherwise recurse into ``children`` (as the site's career.js does)."""
    for node in children:
        if node.get("ans") is not None:
            yield node
        else:
            yield from _icbc_leaves(node.get("children") or [])


def parse_icbc_category(data: dict, category: str, company: str, company_slug: str) -> list[Job]:
    """Jobs of one category file. The id is ``<dept id>:<title slug>``; a short
    description hash is appended only when that key repeats within the file."""
    items = data.get("items")
    if not isinstance(items, list):
        raise ValueError("ICBC career file has no 'items' list")
    entries = []
    for dept in items:
        for leaf in _icbc_leaves(dept.get("children") or []):
            title = html.unescape(leaf.get("name") or "")
            title = " ".join(title.split())
            if not title:  # a real vacancy but nameless; cannot be shown or keyed honestly
                logger.warning("ICBC (Asia) %s: skipped a vacancy with an empty title", dept.get("name"))
                continue
            slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
            entries.append((f"{dept.get('id')}:{slug}", dept, title, leaf["ans"]))
    counts: dict[str, int] = {}
    for key, *_ in entries:
        counts[key] = counts.get(key, 0) + 1
    jobs: dict[str, Job] = {}
    for key, dept, title, body in entries:
        if counts[key] > 1:
            key = f"{key}#{hashlib.sha1(body.encode()).hexdigest()[:10]}"
        source_id = f"{company_slug}:{key}"
        if source_id in jobs:  # identical title and identical body: one vacancy
            continue
        jobs[source_id] = Job(
            source="direct_site",
            source_id=source_id,
            company=company,
            company_slug=company_slug,
            url=ICBC_PAGE.format(slug=category.replace("_", "-")),
            title=title,
            description_raw=body,
            description_clean=_strip_html(body),
            locations=["Hong Kong"],
            department=(dept.get("name") or "").strip() or None,
            scraped_under_slug=company_slug,
            board_signals={"category": category},
        )
    return list(jobs.values())


def fetch_icbc(client: httpx.Client, company: str, company_slug: str) -> list[Job]:
    jobs: dict[str, Job] = {}
    for category in ICBC_CATEGORIES:
        response = client.get(ICBC_JSON.format(cat=category))
        response.raise_for_status()
        for job in parse_icbc_category(response.json(), category, company, company_slug):
            jobs.setdefault(job.source_id, job)
        time.sleep(_SLEEP)
    if not jobs:
        raise ValueError("ICBC (Asia) career files held no vacancies; the layout may have changed")
    return list(jobs.values())


SITE_FETCHERS = {
    "ubs-am-hk": fetch_ubs,
    "cicc": fetch_cicc,
    "icbc-asia": fetch_icbc,
}
