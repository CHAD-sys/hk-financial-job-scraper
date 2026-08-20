"""
Admin Mode — the HTTP surface signed-in admins get that an ordinary Seeker
does not: the recruiter-submission queue (Verification), today's pipeline run,
a deep read-only analytics pass over jobs.db, and direct read/write onto a
single job's row and its enrichment.

Every human-facing route here sits behind `require_admin` (the account-directory
and resume routes ALSO sit behind `require_super_admin`), both dependencies
main.py hands to `build_router()`.  The machine-facing `/pipeline/database` and
`/pipeline/operations` routes use a separate timing-safe shared secret so the
scheduled GitHub pipeline can publish its catalogue and completed Daily Run
Record without possessing a human session.

Writes to jobs.db are limited to submission approval, admin job edits, and the
authenticated daily publication routes described above. All other
dashboard queries use the read-only `get_db` connection.

Several queries below touch `job_history` / `company_metrics`, tables the
pipeline (hk_jobs/migrations.py, phase 11) creates but this backend never
migrates itself and a bare test stand-in (tests/support.py) never seeds. Every
one of those queries is wrapped in `_scalar`/`_rows`, which returns a safe
default instead of raising — a fresh or stand-in database must show an empty
dashboard, never a 500.
"""

from __future__ import annotations

import hmac
import json
import re
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote
from zoneinfo import ZoneInfo

import admin_intelligence
import employers_store
import job_edit
import learning_content
import pipeline_publish
import seekers_store
import submissions
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Body,
    Depends,
    File,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from starlette.background import BackgroundTask
from starlette.responses import FileResponse, Response

from hk_jobs.daily_run.model import DailyRunRecord

_HONG_KONG = ZoneInfo("Asia/Hong_Kong")

_PIPELINE_OPERATIONS_DDL = """
CREATE TABLE IF NOT EXISTS pipeline_operations (
    run_id TEXT PRIMARY KEY, scraped_date TEXT NOT NULL, source_run_url TEXT,
    status TEXT NOT NULL CHECK (status IN ('success', 'warning', 'failed', 'running')),
    started_at TEXT, finished_at TEXT, restore_source TEXT, restore_sha256 TEXT,
    published_sha256 TEXT, published_at TEXT,
    phases_json TEXT NOT NULL DEFAULT '[]', record_json TEXT, recorded_at TEXT NOT NULL
)
"""

_PHASE_KEYS = (
    ("restore", "Restore"),
    ("scrape", "Scrape"),
    ("descriptions", "Descriptions"),
    ("deepseek", "DeepSeek"),
    ("salary_audit", "Salary audit"),
    ("linkedin_promote", "LinkedIn promotion"),
    ("publish", "Railway publish"),
)
_PHASE_STATUSES = {"success", "warning", "failed", "skipped", "running", "not_recorded"}
_LEGACY_PHASE_LABELS = {**dict(_PHASE_KEYS), "linkedin": "LinkedIn"}


def _ensure_pipeline_operations_schema(conn: sqlite3.Connection) -> None:
    conn.execute(_PIPELINE_OPERATIONS_DDL)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(pipeline_operations)")}
    if "record_json" not in columns:
        conn.execute("ALTER TABLE pipeline_operations ADD COLUMN record_json TEXT")


# ── Router ─────────────────────────────────────────────────────────────────────


def build_router(
    *,
    cfg: Callable[[Request], Any],
    get_db: Callable[[Request], sqlite3.Connection],
    get_write_db: Callable[[Request], sqlite3.Connection],
    require_admin: Callable[[Request], dict],
    require_super_admin: Callable[[Request], dict],
    on_pipeline_published: Callable[[Request], None] | None = None,
) -> APIRouter:
    """
    Assemble the admin router against main.py's own dependencies.

    Taking them as arguments (rather than importing main.py) is what keeps this
    module free of the one import that would make it circular: main.py imports
    THIS module to mount the router, so this module cannot import main.py back.

    `on_pipeline_published`, if given, runs as a FastAPI BackgroundTask after
    `POST /pipeline/database` successfully swaps in a new catalogue — the one
    moment this Railway process is guaranteed to hold a freshly-enriched
    jobs.db beside the live seekers.db (see alerts.py / main.py's
    `_trigger_weekly_alerts`). A BackgroundTask, not an inline call: whatever
    it does must never add latency to, or fail, the publication response
    GitHub Actions is waiting on.
    """
    router = APIRouter(prefix="/api/admin", tags=["admin"])

    def _queue_path(request: Request) -> Path:
        return cfg(request).submissions_dir / "submitted_roles.jsonl"

    def _require_pipeline_token(request: Request, supplied: str | None) -> None:
        expected = cfg(request).pipeline_sync_token
        if not expected:
            raise HTTPException(status_code=503, detail="Pipeline sync is disabled")
        if not supplied or not hmac.compare_digest(supplied, expected):
            raise HTTPException(status_code=401, detail="Invalid pipeline sync token")

    @router.get("/pipeline/database")
    def download_pipeline_database(
        request: Request,
        sync_token: str | None = Header(default=None, alias="X-Pipeline-Sync-Token"),
    ):
        """Give GitHub Actions a consistent pipeline-only restore point."""
        _require_pipeline_token(request, sync_token)
        try:
            restore_point = pipeline_publish.create_restore_point(Path(cfg(request).jobs_db))
        except sqlite3.OperationalError as exc:
            raise HTTPException(
                status_code=503, detail="Catalogue snapshot is temporarily busy"
            ) from exc
        return FileResponse(
            restore_point.path,
            media_type="application/gzip",
            filename="jobs.db.gz",
            headers={"X-Pipeline-Snapshot-SHA256": restore_point.sha256},
            background=BackgroundTask(restore_point.path.unlink, missing_ok=True),
        )

    @router.post("/pipeline/database")
    def ingest_pipeline_database(
        request: Request,
        background_tasks: BackgroundTasks,
        snapshot: UploadFile = File(...),
        sync_token: str | None = Header(default=None, alias="X-Pipeline-Sync-Token"),
        source_run_id: str | None = Header(default=None, alias="X-Pipeline-Run-Id"),
        snapshot_sha256: str | None = Header(default=None, alias="X-Pipeline-Snapshot-SHA256"),
        source_run_url: str | None = Header(default=None, alias="X-Pipeline-Source-Url"),
    ):
        """Publish a completed, checksummed pipeline jobs.db into Railway."""
        _require_pipeline_token(request, sync_token)
        try:
            result = pipeline_publish.publish_catalogue(
                Path(cfg(request).jobs_db),
                snapshot.file,
                identity=pipeline_publish.PublicationIdentity(
                    snapshot_sha256=snapshot_sha256 or "",
                    source_run_id=source_run_id or "",
                    source_run_url=source_run_url,
                ),
            )
        except pipeline_publish.InvalidSnapshot as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        except pipeline_publish.PublishConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        except sqlite3.OperationalError as exc:
            raise HTTPException(
                status_code=503, detail="Catalogue publication is temporarily busy"
            ) from exc
        if on_pipeline_published is not None:
            background_tasks.add_task(on_pipeline_published, request)
        return result

    @router.post("/pipeline/operations")
    def ingest_pipeline_operations(
        request: Request,
        body: dict = Body(...),
        sync_token: str | None = Header(default=None, alias="X-Pipeline-Sync-Token"),
    ):
        """Persist the authoritative Daily Run Record, including failed phases."""
        _require_pipeline_token(request, sync_token)
        canonical_record = None
        if body.get("schema_version") is not None:
            try:
                canonical_record = DailyRunRecord.from_dict(body)
            except (KeyError, TypeError, ValueError) as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"invalid Daily Run Record: {exc}",
                ) from None
            body = {
                **body,
                "scraped_date": canonical_record.operating_date,
                "phases": canonical_record.to_dict()["phases"],
            }
        run_id = str(body.get("run_id") or "").strip()
        if not run_id or len(run_id) > 100:
            raise HTTPException(status_code=400, detail="run_id is required")
        try:
            scraped_date = date.fromisoformat(str(body["scraped_date"])).isoformat()
        except (KeyError, TypeError, ValueError):
            raise HTTPException(
                status_code=400,
                detail="scraped_date must be ISO YYYY-MM-DD",
            ) from None
        status = str(body.get("status") or "").strip()
        if status not in {"success", "warning", "failed", "running"}:
            raise HTTPException(status_code=400, detail="invalid pipeline status")
        raw_phases = body.get("phases")
        if not isinstance(raw_phases, list) or len(raw_phases) > 20:
            raise HTTPException(status_code=400, detail="phases must be a list of at most 20 items")
        labels = (
            {phase.key: phase.label for phase in canonical_record.phases}
            if canonical_record
            else _LEGACY_PHASE_LABELS
        )
        phases = []
        seen: set[str] = set()
        for raw in raw_phases:
            key = str(raw.get("key") or "").strip()
            phase_status = str(raw.get("status") or "").strip()
            if key not in labels or key in seen or phase_status not in _PHASE_STATUSES:
                raise HTTPException(status_code=400, detail="invalid or duplicate pipeline phase")
            seen.add(key)
            duration = raw.get("duration_seconds")
            try:
                duration = None if duration is None else max(0, int(duration))
            except (TypeError, ValueError):
                raise HTTPException(
                    status_code=400,
                    detail="phase duration must be seconds",
                ) from None
            phases.append(
                {
                    "key": key,
                    "label": labels[key],
                    "status": phase_status,
                    "duration_seconds": duration,
                    "detail": " ".join(str(raw.get("detail") or "").split())[:300] or None,
                }
            )
        hashes = {}
        for key in ("restore_sha256", "published_sha256"):
            value = str(body.get(key) or "").strip().lower() or None
            if value is not None and not re.fullmatch(r"[0-9a-f]{64}", value):
                raise HTTPException(status_code=400, detail=f"{key} must be SHA-256")
            hashes[key] = value
        stamp = datetime.now(_HONG_KONG).isoformat()
        with get_write_db(request) as conn:
            with conn:
                _ensure_pipeline_operations_schema(conn)
                conn.execute(
                    """
                    INSERT INTO pipeline_operations (
                        run_id, scraped_date, source_run_url, status, started_at,
                        finished_at, restore_source, restore_sha256, published_sha256,
                        published_at, phases_json, record_json, recorded_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (run_id) DO UPDATE SET
                        source_run_url=excluded.source_run_url, status=excluded.status,
                        started_at=excluded.started_at, finished_at=excluded.finished_at,
                        restore_source=excluded.restore_source,
                        restore_sha256=excluded.restore_sha256,
                        published_sha256=excluded.published_sha256,
                        published_at=excluded.published_at,
                        phases_json=excluded.phases_json,
                        record_json=excluded.record_json,
                        recorded_at=excluded.recorded_at
                    """,
                    (
                        run_id,
                        scraped_date,
                        body.get("source_run_url"),
                        status,
                        body.get("started_at"),
                        body.get("finished_at"),
                        body.get("restore_source"),
                        hashes["restore_sha256"],
                        hashes["published_sha256"],
                        body.get("published_at"),
                        json.dumps(phases, separators=(",", ":")),
                        json.dumps(canonical_record.to_dict(), separators=(",", ":"))
                        if canonical_record
                        else None,
                        stamp,
                    ),
                )
                conn.execute(
                    "DELETE FROM pipeline_operations "
                    "WHERE datetime(recorded_at) < datetime('now', '-90 days')"
                )
        return {"run_id": run_id, "status": status, "phases": len(phases), "recorded_at": stamp}

    @router.post("/learning/refresh")
    def refresh_learning_content(
        request: Request,
        force: bool = Query(default=False),
        sync_token: str | None = Header(default=None, alias="X-Pipeline-Sync-Token"),
    ):
        """Refresh Learning metadata while preserving every last-known-good source."""

        _require_pipeline_token(request, sync_token)
        result = learning_content.refresh_content(
            Path(cfg(request).learning_content_path), force=force
        )
        snapshot = result["snapshot"]
        if result["status"] == "failed" and not snapshot["events"] and not snapshot["videos"]:
            raise HTTPException(status_code=502, detail="Both Learning sources failed")
        return result

    # ── Recruiter submissions ───────────────────────────────────────────────

    @router.get("/submissions")
    def list_submissions(
        request: Request,
        status: str = Query("pending", pattern="^(pending|approved|rejected|all)$"),
        _admin: dict = Depends(require_admin),
    ):
        rows = submissions.load_queue(_queue_path(request))
        out = []
        for row in rows:
            row_status = row.get("status", "pending")
            if status != "all" and row_status != status:
                continue
            out.append({**row, "id": submissions.source_id_for(row), "status": row_status})
        # Newest first — that is what "latest requests" means to someone opening the tab.
        out.sort(key=lambda r: r.get("received_at", ""), reverse=True)
        return out

    @router.post("/submissions/{submission_id}/approve")
    def approve_submission_route(
        submission_id: str, request: Request, _admin: dict = Depends(require_admin)
    ):
        path = _queue_path(request)
        rows = submissions.load_queue(path)
        idx = submissions.find_by_source_id(rows, submission_id)
        if idx is None:
            raise HTTPException(status_code=404, detail="Submission not found")

        row = rows[idx]
        if row.get("status") == "approved":
            return {**row, "id": submission_id}

        try:
            sid = submissions.approve_submission(cfg(request).jobs_db, row)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"Could not publish role: {exc}") from None

        rows[idx] = submissions.mark_approved(row, sid)
        submissions.save_queue(path, rows)
        return {**rows[idx], "id": submission_id}

    @router.post("/submissions/{submission_id}/reject")
    def reject_submission_route(
        submission_id: str,
        request: Request,
        reason: str = Body("", embed=True),
        _admin: dict = Depends(require_admin),
    ):
        path = _queue_path(request)
        rows = submissions.load_queue(path)
        idx = submissions.find_by_source_id(rows, submission_id)
        if idx is None:
            raise HTTPException(status_code=404, detail="Submission not found")

        rows[idx] = submissions.mark_rejected(rows[idx], reason=reason)
        submissions.save_queue(path, rows)
        return {**rows[idx], "id": submission_id}

    # ── Intelligence read model ─────────────────────────────────────────────

    @router.get("/intelligence")
    def intelligence_snapshot(
        request: Request,
        days: int = Query(30, ge=1, le=365),
        admin: dict = Depends(require_admin),
    ):
        with get_db(request) as conn:
            return admin_intelligence.build_admin_intelligence(
                conn, history_days=days, is_super_admin=bool(admin.get("is_super_admin"))
            )

    # ── Ultimate Admin: account directory ───────────────────────────────────
    # Read-only, behind require_super_admin — same posture as Source health /
    # Publication safety / Recommendation health above: not queried or
    # serialised for the other four admins. Two independent stores (ADR 0001),
    # so one response with both lists rather than forcing two round trips.

    @router.get("/accounts")
    def list_accounts_route(_admin: dict = Depends(require_super_admin)):
        return {
            "seekers": seekers_store.get_store().list_accounts(),
            "employers": employers_store.get_store().list_accounts(),
        }

    @router.get("/accounts/seekers/{seeker_id}/interests")
    def get_seeker_interests_route(seeker_id: str, _admin: dict = Depends(require_super_admin)):
        """Fetched lazily, per row, when an admin expands a Seeker — never
        bundled into list_accounts_route, which stays a flat query so it does
        not turn into an N-seeker fan-out of resume/discovery/saved-role reads."""
        store = seekers_store.get_store()
        if store.get_seeker(seeker_id) is None:
            raise HTTPException(status_code=404, detail="Seeker not found")
        return store.interests_for_seeker(seeker_id)

    @router.get("/accounts/seekers/{seeker_id}/resume")
    def download_seeker_resume_route(
        seeker_id: str,
        reason: str = Query("", max_length=200, description="Why this file is being read"),
        admin: dict = Depends(require_super_admin),
    ):
        """Serve a Seeker's resume file to an Ultimate Admin, and log that it happened.

        This exists for troubleshooting — a match that looks wrong is usually a
        gap in `resume_intelligence`'s vocabulary rather than a bad CV, and
        confirming which needs the file. Before this route the only way to read
        the bytes was `railway ssh` onto the volume, which is both fiddlier and
        completely untraced; the point of the route is not that the data became
        more available but that reading it now leaves a record.

        Three things keep it narrow:

        - `require_super_admin`, not `require_admin`. The other four admins see
          the account directory but never this, the same split as job_edit.
        - The audit row is written FIRST. If the log write raises, the download
          fails and no unlogged copy leaves the server.
        - `Content-Disposition: attachment` with an ASCII-safe filename, so a
          PDF cannot render inline in the admin's tab and a crafted filename
          cannot break the header.

        Note this is the only route in the API that returns `file_content`. The
        Seeker's own `/api/me/resume` deliberately still does not — see
        main.py's `_resume_out`.
        """
        store = seekers_store.get_store()
        seeker = store.get_seeker(seeker_id)
        if seeker is None:
            raise HTTPException(status_code=404, detail="Seeker not found")

        resume = store.get_resume(seeker_id, include_document=True)
        if resume is None:
            raise HTTPException(status_code=404, detail="This Seeker has no resume on file")

        store.record_resume_download(
            seeker_id=seeker_id,
            seeker_email=seeker["email"],
            admin_id=admin["id"],
            admin_email=admin["email"],
            filename=resume["filename"],
            size_bytes=resume["size_bytes"],
            reason=(reason or "").strip() or None,
        )

        # RFC 6266: `filename` must stay ASCII, `filename*` carries the real
        # name. Quotes and backslashes are stripped rather than escaped — a
        # resume filename has no business containing either, and dropping them
        # is the one option that cannot terminate the header early.
        safe = "".join(
            ch for ch in resume["filename"] if 32 <= ord(ch) < 127 and ch not in '"\\'
        ) or "resume.pdf"
        quoted = quote(resume["filename"], safe="")
        return Response(
            content=resume["file_content"],
            media_type=resume["media_type"],
            headers={
                "Content-Disposition": f'attachment; filename="{safe}"; filename*=UTF-8\'\'{quoted}',
                # Never let a proxy or the browser keep a copy of this one.
                "Cache-Control": "no-store, private",
            },
        )

    @router.get("/accounts/resume-downloads")
    def list_resume_downloads_route(_admin: dict = Depends(require_super_admin)):
        """Who read whose resume, and when. The other half of the route above —
        an audit trail nobody can read is not an audit trail."""
        return {"downloads": seekers_store.get_store().list_resume_downloads()}

    # ── Admin: direct job edit ──────────────────────────────────────────────
    # Behind require_admin, not require_super_admin: every admin may correct a
    # posting, Ultimate Admin included. That is a deliberate widening (2026-08-20)
    # of what used to be an Ultimate-Admin-only pair of routes — a wrong salary on
    # the board is the most visible defect this product has, and gating its fix
    # behind one account made every correction wait on that account.
    #
    # Nothing else about the write changed. See job_edit.py's module docstring for
    # the allowlist, the audit trail (which now names whichever admin edited), and
    # why every enrichment write here marks the row against future automated
    # correction.

    @router.get("/jobs/{source}/{source_id}")
    def get_job_route(
        source: str,
        source_id: str,
        request: Request,
        _admin: dict = Depends(require_admin),
    ):
        with get_write_db(request) as conn:
            try:
                return job_edit.get_job_for_edit(conn, source, source_id)
            except job_edit.JobNotFound:
                raise HTTPException(status_code=404, detail="Job not found") from None

    @router.patch("/jobs/{source}/{source_id}")
    def patch_job_route(
        source: str,
        source_id: str,
        request: Request,
        body: dict = Body(default={}),
        admin: dict = Depends(require_admin),
    ):
        job_changes = body.get("job") or {}
        enrichment_changes = body.get("enrichment") or {}
        with get_write_db(request) as conn:
            try:
                return job_edit.apply_edit(
                    conn,
                    source,
                    source_id,
                    admin["id"],
                    job_changes=job_changes,
                    enrichment_changes=enrichment_changes,
                )
            except job_edit.JobNotFound:
                raise HTTPException(status_code=404, detail="Job not found") from None
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from None

    return router
