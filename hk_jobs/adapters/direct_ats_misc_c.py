"""Deterministic readers for ZA Bank (Feishu Hire), Mox Bank (Pinpoint) and Macquarie (Avature).

ZA Bank: ``POST /api/v1/search/job/posts`` on the ZA Group Feishu Hire portal (site path
246012), offset paged, descriptions inline as plain text, ``publish_time`` in epoch ms. The
tenant mixes ZA Group entities with no entity field, so rows that talk about insurance and
never about banking are dropped (see ``is_za_bank_role``).

Mox Bank: Pinpoint's public ``/postings.json`` (one page, full HTML sections, no posting date).

Macquarie: Avature ``SearchJobs/Hong Kong`` is a free-text search, so rows are filtered on the
"Office Location" field. Server-rendered, 9 rows per page, ``jobOffset`` advances it; past the
end Avature answers with a redirect to an error page. Detail pages give the description.
robots.txt disallows ``qtvc=`` URLs; this never sends it.
"""

import html as html_lib
import logging
import re
import time
from datetime import UTC, datetime

import httpx
from selectolax.parser import HTMLParser

from hk_jobs.adapters.workday import _strip_html
from hk_jobs.schema import Job

logger = logging.getLogger(__name__)

_SLEEP = 0.3
_PAGE_CAP = 20


def _employment_type(text: str | None) -> str | None:
    t = (text or "").lower().replace("_", " ").replace("-", " ")
    if "intern" in t:
        return "internship"
    if "part time" in t:
        return "part-time"
    if "contract" in t or "fixed term" in t or "temporary" in t:
        return "contract"
    if "full time" in t:
        return "full-time"
    return None


# ── ZA Bank (Feishu Hire) ─────────────────────────────────────────────────────

ZA_BASE = "https://zaglobal.jobs.feishu.cn"
ZA_SITE_PATH = "246012"
ZA_HK_CITY = "CT_159"
_ZA_LIMIT = 50


def _za_is_hong_kong(row: dict) -> bool:
    for city in row.get("city_list") or []:
        if city.get("code") == ZA_HK_CITY or "hong kong" in (city.get("en_name") or "").lower():
            return True
    return False


def is_za_bank_role(row: dict) -> bool:
    """False for insurance-side roles of the shared ZA Group portal (no entity field exists)."""
    text = " ".join(str(row.get(k) or "") for k in ("title", "description", "requirement")).lower()
    return not ("insur" in text and "bank" not in text)


def _za_posted_at(row: dict) -> datetime | None:
    ms = row.get("publish_time")
    if not isinstance(ms, int | float) or ms <= 0:
        return None
    return datetime.fromtimestamp(ms / 1000, UTC)


def parse_za_rows(rows: list[dict], company: str, company_slug: str) -> list[Job]:
    jobs = []
    for row in rows:
        if not _za_is_hong_kong(row) or not is_za_bank_role(row):
            continue
        job_id = str(row.get("id") or "").strip()
        title = (row.get("title") or "").strip()
        if not job_id or not title:
            continue
        raw = "\n\n".join(p.strip() for p in (row.get("description"), row.get("requirement")) if p and p.strip())
        category = row.get("job_category") or {}
        jobs.append(
            Job(
                source="direct_site",
                source_id=f"{company_slug}:{job_id}",
                company=company,
                company_slug=company_slug,
                url=f"{ZA_BASE}/{ZA_SITE_PATH}/position/{job_id}/detail",
                title=title,
                description_raw=raw,
                description_clean=_strip_html(raw),
                locations=["Hong Kong"],
                department=category.get("en_name") or None,
                posted_at=_za_posted_at(row),
                scraped_under_slug=company_slug,
            )
        )
    return jobs


def fetch_za_bank(client: httpx.Client, company: str, company_slug: str) -> list[Job]:
    headers = {"website-path": ZA_SITE_PATH, "Origin": ZA_BASE, "Referer": f"{ZA_BASE}/{ZA_SITE_PATH}"}
    seen: dict[str, dict] = {}
    offset, total = 0, None
    for page in range(_PAGE_CAP):
        body = {
            "keyword": "", "limit": _ZA_LIMIT, "offset": offset,
            "job_category_id_list": [], "tag_id_list": [], "location_code_list": [ZA_HK_CITY],
            "subject_id_list": [], "recruitment_id_list": [], "portal_type": 6,
            "job_function_id_list": [], "storefront_id_list": [], "portal_entrance": 1,
        }
        response = client.post(f"{ZA_BASE}/api/v1/search/job/posts", json=body, headers=headers)
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != 0 or not isinstance(payload.get("data"), dict):
            raise ValueError(f"ZA Bank Feishu response unexpected: code={payload.get('code')}")
        data = payload["data"]
        batch = data.get("job_post_list") or []
        total = data.get("count")
        if not isinstance(total, int):
            raise ValueError("ZA Bank Feishu response has no count")
        if not batch:
            break
        fresh = [r for r in batch if str(r.get("id")) not in seen]
        if not fresh:
            break  # a repeated page: stop rather than loop
        seen.update({str(r.get("id")): r for r in fresh})
        offset += len(batch)
        if offset >= total:
            break
        time.sleep(_SLEEP)
    if total and not seen:
        raise ValueError("ZA Bank Feishu listing reports jobs but returned none")
    return parse_za_rows(list(seen.values()), company, company_slug)


# ── Mox Bank (Pinpoint) ───────────────────────────────────────────────────────

MOX_FEED = "https://moxbank.pinpointhq.com/postings.json"
_SECTIONS = (
    ("description", None),
    ("key_responsibilities", "key_responsibilities_header"),
    ("skills_knowledge_expertise", "skills_knowledge_expertise_header"),
    ("benefits", "benefits_header"),
)


def _mox_description(row: dict) -> str:
    parts = []
    for field, header_field in _SECTIONS:
        body = (row.get(field) or "").strip()
        if not body:
            continue
        header = (row.get(header_field) or "").strip() if header_field else ""
        parts.append((f"<h3>{html_lib.escape(header)}</h3>" if header else "") + body)
    return "\n".join(parts).replace("<!--block-->", "")


def parse_mox_feed(payload: dict, company: str, company_slug: str) -> list[Job]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("Mox Pinpoint feed has no 'data' list")
    jobs: dict[str, Job] = {}
    for row in payload["data"]:
        location = row.get("location") or {}
        label = " ".join(str(location.get(k) or "") for k in ("name", "city", "province")).lower()
        if "hong kong" not in label:
            continue
        job_id = str(row.get("id") or "").strip()
        title = (row.get("title") or "").strip()
        if not job_id or not title or not row.get("url"):
            continue
        raw = _mox_description(row)
        job = Job(
            source="direct_site",
            source_id=f"{company_slug}:{job_id}",
            company=company,
            company_slug=company_slug,
            url=row["url"],
            title=title,
            description_raw=raw,
            description_clean=_strip_html(raw),
            locations=["Hong Kong"],
            department=((row.get("job") or {}).get("department") or {}).get("name") or None,
            employment_type=_employment_type(row.get("employment_type")),
            remote_type="onsite" if row.get("workplace_type") == "onsite" else None,
            scraped_under_slug=company_slug,
        )
        jobs.setdefault(job.source_id, job)
    return list(jobs.values())


def fetch_mox_bank(client: httpx.Client, company: str, company_slug: str) -> list[Job]:
    response = client.get(MOX_FEED)
    response.raise_for_status()
    return parse_mox_feed(response.json(), company, company_slug)


# ── Macquarie (Avature) ───────────────────────────────────────────────────────

MQ_LIST = "https://recruitment.macquarie.com/en_US/careers/SearchJobs/Hong%20Kong"
MQ_DETAIL = "https://recruitment.macquarie.com/en_US/careers/JobDetail"
_MQ_PAGE = 9
_MQ_ID = re.compile(r"jobId=(\d+)")


def _mq_fields(article) -> dict[str, str]:
    """Label (from the icon's alt text, e.g. 'Office Location') -> value for one result."""
    out = {}
    for block in article.css("div.article__details__data"):
        icon = block.css_first("img.icon")
        value = block.css_first("p")
        if icon is None or value is None:
            continue
        label = (icon.attributes.get("alt") or "").strip().rstrip(":")
        out[label] = re.sub(r"\s+", " ", value.text(strip=True))
    return out


def parse_macquarie_listing(page: str) -> list[dict]:
    rows = []
    for article in HTMLParser(page).css("article.article--result"):
        link = article.css_first("h3 a.link[href]")
        if link is None:
            continue
        match = _MQ_ID.search(link.attributes.get("href", ""))
        if not match:
            continue
        fields = _mq_fields(article)
        offices = [
            re.sub(r"\s+Office$", "", o.strip())
            for o in fields.get("Office Location", "").split(",")
            if o.strip()
        ]
        rows.append(
            {
                "id": match.group(1),
                "title": link.text(strip=True),
                "offices": offices,
                "posted": fields.get("Posted Date"),
                "category": fields.get("Job Category") or None,
            }
        )
    return rows


def is_macquarie_hong_kong(row: dict) -> bool:
    return any(o.lower() == "hong kong" for o in row["offices"])


def _mq_posted_at(text: str | None) -> datetime | None:
    try:
        return datetime.strptime((text or "").strip(), "%d %b %Y").replace(tzinfo=UTC)
    except ValueError:
        return None


def parse_macquarie_detail(page: str) -> tuple[str, str | None]:
    """(description HTML, employment term text). Metadata fields (class field--*) are skipped."""
    tree = HTMLParser(page)
    parts = []
    for article in tree.css("section.js_views article.article--details"):
        title = article.css_first("h3.article__header__text__title")
        for value in article.css("div.article__content__view__field__value"):
            parent_cls = value.parent.attributes.get("class") or "" if value.parent else ""
            if "field--" in parent_cls:
                continue
            body = (value.html or "").strip()
            if title is not None and title.text(strip=True):
                body = f"<h3>{html_lib.escape(title.text(strip=True))}</h3>\n" + body
                title = None  # heading only once per section
            parts.append(body)
    term = tree.css_first("div.field--employmentterm div.article__content__view__field__value")
    term_text = re.sub(r"[\s,]+$", "", term.text(strip=True)) if term is not None else None
    return "\n".join(parts), term_text or None


def fetch_macquarie(client: httpx.Client, company: str, company_slug: str) -> list[Job]:
    listed: dict[str, dict] = {}
    for page in range(_PAGE_CAP):
        response = client.get(MQ_LIST, params={"listFilterMode": 1, "jobOffset": page * _MQ_PAGE})
        if response.is_redirect:
            break  # Avature redirects to an error page past the last result
        response.raise_for_status()
        rows = parse_macquarie_listing(response.text)
        fresh = [r for r in rows if r["id"] not in listed]
        if not fresh:
            break
        listed.update({r["id"]: r for r in fresh})
        if len(rows) < _MQ_PAGE:
            break
        time.sleep(_SLEEP)
    if not listed:
        logger.warning("Macquarie listing yielded no results at all; check Avature markup")

    jobs = []
    for row in (r for r in listed.values() if is_macquarie_hong_kong(r)):
        time.sleep(_SLEEP)
        url = f"{MQ_DETAIL}?jobId={row['id']}"
        detail = client.get(url)
        detail.raise_for_status()
        raw, term = parse_macquarie_detail(detail.text)
        jobs.append(
            Job(
                source="direct_site",
                source_id=f"{company_slug}:{row['id']}",
                company=company,
                company_slug=company_slug,
                url=url,
                title=row["title"],
                description_raw=raw,
                description_clean=_strip_html(raw),
                locations=row["offices"],
                department=row["category"],
                employment_type=_employment_type(term),
                posted_at=_mq_posted_at(row["posted"]),
                scraped_under_slug=company_slug,
            )
        )
    return jobs


SITE_FETCHERS = {
    "za-bank": fetch_za_bank,
    "mox-bank": fetch_mox_bank,
    "macquarie": fetch_macquarie,
}
