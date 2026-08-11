"""Refresh and persist the small, public Learning-page content snapshot.

The Learning page must not depend on either upstream site at request time.  This
module fetches both sources on a schedule, validates their public metadata, and
atomically replaces a tiny JSON snapshot.  A failed refresh keeps the last good
items; images and videos always remain hosted by Wix and YouTube.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree

import httpx

logger = logging.getLogger(__name__)

EVENTS_URL = "https://www.finexclub.org/event-list"
YOUTUBE_CHANNEL_ID = "UCJkITsrZncJrmEuNtbFGChg"
YOUTUBE_FEED_URL = (
    "https://www.youtube.com/feeds/videos.xml?channel_id=" + YOUTUBE_CHANNEL_ID
)
REFRESH_INTERVAL = timedelta(hours=72)
SCHEMA_VERSION = 1
MAX_EVENTS = 100
MAX_VIDEOS = 12

_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_ATOM = "{http://www.w3.org/2005/Atom}"
_YT = "{http://www.youtube.com/xml/schemas/2015}"
_MEDIA = "{http://search.yahoo.com/mrss/}"


class LearningContentError(ValueError):
    """An upstream response is missing or unsafe to publish."""


class _WarmupDataParser(HTMLParser):
    """Extract Wix's server-rendered warmup JSON without depending on CSS classes."""

    def __init__(self) -> None:
        super().__init__()
        self._collecting = False
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "script" and values.get("id") == "wix-warmup-data":
            self._collecting = True

    def handle_data(self, data: str) -> None:
        if self._collecting:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._collecting:
            self._collecting = False

    @property
    def payload(self) -> str:
        return "".join(self._parts)


def _find_events_component(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        events = value.get("events")
        dates = value.get("dates")
        if (
            isinstance(events, dict)
            and isinstance(events.get("events"), list)
            and isinstance(dates, dict)
            and isinstance(dates.get("events"), dict)
        ):
            return value
        for child in value.values():
            found = _find_events_component(child)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_events_component(child)
            if found is not None:
                return found
    return None


def parse_events_page(html: str) -> list[dict[str, Any]]:
    """Return validated events from the official Wix server-rendered payload."""

    parser = _WarmupDataParser()
    parser.feed(html)
    if not parser.payload:
        raise LearningContentError("FinEx events page has no Wix warmup data")
    try:
        root = json.loads(parser.payload)
    except json.JSONDecodeError as exc:
        raise LearningContentError("FinEx events warmup data is invalid JSON") from exc

    component = _find_events_component(root)
    if component is None:
        raise LearningContentError("FinEx events payload has no events component")
    raw_events = component["events"]["events"]
    if not 1 <= len(raw_events) <= MAX_EVENTS:
        raise LearningContentError(
            f"FinEx events count {len(raw_events)} is outside the safe range"
        )

    date_details = component["dates"]["events"]
    events: list[dict[str, Any]] = []
    for raw in raw_events:
        event_id = str(raw.get("id") or "").strip()
        title = str(raw.get("title") or "").strip()
        slug = str(raw.get("slug") or "").strip()
        scheduling = raw.get("scheduling") or {}
        config = scheduling.get("config") or {}
        rendered_date = date_details.get(event_id) or {}
        start_at = str(
            rendered_date.get("startDateISOFormatNotUTC")
            or config.get("startDate")
            or ""
        ).strip()
        end_at = str(
            rendered_date.get("endDateISOFormatNotUTC")
            or config.get("endDate")
            or ""
        ).strip()
        location = raw.get("location") or {}
        venue = str(location.get("name") or "To be announced").strip()
        image = raw.get("mainImage") or {}
        image_url = str(image.get("url") or "").strip()

        if not event_id or not title or not slug or len(title) > 500:
            raise LearningContentError("FinEx event is missing its identity or title")
        try:
            datetime.fromisoformat(start_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise LearningContentError(f"FinEx event {event_id} has an invalid date") from exc

        events.append(
            {
                "id": event_id,
                "title": title,
                "date": start_at[:10],
                "start_at": start_at,
                "end_at": end_at or None,
                "venue": venue,
                "online": venue.casefold() in {"online", "webinar"},
                "detail_url": f"https://www.finexclub.org/event-details/{slug}",
                "image_url": image_url or None,
            }
        )

    return sorted(events, key=lambda event: event["start_at"], reverse=True)


def _video_topic(title: str) -> str:
    lowered = title.casefold()
    topics = (
        (("artificial intelligence", " ai ", "fintech", "人工智能"), "AI & technology"),
        (("climate", "sustainab"), "Sustainability"),
        (("private equity", "private credit", "私募"), "Private markets"),
        (("crypto", "web3", "token", "數字貨幣"), "Digital assets"),
        (("bank", "asset management", "基金", "資管"), "Banking & markets"),
    )
    padded = f" {lowered} "
    for terms, label in topics:
        if any(term in padded for term in terms):
            return label
    return "FinEx Club"


def parse_youtube_feed(xml: str) -> list[dict[str, Any]]:
    """Return the newest public uploads from FinEx Club's official Atom feed."""

    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise LearningContentError("YouTube feed is invalid XML") from exc

    videos: list[dict[str, Any]] = []
    for entry in root.findall(f"{_ATOM}entry")[:MAX_VIDEOS]:
        video_id = (entry.findtext(f"{_YT}videoId") or "").strip()
        title = (entry.findtext(f"{_ATOM}title") or "").strip()
        published_at = (entry.findtext(f"{_ATOM}published") or "").strip()
        group = entry.find(f"{_MEDIA}group")
        thumbnail = group.find(f"{_MEDIA}thumbnail") if group is not None else None
        thumbnail_url = thumbnail.get("url", "") if thumbnail is not None else ""
        if not _VIDEO_ID.fullmatch(video_id) or not title or len(title) > 500:
            raise LearningContentError("YouTube entry is missing a valid ID or title")
        try:
            datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise LearningContentError(f"YouTube video {video_id} has an invalid date") from exc
        videos.append(
            {
                "id": video_id,
                "title": title,
                "topic": _video_topic(title),
                "published_at": published_at,
                "watch_url": f"https://www.youtube.com/watch?v={video_id}",
                "thumbnail_url": thumbnail_url
                or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
            }
        )
    if not videos:
        raise LearningContentError("YouTube feed contains no videos")
    return videos


def empty_snapshot() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": None,
        "events": [],
        "videos": [],
        "sources": {
            "events": {"last_success_at": None, "last_attempt_at": None, "error": None},
            "videos": {"last_success_at": None, "last_attempt_at": None, "error": None},
        },
    }


def load_snapshot(path: Path) -> dict[str, Any]:
    """Read a snapshot, degrading to an empty response if none exists yet."""

    if not path.is_file():
        return empty_snapshot()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Learning snapshot %s is unreadable: %s", path, exc)
        return empty_snapshot()
    if value.get("schema_version") != SCHEMA_VERSION:
        logger.warning("Learning snapshot %s has an unsupported schema", path)
        return empty_snapshot()
    return value


def _write_snapshot(path: Path, snapshot: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    temporary.replace(path)


def _parse_timestamp(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _due(source: dict[str, Any], now: datetime, force: bool) -> bool:
    if force:
        return True
    last_success = _parse_timestamp(source.get("last_success_at"))
    return last_success is None or now - last_success >= REFRESH_INTERVAL


def _fetch_text(client: httpx.Client, url: str) -> str:
    response = client.get(url)
    response.raise_for_status()
    return response.text


def refresh_content(
    path: Path,
    *,
    client: httpx.Client | None = None,
    now: datetime | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Refresh due sources independently and atomically retain the best snapshot."""

    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    timestamp = now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    snapshot = load_snapshot(path)
    sources = snapshot.setdefault("sources", empty_snapshot()["sources"])
    own_client = client is None
    if client is None:
        client = httpx.Client(
            timeout=25,
            follow_redirects=True,
            headers={"User-Agent": "FinEx-Careers-Learning-Sync/1.0"},
        )

    outcomes: dict[str, str] = {}
    parsers: Iterable[tuple[str, str, Any]] = (
        ("events", EVENTS_URL, parse_events_page),
        ("videos", YOUTUBE_FEED_URL, parse_youtube_feed),
    )
    try:
        for name, url, parser in parsers:
            state = sources.setdefault(name, {})
            if not _due(state, now, force):
                outcomes[name] = "not_due"
                continue
            state["last_attempt_at"] = timestamp
            try:
                items = parser(_fetch_text(client, url))
            except (httpx.HTTPError, LearningContentError) as exc:
                state["error"] = str(exc)[:500]
                outcomes[name] = "failed"
                logger.warning("Learning %s refresh failed: %s", name, exc)
                continue
            snapshot[name] = items
            state.update(
                {"last_success_at": timestamp, "error": None, "count": len(items)}
            )
            outcomes[name] = "updated"
    finally:
        if own_client:
            client.close()

    if "updated" in outcomes.values():
        snapshot["updated_at"] = timestamp
    snapshot["schema_version"] = SCHEMA_VERSION
    _write_snapshot(path, snapshot)

    if outcomes and all(result == "failed" for result in outcomes.values()):
        status = "failed"
    elif "failed" in outcomes.values():
        status = "partial"
    elif "updated" in outcomes.values():
        status = "updated"
    else:
        status = "not_due"
    return {
        "status": status,
        "outcomes": outcomes,
        "storage_bytes": path.stat().st_size,
        "snapshot": snapshot,
    }


def public_snapshot(path: Path) -> dict[str, Any]:
    snapshot = load_snapshot(path)
    return {
        **snapshot,
        "available": bool(snapshot["events"] or snapshot["videos"]),
        "storage_bytes": path.stat().st_size if path.is_file() else 0,
    }
