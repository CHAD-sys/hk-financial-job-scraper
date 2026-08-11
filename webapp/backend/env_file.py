"""
Load the project's shell-style env file into os.environ.

Why this exists
---------------
The scraper gets its secrets because scripts/daily_run.sh does
`source config/api_keys.env` before running anything. The web backend is started
as `uvicorn main:app` with no such step, so it began life with a completely bare
environment — which once left public submissions queued without sending their
notification email: mailer.py read SMTP_USER, got "", and logged a warning
nobody was watching.

Design notes
------------
- **Existing environment always wins** (override=False). In production the
  platform supplies the variables and this file does not exist; locally the file
  supplies them. Neither should be able to clobber the other by accident.
- **A missing file is not an error.** That is the normal production case.
- No new dependency. The file format is a handful of `export KEY=value` lines;
  python-dotenv would be a reasonable choice but not worth a dependency for
  twenty lines of parsing we can test directly.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# webapp/backend/env_file.py -> repo root is three levels up.
DEFAULT_ENV_FILE = Path(__file__).resolve().parent.parent.parent / "config" / "api_keys.env"


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def parse_env_text(text: str) -> dict[str, str]:
    """
    Parse `export KEY=value` / `KEY=value` lines. Ignores blanks and comments.

    Deliberately conservative: anything that is not a plain assignment is
    skipped rather than guessed at. This is a config loader, not a shell.
    """
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or not key.replace("_", "").isalnum():
            continue
        # Trailing inline comments are only stripped for unquoted values —
        # a '#' inside a quoted secret is part of the secret.
        value = value.strip()
        quoted = len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"')
        if not quoted and " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        out[key] = _strip_quotes(value)
    return out


def load_env_file(path: Path | None = None, *, override: bool = False) -> list[str]:
    """
    Load `path` (default config/api_keys.env) into os.environ.

    Returns the names of the variables that were actually applied — names only,
    never values, so this is safe to log.
    """
    target = path or DEFAULT_ENV_FILE
    try:
        text = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.debug("No env file at %s — relying on the process environment", target)
        return []
    except OSError as exc:
        logger.warning("Could not read env file %s: %s", target, exc)
        return []

    applied: list[str] = []
    for key, value in parse_env_text(text).items():
        if not override and os.environ.get(key):
            continue
        os.environ[key] = value
        applied.append(key)

    if applied:
        logger.info("Loaded %d setting(s) from %s: %s", len(applied), target.name, ", ".join(sorted(applied)))
    return applied
