# Salary estimation only ever targets a Role on the board

**Status:** accepted (2026-09-01)
**Builds on:** ADR 0032 (`admin_hidden`), ADR 0033 (board = the full one-month
catalogue). Not superseded by anything.

**The rule, and it does not change:**

> WE DO NOT ESTIMATE THE SALARY OF A ROLE THAT IS NOT ON THE BOARD.

`hk_jobs.enrichment._fetch_unenriched` — the query that decides which Roles get
sent to DeepSeek — now filters on `hk_jobs.board_visibility.board_visible_sql()`,
the identical predicate `webapp/backend/job_read.BOARD_WHERE` uses for what a
Seeker browses: `is_active = 1 AND is_primary = 1 AND NOT admin_hidden AND
posted_at within the last calendar month`. There is no `--enrich` /
`--re-enrich` / `--enrich-boutique` exception — those flags force everything
*else* to be reconsidered, not the board rule.

## Why

A bulk enrichment run on 2026-09-01 spent **$5.24 on 1,164 Roles**. Afterwards:

| where the 1,164 went | count | |
|---|---:|---|
| on the board | 395 | the only useful third |
| `is_primary = 0` — a duplicate copy of a cross-posted vacancy | 154 | a Seeker sees the primary copy, never this row |
| posted more than a month ago | 571 | outside the board window entirely |
| no posting date at all | 44 | can never be on the board ("fails closed") |

**66% of the spend went to Roles a Seeker could not see**, and none of it was a
bug in the usual sense — every API call succeeded. The cause was that
`_fetch_unenriched` selected on `is_active = 1` and ordered by `fetched_at`
(when the scraper last touched a row), neither of which has anything to do with
whether the Role is on the board. The read path had a precise definition of
"on the board"; the write path had none, so the two had no reason to agree.

## What changed

- `hk_jobs/board_visibility.py` (new): `board_visible_sql(*, with_hidden=False)`
  — the one definition, on the pipeline side (`hk_jobs` has no dependency on
  `webapp/backend`, so the predicate lives here and `job_read.py` imports it,
  the same direction it already imports `hk_jobs.sector_classify`).
- `webapp/backend/job_read.py`: `BOARD_WHERE` / `_BOARD_WHERE_WITH_HIDDEN` are
  now `board_visible_sql(...)` calls, not a local string. Behaviour is
  byte-identical to the post-ADR-0033 predicate — this is a de-duplication, not
  a change to what the board shows.
- `hk_jobs/enrichment.py`: `_fetch_unenriched`'s `WHERE j.is_active = 1` becomes
  `WHERE {board_visible_sql()}`; the incremental-mode total count matches.
- The vendored `webapp/backend/hk_jobs/` copies of both files are synced.
- `tests/test_enrichment_board_only.py` (new): pins the rule against a duplicate
  copy, a month-old posting, an undated Role, a hidden Role, and both force
  flags. Shown red against `WHERE j.is_active = 1`.

## Consequences

- The nightly `--enrich` pool is now bounded by the board (~2,750 Roles at
  most), not the whole active catalogue (~19k rows). The 250/night limit and
  the dollar cap still apply on top; they now cap spend on Roles that are
  actually visible.
- A Role that ages past one month, gets superseded as the primary copy of a
  cross-post, or is hidden by an admin stops being a re-enrichment candidate
  from that moment — its stored estimate is simply frozen where it is. If it
  comes back onto the board later (reactivated, re-elected primary, un-hidden)
  it is picked up on the next run like any other board Role whose
  `prompt_version` is stale.
- Estimating "every Role a Seeker can see" is now the *only* thing enrichment
  does, so it is also now a tractable, measurable goal — `COUNT(*) WHERE
  {BOARD_WHERE} AND salary_estimated_min IS NULL` is the whole backlog.
- `salary_audit.py` / `salary_repair.py` (deterministic re-clamp of *stored*
  estimates, no new model calls) are untouched — they re-price what enrichment
  already produced and are not "estimation" in the sense this rule governs.

## Alternatives rejected

**Order by `posted_at` instead of `fetched_at`, keep selecting the whole
catalogue.** Reordering makes a bulk run *reach* the board sooner but still
lets a small run, or a run that overshoots, spend on off-board Roles. The rule
is "never," not "later" — a filter, not a sort.

**Put the predicate in `webapp/backend/job_read.py` and import it into
`hk_jobs`.** Wrong dependency direction: the pipeline runs in GitHub Actions
with only `hk_jobs` on the path, no web app. `job_read.py` already reaches into
`hk_jobs` for `sector_classify`, `migrations`, `sources` — this is the same
move.
