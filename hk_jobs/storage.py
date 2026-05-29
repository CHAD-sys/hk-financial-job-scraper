"""
SQLite persistence layer.

Uses standard-library sqlite3 with SQL that is intentionally
Postgres-compatible so we can migrate later without rewriting queries.
Soft-delete only: jobs are never removed, just marked is_active=False.
"""

import sqlite3

from hk_jobs.schema import Job


def get_connection(db_path: str) -> sqlite3.Connection:
    """Open (or create) the SQLite database at db_path."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def upsert_job(conn: sqlite3.Connection, job: Job) -> None:
    """Insert a new job or update last_seen_at if it already exists."""
    # Phase 1 stub — schema creation and upsert logic added in a later phase.
    raise NotImplementedError
