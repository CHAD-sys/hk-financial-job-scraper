"""HTTP contract for the Alerts opt-in toggle and the unsubscribe link."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from alert_unsubscribe import AlertUnsubscribeToken

from .support import make_app, make_bundle, make_jobs_db

SEEKER = {
    "email": "seeker@example.com",
    "password": "correct-horse-battery",
    "display_name": "Ada",
}

UNSUBSCRIBE_SECRET = "test-unsubscribe-secret"


@pytest.fixture()
def alert_clients(tmp_path, monkeypatch):
    import seekers_store

    make_jobs_db(tmp_path / "jobs.db")
    monkeypatch.setenv("SEEKERS_DB_PATH", str(tmp_path / "seekers.db"))
    seekers_store.reset_store()
    dist = tmp_path / "dist"
    make_bundle(dist)

    def _app():
        return make_app(
            tmp_path / "jobs.db",
            dist,
            tmp_path,
            cookie_secure=False,
            alert_unsubscribe_secret=UNSUBSCRIBE_SECRET,
        )

    anonymous = TestClient(_app())
    signed_in = TestClient(_app())
    response = signed_in.post("/api/auth/register", json=SEEKER)
    assert response.status_code == 201
    return anonymous, signed_in


def test_alerts_default_to_opted_out(alert_clients):
    _, signed_in = alert_clients
    response = signed_in.get("/api/me/alerts")

    assert response.status_code == 200
    assert response.json() == {"opted_in": False}


def test_getting_alert_settings_requires_a_session(alert_clients):
    anonymous, _ = alert_clients
    assert anonymous.get("/api/me/alerts").status_code == 401


def test_setting_alert_settings_requires_a_session(alert_clients):
    anonymous, _ = alert_clients
    response = anonymous.put("/api/me/alerts", json={"opted_in": True})
    assert response.status_code == 401


def test_opt_in_round_trips(alert_clients):
    _, signed_in = alert_clients

    put_response = signed_in.put("/api/me/alerts", json={"opted_in": True})
    assert put_response.status_code == 200
    assert put_response.json() == {"opted_in": True}

    get_response = signed_in.get("/api/me/alerts")
    assert get_response.json() == {"opted_in": True}


def test_opt_out_round_trips(alert_clients):
    _, signed_in = alert_clients
    signed_in.put("/api/me/alerts", json={"opted_in": True})

    response = signed_in.put("/api/me/alerts", json={"opted_in": False})

    assert response.json() == {"opted_in": False}
    assert signed_in.get("/api/me/alerts").json() == {"opted_in": False}


def test_unsubscribe_link_opts_a_seeker_out_with_no_session(alert_clients):
    import seekers_store

    anonymous, signed_in = alert_clients
    signed_in.put("/api/me/alerts", json={"opted_in": True})

    me = signed_in.get("/api/auth/me").json()
    tokens = AlertUnsubscribeToken(UNSUBSCRIBE_SECRET)
    token = tokens.issue(me["id"])

    response = anonymous.post("/api/alerts/unsubscribe", json={"token": token})

    assert response.status_code == 204
    assert seekers_store.get_store().get_alert_opt_in(me["id"]) is False


def test_unsubscribe_cannot_opt_a_seeker_back_in(alert_clients):
    """The link can only turn Alerts off — consent to turn them on flows
    through PUT /api/me/alerts only (Q5: opt-in only, never assumed)."""
    import seekers_store

    _, signed_in = alert_clients
    signed_in.put("/api/me/alerts", json={"opted_in": False})
    me = signed_in.get("/api/auth/me").json()
    tokens = AlertUnsubscribeToken(UNSUBSCRIBE_SECRET)
    token = tokens.issue(me["id"])

    signed_in.post("/api/alerts/unsubscribe", json={"token": token})

    assert seekers_store.get_store().get_alert_opt_in(me["id"]) is False


def test_unsubscribe_with_a_garbage_token_is_a_harmless_no_op(alert_clients):
    anonymous, _ = alert_clients
    response = anonymous.post("/api/alerts/unsubscribe", json={"token": "not-a-real-token"})
    assert response.status_code == 204


def test_unsubscribe_with_a_token_for_an_unknown_seeker_is_a_harmless_no_op(alert_clients):
    anonymous, _ = alert_clients
    tokens = AlertUnsubscribeToken(UNSUBSCRIBE_SECRET)
    token = tokens.issue("00000000-0000-4000-8000-000000000000")

    response = anonymous.post("/api/alerts/unsubscribe", json={"token": token})

    assert response.status_code == 204
