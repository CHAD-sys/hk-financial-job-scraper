# A Closed Role leaves Saved Roles after a fortnight

**Status:** accepted (2026-08-04)
**Narrows:** ADR 0010 (browsing is filtered, addressing is not)

A Saved Role that has been **Closed** for longer than fourteen days stops
appearing in the Seeker's list. Everything else about it is unchanged: the
Listing stays in `jobs.db`, the reference stays in `seekers.db`, and the Role is
still there when something addresses it by `(source, source_id)`.

The window lives in `webapp/backend/job_read.py` as `SAVED_ROLE_RETENTION`, and
the rule is applied by `job_read.saved_roles` — the only function that knows it.
`GET /api/me/saved` calls that; nothing else may spell a window of its own.

## Why this is not the thing ADR 0010 rejected

ADR 0010 lists "filter closed Roles out of Saved Roles" under alternatives
rejected, and the reasoning was right: 43% of Roles posted in the last 30 days
are already closed, so a Seeker returning after a month would find a list that
had silently emptied itself of exactly the Roles they wanted to look back at.
Being told a Role closed *is* the feature.

This rule keeps that. A Seeker who comes back on Tuesday to a Role that closed on
Monday is told it closed, with the `closed` flag and the badge, unchanged. What
this adds is an end to it. A Role that closed three months ago is not information
any more, it is clutter, and a list that only ever grows is one the Seeker
eventually stops opening.

So the disagreement with 0010 is about duration, not about whether. Fourteen days
is long enough to cover "I applied to this and want to check what it said" and
short enough that the list stays about the Roles a Seeker is actually working on.

## Why it is not a third Visibility

ADR 0010 asks that anything reaching for a third visibility rule be argued as a
new *kind* of question rather than added as a convenient enum member. This is
that argument, and the answer is that it is not a visibility rule at all.

Visibility answers "may this reader see this row". This answers "is this still
worth keeping in front of them", which is retention — the same distinction as
between an access rule and an inbox that archives old mail. Addressing is
untouched: `jobs_by_refs` and `get_job` still return a Role closed in May, so a
deep link to what a Seeker applied to still opens, and the board still shows open
Roles only.

`saved_roles` is therefore a second function over the same machinery rather than
a third `Visibility` member. Both go through one private body; the retention
predicate is the only difference.

## Recording when a Listing closed

The rule needs a fact the schema did not carry. `is_active` says a Role is no
longer open and nothing said for how long — `job_history` counts Listings per
company per day, not the fate of one Listing — so a Saved Role that closed last
night and one that closed in May were the same row to every reader.

Phase 30 adds `jobs.closed_at`, written by `JobStore.deactivate()` and cleared by
the upsert when a Listing comes back. That it is trustworthy at all is a
consequence of `deactivate()` being the single write path to `is_active = 0`: a
closure date written by three of the four writers that used to exist would make
NULL mean either "still open" or "the writer that forgot", and a rule reading it
would be a coin flip.

**The backfill is a proxy.** 10,126 rows were already closed with no date.
`fetched_at` is the last time a Listing was seen alive, and deactivation happens
on the first run that does not see it, so for a closed row it lands within about
a day of the truth. It is wrong in one direction: a company whose scrape kept
failing has its deactivation deferred by the guards in `mark_inactive_for_run`,
so those rows read as older than they are. The alternative — leaving them NULL —
would have handed every long-dead Saved Role a fresh fortnight starting from
whenever the migration happened to run. Measured on the live database: 6,423 of
the 10,126 are dated more than a fortnight ago, 3,703 within.

## Consequences

- **Every unknown keeps the Role.** A NULL `closed_at`, or one `datetime()`
  cannot parse, fails open. Hiding a Saved Role is the destructive direction —
  the Seeker did not ask for it to go — so it happens only on a date we can read.
- **Nothing is deleted.** The rule is read-time only, which is what makes it
  reversible: a Listing that reopens has its `closed_at` cleared by the upsert and
  the Saved Role returns on its own, with the Seeker never having unsaved it.
  Pruning the reference instead would have made a reopening unrecoverable.
- **The backend requires a migrated `jobs.db`.** `saved_roles` reads
  `j.closed_at`, so a backend deployed against a database that has not reached
  phase 30 will fail this endpoint. This is not a new coupling — the read path
  already requires `grp_new` (phase 22) and `board_signals` (phase 21) — but it
  is the first one added since Saved Roles existed, so it is worth stating: the
  database migrates before the backend deploys.
- **Signed-out visitors are unaffected.** The localStorage store keeps whole Job
  copies rather than references (see `savedRoles/store.ts`), so it cannot learn
  that a Role closed, let alone when. Giving it the rule means re-resolving local
  saves against the server, which is a different change. Deferred, and consistent
  with `PLAN_ACCOUNTS.md` §1: not going stale is what the account is *for*.
- **One visible seam.** A Seeker who reaches a long-closed Role by deep link sees
  it as unsaved even when the reference is still there, because the bookmark
  state is derived from the list. Reachable only from an old link to a Role
  closed over a fortnight; re-saving it is harmless and idempotent.

## Alternatives rejected

**Delete the `saved_roles` row.** "Disappears" would mean disappears, and the
storage would be tidier. Rejected because it is irreversible in the one case that
matters — a Listing that reopens — and because unsaving is the Seeker's action to
take, not ours.

**Make the window configurable per Seeker.** No Seeker has asked, there is no
settings surface to put it on, and a per-Seeker window is a much harder thing to
remove later than to add. Revisit if anyone actually asks.

**Show them under a "Closed" fold instead of removing them.** Genuinely better
for the Seeker who wants their history, and a real option later. It is a design
change to `SavedJobsPage`, not a rule, so it does not belong in this decision.
