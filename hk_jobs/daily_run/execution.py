"""Concrete local and hosted adapters for the canonical Daily Run phases."""

from __future__ import annotations

import gzip
import hashlib
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

import httpx

from hk_jobs.daily_run.model import DailyRunRecord, PhaseStatus
from hk_jobs.daily_run.registry import PhaseDefinition
from hk_jobs.daily_run.runner import PhaseOutput


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    repo: Path
    database: Path
    export: Path

    @classmethod
    def under(cls, repo: str | Path) -> RuntimePaths:
        root = Path(repo).resolve()
        return cls(root, root / "data/jobs.db", root / "data/jobs.jsonl")


class CommandPhaseExecutor:
    """Translate domain phases into commands and owned remote transports."""

    def __init__(
        self,
        paths: RuntimePaths,
        *,
        company: str | None = None,
        environ: dict[str, str] | None = None,
        run_command: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        http_get: Callable[..., httpx.Response] = httpx.get,
        http_post: Callable[..., httpx.Response] = httpx.post,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self.paths = paths
        self.company = company
        self.environ = environ if environ is not None else os.environ
        self._run_command = run_command
        self._http_get = http_get
        self._http_post = http_post
        self._now = now

    def __call__(self, phase: PhaseDefinition, record: DailyRunRecord) -> PhaseOutput:
        if self.environ.get("GITHUB_ACTIONS") == "true":
            print(f"::group::{phase.label}", flush=True)
        try:
            handler = getattr(self, f"_{phase.key}")
            return handler(record)
        finally:
            if self.environ.get("GITHUB_ACTIONS") == "true":
                print("::endgroup::", flush=True)

    def _pipeline(self, *arguments: str) -> None:
        command = [
            sys.executable,
            "-m",
            "hk_jobs.pipeline",
            "--db",
            str(self.paths.database),
            *arguments,
            "--log-level",
            "INFO",
        ]
        self._run_command(command, cwd=self.paths.repo, check=True, text=True)

    def _restore(self, _record: DailyRunRecord) -> PhaseOutput:
        self.paths.database.parent.mkdir(parents=True, exist_ok=True)
        url = self.environ.get("PIPELINE_DATABASE_SYNC_URL", "")
        token = self.environ.get("PIPELINE_SYNC_TOKEN", "")
        if url and token:
            try:
                response = self._http_get(
                    url,
                    headers={"X-Pipeline-Sync-Token": token},
                    timeout=120,
                    follow_redirects=True,
                )
                response.raise_for_status()
                self._restore_gzip(response.content)
                return PhaseOutput(
                    detail="Restored the latest enriched database from Railway",
                    facts={
                        "restore_source": "railway",
                        "restore_sha256": self._sha256(self.paths.database),
                    },
                )
            except (httpx.HTTPError, OSError, sqlite3.DatabaseError) as exc:
                print(f"::warning::Railway restore unavailable: {exc}", flush=True)
        if self._restore_github_artifact():
            return PhaseOutput(
                detail="Railway unavailable; restored the latest successful GitHub artifact",
                facts={
                    "restore_source": "github_artifact",
                    "restore_sha256": self._sha256(self.paths.database),
                },
            )
        self.paths.database.unlink(missing_ok=True)
        return PhaseOutput(
            detail="No reusable database was available; starting a new history",
            facts={"restore_source": "fresh", "restore_sha256": None},
        )

    def _restore_gzip(self, content: bytes) -> None:
        temporary = self.paths.database.with_suffix(".restore.tmp")
        try:
            temporary.write_bytes(gzip.decompress(content))
            with sqlite3.connect(temporary) as conn:
                if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise sqlite3.DatabaseError("restored database failed quick_check")
            temporary.replace(self.paths.database)
        finally:
            temporary.unlink(missing_ok=True)

    def _restore_github_artifact(self) -> bool:
        repository = self.environ.get("GITHUB_REPOSITORY")
        token = self.environ.get("GH_TOKEN")
        if not repository or not token or shutil.which("gh") is None:
            return False
        try:
            lookup = self._run_command(
                [
                    "gh",
                    "run",
                    "list",
                    "--repo",
                    repository,
                    "--workflow",
                    "daily.yml",
                    "--status",
                    "success",
                    "--limit",
                    "1",
                    "--json",
                    "databaseId",
                    "--jq",
                    ".[0].databaseId // empty",
                ],
                check=True,
                capture_output=True,
                text=True,
                cwd=self.paths.repo,
            )
            prior_run = lookup.stdout.strip()
            if not prior_run:
                return False
            self._run_command(
                [
                    "gh",
                    "run",
                    "download",
                    prior_run,
                    "--repo",
                    repository,
                    "--name",
                    f"jobs-db-{prior_run}",
                    "--dir",
                    str(self.paths.database.parent),
                ],
                check=True,
                text=True,
                cwd=self.paths.repo,
            )
            with sqlite3.connect(self.paths.database) as conn:
                return conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        except (OSError, sqlite3.DatabaseError, subprocess.CalledProcessError):
            self.paths.database.unlink(missing_ok=True)
            return False

    def _scrape(self, _record: DailyRunRecord) -> PhaseOutput:
        self.paths.database.parent.mkdir(parents=True, exist_ok=True)
        arguments = ["--export", str(self.paths.export)]
        if self.company:
            arguments.extend(["--company", self.company])
        self._pipeline(*arguments)
        return PhaseOutput(detail="Collected configured Role sources")

    def _descriptions(self, _record: DailyRunRecord) -> PhaseOutput:
        self._pipeline("--fetch-descriptions")
        return PhaseOutput(detail="Fetched missing Role descriptions")

    def _deepseek(self, _record: DailyRunRecord) -> PhaseOutput:
        if not self.environ.get("DEEPSEEK_API_KEY"):
            raise RuntimeError("DEEPSEEK_API_KEY is not configured")
        limit = self.environ.get("DEEPSEEK_DAILY_ENRICH_LIMIT")
        arguments = ["--enrich"]
        if limit:
            arguments.extend(["--enrich-limit", limit])
        self._pipeline(*arguments)
        return PhaseOutput(detail="Enriched new and stale Roles")

    def _salary_audit(self, _record: DailyRunRecord) -> PhaseOutput:
        self._pipeline("--audit-salaries")
        return PhaseOutput(detail="Audited salary outliers")

    def _salary_repair(self, _record: DailyRunRecord) -> PhaseOutput:
        # --repair-all-rows, not just the live board: a soft-deleted Role keeps its
        # estimate and returns with it when a later scrape re-activates it, so a
        # board-only pass leaves a backlog that drips back onto the board.
        self._pipeline(
            "--repair-internship-salaries", "--repair-all-rows", "--repair-apply",
        )
        # The title-grade ceiling, same posture: deterministic, down-only, and swept
        # across all rows so a soft-deleted Role cannot carry a stale estimate back
        # onto the board when a later scrape re-activates it.
        self._pipeline(
            "--repair-grade-ceilings", "--repair-all-rows", "--repair-apply",
        )
        return PhaseOutput(detail="Re-applied deterministic salary repairs")

    def _pocketbase(self, _record: DailyRunRecord) -> PhaseOutput:
        self._run_command(
            [sys.executable, "-m", "hk_jobs.sync_pocketbase"],
            cwd=self.paths.repo,
            check=True,
            text=True,
        )
        return PhaseOutput(detail="Refreshed the verification mirror")

    def _linkedin_fetch(self, _record: DailyRunRecord) -> PhaseOutput:
        self._pipeline("--fetch-posts")
        return PhaseOutput(detail="Applied the watchlist's owned cadence decision")

    def _linkedin_discovery(self, _record: DailyRunRecord) -> PhaseOutput:
        if self._now().astimezone(ZoneInfo("Asia/Hong_Kong")).isoweekday() != 1:
            return PhaseOutput(
                status=PhaseStatus.SKIPPED,
                detail="Weekly discovery runs on Mondays in Hong Kong",
            )
        self._pipeline("--posts-discovery")
        return PhaseOutput(detail="Ran weekly LinkedIn discovery")

    def _linkedin_promote(self, _record: DailyRunRecord) -> PhaseOutput:
        self._pipeline("--promote-posts")
        return PhaseOutput(detail="Classified and promoted eligible LinkedIn posts")

    def _backup(self, _record: DailyRunRecord) -> PhaseOutput:
        self._pipeline("--backup")
        return PhaseOutput(detail="Created the rolling local backup")

    def _publish(self, record: DailyRunRecord) -> PhaseOutput:
        url = self.environ.get("PIPELINE_DATABASE_SYNC_URL", "")
        token = self.environ.get("PIPELINE_SYNC_TOKEN", "")
        if not url or not token:
            raise RuntimeError("Railway publication URL or token is not configured")
        digest = self._sha256(self.paths.database)
        packed = tempfile.NamedTemporaryFile(prefix="daily-run-", suffix=".db.gz", delete=False)
        packed_path = Path(packed.name)
        packed.close()
        try:
            with (
                self.paths.database.open("rb") as source,
                gzip.open(packed_path, "wb", compresslevel=1) as target,
            ):
                shutil.copyfileobj(source, target, 1024 * 1024)
            with packed_path.open("rb") as snapshot:
                response = self._http_post(
                    url,
                    headers={
                        "X-Pipeline-Sync-Token": token,
                        "X-Pipeline-Run-Id": record.run_id,
                        "X-Pipeline-Snapshot-SHA256": digest,
                        "X-Pipeline-Source-Url": record.source_run_url or "",
                    },
                    files={"snapshot": ("jobs.db.gz", snapshot, "application/gzip")},
                    timeout=180,
                )
            response.raise_for_status()
        finally:
            packed_path.unlink(missing_ok=True)
        return PhaseOutput(
            detail="Published the completed catalogue to Railway",
            facts={
                "published_sha256": digest,
                "published_at": self._now().isoformat(),
            },
        )

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()


def collect_database_facts(record: DailyRunRecord, database: str | Path) -> None:
    """Attach bounded market facts to the record after catalogue-changing work."""
    path = Path(database)
    if not path.exists():
        return
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row

        def scalar(sql: str, default: Any = 0) -> Any:
            try:
                row = conn.execute(sql).fetchone()
                return row[0] if row and row[0] is not None else default
            except sqlite3.Error:
                return default

        active = int(scalar("SELECT COUNT(*) FROM jobs WHERE is_active=1"))
        missing = int(
            scalar(
                "SELECT COUNT(*) FROM jobs WHERE is_active=1 "
                "AND TRIM(COALESCE(description_clean,''))=''"
            )
        )
        enriched = int(
            scalar(
                "SELECT COUNT(*) FROM jobs j JOIN job_enrichments e "
                "ON j.source=e.source AND j.source_id=e.source_id WHERE j.is_active=1"
            )
        )
        record.quality.update(
            {
                "active_roles": active,
                "missing_descriptions": missing,
                "description_coverage_pct": round(100 * (active - missing) / active, 1)
                if active
                else 0.0,
                "enrichment_coverage_pct": round(100 * enriched / active, 1) if active else 0.0,
            }
        )
        try:
            rows = conn.execute(
                """SELECT source, COUNT(*) companies, SUM(status='success') successful,
                          SUM(status='failed') failed, SUM(jobs_found) roles_found,
                          ROUND(SUM(runtime_seconds),1) runtime_seconds
                   FROM pipeline_company_runs
                   WHERE run_id=? GROUP BY source ORDER BY source""",
                (record.run_id,),
            ).fetchall()
            record.source_health = [dict(row) for row in rows]
        except sqlite3.Error:
            record.source_health = []
        try:
            rows = conn.execute(
                """SELECT calls, roles_processed, prompt_cache_hit_tokens,
                          prompt_cache_miss_tokens, completion_tokens, estimated_cost_usd
                   FROM ai_usage WHERE run_id=?""",
                (record.run_id,),
            ).fetchall()
            record.ai_usage.update(
                {
                    "calls": sum(int(row["calls"]) for row in rows),
                    "roles_processed": sum(int(row["roles_processed"]) for row in rows),
                    "estimated_cost_usd": round(
                        sum(float(row["estimated_cost_usd"]) for row in rows), 4
                    ),
                }
            )
        except sqlite3.Error:
            pass
