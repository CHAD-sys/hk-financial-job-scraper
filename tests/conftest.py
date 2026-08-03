"""
Shared fixtures for the backend tests.

The builders themselves live in `support.py`; this file turns them into fixtures
so a test can ask for what it needs rather than wiring tmp paths by hand.

Note what is deliberately NOT here: an app fixture that every test shares. The
FastAPI app decides its configuration at import time, so each test that needs a
differently-configured app must re-import the module — see `support.import_main`.
Until there is an app factory, a session-scoped app fixture would be a lie.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from .support import make_bundle, make_jobs_db


@pytest.fixture(autouse=True)
def _no_outbound_mail(monkeypatch):
    """
    Nothing in the test suite may reach a real SMTP server.

    This is not paranoia. `main.py` calls `load_env_file()` at import, which reads
    the developer's real `config/api_keys.env` into `os.environ`; `mailer.py` then
    computes `SEEKER_MAIL_READY` at import from those values and freezes it. On a
    machine that has the file, every `POST /api/auth/register` in the test suite
    opened a live `smtplib.SMTP("mail.finexclub.org", 587)` with the real mailbox
    password and sent a verification mail to `seeker@example.com` — roughly twenty
    per run, from tests whose own docstring calls them hermetic.

    Blanking the credentials before the app is imported makes `SEEKER_MAIL_READY`
    false, so `send_to` returns False without connecting. The real fix is an
    injectable sender rather than import-time module constants; until then this
    fixture is the seam.
    """
    for var in ("SEEKER_SMTP_PASS", "SMTP_PASS", "SEEKER_SMTP_USER", "SMTP_USER"):
        monkeypatch.setenv(var, "")


@pytest.fixture()
def jobs_db(tmp_path: Path) -> Path:
    """A seeded stand-in jobs.db. Tests wanting their own rows call
    `make_jobs_db` directly instead."""
    path = tmp_path / "jobs.db"
    make_jobs_db(path)
    return path


@pytest.fixture()
def frontend_dist(tmp_path: Path) -> Path:
    """A fake built bundle."""
    dist = tmp_path / "dist"
    make_bundle(dist)
    return dist
