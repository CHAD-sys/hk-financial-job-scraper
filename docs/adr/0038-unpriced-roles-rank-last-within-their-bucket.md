# Unpriced Roles rank last, hardest under search

**Status:** accepted (2026-09-03)
**Builds on:** ADR 0035 (which measured the problem: the freshest Roles are the
least likely to be priced), ADR 0034 (enrichment only ever targets the board),
ADR 0036 (a Role carrying no figure is always a re-enrichment candidate).

On the board (`/api/jobs`), a Role whose card shows **no salary figure** ranks
after the priced ones. How far after depends on the sort, and each sort keeps
its own natural bucket:

| sort | bucket | effect |
|---|---|---|
| `RELEVANCE` | **the whole result set** | every priced match outranks every unpriced one; BM25 orders within each group |
| `NEWEST` | the posting day | an unpriced Role never sinks below a Role posted the day before |
| `COMPANY` | the employer | purely additive — this sort had no tiebreak at all |
| `SALARY_HIGH` / `SALARY_LOW` | — | already sink unpriced rows; untouched |

It is an ordering rule and nothing else: the Role stays on the board, stays
addressable, and is still counted in `total`.

**Search is the case that matters.** Typing into the box is how a Seeker looks
for one specific thing, and `JobBoardPage.tsx:145` switches the sort to
`relevance` the moment they do — so the searching Seeker is the one reader who
never sees the `NEWEST` rule at all. That is why `RELEVANCE` gets the strongest
form, and the only one that reorders across the whole result rather than inside
a bucket. An earlier draft of this ADR exempted relevance on the reasoning
below, under "Alternatives rejected"; the owner overruled it, and was right to.

## Why

A card with no salary figure is the weakest card on the board. It is the one
field a Seeker scans for, and the Role next to it usually has one.

Enrichment is a queue, not a property of arrival. A Role scraped tonight is
priced within a night or two, not on the way in. So under plain `posted_at
DESC` the queue points exactly the wrong way — the freshest Roles, the ones
page 1 is made of, are precisely the ones nothing has priced yet. ADR 0035
measured this directly: **73% of Roles posted in the last two days were
un-enriched**, and it named the consequence as the reason to cap the board —
"the gap was worst on the *freshest* Roles, the ones a Seeker is most likely to
open".

ADR 0035 fixed the supply side: cap the board at 60 Roles per employer so the
nightly run can price all of it. This is the display side of the same problem.
Even with enrichment keeping up, there is always a window — one night wide —
where the newest Roles are unpriced, and under a pure recency sort that window
is the top of page 1. On the 2026-09-02 snapshot the first 72 rows of the board
were 53% unpriced.

## What "unpriced" means

The same question `JobCard.tsx` asks when it decides whether to render a figure:
a disclosed range if there is one, otherwise the AI estimate, otherwise nothing.

```sql
COALESCE(e.salary_hkd_min, e.salary_hkd_max,
         e.salary_estimated_min, e.salary_estimated_max) IS NULL
```

All four columns, not the `_max` pair the salary sorts read, so a Role carrying
only a floor — which the card renders as "HK$45k+/mo" — counts as priced. On
the 2026-09 board the two predicates happen to select the same 1,191 rows
because min and max always travel together; the wider one is still the correct
one, because it is the one that matches what the Seeker sees.

The AI estimate counts. It has been visible to every visitor since the owner
decision of 2026-09-03 (`3369d2e`), so "does this card show a figure" has the
same answer for every reader and the ordering does not depend on who is asking.

## Why NEWEST buckets but RELEVANCE partitions

`NEWEST` is a **labelled** sort. The dropdown says "Newest first", and a rule
that put a week-old priced Role above one posted this morning would make that
label false — `ORDER BY has_salary, posted_at` is a filter wearing an ordering's
clothes, and with ~20% of the live board unpriced it pushes ~440 Roles behind
every priced Role. The day bucket gets the same first-three-pages result while
the label stays true.

`RELEVANCE` carries no such promise. "Most relevant" is a ranking nobody can
audit from the outside — the Seeker cannot tell whether the 4th result beat the
9th on BM25 or on a salary figure, and has no expectation that they could. The
sort is already a blend of signals (`search_index` promotes exact title matches
and excludes opposite-title ones before job_read ever sees the list). Adding one
more signal at the front of that blend breaks no promise the UI makes.

And it is the only form that delivers what was asked. Under a bucketed rule the
priced matches sitting at relevance ranks 30–60 never reach page 1; only a
partition pulls them up.

The bucket keeps both properties true at once. Under `NEWEST` the bucket is the
posting **day**: an unpriced Role never sinks below a Role posted the day
before, so newest still means newest, and the demotion is bounded by one day's
volume.

**The day bucket costs nothing, because sub-day order carried no information.**
`posted_at` is midnight on 651 of 2,216 board rows (date-only sources), and the
rest cluster on the minute the scraper ran — dozens of rows at `...T09:1x` from
one batch. Within a day the ordering was scrape order, not posting order. This
rule spends noise and buys a signal.

Under `COMPANY` the rule is purely additive: `j.company ASC` had no tiebreak at
all, so rows within one employer came back in whatever order SQLite chose.

## What changes

### `webapp/backend/job_read.py`

`_DEMOTED_SORT_SQL` — the demoted form of each sort, alongside `_SORT_SQL`:

```
NEWEST   date(<valid posted_at>) DESC NULLS LAST,
         <priced first>,
         <valid posted_at> DESC NULLS LAST
COMPANY  j.company ASC, <priced first>
```

`SALARY_HIGH` / `SALARY_LOW` have **no entry**: their leading `CASE` already
sinks unpriced rows to the bottom in both directions, and a second copy of that
rule could only drift from the first.

`_order_sql(sort, search_rowids, demote_unpriced=False)` (new) is now the one
place an `ORDER BY` is chosen. It replaces the identical five-line conditional
that `list_jobs` and `salary_audit_rows` each spelled out.

`list_jobs` gains `demote_unpriced: bool = False`, shaped exactly like
`boost_recruiter_posts`: opt-in, order-only, no effect on `total` or the WHERE
clause.

### `webapp/backend/main.py`

`/api/jobs` passes `demote_unpriced=True`. It is the only caller that does.

### Who opts out, and why the flag is not inside `_SORT_SQL`

- **`role_feed._candidates`** takes a bounded newest-first window and scores it
  (ADR 0014). Demoting would change *which* Roles reach the scorer, quietly
  biasing recommendations toward priced ones and shrinking the pool — the same
  reason it already declines `boost_recruiter_posts`.
- **`salary_audit_rows`** is Ultimate Admin hunting the unpriced Roles. Its
  sort must not be the one that hides them. This is the decisive argument for a
  caller's flag over a change to `_SORT_SQL[NEWEST]`: the two screens read the
  same rows through the same sort and want opposite answers.
- **The SEO shell** (`_category_body`) sorts by `RELEVANCE`, so it is unaffected
  either way.

### Relevance, the strongest form

`_order_sql` puts `_PRICED_FIRST` ahead of the BM25 replay:

```sql
ORDER BY <priced first>, CASE j.rowid WHEN … THEN … END ASC
```

One extra leading term, and the BM25 `CASE` is still emitted **once**. That is
not incidental: `search_index.matching_rowids` returns up to 20,000 rowids and
the `CASE` carries one `WHEN` per rowid ("a few hundred ms in the worst case",
per its own docstring), so any form needing it twice — banding by
`rank / N`, say — would double the most expensive expression in this module.
The partition costs nothing measurable.

Measured against the 2026-09 board, page 1 goes to **zero** unpriced results on
every query tried:

| query | board matches | page 1 before | page 1 after |
|---|---:|---:|---:|
| `quantitative` | 196 | 9 / 24 unpriced | **0 / 24** |
| `private banking` | 74 | 2 / 24 | **0 / 24** |
| `risk manager` | 84 | 0 / 24 | **0 / 24** |

`risk manager` also shows the rule's honest ceiling: 48 of its 84 matches are
priced, so pages 1–2 are clean and page 3 necessarily starts on unpriced rows.
The rule ranks; it cannot manufacture coverage. Enrichment does that.

`RELEVANCE` with *nothing* to rank by is a different case: it already falls
back to `NEWEST`, so what it actually runs is a newest-first listing, and it
takes the day-bucketed form like any other.

### Composition with the Recruiter Posts boost

They compose without special-casing. `_boosted_rows_sql` ranks within each tier
by whatever expression it is handed, so Recruiter Posts keep their reserved
slot in every stride — priced or not — and the demotion applies inside each
tier. This matters: 82% of Recruiter Posts on the 2026-09 board carry no
figure, so a rule that ranked *across* tiers would have quietly undone Secret
Market visibility, which is the entire point of paying for that source.

### Not a vendoring case

`job_read.py` and `main.py` live only under `webapp/backend/`. The vendored
`webapp/backend/hk_jobs/` copy that shadows the real package at runtime (ADR
0035's last section) holds neither file, so nothing needs syncing here.

### Tests

`tests/test_job_read.py` gains thirteen tests. Each was shown RED against a
deliberate mutant of the real code, not merely written before the feature:

| mutant | tests that caught it |
|---|---|
| demotion is a no-op | same-day ordering, COMPANY sort, relevance fallback |
| hard partition under NEWEST (no day bucket) | *never crosses a day* |
| **relevance exempted** | search partition (unit + HTTP) |
| **priced-first as a BM25 tiebreak** (too weak to reorder) | search partition (unit + HTTP) |
| **BM25 dropped inside each group** | BM25 order preserved, search partition |
| `_max`-only predicate | disclosed-floor-alone counts as priced |
| rule baked into `_SORT_SQL` | salary-audit rows still show unpriced first |

Two fixtures had to be rebuilt because they passed for the wrong reason — the
same failure mode both times, and the reason this repo's rule is that a test be
*shown* red rather than merely written first:

- the floor test put the unpriced row *older*, so under a `_max`-only predicate
  both rows fell on the same side and the tiebreak dropped through to recency.
  The figureless Role is now the newer one.
- the search fixture inserted its priced rows shortest-first, so BM25 order and
  rowid order agreed and a rule that discarded relevance entirely still looked
  correct. They are now inserted longest-first, so the two disagree.

## Consequences

- Page 1 of the board is priced. On the worst-case snapshot measured (54%
  unpriced — a stale local copy; the live board is ~20%) the first 72 rows went
  from 53% unpriced to 0%, while by row 240 unpriced Roles are back at 69%.
  They are demoted, not banished.
- **Internships are demoted too.** 85 are on the board, 36 unpriced — and they
  are unpriced *by design* (ADR 0037's follow-up stopped re-enriching them), so
  no future run will lift them. Accepted rather than carved out: the rule is
  about the card a Seeker reads, not about why the figure is missing, and a
  Seeker filtering `is_internship=true` sees only internships anyway, ordered
  among themselves.
- The demotion is a *symptom* rule. If the unpriced share of the board grows,
  it hides that from the board without reporting it. The measurement that
  matters stays the one ADR 0035 and 0036 use — the unpriced count on the
  board — and it is unaffected by this ADR, because `total` and every facet
  count are unchanged.
- A Role priced by tonight's run rises tomorrow with no other change. Ordering
  is computed per read; there is nothing stored and nothing to backfill.
- Two sorts are exempt by construction (`SALARY_HIGH`, `SALARY_LOW`) because
  they already sink unpriced rows. A new `Sort` member gets no demotion until
  someone adds an entry to `_DEMOTED_SORT_SQL`, which is the safe default.
- **A very relevant unpriced Role can fall behind less relevant priced ones.**
  This is the real cost of the partition, and it lands hardest on the exact
  case `search_index._promote_exact_title_matches` exists to serve: an exact
  title match carrying no figure loses that promotion. Accepted for now — the
  Role is still returned, still on page 1 of a small result set, and still
  addressable by deep link. If it bites, the fix is to exempt the
  exact-title-promoted prefix of `search_rowids` rather than to weaken the rule
  everywhere; that needs `matching_rowids` to report how many rows it promoted,
  which it does not today.

## Alternatives rejected

**Exempt search relevance.** The first draft of this ADR did exactly that, on
the reasoning that a Seeker who typed a query is answering "which of these is
the role I meant", so a card's salary is not evidence about the match.
Overruled by the owner, and the reasoning was wrong on its own terms: a Seeker
looking for one specific thing is *more* invested in the answer, not less, and
a result they cannot price is a worse answer to their question, not a purer
one. It also left the rule aimed at the one reader who never encounters it —
the board switches to `relevance` the moment the search box is typed into, so
the exemption meant searching Seekers saw no change at all.

**Band the relevance ranking (priced-first within each block of N matches).**
The bounded middle ground: no Role moves more than one band, so a strong match
cannot fall far. Rejected on two counts. Banding on raw BM25 position is
meaningless — `matching_rowids` ranks ~15k rows including inactive and
non-primary duplicates, and the board-visible fraction varies per query, so a
band of 100 rowids is anywhere from 5 to 80 visible rows and the rule's
strength would swing query to query. Banding on *visible* position needs a
`ROW_NUMBER()` window pass, which then has to nest inside `_boosted_rows_sql`'s
own window pass — two interacting window functions over one result set,
producing an order neither docstring describes.

**A fixed age penalty (treat an unpriced Role as posted N days earlier).**
Tunable and smooth, but no value of N is defensible: the board runs at
~70–220 Roles a day, so even N=1 pushes an unpriced Role past a full day of
priced ones — the day bucket with none of the day bucket's honesty about what
"newest" means. It also silently reorders across the one boundary a recency
sort exists to respect.

**A reserved-slot cadence, mirroring the Recruiter Posts boost in reverse.**
The machinery already exists. Rejected: the boost occupies that mechanism, and
two interacting stride merges over the same result set produce an order neither
rule's docstring describes.

**Filter unpriced Roles off the board until they are enriched.** Rejected on
ADR 0035's own terms — that ADR shrank the board so every visible Role could be
priced, and this would shrink it again by a set that changes nightly, flapping
Roles on and off the board as the enrichment queue drains. It also contradicts
ADR 0010: an open Role a Seeker can address should be one they can browse to.

**Show an explicit "salary not estimated yet" state on the card instead.** Not
mutually exclusive, and possibly worth doing — but it is a frontend change that
makes the gap *more* prominent, which is the opposite of what was asked for
here. Left open.
