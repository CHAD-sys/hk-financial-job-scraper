from email import message_from_string

from hk_jobs import notifications


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
