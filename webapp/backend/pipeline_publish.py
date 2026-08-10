"""Atomic publication of a completed pipeline database into the live catalogue.

GitHub Actions owns scraped catalogue data. Railway also owns data inside the
same SQLite file: approved recruiter roles (``source='direct'``), Ultimate
Admin corrections, and publication receipts. Publication therefore imports
the pipeline-owned tables in one transaction instead of replacing jobs.db.
Readers see either the old catalogue or the complete new one.
"""

from __future__ import annotations

import gzip
import hashlib
import re
import shutil
import sqlite3
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO

import job_edit


class InvalidSnapshot(ValueError):
    """The uploaded database is corrupt, incompatible, or dangerously small."""


class PublishConflict(RuntimeError):
    """The run was already published with different content, or another runs."""


_LOCK = threading.Lock()
_MAX_UNCOMPRESSED = 768 * 1024 * 1024
_REQUIRED_TABLES = ("jobs", "job_enrichments", "job_history", "company_metrics")
_PIPELINE_TABLES = (
    "jobs",
    "job_enrichments",
    "job_history",
    "company_metrics",
    "salary_audit_log",
    "linkedin_posts",
    "recruiter_fetch_state",
    "vendor_costs",
    "run_cadence",
    "tech_title_cache",
)
# Columns introduced by pipeline migrations that the web service can safely
# add to an older persistent volume. Never infer DDL from an uploaded file.
_ADDITIVE_COLUMNS = {("jobs", "closed_at"): "TEXT"}
_SYNC_DDL = """
CREATE TABLE IF NOT EXISTS pipeline_catalog_sync (
    source_run_id TEXT PRIMARY KEY,
    snapshot_sha256 TEXT NOT NULL,
    source_run_url TEXT,
    received_at TEXT NOT NULL,
    active_jobs INTEGER NOT NULL
)
"""
_FTS_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS jobs_fts USING fts5(
    title, title_en, company, skills, description,
    tokenize = 'porter unicode61 remove_diacritics 2'
)
"""
_VOCAB_DDL = """
CREATE TABLE IF NOT EXISTS search_vocab (
    word TEXT NOT NULL PRIMARY KEY,
    first TEXT NOT NULL,
    len INTEGER NOT NULL,
    doc_count INTEGER NOT NULL
)
"""
_TOKEN = re.compile(r"[^\w一-鿿]+", re.UNICODE)


def _table_exists(conn: sqlite3.Connection, schema: str, table: str) -> bool:
    return (
        conn.execute(
            f"SELECT 1 FROM {schema}.sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        is not None
    )


def _columns(conn: sqlite3.Connection, schema: str, table: str) -> list[str]:
    # schema/table are selected exclusively from fixed internal constants.
    return [row[1] for row in conn.execute(f"PRAGMA {schema}.table_info({table})")]


def _decompress(upload: BinaryIO, expected_sha256: str) -> Path:
    temp = tempfile.NamedTemporaryFile(prefix="finex-catalog-", suffix=".db", delete=False)
    path = Path(temp.name)
    digest = hashlib.sha256()
    size = 0
    try:
        with temp, gzip.GzipFile(fileobj=upload, mode="rb") as source:
            while chunk := source.read(1024 * 1024):
                size += len(chunk)
                if size > _MAX_UNCOMPRESSED:
                    raise InvalidSnapshot("Snapshot exceeds the 768 MB safety limit")
                digest.update(chunk)
                temp.write(chunk)
    except (gzip.BadGzipFile, EOFError, OSError) as exc:
        path.unlink(missing_ok=True)
        raise InvalidSnapshot("Snapshot is not a valid gzip archive") from exc
    if not size:
        path.unlink(missing_ok=True)
        raise InvalidSnapshot("Snapshot is empty")
    if digest.hexdigest() != expected_sha256.lower():
        path.unlink(missing_ok=True)
        raise InvalidSnapshot("Snapshot SHA-256 does not match the upload")
    return path


def _validate(incoming_path: Path, live_path: Path) -> int:
    try:
        conn = sqlite3.connect(f"file:{incoming_path}?mode=ro", uri=True)
        try:
            if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise InvalidSnapshot("SQLite integrity check failed")
            missing = [t for t in _REQUIRED_TABLES if not _table_exists(conn, "main", t)]
            if missing:
                raise InvalidSnapshot(f"Snapshot is missing tables: {', '.join(missing)}")
            active = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE is_active=1 AND source<>'direct'"
            ).fetchone()[0]
            if active < 1:
                raise InvalidSnapshot("Snapshot contains no active pipeline roles")
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        raise InvalidSnapshot("Snapshot is not a valid SQLite database") from exc

    if live_path.exists():
        with sqlite3.connect(live_path) as live:
            current = live.execute(
                "SELECT COUNT(*) FROM jobs WHERE is_active=1 AND source<>'direct'"
            ).fetchone()[0]
        if current >= 100 and active < max(25, int(current * 0.25)):
            raise InvalidSnapshot(
                f"Snapshot has only {active} active roles versus {current} live; "
                "publication stopped"
            )
    return active


def _backup(live_path: Path, run_id: str) -> Path:
    backup_dir = live_path.parent / "catalog-backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    safe_run = re.sub(r"[^A-Za-z0-9_.-]", "-", run_id)[:80]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = backup_dir / f"jobs-before-{safe_run}-{stamp}.db.gz"
    raw = tempfile.NamedTemporaryFile(prefix="finex-backup-", suffix=".db", delete=False)
    raw_path = Path(raw.name)
    raw.close()
    try:
        with sqlite3.connect(live_path) as source, sqlite3.connect(raw_path) as dest:
            source.backup(dest)
        with raw_path.open("rb") as source, gzip.open(target, "wb", compresslevel=1) as dest:
            shutil.copyfileobj(source, dest, 1024 * 1024)
    finally:
        raw_path.unlink(missing_ok=True)
    ordered = sorted(
        backup_dir.glob("jobs-before-*.db.gz"), key=lambda item: item.stat().st_mtime, reverse=True
    )
    for old in ordered[3:]:
        old.unlink(missing_ok=True)
    return target


def export_pipeline_snapshot(live_path: Path) -> tuple[Path, str]:
    """Return a gzipped, consistent pipeline-only copy of Railway's jobs DB.

    The scheduled Action needs the latest enrichment state, but it must not
    download Railway-owned direct roles, Ultimate Admin audit history, or sync
    receipts into a public build artifact. SQLite's backup API gives a coherent
    point-in-time copy while the live service remains online.
    """
    raw = tempfile.NamedTemporaryFile(prefix="finex-restore-", suffix=".db", delete=False)
    raw_path = Path(raw.name)
    raw.close()
    packed = tempfile.NamedTemporaryFile(
        prefix="finex-restore-", suffix=".db.gz", delete=False
    )
    packed_path = Path(packed.name)
    packed.close()
    try:
        with sqlite3.connect(live_path) as source, sqlite3.connect(raw_path) as dest:
            source.backup(dest)
        with sqlite3.connect(raw_path) as snapshot:
            snapshot.execute("DELETE FROM job_enrichments WHERE source='direct'")
            snapshot.execute("DELETE FROM jobs WHERE source='direct'")
            for table in ("admin_edits", "pipeline_snapshot_sync", "pipeline_catalog_sync"):
                if _table_exists(snapshot, "main", table):
                    snapshot.execute(f'DELETE FROM "{table}"')
            _rebuild_search(snapshot)
        digest = hashlib.sha256()
        with raw_path.open("rb") as source, gzip.open(
            packed_path, "wb", compresslevel=1
        ) as dest:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
                dest.write(chunk)
        return packed_path, digest.hexdigest()
    except Exception:
        packed_path.unlink(missing_ok=True)
        raise
    finally:
        raw_path.unlink(missing_ok=True)


def _copy_rows(conn: sqlite3.Connection, table: str) -> None:
    live_cols = _columns(conn, "main", table)
    incoming_cols = _columns(conn, "incoming", table)
    # An upgraded database and a freshly-created one can have identical columns
    # in different physical order (ALTER TABLE appends). Address every column by
    # name; only a genuinely different set is incompatible.
    missing_live = set(incoming_cols) - set(live_cols)
    unsupported = {
        column for column in missing_live if (table, column) not in _ADDITIVE_COLUMNS
    }
    if unsupported or set(live_cols) - set(incoming_cols):
        raise InvalidSnapshot(f"Incompatible {table} schema")
    for column in sorted(missing_live):
        definition = _ADDITIVE_COLUMNS[(table, column)]
        conn.execute(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {definition}')
    live_cols = _columns(conn, "main", table)
    names = ", ".join(f'"{name}"' for name in live_cols)
    conn.execute(f'DELETE FROM "{table}"')
    conn.execute(f'INSERT INTO "{table}" ({names}) SELECT {names} FROM incoming."{table}"')


def _rebuild_search(conn: sqlite3.Connection) -> int:
    conn.execute(_FTS_DDL)
    conn.execute(_VOCAB_DDL)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_search_vocab_lookup ON search_vocab(first, len)")
    conn.execute("DELETE FROM jobs_fts")
    conn.execute("DELETE FROM search_vocab")
    rows = conn.execute(
        """
        SELECT j.rowid, j.title, COALESCE(e.title_en, ''), j.company,
               COALESCE(e.required_skills, ''), COALESCE(j.description_clean, '')
        FROM jobs j LEFT JOIN job_enrichments e
          ON j.source=e.source AND j.source_id=e.source_id
        """
    ).fetchall()
    if rows:
        conn.executemany(
            "INSERT INTO jobs_fts(rowid,title,title_en,company,skills,description) "
            "VALUES (?,?,?,?,?,?)",
            rows,
        )
    vocab: dict[str, int] = {}
    for row in rows:
        words: set[str] = set()
        for value in row[1:]:
            words.update(
                word
                for word in _TOKEN.split(str(value).lower())
                if len(word) >= 2 and word.isascii()
            )
        for word in words:
            vocab[word] = vocab.get(word, 0) + 1
    if vocab:
        conn.executemany(
            "INSERT INTO search_vocab(word,first,len,doc_count) VALUES (?,?,?,?)",
            [(word, word[0], len(word), count) for word, count in vocab.items()],
        )
    return len(rows)


def _rows_as_dicts(conn: sqlite3.Connection, table: str, where: str) -> list[dict[str, Any]]:
    cursor = conn.execute(f'SELECT * FROM "{table}" WHERE {where}')
    names = [item[0] for item in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def _insert_dicts(conn: sqlite3.Connection, table: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    cols = list(rows[0])
    names = ", ".join(f'"{name}"' for name in cols)
    marks = ", ".join("?" for _ in cols)
    conn.executemany(
        f'INSERT OR REPLACE INTO "{table}" ({names}) VALUES ({marks})',
        [[row[name] for name in cols] for row in rows],
    )


def publish_snapshot(
    live_path: Path,
    upload: BinaryIO,
    *,
    expected_sha256: str,
    source_run_id: str,
    source_run_url: str | None,
) -> dict[str, Any]:
    """Validate, back up, and transactionally publish one gzipped jobs.db."""
    if not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256):
        raise InvalidSnapshot("Snapshot SHA-256 must contain 64 hexadecimal characters")
    if not source_run_id or len(source_run_id) > 100:
        raise InvalidSnapshot("Pipeline run ID is missing or too long")
    if not _LOCK.acquire(blocking=False):
        raise PublishConflict("Another catalogue publication is already running")
    incoming_path: Path | None = None
    try:
        incoming_path = _decompress(upload, expected_sha256)
        incoming_active = _validate(incoming_path, live_path)
        with sqlite3.connect(live_path) as check:
            check.execute(_SYNC_DDL)
            prior = check.execute(
                "SELECT snapshot_sha256, active_jobs, received_at FROM pipeline_catalog_sync "
                "WHERE source_run_id=?",
                (source_run_id,),
            ).fetchone()
            if prior:
                if prior[0] != expected_sha256.lower():
                    raise PublishConflict("This run ID was already published with another snapshot")
                return {
                    "source_run_id": source_run_id,
                    "active_jobs": prior[1],
                    "received_at": prior[2],
                    "already_published": True,
                }

        _backup(live_path, source_run_id)
        conn = sqlite3.connect(live_path, timeout=60)
        try:
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute("ATTACH DATABASE ? AS incoming", (str(incoming_path),))
            direct_jobs = _rows_as_dicts(conn, "jobs", "source='direct'")
            direct_enrichments = _rows_as_dicts(conn, "job_enrichments", "source='direct'")
            conn.execute("BEGIN IMMEDIATE")
            for table in _PIPELINE_TABLES:
                if _table_exists(conn, "main", table) and _table_exists(conn, "incoming", table):
                    _copy_rows(conn, table)
            _insert_dicts(conn, "jobs", direct_jobs)
            _insert_dicts(conn, "job_enrichments", direct_enrichments)
            job_edit.reapply_recorded_edits(conn)
            _rebuild_search(conn)
            received_at = datetime.now(timezone.utc).isoformat()
            active_jobs = conn.execute("SELECT COUNT(*) FROM jobs WHERE is_active=1").fetchone()[0]
            if active_jobs < incoming_active:
                raise InvalidSnapshot("Published role count failed its consistency check")
            conn.execute(_SYNC_DDL)
            conn.execute(
                "INSERT INTO pipeline_catalog_sync "
                "(source_run_id,snapshot_sha256,source_run_url,received_at,active_jobs) "
                "VALUES (?,?,?,?,?)",
                (source_run_id, expected_sha256.lower(), source_run_url, received_at, active_jobs),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return {
            "source_run_id": source_run_id,
            "active_jobs": active_jobs,
            "received_at": received_at,
            "already_published": False,
        }
    finally:
        if incoming_path:
            incoming_path.unlink(missing_ok=True)
        _LOCK.release()
