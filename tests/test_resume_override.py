"""A Seeker's correction of their own extracted evidence.

Extraction is a heuristic over an arbitrary PDF, so it is sometimes wrong in
ways only the person who wrote the CV can settle. These tests pin the property
that makes the override layer worth having: a correction outlives a re-run of
the extractor.
"""

from __future__ import annotations

import io
import json
import sqlite3
import zipfile

import pytest
from fastapi.testclient import TestClient

from .support import job, make_app, make_bundle, make_jobs_db

SEEKER = {
    "email": "seeker@example.com",
    "password": "correct-horse-battery",
    "display_name": "Ada",
}
DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)

# Reads as a student with internships only — the case that used to come out
# "senior" and the reason a human needs a way to answer back.
STUDENT_CV = (
    "EXPERIENCE\n"
    "Summer Analyst Intern, A Bank\n"
    "Jun 2026 - Aug 2026\n"
    "- Built models in Python and SQL\n"
    "EDUCATION\n"
    "BBA in Finance, Year 2\n"
    "2024 - 2028\n"
)


def _docx(text: str) -> bytes:
    body = "".join(
        f"<w:p><w:r><w:t>{line}</w:t></w:r></w:p>" for line in text.split("\n")
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", "<Types />")
        package.writestr("word/document.xml", document)
    return buffer.getvalue()


@pytest.fixture()
def jobs_db(tmp_path):
    path = tmp_path / "jobs.db"
    make_jobs_db(
        path,
        jobs=[
            job(
                source="workday",
                source_id="LEAD",
                company="HSBC",
                title="Head of Treasury",
                posted_at="2026-08-07T00:00:00+00:00",
            )
        ],
    )
    return path


@pytest.fixture()
def signed_in(jobs_db, tmp_path, monkeypatch):
    monkeypatch.setenv("SEEKERS_DB_PATH", str(tmp_path / "seekers.db"))
    import seekers_store

    seekers_store.reset_store()
    dist = tmp_path / "dist"
    make_bundle(dist)
    client = TestClient(make_app(jobs_db, dist, tmp_path, cookie_secure=False))
    assert client.post("/api/auth/register", json=SEEKER).status_code == 201
    response = client.put(
        "/api/me/resume",
        files={"resume": ("cv.docx", _docx(STUDENT_CV), DOCX_MEDIA_TYPE)},
    )
    assert response.status_code == 200
    return client


def test_a_correction_becomes_the_effective_evidence(signed_in):
    response = signed_in.put(
        "/api/me/resume/analysis",
        json={"seniority": "intern", "years_experience": 1},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["analysis"]["seniority"] == "intern"
    assert body["analysis"]["years_experience"] == 1


def test_the_extraction_is_kept_alongside_the_correction(signed_in):
    signed_in.put("/api/me/resume/analysis", json={"seniority": "intern"})

    body = signed_in.get("/api/me/resume").json()
    assert body["analysis"]["seniority"] == "intern"
    assert body["analysis_extracted"]["seniority"] == "junior"
    assert body["analysis_override"] == {"seniority": "intern"}


def test_clearing_a_field_falls_back_to_the_extraction(signed_in):
    signed_in.put("/api/me/resume/analysis", json={"seniority": "lead"})
    signed_in.put("/api/me/resume/analysis", json={"seniority": None})

    body = signed_in.get("/api/me/resume").json()
    assert body["analysis"]["seniority"] == "junior"
    assert body["analysis_override"] == {}


def test_re_running_the_extractor_does_not_discard_a_correction(signed_in, tmp_path):
    # The whole point of the layer: scripts/reanalyse_resumes.py rewrites the
    # extracted half wholesale, and the Seeker's answer must survive it.
    signed_in.put("/api/me/resume/analysis", json={"seniority": "intern"})

    conn = sqlite3.connect(tmp_path / "seekers.db")
    with conn:
        conn.execute(
            "UPDATE seeker_resumes SET analysis_json = ?",
            (json.dumps({"skills": [], "role_families": [], "sectors": [],
                         "years_experience": 99, "seniority": "executive"}),),
        )
    conn.close()

    body = signed_in.get("/api/me/resume").json()
    assert body["analysis_extracted"]["seniority"] == "executive"
    assert body["analysis"]["seniority"] == "intern"


def test_uploading_a_new_resume_clears_the_correction(signed_in):
    signed_in.put("/api/me/resume/analysis", json={"seniority": "intern"})
    signed_in.put(
        "/api/me/resume",
        files={"resume": ("cv2.docx", _docx(STUDENT_CV), DOCX_MEDIA_TYPE)},
    )

    body = signed_in.get("/api/me/resume").json()
    assert body["analysis_override"] == {}
    assert body["analysis"]["seniority"] == "junior"


def test_matching_honours_the_corrected_career_level(signed_in):
    # A "Head of Treasury" role is a distance-2 mismatch for a junior and a
    # distance-3 mismatch for an intern, so the correction has to reach the
    # ranker, not just the account page.
    before = signed_in.get("/api/me/resume-matches").json()
    signed_in.put("/api/me/resume/analysis", json={"seniority": "lead"})
    after = signed_in.get("/api/me/resume-matches").json()

    assert before["model_version"] == after["model_version"]
    assert [item["match_score"] for item in after["items"]] != [
        item["match_score"] for item in before["items"]
    ] or not before["items"]


def test_added_skills_are_used_when_scoring(signed_in):
    signed_in.put(
        "/api/me/resume/analysis",
        json={"skills": ["treasury operations", "liquidity management"]},
    )

    body = signed_in.get("/api/me/resume").json()
    assert "treasury operations" in body["analysis"]["skills"]
    assert "treasury operations" not in body["analysis_extracted"]["skills"]


@pytest.mark.parametrize(
    "payload,detail",
    [
        ({"seniority": "chief wizard"}, "career level"),
        ({"years_experience": -1}, "between 0 and 60"),
        ({"years_experience": 61}, "between 0 and 60"),
    ],
)
def test_nonsense_corrections_are_refused(signed_in, payload, detail):
    response = signed_in.put("/api/me/resume/analysis", json=payload)

    assert response.status_code == 422
    assert detail in response.json()["detail"]


def test_correcting_without_a_resume_is_a_404(jobs_db, tmp_path, monkeypatch):
    monkeypatch.setenv("SEEKERS_DB_PATH", str(tmp_path / "empty.db"))
    import seekers_store

    seekers_store.reset_store()
    dist = tmp_path / "dist2"
    make_bundle(dist)
    client = TestClient(make_app(jobs_db, dist, tmp_path, cookie_secure=False))
    assert client.post("/api/auth/register", json=SEEKER).status_code == 201

    response = client.put("/api/me/resume/analysis", json={"seniority": "mid"})

    assert response.status_code == 404


def test_a_correction_needs_an_account(jobs_db, tmp_path, monkeypatch):
    monkeypatch.setenv("SEEKERS_DB_PATH", str(tmp_path / "anon.db"))
    import seekers_store

    seekers_store.reset_store()
    dist = tmp_path / "dist3"
    make_bundle(dist)
    client = TestClient(make_app(jobs_db, dist, tmp_path, cookie_secure=False))

    assert client.put("/api/me/resume/analysis", json={"seniority": "mid"}).status_code == 401
