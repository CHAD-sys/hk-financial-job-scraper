"""
Sending mail to a Seeker, behind an interface.

WHY THIS EXISTS
---------------
`mailer.send_to` reads its SMTP settings at import and freezes a
`SEEKER_MAIL_READY` boolean from them. `main.py` calls `load_env_file()` at
import too, which puts the developer's real `config/api_keys.env` into
`os.environ` — so on any machine that has that file, every
`POST /api/auth/register` in the test suite opened a live SMTP connection to
mail.finexclub.org with the real mailbox password and sent a verification email
to `seeker@example.com`. About twenty per run, from tests whose own docstring
called them hermetic.

That was patched with a fixture that blanks the credentials before the app is
imported. A fixture is a guard, not a seam: it works only for tests that
remember it, and it says nothing about what was sent.

A Seeker-mail sender is now a collaborator the app is given. Two adapters, so
the seam is real: SmtpSender in production, RecordingSender in tests — where
"did registration email them?" becomes an assertion instead of a hope.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Message:
    to: str
    subject: str
    body: str


class Sender(Protocol):
    """Somewhere to send a Seeker's mail."""

    def send(self, message: Message) -> bool:
        """
        Deliver one message. False means it did not go.

        NO CALLER MAY TREAT FALSE AS FATAL. Mail here is best-effort:
        registration, password changes and account deletion all complete
        regardless, because a signup that 500s over a missing mailbox password
        is a far worse failure than one that quietly defers a verification
        email.
        """
        ...


class SmtpSender:
    """The real thing. Delegates to `mailer`, which owns the SMTP details."""

    def send(self, message: Message) -> bool:
        import mailer  # local, so importing this module needs no SMTP config

        if not mailer.SEEKER_MAIL_READY:
            logger.warning("Seeker mail not configured — not sending %r", message.subject)
            return False
        return mailer.send_to(message.to, message.subject, message.body)


@dataclass
class RecordingSender:
    """
    Keeps messages instead of sending them.

    The default in tests. `sent` is what turns "we emailed them a verification
    link" from an untested claim into an assertion — and note that nothing
    asserted on Seeker mail before, which is how a dead /verify link went
    unnoticed.
    """

    sent: list[Message] = field(default_factory=list)
    #: What `send` returns. Set False to exercise a caller's failure path.
    delivers: bool = True

    def send(self, message: Message) -> bool:
        self.sent.append(message)
        return self.delivers

    @property
    def recipients(self) -> list[str]:
        return [m.to for m in self.sent]


class NullSender:
    """Drops everything, silently. For a deploy with no mailbox configured."""

    def send(self, message: Message) -> bool:
        logger.info("No sender configured — dropping %r", message.subject)
        return False


# ── Sending the Role-submission moderation email ───────────────────────────────
#
# WHY THIS EXISTS
# ----------------
# The Seeker-mail seam above exists because tests calling POST /api/auth/register
# used to open a live SMTP connection with the developer's real config/api_keys.env
# credentials. /api/post-role's notification email (mailer.send_mail) had the
# identical bug and was never given the same fix: main.py called the bare
# mailer.send_mail() function directly, so any test hitting /api/post-role
# without individually remembering to monkeypatch it — tests/test_app_factory.py
# did not — sent a real email to the real SUBMISSION_RECIPIENT every run.
#
# No `to` parameter on purpose. SUBMISSION_RECIPIENT must never be
# request-derived (see mailer.py) or the endpoint becomes an open relay; keeping
# it out of this interface makes that invariant structural, not a convention a
# future caller has to remember.


@dataclass(frozen=True)
class SubmissionMessage:
    subject: str
    body: str
    reply_to: str | None = None


class SubmissionNotifier(Protocol):
    """Somewhere to send the Role-submission moderation email."""

    def notify(self, subject: str, body: str, reply_to: str | None = None) -> bool:
        """Deliver one message to SUBMISSION_RECIPIENT. False means it did not go."""
        ...


class SmtpSubmissionNotifier:
    """The real thing. Delegates to mailer, which owns the SMTP details."""

    def notify(self, subject: str, body: str, reply_to: str | None = None) -> bool:
        import mailer  # local, so importing this module needs no SMTP config

        return mailer.send_mail(subject, body, reply_to=reply_to)


@dataclass
class RecordingSubmissionNotifier:
    """Keeps messages instead of sending them. The default in tests."""

    sent: list[SubmissionMessage] = field(default_factory=list)
    #: What `notify` returns. Set False to exercise a caller's failure path.
    delivers: bool = True

    def notify(self, subject: str, body: str, reply_to: str | None = None) -> bool:
        self.sent.append(SubmissionMessage(subject=subject, body=body, reply_to=reply_to))
        return self.delivers
