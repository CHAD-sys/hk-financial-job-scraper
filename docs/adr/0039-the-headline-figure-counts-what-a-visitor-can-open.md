# The headline figure counts what a visitor can open

**Status:** accepted (2026-09-03)
**Supersedes:** the headline/board split in ADR 0032, carried forward by ADR 0035.

The "X live roles" figure — the About page, the landing pages, the search hero,
the bare `/jobs` header — counts **the board**. The number a visitor is shown is
the number of Roles that visitor can actually open.

`job_read.live_count_where()` returns `BOARD_WHERE` plus the caller's audience
scoping. `LIVE_COUNT_WHERE`, the separate wider predicate, is deleted.

## Why

ADR 0032 split the two deliberately, and the reasoning was sound at the time:
the board was becoming a *curated* slice, and curating it down should not move
the number a visitor first sees. ADR 0035's per-employer cap then inherited that
split.

What nobody re-checked is how big the gap got. Measured on the 2026-09
catalogue:

| | roles | employers |
|---|---:|---:|
| headline figure | **3,331** | 134 |
| what a visitor can browse | **2,148** | 129 |

**36% of the headline was Roles nobody could reach.** Not withheld, not
member-only, not closed — simply past their employer's 60-Role cap, counted in
a number presented as what the site has.

The split's own justification is what fails here. "Curating the board down
should not move the number" is right when the curation removes noise a visitor
would not want anyway. ADR 0035's cap does not do that: it removes ~1,200
genuinely open, genuinely relevant Roles, purely so the nightly enrichment
budget covers what remains. That is an operational constraint, and an
operational constraint should not be invisible in the number we publish.

And a visitor does not read "3,331 live roles" as a statement about a catalogue
they cannot see. They read it as "this site has 3,331 jobs". It did not.

## What "reality" means here, precisely

Three candidate numbers, and why the middle one wins:

- **Every open Role we hold (~19k rows).** No — most are closed, duplicated
  cross-posts, or months old. Nobody claims this is the number.
- **Open, primary, posted this month, uncapped (3,331).** What we *track*. A
  true and interesting figure — it is the one the market-intelligence reports
  use — but it is not a fact about the portal.
- **The board (2,148).** What a visitor can find, open and apply to. This is
  what the sentence "how many jobs are on our portal" means.

The second number does not disappear; it stops being the one on the marketing
surface. Anything that genuinely wants market context (the PDF reports,
`docs/HK_MARKET_REPORT.html`) computes its own totals and is unaffected by this
ADR — none of them go through `live_count_where`.

## What changes

`job_read.py` — `LIVE_COUNT_WHERE` deleted; `live_count_where(audience)` now
returns `BOARD_WHERE` + audience scoping. Its three callers (`get_stats`,
`_hub_body`, `_landing_pages` in `main.py`) are unchanged.

This moves **every** figure those surfaces publish, not only the headline:
`total_active_jobs`, `employer_count`, and the `by_sector` / `by_seniority` /
`by_remote_type` / `by_source_tier` / `top_skills` breakdowns. That is the
point — under the split, the breakdowns summed to more than a visitor could
browse, so a sector count and the board's own "Showing N" disagreed for the
same filter.

One behavioural side effect, accepted: `BOARD_WHERE` excludes `admin_hidden`
Roles and the old predicate included them, so hiding a Role now moves the
headline by one. ADR 0032 wanted the opposite. It is the right way round: a
Role an admin has hidden is not one a visitor can open, so it should not be
counted as one. 0 Roles are hidden today.

### Tests

`tests/test_jobs_api.py::test_the_headline_figure_counts_only_what_a_visitor_can_open`
— an employer put **over** `BOARD_COMPANY_CAP`, asserting the headline, the
board total and the sector breakdown all agree. Shown RED against the restored
pre-0039 predicate.

The existing `test_stats_and_jobs_agree_on_what_is_open` passes either way and
always did: its fixture has no employer near the cap, so the two predicates
agree by accident there. An over-cap employer is the only fixture shape in
which the split is visible at all — which is exactly why the gap survived two
ADRs without anything going red.

## Consequences

- **The public number drops ~36%, from ~3,332 to ~2,150.** This is the whole
  point and it should be stated plainly to anyone who tracks it: nothing about
  the market changed, and no Role was lost. The old number was counting Roles
  the board does not show.
- The headline and the board's own "Showing N roles" now agree, as do the
  sector facets. Under the split they could not, and a visitor comparing them
  saw an unexplained shortfall.
- Raising `BOARD_COMPANY_CAP` now raises the published figure too. That is a
  coupling ADR 0032 deliberately avoided; it is reinstated knowingly, because
  the alternative is publishing a number the product does not honour.
- If the marketing surface later wants the wider market figure back, it should
  return as its **own labelled statistic** ("we track N roles across HK
  finance") beside the board count — not as an unlabelled headline that reads
  as a catalogue size. This ADR does not add one.

## Alternatives rejected

**Keep the number, change the label** ("3,331 roles tracked"). Cheaper, and
honest as far as it goes. Rejected: the figure sits in a hero and on the
Careers door, where nobody reads a qualifier, and it would still disagree with
the "Showing N" line one click later. A number that needs a footnote to stop
being misleading is the wrong number.

**Raise `BOARD_COMPANY_CAP` until the gap closes.** That is the *other* way to
make the two agree, and it is a real option — but it is an enrichment-budget
decision (ADR 0035), not a presentation one, and it would put ~1,200 Roles back
on the board with no salary estimate, which is the exact problem 0035 was
written to solve.
