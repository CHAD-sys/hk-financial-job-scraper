"""HTTP contract for discovery capture and the Roles-for-you feed."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from .support import enrichment, job, make_app, make_bundle, make_jobs_db

SEEKER = {
    "email": "seeker@example.com",
    "password": "correct-horse-battery",
    "display_name": "Ada",
}


@pytest.fixture()
def recommendation_db(tmp_path):
    path = tmp_path / "jobs.db"
    make_jobs_db(
        path,
        jobs=[
            job(
                source="workday",
                source_id="SAVED",
                company="HSBC",
                title="Credit Risk Analyst",
                posted_at="2026-08-07T00:00:00+00:00",
            ),
            job(
                source="workday",
                source_id="RISK",
                company="Hang Seng Bank",
                title="Senior Credit Risk Manager",
                posted_at="2026-08-07T00:00:00+00:00",
            ),
            job(
                source="eightfold",
                source_id="ACTUARY",
                company="AIA",
                title="Actuarial Manager",
                posted_at="2026-08-06T00:00:00+00:00",
            ),
        ],
        enrichments=[
            enrichment(
                source="workday",
                source_id="SAVED",
                seniority="mid",
                required_skills='["credit risk"]',
            ),
            enrichment(
                source="workday",
                source_id="RISK",
                seniority="mid",
                required_skills='["credit risk"]',
            ),
            enrichment(
                source="eightfold",
                source_id="ACTUARY",
                seniority="senior",
                required_skills='["actuarial modelling"]',
            ),
        ],
    )
    return path


@pytest.fixture()
def recommendation_clients(recommendation_db, tmp_path, monkeypatch):
    import seekers_store

    monkeypatch.setenv("SEEKERS_DB_PATH", str(tmp_path / "seekers.db"))
    seekers_store.reset_store()
    dist = tmp_path / "dist"
    make_bundle(dist)

    anonymous = TestClient(
        make_app(recommendation_db, dist, tmp_path, cookie_secure=False)
    )
    signed_in = TestClient(
        make_app(recommendation_db, dist, tmp_path, cookie_secure=False)
    )
    response = signed_in.post("/api/auth/register", json=SEEKER)
    assert response.status_code == 201
    return anonymous, signed_in


def test_anonymous_feed_is_market_based_and_writes_no_seeker_data(
    recommendation_clients,
):
    import seekers_store

    anonymous, _ = recommendation_clients
    response = anonymous.get("/api/recommendations", params={"page_size": 2})

    assert response.status_code == 200
    body = response.json()
    assert body["personalized"] is False
    assert body["model_version"] == "signals-v1"
    assert len(body["items"]) == 2
    conn = seekers_store.get_store()._conn()
    assert conn.execute("SELECT COUNT(*) FROM recommendation_impressions").fetchone()[0] == 0


def test_discovery_capture_requires_a_seeker_session(recommendation_clients):
    anonymous, _ = recommendation_clients
    response = anonymous.post(
        "/api/me/discovery",
        json={
            "search_query": "credit risk",
            "filters": {"sectors": ["Banking"]},
            "result_count": 2,
        },
    )
    assert response.status_code == 401


def test_discovery_capture_persists_the_settled_filter_state(recommendation_clients):
    import seekers_store

    _, signed_in = recommendation_clients
    response = signed_in.post(
        "/api/me/discovery",
        json={
            "search_query": "Credit Risk",
            "filters": {
                "tier": "all",
                "sectors": ["Banking"],
                "seniority": ["mid"],
                "is_new": False,
            },
            "result_count": 2,
        },
    )
    assert response.status_code == 204

    seeker_id = signed_in.get("/api/auth/me").json()["id"]
    event = seekers_store.get_store().list_discovery_events(seeker_id)[0]
    assert event["search_query"] == "credit risk"
    assert json.loads(event["filters_json"]) == {
        "sectors": ["Banking"],
        "seniority": ["mid"],
    }
    assert event["result_count"] == 2


def test_personalized_feed_uses_saved_and_discovery_signals_and_records_impressions(
    recommendation_clients,
):
    import seekers_store

    _, signed_in = recommendation_clients
    assert signed_in.post(
        "/api/me/saved", json={"source": "workday", "source_id": "SAVED"}
    ).status_code == 204
    assert signed_in.post(
        "/api/me/discovery",
        json={
            "search_query": "credit risk",
            "filters": {"sectors": ["Banking"], "seniority": ["mid"]},
            "result_count": 2,
        },
    ).status_code == 204

    response = signed_in.get("/api/recommendations", params={"page_size": 3})
    assert response.status_code == 200
    body = response.json()
    assert body["personalized"] is True
    assert body["saved_role_count"] == 1
    assert body["activity_count"] == 1
    assert body["items"][0]["job"]["source_id"] == "RISK"
    assert "SAVED" not in [item["job"]["source_id"] for item in body["items"]]
    assert any("credit risk" in reason.lower() for reason in body["items"][0]["reasons"])

    seeker_id = signed_in.get("/api/auth/me").json()["id"]
    impressions = seekers_store.get_store().list_recommendation_impressions(seeker_id)
    assert len(impressions) == len(body["items"])
    assert {row["batch_id"] for row in impressions} == {body["batch_id"]}

    clicked = signed_in.post("/api/me/recommendations/workday/RISK/click")
    assert clicked.status_code == 204
    clicked_row = next(
        row
        for row in seekers_store.get_store().list_recommendation_impressions(seeker_id)
        if row["source_id"] == "RISK"
    )
    assert clicked_row["clicked_at"] is not None
