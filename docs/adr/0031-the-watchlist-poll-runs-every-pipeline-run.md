# The watchlist poll runs every pipeline run

**Status:** accepted (2026-08-27)
**Supersedes:** ADR 0012 (one pipeline run in three)

The Apify watchlist poll (`--fetch-posts`, phase 5 of `daily_run.sh` and the
hosted GitHub Actions workflow) now runs on **every** pipeline run, reverting
`hk_jobs/posts/cadence.py`'s `POSTS_RUN_INTERVAL` from 3 to 1.

## Why

ADR 0012's own measurement is what makes this change safe: **the interval was
never a cost lever.** Apify bills per RESULT (`VendorResult.cost_usd =
len(items) * $0.002`), and the poll is watermarked — each recruiter is fetched
`since` their own `last_fetched_at`, so a poll's take over any stretch of time
is the same total posts, however that stretch is sliced into individual runs.
Running one night in three was close to cost-neutral in dollars; running every
night is too, for the identical reason. Steady-state spend stays ~$0.71/month,
14% of Apify's $5 free credit, at either cadence — see ADR 0012's own ledger
figures, which this decision does not revisit.

What the interval DOES change is latency and actor-run count, and this
decision trades one for the other in the opposite direction ADR 0012 did:

- **Latency drops from up to three days to at most one.** A recruiter's post
  is now stale for one missed pipeline run, not three, which matters for a
  source whose entire pitch (CONTEXT.md's Recruiter Posts / "Secret Market")
  is roles not yet on the board — ADR 0012 named this the actual price of the
  slower cadence and it is the reason to pay it back.
- **Actor runs return to ~59/night** (one per enabled recruiter), the 3x ADR
  0012 cut. Our ledger prices actor runs at zero today, so this costs nothing
  measured — it gives up the insurance ADR 0012 named explicitly: "real
  insurance if Apify ever meters runs or compute separately from results."
  That insurance is the one thing this decision knowingly forfeits.

## The floor moves with it, for free

`CATCHUP_FLOOR_HOURS` is derived from the interval (`POSTS_RUN_INTERVAL * 24 +
24`), not written down separately — ADR 0012 built it that way for exactly
this situation. At interval=1 the floor is 48 hours: a day of margin over the
24-hour gap a daily poll actually leaves, same shape as "the 48h the store.py
constant used to hardcode before ADR 0012 needed it to move." No manual
follow-up was needed here beyond changing the one constant.

## The one-in-three algorithm is not deleted

`claim_run` still takes an arbitrary `interval`; `POSTS_RUN_INTERVAL == 1` is
a choice about this job, not a constraint the module enforces. The off-by-one
ADR 0012 named ("skip three, then run" is one in four, not one in three)
remains a real bug shape for any interval above 1, so `tests/test_posts_cadence.py`
keeps pinning it explicitly at `interval=3` — independent of what the deployed
default is — rather than deleting that coverage along with today's use of it.

## Consequences

- `hk_jobs/posts/cadence.py`'s `POSTS_RUN_INTERVAL` is `1`; `CATCHUP_FLOOR_HOURS`
  recomputes to 48h automatically.
- Every nightly pipeline run polls; the "skipped run exits 0, not an error"
  path in `_fetch_posts` is unreachable at this interval by construction, but
  stays in the code — a future reason to slow the cadence again should not
  have to rebuild it.
- A post can be at most one pipeline run stale before promotion, down from
  three.
- Actor runs return to ~59/night from ~20/night (3x more calls to Apify),
  costing $0 measured but giving up the run-count insurance margin ADR 0012
  bought. Revisit if Apify ever bills or throttles by call/compute rather than
  result.
- `docs/PLAN_LINKEDIN_POSTS.md`'s decision record and `CLAUDE.md`/`AGENTS.md`'s
  LinkedIn-posts exception section are updated to say "every run," with the
  lineage (daily → one-in-three, ADR 0012 → every run, this ADR) kept rather
  than erased.

## Alternatives rejected

**A smaller interval than 1** does not exist — 1 is every run, the fastest a
run-counted cadence can be. Polling more than once per pipeline run would mean
gating outside `--fetch-posts`'s run-per-invocation model entirely, which
nothing here asked for and which reintroduces exactly the "shell-side check
would not cover a hand-run poll" problem ADR 0012 rejected for the opposite
reason.

**Deleting the cadence module** now that the default is "every run" — rejected
for the same reason ADR 0012 kept the general algorithm rather than
hardcoding "poll always": the interval is a decision this ADR made, not a
property of `claim_run`, and a future reason to slow the poll back down (a
metering change at Apify, a different budget picture) should not have to
rebuild the off-by-one-correct cadence machinery from scratch.
