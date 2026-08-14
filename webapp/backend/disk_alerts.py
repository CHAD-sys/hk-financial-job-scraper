"""
Daily disk-capacity email alert for the Railway volume.

WHY THIS EXISTS
---------------
jobs.db, its WAL, seekers.db (accounts, sessions, Seeker resumes), employers.db,
and the rolling pipeline backups all share one Railway volume. Nothing watches
how full it is. If it fills, the next write anywhere on the volume — a Seeker
resume upload, a WAL checkpoint, a pipeline publish — fails, and the first
anyone hears about it is that failure, live. This checks the mounted volume's
usage and emails the operator while it stays at or above a threshold, so "the
disk is full" is a morning email instead of an incident.

Checked from inside the Railway process (main.py's periodic task), never from
the GitHub Actions pipeline runner — that runner never touches this
filesystem, only this Railway process does (see main.py's _trigger_weekly_alerts
docstring for the same fact about seekers.db).
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

#: (subject, body_text) -> sent?  Matches mailer.send_mail's signature exactly,
#: so production wires mailer.send_mail in directly and tests hand in a stub.
MailSender = Callable[[str, str], bool]

_BYTES_PER_GB = 1024**3


@dataclass(frozen=True)
class DiskUsage:
    """One typed reading of the filesystem a path sits on, in bytes."""

    total_bytes: int
    used_bytes: int
    free_bytes: int

    @property
    def percent_used(self) -> float:
        if self.total_bytes == 0:
            return 0.0
        return (self.used_bytes / self.total_bytes) * 100


def check_disk_usage(path: Path) -> DiskUsage:
    """Usage of the filesystem `path` sits on — the mounted Railway volume in production."""
    total, used, free = shutil.disk_usage(path)
    return DiskUsage(total_bytes=total, used_bytes=used, free_bytes=free)


def _to_gb(n: int) -> float:
    return n / _BYTES_PER_GB


def _compose(usage: DiskUsage, *, path: Path, threshold_pct: int) -> tuple[str, str]:
    subject = f"FinEx Careers: disk at {usage.percent_used:.0f}% ({path})"
    body = (
        f"The Railway volume backing {path} is at {usage.percent_used:.1f}% capacity.\n\n"
        f"Used:  {_to_gb(usage.used_bytes):.2f} GB\n"
        f"Free:  {_to_gb(usage.free_bytes):.2f} GB\n"
        f"Total: {_to_gb(usage.total_bytes):.2f} GB\n\n"
        f"Alert threshold: {threshold_pct}%. This email repeats once a day for as long as "
        "usage stays at or above the threshold, and stops on its own once you free up "
        "space or grow the volume — no need to acknowledge it."
    )
    return subject, body


def maybe_send_capacity_alert(path: Path, *, threshold_pct: int, send: MailSender) -> DiskUsage:
    """
    Check `path`'s filesystem usage and email `send` if it is at or above
    threshold_pct. Always returns the reading, so a caller can log it whether
    or not an email went out — the check itself is not conditional, only the
    email is.
    """
    usage = check_disk_usage(path)
    if usage.percent_used >= threshold_pct:
        subject, body = _compose(usage, path=path, threshold_pct=threshold_pct)
        sent = send(subject, body)
        logger.info(
            "Disk capacity alert: %.1f%% used (threshold %d%%), email sent=%s",
            usage.percent_used,
            threshold_pct,
            sent,
        )
    return usage
