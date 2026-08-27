# Saved Roles resolve to an active vacancy sibling

**Status:** accepted (2026-08-27)

`reconcile_cross_posted` elects `is_primary` from scratch on every run — no
identity persists between runs for "which copy is the displayed one." That
was already known to be safe for browsing: `Visibility.ADDRESSABLE`
(`webapp/backend/job_read.py`) exists specifically so a reference to a
now-non-primary copy still resolves, "whatever state it is in," rather than
404ing a link whose copy stopped being primary at the last reconciliation.

## The gap this left open

A Saved Role stores `(source, source_id)` of whichever copy was primary at
save time. `ADDRESSABLE` correctly keeps returning that exact row even after
it stops being primary — but if that SPECIFIC copy's *source* later drops
the listing entirely (`is_active = 0`), while the same real vacancy is still
open under a *sibling* source in the same cluster, the Saved Role now
resolves to a row that is genuinely closed. The Seeker sees "this role has
closed" for a role that has not — the vacancy is still live, just not under
the one copy they happened to bookmark.

This is a narrower, more precise version of what the original
cross-posted-matching audit flagged as "no persisted vacancy identity across
runs." The `is_primary`-churn framing overstated the risk (`ADDRESSABLE`
already handles that part); the real gap is specifically about a Saved
Role's exact copy closing while a sibling survives.

## The decision

Two additions, both additive to what exists:

1. **`jobs.vacancy_id`** (migration phase 38): a stable id assigned to every
   cross-posted cluster by `reconcile_cross_posted` (`_elect_vacancy_id`),
   persisted across runs — the one thing genuinely new here, since
   `is_primary` is deliberately NOT persisted. Adopts a member's existing id
   when there's exactly one; mints one when there's none; and when a
   bridging source merges two previously-separate ids into one cluster, the
   DISPLAY_ORDER-preferred row's id wins. A single-source Role has no
   vacancy_id — nothing to fall back to.

2. **`job_read._resolve_vacancy_refs`**: runs before `_by_refs`'s own query
   (the shared body of `jobs_by_refs` and `saved_roles`) and rewrites any
   reference whose exact row is inactive to an active sibling sharing its
   `vacancy_id`, if one exists. `_by_refs`'s retention SQL, visibility rule,
   and order-preservation are untouched — this only changes WHICH reference
   gets looked up, never how the lookup behaves once it has one.

`vacancy_id` is a lookup key only. A Saved Role's own stored reference
stays `(source, source_id)` exactly as before — no change to `seekers.db`,
no migration of existing saved references, no new field a Seeker's client
needs to know about.

## What this does not fix

If BOTH the saved copy and every sibling in its cluster are closed, the
Saved Role still correctly reads as closed — there is no vacancy left to
resolve to. And a vacancy that was never cross-posted has no sibling by
definition; closing is closing. Neither is a gap — a Role that has actually
closed everywhere should say so.
