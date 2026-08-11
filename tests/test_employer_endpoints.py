"""
Tests for the Employer HTTP surface — the gate opened at the owner's explicit
2026-08-05 direction, reopening docs/adr/0001 rather than routing around it.

Phase 1 was identity only (register/login/logout/me/delete). Phase 2 (this
file's later sections) adds email verification, password reset and Google
sign-in, each on its own store (employers_store.py) and its own cookie
(finex_employer_session), deliberately separate from Seeker identity. What
these tests pin:

  - an Employer and a Seeker session are independent — signing in as one does
    not touch the other, and both can be held in the same browser at once,
  - registering an already-used address is an honest 409 here, unlike
    Seeker registration's non-enumerable answer (there is no Employer mail
    path yet to notify the real owner instead — see main.py's employer_
    register() docstring for why that trade was made deliberately),
  - one failure message for every login failure, same reasoning as Seeker login,
  - forgot-password DOES answer the same way regardless of whether the address
    has an account — the opposite trade from register, made deliberately (see
    employer_forgot_password()'s docstring for why),
  - Google sign-in can recognise or link an existing Employer, but never
    creates one — auth.link_or_create_employer has no create_if_missing
    escape hatch, because company_name has no Google equivalent,
  - deletion really deletes.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from .support import make_app, make_bundle, make_jobs_db

GOOD = {
    "email": "recruiter@example.com",
    "password": "correct-horse-battery",
    "company_name": "Acme Capital",
    "contact_name": "Jamie Lee",
}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import employers_store
    import seekers_store

    db = tmp_path / "jobs.db"
    make_jobs_db(db)
    dist = tmp_path / "dist"
    make_bundle(dist)

    monkeypatch.setenv("SEEKERS_DB_PATH", str(tmp_path / "seekers.db"))
    monkeypatch.setenv("EMPLOYERS_DB_PATH", str(tmp_path / "employers.db"))
    seekers_store.reset_store()
    employers_store.reset_store()

    return TestClient(make_app(db, dist, tmp_path, cookie_secure=False))


def _register(client, **over):
    return client.post("/api/employer/register", json={**GOOD, **over})


# ── Registration ──────────────────────────────────────────────────────────────

def test_register_creates_employer_and_signs_them_in(client):
    r = _register(client)
    assert r.status_code == 201
    body = r.json()
    assert body["email"] == "recruiter@example.com"
    assert body["company_name"] == "Acme Capital"
    assert client.cookies.get("finex_employer_session")
    assert client.get("/api/employer/me").status_code == 200


def test_password_never_appears_in_any_response(client):
    r = _register(client)
    assert GOOD["password"] not in r.text
    assert "password" not in r.json()


def test_email_is_normalised(client):
    _register(client, email="RECRUITER@Example.COM")
    assert client.get("/api/employer/me").json()["email"] == "recruiter@example.com"


def test_registering_an_existing_address_is_a_real_409(client):
    """Unlike Seeker registration, this is honest — there is no Employer mail
    path yet to warn the real owner instead of leaving a silent dead end."""
    _register(client)
    client.post("/api/employer/logout")
    client.cookies.clear()

    r = _register(client, contact_name="Impostor")
    assert r.status_code == 409
    assert client.get("/api/employer/me").status_code == 401


def test_honeypot_looks_like_success_but_creates_nothing(client):
    r = _register(client, website="http://spam.test")
    assert r.status_code == 201
    assert client.get("/api/employer/me").status_code == 401
    # The address is still free, proving no Employer was created.
    assert _register(client).status_code == 201


def test_short_password_is_rejected(client):
    assert _register(client, password="short").status_code == 422


def test_registration_rate_limit_trips_per_email(client):
    codes = [
        client.post("/api/employer/register", json={
            **GOOD, "email": GOOD["email"], "contact_name": f"Try {i}",
        }).status_code
        for i in range(6)
    ]
    assert 429 in codes, "per-email registration limiter never engaged"


# ── Login ─────────────────────────────────────────────────────────────────────

def test_login_round_trip(client):
    _register(client)
    client.post("/api/employer/logout")
    client.cookies.clear()
    r = client.post("/api/employer/login", json={"email": GOOD["email"], "password": GOOD["password"]})
    assert r.status_code == 200
    assert client.get("/api/employer/me").status_code == 200


def test_wrong_password_and_unknown_account_give_the_same_answer(client):
    _register(client)
    client.cookies.clear()
    wrong = client.post("/api/employer/login",
                        json={"email": GOOD["email"], "password": "nope-nope-nope"})
    unknown = client.post("/api/employer/login",
                          json={"email": "nobody@example.com", "password": "nope-nope-nope"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"]


def test_login_rate_limit_trips_per_email(client):
    _register(client)
    client.cookies.clear()
    codes = [
        client.post("/api/employer/login",
                    json={"email": GOOD["email"], "password": "wrong-password-here"}).status_code
        for _ in range(12)
    ]
    assert 429 in codes, "per-email login limiter never engaged"


# ── Session ───────────────────────────────────────────────────────────────────

def test_session_cookie_is_httponly_and_lax(client):
    r = _register(client)
    raw = r.headers["set-cookie"].lower()
    assert "httponly" in raw
    assert "samesite=lax" in raw


def test_me_is_401_when_anonymous(client):
    assert client.get("/api/employer/me").status_code == 401


def test_logout_is_idempotent(client):
    assert client.post("/api/employer/logout").status_code == 204
    _register(client)
    assert client.post("/api/employer/logout").status_code == 204
    assert client.get("/api/employer/me").status_code == 401


def test_a_garbage_cookie_is_anonymous_not_an_error(client):
    client.cookies.set("finex_employer_session", "not-a-real-token")
    assert client.get("/api/employer/me").status_code == 401


# ── Deletion ──────────────────────────────────────────────────────────────────

def test_delete_account_really_deletes(client):
    _register(client)
    assert client.delete("/api/employer/me").status_code == 204
    assert client.get("/api/employer/me").status_code == 401
    # The address is free again.
    assert _register(client).status_code == 201


def test_delete_requires_sign_in(client):
    assert client.delete("/api/employer/me").status_code == 401


# ── Independence from Seeker identity ──────────────────────────────────────────

def test_employer_and_seeker_sessions_are_independent(client):
    """Separate stores, separate cookies: a browser can hold both at once, and
    neither endpoint family can read the other's session."""
    client.post("/api/auth/register", json={
        "email": "seeker@example.com", "password": "correct-horse-battery", "display_name": "Ada",
    })
    _register(client)

    assert client.cookies.get("finex_session")
    assert client.cookies.get("finex_employer_session")
    assert client.get("/api/auth/me").status_code == 200
    assert client.get("/api/employer/me").status_code == 200

    client.post("/api/auth/logout")
    # Signing a Seeker out must not touch the Employer session sharing the jar.
    assert client.get("/api/employer/me").status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_employer_accounts_do_not_bypass_the_research_scope(client):
    anon = client.get("/api/jobs", params={"search": "credit risk"})
    assert anon.status_code == 200
    assert client.get("/api/jobs").status_code == 422
    assert anon.json()["jobs"][0]["title"] == "Credit Risk Analyst"


# ── Email verification ───────────────────────────────────────────────────────
#
# Same shape as test_auth_endpoints.py's Seeker section, and the same reason
# it exists at all: employers_store.py's own module docstring warns that an
# email flow shipped without the endpoint that consumes it is exactly the bug
# this repo's audit found once already.

def _sender(client):
    return client.app.state.sender


def _token_from(body: str) -> str:
    return body.split("token=", 1)[1].split()[0]


def test_registering_emails_a_verification_link(client):
    _register(client)
    sent = _sender(client).sent
    assert [m.to for m in sent] == [GOOD["email"]]
    assert "Confirm" in sent[0].subject
    assert "/employer/verify?token=" in sent[0].body


def test_registration_succeeds_even_when_mail_cannot_be_delivered(client):
    _sender(client).delivers = False
    assert _register(client).status_code == 201
    assert client.get("/api/employer/me").status_code == 200


def test_verify_email_marks_employer_verified(client):
    _register(client)
    assert client.get("/api/employer/me").json()["email_verified"] is False

    token = _token_from(_sender(client).sent[-1].body)
    r = client.post("/api/employer/auth/verify-email", json={"token": token})
    assert r.status_code == 200
    assert r.json()["email_verified"] is True
    assert client.get("/api/employer/me").json()["email_verified"] is True


def test_verify_email_rejects_an_unknown_token(client):
    r = client.post("/api/employer/auth/verify-email", json={"token": "not-a-real-token"})
    assert r.status_code == 400


def test_verify_token_is_single_use(client):
    _register(client)
    token = _token_from(_sender(client).sent[-1].body)
    assert client.post("/api/employer/auth/verify-email", json={"token": token}).status_code == 200
    assert client.post("/api/employer/auth/verify-email", json={"token": token}).status_code == 400


def test_verify_email_does_not_require_being_signed_in(client):
    """The token itself is the credential — same reasoning as Seeker's
    verify_email(), same test."""
    _register(client)
    token = _token_from(_sender(client).sent[-1].body)
    client.post("/api/employer/logout")
    client.cookies.clear()
    assert client.post("/api/employer/auth/verify-email", json={"token": token}).status_code == 200


# ── Password reset ───────────────────────────────────────────────────────────

def test_forgot_password_answers_the_same_whether_or_not_the_account_exists(client):
    """Unlike register's honest 409, this one is non-enumerable — the opposite
    trade, made deliberately (employer_forgot_password()'s docstring)."""
    _register(client)
    known = client.post("/api/employer/auth/forgot-password", json={"email": GOOD["email"]})
    unknown = client.post("/api/employer/auth/forgot-password",
                          json={"email": "nobody@example.com"})
    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json() == {"ok": True}


def test_forgot_password_emails_only_a_real_account(client):
    _register(client)
    _sender(client).sent.clear()
    client.post("/api/employer/auth/forgot-password", json={"email": "nobody@example.com"})
    assert _sender(client).sent == []

    client.post("/api/employer/auth/forgot-password", json={"email": GOOD["email"]})
    sent = _sender(client).sent
    assert [m.to for m in sent] == [GOOD["email"]]
    assert "/employer/reset-password?token=" in sent[0].body


def test_reset_password_signs_back_in_and_revokes_other_sessions(client):
    _register(client)
    old_cookie = client.cookies.get("finex_employer_session")

    client.post("/api/employer/auth/forgot-password", json={"email": GOOD["email"]})
    token = _token_from(_sender(client).sent[-1].body)

    r = client.post("/api/employer/auth/reset-password",
                    json={"token": token, "password": "new-correct-horse-2"})
    assert r.status_code == 200
    assert client.get("/api/employer/me").status_code == 200

    stale = TestClient(client.app)
    stale.cookies.set("finex_employer_session", old_cookie)
    assert stale.get("/api/employer/me").status_code == 401

    fresh = TestClient(client.app)
    old_login = fresh.post("/api/employer/login",
                           json={"email": GOOD["email"], "password": GOOD["password"]})
    assert old_login.status_code == 401
    new_login = fresh.post("/api/employer/login",
                           json={"email": GOOD["email"], "password": "new-correct-horse-2"})
    assert new_login.status_code == 200


def test_reset_token_is_single_use(client):
    _register(client)
    client.post("/api/employer/auth/forgot-password", json={"email": GOOD["email"]})
    token = _token_from(_sender(client).sent[-1].body)

    first = client.post("/api/employer/auth/reset-password",
                        json={"token": token, "password": "new-correct-horse-3"})
    assert first.status_code == 200
    second = client.post("/api/employer/auth/reset-password",
                         json={"token": token, "password": "another-password-4"})
    assert second.status_code == 400


def test_reset_password_rejects_an_unknown_token(client):
    r = client.post("/api/employer/auth/reset-password",
                    json={"token": "not-a-real-token", "password": "whatever-password"})
    assert r.status_code == 400


# ── Google OAuth ──────────────────────────────────────────────────────────────
#
# Same reach as test_auth_endpoints.py's Google section: what's testable
# without a real Google Cloud project is that the code degrades cleanly with
# no credentials, that CSRF state is actually checked, and that it uses its
# OWN state cookie / redirect path — separate from the Seeker flow.

def test_employer_google_start_redirects_to_signin_when_not_configured(client, monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    r = client.get("/api/employer/auth/google", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert "/employer/signin?error=google_unavailable" in r.headers["location"]
    assert "google_employer_oauth_state" not in client.cookies


def test_employer_google_start_redirects_to_google_when_configured(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-client-secret")
    r = client.get("/api/employer/auth/google", follow_redirects=False)
    assert r.status_code in (302, 307)
    location = r.headers["location"]
    assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client_id=test-client-id" in location
    callback_path_present = (
        "employer%2Fauth%2Fgoogle%2Fcallback" in location
        or "employer/auth/google/callback" in location
    )
    assert callback_path_present
    assert client.cookies.get("google_employer_oauth_state")


def test_employer_google_state_cookie_is_independent_from_seeker(client, monkeypatch):
    """Two separate cookies, two separate paths — a Seeker Google attempt in
    the same browser must not satisfy an Employer callback's CSRF check."""
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-client-secret")
    client.get("/api/auth/google", follow_redirects=False)
    assert client.cookies.get("google_oauth_state")
    assert "google_employer_oauth_state" not in client.cookies


def test_employer_google_callback_rejects_missing_state(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-client-secret")
    r = client.get("/api/employer/auth/google/callback?code=abc", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert "/employer/signin?error=google_failed" in r.headers["location"]


def test_employer_google_callback_rejects_mismatched_state(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-client-secret")
    client.get("/api/employer/auth/google", follow_redirects=False)  # mints a real state cookie
    r = client.get(
        "/api/employer/auth/google/callback?code=abc&state=not-the-real-state",
        follow_redirects=False,
    )
    assert r.status_code in (302, 307)
    assert "/employer/signin?error=google_failed" in r.headers["location"]
    assert client.get("/api/employer/me").status_code == 401


def test_employer_google_callback_surfaces_provider_error(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-client-secret")
    r = client.get("/api/employer/auth/google/callback?error=access_denied", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert "/employer/signin?error=google_failed" in r.headers["location"]
