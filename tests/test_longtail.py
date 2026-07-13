"""
Tests for the longtail (LLM-extraction) adapter.

Focus: _parse_posted_date must reject implausible LLM-extracted dates so that a
copyright year or a future deadline scraped off a boutique careers page never
becomes a job's posting date (which would corrupt "newest first" sorting).
"""

from datetime import datetime, timedelta, timezone

from hk_jobs.adapters.longtail import _parse_posted_date


def _iso(days_offset: int) -> str:
    d = datetime.now(timezone.utc).date() + timedelta(days=days_offset)
    return d.isoformat()


def test_recent_date_is_kept():
    got = _parse_posted_date(_iso(-20))
    assert got is not None
    assert got.date() == datetime.now(timezone.utc).date() - timedelta(days=20)


def test_today_is_kept():
    assert _parse_posted_date(_iso(0)) is not None


def test_future_date_is_rejected():
    # LLM grabbed an application deadline / wrong year in the future.
    assert _parse_posted_date(_iso(30)) is None
    assert _parse_posted_date("2099-01-01") is None


def test_ancient_date_is_rejected():
    # LLM grabbed a copyright year / "established" date.
    assert _parse_posted_date("2018-11-06") is None
    assert _parse_posted_date(_iso(-500)) is None


def test_absent_or_unparseable_is_none():
    assert _parse_posted_date("") is None
    assert _parse_posted_date(None) is None
    assert _parse_posted_date("sometime last spring") is None
    assert _parse_posted_date(12345) is None  # non-str


def test_multiple_formats_parse():
    # A plausible recent date in each accepted format round-trips to a real date.
    d = datetime.now(timezone.utc).date() - timedelta(days=10)
    for text in (d.strftime("%Y-%m-%d"), d.strftime("%Y/%m/%d"),
                 d.strftime("%d/%m/%Y"), d.strftime("%d-%m-%Y")):
        assert _parse_posted_date(text) is not None, text
