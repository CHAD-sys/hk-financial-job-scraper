"""
Tests for the Seeker account HTTP surface (phase 2 of docs/PLAN_ACCOUNTS.md).

The crypto and storage are covered by test_auth_core.py and test_seekers_store.py.
What is unique to this layer, and what these tests pin, is the *observable
behaviour of the endpoints* — most of which is deliberately counter-intuitive:

  - registering an address that already exists must be INDISTINGUISHABLE from a
    successful registration, or the endpoint becomes an oracle for who has an
    account (PLAN_ACCOUNTS §5),
  - a filled honeypot must look like success for the same reason,
  - one failure message for every login failure, whatever the real cause,
  - rate limits key on the target EMAIL as well as the caller's IP, because in an
    inbox-bombing attempt the victim is the constant and the source IP is not,
  - a Saved Role resolves against jobs.db at read time and is never a stored copy,
  - deletion really deletes (ADR 0007).

The database fixtures are reused from test_single_origin so both files describe
the same app shape, and both stay hermetic — a stand-in jobs.db in tmp_path
rather than the real one.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from .support import make_app, make_bundle, make_jobs_db

GOOD = {"email": "seeker@example.com", "password": "correct-horse-battery", "display_name": "Ada"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import seekers_store

    db = tmp_path / "jobs.db"
    make_jobs_db(db)
    dist = tmp_path / "dist"
    make_bundle(dist)

    # Explicit override, so a test can never touch a real seekers.db. Still an
    # env var because the seeker store is a process-wide singleton — the one
    # piece of state create_app does not yet own.
    monkeypatch.setenv("SEEKERS_DB_PATH", str(tmp_path / "seekers.db"))
    # reset_store() has existed since the store was written, documented "for
    # tests and for a config reload", with zero callers: the tests deleted the
    # module from sys.modules and re-executed it instead, which also re-ran
    # auth.py's import-time Argon2 hash on every fixture.
    seekers_store.reset_store()

    # Cookies over http in the test client: Secure cookies would never be stored.
    return TestClient(make_app(db, dist, tmp_path, cookie_secure=False))


def _register(client, **over):
    return client.post("/api/auth/register", json={**GOOD, **over})


# ── Registration ──────────────────────────────────────────────────────────────

def test_register_creates_seeker_and_signs_them_in(client):
    r = _register(client)
    assert r.status_code == 201
    body = r.json()
    assert body["email"] == "seeker@example.com"
    assert body["email_verified"] is False
    assert client.cookies.get("finex_session")
    assert client.get("/api/auth/me").status_code == 200


def test_password_never_appears_in_any_response(client):
    r = _register(client)
    assert GOOD["password"] not in r.text
    assert "password" not in r.json()


def test_email_is_normalised(client):
    _register(client, email="SEEKER@Example.COM")
    assert client.get("/api/auth/me").json()["email"] == "seeker@example.com"


def test_registering_an_existing_address_is_indistinguishable_from_success(client):
    _register(client)
    client.post("/api/auth/logout")
    client.cookies.clear()

    r = _register(client, display_name="Impostor")
    # Same status and same shape as a real registration...
    assert r.status_code == 201
    assert r.json()["email"] == "seeker@example.com"
    # ...but no session was issued, which the real owner notices and an attacker
    # cannot observe from the response alone.
    assert client.get("/api/auth/me").status_code == 401


def test_honeypot_looks_like_success_but_creates_nothing(client):
    r = _register(client, website="http://spam.test")
    assert r.status_code == 201
    assert client.get("/api/auth/me").status_code == 401
    # The address is still free, proving no Seeker was created.
    assert _register(client).status_code == 201
    assert client.get("/api/auth/me").status_code == 200


def test_short_password_is_rejected(client):
    assert _register(client, password="short").status_code == 422


# ── Login ─────────────────────────────────────────────────────────────────────

def test_login_round_trip(client):
    _register(client)
    client.post("/api/auth/logout")
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"email": GOOD["email"], "password": GOOD["password"]})
    assert r.status_code == 200
    assert client.get("/api/auth/me").status_code == 200


def test_wrong_password_and_unknown_account_give_the_same_answer(client):
    _register(client)
    client.cookies.clear()
    wrong = client.post("/api/auth/login", json={"email": GOOD["email"], "password": "nope-nope-nope"})
    unknown = client.post("/api/auth/login",
                          json={"email": "nobody@example.com", "password": "nope-nope-nope"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"]


def test_login_rate_limit_trips_per_email(client):
    _register(client)
    client.cookies.clear()
    codes = [
        client.post("/api/auth/login",
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
    assert client.get("/api/auth/me").status_code == 401


def test_logout_is_idempotent(client):
    assert client.post("/api/auth/logout").status_code == 204
    _register(client)
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401


def test_a_garbage_cookie_is_anonymous_not_an_error(client):
    client.cookies.set("finex_session", "not-a-real-token")
    assert client.get("/api/auth/me").status_code == 401


# ── Saved Roles ───────────────────────────────────────────────────────────────

def test_saved_roles_require_sign_in(client):
    assert client.get("/api/me/saved").status_code == 401


def test_save_list_and_unsave(client):
    _register(client)
    assert client.get("/api/me/saved").json() == []

    assert client.post("/api/me/saved",
                       json={"source": "workday", "source_id": "J1"}).status_code == 204
    saved = client.get("/api/me/saved").json()
    assert len(saved) == 1
    # Resolved from jobs.db at read time — the title was never stored by us.
    assert saved[0]["title"] == "Credit Risk Analyst"
    assert saved[0]["company"] == "HSBC"

    assert client.delete("/api/me/saved/workday/J1").status_code == 204
    assert client.get("/api/me/saved").json() == []


def test_saving_twice_is_idempotent(client):
    _register(client)
    for _ in range(2):
        client.post("/api/me/saved", json={"source": "workday", "source_id": "J1"})
    assert len(client.get("/api/me/saved").json()) == 1


def test_a_reference_to_a_vanished_role_is_skipped_not_a_500(client):
    """A Role that has left jobs.db entirely must not break the whole list."""
    _register(client)
    client.post("/api/me/saved", json={"source": "workday", "source_id": "J1"})
    client.post("/api/me/saved", json={"source": "ghost", "source_id": "GONE"})
    saved = client.get("/api/me/saved").json()
    assert [s["source_id"] for s in saved] == ["J1"]


def test_merge_is_a_union_and_is_idempotent(client):
    """Decision 14: first sign-in lifts localStorage saves in, losing nothing."""
    _register(client)
    client.post("/api/me/saved", json={"source": "workday", "source_id": "J1"})

    body = {"roles": [{"source": "workday", "source_id": "J1"},
                      {"source": "jobsdb", "source_id": "X9"}]}
    first = client.post("/api/me/saved/merge", json=body).json()
    assert first["merged"] == 1, "already-saved role should not be double counted"

    second = client.post("/api/me/saved/merge", json=body).json()
    assert second["merged"] == 0, "merge must be idempotent"


# ── Deletion ──────────────────────────────────────────────────────────────────

def test_delete_account_really_deletes(client):
    _register(client)
    client.post("/api/me/saved", json={"source": "workday", "source_id": "J1"})

    assert client.delete("/api/me").status_code == 204
    assert client.get("/api/auth/me").status_code == 401
    # The address is free again, which a soft-delete would not permit.
    assert _register(client).status_code == 201
    # And the new account does not inherit the old one's saved roles.
    assert client.get("/api/me/saved").json() == []


def test_delete_requires_sign_in(client):
    assert client.delete("/api/me").status_code == 401


# ── The board stays public (ADR 0002) ─────────────────────────────────────────

def test_jobs_endpoints_are_unaffected_by_accounts(client):
    """Nothing is gated. An anonymous visitor sees exactly what they always did."""
    anon = client.get("/api/jobs")
    assert anon.status_code == 200
    row = anon.json()["jobs"][0]
    # The fields the deleted plan proposed gating are all still present to an
    # anonymous caller: the apply link, the title, the company, the salary keys.
    assert row["url"]
    assert row["title"] == "Credit Risk Analyst"
    assert row["company"] == "HSBC"
    assert "salary_estimated_min" in row
