"""
Tests for the backend's env-file loader.

This exists because its absence caused a real, silent bug: the web backend is
started as `uvicorn main:app` and never sourced config/api_keys.env the way
daily_run.sh does, so /api/contact queued enquiries and quietly sent no email.
The behaviours worth locking down are the ones that would let that happen again
— or would let a local file quietly override production credentials.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent / "webapp" / "backend"
sys.path.insert(0, str(BACKEND))

from env_file import load_env_file, parse_env_text  # noqa: E402


# ── Parsing ───────────────────────────────────────────────────────────────────

def test_parses_export_and_bare_assignments():
    parsed = parse_env_text("export SMTP_USER=me@example.com\nSMTP_PASS=abcd1234\n")
    assert parsed == {"SMTP_USER": "me@example.com", "SMTP_PASS": "abcd1234"}


def test_ignores_comments_and_blank_lines():
    parsed = parse_env_text("# a comment\n\n  \nexport A=1\n")
    assert parsed == {"A": "1"}


def test_strips_matching_quotes():
    parsed = parse_env_text("A='single'\nB=\"double\"\nC=unquoted\n")
    assert parsed == {"A": "single", "B": "double", "C": "unquoted"}


def test_hash_inside_a_quoted_value_is_kept():
    """App passwords and API keys can contain '#'; it must not be treated as a comment."""
    parsed = parse_env_text("SMTP_PASS='se#cret'\n")
    assert parsed["SMTP_PASS"] == "se#cret"


def test_trailing_comment_stripped_from_unquoted_value():
    parsed = parse_env_text("A=value # trailing note\n")
    assert parsed["A"] == "value"


def test_lines_without_assignment_are_skipped():
    parsed = parse_env_text("just some text\nA=1\n")
    assert parsed == {"A": "1"}


# ── Loading ───────────────────────────────────────────────────────────────────

def test_loads_into_environ(tmp_path, monkeypatch):
    f = tmp_path / "keys.env"
    f.write_text("export SMTP_USER=me@example.com\n", encoding="utf-8")
    monkeypatch.delenv("SMTP_USER", raising=False)

    applied = load_env_file(f)

    import os
    assert applied == ["SMTP_USER"]
    assert os.environ["SMTP_USER"] == "me@example.com"


def test_existing_environment_wins(tmp_path, monkeypatch):
    """
    The production case: the platform sets real credentials and a stray local
    file must not be able to replace them.
    """
    f = tmp_path / "keys.env"
    f.write_text("SMTP_USER=from-file@example.com\n", encoding="utf-8")
    monkeypatch.setenv("SMTP_USER", "from-platform@example.com")

    applied = load_env_file(f)

    import os
    assert applied == []
    assert os.environ["SMTP_USER"] == "from-platform@example.com"


def test_override_true_replaces(tmp_path, monkeypatch):
    f = tmp_path / "keys.env"
    f.write_text("A=file\n", encoding="utf-8")
    monkeypatch.setenv("A", "env")

    load_env_file(f, override=True)

    import os
    assert os.environ["A"] == "file"


def test_missing_file_is_not_an_error(tmp_path):
    """Normal in production, where the platform supplies the environment."""
    assert load_env_file(tmp_path / "nope.env") == []


def test_returns_names_only_so_it_is_safe_to_log(tmp_path, monkeypatch):
    f = tmp_path / "keys.env"
    f.write_text("SMTP_PASS=supersecret\n", encoding="utf-8")
    monkeypatch.delenv("SMTP_PASS", raising=False)

    applied = load_env_file(f)

    assert applied == ["SMTP_PASS"]
    assert "supersecret" not in " ".join(applied)


# ── The regression this was written for ───────────────────────────────────────

def test_backend_sees_smtp_settings_after_load(tmp_path, monkeypatch):
    """
    End to end: with a file present and a bare environment, the mailer module
    must come up configured. This is the exact condition that failed.
    """
    f = tmp_path / "keys.env"
    f.write_text("SMTP_USER=me@example.com\nSMTP_PASS=abcd1234efgh5678\n", encoding="utf-8")
    for var in ("SMTP_USER", "SMTP_PASS"):
        monkeypatch.delenv(var, raising=False)

    load_env_file(f)

    sys.modules.pop("mailer", None)
    import importlib
    mailer = importlib.import_module("mailer")

    assert mailer.SMTP_USER == "me@example.com"
    assert mailer.SMTP_PASS == "abcd1234efgh5678"
