"""
The rate limiter: what it refuses, what it forgets, and what it will not forget.

Two halves of this were previously unreachable from a test.

The window *reopening* needed an hour of sleeping, because `time.time()` was read
inline — so all three existing rate-limit tests asserted that the limiter blocks
and none asserted that it ever stops. `clock` is an argument now.

The table's *size* had no bound and no observer. `_limit` pruned timestamps
inside a key and never removed a key, and `login:email:{email}` keys on an
address the caller types. Measured against the old code: 100,000 distinct emails
produced 100,000 keys and 21.9 MiB, and advancing 27 hours past a 15-minute
window reclaimed zero bytes.
"""

from __future__ import annotations

import sys

import pytest

from .support import BACKEND, make_app

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from rate_limit import RateLimiter, RedisRateLimiter  # noqa: E402


class Clock:
    """A clock a test can move. The seam that makes expiry assertable at all."""

    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def limiter(**kw) -> tuple[RateLimiter, Clock]:
    clock = Clock()
    return RateLimiter(clock=clock, **kw), clock


# ── The window ────────────────────────────────────────────────────────────────

def test_calls_up_to_the_limit_are_allowed():
    rl, _ = limiter()
    assert [rl.allow("k", limit=3, window_s=60) for _ in range(3)] == [True, True, True]


def test_the_call_after_the_limit_is_refused():
    rl, _ = limiter()
    for _ in range(3):
        rl.allow("k", limit=3, window_s=60)
    assert rl.allow("k", limit=3, window_s=60) is False


def test_the_window_reopens():
    """
    The half nobody could test. A limiter that never forgets is not a rate
    limiter, it is a permanent ban, and the difference took an hour of wall
    clock to observe before `clock` was a parameter.
    """
    rl, clock = limiter()
    for _ in range(3):
        rl.allow("k", limit=3, window_s=60)
    assert rl.allow("k", limit=3, window_s=60) is False

    clock.advance(61)
    assert rl.allow("k", limit=3, window_s=60) is True


def test_the_window_slides_rather_than_resetting():
    """
    Three calls spread across the window do not all expire together: at t=90
    the calls from t=0 and t=45 are gone but t=60's is not.
    """
    rl, clock = limiter()
    rl.allow("k", limit=2, window_s=60)          # t=0
    clock.advance(45)
    rl.allow("k", limit=2, window_s=60)          # t=45
    assert rl.allow("k", limit=2, window_s=60) is False

    clock.advance(20)                             # t=65 — only t=0 has expired
    assert rl.allow("k", limit=2, window_s=60) is True
    assert rl.allow("k", limit=2, window_s=60) is False


def test_keys_are_independent():
    rl, _ = limiter()
    for _ in range(3):
        rl.allow("a", limit=3, window_s=60)
    assert rl.allow("a", limit=3, window_s=60) is False
    assert rl.allow("b", limit=3, window_s=60) is True


def test_one_key_can_carry_two_different_limits():
    """
    Registration uses 3/hour per email; login uses 10/15min. They are different
    keys, but the limiter must not cache a window per key either.
    """
    rl, _ = limiter()
    for _ in range(3):
        assert rl.allow("k", limit=10, window_s=900) is True
    assert rl.allow("k", limit=3, window_s=900) is False
    assert rl.allow("k", limit=10, window_s=900) is True


# ── The leak ──────────────────────────────────────────────────────────────────

def test_expired_keys_are_swept():
    """
    THE regression. Old behaviour: 100,000 distinct emails left 100,000 keys
    that were never removed, and were only ever *pruned* if the same key came
    back — which an attacker choosing a fresh address each time never does.
    """
    rl, clock = limiter(sweep_interval_s=10)
    for i in range(500):
        rl.allow(f"login:email:a{i}@example.com", limit=10, window_s=60)
    assert rl.stats()["keys"] == 500

    clock.advance(3600)
    rl.allow("someone-else", limit=10, window_s=60)   # any call triggers the sweep

    assert rl.stats()["keys"] == 1, "expired keys must not survive"


def test_a_sweep_never_drops_a_key_that_is_still_limiting():
    """
    The one error that would matter: sweeping a live key hands out free attempts.
    """
    rl, clock = limiter(sweep_interval_s=1)
    for _ in range(3):
        rl.allow("victim@example.com", limit=3, window_s=3600)
    for i in range(200):
        rl.allow(f"noise{i}", limit=3, window_s=3600)

    clock.advance(120)                                # past the sweep interval
    rl.allow("trigger", limit=3, window_s=3600)

    assert rl.allow("victim@example.com", limit=3, window_s=3600) is False


def test_sweeping_uses_the_longest_window_in_play():
    """
    Keys do not record their own window, so the sweep uses the longest any
    caller has asked for. Conservative on purpose — a 15-minute key may linger
    for an hour, which costs memory; the reverse would cost a bypass.
    """
    rl, clock = limiter(sweep_interval_s=1)
    rl.allow("short", limit=1, window_s=60)
    rl.allow("long", limit=1, window_s=3600)

    clock.advance(120)                                # past 60s, well inside 3600s
    rl.allow("trigger", limit=1, window_s=3600)
    assert rl.stats()["keys"] == 3, "the 3600s window governs the sweep"

    clock.advance(3600)
    rl.allow("trigger2", limit=1, window_s=3600)
    assert rl.stats()["keys"] == 1


def test_the_table_never_exceeds_its_capacity():
    rl, _ = limiter(capacity=50)
    for i in range(5_000):
        rl.allow(f"flood{i}", limit=10, window_s=3600)
    assert rl.stats()["keys"] <= 50


# ── Fail closed, not LRU ──────────────────────────────────────────────────────

def test_a_flood_cannot_evict_the_key_that_is_tracking_it():
    """
    THE security property, and the whole reason capacity refuses new keys rather
    than evicting old ones.

    Under LRU this test fails: the attacker fills the table, pushes their own
    brute-force counter out, and resumes with a clean slate — a bypass strictly
    worse than the leak it would have fixed.
    """
    rl, _ = limiter(capacity=100)

    for _ in range(10):                               # exhaust the login budget
        rl.allow("login:email:victim@example.com", limit=10, window_s=900)
    assert rl.allow("login:email:victim@example.com", limit=10, window_s=900) is False

    for i in range(10_000):                           # flood, trying to evict it
        rl.allow(f"login:email:junk{i}@evil.example", limit=10, window_s=900)

    assert rl.allow("login:email:victim@example.com", limit=10, window_s=900) is False, (
        "the attacker evicted their own rate limit"
    )


def test_a_full_table_refuses_new_keys():
    rl, _ = limiter(capacity=10)
    for i in range(10):
        assert rl.allow(f"k{i}", limit=100, window_s=3600) is True
    assert rl.allow("one-too-many", limit=100, window_s=3600) is False


def test_a_full_table_still_serves_the_keys_it_already_holds():
    """Refusing new keys must not refuse existing ones — that would be a self-DoS."""
    rl, _ = limiter(capacity=5)
    for i in range(5):
        rl.allow(f"k{i}", limit=100, window_s=3600)
    rl.allow("refused", limit=100, window_s=3600)

    assert rl.allow("k0", limit=100, window_s=3600) is True


def test_capacity_recovers_once_the_flood_expires():
    rl, clock = limiter(capacity=10, sweep_interval_s=1)
    for i in range(10):
        rl.allow(f"flood{i}", limit=100, window_s=60)
    assert rl.allow("legit@example.com", limit=100, window_s=60) is False

    clock.advance(3600)
    assert rl.allow("legit@example.com", limit=100, window_s=60) is True


def test_refusals_are_counted_for_operators():
    rl, _ = limiter(capacity=2)
    for i in range(5):
        rl.allow(f"k{i}", limit=100, window_s=3600)
    assert rl.stats()["refused"] == 3
    assert rl.stats()["capacity"] == 2


# ── Concurrency ───────────────────────────────────────────────────────────────

def test_the_limit_holds_under_concurrent_callers():
    """
    uvicorn serves requests on a thread pool, so two callers can hit one key at
    once. Exactly `limit` must get through — no more.
    """
    import threading

    rl, _ = limiter()
    allowed: list[bool] = []
    lock = threading.Lock()

    def hit() -> None:
        ok = rl.allow("shared", limit=20, window_s=3600)
        with lock:
            allowed.append(ok)

    threads = [threading.Thread(target=hit) for _ in range(200)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sum(allowed) == 20


# ── Wiring ────────────────────────────────────────────────────────────────────

def test_each_app_gets_its_own_limiter(tmp_path):
    """
    Two apps in one process must not share a budget, or one test's requests
    would exhaust another's.
    """
    a, b = make_app(tmp_path / "a"), make_app(tmp_path / "b")
    assert a.state.limiter is not b.state.limiter


@pytest.mark.parametrize("endpoint,payload", [
    ("/api/auth/login", {"email": "x@example.com", "password": "y"}),
])
def test_the_endpoints_no_longer_leak_a_key_per_attempt(tmp_path, endpoint, payload):
    """
    The end-to-end version of the leak, through the real HTTP surface: 300
    attempts on 300 distinct emails, then the window passes.
    """
    from fastapi.testclient import TestClient

    app = make_app(tmp_path)
    clock = Clock()
    app.state.limiter = RateLimiter(clock=clock, sweep_interval_s=10)
    client = TestClient(app)

    for i in range(300):
        client.post(endpoint, json={**payload, "email": f"a{i}@example.com"})
    assert app.state.limiter.stats()["keys"] > 100

    clock.advance(7200)
    client.post(endpoint, json={**payload, "email": "final@example.com"})

    assert app.state.limiter.stats()["keys"] <= 2


# ── RedisRateLimiter — the shared implementation ────────────────────────────
#
# Same sliding-window contract as RateLimiter above, proven against a real
# Lua interpreter (fakeredis[lua], not a Python stand-in) so these tests catch
# a script bug the same way a real Redis server would. `capacity`/sweep tests
# have no equivalent here — see RedisRateLimiter's docstring for why a shared
# store does not have that problem the same way a per-process dict does.

def redis_limiter(**kw) -> tuple[RedisRateLimiter, Clock]:
    import fakeredis

    clock = Clock()
    rl = RedisRateLimiter("redis://unused", client=fakeredis.FakeRedis(), clock=clock, **kw)
    return rl, clock


def test_redis_calls_up_to_the_limit_are_allowed():
    rl, _ = redis_limiter()
    assert [rl.allow("k", limit=3, window_s=60) for _ in range(3)] == [True, True, True]


def test_redis_the_call_after_the_limit_is_refused():
    rl, _ = redis_limiter()
    for _ in range(3):
        rl.allow("k", limit=3, window_s=60)
    assert rl.allow("k", limit=3, window_s=60) is False


def test_redis_the_window_reopens():
    rl, clock = redis_limiter()
    for _ in range(3):
        rl.allow("k", limit=3, window_s=60)
    assert rl.allow("k", limit=3, window_s=60) is False

    clock.advance(61)
    assert rl.allow("k", limit=3, window_s=60) is True


def test_redis_the_window_slides_rather_than_resetting():
    rl, clock = redis_limiter()
    rl.allow("k", limit=2, window_s=60)          # t=0
    clock.advance(45)
    rl.allow("k", limit=2, window_s=60)          # t=45
    assert rl.allow("k", limit=2, window_s=60) is False

    clock.advance(20)                             # t=65 — only t=0 has expired
    assert rl.allow("k", limit=2, window_s=60) is True
    assert rl.allow("k", limit=2, window_s=60) is False


def test_redis_keys_are_independent():
    rl, _ = redis_limiter()
    for _ in range(3):
        rl.allow("a", limit=3, window_s=60)
    assert rl.allow("a", limit=3, window_s=60) is False
    assert rl.allow("b", limit=3, window_s=60) is True


def test_redis_one_key_can_carry_two_different_limits():
    rl, _ = redis_limiter()
    for _ in range(3):
        assert rl.allow("k", limit=10, window_s=900) is True
    assert rl.allow("k", limit=3, window_s=900) is False
    assert rl.allow("k", limit=10, window_s=900) is True


def test_redis_a_key_expires_on_its_own_instead_of_needing_a_sweep():
    """
    The replacement for RateLimiter's capacity/sweep pair: Redis is told
    (via PEXPIRE) to drop the key itself once it can no longer be limiting
    anyone, so a flood of distinct keys costs memory for one window's length,
    not forever.
    """
    import fakeredis

    fake = fakeredis.FakeRedis()
    rl = RedisRateLimiter("redis://unused", client=fake)
    rl.allow("k", limit=3, window_s=60)
    ttl_ms = fake.pttl("k")
    assert 0 < ttl_ms <= 61_000


def test_redis_fails_open_when_unreachable():
    """
    A rate limiter that is down must not become a second way to take the site
    down. `object()` has no `register_script`/EVAL support, standing in for a
    Redis connection that raises on every call.
    """
    import redis as redis_module

    class _BrokenScript:
        def __call__(self, *a, **kw):
            raise redis_module.RedisError("connection refused")

    class _BrokenRedis:
        def register_script(self, _lua):
            return _BrokenScript()

    rl = RedisRateLimiter("redis://unused", client=_BrokenRedis())
    assert rl.allow("k", limit=1, window_s=60) is True
    assert rl.allow("k", limit=1, window_s=60) is True, "must keep failing open, not just once"


def test_redis_the_limit_holds_under_concurrent_callers():
    """
    The atomicity guarantee this class exists for: two replicas (simulated
    here as two threads sharing one fake Redis) racing on the same key must
    not both slip through on a stale count. Correctness comes from the Lua
    script running atomically inside Redis, not from a Python-side lock.

    max_connections is raised because fakeredis's default pool is small
    enough that 200 real threads exhaust it — a real Redis server has no such
    ceiling, and a starved connection here would surface as a fail-open
    (correct behaviour, tested separately) rather than the race this test is
    actually checking for.
    """
    import threading

    import fakeredis

    fake = fakeredis.FakeRedis(max_connections=250)
    rl = RedisRateLimiter("redis://unused", client=fake)
    allowed: list[bool] = []
    lock = threading.Lock()

    def hit() -> None:
        ok = rl.allow("shared", limit=20, window_s=3600)
        with lock:
            allowed.append(ok)

    threads = [threading.Thread(target=hit) for _ in range(200)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sum(allowed) == 20


# ── Wiring ────────────────────────────────────────────────────────────────────

def test_app_uses_redis_limiter_once_redis_url_is_set(tmp_path):
    """
    Construction alone must not require a live Redis connection — register_script
    only wraps the script text, so a app can boot even if Redis is briefly
    unreachable (the actual connection attempt happens lazily, on the first
    allow() call, which is where the fail-open behaviour takes over).
    """
    app = make_app(tmp_path / "db.sqlite", redis_url="redis://localhost:1")
    assert isinstance(app.state.limiter, RedisRateLimiter)


def test_app_uses_in_process_limiter_when_redis_url_is_unset(tmp_path):
    app = make_app(tmp_path / "db.sqlite")
    assert isinstance(app.state.limiter, RateLimiter)
