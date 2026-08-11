from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import learning_content
from fastapi.testclient import TestClient

from .support import make_app, make_bundle, make_jobs_db

EVENTS = [
    {
        "id": "event-1",
        "title": "Finance Leadership Seminar",
        "slug": "finance-leadership-seminar",
        "location": {"name": "Central Plaza"},
        "scheduling": {
            "config": {
                "startDate": "2026-09-14T10:00:00.000Z",
                "endDate": "2026-09-14T12:00:00.000Z",
            }
        },
        "mainImage": {"url": "https://static.wixstatic.com/media/event.jpg"},
    }
]


def events_html(events=EVENTS) -> str:
    dates = {
        event["id"]: {
            "startDateISOFormatNotUTC": "2026-09-14T18:00:00+08:00",
            "endDateISOFormatNotUTC": "2026-09-14T20:00:00+08:00",
        }
        for event in events
    }
    payload = {
        "appsWarmupData": {
            "app": {
                "widget": {
                    "events": {"events": events},
                    "dates": {"events": dates},
                }
            }
        }
    }
    return f'<script type="application/json" id="wix-warmup-data">{json.dumps(payload)}</script>'


YOUTUBE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"
      xmlns:media="http://search.yahoo.com/mrss/"
      xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <yt:videoId>qUuzybEQdlE</yt:videoId>
    <title>CEO interview on AI and asset management</title>
    <published>2026-08-09T13:01:14+00:00</published>
    <media:group><media:thumbnail url="https://i.ytimg.com/vi/qUuzybEQdlE/hqdefault.jpg"/></media:group>
  </entry>
</feed>"""


class SourceClient:
    def __init__(self, *, events: str = "ok", videos: str = "ok") -> None:
        self.events = events
        self.videos = videos

    def get(self, url: str) -> httpx.Response:
        request = httpx.Request("GET", url)
        state = self.events if url == learning_content.EVENTS_URL else self.videos
        if state == "fail":
            return httpx.Response(503, request=request, text="unavailable")
        text = events_html() if url == learning_content.EVENTS_URL else YOUTUBE
        return httpx.Response(200, request=request, text=text)


def test_parse_events_page_uses_full_wix_dates_and_remote_assets():
    result = learning_content.parse_events_page(events_html())

    assert result == [
        {
            "id": "event-1",
            "title": "Finance Leadership Seminar",
            "date": "2026-09-14",
            "start_at": "2026-09-14T18:00:00+08:00",
            "end_at": "2026-09-14T20:00:00+08:00",
            "venue": "Central Plaza",
            "online": False,
            "detail_url": "https://www.finexclub.org/event-details/finance-leadership-seminar",
            "image_url": "https://static.wixstatic.com/media/event.jpg",
        }
    ]


def test_parse_youtube_feed_keeps_only_metadata():
    result = learning_content.parse_youtube_feed(YOUTUBE)

    assert result[0]["id"] == "qUuzybEQdlE"
    assert result[0]["topic"] == "AI & technology"
    assert result[0]["watch_url"].endswith("qUuzybEQdlE")
    assert set(result[0]) == {
        "id", "title", "topic", "published_at", "watch_url", "thumbnail_url"
    }


def test_refresh_preserves_last_good_source_when_one_upstream_fails(tmp_path):
    path = tmp_path / "learning.json"
    first = learning_content.refresh_content(
        path,
        client=SourceClient(),
        now=datetime(2026, 8, 1, tzinfo=timezone.utc),
        force=True,
    )
    old_events = first["snapshot"]["events"]

    second = learning_content.refresh_content(
        path,
        client=SourceClient(events="fail"),
        now=datetime(2026, 8, 5, tzinfo=timezone.utc),
        force=True,
    )

    assert second["status"] == "partial"
    assert second["snapshot"]["events"] == old_events
    assert second["snapshot"]["sources"]["events"]["error"]
    assert second["snapshot"]["videos"][0]["id"] == "qUuzybEQdlE"
    assert second["storage_bytes"] < 20_000


def test_refresh_skips_sources_until_72_hours_have_elapsed(tmp_path):
    path = tmp_path / "learning.json"
    learning_content.refresh_content(
        path,
        client=SourceClient(),
        now=datetime(2026, 8, 1, tzinfo=timezone.utc),
        force=True,
    )

    result = learning_content.refresh_content(
        path,
        client=SourceClient(events="fail", videos="fail"),
        now=datetime(2026, 8, 2, tzinfo=timezone.utc),
    )

    assert result["status"] == "not_due"
    assert result["outcomes"] == {"events": "not_due", "videos": "not_due"}


def test_public_api_serves_snapshot_without_fetching_upstreams(tmp_path):
    db = tmp_path / "jobs.db"
    dist = tmp_path / "dist"
    content = tmp_path / "learning.json"
    make_jobs_db(db)
    make_bundle(dist)
    learning_content.refresh_content(
        content,
        client=SourceClient(),
        now=datetime(2026, 8, 1, tzinfo=timezone.utc),
        force=True,
    )
    client = TestClient(make_app(db, dist, tmp_path, learning_content_path=content))

    response = client.get("/api/learning")

    assert response.status_code == 200
    assert response.json()["available"] is True
    assert response.json()["events"][0]["title"] == "Finance Leadership Seminar"
    assert response.json()["storage_bytes"] < 20_000


def test_refresh_api_requires_pipeline_token(tmp_path, monkeypatch):
    db = tmp_path / "jobs.db"
    dist = tmp_path / "dist"
    make_jobs_db(db)
    make_bundle(dist)
    app = make_app(
        db,
        dist,
        tmp_path,
        learning_content_path=tmp_path / "learning.json",
        pipeline_sync_token="sync-secret",
    )
    client = TestClient(app)
    called = []

    def fake_refresh(path, *, force=False):
        called.append((path, force))
        return {
            "status": "updated",
            "outcomes": {"events": "updated", "videos": "updated"},
            "storage_bytes": 123,
            "snapshot": {"events": [{}], "videos": [{}]},
        }

    monkeypatch.setattr(learning_content, "refresh_content", fake_refresh)

    assert client.post("/api/admin/learning/refresh").status_code == 401
    response = client.post(
        "/api/admin/learning/refresh?force=true",
        headers={"X-Pipeline-Sync-Token": "sync-secret"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "updated"
    assert called == [(tmp_path / "learning.json", True)]
