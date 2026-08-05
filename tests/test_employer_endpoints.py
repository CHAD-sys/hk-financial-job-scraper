"""
Tests for the Employer HTTP surface — the gate opened at the owner's explicit
2026-08-05 direction, reopening docs/adr/0001 rather than routing around it.

v1 is identity only (register/login/logout/me/delete), on its own store
(employers_store.py) and its own cookie (finex_employer_session), deliberately
separate from Seeker identity. What these tests pin:

  - an Employer and a Seeker session are independent — signing in as one does
    not touch the other, and both can be held in the same browser at once,
  - registering an already-used address is an honest 409 here, unlike
    Seeker registration's non-enumerable answer (there is no Employer mail
    path yet to notify the real owner instead — see main.py's employer_
    register() docstring for why that trade was made deliberately),
  - one failure message for every login failure, same reasoning as Seeker login,
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


def test_jobs_endpoints_are_unaffected_by_employer_accounts(client):
    """Nothing is gated. Mirrors the Seeker-side ADR 0002 test."""
    anon = client.get("/api/jobs")
    assert anon.status_code == 200
    assert anon.json()["jobs"][0]["title"] == "Credit Risk Analyst"
