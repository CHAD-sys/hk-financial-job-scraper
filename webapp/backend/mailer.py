"""
Outbound email for the web backend.

Deliberately self-contained rather than importing hk_jobs.notifications._send_email().
The backend is started as `uvicorn main:app` with webapp/backend as the working
directory (see Procfile / railway.json), so the repo root is not on sys.path and
hk_jobs is not importable without path surgery that would break on deploy. The
SMTP logic is twenty lines; duplicating it is cheaper than coupling the API to
the scraper package.

Configuration is the same environment as the scraper's notifications, so a single
set of SMTP variables serves both:
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS
"""

from __future__ import annotations

import logging
import os
import re
import smtplib
from email.message import EmailMessage

logger = logging.getLogger(__name__)

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")

# Where enquiries and role submissions go. A module constant on purpose: the
# recipient must never be derived from a request, or the endpoint becomes an
# open relay for anyone who can POST to it.
RECIPIENT = os.getenv("ENQUIRY_EMAIL", "mohamedaminechahid@gmail.com")

# CR/LF in a header field is how header injection works — an attacker who gets a
# newline into a Subject or Reply-To can append arbitrary headers (Bcc, etc.).
# EmailMessage raises on embedded newlines, but stripping first gives a clean
# value rather than a 500.
_HEADER_UNSAFE = re.compile(r"[\r\n]+")


def _header_safe(value: str, limit: int = 200) -> str:
    return _HEADER_UNSAFE.sub(" ", value).strip()[:limit]


def send_mail(subject: str, body_text: str, reply_to: str | None = None) -> bool:
    """
    Send one plain-text message to RECIPIENT. Returns False on any failure —
    callers must not treat a False as data loss; every caller persists the
    submission to disk before calling this.
    """
    if not SMTP_USER or not SMTP_PASS:
        logger.warning("SMTP credentials not configured — email not sent: %s", subject)
        return False

    msg = EmailMessage()
    msg["Subject"] = _header_safe(subject)
    msg["From"] = SMTP_USER
    msg["To"] = RECIPIENT
    # Reply-To carries visitor-supplied input, so it is sanitised like any other
    # header. It is set only when the address already passed EmailStr validation.
    if reply_to:
        msg["Reply-To"] = _header_safe(reply_to)
    msg.set_content(body_text)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as srv:
            srv.starttls()
            srv.login(SMTP_USER, SMTP_PASS)
            srv.send_message(msg)
        return True
    except Exception as exc:  # noqa: BLE001 - never let mail failure break a request
        logger.error("Failed to send %r: %s", subject, exc)
        return False
