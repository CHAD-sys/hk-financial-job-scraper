"""Deterministic reader for Jane Street's public open-positions feed.

The careers page is an empty shell that its own JavaScript fills from one static
JSON file, ``/jobs/main.json`` (every office, descriptions inline, no paging).
Hong Kong rows have ``city == "HKG"`` (or a multi-city value such as "NYC/HKG").
The feed has no posting date, so ``posted_at`` stays None.
"""

import html
import logging
import re

import httpx

from hk_jobs.adapters.workday import _strip_html
from hk_jobs.schema import Job

logger = logging.getLogger(__name__)

FEED_URL = "https://www.janestreet.com/jobs/main.json"
POSITION_URL = "https://www.janestreet.com/join-jane-street/position/{id}/"
# robots.txt disallows exactly this position page; do not publish a link to it.
_ROBOTS_DISALLOWED_IDS = frozenset({"7304961002"})

# Some titles swap Latin capitals for look-alike Lisu letters (seen live:
# "ꓟachine ꓡearning ꓣesearcher"). Only letters verified against a real title are
# mapped; anything else is left alone and logged rather than guessed at.
_LISU_TO_LATIN = {"ꓟ": "M", "ꓡ": "L", "ꓣ": "R"}
_LISU_RANGE = re.compile("[ꓐ-꓿]")


def clean_title(raw: str) -> str:
    title = "".join(_LISU_TO_LATIN.get(ch, ch) for ch in raw).strip()
    if _LISU_RANGE.search(title):
        logger.warning("Jane Street title still has unmapped Lisu letters: %r", title)
    return title


def is_hong_kong(city: str | None) -> bool:
    return "HKG" in (city or "").upper().split("/")


def parse_janestreet_feed(
    rows: list[dict], company: str, company_slug: str
) -> list[Job]:
    jobs: list[Job] = []
    seen: set[str] = set()
    for row in rows:
        job_id = str(row.get("id") or "")
        title = clean_title(row.get("position") or "")
        if (
            not job_id
            or not title
            or job_id in seen
            or job_id in _ROBOTS_DISALLOWED_IDS
            or not is_hong_kong(row.get("city"))
        ):
            continue
        seen.add(job_id)
        raw = html.unescape(row.get("overview") or "")
        jobs.append(
            Job(
                source="direct_site",
                source_id=f"{company_slug}:{job_id}",
                company=company,
                company_slug=company_slug,
                url=POSITION_URL.format(id=job_id),
                title=title,
                description_raw=raw,
                description_clean=_strip_html(raw),
                locations=["Hong Kong"],
                department=row.get("team") or row.get("category") or None,
                employment_type="internship"
                if "internship" in (row.get("availability") or "").lower()
                else None,
                scraped_under_slug=company_slug,
                board_signals={
                    "availability": row.get("availability"),
                    "duration": row.get("duration"),
                    "category": row.get("category"),
                },
            )
        )
    return jobs


def fetch_janestreet(client: httpx.Client, company: str, company_slug: str) -> list[Job]:
    response = client.get(FEED_URL)
    response.raise_for_status()
    rows = response.json()
    if not isinstance(rows, list):
        raise ValueError("Jane Street feed is no longer a JSON array; check main.json")
    jobs = parse_janestreet_feed(rows, company, company_slug)
    if rows and not jobs:
        logger.warning("Jane Street feed has %d rows but none in Hong Kong", len(rows))
    return jobs
