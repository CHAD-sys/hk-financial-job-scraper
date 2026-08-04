"""
Rate limiting: how many times a key may act inside a window.

WHY THIS EXISTS
---------------
The limiter was four lines in `main.py` reading a `defaultdict(list)` off
`app.state`. Two things followed from that shape.

**It leaked, and the key is attacker-controlled.** `_limit` pruned the
timestamps *inside* a key but never removed the key — and it only pruned keys it
happened to touch. `login:email:{email}` keys on an address the caller types, so
an attacker who never repeats an email left one permanent dict entry per
request, forever. Measured on the real code: 100,000 distinct emails produced
100,000 keys and 21.9 MiB; a million would be ~219 MiB. Advancing 27 hours past
a 15-minute window left 99,999 of those 100,000 keys as pure garbage and
reclaimed **zero** bytes. The process is a single Railway instance.

**Half its behaviour could not be tested.** `now = time.time()` was read
inline, so proving the window ever *reopens* meant sleeping for an hour. All
three existing rate-limit tests assert that the limiter blocks; none asserts
that it ever stops blocking. `clock` is now an argument.

FAIL CLOSED, NOT LRU
--------------------
Sweeping expired keys is always safe, but on its own it only bounds memory to
"distinct keys seen within one window" — a sustained flood still grows without
limit. So there is a hard `capacity`, and reaching it refuses to track NEW keys
rather than evicting old ones.

That direction is deliberate. LRU eviction would give a bounded table and a
bypass: flood junk keys until the entry tracking your own brute-force is pushed
out, then resume with a clean counter — which would make the limiter weaker
than the leak it replaced. Refusing new keys instead means an attacker can never
evict the record of themselves. The cost is that a flood large enough to fill
the table also turns away genuinely new callers; a flood at that scale is
already a denial of service, and this fails in the safe direction.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)

#: Distinct keys tracked at once. 100k costs ~22 MiB, which is affordable on the
#: single instance this runs on, and is far more distinct emails than a real hour
#: of traffic produces.
DEFAULT_CAPACITY = 100_000

#: A full sweep is O(keys), so it runs at most this often rather than on every
#: request. Between sweeps the table may hold expired keys; that is a memory
#: cost, never a correctness one, because an expired key limits nobody.
DEFAULT_SWEEP_INTERVAL_S = 60.0


class RateLimiter:
    """
    A sliding-window limiter over a bounded, self-sweeping table.

    In-memory and therefore per-process: it resets on deploy and does not span
    replicas. Adequate for one instance at current traffic; the seam is here so
    a Redis-backed implementation can take its place without any caller
    changing (PLAN_ACCOUNTS §5 — it needs to be persistent before anyone pays
    us).
    """

    def __init__(
        self,
        *,
        capacity: int = DEFAULT_CAPACITY,
        sweep_interval_s: float = DEFAULT_SWEEP_INTERVAL_S,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._capacity = capacity
        self._sweep_interval_s = sweep_interval_s
        self._clock = clock
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()
        self._last_sweep = clock()
        # The longest window any caller has asked for. A key is only swept once
        # it is dead by THAT measure, so a 15-minute key may linger for an hour.
        # Deliberately conservative: sweeping a key that could still be limiting
        # someone would hand out free attempts, which is the one error that
        # matters here.
        self._max_window_s = 0.0
        self._refusals = 0

    def allow(self, key: str, *, limit: int, window_s: float) -> bool:
        """
        True if this call is within `limit` for `key` over the last `window_s`.

        Records the call when it is allowed, so `limit` calls in a window pass
        and the next one does not.
        """
        now = self._clock()
        with self._lock:
            self._max_window_s = max(self._max_window_s, float(window_s))
            if now - self._last_sweep >= self._sweep_interval_s:
                self._sweep(now)

            hits = self._hits.get(key)
            if hits is None:
                # A key we are not tracking. Make room, or refuse.
                if len(self._hits) >= self._capacity:
                    self._sweep(now)
                if len(self._hits) >= self._capacity:
                    self._refusals += 1
                    if self._refusals == 1 or self._refusals % 10_000 == 0:
                        logger.warning(
                            "Rate-limit table full at %d keys — refusing new keys "
                            "(%d refused so far). Existing keys are unaffected, so no "
                            "limit can be evicted; this is a flood, not a bug.",
                            self._capacity, self._refusals,
                        )
                    return False
                hits = []

            live = [t for t in hits if now - t < window_s]
            if len(live) >= limit:
                self._hits[key] = live
                return False
            live.append(now)
            self._hits[key] = live
            return True

    def _sweep(self, now: float) -> None:
        """
        Drop every key whose most recent call is outside the longest window.

        Caller holds the lock. Timestamps are appended in order, so the last one
        is the newest.
        """
        before = len(self._hits)
        self._hits = {
            key: hits
            for key, hits in self._hits.items()
            if hits and now - hits[-1] < self._max_window_s
        }
        self._last_sweep = now
        dropped = before - len(self._hits)
        if dropped:
            logger.debug("Rate-limit sweep dropped %d expired key(s).", dropped)

    def stats(self) -> dict[str, int]:
        """Current size and how many new keys have been refused. For operators."""
        with self._lock:
            return {
                "keys": len(self._hits),
                "capacity": self._capacity,
                "refused": self._refusals,
            }
