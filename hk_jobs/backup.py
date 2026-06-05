"""
Database backup utility.

Creates a dated copy of jobs.db in data/backups/ and enforces a
rolling retention window (default 30 days). Safe to run multiple times
per day — overwrites the same dated file rather than accumulating duplicates.
"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


def backup_database(
    db_path: str = "data/jobs.db",
    backup_dir: str = "data/backups",
    retention_days: int = 30,
) -> bool:
    src = Path(db_path)
    dst_dir = Path(backup_dir)

    if not src.exists():
        logger.error("Database not found: %s", db_path)
        return False

    dst_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d")
    dst = dst_dir / f"jobs_{today}.db"

    shutil.copy2(src, dst)
    size_mb = dst.stat().st_size / (1024 * 1024)
    logger.info("✅ Backup created: %s (%.1f MB)", dst, size_mb)

    # Enforce retention — keep only the N most recent dated files
    backups = sorted(dst_dir.glob("jobs_*.db"))
    if len(backups) > retention_days:
        for old in backups[:-retention_days]:
            old.unlink()
            logger.info("🗑  Deleted old backup: %s", old.name)

    kept = min(len(backups), retention_days)
    logger.info("📦 Backups kept: %d / %d days", kept, retention_days)
    return True
