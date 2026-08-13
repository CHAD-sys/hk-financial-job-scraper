"""Non-expiring, stateless proof that an Alert unsubscribe link belongs to a
given Seeker.

Deliberately NOT built on `email_tokens` (seekers_store.py) or `RoleAccess`
(role_access.py) — both are the wrong shape here. `email_tokens` rows are
single-use and expire within an hour, right for a verify/reset link clicked
minutes after it is sent, wrong for an unsubscribe link that must still work
if the email sits unread for three weeks. `RoleAccess` grants expire in 2
hours for the same reason. An unsubscribe token instead needs no expiry, no
database row, and no revocation — it proves only "this token was minted for
this seeker_id", which stays true for as long as the account exists. Stateless
HMAC signing is the whole mechanism.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets


class AlertUnsubscribeToken:
    """Issue and resolve Seeker-bound unsubscribe tokens for Alert emails."""

    def __init__(self, secret: str | bytes | None = None) -> None:
        if not secret:
            secret = secrets.token_bytes(32)
        self._secret = secret.encode("utf-8") if isinstance(secret, str) else secret

    def issue(self, seeker_id: str) -> str:
        """A token for this seeker_id, safe to embed in an email link."""
        signature = self._sign(seeker_id)
        return f"{seeker_id}.{signature}"

    def resolve(self, token: str | None) -> str | None:
        """The seeker_id the token proves, or None if it does not verify."""
        if not token or len(token) > 512 or "." not in token:
            return None
        seeker_id, _, supplied_signature = token.rpartition(".")
        if not hmac.compare_digest(supplied_signature, self._sign(seeker_id)):
            return None
        return seeker_id

    def _sign(self, seeker_id: str) -> str:
        return hmac.new(self._secret, seeker_id.encode("utf-8"), hashlib.sha256).hexdigest()
