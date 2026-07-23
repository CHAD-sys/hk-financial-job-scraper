"""
Tests for hk_jobs/posts/extractor.py.

_call_deepseek is the single mockable seam — no real network call is made.
"""

import json

import httpx
import pytest

from hk_jobs.posts.extractor import (
    ANTHROPIC_MODEL,
    ExtractorAuthError,
    _call_haiku,
    extract_post,
    extract_post_haiku,
)


def _canned_reply(**overrides):
    data = {
        "is_job_post": True,
        "confidence": 0.9,
        "title": "Assistant Relationship Manager",
        "employer_named": False,
        "employer_hint": "international private bank",
        "location": "Hong Kong",
        "hk_plausible": True,
        "seniority": "mid",
        "salary_min": None,
        "salary_max": None,
        "salary_currency": None,
        "skills": ["private banking", "relationship management"],
    }
    data.update(overrides)
    return json.dumps(data)


def test_empty_post_returns_none():
    assert extract_post("", api_key="fake") is None
    assert extract_post("   ", api_key="fake") is None


def test_missing_key_raises_auth_error(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(ExtractorAuthError):
        extract_post("some post text")


def test_successful_extraction(monkeypatch):
    monkeypatch.setattr(
        "hk_jobs.posts.extractor._call_deepseek", lambda text, api_key: _canned_reply()
    )
    result = extract_post("Hiring an ARM in HK", api_key="fake")
    assert result is not None
    assert result.is_job_post is True
    assert result.title == "Assistant Relationship Manager"
    assert result.employer_named is False
    assert result.hk_plausible is True
    assert result.confidence == 0.9
    assert result.skills == ["private banking", "relationship management"]


def test_non_job_post_nulls_other_fields(monkeypatch):
    reply = _canned_reply(is_job_post=False, title="Some Title", location="Hong Kong")
    monkeypatch.setattr("hk_jobs.posts.extractor._call_deepseek", lambda text, api_key: reply)
    result = extract_post("just a congratulations post", api_key="fake")
    assert result.is_job_post is False
    assert result.title is None
    assert result.location is None
    assert result.hk_plausible is False
    assert result.skills == []


def test_confidence_is_clamped(monkeypatch):
    reply = _canned_reply(confidence=1.5)
    monkeypatch.setattr("hk_jobs.posts.extractor._call_deepseek", lambda text, api_key: reply)
    result = extract_post("x", api_key="fake")
    assert result.confidence == 1.0


def test_markdown_fenced_json_is_stripped(monkeypatch):
    fenced = "```json\n" + _canned_reply() + "\n```"
    monkeypatch.setattr("hk_jobs.posts.extractor._call_deepseek", lambda text, api_key: fenced)
    result = extract_post("x", api_key="fake")
    assert result is not None
    assert result.title == "Assistant Relationship Manager"


def test_malformed_json_retries_then_returns_none(monkeypatch):
    calls = {"n": 0}

    def _bad_call(text, api_key):
        calls["n"] += 1
        return "not valid json{{{"

    monkeypatch.setattr("hk_jobs.posts.extractor._call_deepseek", _bad_call)
    result = extract_post("x", api_key="fake")
    assert result is None
    assert calls["n"] == 2  # low retry cap, matches vendor_client.py


def test_auth_error_from_call_is_not_retried(monkeypatch):
    calls = {"n": 0}

    def _auth_fail(text, api_key):
        calls["n"] += 1
        resp = httpx.Response(401, request=httpx.Request("POST", "https://x"))
        raise httpx.HTTPStatusError("unauthorized", request=resp.request, response=resp)

    monkeypatch.setattr("hk_jobs.posts.extractor._call_deepseek", _auth_fail)
    with pytest.raises(ExtractorAuthError):
        extract_post("x", api_key="fake")
    assert calls["n"] == 1


def test_transient_http_error_retries_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def _flaky(text, api_key):
        calls["n"] += 1
        if calls["n"] == 1:
            resp = httpx.Response(500, request=httpx.Request("POST", "https://x"))
            raise httpx.HTTPStatusError("server error", request=resp.request, response=resp)
        return _canned_reply()

    monkeypatch.setattr("hk_jobs.posts.extractor._call_deepseek", _flaky)
    result = extract_post("x", api_key="fake")
    assert result is not None
    assert calls["n"] == 2


# ── extract_post_haiku ──────────────────────────────────────────────────────

def test_haiku_missing_key_raises_auth_error(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ExtractorAuthError):
        extract_post_haiku("some post text")


def test_haiku_successful_extraction(monkeypatch):
    """_call_haiku returns the model's continuation AFTER the '{' prefill —
    _call_haiku itself re-attaches it, so the seam here returns raw model text."""
    reply_after_prefill = _canned_reply()[1:]  # strip the leading '{' the prefill already covers
    monkeypatch.setattr(
        "hk_jobs.posts.extractor._call_haiku", lambda text, api_key: "{" + reply_after_prefill
    )
    result = extract_post_haiku("Hiring an ARM in HK", api_key="fake")
    assert result is not None
    assert result.title == "Assistant Relationship Manager"
    assert result.is_job_post is True


def test_call_haiku_prefills_and_reattaches_brace(monkeypatch):
    captured = {}

    class _FakeResponse:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"content": [{"text": '"is_job_post": false}'}]}

    def _mock_post(url, headers, json, timeout):
        captured["url"] = url
        captured["json"] = json
        return _FakeResponse()

    monkeypatch.setattr("hk_jobs.posts.extractor.httpx.post", _mock_post)
    text = _call_haiku("x", api_key="fake")
    assert text == '{"is_job_post": false}'
    assert captured["json"]["messages"][-1] == {"role": "assistant", "content": "{"}
    assert captured["json"]["model"] == ANTHROPIC_MODEL
    assert "anthropic.com" in captured["url"]


def test_haiku_auth_error_on_401(monkeypatch):
    class _FakeResponse:
        status_code = 401
        request = httpx.Request("POST", "https://x")

        def raise_for_status(self):
            pass

    monkeypatch.setattr(
        "hk_jobs.posts.extractor.httpx.post",
        lambda url, headers, json, timeout: _FakeResponse(),
    )
    with pytest.raises(ExtractorAuthError):
        extract_post_haiku("x", api_key="fake")
