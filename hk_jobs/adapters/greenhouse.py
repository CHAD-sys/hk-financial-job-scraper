"""
Greenhouse job-board adapter.

Greenhouse publishes every board as an unauthenticated JSON feed:

  GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true

One response holds the whole board (no pagination) with the full description
inline. Used for quant/hedge-fund firms whose own careers site only wraps this
feed: Flow Traders, Hudson River Trading, Point72, Squarepoint, Man Group.

Hong Kong is filtered client-side. ``location.name`` alone is not enough — HRT
lists a Hong Kong role as "Singapore" and Squarepoint spells it "Honk Kong" — so
a job counts when ``location.name`` OR any ``offices[]`` name/location says
"Hong Kong".
"""

import html
import logging
from datetime import datetime

from hk_jobs.adapters.base import BaseAdapter
from hk_jobs.adapters.workday import _strip_html
from hk_jobs.http_utils import with_retry
from hk_jobs.schema import Job

logger = logging.getLogger(__name__)

_API = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
_HK = "hong kong"


def _hk_offices(job: dict) -> list[str]:
    """Offices on this posting that are in Hong Kong (names only, stripped)."""
    return [
        (o.get("name") or "").strip()
        for o in job.get("offices") or []
        if _HK in f"{o.get('name') or ''} {o.get('location') or ''}".lower()
    ]


def is_hong_kong(job: dict) -> bool:
    location = ((job.get("location") or {}).get("name") or "").lower()
    return _HK in location or bool(_hk_offices(job))


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        logger.debug("Could not parse Greenhouse timestamp %r", value)
        return None


class GreenhouseAdapter(BaseAdapter):
    """``board_token`` comes from companies.yaml (e.g. ``flowtraders``)."""

    source_name = "greenhouse"

    def __init__(self, company: str, company_slug: str, board_token: str, **kwargs) -> None:
        super().__init__(company, company_slug, board_token=board_token, **kwargs)
        self.board_token = board_token

    def fetch_jobs(self) -> list[Job]:
        return self._safe_fetch(self._fetch_all)

    def _fetch_all(self) -> list[Job]:
        with self._client(timeout=30.0) as client:
            resp = with_retry(
                lambda: client.get(
                    _API.format(token=self.board_token), params={"content": "true"}
                )
            )
            resp.raise_for_status()
            raw = resp.json().get("jobs") or []

        jobs: dict[str, Job] = {}
        for item in raw:
            if not is_hong_kong(item):
                continue
            job = self._map(item)
            if job.source_id and job.title:
                jobs.setdefault(job.source_id, job)  # multi-office reqs repeat ids
        if raw and not jobs:
            logger.info("%s: %d jobs on board, none in Hong Kong", self.company, len(raw))
        return list(jobs.values())

    def _map(self, item: dict) -> Job:
        # `content` is entity-escaped HTML — unescape exactly once.
        raw_html = html.unescape(item.get("content") or "")
        hk_offices = _hk_offices(item)
        # Greenhouse leaves first_published null on some reqs; updated_at is the
        # nearest honest fallback and is only used for that.
        posted_at = _parse_dt(item.get("first_published")) or _parse_dt(item.get("updated_at"))
        departments = [d.get("name") for d in item.get("departments") or [] if d.get("name")]
        return Job(
            source=self.source_name,
            source_id=str(item.get("id") or ""),
            company=self.company,
            company_slug=self.company_slug,
            url=item.get("absolute_url") or "",
            title=(item.get("title") or "").strip(),
            department=departments[0] if departments else None,
            locations=["Hong Kong"],
            description_raw=raw_html,
            description_clean=_strip_html(raw_html),
            posted_at=posted_at,
            board_signals={
                "requisition_id": item.get("requisition_id"),
                "all_locations": (item.get("location") or {}).get("name", "").strip(),
                "hk_offices": hk_offices,
            },
        )
