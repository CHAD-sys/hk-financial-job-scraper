"""
Tests for the two write endpoints — /api/contact and /api/post-role.

These are the only POSTs in the app and the only public write surface, so the
tests here are about the guardrails rather than the happy path: honeypot,
rate limiting, field caps, enum validation, header injection, and the promise
that a submission is never lost when SMTP is down.

No real email is ever sent: mailer.send_mail is monkeypatched in every test.
"""

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
    """A fresh app per test, writing its JSONL queue into tmp_path."""
    monkeypatch.setenv("SUBMISSIONS_DIR", str(tmp_path))
    monkeypatch.setenv("SUBMIT_RATE_LIMIT", "3")
    monkeypatch.syspath_prepend(str(BACKEND))

    # Reimport so module-level config (SUBMISSIONS_DIR, _RATE_LIMIT) and the
    # in-memory rate log are rebuilt for each test.
    for mod in ("main", "mailer"):
        sys.modules.pop(mod, None)
    main = importlib.import_module("main")

    sent: list[dict] = []

    def fake_send(subject, body, reply_to=None):
        sent.append({"subject": subject, "body": body, "reply_to": reply_to})
        return True

    monkeypatch.setattr(main, "send_mail", fake_send)

    c = TestClient(main.app)
    c.sent = sent          # type: ignore[attr-defined]
    c.queue_dir = tmp_path  # type: ignore[attr-defined]
    return c


def enquiry(**over):
    body = {
        "name": "Jane Doe",
        "email": "jane@example.com",
        "career_stage": "8–15 years",
        "message": "Weighing a move from sell-side to a family office.",
        "website": "",
    }
    body.update(over)
    return body


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


def read_queue(client, name):
    path = client.queue_dir / f"{name}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


# ── Happy path ────────────────────────────────────────────────────────────────

def test_enquiry_is_queued_and_emailed(client):
    r = client.post("/api/contact", json=enquiry())
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}

    rows = read_queue(client, "enquiries")
    assert len(rows) == 1
    assert rows[0]["email"] == "jane@example.com"
    assert "received_at" in rows[0]
    # The honeypot value must never be persisted.
    assert "website" not in rows[0]

    assert len(client.sent) == 1
    assert client.sent[0]["reply_to"] == "jane@example.com"


def test_role_is_queued_as_pending(client):
    r = client.post("/api/post-role", json=role())
    assert r.status_code == 200, r.text

    rows = read_queue(client, "submitted_roles")
    assert len(rows) == 1
    # Nothing reaches the board without a human; status is pending at rest.
    assert rows[0]["status"] == "pending"
    assert rows[0]["title"] == "VP, Credit Risk"


# ── Honeypot ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "path,payload,queue",
    [
        ("/api/contact", enquiry(website="http://spam.example"), "enquiries"),
        ("/api/post-role", role(website="buy-now"), "submitted_roles"),
    ],
)
def test_honeypot_looks_successful_but_sends_nothing(client, path, payload, queue):
    r = client.post(path, json=payload)
    # Same 200 a human gets — never tell the bot it was caught.
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert read_queue(client, queue) == []
    assert client.sent == []


# ── Rate limiting ─────────────────────────────────────────────────────────────

def test_rate_limit_returns_429_after_the_cap(client):
    for i in range(3):
        assert client.post("/api/contact", json=enquiry()).status_code == 200, f"call {i}"

    r = client.post("/api/contact", json=enquiry())
    assert r.status_code == 429
    assert len(read_queue(client, "enquiries")) == 3


def test_rate_limits_are_per_endpoint(client):
    for _ in range(3):
        client.post("/api/contact", json=enquiry())
    # The role endpoint has its own bucket, so it is still open.
    assert client.post("/api/post-role", json=role()).status_code == 200


# ── Validation ────────────────────────────────────────────────────────────────

def test_unknown_career_stage_rejected(client):
    r = client.post("/api/contact", json=enquiry(career_stage="Intern"))
    assert r.status_code == 422
    assert read_queue(client, "enquiries") == []


def test_unknown_employment_type_rejected(client):
    assert client.post("/api/post-role", json=role(employment_type="Freelance")).status_code == 422


def test_oversized_message_rejected_not_truncated(client):
    r = client.post("/api/contact", json=enquiry(message="x" * 5001))
    assert r.status_code == 422
    assert read_queue(client, "enquiries") == []


def test_malformed_email_rejected(client):
    assert client.post("/api/contact", json=enquiry(email="not-an-email")).status_code == 422


@pytest.mark.parametrize("bad", ["javascript:alert(1)", "data:text/html,x", "mailto:a@b.c", "/relative"])
def test_non_http_apply_url_rejected(client, bad):
    assert client.post("/api/post-role", json=role(apply_url=bad)).status_code == 422


# ── Header injection ──────────────────────────────────────────────────────────

def test_newlines_in_name_never_reach_a_header(tmp_path, monkeypatch):
    """
    End-to-end: real send_mail, only the SMTP socket faked.

    Mocking send_mail here would mock out the sanitiser itself and prove
    nothing — so this test drives the genuine mailer and inspects the
    EmailMessage that would have gone on the wire.
    """
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
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def starttls(self): pass
        def login(self, *a): pass
        def send_message(self, msg): captured.append(msg)

    monkeypatch.setattr(mailer_mod.smtplib, "SMTP", FakeSMTP)

    c = TestClient(main.app)
    r = c.post("/api/contact", json=enquiry(name="Jane\r\nBcc: victim@example.com"))
    assert r.status_code == 200
    assert len(captured) == 1

    msg = captured[0]
    assert msg["Bcc"] is None, "injected header must not exist"
    for header in ("Subject", "To", "From", "Reply-To"):
        value = msg[header]
        if value is not None:
            assert "\r" not in str(value) and "\n" not in str(value), f"{header} carries CRLF"
    # And the recipient is still ours, not anything the request supplied.
    assert msg["To"] == mailer_mod.RECIPIENT


def test_header_sanitiser_strips_crlf():
    """_header_safe is the last line of defence; test it directly."""
    sys.path.insert(0, str(BACKEND))
    sys.modules.pop("mailer", None)
    mailer = importlib.import_module("mailer")

    out = mailer._header_safe("Subject\r\nBcc: evil@example.com")
    assert "\r" not in out and "\n" not in out
    assert out.startswith("Subject")


def test_recipient_is_not_taken_from_the_request(client):
    """An attacker-supplied 'to' must be ignored, not honoured."""
    payload = enquiry()
    payload["to"] = "attacker@example.com"
    r = client.post("/api/contact", json=payload)
    assert r.status_code == 200
    assert "attacker@example.com" not in json.dumps(read_queue(client, "enquiries"))


# ── Durability ────────────────────────────────────────────────────────────────

def test_submission_survives_smtp_failure(client, monkeypatch):
    """Mail is best-effort; the JSONL queue is the source of truth."""
    import main

    monkeypatch.setattr(main, "send_mail", lambda *a, **k: False)

    r = client.post("/api/contact", json=enquiry())
    assert r.status_code == 200          # the visitor is not punished for our outage
    assert len(read_queue(client, "enquiries")) == 1


def test_500_only_when_both_persistence_and_mail_fail(client, monkeypatch):
    import main

    monkeypatch.setattr(main, "send_mail", lambda *a, **k: False)
    monkeypatch.setattr(main, "_persist", lambda *a, **k: False)

    assert client.post("/api/contact", json=enquiry()).status_code == 500


# ── Read endpoints still work ─────────────────────────────────────────────────

def test_cors_allows_post(client):
    """Without POST in allow_methods the browser blocks both forms outright."""
    import main

    for mw in main.app.user_middleware:
        if "CORS" in str(mw.cls):
            assert "POST" in mw.kwargs["allow_methods"]
            break
    else:
        pytest.fail("CORS middleware not found")
