"""Short-lived proof that a Role was returned through an allowed discovery path.

Catalogue search, recommendations, resume matches, and Saved Roles may expose a
Role summary. Each of those paths issues the same opaque grant. The public detail
route accepts the reference only when accompanied by a valid grant for that exact
Role; knowing or guessing a jobs.db key is not itself permission to read it.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from datetime import timedelta
from typing import Callable

DEFAULT_GRANT_TTL = timedelta(hours=2)


class RoleAccess:
    """Issue and verify expiring, reference-bound Role grants."""

    def __init__(
        self,
        secret: str | bytes | None = None,
        *,
        ttl: timedelta = DEFAULT_GRANT_TTL,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if secret is None or secret == "" or secret == b"":
            secret = secrets.token_bytes(32)
        self._secret = secret.encode("utf-8") if isinstance(secret, str) else secret
        self._ttl_seconds = max(1, int(ttl.total_seconds()))
        self._clock = clock

    def issue(self, source: str, source_id: str) -> str:
        payload = {
            "v": 1,
            "source": source,
            "source_id": source_id,
            "exp": int(self._clock()) + self._ttl_seconds,
        }
        body = _encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
        signature = _encode(hmac.new(self._secret, body.encode(), hashlib.sha256).digest())
        return f"{body}.{signature}"

    def allows(self, token: str | None, source: str, source_id: str) -> bool:
        if not token or len(token) > 2_048:
            return False
        try:
            body, supplied_signature = token.split(".", 1)
            expected_signature = _encode(
                hmac.new(self._secret, body.encode(), hashlib.sha256).digest()
            )
            if not hmac.compare_digest(supplied_signature, expected_signature):
                return False
            payload = json.loads(_decode(body))
            return (
                payload.get("v") == 1
                and payload.get("source") == source
                and payload.get("source_id") == source_id
                and isinstance(payload.get("exp"), int)
                and payload["exp"] >= int(self._clock())
            )
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError, TypeError):
            return False


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)
