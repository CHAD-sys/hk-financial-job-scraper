"""
One pipeline run in three calls Apify.

THE RULE, AND THE OFF-BY-ONE IT IS EASY TO GET WRONG
----------------------------------------------------
The watchlist poll runs on the 1st, 4th, 7th run — one run in every three, with
two skipped between. The tempting mistake is "skip three, then run", which is one
in four: 25% cheaper than asked for and 33% staler. `test_it_is_one_in_three_not_one_in_four`
is the test that tells them apart, and it is the reason this file exists.

THE SECOND HALF, WHICH IS NOT ABOUT MONEY
-----------------------------------------
Slowing the poll down silently breaks it unless the catch-up floor moves too.
Each recruiter is fetched `since = max(last_fetched_at, now - CATCHUP_FLOOR_HOURS)`.
At 48h — right for a daily poll — a three-run cadence leaves the watermark ~72h
old, `max` picks the floor, and the poll asks for two days of a three-day gap.
A day of recruiter posts would go missing every cycle, and the only trace would
be the routine "capping lookback" line the fetcher already logs on purpose.

So the floor is derived from the interval, and
`test_the_catchup_floor_covers_the_whole_gap_the_cadence_creates` fails if anyone
changes one without the other.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from hk_jobs.migrations import migrate
from hk_jobs.posts import cadence
from hk_jobs.posts.cadence import (
    CATCHUP_FLOOR_HOURS,
    POSTS_RUN_INTERVAL,
    claim_run,
    peek,
)


@pytest.fixture()
def db(tmp_path: Path) -> str:
    path = str(tmp_path / "jobs.db")
    migrate(path)
    return path


def run_pattern(db: str, n: int, **kw) -> list[bool]:
    """Whether each of `n` consecutive runs polls."""
    return [claim_run(db, **kw).due for _ in range(n)]


# ── The cadence ───────────────────────────────────────────────────────────────

def test_the_first_run_polls(db: str):
    """
    A fresh counter must not sit out two runs before doing anything. Anyone
    deploying this expects the next nightly run to poll.
    """
    assert claim_run(db).due is True


def test_it_is_one_in_three_not_one_in_four(db: str):
    """
    THE test. Both plausible readings of "every 3 runs" produce a pattern; only
    one of them is what was asked for.

        one in three (this):  poll . . poll . . poll     <- 3 polls in 9 runs
        one in four  (wrong): poll . . . poll . . . poll <- 3 polls in 12 runs
    """
    assert run_pattern(db, 9) == [
        True, False, False,
        True, False, False,
        True, False, False,
    ]


def test_exactly_one_run_in_three_polls_over_a_long_stretch(db: str):
    """A month of nightly runs. The ratio is the whole point, so state it."""
    pattern = run_pattern(db, 30)
    assert sum(pattern) == 10
    assert len(pattern) == 30


def test_the_gap_between_polls_is_always_the_interval(db: str):
    polled = [i for i, due in enumerate(run_pattern(db, 30)) if due]
    gaps = {b - a for a, b in zip(polled, polled[1:])}
    assert gaps == {POSTS_RUN_INTERVAL}


def test_the_interval_is_three(db: str):
    """
    Pinned deliberately. The number was chosen against measured spend — the
    watchlist was 91% of vendor cost and the month landed at ~86% of Apify's free
    credit — so changing it is a decision, not a tweak, and should break a test.
    """
    assert POSTS_RUN_INTERVAL == 3


# ── The counter ───────────────────────────────────────────────────────────────

def test_every_run_is_counted_including_the_skipped_ones(db: str):
    """
    A skipped run must still advance the counter or the cadence never advances —
    the poll would be due forever and nothing would be saved.
    """
    run_pattern(db, 5)
    assert peek(db)["runs"] == 5


def test_the_counter_survives_the_process(db: str):
    """
    It has to live in the database. `--fetch-posts` is a separate process per
    nightly run, so anything in memory starts over at run 0 every night and polls
    every time — the exact thing this is supposed to stop.
    """
    assert claim_run(db).due is True
    assert claim_run(db).due is False
    # A brand-new connection, as the next night's process would have.
    assert claim_run(db).due is False
    assert claim_run(db).due is True


def test_a_poll_and_a_skip_are_told_apart_in_the_record(db: str):
    """`last_due_at` answers "when did we last poll", not "when did we last look"."""
    claim_run(db)
    after_poll = peek(db)
    claim_run(db)
    after_skip = peek(db)

    assert after_skip["last_run_at"] != after_poll["last_run_at"], "every run is seen"
    assert after_skip["last_due_at"] == after_poll["last_due_at"], "only a poll moves this"


def test_two_jobs_keep_separate_counters(db: str):
    claim_run(db, name="a")
    assert claim_run(db, name="b").due is True
    assert peek(db, name="a")["runs"] == 1
    assert peek(db, name="b")["runs"] == 1


def test_peek_does_not_advance_anything(db: str):
    claim_run(db)
    peek(db)
    peek(db)
    assert peek(db)["runs"] == 1
    assert claim_run(db).due is False, "peeking must not have burned a run"


def test_peek_on_a_counter_that_has_never_run(db: str):
    assert peek(db) == {"name": cadence.WATCHLIST, "runs": 0,
                        "last_run_at": None, "last_due_at": None}


# ── Forcing ───────────────────────────────────────────────────────────────────

def test_force_polls_on_a_run_that_is_not_due(db: str):
    claim_run(db)
    assert claim_run(db).due is False
    assert claim_run(db, force=True).due is True


def test_forcing_still_counts_as_a_run(db: str):
    """
    Otherwise a hand-run poll sits outside the cycle and the next nightly run is
    due anyway — two paid polls in two runs, which is what the cadence exists to
    prevent.
    """
    claim_run(db, force=True)
    assert peek(db)["runs"] == 1


def test_a_forced_run_says_it_was_forced(db: str):
    """
    `forced` distinguishes "we overrode the cadence" from "--posts-force was
    passed on a run that was going to poll anyway". Only the first is worth
    seeing in a log when you are working out where the money went.
    """
    claim_run(db)                                  # run 0 — its turn
    forced = claim_run(db, force=True)             # run 1 — overridden
    assert forced.forced is True
    assert "forced" in forced.describe()

    claim_run(db)                                  # run 2 — skipped
    earned = claim_run(db, force=True)             # run 3 — its turn regardless
    assert earned.due is True
    assert earned.forced is False, "the flag changed nothing on this run"


# ── Configuration ─────────────────────────────────────────────────────────────

def test_an_interval_of_one_polls_every_run(db: str):
    assert run_pattern(db, 4, interval=1) == [True, True, True, True]


def test_an_interval_below_one_is_refused(db: str):
    """
    Silently treating 0 as "never" would stop the poll forever; as "always" would
    spend on every run. Neither is a guess worth making on the caller's behalf.
    """
    with pytest.raises(ValueError, match="at least 1 run"):
        claim_run(db, interval=0)


# ── The floor that has to move with it ────────────────────────────────────────

def test_the_catchup_floor_covers_the_whole_gap_the_cadence_creates(db: str):
    """
    THE silent-data-loss guard. The floor must be at least the cadence gap, or
    the poll asks for less time than has actually passed.
    """
    assert CATCHUP_FLOOR_HOURS >= POSTS_RUN_INTERVAL * 24, (
        f"a {POSTS_RUN_INTERVAL}-run cadence leaves a {POSTS_RUN_INTERVAL * 24}h gap, "
        f"but the floor caps lookback at {CATCHUP_FLOOR_HOURS}h — every cycle would "
        "lose the oldest posts, logging only the routine 'capping lookback' line"
    )


def test_the_floor_has_slack_for_a_late_or_missed_run(db: str):
    assert CATCHUP_FLOOR_HOURS >= POSTS_RUN_INTERVAL * 24 + 24


def test_the_fetcher_asks_for_the_whole_gap_at_this_cadence(db: str):
    """
    The floor arithmetic through the real resolver rather than against the
    constant, because `_resolve_since` is what the vendor call actually uses.

    At 48h this asserted 2 days of cover for a 3-day gap — the bug, before the
    floor was derived from the interval.
    """
    from hk_jobs.posts.fetcher import _resolve_since

    now = datetime.now(UTC)
    gap_hours = POSTS_RUN_INTERVAL * 24
    watermark = (now - timedelta(hours=gap_hours)).isoformat()

    since = datetime.fromisoformat(_resolve_since(watermark))
    covered_days = (now.date() - since.date()).days

    assert covered_days >= gap_hours / 24, (
        f"poll asks for {covered_days}d but {gap_hours / 24}d have passed"
    )


def test_the_store_still_exports_the_floor(db: str):
    """It moved to cadence.py; every existing caller imports it from store."""
    from hk_jobs.posts.store import CATCHUP_FLOOR_HOURS as from_store

    assert from_store == CATCHUP_FLOOR_HOURS


# ── Storage ───────────────────────────────────────────────────────────────────

def test_the_table_is_created_by_a_migration(db: str):
    conn = sqlite3.connect(db)
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()
    assert "run_cadence" in tables


# ── Through the CLI mode ──────────────────────────────────────────────────────
# The gate lives in `_fetch_posts`, not in daily_run.sh, because the cost is a
# property of the poll rather than of one caller's crontab. These check the wire
# actually reaches the vendor call — a cadence nothing consults saves nothing.

def _args(db: str, **over):
    from hk_jobs.cli import PipelineArgs

    return PipelineArgs(db=db, fetch_posts=True, **over)


def _run_fetch_posts(db: str, monkeypatch, **over) -> list[str]:
    """Run the mode with the vendor call replaced; returns one entry per poll."""
    from hk_jobs import cli
    from hk_jobs.posts import fetcher

    polls: list[str] = []

    def fake_fetch_watchlist(db_path, **kw):
        polls.append(db_path)
        return fetcher.FetchRunSummary(recruiters_polled=1)

    monkeypatch.setattr(fetcher, "fetch_watchlist", fake_fetch_watchlist)
    cli._fetch_posts(_args(db, **over))
    return polls


def test_the_mode_polls_on_one_run_in_three(db: str, monkeypatch):
    polls = []
    for _ in range(6):
        polls.append(bool(_run_fetch_posts(db, monkeypatch)))
    assert polls == [True, False, False, True, False, False]


def test_a_skipped_run_is_not_an_error(db: str, monkeypatch):
    """
    daily_run.sh treats a non-zero exit from this phase as a WARNING it logs.
    Skipping is the expected outcome two runs in three, so raising here would
    put a false alarm in the log more often than not.
    """
    _run_fetch_posts(db, monkeypatch)                      # run 0 — polls
    assert _run_fetch_posts(db, monkeypatch) == []         # run 1 — skips, no raise


def test_posts_force_reaches_the_vendor_on_a_skipped_run(db: str, monkeypatch):
    _run_fetch_posts(db, monkeypatch)
    assert _run_fetch_posts(db, monkeypatch, posts_force=True) != []


def test_the_flag_is_off_by_default(db: str):
    from hk_jobs.cli import PipelineArgs, build_parser

    assert PipelineArgs().posts_force is False
    parsed = PipelineArgs.from_namespace(build_parser().parse_args(["--fetch-posts"]))
    assert parsed.posts_force is False
    forced = PipelineArgs.from_namespace(
        build_parser().parse_args(["--fetch-posts", "--posts-force"])
    )
    assert forced.posts_force is True


def test_the_backfill_is_not_gated(db: str, monkeypatch):
    """
    A one-time deep pull is a human asking for it now. Putting it behind the
    cadence would mean "run the backfill" silently doing nothing two times in
    three, which is the worst possible answer for a manual command.
    """
    from hk_jobs import cli
    from hk_jobs.cli import PipelineArgs
    from hk_jobs.posts import fetcher

    calls: list[bool] = []
    monkeypatch.setattr(
        fetcher, "fetch_watchlist",
        lambda db_path, **kw: (calls.append(kw.get("backfill", False)),
                               fetcher.FetchRunSummary(recruiters_polled=1))[1],
    )
    for _ in range(3):
        cli._fetch_posts_backfill(PipelineArgs(db=db, fetch_posts_backfill=True))
    assert calls == [True, True, True]
