"""
Shared HTTP utilities used across adapters.

with_retry() wraps a single HTTP call and retries it on transient failures
(timeouts, network errors, and server-side rate-limiting) with exponential
backoff before giving up and letting the exception propagate.
"""

import logging
import time
from typing import Any, Callable

import httpx

logger = logging.getLogger(__name__)

# Status codes worth retrying: 429 Too Many Requests, 5xx Server Error
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


def with_retry(
    fn: Callable[[], Any],
    *,
    max_attempts: int = 3,
    backoff_base: float = 2.0,
) -> Any:
    """
    Call fn() up to max_attempts times, retrying on transient HTTP errors.

    Retries on:
      • httpx.TimeoutException  — read/write/connect/pool timeout
      • httpx.NetworkError      — connection refused, DNS failure, etc.
      • httpx.HTTPStatusError   — only when status is 429 or 5xx

    Does NOT retry on other 4xx errors (400, 401, 403, 404…).  Those signal
    a configuration problem that won't self-heal: wrong URL, bad credentials,
    or an anti-bot block that needs a proxy.

    Backoff: backoff_base * 2^(attempt-1) seconds between retries.
    With the default base=2.0: 2 s before the 2nd attempt, 4 s before the 3rd.
    Set backoff_base=0 in tests to disable sleeping.

    Args:
        fn:           Zero-argument callable that makes one HTTP request.
        max_attempts: Total attempts including the first (default 3).
        backoff_base: Exponential backoff base in seconds (default 2.0).
    """
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()

        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            if attempt == max_attempts:
                raise
            delay = backoff_base * (2 ** (attempt - 1))
            logger.warning(
                "Transient error on attempt %d/%d (%s) — retrying in %.1f s",
                attempt, max_attempts, type(exc).__name__, delay,
            )
            time.sleep(delay)

        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            if code not in _RETRYABLE_STATUS or attempt == max_attempts:
                raise
            delay = backoff_base * (2 ** (attempt - 1))
            logger.warning(
                "HTTP %d on attempt %d/%d — retrying in %.1f s",
                code, attempt, max_attempts, delay,
            )
            time.sleep(delay)
