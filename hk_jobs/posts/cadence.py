"""
How often the watchlist poll actually calls Apify.

WHY THIS IS DAILY, AND WHAT THAT ACTUALLY COSTS
-------------------------------------------------
The watchlist poll used to run one pipeline run in three (ADR 0012), to hold
Apify spend inside the free plan. Measuring it showed that premise was wrong —
the poll is now every pipeline run (ADR 0031) because the thing "one in three"
was bought with (fresher posts, sooner) was worth more than what it saved,
which turned out to be close to nothing:

  Apify bills per RESULT, not per call — `VendorResult.cost_usd` is
  `len(items) * $0.002`, and a call returning nothing is not even logged. The
  poll is also watermarked rather than windowed: each recruiter is fetched
  `since` their own `last_fetched_at`, so a poll's total take over a month is
  the same however it is sliced into individual runs.

Same posts, same results, **same bill** — daily or one-in-three. What DOES
change with the interval is the number of actor RUNS (about 59 a night, one
per enabled recruiter, which our ledger prices at zero) and latency: at
one-in-three a post could sit unpromoted for up to three days; daily, at most
one.

The measured steady-state spend (ADR 0012, 2026-08-04): $0.024/day, about
$0.71/month, or 14% of the $5 free credit — comfortably inside the free tier
at either cadence. See docs/adr/0012 and docs/adr/0031.

THE OFF-BY-ONE THIS MODULE STILL HAS TO GET RIGHT FOR ANY INTERVAL
--------------------------------------------------------------------
`run_index % interval == 0`, with `run_index` counted from zero, so an
interval of 3 polls on the 1st, 4th, 7th run — one run in every three, two
skipped between. The off-by-one worth naming is "skip three then run", which
is one in four. `POSTS_RUN_INTERVAL == 1` makes this moot in production today
(every run satisfies `run_index % 1 == 0`), but `claim_run` still takes an
arbitrary `interval`, and `tests/test_posts_cadence.py` pins the general
algorithm at interval=3 regardless of what the deployed default is — a future
cadenced job, or a reason to slow this one back down, gets a correct interval
for free.

THE FLOOR HAS TO COVER THE CADENCE
----------------------------------
`CATCHUP_FLOOR_HOURS` caps how far back a poll will ask, so a stale watermark
cannot turn into a full-history pull. At interval=1 it is 48 hours: a day of
margin over the 24-hour gap a daily poll actually leaves, enough slack for one
late or missed run without truncating the lookback.

So the floor is derived here from the interval rather than written down next
to it. Changing the cadence moves the floor with it; that is the whole reason
both constants live in this module.

WHAT A RUN IS
-------------
An invocation of `--fetch-posts`. `daily_run.sh` — and the hosted GitHub
Actions workflow — call it exactly once per nightly pipeline, so at the
current interval every nightly run polls.

A run that comes up due consumes its turn whether or not the poll then
succeeded — a vendor outage or a hit budget cap does not earn a retry on the
next run. That is the simpler rule and it costs nothing: the watermark does not
advance on a failed poll, so the next successful one covers the whole gap. The
alternative makes the cadence depend on vendor health, and has no clean answer
when a poll half-succeeds across ~30 recruiters.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

#: Run the watchlist poll on one pipeline run in this many. 1 = every run.
#:
#: Raising it does NOT reduce the bill — see the module docstring; billing is per
#: result and the poll is watermarked, so fewer polls each return proportionally
#: more posts. It only trades actor-run count against staleness. One is the
#: owner's decision (2026-08-27, ADR 0031, supersedes the three from ADR 0012).
POSTS_RUN_INTERVAL = 1

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
