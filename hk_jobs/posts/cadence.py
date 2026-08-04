"""
How often the watchlist poll actually calls Apify.

WHY THIS EXISTS, AND WHAT IT ACTUALLY SAVES
-------------------------------------------
The watchlist poll is the only thing in this repo that calls a paid vendor on
every nightly run, and the owner asked for it to run one night in three to stay
inside Apify's free plan. It does that. But measuring it afterwards showed the
saving is not the one you would assume, and it is worth knowing which:

  Apify bills per RESULT, not per call — `VendorResult.cost_usd` is
  `len(items) * $0.002`, and a call returning nothing is not even logged. The
  poll is also watermarked rather than windowed: each recruiter is fetched
  `since` their own `last_fetched_at`, so a three-day poll returns the three
  days of posts that three daily polls would have returned between them.

Same posts, same results, **same bill**. What this cuts by 3x is the number of
actor RUNS — about 59 a night, one per enabled recruiter — which our ledger
prices at zero. Keep that in mind before reaching for a bigger interval to save
money; it will not.

The measured spend, for scale: steady state is $0.024/day, about $0.71/month,
or 14% of the $5 free credit. The $4.29 that July looks like is 95% one-off
backfill (2026-07-22, 1,849 posts in a single deep pull) and does not recur.
See docs/adr/0012.

What this DOES cost is latency: a post can be three days old before it is
promoted, where it used to be one.

ONE IN THREE, NOT ONE IN FOUR
-----------------------------
`run_index % interval == 0`, with `run_index` counted from zero, so the poll
runs on the 1st, 4th, 7th run: exactly one run in every three, with two skipped
between. The off-by-one worth naming is "skip three then run", which is one in
four and 25% cheaper than asked for — and 33% staler.

THE FLOOR HAS TO COVER THE CADENCE
----------------------------------
`CATCHUP_FLOOR_HOURS` caps how far back a poll will ask, so a stale watermark
cannot turn into a full-history pull. It lived in `store.py` at 48 hours, which
is right for a daily poll and silently wrong for any slower one: at a three-run
cadence the watermark is ~72h old, `max(last_fetched_at, now - 48h)` picks the
FLOOR, and the poll asks for two days of a three-day gap. A day of recruiter
posts would go missing every cycle, with nothing in the logs but the routine
"capping lookback" line.

So the floor is derived here from the interval rather than written down next to
it. Changing the cadence moves the floor with it; that is the whole reason both
constants live in this module.

WHAT A RUN IS
-------------
An invocation of `--fetch-posts`. `daily_run.sh` calls it exactly once per
nightly run, so "one run in three" is one nightly pipeline in three.

A run that comes up due consumes its turn whether or not the poll then
succeeded — a vendor outage or a hit budget cap does not earn a retry on the
next run. That is the simpler rule and it costs nothing: the watermark does not
advance on a failed poll, so the next successful one covers the whole gap. The
alternative makes "one in three" depend on vendor health, and has no clean
answer when a poll half-succeeds across ~30 recruiters.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

#: Run the watchlist poll on one pipeline run in this many.
#:
#: Raising it does NOT reduce the bill — see the module docstring; billing is per
#: result and the poll is watermarked, so fewer polls each return proportionally
#: more posts. It reduces actor runs and increases how stale a post can be before
#: it is promoted. Three is the owner's decision (2026-08-04).
POSTS_RUN_INTERVAL = 3

#: How far back a poll will ask when the watermark is older than this. Must
#: cover the whole gap the cadence creates, plus a day of slack for a late or
#: missed run — otherwise the floor quietly truncates the lookback.
CATCHUP_FLOOR_HOURS = POSTS_RUN_INTERVAL * 24 + 24

#: The counter the watchlist poll keeps. A name rather than a bare table so a
#: second cadenced job later does not have to invent its own storage.
WATCHLIST = "posts_watchlist"


@dataclass(frozen=True)
class RunDecision:
    """What this run should do, and where it sits in the cycle."""

    due: bool
    #: 0-based index of THIS run since the counter began.
    run_index: int
    interval: int
    #: 0 when due; otherwise how many more runs until the next one is.
    runs_until_due: int
    #: True when the caller overrode the cadence rather than earning its turn.
    forced: bool = False

    def describe(self) -> str:
        if self.forced:
            return f"forced (run #{self.run_index + 1}, would not otherwise be due)"
        if self.due:
            return f"due (run #{self.run_index + 1}, 1 run in {self.interval})"
        return (
            f"not due (run #{self.run_index + 1}, 1 run in {self.interval}; "
            f"next in {self.runs_until_due})"
        )


def claim_run(
    db_path: str,
    *,
    name: str = WATCHLIST,
    interval: int = POSTS_RUN_INTERVAL,
    force: bool = False,
) -> RunDecision:
    """
    Record that a run happened and say whether it is this job's turn.

    One call does both on purpose. Split into `is_due()` and `record_run()` the
    counter can advance without a decision, or a decision be taken twice on one
    run — and either way the cadence silently stops being what it claims.

    `force=True` still records the run, so overriding the cadence by hand shifts
    the cycle rather than sitting outside it.
    """
    if interval < 1:
        raise ValueError(f"interval must be at least 1 run, got {interval!r}")

    now = datetime.now(UTC).isoformat()
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            row = conn.execute(
                "SELECT runs FROM run_cadence WHERE name = ?", (name,)
            ).fetchone()
            run_index = int(row[0]) if row else 0

            due = force or (run_index % interval == 0)
            remainder = run_index % interval
            runs_until_due = 0 if due else interval - remainder

            conn.execute(
                "INSERT INTO run_cadence (name, runs, last_run_at, last_due_at) "
                "VALUES (?, 1, ?, ?) "
                "ON CONFLICT (name) DO UPDATE SET "
                "  runs = run_cadence.runs + 1, "
                "  last_run_at = excluded.last_run_at, "
                # Only moved when this run actually took its turn, so it stays
                # readable as "when did we last poll", not "when did we last look".
                "  last_due_at = COALESCE(excluded.last_due_at, run_cadence.last_due_at)",
                (name, now, now if due else None),
            )
    finally:
        conn.close()

    decision = RunDecision(
        due=due,
        run_index=run_index,
        interval=interval,
        runs_until_due=runs_until_due,
        forced=force and run_index % interval != 0,
    )
    logger.debug("Cadence %s: %s", name, decision.describe())
    return decision


def peek(db_path: str, *, name: str = WATCHLIST) -> dict[str, object]:
    """
    The counter as it stands, without touching it. For reports and for humans
    asking "when does this next run".
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT name, runs, last_run_at, last_due_at FROM run_cadence WHERE name = ?",
            (name,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return {"name": name, "runs": 0, "last_run_at": None, "last_due_at": None}
    return dict(row)
