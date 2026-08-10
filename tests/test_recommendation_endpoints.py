"""HTTP contract for discovery capture and the Roles-for-you feed."""

from __future__ import annotations

import json
import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from .support import enrichment, job, make_app, make_bundle, make_jobs_db

SEEKER = {
    "email": "seeker@example.com",
    "password": "correct-horse-battery",
    "display_name": "Ada",
}

DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


def make_resume_docx(text: str) -> bytes:
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f'<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>'
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", "<Types />")
        package.writestr("word/document.xml", document)
    return buffer.getvalue()


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
    assert body["model_version"] == "signals-v3"
    assert body["personalization_enabled"] is False
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


def test_v2_feedback_is_user_controlled_but_signal_sources_are_not(
    recommendation_clients,
):
    import seekers_store

    _, signed_in = recommendation_clients
    seeker_id = signed_in.get("/api/auth/me").json()["id"]

    assert signed_in.post(
        "/api/me/recommendations/workday/RISK/feedback",
        json={"action": "more_like"},
    ).status_code == 204
    assert signed_in.post(
        "/api/me/recommendations/eightfold/ACTUARY/feedback",
        json={"action": "not_interested"},
    ).status_code == 204

    feed = signed_in.get("/api/recommendations", params={"page_size": 3}).json()
    assert "ACTUARY" not in [item["job"]["source_id"] for item in feed["items"]]
    risk = next(item for item in feed["items"] if item["job"]["source_id"] == "RISK")
    assert risk["feedback"] == ["more_like"]

    assert signed_in.delete(
        "/api/me/recommendations/workday/RISK/feedback/more_like"
    ).status_code == 204
    assert signed_in.delete(
        "/api/me/recommendations/eightfold/ACTUARY/feedback/not_interested"
    ).status_code == 204

    assert signed_in.post(
        "/api/me/discovery",
        json={
            "search_query": "banking risk",
            "filters": {"sectors": ["Banking"]},
            "result_count": 2,
        },
    ).status_code == 204
    assert seekers_store.get_store().list_discovery_events(seeker_id)

    assert signed_in.get("/api/me/recommendation-preferences").status_code == 404
    assert signed_in.patch(
        "/api/me/recommendation-preferences",
        json={"use_clicks": False},
    ).status_code == 405
    assert signed_in.post(
        "/api/me/recommendations/hidden-employers",
        json={"company": "AIA"},
    ).status_code == 405
    assert signed_in.delete("/api/me/recommendation-profile").status_code == 405

    assert signed_in.post(
        "/api/me/recommendations/workday/RISK/feedback",
        json={"action": "wrong_reason", "detail": "No longer exposed"},
    ).status_code == 422


def test_resume_upload_status_replacement_matches_and_deletion(
    recommendation_clients,
):
    anonymous, signed_in = recommendation_clients
    first = make_resume_docx(
        "Senior Credit Risk Manager with 7 years of experience in banking, "
        "credit risk, Basel III, SQL and financial modelling."
    )

    assert anonymous.get("/api/me/resume").status_code == 401
    upload = signed_in.put(
        "/api/me/resume",
        files={"resume": ("credit-risk.docx", first, DOCX_MEDIA_TYPE)},
    )
    assert upload.status_code == 200
    assert upload.json()["filename"] == "credit-risk.docx"
    assert {"credit risk", "basel iii", "sql"} <= set(
        upload.json()["analysis"]["skills"]
    )

    status = signed_in.get("/api/me/resume")
    assert status.status_code == 200
    assert status.json()["filename"] == "credit-risk.docx"
    assert "text_content" not in status.text
    assert "file_content" not in status.text

    matches = signed_in.get("/api/me/resume-matches", params={"limit": 2})
    assert matches.status_code == 200
    body = matches.json()
    assert body["has_resume"] is True
    assert body["items"][0]["job"]["source_id"] == "RISK"
    assert body["items"][0]["match_score"] >= 40
    assert any("Skills aligned" in reason for reason in body["items"][0]["reasons"])

    replacement = make_resume_docx(
        "Actuarial Manager with 8 years of experience in insurance and actuarial modelling."
    )
    replaced = signed_in.put(
        "/api/me/resume",
        files={"resume": ("actuarial.docx", replacement, DOCX_MEDIA_TYPE)},
    )
    assert replaced.status_code == 200
    assert replaced.json()["filename"] == "actuarial.docx"
    assert signed_in.get("/api/me/resume-matches").json()["items"][0]["job"][
        "source_id"
    ] == "ACTUARY"

    assert signed_in.delete("/api/me/resume").status_code == 204
    assert signed_in.get("/api/me/resume").json() is None
    assert signed_in.get("/api/me/resume-matches").json()["has_resume"] is False


def test_invalid_replacement_keeps_the_previous_resume(recommendation_clients):
    _, signed_in = recommendation_clients
    valid = make_resume_docx(
        "Credit Risk Analyst with 5 years of experience in banking and SQL."
    )
    assert signed_in.put(
        "/api/me/resume",
        files={"resume": ("valid.docx", valid, DOCX_MEDIA_TYPE)},
    ).status_code == 200

    invalid = signed_in.put(
        "/api/me/resume",
        files={"resume": ("replacement.txt", b"not a supported resume", "text/plain")},
    )

    assert invalid.status_code == 422
    assert signed_in.get("/api/me/resume").json()["filename"] == "valid.docx"


def test_oversized_resume_is_rejected_before_storage(recommendation_clients):
    _, signed_in = recommendation_clients
    response = signed_in.put(
        "/api/me/resume",
        files={
            "resume": (
                "large.pdf",
                b"%PDF-" + b"x" * (5 * 1024 * 1024),
                "application/pdf",
            )
        },
    )
    assert response.status_code == 413
    assert signed_in.get("/api/me/resume").json() is None
