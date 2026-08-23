"""The Manager-grade floor backfill only applies its own new policy."""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "apply_manager_grade_floors.py"


def _add_role(
    conn: sqlite3.Connection,
    source_id: str,
    *,
    company_slug: str,
    title: str,
    tier: str | None,
    role: str | None,
    minimum: int,
    maximum: int,
    pinned: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO jobs (source, source_id, company, company_slug, title) VALUES (?, ?, ?, ?, ?)",
        ("longtail", source_id, "Example employer", company_slug, title),
    )
    conn.execute(
        """
        INSERT INTO job_enrichments
            (source, source_id, salary_tier, salary_role, salary_estimated_min,
             salary_estimated_max, manually_edited_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("longtail", source_id, tier, role, minimum, maximum, pinned),
    )


def test_backfill_applies_only_manager_floor_to_unpinned_recognised_rows(tmp_path: Path) -> None:
    database = tmp_path / "jobs.db"
    conn = sqlite3.connect(database)
    conn.executescript(
        """
        CREATE TABLE jobs (
            source TEXT, source_id TEXT, company TEXT, company_slug TEXT,
            title TEXT, is_active INTEGER DEFAULT 1,
            PRIMARY KEY (source, source_id)
        );
        CREATE TABLE job_enrichments (
            source TEXT, source_id TEXT, seniority TEXT, salary_tier TEXT,
            salary_role TEXT, salary_estimated_min INTEGER, salary_estimated_max INTEGER,
            manually_edited_at TEXT, PRIMARY KEY (source, source_id)
        );
        """
    )
    _add_role(
        conn, "small", company_slug="small-firm", title="Manager, Treasury Operations",
        tier="back_office_operations", role="operations_general", minimum=25_000, maximum=39_000,
    )
    _add_role(
        conn, "large", company_slug="hsbc-hk", title="Manager, Credit Risk",
        tier="middle_office", role="risk_credit", minimum=35_000, maximum=48_000,
    )
    _add_role(
        conn, "assistant", company_slug="small-firm", title="Assistant Manager, Treasury Operations",
        tier="back_office_operations", role="operations_general", minimum=25_000, maximum=31_000,
    )
    _add_role(
        conn, "pinned", company_slug="small-firm", title="Manager, Treasury Operations",
        tier="back_office_operations", role="operations_general", minimum=25_000, maximum=39_000,
        pinned="2026-08-22T00:00:00Z",
    )
    conn.commit()
    conn.close()

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--db", str(database), "--apply", "--no-backup"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Manager-grade floor corrections: 2" in result.stdout
    assert "Pinned matches skipped: 1" in result.stdout

    conn = sqlite3.connect(database)
    values = dict(
        conn.execute(
            "SELECT source_id, printf('%d-%d', salary_estimated_min, salary_estimated_max) FROM job_enrichments"
        ).fetchall()
    )
    conn.close()
    assert values == {
        "small": "40000-50000",
        "large": "50000-60000",
        "assistant": "25000-31000",
        "pinned": "25000-39000",
    }
