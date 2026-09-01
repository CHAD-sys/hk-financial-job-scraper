# Revert the board's sector-cap and 6-month window

**Status:** accepted (2026-09-01)
**Supersedes:** the freshness-cap and 6-month-window halves of ADR 0032 (accepted
and deployed the same day). ADR 0032's other two decisions — the `admin_hidden`
state and the Ultimate-Admin-only access rule for it — are **not** reverted; see
"What stays" below.

The board is the full catalogue again: every open, primary, not-admin-hidden
Role posted within the last calendar month. `job_read.BOARD_WHERE` drops the
per-sector freshness cap (`BOARD_SECTOR_CAP`) and the 6-month window entirely,
reverting to exactly `LIVE_COUNT_WHERE`'s rule plus the `admin_hidden` exclusion.

## Why

ADR 0032 shrank the board from ~2,750 Roles to a sector-fair freshest ~1,280 to
solve a real problem — much of the board was stale and about to only get
staler with the scrape pipeline down. The stated goal, from the owner, was
narrower than what got built: run the AI salary estimator against the Roles a
Seeker can actually see. That work surfaced the trade-off in the worst
possible light: the curation cut the board roughly in half, and the estimator
run that followed still couldn't cover what was left, because the two
constraints didn't compose the way they were expected to —

- The sector cap is re-evaluated on every read, but a Role's freshness rank
  shifts as neighbouring Roles' `posted_at`/`fetched_at` change, so "the
  visible board" was not a stable target between the estimator run starting
  and the count being checked afterward: the missing-estimate figure on the
  board *increased* (415 → 536) even though the run wrote 1,164 new estimates.
- Enrichment has no board-aware selection (`_fetch_unenriched` orders by
  `fetched_at DESC` across the whole active catalogue); scoping it to "only
  the curated board" was never actually implemented, so the run's coverage of
  the board was incidental, not targeted.

Put together: a smaller, harder-to-target board, for a genuinely-open Role
that a Seeker could no longer find. That is a worse outcome than the stale
board ADR 0032 set out to fix, and reverting immediately — rather than trying
to patch the interaction — is the responsible response to shipping something
that made the product worse.

## What reverts

- `job_read.BOARD_WHERE`: no more per-sector cap, no more 6-month window. Back
  to `is_active = 1 AND is_primary = 1 AND NOT admin_hidden AND posted_at >=
  now - 1 month` — identical to `LIVE_COUNT_WHERE` except for the
  `admin_hidden` clause.
- `BOARD_SECTOR_CAP`, `_BOARD_FRESHNESS_CAP_SQL`, and the `ROW_NUMBER() OVER
  (PARTITION BY sector)` subquery are deleted from `job_read.py`, not merely
  disabled — there is no live code path that still ranks Roles by sector.
- The board is ~2,750 Roles again — every board-side count (`total`, the
  "Showing N" line, facets, `research_total`) moves back up with it, since
  they all derive from the one `BOARD_WHERE` fragment.
- `tests/test_job_read.py`'s sector-cap tests are deleted; the 6-month-window
  test reverts to asserting one month, restoring its pre-0032 form.

## What stays

- **`admin_hidden`** (migration phase 41) and the Ultimate-Admin-only access
  rule from ADR 0032's "Who may see a hidden Role" section. Both are correct,
  narrowly-scoped features that were never the source of the problem — an
  admin manually burying an individual bad Listing is unrelated to an
  automatic mechanism that reshapes the whole board. `admin_hidden` still
  excludes a Role from `BOARD_WHERE`; the `admin_hidden=include`/`only` query
  param, the FilterBar control, and the greyed `JobCard` treatment are
  unchanged.
- **`hk_jobs.storage.JobStore.deactivate_aged_out()`** (the nightly 6-month
  `is_active = 0` sweep). This is pipeline hygiene, not board display — it
  retires a Listing that is almost certainly filled, the same soft-delete
  every other `deactivate()` caller uses. With the board back on a 1-month
  window, essentially nothing that old was ever going to be `is_active = 1`
  and inside the window regardless; the sweep just makes that state true in
  storage rather than leaving a zombie row to rot.
- `LIVE_COUNT_WHERE` and `live_count_where()` stay as their own predicate
  rather than being collapsed back into a single constant — a future change
  to the admin-hidden exclusion (or another Ultimate-Admin-only carve-out)
  should not have to re-split them again from scratch.

## Consequences

- The board no longer needs SQLite window functions for browsing; the
  `admin_hidden=include`/`only` admin path is correspondingly simpler too
  (`_build_board_where` is now a two-line string, not a ranked subquery).
- Enrichment coverage of what a Seeker actually sees is, once again, not
  something the product tracks or targets — it is whatever the nightly
  `--enrich` backlog-clearing happens to reach, `fetched_at`-ordered, same as
  it was before ADR 0032. If "estimate every visible Role" is revisited, it
  needs its own targeted selection in `hk_jobs/enrichment.py` (a board-derived
  ref list, not a client-side rank), built and reviewed as its own step —
  not bundled with a board-visibility change again.
- The ~1,164 Roles enriched during the reverted board's lifetime keep their
  estimates; nothing about this revert un-enriches them.

## Alternatives rejected

**Keep the cap, fix the targeting instead** (give enrichment a board-aware
selection so the estimator run actually tracks the curated board). Rejected
for now: it does not address the harder complaint — the board is smaller and
harder to browse for no benefit the owner asked for. If a future need for a
smaller board reappears, it should be re-argued and re-built as its own
decision, not resurrected as a side effect of fixing enrichment targeting.

**Widen the cap instead of removing it** (e.g. raise `BOARD_SECTOR_CAP` until
the board is back near 2,750). Rejected: at that point the cap does nothing —
it stops mattering once it exceeds every sector's real population — so keeping
the machinery around costs the window-function complexity for zero effect.
