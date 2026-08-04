# The watchlist poll runs one pipeline run in three

**Status:** accepted (2026-08-04)
**Supersedes:** the "daily watchlist polling" half of `PLAN_LINKEDIN_POSTS.md` decision 2

The Apify watchlist poll (`--fetch-posts`, phase 5 of `daily_run.sh`) runs on one
pipeline run in every three — the 1st, 4th, 7th — with two runs skipped between.
`hk_jobs/posts/cadence.py` owns the interval and the counter; the gate is inside
the `--fetch-posts` mode, not in `daily_run.sh`.

## Why — and an honest accounting of what it does and does not save

The owner asked for this to hold Apify spend inside the free plan. Measuring it
properly afterwards showed the premise needs correcting, so this section records
what the numbers actually say rather than what the change was expected to do.

**Apify bills per result, not per call.** `VendorResult.cost_usd` is
`len(items) × $0.002`, and `_record_result_cost` does not even log a call that
returned nothing. Cost is therefore a function of how many posts recruiters
write, not of how often we ask.

**The poll is watermarked, not windowed.** Each recruiter is fetched `since`
their own `last_fetched_at`, so a poll covering three days returns the three days
of posts that three daily polls would have returned between them.

Put together: **running one night in three is close to cost-neutral in dollars.**
Same posts, same results, same bill. What it cuts by 3× is the number of *actor
runs* — roughly 59 per polling night, one per enabled recruiter — which our
ledger prices at zero.

The spend figures, from `vendor_costs` on 2026-08-04:

| period | billed calls | posts | spend |
|---|---|---|---|
| 2026-07-22 (one-off backfill) | 67 | 1,849 | **$3.698** |
| 2026-07-23 … 2026-08-04 (steady state, 8 polling days) | 65 | 95 | **$0.190** |

Steady state is **$0.024/day → ~$0.71/month**, or **14% of Apify's $5 free
credit**. The alarming-looking $4.29 July total is 95% one-time backfill, which
does not recur. The $30/month cap from decision 6 has never been close to firing,
and neither, it turns out, has the free tier.

**So this is not the change that keeps us on the free plan — we were already
comfortably on it.** It is kept because it is what was asked for, it is harmless,
and the 3× reduction in actor runs is real insurance if Apify ever meters runs or
compute separately from results. It should not be described as a cost fix.

## What it does cost

Latency. A post can now be up to three days old before it is promoted, where it
used to be one. Acceptable for a source that is explicitly a side channel rather
than the board — but it is the actual price paid here, and it is paid for a
saving that is close to zero in dollars.

One thing to watch: `fetch_profile_posts` takes `max_posts=20` per profile per
poll. At the observed rate (~1.5 posts per recruiter per poll) a three-day poll
lands near 4–5 and nowhere near the cap, but a recruiter posting more than ~6
times a day would now be truncated where a daily poll would not have been.

## One in three, not one in four

`run_index % 3 == 0`, counted from zero. The off-by-one worth naming is "skip
three, then run", which is one in four — 25% cheaper than intended and 33%
staler. `tests/test_posts_cadence.py::test_it_is_one_in_three_not_one_in_four`
exists to tell the two apart.

## The catch-up floor had to move with it

`CATCHUP_FLOOR_HOURS` caps how far back a poll will ask, so a stale watermark
cannot become a full-history pull. It was 48 hours, which is correct for a daily
poll and **silently wrong for any slower one**: at a three-run cadence the
watermark is ~72h old, `max(last_fetched_at, now - 48h)` selects the floor, and
the poll asks for two days of a three-day gap. A day of recruiter posts would
have gone missing every cycle, and the only trace in the log would be the routine
"capping lookback" line the fetcher already emits on purpose.

So the floor is now **derived** from the interval in `cadence.py`
(`POSTS_RUN_INTERVAL * 24 + 24`) rather than written down separately. Changing
the cadence moves the floor with it, and a test fails if the two ever disagree.
`store.py` re-exports the constant, because that is where every caller already
imports it from.

## Consequences

- **A skipped run exits 0.** `daily_run.sh` treats a non-zero exit from phase 5
  as a warning it logs; skipping is the expected outcome two runs in three, so
  failing would put a false alarm in the log more often than not.
- **The counter is in the database** (`run_cadence`, phase 31). `--fetch-posts`
  is a separate process per night, so anything in memory would restart at run 0
  and poll every time.
- **A due run consumes its turn even if the poll then fails.** A vendor outage or
  a hit budget cap does not earn a retry on the next run. This costs nothing: the
  watermark does not advance on a failed poll, so the next successful one covers
  the whole gap. The alternative makes "one in three" depend on vendor health and
  has no clean answer when a poll half-succeeds across ~30 recruiters.
- **`--posts-force` overrides it**, and still counts as a run, so forcing shifts
  the cycle rather than sitting outside it.
- **`--fetch-posts-backfill` is not gated.** It is a human asking for a deep pull
  now; making it silently do nothing two times in three is the worst available
  answer for a manual command.
- **Discovery (phase 5b) is unchanged** — Mondays only, and $0.064 of spend to
  date. Gating it further would save nothing measurable. If it ever grows, it
  gets its own counter; `claim_run` already takes a name.

## Alternatives rejected

**Gate it in `daily_run.sh`** with a counter file. Fewer moving parts, and wrong
in one specific way: the cost belongs to the poll, not to one caller's crontab. A
hand-run `--fetch-posts` spends exactly the same money and a shell-side check
would not have covered it.

**Gate on elapsed time** ("don't poll if we polled within 3 days"). Stateless —
it could read `last_fetched_at` — and it drifts: if a run is missed, a time gate
still fires on the next one, so the cadence silently becomes "whenever a run
happens more than 3 days later". Runs are what was asked for and runs are what is
counted.

**Raise the interval further (5, 7).** Cheaper still, and the latency starts to
matter for a source whose entire pitch is that these roles are not on the board
yet. Three keeps us inside the free tier with room; revisit if spend moves.
