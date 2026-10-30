"""Deterministic readers for Bank of Communications (HK) and China Minsheng Bank.

Bank of Communications (HK): the bank's own CMS publishes vacancies on seven
department pages. Each page has an index of ``showJobDetails('J_nnn')`` links
and the full description in ``td.description#J_nnn`` on the same page. There is
no posting date and no per-job URL (the link is a fragment on the department
page), so ``posted_at`` stays None. Every vacancy is the HK entity's, so the
location is the constant "Hong Kong".

China Minsheng Bank: an unauthenticated JSON backend behind an Angular portal,
HTTP only on port 8080. The listing is a form-encoded POST (the ``view`` field
is mandatory; errors come back as HTTP 200 with ``success: false``). The portal
covers the whole group, so rows are filtered client-side on the region name
being Hong Kong, then each HK row's detail is fetched for the English body.

CITIC Futures International is deliberately not here: its server sends an
incomplete TLS chain, which httpx rejects under normal verification.
"""

import html
import logging
import re
import time
from datetime import datetime, timedelta, timezone

import httpx
from selectolax.parser import HTMLParser

from hk_jobs.adapters.workday import _strip_html
from hk_jobs.schema import Job

logger = logging.getLogger(__name__)

_SLEEP = 0.5  # seconds between requests

# ── Bank of Communications (HK) ───────────────────────────────────────────────

BOCOM_BASE = "https://hk.bankcomm.com/hk/shtml/hk/en/2005773/2005781/2005782/2005783"
BOCOM_DEPARTMENTS = {
    "2005784": "Retail Banking",
    "2005786": "Business Banking",
    "2005785": "Treasury",
    "2005787": "Credit Management",
    "2005788": "Finance",
    "2005789": "Business Support",
    "2005790": "Others",
}
_JOB_ID = re.compile(r"'(J_\d+)'")


def bocom_page_url(channel: str) -> str:
    return f"{BOCOM_BASE}/{channel}/list.shtml"


def parse_bocom_page(page_html: str, channel: str, department: str, company: str, company_slug: str) -> list[Job]:
    tree = HTMLParser(page_html)
    titles: dict[str, str] = {}
    for link in tree.css("a[onclick^='showJobDetails']"):
        match = _JOB_ID.search(link.attributes.get("onclick") or "")
        if match:
            titles.setdefault(match.group(1), link.text(strip=True))
    bodies = {}
    for cell in tree.css("td.description"):
        job_id = cell.attributes.get("id")
        if job_id:
            bodies.setdefault(job_id, cell)
    if set(titles) != set(bodies):
        raise ValueError(
            f"BoCom page {channel} is inconsistent: index {sorted(titles)} vs descriptions {sorted(bodies)}"
        )
    jobs = []
    for job_id, title in titles.items():
        raw = bodies[job_id].html or ""
        jobs.append(
            Job(
                source="direct_site",
                source_id=f"{company_slug}:{channel}:{job_id}",
                company=company,
                company_slug=company_slug,
                url=f"{bocom_page_url(channel)}#{job_id.replace('_', '')}",
                title=title.strip(),
                description_raw=raw,
                description_clean=_strip_html(raw),
                locations=["Hong Kong"],
                department=department,
                scraped_under_slug=company_slug,
            )
        )
    return jobs


def fetch_bocom(client: httpx.Client, company: str, company_slug: str) -> list[Job]:
    jobs: dict[str, Job] = {}
    for n, (channel, department) in enumerate(BOCOM_DEPARTMENTS.items()):
        if n:
            time.sleep(_SLEEP)
        response = client.get(bocom_page_url(channel))
        response.raise_for_status()
        for job in parse_bocom_page(response.text, channel, department, company, company_slug):
            jobs.setdefault(job.source_id, job)
    return list(jobs.values())


# ── China Minsheng Bank ───────────────────────────────────────────────────────

MINSHENG_API = "http://career.cmbc.com.cn:8080/portal/rest/careerrecruitment"
MINSHENG_APP = "http://career.cmbc.com.cn:8080/index.jsp#/app/recruitmentview"
_PAGE_SIZE = 100
_PAGE_CAP = 20
_HKT = timezone(timedelta(hours=8))  # portal timestamps are China/HK local time
_P = "careerRecruitment_"


def is_hong_kong_region(item: dict) -> bool:
    regions = item.get(_P + "regions_name") or ""
    return any(part.strip() == "香港" for part in re.split(r"[,，、]", regions))


def parse_publish_date(value: str | None) -> datetime | None:
    try:
        return datetime.strptime((value or "").strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=_HKT)
    except ValueError:
        return None


def _data(response: httpx.Response) -> dict:
    response.raise_for_status()
    body = response.json()
    if not body.get("success"):
        raise ValueError(f"Minsheng API error: {body.get('messages')}")
    return body["data"]


def _list_all(client: httpx.Client) -> list[dict]:
    items: dict[str, dict] = {}
    for page in range(1, _PAGE_CAP + 1):
        data = _data(
            client.post(
                f"{MINSHENG_API}/search.view",
                data={
                    "searchRecruitmentIds": "social",
                    "view": "careerRecruitmentList",
                    "pageNo": page,
                    "pageSize": _PAGE_SIZE,
                },
            )
        )
        rows = data.get("items") or []
        fresh = [r for r in rows if r.get("id") not in items]
        if not fresh:
            break
        for row in fresh:
            items[row["id"]] = row
        if page >= int(data.get("pageCount") or 1):
            break
        time.sleep(_SLEEP)
    return list(items.values())


def map_minsheng(item: dict, detail: dict, company: str, company_slug: str) -> Job:
    content = detail.get(_P + "career_careerDetail_content") or ""
    quals = detail.get(_P + "career_careerDetail_qualifications") or ""
    raw = html.unescape(content + quals) if "&lt;" in (content + quals) else content + quals
    return Job(
        source="direct_site",
        source_id=f"{company_slug}:{item['id']}",
        company=company,
        company_slug=company_slug,
        url=f"{MINSHENG_APP}/{item['id']}",
        title=(item.get(_P + "career_name") or "").strip(),
        description_raw=raw,
        description_clean=_strip_html(raw),
        locations=["Hong Kong"],
        department=item.get(_P + "career_jobFamily_name") or None,
        posted_at=parse_publish_date(item.get(_P + "career_publishDate")),
        scraped_under_slug=company_slug,
        board_signals={"employer": item.get(_P + "career_enterprise_name")},
    )


def fetch_minsheng(client: httpx.Client, company: str, company_slug: str) -> list[Job]:
    jobs = []
    for item in (i for i in _list_all(client) if is_hong_kong_region(i)):
        time.sleep(_SLEEP)
        detail = _data(
            client.get(f"{MINSHENG_API}/view/{item['id']}.view", params={"view": "careerRecruitmentView"})
        )
        jobs.append(map_minsheng(item, detail, company, company_slug))
    return jobs


SITE_FETCHERS = {
    "bank-of-communications": fetch_bocom,
    "minsheng-bank": fetch_minsheng,
}
