"""
Everything the backend reads from its environment, in one object.

WHY THIS EXISTS
---------------
All of this used to be module-level constants in main.py, computed at import:
the database path, the submissions directory, CORS origins, the cookie policy,
the frontend bundle location, the rate limit. Importing the module WAS
constructing the app, so there was exactly one possible configuration per
process — and the tests said so out loud:

    for mod in ("main", "mailer"): sys.modules.pop(mod, None)
    return importlib.import_module("main")

Deleting a module from `sys.modules` and re-executing it is not a seam. It also
re-ran a network download and a 64 MiB Argon2 hash every time.

Settings is a plain frozen dataclass with no I/O of its own beyond `from_env`,
so a test constructs one directly and never touches the environment at all.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

#: Repo root, from this file's location. Only used for defaults.
_REPO = Path(__file__).resolve().parent.parent.parent


def _flag(name: str, *, default: bool) -> bool:
    """An env flag. Absent means the default; "0" is the only way to say false."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw != "0"


@dataclass(frozen=True)
class Settings:
    """
    One app's configuration.

    Frozen because nothing should reconfigure a running app: the whole point of
    the factory is that a different configuration means a different app.
    """

    #: The jobs database. Read-only; see `job_read`.
    jobs_db: Path = _REPO / "data" / "jobs.db"

    #: Where consultation enquiries and role submissions are appended as JSONL.
    submissions_dir: Path | None = None

    #: The built React bundle. Absent is not fatal — the API serves without a UI.
    frontend_dist: Path = Path(__file__).resolve().parent.parent / "frontend" / "dist"

    #: Allowed CORS origins. Inert at one origin (ADR 0005), but a dev frontend
    #: pointed at an absolute API URL still preflights.
    cors_origins: tuple[str, ...] = ("http://localhost:5173",)

    #: Secure cookies require HTTPS, which localhost is not. Defaulting to True
    #: means the safe setting is the one you get by forgetting to configure.
    cookie_secure: bool = True

    #: Submissions per hour, per key. In-memory, so per-process.
    submit_rate_limit: int = 3

    #: Trust X-Forwarded-For for rate-limit keys and logging. True by default
    #: because production (Railway) always sits behind a proxy that sets it
    #: honestly. The escape hatch is for a deployment reachable directly,
    #: where the header is caller-controlled and every IP-keyed rate limit
    #: (register, login, reset, employer register/login) could otherwise be
    #: routed around by forging a fresh value on every request.
    trust_proxy_headers: bool = True

    #: Optional one-time download to seed an empty volume on first boot.
    db_seed_url: str = ""

    def __post_init__(self) -> None:
        # Submissions default to sitting beside the database, which is the
        # Railway volume in production. Computed here rather than as a default
        # because it depends on another field.
        if self.submissions_dir is None:
            object.__setattr__(self, "submissions_dir", self.jobs_db.parent)
        for name in ("jobs_db", "submissions_dir", "frontend_dist"):
            object.__setattr__(self, name, Path(getattr(self, name)).resolve())

    @classmethod
    def from_env(cls) -> "Settings":
        """
        Read the environment.

        Call this AFTER `load_env_file()`, which is what puts
        `config/api_keys.env` into `os.environ` in local development.
        """
        cors = os.environ.get("CORS_ORIGINS", "http://localhost:5173").strip()
        origins = ("*",) if cors == "*" else tuple(o.strip() for o in cors.split(",") if o.strip())

        submissions = os.environ.get("SUBMISSIONS_DIR")
        return cls(
            jobs_db=Path(os.environ.get("JOBS_DB_PATH", str(cls.jobs_db))),
            submissions_dir=Path(submissions) if submissions else None,
            frontend_dist=Path(os.environ.get("FRONTEND_DIST", str(cls.frontend_dist))),
            cors_origins=origins,
            cookie_secure=_flag("SESSION_COOKIE_SECURE", default=True),
            submit_rate_limit=int(os.environ.get("SUBMIT_RATE_LIMIT", "3")),
            db_seed_url=os.environ.get("DB_SEED_URL", "").strip(),
            trust_proxy_headers=_flag("TRUST_PROXY_HEADERS", default=True),
        )

    # ── Derived ───────────────────────────────────────────────────────────────

    @property
    def index_html(self) -> Path:
        return self.frontend_dist / "index.html"

    def frontend_present(self) -> bool:
        """True only when there is an actual bundle, not just a directory."""
        return self.index_html.is_file()
