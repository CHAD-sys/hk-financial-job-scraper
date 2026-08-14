"""Behavior contract for the daily disk-capacity alert (disk_alerts.py)."""

from __future__ import annotations

from pathlib import Path

import disk_alerts


def _stub_usage(monkeypatch, *, total: int, used: int) -> None:
    """Replace shutil.disk_usage with a fixed reading, so tests don't depend
    on how full the machine running them actually is."""

    def fake_disk_usage(path):
        return (total, used, total - used)

    monkeypatch.setattr(disk_alerts.shutil, "disk_usage", fake_disk_usage)


class _Recorder:
    """A MailSender that records calls instead of sending anything."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def __call__(self, subject: str, body: str) -> bool:
        self.calls.append((subject, body))
        return True


def test_below_threshold_sends_nothing(monkeypatch, tmp_path):
    _stub_usage(monkeypatch, total=100, used=79)
    sender = _Recorder()

    usage = disk_alerts.maybe_send_capacity_alert(tmp_path, threshold_pct=80, send=sender)

    assert sender.calls == []
    assert usage.percent_used == 79.0


def test_at_threshold_sends_email(monkeypatch, tmp_path):
    _stub_usage(monkeypatch, total=100, used=80)
    sender = _Recorder()

    disk_alerts.maybe_send_capacity_alert(tmp_path, threshold_pct=80, send=sender)

    assert len(sender.calls) == 1


def test_above_threshold_email_reports_percent_and_path(monkeypatch, tmp_path):
    _stub_usage(monkeypatch, total=100, used=92)
    sender = _Recorder()

    disk_alerts.maybe_send_capacity_alert(tmp_path, threshold_pct=80, send=sender)

    subject, body = sender.calls[0]
    assert "92%" in subject
    assert str(tmp_path) in subject
    assert "92.0%" in body
    assert "threshold: 80%" in body.lower()


def test_reading_is_returned_even_when_nothing_is_sent(monkeypatch, tmp_path):
    _stub_usage(monkeypatch, total=100, used=10)
    sender = _Recorder()

    usage = disk_alerts.maybe_send_capacity_alert(tmp_path, threshold_pct=80, send=sender)

    assert sender.calls == []
    assert usage.used_bytes == 10
    assert usage.total_bytes == 100


def test_percent_used_handles_zero_total():
    usage = disk_alerts.DiskUsage(total_bytes=0, used_bytes=0, free_bytes=0)
    assert usage.percent_used == 0.0


def test_check_disk_usage_reads_a_real_path(tmp_path: Path):
    usage = disk_alerts.check_disk_usage(tmp_path)
    assert usage.total_bytes > 0
    assert 0.0 <= usage.percent_used <= 100.0
