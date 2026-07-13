"""
Database backup utility.

Creates a dated copy of jobs.db in data/backups/. By default it now KEEPS
EVERY daily snapshot (retention_days=0) — the daily state of the DB is treated
as valuable historical data for future trend/analytics features, so we never
prune it automatically. Pass a positive retention_days to re-enable a rolling
window. Safe to run multiple times per day — overwrites the same dated file
rather than accumulating duplicates.

Note: full-DB snapshots are ~35 MB each (~13 GB/year). The lightweight, queryable
trend data lives in the job_history table inside jobs.db; these snapshots are a
belt-and-suspenders raw archive. Compress or archive old ones if disk grows.
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
    retention_days: int = 0,   # 0 = keep every daily snapshot (no pruning)
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

    # Retention: retention_days<=0 keeps EVERY snapshot (default). A positive value
    # re-enables a rolling window that keeps only the N most recent dated files.
    backups = sorted(dst_dir.glob("jobs_*.db"))
    if retention_days > 0 and len(backups) > retention_days:
        for old in backups[:-retention_days]:
            old.unlink()
            logger.info("🗑  Deleted old backup: %s", old.name)
        logger.info("📦 Backups kept: %d / %d days (rolling)", retention_days, retention_days)
    else:
        logger.info("📦 Backups kept: %d (retaining ALL daily snapshots)", len(backups))
    return True
