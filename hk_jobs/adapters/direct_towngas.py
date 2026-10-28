"""First-party JSON API behind Towngas's JavaScript job list.

The endpoints and payload are taken from the portal's ``/js/job.js``. The
listing endpoint returns every opening in pages, and the definition endpoint
returns HTML for the full description. No browser or LLM is needed.

Rights review: https://www.towngas.com/en/Info/Disclaimer disallows storing
site content in another website/electronic retrieval system; do not enable
publication without the owner's permission review.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime

import httpx
from selectolax.parser import HTMLParser

from hk_jobs.schema import Job

logger = logging.getLogger(__name__)

BASE_URL = "https://www.towngas.com"
_MAIN_COMPANY = "The HK and China Gas Co Ltd"
_PAGE_SIZE = 100
_EMPLOYMENT = {
    "Permanent": "full-time",
    "Part Time": "part-time",
    "Contract": "contract",
    "Temporary": "contract",
    "Internship": "internship",
    "Apprentice": "internship",
}


def _payload(response: httpx.Response) -> dict:
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or data.get("statusCode") != 200:
        raise ValueError("Towngas API returned an unsuccessful payload")
    content = data.get("content")
    if not isinstance(content, dict):
        raise ValueError("Towngas API content is missing")
    return content


def _posted(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _job_from_payload(summary: dict, detail: dict, company: str, company_slug: str) -> Job:
    job_id = summary["jobID"]
    sections = detail.get("jobDefinitionList") or []
    raw = "\n".join(
        f"<h3>{section.get('titleENU', '')}</h3>{section.get('contentENU', '')}"
        for section in sections
        if isinstance(section, dict) and section.get("contentENU")
    )
    clean = HTMLParser(raw).text(separator="\n", strip=True) if raw else ""
    return Job(
        source="direct_site",
        source_id=f"{company_slug}:{job_id}",
        company=company,
        company_slug=company_slug,
        url=f"{BASE_URL}/en/Careers/Job-Opportunities/Job-List/Job-Details?jobID={job_id}",
        title=summary["jobTitle"].strip(),
        department=summary.get("jobFunction") or None,
        employment_type=_EMPLOYMENT.get(summary.get("employmentType")),
        posted_at=_posted(summary.get("startDate")),
        description_raw=raw,
        description_clean=clean,
        locations=["Hong Kong"],
        board_signals={"expires_at": summary["expireDate"]} if summary.get("expireDate") else {},
    )


def fetch_towngas(client: httpx.Client, company: str, company_slug: str) -> list[Job]:
    """Fetch all Towngas parent-company openings and their full descriptions."""
    jobs: list[Job] = []
    seen: set[str] = set()
    page_num = 1
    while True:
        query = {
            "jobFunction": "-1",
            "employmentType": "-1",
            "companyID": "-1",
            "pageSize": _PAGE_SIZE,
            "pageNum": page_num,
            "keyword": "",
            "sort": 1,
            "ascOrDesc": "asc",
        }
        listing = _payload(client.post(f"{BASE_URL}/api/getJobList?lang=0", json=query))
        rows = listing.get("jobsList")
        if not isinstance(rows, list):
            raise ValueError("Towngas API jobsList is missing")
        for summary in rows:
            if not isinstance(summary, dict) or summary.get("company") != _MAIN_COMPANY:
                continue
            job_id = summary.get("jobID")
            if job_id is None or not summary.get("jobTitle") or str(job_id) in seen:
                continue
            seen.add(str(job_id))
            # The source policy limits detail requests to at most 3 per second.
            if len(seen) > 1:
                time.sleep(0.35)
            try:
                detail = _payload(
                    client.get(
                        f"{BASE_URL}/api/getJobDefinition",
                        params={"jobId": job_id, "lang": 0},
                    )
                )
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning("Towngas detail %s unavailable: %s", job_id, exc)
                detail = {}
            jobs.append(_job_from_payload(summary, detail, company, company_slug))
        total = listing.get("totalNum")
        if not isinstance(total, int) or page_num * _PAGE_SIZE >= total or not rows:
            break
        page_num += 1
    return jobs
