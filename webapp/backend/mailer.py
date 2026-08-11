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

# Where Role submissions go. A module constant on purpose: the
# recipient must never be derived from a request, or the endpoint becomes an
# open relay for anyone who can POST to it.
SUBMISSION_RECIPIENT = os.getenv("SUBMISSION_EMAIL", "amine@finexclub.org")

# CR/LF in a header field is how header injection works — an attacker who gets a
# newline into a Subject or Reply-To can append arbitrary headers (Bcc, etc.).
# EmailMessage raises on embedded newlines, but stripping first gives a clean
# value rather than a 500.
_HEADER_UNSAFE = re.compile(r"[\r\n]+")


def _header_safe(value: str, limit: int = 200) -> str:
    return _HEADER_UNSAFE.sub(" ", value).strip()[:limit]


def send_mail(subject: str, body_text: str, reply_to: str | None = None) -> bool:
    """
    Send one plain-text message to SUBMISSION_RECIPIENT. Returns False on any failure —
    callers must not treat a False as data loss; every caller persists the
    submission to disk before calling this.
    """
    if not SMTP_USER or not SMTP_PASS:
        logger.warning("SMTP credentials not configured — email not sent: %s", subject)
        return False

    msg = EmailMessage()
    msg["Subject"] = _header_safe(subject)
    msg["From"] = SMTP_USER
    msg["To"] = SUBMISSION_RECIPIENT
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
        # Logged on success as well as failure: "no error in the log" is weak
        # evidence that mail is flowing, and this whole class of bug is silent.
        logger.info("Sent %r to %s", msg["Subject"], SUBMISSION_RECIPIENT)
        return True
    except Exception as exc:  # noqa: BLE001 - never let mail failure break a request
        logger.error("Failed to send %r: %s", subject, exc)
        return False


# ── Mail TO a Seeker ──────────────────────────────────────────────────────────
# Everything above sends to the fixed SUBMISSION_RECIPIENT constant, deliberately,
# so the endpoint cannot become an open relay. Seeker accounts need the opposite
# direction: mail to an address a stranger typed (verification, password reset).
#
# That is a genuinely different capability with a different threat model, so it
# gets its own function and its own credentials rather than relaxing send_mail().
# The abuse it invites — pointing our sending reputation at a victim's inbox —
# is held off by per-target-email rate limiting at the endpoint, not here.
#
# Identity: amine@finexclub.org over the existing HostGator mail host, per ADR
# 0009. Not a new Resend subdomain: DNS shows mail.finexclub.org is already the
# live MX for the business mail, and finexclub.org's single permitted SPF record
# (`v=spf1 a mx include:websitewelcome.com ~all`) already authorises that server
# via `a mx`. So this needs no DNS change at all.

SEEKER_SMTP_HOST = os.getenv("SEEKER_SMTP_HOST", "mail.finexclub.org")
SEEKER_SMTP_PORT = int(os.getenv("SEEKER_SMTP_PORT", "587"))
SEEKER_FROM = os.getenv("SEEKER_FROM", "FinEx Careers <amine@finexclub.org>")
SEEKER_SMTP_USER = os.getenv("SEEKER_SMTP_USER", "amine@finexclub.org")
SEEKER_SMTP_PASS = os.getenv("SEEKER_SMTP_PASS", "")

# Callers check this before composing. False means "not configured yet" — the
# account still gets created, the Seeker just receives no mail. A registration
# that 500s because the mailbox password is missing would be a far worse
# failure than one that quietly defers the verification email.
SEEKER_MAIL_READY = bool(SEEKER_SMTP_USER and SEEKER_SMTP_PASS)


def send_to(to: str, subject: str, body_text: str) -> bool:
    """
    Send one plain-text message to a Seeker. Returns False on any failure.

    No caller may treat False as fatal: mail is best-effort here. Registration,
    password changes and account deletion all complete regardless.
    """
    if not SEEKER_MAIL_READY:
        logger.warning("Seeker mail not configured — not sending %r", subject)
        return False

    msg = EmailMessage()
    msg["Subject"] = _header_safe(subject)
    msg["From"] = SEEKER_FROM
    # The recipient is request-derived here, unlike send_mail(). It is sanitised
    # for CR/LF like any other header — an address reaching this point has
    # already passed EmailStr validation, but header injection is cheap to close
    # twice and expensive to miss once.
    msg["To"] = _header_safe(to, limit=320)
    msg.set_content(body_text)

    try:
        with smtplib.SMTP(SEEKER_SMTP_HOST, SEEKER_SMTP_PORT, timeout=20) as srv:
            srv.starttls()
            srv.login(SEEKER_SMTP_USER, SEEKER_SMTP_PASS)
            srv.send_message(msg)
        logger.info("Sent %r to a Seeker", msg["Subject"])
        return True
    except Exception as exc:  # noqa: BLE001 - mail failure must not break a request
        logger.error("Failed to send %r to a Seeker: %s", subject, exc)
        return False
