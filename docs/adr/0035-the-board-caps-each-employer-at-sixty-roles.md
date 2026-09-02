# The board caps each employer at 60 Roles, newest first

**Status:** accepted (2026-09-02)
**Builds on:** ADR 0032 (`admin_hidden`, and the `ROW_NUMBER() OVER (PARTITION
BY …)` machinery this reuses), ADR 0033 (which reverted ADR 0032's *sector*
cap), ADR 0034 (enrichment selects on `board_visible_sql()`).

`hk_jobs.board_visibility.board_visible_sql()` gains one clause: a Role is on
the board only if it is among the freshest **`BOARD_COMPANY_CAP` (60)** Roles
for its employer (`jobs.company_slug`), ranked by `posted_at` descending. The
board goes from ~3,250 Roles to ~2,100. Because `job_read.BOARD_WHERE` and
`hk_jobs.enrichment._fetch_unenriched` both read that one function, the browse
board and the salary-estimation queue shrink together.

## Why

The board had drifted to ~3,250 open Roles. The nightly DeepSeek enrichment
(seniority, skills, `description_summary`, and the anchor-table salary estimate
— the *only* estimator, on purpose) is capped at 250 Roles / $2.00 a run, and
new board Roles arrive at ~150–200/night. So enrichment never caught up: on
2026-09-01, **~1,600 of ~3,250 board Roles had no salary figure and ~1,300 had
no card summary** — and the gap was worst on the *freshest* Roles, the ones a
Seeker is most likely to open (73% of Roles posted in the last two days were
un-enriched).

The pool is lopsided by employer. A handful of mega-posters dominate it:

| employer | Roles on the board (2026-09-01) |
|---|---:|
| Bank of China (HK) | 298 |
| HKEX | 219 |
| AIA Hong Kong | 161 |
| Citibank HK | 134 |
| ICBC (Asia) | 129 |
| FWD Insurance | 121 |
| … 20 more over 60 … | |
| ~55 employers | already under 60 |

Capping every employer at the same number brings the board to ~2,100 —
**`Σ min(employer_count, 60)`** — a size the nightly run covers in full with
headroom for the daily inflow (see "The nightly, after this" below). ~55
smaller employers are untouched; only ~26 mega-posters lose Roles, and the
Roles they lose are their *oldest* — the ones nearest aging out of the
one-month window anyway.

**Why per-employer and not per-sector.** ADR 0032 tried a per-sector cap and
ADR 0033 reverted it the same day. Two of that revert's three reasons do not
apply here:

- *"The freshness rank is re-evaluated per read, so the visible board moved
  under the enrichment run instead of holding still."* Sector cohorts are huge
  (2,367 Banking Roles competing for 240 slots — the boundary Role changes
  constantly). Employer cohorts are 60–300; the boundary moves only when that
  one employer posts or ages out a Role, and ~55 employers have no boundary at
  all. The churn that remains is on Roles ~3–5 weeks old that are about to
  leave the board regardless.
- *"Enrichment has no board-aware selection to begin with."* Fixed by ADR
  0034 the next day. The cap lives in `board_visible_sql()`, so
  `_fetch_unenriched` respects it by construction — the exact composition
  failure ADR 0033 hit ("the missing-estimate count rose 415 → 536 even after
  1,164 estimates were written") cannot recur, because there is no second,
  client-side rank.

The third reason — *"no benefit the owner asked for"* — is the opposite here:
the owner asked for a board small enough to enrich in full, for a concrete
reason (every visible Role carries a salary and a summary).

**Why 60.** It lands the board at ~2,100 on the 2026-09 catalogue, the stated
target. It is one module-level constant with no per-employer override; raising
it widens every employer equally. "We show up to 60 current openings per
employer, newest first" is a rule that can be stated plainly on the page.

**Why newest-first and not by relevance or a score.** `posted_at DESC` needs no
enrichment, no model, no stored rank — it is a column every adapter populates
(JobsDB even gives an exact `listingDate` at listing time). Tie broken by
`rowid DESC`. The board's default browse sort is already `Sort.NEWEST`, so the
cap and the list agree on order.

## What changes

### `hk_jobs/board_visibility.py`

`BOARD_COMPANY_CAP = 60` (new constant) and `board_visible_sql()` appends:

```sql
AND j.rowid IN (
  SELECT rowid FROM (
    SELECT j.rowid AS rowid, ROW_NUMBER() OVER (
      PARTITION BY j.company_slug
      ORDER BY j.posted_at DESC, j.rowid DESC
    ) AS _company_rank
    FROM jobs j WHERE <the same open/primary/not-hidden/1-month core>
  ) WHERE _company_rank <= 60
)
```

The subquery is not correlated — it ranks the whole eligible set once. Under
`with_hidden=True` (Ultimate Admin's greyed hidden view, ADR 0032) the
`NOT admin_hidden` clause is dropped from **both** the core and the subquery's
own `WHERE`, so hidden Roles rank in — same as ADR 0032's sector version did.

### Read side — `webapp/backend/job_read.py`

`BOARD_WHERE` / `_BOARD_WHERE_WITH_HIDDEN` are unchanged calls to
`board_visible_sql(...)`, so they pick the cap up for free: the list, `total`,
`total_pages`, the "Showing N" line, the filter facets, `research_total`, and
`role_feed.roles_for_seeker` all now count the capped board.

`LIVE_COUNT_WHERE` (the "X live roles" headline stat) is **not** capped — same
deliberate split ADR 0032 established: reduce what a visitor browses without
moving the number they first see. It stays at ~3,220.

### Write side — enrichment

No code change: `hk_jobs.enrichment._fetch_unenriched` already filters on
`board_visible_sql()` (ADR 0034). Its pool drops from ~3,250 to ~2,100.

### Nightly enrichment limit

`DEEPSEEK_DAILY_ENRICH_LIMIT` / `DEEPSEEK_RUN_BUDGET_USD` raised from
`250` / `$2.00` to **`500` / `$4.00`** (`.github/workflows/daily.yml`). With a
~2,100-Role board and ~110–130 new Roles a night after the cap, 500/night
clears the standing backlog in ~4–6 nights and then holds the board at full
coverage. The one-off backlog (~1,300 Roles from the 22–31 Aug pipeline
outage) is cleared by a manual `enrich_limit` / `enrich_budget` dispatch, not
by the standing limit.

### Vendored copy

`webapp/backend/hk_jobs/board_visibility.py` and `.../enrichment.py` are
synced — the backend imports the vendored copy at runtime (it shadows the real
package on `sys.path`), so a change to `hk_jobs/board_visibility.py` alone
would not reach the live board.

### Tests

- `tests/test_board_visibility_company_cap.py` (new) — pins the predicate at
  the SQL level: an over-cap employer keeps only its freshest 60, a small
  employer is untouched, the cap is per-employer, a capped-out Role stays
  `is_active` (off the *browse* board, not Closed), hidden Roles rank in only
  under `with_hidden`, the constant is the single knob. Shown RED against the
  pre-0035 predicate.
- `tests/test_job_read.py` — two integration tests through `list_jobs`: the
  cap and the `total` that derives from it. Shown RED first.
- `tests/support.py` — the stand-in `jobs` DDL gains `company_slug` (the
  partition key); `job()` defaults it to a slug of the row's `company` so two
  differently-named employers in one fixture stay distinct.
- `tests/test_enrichment_board_only.py` (ADR 0034) still passes unchanged.

### `CLAUDE.md` / `CONTEXT.md`

The board definition gains the cap: "every open, primary Role posted within the
last calendar month, up to 60 per employer (newest first)".

## Consequences

- The board is ~2,100 Roles, ~35% smaller. A genuinely-open Role can be off the
  browse board because 60 fresher ones exist at the same employer — intended.
  `Visibility.ADDRESSABLE` is unaffected: a deep link, a Saved Role, an
  already-granted resume match still resolves. The Role stays `is_active`; the
  nightly scrape keeps re-confirming it; nothing marks it Closed.
- A capped-out Role that later rises back into its employer's freshest 60 (as
  older siblings age out) reappears on the board and is picked up by the next
  enrichment run like any other board Role whose `prompt_version` is stale.
- The board and the "X live roles" stat now describe different sets again
  (~2,100 vs ~3,220). Nothing on the page claims they are the same; the
  board's own "Showing N" line counts the capped set.
- The ASF salary-audit page (`job_read.salary_audit_rows`, Ultimate Admin) is
  `Visibility.BOARD`, so it now lists ~2,100 rows, not ~3,250 — deliberately
  aligned with ADR 0034 (audit the salaries we actually estimate). A Role off
  the board is still corrected by reference; the salary skills (`/price-it`,
  `/fix-s`, `/norm-it`) read the published DB directly and are unaffected by
  this endpoint.
- The `ROW_NUMBER() OVER (PARTITION BY …)` subquery runs on every board-side
  count. At ~19k rows / ~3k eligible it is sub-millisecond in SQLite (measured
  under ADR 0032); revisit only if the table grows an order of magnitude.
- Two `companies.yaml` slugs for one real employer (ADR 0027's cross-slug case)
  get a cap of 60 each. Rare, and arguably right — they are configured as
  separate entries. Not addressed here.
- `BOARD_COMPANY_CAP` is the one knob. If the board needs to be larger or
  smaller later, it moves; there is no per-employer or per-sector override and
  this ADR does not add one.

## Alternatives rejected

**Cut it at the adapter (stop paginating a mega-poster's older Roles).**
Rejected: a Role the adapter stops returning is marked `is_active = 0` by
`mark_inactive_for_run()` — Closed, which is false (it is open, we just stopped
looking). That evicts it from Saved Roles after a fortnight (ADR 0011),
corrupts `company_metrics` / `job_history` with fake closures, and flaps the
Role on and off as the pagination boundary moves. The board predicate keeps
the Role open and addressable while taking it off the browse board.

**Shorten the one-month window instead (to ~3 weeks).** It shrinks the
standing board but does nothing for the *nightly inflow* — new Roles arrive at
the same rate regardless of the window — so it does not make the nightly run's
job smaller in the way that matters. The per-employer cap cuts the inflow too
(a mega-poster's daily posts above 60 never enter).

**Per-sector cap (ADR 0032, reverted).** The owner already rejected it, and it
favours whichever sector posts most. Per-employer is the cleaner unit and a
statable rule.

**Leave the board at ~3,250, target enrichment at a capped subset instead.**
Then ~1,150 board Roles show a blank salary and no summary forever. The owner's
requirement is that every *visible* Role is enriched, so the visible set is
what has to shrink.
