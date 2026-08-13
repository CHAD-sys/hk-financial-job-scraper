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
from dataclasses import dataclass
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

    #: Where recruiter Role submissions are appended as JSONL.
    submissions_dir: Path | None = None

    #: Last-known-good public metadata for the Learning page. This tiny JSON
    #: file sits on the Railway volume; videos and images remain upstream.
    learning_content_path: Path | None = None

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

    #: Redis connection string for the rate limiter. Empty (the default) means
    #: the in-process RateLimiter — correct for one replica, resets on deploy.
    #: Set this once the app runs more than one replica, or takes payment, so
    #: every replica shares one count instead of each starting from zero
    #: (rate_limit.py). Railway's Redis plugin sets this automatically once
    #: attached and referenced via a variable reference on the backend service.
    redis_url: str = ""

    #: Shared secret used only by the scheduled GitHub pipeline when it
    #: publishes the completed Hong Kong-day snapshot to Railway. Empty keeps
    #: the ingestion endpoint disabled, which is the safe local default.
    pipeline_sync_token: str = ""

    #: Signs short-lived grants proving that a Role reached the browser through
    #: research, recommendations, resume matching, or Saved Roles. When empty,
    #: the app generates a process-local secret at startup; production should
    #: set ROLE_ACCESS_SECRET so grants survive restarts and multiple replicas.
    role_access_secret: str = ""

    #: Signs non-expiring Alert-unsubscribe tokens (alert_unsubscribe.py) — a
    #: SEPARATE secret from role_access_secret on purpose, so a token minted
    #: for one purpose can never be replayed as the other. When empty, the app
    #: generates a process-local secret at startup; production should set
    #: ALERT_UNSUBSCRIBE_SECRET so a restart or a second replica does not
    #: invalidate every unsubscribe link already sitting in a Seeker's inbox.
    alert_unsubscribe_secret: str = ""

    #: Master kill switch for the weekly Alerts email (alerts.py). OFF by
    #: design: the feature is fully built and wired (main.py triggers it as a
    #: background task after every pipeline publish, admin.py), but nothing
    #: sends a single email until ALERTS_ENABLED=1 is set in the environment.
    #: Deliberately separate from any individual Seeker's opt-in — this flag
    #: gates whether the feature runs AT ALL, not whether one Seeker wants it.
    alerts_enabled: bool = False

    def __post_init__(self) -> None:
        # Submissions default to sitting beside the database, which is the
        # Railway volume in production. Computed here rather than as a default
        # because it depends on another field.
        if self.submissions_dir is None:
            object.__setattr__(self, "submissions_dir", self.jobs_db.parent)
        if self.learning_content_path is None:
            object.__setattr__(
                self, "learning_content_path", self.jobs_db.parent / "learning_content.json"
            )
        for name in ("jobs_db", "submissions_dir", "learning_content_path", "frontend_dist"):
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
        learning_content = os.environ.get("LEARNING_CONTENT_PATH")
        return cls(
            jobs_db=Path(os.environ.get("JOBS_DB_PATH", str(cls.jobs_db))),
            submissions_dir=Path(submissions) if submissions else None,
            learning_content_path=Path(learning_content) if learning_content else None,
            frontend_dist=Path(os.environ.get("FRONTEND_DIST", str(cls.frontend_dist))),
            cors_origins=origins,
            cookie_secure=_flag("SESSION_COOKIE_SECURE", default=True),
            submit_rate_limit=int(os.environ.get("SUBMIT_RATE_LIMIT", "3")),
            db_seed_url=os.environ.get("DB_SEED_URL", "").strip(),
            trust_proxy_headers=_flag("TRUST_PROXY_HEADERS", default=True),
            redis_url=os.environ.get("REDIS_URL", "").strip(),
            pipeline_sync_token=os.environ.get("PIPELINE_SYNC_TOKEN", "").strip(),
            role_access_secret=os.environ.get("ROLE_ACCESS_SECRET", "").strip(),
            alert_unsubscribe_secret=os.environ.get("ALERT_UNSUBSCRIBE_SECRET", "").strip(),
            alerts_enabled=_flag("ALERTS_ENABLED", default=False),
        )

    # ── Derived ───────────────────────────────────────────────────────────────

    @property
    def index_html(self) -> Path:
        return self.frontend_dist / "index.html"

    def frontend_present(self) -> bool:
        """True only when there is an actual bundle, not just a directory."""
        return self.index_html.is_file()
