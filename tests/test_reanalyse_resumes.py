"""The backfill that carries stored resumes onto the current extractor.

analyse_resume() runs only at upload, and evidence_from_storage() rehydrates
whatever was stored verbatim, so without this script an extractor change
reaches nobody who has already uploaded.
"""

from __future__ import annotations

import hashlib
import io
import json
import runpy
import sqlite3
import sys
import zipfile
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent / "webapp" / "backend"
SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(BACKEND))

from seekers_store import SeekerStore  # noqa: E402

DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)

STALE_CV = (
    "EXPERIENCE\n"
    "Summer Analyst Intern, A Bank\n"
    "Jun 2026 - Aug 2026\n"
    "- Reported directly to the Vice President covering capital markets\n"
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
def seeded(tmp_path, monkeypatch):
    """A seekers.db holding one resume stamped with a stale v1 analysis."""
    db_path = tmp_path / "seekers.db"
    store = SeekerStore(db_path)
    seeker_id = store.create_seeker("alice@example.com")
    payload = _docx(STALE_CV)
    store.replace_resume(
        seeker_id,
        filename="resume.docx",
        media_type=DOCX_MEDIA_TYPE,
        size_bytes=len(payload),
        content_sha256=hashlib.sha256(payload).hexdigest(),
        file_content=payload,
        text_content="stale text captured by the old extractor",
        analysis={"skills": [], "role_families": [], "sectors": [],
                  "years_experience": None, "seniority": "senior"},
    )
    monkeypatch.setenv("SEEKERS_DB_PATH", str(db_path))
    return db_path


def _run(*argv):
    monkey = ["reanalyse_resumes.py", *argv]
    original, sys.argv = sys.argv, monkey
    try:
        runpy.run_path(str(SCRIPTS / "reanalyse_resumes.py"), run_name="__main__")
    except SystemExit as exc:
        assert exc.code == 0, f"script exited {exc.code}"
    finally:
        sys.argv = original


def _stored(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT text_content, analysis_json FROM seeker_resumes"
    ).fetchone()
    conn.close()
    return row["text_content"], json.loads(row["analysis_json"])


def test_a_dry_run_changes_nothing(seeded):
    _run()

    text, analysis = _stored(seeded)
    assert text == "stale text captured by the old extractor"
    assert analysis["seniority"] == "senior"


def test_apply_recomputes_text_and_analysis_from_the_original_file(seeded):
    # The stored text was produced by the old extractor, so re-analysing it
    # alone would not help; the backfill re-parses the original blob.
    _run("--apply")

    text, analysis = _stored(seeded)
    assert "summer analyst intern" in text.casefold()
    assert analysis["seniority"] == "junior"
    assert "certifications" in analysis


def test_apply_leaves_a_backup_beside_the_database(seeded):
    _run("--apply")

    assert list(seeded.parent.glob("seekers.db.*.bak"))


def test_an_unparseable_stored_file_is_left_untouched(seeded):
    conn = sqlite3.connect(seeded)
    with conn:
        conn.execute("UPDATE seeker_resumes SET file_content = ?", (b"not a docx",))
    conn.close()

    _run("--apply")

    text, analysis = _stored(seeded)
    assert text == "stale text captured by the old extractor"
    assert analysis["seniority"] == "senior"
