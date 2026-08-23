"""The employer-overlay backfill is narrow, deterministic, and admin-safe."""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "apply_employer_salary_overlays.py"
AM_SLUG = "alvarez-marsal-corporate-finance-limited"
AM_TITLE = "Manager - Project Delivery and Operations (Infrastructure & Capital Projects)"


def _add_role(
    conn: sqlite3.Connection,
    source_id: str,
    title: str,
    company_slug: str,
    minimum: int,
    maximum: int,
    *,
    pinned: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO jobs (source, source_id, company, company_slug, title, source_tier) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("longtail", source_id, "Example employer", company_slug, title, "boutique"),
    )
    conn.execute(
        "INSERT INTO job_enrichments VALUES (?, ?, ?, ?, ?)",
        ("longtail", source_id, minimum, maximum, pinned),
    )


def test_backfill_applies_only_matching_unpinned_employer_overlays(tmp_path: Path) -> None:
    database = tmp_path / "jobs.db"
    conn = sqlite3.connect(database)
    conn.executescript(
        """
        CREATE TABLE jobs (
            source TEXT, source_id TEXT, company TEXT, company_slug TEXT,
            title TEXT, source_tier TEXT, is_active INTEGER DEFAULT 1,
            PRIMARY KEY (source, source_id)
        );
        CREATE TABLE job_enrichments (
            source TEXT, source_id TEXT, salary_estimated_min INTEGER,
            salary_estimated_max INTEGER, manually_edited_at TEXT,
            PRIMARY KEY (source, source_id)
        );
        """
    )
    _add_role(conn, "match", AM_TITLE, AM_SLUG, 17_500, 35_000)
    _add_role(conn, "unrelated", "Manager (Financial Services – M&A / Deals)", AM_SLUG, 17_500, 35_000)
    _add_role(conn, "pinned", AM_TITLE, AM_SLUG, 30_000, 40_000, pinned="2026-08-22T00:00:00Z")
    conn.commit()
    conn.close()

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--db", str(database), "--apply", "--no-backup"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Overlay corrections: 1" in result.stdout
    assert "Pinned matches skipped: 1" in result.stdout

    conn = sqlite3.connect(database)
    values = dict(
        conn.execute(
            "SELECT source_id, printf('%d-%d', salary_estimated_min, salary_estimated_max) FROM job_enrichments"
        ).fetchall()
    )
    conn.close()
    assert values == {"match": "45000-60000", "unrelated": "17500-35000", "pinned": "30000-40000"}
