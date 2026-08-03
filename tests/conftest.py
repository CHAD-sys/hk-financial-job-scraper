"""
Shared fixtures for the backend tests.

The builders themselves live in `support.py`; this file turns them into fixtures
so a test can ask for what it needs rather than wiring tmp paths by hand.

There used to be an autouse fixture here that blanked the SMTP credentials,
because `main.py` loaded the developer's real `config/api_keys.env` at import
and the suite was mailing `seeker@example.com` about twenty times a run. It is
gone: `support.make_app` gives every app a RecordingSender, so there is no SMTP
connection to blank. A seam rather than a guard — and a test can now assert on
what was sent instead of only on what was not.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from .support import make_bundle, make_jobs_db


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
