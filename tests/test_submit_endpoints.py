"""Guardrails for the public recruiter Role-submission endpoint."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parent.parent / "webapp" / "backend"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBMISSIONS_DIR", str(tmp_path))
    monkeypatch.setenv("SUBMIT_RATE_LIMIT", "3")
    monkeypatch.syspath_prepend(str(BACKEND))
    for mod in ("main", "mailer"):
        sys.modules.pop(mod, None)
    main = importlib.import_module("main")

    sent: list[dict] = []

    def fake_send(subject, body, reply_to=None):
        sent.append({"subject": subject, "body": body, "reply_to": reply_to})
        return True

    monkeypatch.setattr(main, "send_mail", fake_send)
    result = TestClient(main.app)
    result.sent = sent  # type: ignore[attr-defined]
    result.queue_dir = tmp_path  # type: ignore[attr-defined]
    return result


def role(**over):
    body = {
        "contact_name": "Rec Ruiter",
        "contact_email": "rec@agency.com",
        "company": "Example Capital",
        "title": "VP, Credit Risk",
        "location": "Hong Kong",
        "employment_type": "Full-time",
        "salary_range": "HKD 80,000 - 110,000 / month",
        "description": "Own the credit risk book for APAC.",
        "apply_url": "https://example.com/apply",
        "website": "",
    }
    body.update(over)
    return body


def read_queue(client):
    path = client.queue_dir / "submitted_roles.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_role_is_queued_as_pending_and_emailed(client):
    response = client.post("/api/post-role", json=role())
    assert response.status_code == 200, response.text
    assert response.json() == {"ok": True}
    rows = read_queue(client)
    assert len(rows) == 1
    assert rows[0]["status"] == "pending"
    assert rows[0]["title"] == "VP, Credit Risk"
    assert "website" not in rows[0]
    assert client.sent[0]["reply_to"] == "rec@agency.com"


def test_honeypot_looks_successful_but_sends_nothing(client):
    response = client.post("/api/post-role", json=role(website="buy-now"))
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert read_queue(client) == []
    assert client.sent == []


def test_rate_limit_returns_429_after_the_cap(client):
    for _ in range(3):
        assert client.post("/api/post-role", json=role()).status_code == 200
    assert client.post("/api/post-role", json=role()).status_code == 429
    assert len(read_queue(client)) == 3


def test_unknown_employment_type_rejected(client):
    assert client.post("/api/post-role", json=role(employment_type="Freelance")).status_code == 422


@pytest.mark.parametrize("bad", ["javascript:alert(1)", "data:text/html,x", "mailto:a@b.c", "/relative"])
def test_non_http_apply_url_rejected(client, bad):
    assert client.post("/api/post-role", json=role(apply_url=bad)).status_code == 422


def test_newlines_in_title_never_reach_a_header(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBMISSIONS_DIR", str(tmp_path))
    monkeypatch.setenv("SMTP_USER", "sender@example.com")
    monkeypatch.setenv("SMTP_PASS", "app-password")
    monkeypatch.syspath_prepend(str(BACKEND))
    for mod in ("main", "mailer"):
        sys.modules.pop(mod, None)

    import mailer as mailer_mod
    main = importlib.import_module("main")
    captured: list = []

    class FakeSMTP:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def starttls(self): pass
        def login(self, *args): pass
        def send_message(self, message): captured.append(message)

    monkeypatch.setattr(mailer_mod.smtplib, "SMTP", FakeSMTP)
    response = TestClient(main.app).post(
        "/api/post-role", json=role(title="VP Risk\r\nBcc: victim@example.com")
    )
    assert response.status_code == 200
    assert len(captured) == 1
    message = captured[0]
    assert message["Bcc"] is None
    for header in ("Subject", "To", "From", "Reply-To"):
        value = message[header]
        if value is not None:
            assert "\r" not in str(value) and "\n" not in str(value)
    assert message["To"] == mailer_mod.SUBMISSION_RECIPIENT


def test_header_sanitiser_strips_crlf():
    sys.path.insert(0, str(BACKEND))
    sys.modules.pop("mailer", None)
    mailer = importlib.import_module("mailer")
    cleaned = mailer._header_safe("Subject\r\nBcc: evil@example.com")
    assert "\r" not in cleaned and "\n" not in cleaned


def test_submission_survives_smtp_failure(client, monkeypatch):
    import main
    monkeypatch.setattr(main, "send_mail", lambda *args, **kwargs: False)
    assert client.post("/api/post-role", json=role()).status_code == 200
    assert len(read_queue(client)) == 1


def test_500_only_when_both_persistence_and_mail_fail(client, monkeypatch):
    import main
    monkeypatch.setattr(main, "send_mail", lambda *args, **kwargs: False)
    monkeypatch.setattr(main, "_persist", lambda *args, **kwargs: False)
    assert client.post("/api/post-role", json=role()).status_code == 500


def test_cors_allows_post(client):
    import main
    for middleware in main.app.user_middleware:
        if "CORS" in str(middleware.cls):
            assert "POST" in middleware.kwargs["allow_methods"]
            break
    else:
        pytest.fail("CORS middleware not found")
