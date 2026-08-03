# Browsing is filtered; addressing is not

**Status:** accepted (2026-08-03)

Every read of `jobs.db` obeys one of exactly two visibility rules, and which one
applies is decided by *how the caller asked*, not by which endpoint they hit.

- **Browsing** — a query that describes what it wants ("Banking roles, senior,
  newest first") gets `is_active = 1 AND is_primary = 1`. Only open Roles, and a
  vacancy cross-posted to four sources appears once rather than four times.
- **Addressing** — a request that names a specific `(source, source_id)` gets
  that row whatever state it is in. A `closed` field on the response says which.

`webapp/backend/job_read.py` owns both rules. Callers pick a `Visibility`; they
cannot spell a rule of their own.

## Why not one rule

The obvious design is a single invariant hidden behind the interface. We had
that, informally, and it is what caused the bug this ADR comes out of.

`is_active = 1 AND is_primary = 1` lived inside one filter-building function.
`get_job` applied half of it. `list_saved` applied none — so a Saved Role that
had closed came back looking live, with a working apply button, which is the
exact behaviour `CONTEXT.md` promises Saved Roles do not have. The rule had no
home, so two of its three callers forgot it.

But making all three obey the strict rule would have been worse:

- `get_job` would 404 a deep link whose copy stopped being primary at the last
  `reconcile_cross_posted()` run. The link is valid; the primary flag moved.
- `list_saved` would silently drop a Saved Role the moment its vacancy closed —
  hiding precisely the thing a Seeker needs to be told, and defeating the
  soft-delete rule that keeps the row in the first place.

So the two rules are not a compromise between strict and lax. They are two
genuinely different questions. "Show me what is available" must exclude what is
not. "Show me the thing I pointed at" must not, or the pointer is a lie.

## Consequences

- `JobSummary.closed` is part of the public API. It is derived from `is_active`,
  and the storage column name never reaches the wire.
- A Role that has left `jobs.db` entirely is dropped from a by-reference read
  rather than tombstoned — there is nothing to render but the reference. Logged,
  not surfaced. Soft-delete makes this near-impossible in practice.
- `/api/filters` and `/api/stats` build their own aggregate SQL and cannot go
  through the read functions, so they interpolate `job_read.BOARD_WHERE`. Tests
  pin their totals to `/api/jobs` so the two cannot drift.
- Anything that grows a third notion of visibility should be read as a signal
  that a new *kind* of question is being asked, and argued on that basis — not
  added as a third enum member because it is convenient.

## Alternatives rejected

**Filter closed Roles out of Saved Roles.** Simplest, and contradicts
`CONTEXT.md`'s definition of a Saved Role. Rejected: the guarantee is the
feature. Per `PLAN_ACCOUNTS.md` §1 the entire benefit of an account is that
Saved Roles stop going stale, and 43% of Roles posted in the last 30 days are
already closed — so a Seeker returning after a month is near a coin flip.

**Three rules** (`BOARD` / `ADDRESSABLE` / `ANY_STATE`). Drawn up first, then
collapsed: once `ADDRESSABLE` had to return closed Roles so a Seeker could open
their own Saved Role, it was `ANY_STATE` under another name.

**A `status` enum instead of a boolean.** Deferred. There is one non-open state
today. A boolean that later becomes an enum is a smaller migration than an enum
with one meaningful value is a lie.
