"""
The app factory.

These pin the property the backend did not have before: an app's configuration
is an argument, not something the module reads from the environment while it is
being imported. Two apps with two different databases can exist in one process,
which is the whole reason the tests no longer delete `main` from `sys.modules`
and re-execute it.
"""

from __future__ import annotations

import sys

import pytest
from fastapi.testclient import TestClient

from .support import BACKEND, job, make_app, make_bundle, make_jobs_db

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from settings import Settings  # noqa: E402


def _db(tmp_path, name: str, company: str):
    path = tmp_path / f"{name}.db"
    make_jobs_db(path, jobs=[job(source="workday", source_id=name, company=company,
                                 title=f"{name} Role", posted_at="2026-07-01")])
    return path


def _role_payload(**over):
    return {
        "contact_name": "A",
        "contact_email": "a@example.com",
        "company": "Example Capital",
        "title": "Risk Manager",
        "location": "Hong Kong",
        "employment_type": "Full-time",
        "salary_range": "",
        "description": "A sufficiently detailed role description.",
        "apply_url": "https://example.com/apply",
        "website": "",
        **over,
    }


# ── The seam ──────────────────────────────────────────────────────────────────

def test_two_apps_can_serve_two_databases_at_once(tmp_path):
    """
    Impossible before: the database path was a module-level constant resolved at
    import, so a process had exactly one, and a second configuration meant
    re-executing the module.
    """
    first = TestClient(make_app(_db(tmp_path, "first", "HSBC")))
    second = TestClient(make_app(_db(tmp_path, "second", "AIA")))

    assert first.get("/api/jobs", params={"search": "first"}).json()["jobs"][0]["company"] == "HSBC"
    assert second.get("/api/jobs", params={"search": "second"}).json()["jobs"][0]["company"] == "AIA"
    # And the first is still itself — building the second did not reconfigure it.
    assert first.get("/api/jobs", params={"search": "first"}).json()["jobs"][0]["company"] == "HSBC"


def test_settings_are_reachable_from_a_request(tmp_path):
    db = _db(tmp_path, "cfg", "HSBC")
    body = TestClient(make_app(db, submissions=tmp_path)).get("/health").json()
    assert body["db"] == str(db.resolve())
    assert body["submissions_dir"] == str(tmp_path.resolve())


def test_rate_limit_budgets_are_per_app(tmp_path):
    """
    The rate log used to be one module-level dict, so every app in the process
    shared a budget — and in a test run that meant one test could exhaust
    another's. Each app owns its own now.
    """
    payload = _role_payload()
    busy = TestClient(make_app(_db(tmp_path, "busy", "HSBC"), submissions=tmp_path / "busy"))
    fresh = TestClient(make_app(_db(tmp_path, "fresh", "HSBC"), submissions=tmp_path / "fresh"))

    codes = [busy.post("/api/post-role", json=payload).status_code for _ in range(6)]
    assert 429 in codes, "the limiter should have engaged on the busy app"
    assert fresh.post("/api/post-role", json=payload).status_code == 200


# ── Nothing happens at import ─────────────────────────────────────────────────

def test_building_an_app_does_not_touch_the_database(tmp_path):
    """
    create_app must not open, create or download anything. The seed download in
    particular used to run at import, so merely importing this module could
    start pulling a 100 MB file.
    """
    missing = tmp_path / "nothing" / "jobs.db"
    make_app(missing)
    assert not missing.exists()


def test_a_seed_url_is_fetched_at_startup_and_not_before(tmp_path, monkeypatch):
    """
    A configured seed URL is the lifespan's business, not the constructor's.

    This is the one that used to bite hardest: the download ran at import, so a
    test process that inherited DB_SEED_URL from the developer's env file would
    start pulling a 100 MB database just by importing the module.
    """
    import employers_store
    import main
    import seekers_store

    # The lifespan also purges expired sessions in both account stores on every
    # boot (see main._purge_expired_sessions). Without an explicit override,
    # get_store() resolves to <repo>/data/{seekers,employers}.db — this is the
    # one test in the suite that actually enters the lifespan, so it is the one
    # place a missing override would touch a real developer database instead of
    # a throwaway one.
    monkeypatch.setenv("SEEKERS_DB_PATH", str(tmp_path / "seekers.db"))
    monkeypatch.setenv("EMPLOYERS_DB_PATH", str(tmp_path / "employers.db"))
    seekers_store.reset_store()
    employers_store.reset_store()

    seeded: list[Settings] = []
    monkeypatch.setattr(main, "_seed_db_if_missing", seeded.append)

    app = main.create_app(Settings(jobs_db=tmp_path / "absent.db",
                                   db_seed_url="https://example.test/seed.db"))
    assert seeded == [], "constructing the app must not fetch anything"

    with TestClient(app):        # entering the context runs the lifespan
        pass
    assert [s.db_seed_url for s in seeded] == ["https://example.test/seed.db"]


def test_startup_purges_expired_sessions_in_both_stores(tmp_path, monkeypatch):
    """
    seekers_store.purge_expired_sessions() and its employers_store twin were
    written "safe to call on startup or from a periodic task" but had no caller
    anywhere in the codebase — expired rows were only ever removed one at a
    time, on the read that happened to land on them. This pins the fix: the
    lifespan now calls both stores' purge on every boot, before the app starts
    serving requests.
    """
    from datetime import timedelta

    import employers_store
    import main
    import seekers_store

    monkeypatch.setenv("SEEKERS_DB_PATH", str(tmp_path / "seekers.db"))
    monkeypatch.setenv("EMPLOYERS_DB_PATH", str(tmp_path / "employers.db"))
    seekers_store.reset_store()
    employers_store.reset_store()

    seeker_store = seekers_store.get_store()
    seeker_id = seeker_store.create_seeker("erin@example.com")
    now = seekers_store.utcnow()
    seeker_store.insert_session("seeker-live", seeker_id, now + timedelta(days=90))
    seeker_store.insert_session("seeker-dead", seeker_id, now - timedelta(seconds=1))

    employer_store = employers_store.get_store()
    employer_id = employer_store.create_employer(
        "hr@example.com", password_hash="x", company_name="Acme"
    )
    employer_store.insert_session("employer-live", employer_id, now + timedelta(days=90))
    employer_store.insert_session("employer-dead", employer_id, now - timedelta(seconds=1))

    app = main.create_app(Settings(jobs_db=tmp_path / "absent.db"))
    with TestClient(app):  # entering the context runs the lifespan
        pass

    assert seeker_store.get_session("seeker-dead") is None
    assert seeker_store.get_session("seeker-live") is not None
    assert employer_store.get_session("employer-dead") is None
    assert employer_store.get_session("employer-live") is not None


def test_startup_migrates_an_existing_jobs_database(tmp_path, monkeypatch):
    import main

    db = _db(tmp_path, "migrate", "HSBC")
    migrated: list[str] = []
    monkeypatch.setattr(main, "migrate", lambda path: migrated.append(path) or [])

    app = main.create_app(Settings(jobs_db=db))
    with TestClient(app):
        pass

    assert migrated == [str(db)]


# ── The module-level app ──────────────────────────────────────────────────────

def test_module_level_app_still_exists_for_uvicorn():
    """
    Procfile and railway.json both run `uvicorn main:app`. The factory is the
    seam; this is one ordinary caller of it, and deleting it would break the
    deploy without breaking a single test.
    """
    import main
    assert isinstance(main.app, type(main.create_app(Settings())))
    assert main.app.state.settings is not None


def test_the_frontend_mount_is_decided_per_app(tmp_path):
    """Route registration used to depend on the filesystem AT IMPORT."""
    db = _db(tmp_path, "spa", "HSBC")
    dist = tmp_path / "dist"
    make_bundle(dist)

    with_ui = TestClient(make_app(db, dist, tmp_path))
    without_ui = TestClient(make_app(db, tmp_path / "no-such-dist", tmp_path))

    assert with_ui.get("/jobs").status_code == 200     # SPA catch-all serves index.html
    assert without_ui.get("/jobs").status_code == 404  # nothing to serve
    assert without_ui.get("/api/jobs", params={"search": "spa"}).status_code == 200


@pytest.mark.parametrize("secure", [True, False])
def test_cookie_policy_comes_from_settings(tmp_path, secure):
    app = make_app(_db(tmp_path, f"cookie{secure}", "HSBC"), cookie_secure=secure)
    assert app.state.settings.cookie_secure is secure


# ── X-Forwarded-For trust ────────────────────────────────────────────────────
#
# Every IP-keyed rate limit in main.py reads its key from _client_ip(), which
# used to trust X-Forwarded-For unconditionally. /api/post-role is a clean
# endpoint to prove the behaviour through: its limit is IP-only (no email key
# to confuse the picture), and Starlette's TestClient always reports the same
# "testclient" peer regardless of what headers a request carries — so a test
# forging a fresh X-Forwarded-For value on every call is exactly the attack
# this setting defends against.

def test_trusted_proxy_headers_let_forged_xff_bypass_the_ip_limit(tmp_path):
    """
    Default behaviour, unchanged: trust_proxy_headers=True is the production
    posture (Railway always sits in front). A caller who can set its own
    X-Forwarded-For — which a caller behind Railway's real edge cannot — gets
    treated as a fresh IP every request and never trips the limiter. This is
    what proves the header is doing anything at all before the next test
    proves it can be turned off.
    """
    client = TestClient(make_app(_db(tmp_path, "xff-trusted", "HSBC"), submissions=tmp_path))
    codes = [
        client.post("/api/post-role", json=_role_payload(),
                    headers={"X-Forwarded-For": f"10.0.0.{i}"}).status_code
        for i in range(5)
    ]
    assert 429 not in codes, "a distinct X-Forwarded-For per request must read as a distinct IP"


def test_untrusted_proxy_headers_ignore_xff_and_limit_by_real_peer(tmp_path):
    """
    trust_proxy_headers=False — the escape hatch for a deployment reachable
    directly. The same forged-X-Forwarded-For attack from the test above must
    now fail to bypass anything, because every request is correctly attributed
    to the one real peer regardless of what the header claims.
    """
    client = TestClient(make_app(_db(tmp_path, "xff-untrusted", "HSBC"), submissions=tmp_path,
                                 trust_proxy_headers=False))
    codes = [
        client.post("/api/post-role", json=_role_payload(),
                    headers={"X-Forwarded-For": f"10.0.0.{i}"}).status_code
        for i in range(5)
    ]
    assert 429 in codes, "forging a fresh X-Forwarded-For must not evade the limit once untrusted"
