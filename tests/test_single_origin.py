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

The builders live in `support.py`. Each test builds its own app through
`create_app`, so "a differently configured app" is a function call rather than a
re-import.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from .support import INDEX_MARKER, make_app, make_bundle, make_jobs_db


@pytest.fixture()
def client(tmp_path):
    """The deployed shape: API + a built bundle, one origin."""
    db = tmp_path / "jobs.db"
    make_jobs_db(db)
    dist = tmp_path / "dist"
    make_bundle(dist)
    return TestClient(make_app(db, dist, tmp_path))


@pytest.fixture()
def api_only_client(tmp_path):
    """Backend-only local dev: nothing has been built, dist/ does not exist."""
    db = tmp_path / "jobs.db"
    make_jobs_db(db)
    return TestClient(make_app(db, tmp_path / "nope" / "dist", tmp_path))


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
