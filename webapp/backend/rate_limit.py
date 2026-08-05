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
import secrets
import threading
import time
from collections.abc import Callable
from typing import Protocol

logger = logging.getLogger(__name__)


class Limiter(Protocol):
    """What every rate limiter implementation offers — see sender.py's `Sender`
    for the same pattern. `RateLimiter` (in-process) and `RedisRateLimiter`
    (shared) both satisfy this; `create_app()` picks one from `Settings`."""

    def allow(self, key: str, *, limit: int, window_s: float) -> bool: ...
    def stats(self) -> dict[str, int]: ...

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


# ── The shared implementation, for when a process is not the only one ─────────
#
# One Lua script, run atomically by Redis itself: drop hits older than the
# window, count what is left, and only record the new hit if that count is
# still under `limit`. Atomic matters here for the same reason `RateLimiter`
# above takes a lock — two replicas must not both read "9 of 10 used" and both
# let a 10th and 11th attempt through.
_SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]

redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
local count = redis.call('ZCARD', key)
if count >= limit then
  return 0
end
redis.call('ZADD', key, now, member)
redis.call('PEXPIRE', key, math.ceil(window * 1000) + 1000)
return 1
"""


class RedisRateLimiter:
    """
    The same sliding-window limit as `RateLimiter`, backed by Redis instead of
    a per-process dict — so every replica, and a process that just redeployed,
    shares one count instead of each starting from zero (see this module's
    docstring — that gap is the whole reason this class exists).

    Each key is a Redis sorted set: member = one call, score = when it
    happened. There is no `capacity`/sweep pair to reason about the way
    `RateLimiter` needs one: Redis expires each key a little past its own
    window (`PEXPIRE` below), so a flood of distinct keys costs memory for at
    most one window's length, never forever — the unbounded-growth problem
    `RateLimiter`'s docstring describes does not exist the same way against a
    real store.

    If Redis is unreachable, `allow()` fails OPEN rather than refusing every
    request in the process: a rate limiter going down should not become a
    second way to take the whole site down.
    """

    def __init__(
        self,
        redis_url: str,
        *,
        client: object | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if client is not None:
            self._redis = client
        else:
            import redis as redis_module

            self._redis = redis_module.Redis.from_url(
                redis_url, socket_connect_timeout=2, socket_timeout=2,
            )
        self._script = self._redis.register_script(_SLIDING_WINDOW_LUA)
        self._clock = clock
        self._refused = 0
        self._lock = threading.Lock()

    def allow(self, key: str, *, limit: int, window_s: float) -> bool:
        import redis as redis_module

        now = self._clock()
        # secrets.token_hex, not a counter: two threads racing on the same
        # process must never generate the same sorted-set member, or the
        # second ZADD silently overwrites the first instead of adding a hit.
        member = f"{now}-{secrets.token_hex(4)}"
        try:
            result = self._script(keys=[key], args=[now, window_s, limit, member])
        except redis_module.RedisError:
            logger.warning("Redis rate limiter unreachable — failing open for %r", key,
                            exc_info=True)
            return True
        allowed = bool(result)
        if not allowed:
            with self._lock:
                self._refused += 1
        return allowed

    def stats(self) -> dict[str, int]:
        """
        Best-effort only. Unlike `RateLimiter`, there is no single "this
        table's keys" to count — Redis holds every replica's keys together,
        and counting them exactly means an O(keys) SCAN this method has no
        reason to pay for. `refused` is this process's count since it started,
        not the shared total.
        """
        with self._lock:
            return {"refused": self._refused}
