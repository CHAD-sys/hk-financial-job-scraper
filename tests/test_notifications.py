from email import message_from_string

from hk_jobs import notifications
from hk_jobs.daily_run import DailyRunRecord, PhaseStatus, profile_for


def test_notification_recipients_support_multiple_addresses_and_deduplicate():
    assert notifications._notification_recipients(
        " amine@finexclub.org, mohamedaminechahid@gmail.com; AMINE@finexclub.org "
    ) == ["amine@finexclub.org", "mohamedaminechahid@gmail.com"]


def test_send_email_addresses_every_recipient(monkeypatch):
    sent: dict[str, object] = {}

    class FakeSmtp:
        def __init__(self, host, port):
            sent["connection"] = (host, port)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def ehlo(self):
            pass

        def starttls(self):
            pass

        def login(self, user, password):
            sent["login"] = (user, password)

        def sendmail(self, sender, recipients, message):
            sent["sender"] = sender
            sent["recipients"] = recipients
            sent["message"] = message

    monkeypatch.setattr(notifications, "SMTP_USER", "sender@example.com")
    monkeypatch.setattr(notifications, "SMTP_PASS", "app-password")
    monkeypatch.setattr(
        notifications,
        "NOTIFY_EMAILS",
        ["amine@finexclub.org", "mohamedaminechahid@gmail.com"],
    )
    monkeypatch.setattr(notifications.smtplib, "SMTP", FakeSmtp)

    assert notifications._send_email("Daily result", "<b>Done</b>", "Done") is True
    assert sent["recipients"] == [
        "amine@finexclub.org",
        "mohamedaminechahid@gmail.com",
    ]
    parsed = message_from_string(str(sent["message"]))
    assert parsed["To"] == "amine@finexclub.org, mohamedaminechahid@gmail.com"


def test_daily_result_email_uses_the_authoritative_phase_record(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        notifications,
        "_collect",
        lambda _path: {"active": 1842, "zero_today": 1},
    )
    monkeypatch.setattr(
        notifications,
        "_send_email",
        lambda subject, html, text: captured.update(
            subject=subject, html=html, text=text
        )
        or True,
    )
    record = DailyRunRecord.start("email-1", profile_for("hosted"))
    for phase in record.phases:
        record.begin_phase(phase.key)
        status = PhaseStatus.FAILED if phase.key == "salary_audit" else PhaseStatus.SUCCESS
        record.finish_phase(phase.key, status, detail=f"Evidence for {phase.label}")
    record.finalize()

    assert notifications.send_daily_run_result(record, "jobs.db") is True
    assert "WARNING" in captured["subject"]
    assert "Salary audit: failed" in captured["text"]
    assert "Evidence for Salary audit" in captured["text"]
