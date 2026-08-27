# Cross-posted primary election checks the row, not just the source

**Status:** accepted (2026-08-27)

`reconcile_cross_posted` elects one copy of a cross-posted vacancy as
`is_primary = 1`; `job_read._to_summary` then reads the displayed Role's
description, salary, and skills entirely off that one row's own columns.
Everything else in the cluster — including any richer data a demoted copy
happens to carry — was unreachable.

## The gap

`sources.DISPLAY_ORDER` ranks JobsDB first because JobsDB rows are *usually*
the richest: "9 of 9 active rows carry a full description," per its own
comment. That's a statistical prior about the source, applied unconditionally
to every row from it. A specific JobsDB copy that's stale or was only ever
listing-scraped breaks that assumption, and when it does, `_primary_rowid`
still elects it — discarding a fuller Workday or eFC copy sitting in the same
database, on the same run, for no reason a Seeker could see.

## The decision

`_primary_rowid` now checks richness per row (`_richness`: has a non-empty
`description_clean`, has a disclosed `salary_min`) before accepting the
DISPLAY_ORDER default. The default only loses its slot when another copy in
the same cluster is **strictly** richer — has a description or salary the
default lacks. Ties keep the DISPLAY_ORDER pick exactly as before; this only
ever fires when there's a concrete, checkable reason to move.

This is deliberately narrower than a full field-level merge (best description
+ best salary assembled onto whichever row displays). That would need
`_to_summary` to read from a synthesized composite rather than one row, which
touches the read path this ADR doesn't. Electing a different existing row is
the smaller, sufficient fix: it stops content loss without changing what
"the primary row" means anywhere else in the codebase.

## Consequence

Which copy is primary can now depend on data, not only on source identity —
already true in spirit (idempotent per-run recomputation, ADR-adjacent to
0027/0028's grouping changes), but now also true of the field this decision
is about. Combining this with `is_primary` having no persisted identity
across runs (a known, separately-tracked gap — see the cross-posted-matching
audit) means the displayed copy can, in principle, alternate between two
richness-tied-then-untied copies run to run. Not addressed here.
