# Cross-posted matching refuses named different districts

**Status:** accepted (2026-08-27)

`JobStore.reconcile_cross_posted()` clustered same-employer rows into
vacancies by fuzzy title match alone, explicitly "location-independent" — a
prior fix (`test_reconcile_matches_despite_different_location_strings`)
deliberately made it ignore locations, because eFC's "Hong Kong" vs JobsDB's
"Hong Kong SAR" were the same vacancy phrased two ways, and location-aware
matching had been sinking that match to zero.

## The gap this reopened

Multi-branch employers (HSBC, Hang Seng, Standard Chartered, and most HK
insurers) routinely run near-identical titles at different branches in the
same week — "Relationship Manager" in Central and, separately, in Kwun Tong.
With location fully ignored, two genuinely different openings cross-posted
under a shared fuzzy title would collapse into one card, silently dropping
one of them from the board.

## The decision

`_cluster_by_title` now extracts named HK districts from `locations`
(`_location_districts`, matched against a fixed lexicon in `_HK_DISTRICTS`)
and refuses a match when **both** sides name a district and those sets are
**disjoint**. Generic HK-wide phrasing ("Hong Kong", "Hong Kong SAR", "HK")
produces no district tokens on either side, so the original fix this ADR
must not regress — title-only matching — still applies whenever the
signal isn't there to use.

The lexicon is deliberately not exhaustive. An address it doesn't recognise,
or a single-sided district (one row says "Central", the other just "Hong
Kong"), falls back to the pre-existing behavior rather than blocking the
match — a missed district is a false negative on this rule alone, not a
wrong merge, and the safe direction to err toward here is the one that keeps
today's real cross-source matches working.

## Consequence

A cross-posted vacancy whose two source pages disagree on which named
district it's in (one page stale, one current) will now show as two cards
instead of one, until the stale copy is re-scraped or ages out. This is the
accepted trade for not silently erasing a distinct branch opening; see ADR
0027 for the sibling decision this extends (company-name grouping across
slugs) and the wider cross-posted-matching audit it was written against for
what's still open (richest-source-wins discarding better data from a demoted
copy; no persisted vacancy identity across runs).
