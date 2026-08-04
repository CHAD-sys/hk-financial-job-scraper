"""
When a Closed Role leaves a Seeker's Saved Roles.

THE RULE
--------
A Saved Role that has been Closed for longer than `SAVED_ROLE_RETENTION`
(a fortnight) stops appearing in the Seeker's list. Nothing is deleted: the
Listing stays in jobs.db under the soft-delete rule, the reference stays in
seekers.db, and the Role stays reachable by deep link. Only the list stops
showing it. See docs/adr/0011.

WHAT THESE TESTS ARE GUARDING
-----------------------------
The rule needs two facts that did not exist before it: WHETHER a Role is closed
(`is_active`, which we had) and WHEN it closed (`closed_at`, which we did not).
The second is only trustworthy because `JobStore.deactivate` is the single write
path to `is_active = 0` — a closure date written by three of four writers would
make NULL ambiguous between "still open" and "the writer that forgot", and the
tests below would then be asserting on a coin flip.

So the load-bearing cases here are the boundary (a day either side of the
fortnight) and, more importantly, every way the date can be missing or wrong.
Those all FAIL OPEN — an unknown date keeps the Role. Hiding a Saved Role is the
destructive direction; the Seeker did not ask for it to go.

`now` is injected rather than slept through, which is the only reason the
fortnight is assertable at all.
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta, timezone

import pytest

from .support import BACKEND, job, make_app, make_bundle, make_jobs_db

sys.path.insert(0, str(BACKEND))

from job_read import (  # noqa: E402
    SAVED_ROLE_RETENTION,
    jobs_by_refs,
    prepare,
    saved_roles,
)

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)


def ago(days: float) -> str:
    """An ISO closure timestamp `days` before NOW."""
    return (NOW - timedelta(days=days)).isoformat()


OPEN = ("workday", "OPEN")
JUST_CLOSED = ("workday", "JUST_CLOSED")
CLOSED_13D = ("workday", "CLOSED_13D")
CLOSED_15D = ("workday", "CLOSED_15D")
CLOSED_UNDATED = ("workday", "CLOSED_UNDATED")
CLOSED_GARBLED = ("workday", "CLOSED_GARBLED")


@pytest.fixture()
def conn(tmp_path) -> sqlite3.Connection:
    db = tmp_path / "jobs.db"
    make_jobs_db(
        db,
        jobs=[
            job(source="workday", source_id="OPEN", title="Open Role"),
            job(source="workday", source_id="JUST_CLOSED", title="Closed Last Night",
                is_active=0, closed_at=ago(1)),
            job(source="workday", source_id="CLOSED_13D", title="Closed A Fortnight Less A Day",
                is_active=0, closed_at=ago(13)),
            job(source="workday", source_id="CLOSED_15D", title="Closed Over A Fortnight",
                is_active=0, closed_at=ago(15)),
            # Closed before phase 30 existed and never backfilled.
            job(source="workday", source_id="CLOSED_UNDATED", title="Closed, Undated",
                is_active=0, closed_at=None),
            # A date nothing can parse.
            job(source="workday", source_id="CLOSED_GARBLED", title="Closed, Garbled",
                is_active=0, closed_at="last Tuesday-ish"),
        ],
    )
    c = prepare(sqlite3.connect(db))
    yield c
    c.close()


def ids(summaries) -> list[str]:
    return [s.source_id for s in summaries]


# ── The rule ──────────────────────────────────────────────────────────────────

def test_an_open_role_is_listed(conn):
    assert ids(saved_roles(conn, [OPEN], now=NOW)) == ["OPEN"]


def test_a_role_closed_last_night_is_still_listed(conn):
    """
    The half of ADR 0010 this rule must not break. A Seeker who comes back on
    Tuesday to a Role that closed on Monday is told it closed — that is the whole
    point of resolving a reference instead of storing a copy.
    """
    listed = saved_roles(conn, [JUST_CLOSED], now=NOW)
    assert ids(listed) == ["JUST_CLOSED"]
    assert listed[0].closed is True


def test_a_role_closed_longer_than_the_window_is_not_listed(conn):
    assert saved_roles(conn, [CLOSED_15D], now=NOW) == []


def test_the_boundary_is_the_retention_window(conn):
    """
    A day inside the window stays, a day outside it goes. Pinned against the
    constant rather than a hardcoded 14, so changing the window moves both sides
    together instead of leaving a test asserting the old fortnight.
    """
    inside = NOW - SAVED_ROLE_RETENTION + timedelta(hours=1)
    outside = NOW - SAVED_ROLE_RETENTION - timedelta(hours=1)

    conn.execute("UPDATE jobs SET closed_at = ? WHERE source_id = 'JUST_CLOSED'",
                 [inside.isoformat()])
    assert ids(saved_roles(conn, [JUST_CLOSED], now=NOW)) == ["JUST_CLOSED"]

    conn.execute("UPDATE jobs SET closed_at = ? WHERE source_id = 'JUST_CLOSED'",
                 [outside.isoformat()])
    assert saved_roles(conn, [JUST_CLOSED], now=NOW) == []


def test_it_keeps_the_seekers_order_and_drops_only_the_expired(conn):
    listed = saved_roles(conn, [CLOSED_15D, OPEN, CLOSED_13D, JUST_CLOSED], now=NOW)
    assert ids(listed) == ["OPEN", "CLOSED_13D", "JUST_CLOSED"]


def test_the_window_passing_is_what_removes_it_not_the_closing(conn):
    """
    Same row, same database, two different reading days: present on the day it
    closes, gone a fortnight later. This is the behaviour a Seeker actually
    experiences, and it is only observable because `now` is a parameter.
    """
    assert ids(saved_roles(conn, [CLOSED_13D], now=NOW)) == ["CLOSED_13D"]
    assert saved_roles(conn, [CLOSED_13D], now=NOW + timedelta(days=2)) == []


# ── Failing open ──────────────────────────────────────────────────────────────

def test_a_closed_role_with_no_date_is_kept(conn):
    """
    NULL means "we do not know when this closed", not "it closed at the dawn of
    time". Rows closed before phase 30 can be in this state, and dropping them
    would silently empty a Seeker's list on the day we deployed.
    """
    assert ids(saved_roles(conn, [CLOSED_UNDATED], now=NOW)) == ["CLOSED_UNDATED"]


def test_a_closed_role_with_an_unreadable_date_is_kept(conn):
    """
    `datetime('last Tuesday-ish')` is NULL in SQLite, and NULL >= x is NULL,
    which is falsy — so without the explicit IS NULL branch a garbled date would
    hide the Role rather than keep it. Wrong direction, silently.
    """
    assert ids(saved_roles(conn, [CLOSED_GARBLED], now=NOW)) == ["CLOSED_GARBLED"]


def test_a_reference_with_no_row_is_dropped_as_before(conn):
    assert saved_roles(conn, [("ghost", "GONE")], now=NOW) == []


def test_no_references_is_no_query(conn):
    assert saved_roles(conn, [], now=NOW) == []


def test_it_defaults_to_the_real_clock(conn):
    """`now` is a test seam, not a required argument."""
    assert ids(saved_roles(conn, [OPEN])) == ["OPEN"]


# ── What the rule is NOT ──────────────────────────────────────────────────────

def test_addressing_a_role_directly_still_returns_it(conn):
    """
    Retention is a property of the LIST, not of the Role. A long-closed Role is
    still there when something names it — ADR 0010's addressing rule is
    untouched, and a Seeker's deep link to what they applied to still opens.
    """
    assert ids(jobs_by_refs(conn, [CLOSED_15D])) == ["CLOSED_15D"]


def test_it_does_not_touch_the_listing(conn):
    """Read-time only. Nothing is deleted and no state changes — the soft-delete
    rule keeps the row, and a reopened Listing must be able to come back."""
    state = "SELECT is_active, closed_at FROM jobs WHERE source_id = 'CLOSED_15D'"
    before = conn.execute(state).fetchone()
    saved_roles(conn, [CLOSED_15D], now=NOW)
    after = conn.execute(state).fetchone()
    assert (before["is_active"], before["closed_at"]) == (after["is_active"], after["closed_at"])


def test_a_reopened_role_returns_to_the_list_on_its_own(conn):
    """
    The reason this is a read-time rule rather than a pruned reference. The
    upsert clears `closed_at` when a Listing comes back (storage.py `_UPSERT`);
    the Saved Role reappears with no action from the Seeker, who never unsaved it.
    """
    assert saved_roles(conn, [CLOSED_15D], now=NOW) == []
    conn.execute("UPDATE jobs SET is_active = 1, closed_at = NULL WHERE source_id = 'CLOSED_15D'")
    assert ids(saved_roles(conn, [CLOSED_15D], now=NOW)) == ["CLOSED_15D"]


# ── Through the endpoint ──────────────────────────────────────────────────────
# The endpoint has no `now` seam — a route handler taking the current time as a
# query parameter would be a way to see another Seeker's expired Roles, and worse,
# a way to see everyone's. So these seed against the real clock instead.


def real_ago(*, days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import seekers_store
    from fastapi.testclient import TestClient

    db = tmp_path / "jobs.db"
    make_jobs_db(
        db,
        jobs=[
            job(source="workday", source_id="OPEN", title="Open Role"),
            job(source="workday", source_id="JUST_CLOSED", title="Closed Last Night",
                is_active=0, closed_at=real_ago(days=1)),
            job(source="workday", source_id="LONG_CLOSED", title="Closed In May",
                is_active=0, closed_at=real_ago(days=90)),
        ],
    )
    dist = tmp_path / "dist"
    make_bundle(dist)
    monkeypatch.setenv("SEEKERS_DB_PATH", str(tmp_path / "seekers.db"))
    seekers_store.reset_store()
    return TestClient(make_app(db, dist, tmp_path, cookie_secure=False))


def test_the_endpoint_lists_the_open_and_the_recently_closed_but_not_the_long_closed(client):
    """
    End to end, through the real HTTP surface a Seeker's browser talks to: three
    Roles saved, three references in seekers.db, two come back.
    """
    client.post("/api/auth/register", json={
        "email": "seeker@example.com", "password": "correct-horse-battery",
    })
    for source_id in ("OPEN", "JUST_CLOSED", "LONG_CLOSED"):
        assert client.post(
            "/api/me/saved", json={"source": "workday", "source_id": source_id}
        ).status_code == 204

    listed = client.get("/api/me/saved")
    assert listed.status_code == 200
    assert {j["source_id"] for j in listed.json()} == {"OPEN", "JUST_CLOSED"}
    assert [j["closed"] for j in listed.json() if j["source_id"] == "JUST_CLOSED"] == [True]


def test_the_reference_survives_the_role_leaving_the_list(client):
    """
    Hidden, not unsaved. The row in seekers.db is still there, which is what lets
    a reopened Role come back and what stops this being a deletion the Seeker
    never asked for.
    """
    import seekers_store

    client.post("/api/auth/register", json={
        "email": "seeker@example.com", "password": "correct-horse-battery",
    })
    client.post("/api/me/saved", json={"source": "workday", "source_id": "LONG_CLOSED"})
    assert client.get("/api/me/saved").json() == []

    store = seekers_store.get_store()
    seeker = store.get_seeker_by_email("seeker@example.com")
    saved = store.list_saved_roles(seeker["id"])
    assert [(r["source"], r["source_id"]) for r in saved] == [("workday", "LONG_CLOSED")]
