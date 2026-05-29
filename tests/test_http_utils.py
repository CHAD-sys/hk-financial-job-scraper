"""Tests for hk_jobs/http_utils.py — retry-with-backoff helper."""

import httpx
import pytest

from hk_jobs.http_utils import with_retry

_REQ = httpx.Request("GET", "http://example.com")


# ── success path ──────────────────────────────────────────────────────────────

def test_returns_value_on_first_attempt():
    assert with_retry(lambda: "ok", backoff_base=0) == "ok"


def test_returns_none_when_fn_returns_none():
    assert with_retry(lambda: None, backoff_base=0) is None


# ── timeout / network retries ─────────────────────────────────────────────────

def test_retries_on_timeout_and_succeeds():
    calls = []

    def fn():
        calls.append(1)
        if len(calls) < 3:
            raise httpx.TimeoutException("slow", request=_REQ)
        return "ok"

    assert with_retry(fn, max_attempts=3, backoff_base=0) == "ok"
    assert len(calls) == 3


def test_retries_on_network_error():
    calls = []

    def fn():
        calls.append(1)
        if len(calls) < 2:
            raise httpx.ConnectError("refused", request=_REQ)
        return "done"

    assert with_retry(fn, max_attempts=3, backoff_base=0) == "done"
    assert len(calls) == 2


def test_raises_after_max_attempts_timeout():
    calls = []

    def fn():
        calls.append(1)
        raise httpx.TimeoutException("always", request=_REQ)

    with pytest.raises(httpx.TimeoutException):
        with_retry(fn, max_attempts=3, backoff_base=0)
    assert len(calls) == 3


# ── HTTP status retries ───────────────────────────────────────────────────────

def test_retries_on_429():
    resp = httpx.Response(429, request=_REQ)
    calls = []

    def fn():
        calls.append(1)
        if len(calls) < 3:
            raise httpx.HTTPStatusError("rate limited", request=_REQ, response=resp)
        return "ok"

    assert with_retry(fn, max_attempts=3, backoff_base=0) == "ok"
    assert len(calls) == 3


def test_retries_on_503():
    resp = httpx.Response(503, request=_REQ)
    calls = []

    def fn():
        calls.append(1)
        if len(calls) < 2:
            raise httpx.HTTPStatusError("server error", request=_REQ, response=resp)
        return "ok"

    assert with_retry(fn, max_attempts=3, backoff_base=0) == "ok"
    assert len(calls) == 2


def test_does_not_retry_404():
    resp = httpx.Response(404, request=_REQ)
    calls = []

    def fn():
        calls.append(1)
        raise httpx.HTTPStatusError("not found", request=_REQ, response=resp)

    with pytest.raises(httpx.HTTPStatusError):
        with_retry(fn, max_attempts=3, backoff_base=0)
    assert len(calls) == 1  # no retry


def test_does_not_retry_403():
    resp = httpx.Response(403, request=_REQ)
    calls = []

    def fn():
        calls.append(1)
        raise httpx.HTTPStatusError("forbidden", request=_REQ, response=resp)

    with pytest.raises(httpx.HTTPStatusError):
        with_retry(fn, max_attempts=3, backoff_base=0)
    assert len(calls) == 1


def test_raises_after_max_attempts_429():
    resp = httpx.Response(429, request=_REQ)
    calls = []

    def fn():
        calls.append(1)
        raise httpx.HTTPStatusError("always rate-limited", request=_REQ, response=resp)

    with pytest.raises(httpx.HTTPStatusError):
        with_retry(fn, max_attempts=3, backoff_base=0)
    assert len(calls) == 3
