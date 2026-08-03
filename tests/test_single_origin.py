"""
Tests for the single-origin setup — FastAPI serving the built React bundle.

The one thing that can go wrong here is routing precedence. The catch-all that
makes client-side routes survive a hard refresh matches EVERY path, so if it is
registered in the wrong place, or its guards are wrong, it quietly swallows the
API: /api/jobs would start answering with a page of HTML instead of JSON. These
tests pin both directions of that boundary —

  - the API and /health still answer as themselves,
  - unknown non-API paths (/jobs, /saved, …) answer with index.html,
  - unknown API paths still 404 rather than being handed the SPA,
  - and the backend still boots at all when no bundle has been built.

The bundle here is a handful of fake files in tmp_path, not the real dist/: the
subject under test is routing, so a real 400 kB build would only make the test
slower and dependent on `npm run build` having been run.

The database is likewise a two-table stand-in rather than the real 100 MB
jobs.db, so this file is hermetic and runs anywhere. It holds exactly the
columns /api/jobs reads — enough to prove the route still reaches SQLite and
returns rows.
"""

from __future__ import annotations

import importlib
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parent.parent / "webapp" / "backend"

INDEX_MARKER = "<!-- test index.html -->"


def _make_db(path: Path) -> None:
    """A minimal jobs.db: the columns /api/jobs selects and filters on, one row."""
    conn = sqlite3.connect(path)
    with conn:
        conn.execute(
            """
            CREATE TABLE jobs (
                source          TEXT NOT NULL,
                source_id       TEXT NOT NULL,
                company         TEXT NOT NULL,
                url             TEXT NOT NULL,
                title           TEXT NOT NULL,
                description_clean TEXT NOT NULL DEFAULT '',
                locations       TEXT NOT NULL DEFAULT '[]',
                posted_at       TEXT,
                is_active       INTEGER NOT NULL DEFAULT 1,
                is_primary      INTEGER NOT NULL DEFAULT 1,
                cross_posted    INTEGER NOT NULL DEFAULT 0,
                apply_url       TEXT NOT NULL DEFAULT '',
                source_tier     TEXT NOT NULL DEFAULT 'mainstream',
                board_signals   TEXT NOT NULL DEFAULT '{}',
                grp_new         INTEGER,
                grp_urgent      INTEGER,
                grp_applicants  INTEGER,
                PRIMARY KEY (source, source_id)
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE job_enrichments (
                source          TEXT NOT NULL,
                source_id       TEXT NOT NULL,
                seniority       TEXT,
                job_category    TEXT,
                remote_type     TEXT,
                required_skills TEXT,
                salary_hkd_min  INTEGER,
                salary_hkd_max  INTEGER,
                salary_estimated_min INTEGER,
                salary_estimated_max INTEGER,
                salary_estimated_confidence TEXT,
                years_experience_required INTEGER,
                description_summary TEXT,
                title_en        TEXT,
                PRIMARY KEY (source, source_id)
            );
            """
        )
        conn.execute(
            "INSERT INTO jobs (source, source_id, company, url, title, description_clean, "
            "locations, posted_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                "workday", "J1", "HSBC", "https://example.test/j1",
                "Credit Risk Analyst", "Analyse credit risk.",
                '["Hong Kong"]', "2026-07-01T00:00:00+00:00",
            ),
        )
    conn.close()


def _make_bundle(dist: Path) -> None:
    """A fake `npm run build` output: index.html, a hashed asset, a root file."""
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(
        f"<html><body>{INDEX_MARKER}<div id='root'></div></body></html>", encoding="utf-8"
    )
    (dist / "assets" / "index-abc123.js").write_text("console.log('app')", encoding="utf-8")
    (dist / "favicon.svg").write_text("<svg/>", encoding="utf-8")


def _import_main(monkeypatch, db: Path, dist: Path, submissions: Path):
    """Fresh app per test — module-level config (DB_PATH, FRONTEND_DIST) and the
    static mount are all decided at import time, so a reimport is the only way to
    exercise a different configuration."""
    monkeypatch.setenv("JOBS_DB_PATH", str(db))
    monkeypatch.setenv("FRONTEND_DIST", str(dist))
    monkeypatch.setenv("SUBMISSIONS_DIR", str(submissions))
    monkeypatch.syspath_prepend(str(BACKEND))
    for mod in ("main", "mailer"):
        sys.modules.pop(mod, None)
    return importlib.import_module("main")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """The deployed shape: API + a built bundle, one origin."""
    db = tmp_path / "jobs.db"
    _make_db(db)
    dist = tmp_path / "dist"
    _make_bundle(dist)
    main = _import_main(monkeypatch, db, dist, tmp_path)
    return TestClient(main.app)


@pytest.fixture()
def api_only_client(tmp_path, monkeypatch):
    """Backend-only local dev: nothing has been built, dist/ does not exist."""
    db = tmp_path / "jobs.db"
    _make_db(db)
    main = _import_main(monkeypatch, db, tmp_path / "nope" / "dist", tmp_path)
    return TestClient(main.app)


# ── The API must not be shadowed ──────────────────────────────────────────────

def test_api_jobs_still_responds(client):
    r = client.get("/api/jobs")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    body = r.json()
    assert body["total"] == 1
    assert body["jobs"][0]["title"] == "Credit Risk Analyst"


def test_api_job_detail_still_responds(client):
    r = client.get("/api/jobs/workday/J1")
    assert r.status_code == 200
    assert r.json()["company"] == "HSBC"


def test_health_still_responds(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_unknown_api_path_is_404_not_index(client):
    """The failure this guards against: a retired or typo'd endpoint answering
    200 with HTML, so the frontend reports a JSON parse error instead of a 404."""
    for path in ("/api/unknown", "/api/jobz", "/api/jobs/extra/segments/here", "/api"):
        r = client.get(path)
        assert r.status_code == 404, f"{path} should be 404, got {r.status_code}"
        assert INDEX_MARKER not in r.text, f"{path} was served the SPA"


# ── Client-side routes must survive a hard refresh ────────────────────────────

@pytest.mark.parametrize("path", ["/", "/jobs", "/saved", "/about", "/learning", "/post-a-role"])
def test_client_routes_return_index_html(client, path):
    r = client.get(path)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert INDEX_MARKER in r.text


def test_deep_client_route_returns_index(client):
    """React Router owns everything below a route too — a nested or future path
    must not 404 just because this server has never heard of it."""
    r = client.get("/jobs/some/deep/path")
    assert r.status_code == 200
    assert INDEX_MARKER in r.text


def test_index_html_is_not_cached(client):
    """index.html names the current hashed bundle. A cached copy pins a returning
    visitor to a JS file that no longer exists, and the app boots blank."""
    r = client.get("/jobs")
    assert "no-cache" in r.headers.get("cache-control", "")


# ── Real files are served as themselves ───────────────────────────────────────

def test_hashed_assets_are_served(client):
    r = client.get("/assets/index-abc123.js")
    assert r.status_code == 200
    assert "console.log" in r.text


def test_root_level_files_are_served(client):
    """favicon.svg and friends live at the root of the bundle, not under assets/."""
    r = client.get("/favicon.svg")
    assert r.status_code == 200
    assert "<svg" in r.text


def test_missing_asset_is_404_not_index(client):
    """A missing hashed file must fail honestly. Handing back index.html would
    make the browser try to execute HTML as JavaScript."""
    r = client.get("/assets/does-not-exist.js")
    assert r.status_code == 404
    assert INDEX_MARKER not in r.text


def test_path_traversal_cannot_escape_the_bundle(client):
    """..-escapes resolve outside dist/ and fall through to the SPA, never to a
    file read. CLAUDE.md is a real file two directories above dist/."""
    r = client.get("/%2e%2e/%2e%2e/CLAUDE.md")
    assert r.status_code in (200, 404)
    assert "FinEx" not in r.text or INDEX_MARKER in r.text


# ── The API must still boot with no bundle ────────────────────────────────────

def test_api_boots_without_a_bundle(api_only_client):
    """Backend-only development, and a deploy whose frontend build failed: a
    working API with no UI beats a service that refuses to start."""
    assert api_only_client.get("/api/jobs").status_code == 200
    assert api_only_client.get("/health").status_code == 200


def test_no_catch_all_without_a_bundle(api_only_client):
    """With nothing to serve, /jobs is an honest 404 rather than a broken page."""
    r = api_only_client.get("/jobs")
    assert r.status_code == 404


def test_health_reports_the_missing_bundle(api_only_client):
    """Same reasoning as the email field next to it: a silent misconfiguration
    that breaks nothing at boot needs somewhere to be visible."""
    assert "NOT BUILT" in api_only_client.get("/health").json()["frontend"]
