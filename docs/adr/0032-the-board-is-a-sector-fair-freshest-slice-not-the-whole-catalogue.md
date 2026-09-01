# The board is a sector-fair freshest slice, not the whole catalogue

**Status:** accepted (2026-09-01)
**Supersedes:** the `BOARD_POSTING_WINDOW_SQL` rule in `webapp/backend/job_read.py`
(the "one calendar month from the posting date" visibility window and its
ADR-grade code comment). Builds on ADR 0018 (public research does not expose the
catalogue) and ADR 0019 (every admin may correct a Role).

The public board shows **the freshest ~240 Roles per sector** among Roles that
are active, primary, not admin-hidden, and posted within the last 6 months —
about **1,280 Roles today**, down from ~2,750. Everything that describes the
browse experience (the list, `total`, `total_pages`, the "Showing N" line,
pagination, filter facets, `research_total`) counts that slice. The one public
figure that does **not** is the "live roles" headline stat, which keeps its
current meaning.

## Why

The board had drifted to ~2,750 visible Roles, and a read of the live data
(2026-09-01) showed the freshness was mostly nominal: the 0–7-day age bucket was
empty, every visible Role was 7–31 days old, and an estimated 900–1,200 of them
were already closed at source but never deactivated (the scrape had not
completed since 2026-08-21). A smaller, genuinely-fresh board serves a Seeker
better than a large stale one.

**Why a per-sector cap and not a global "freshest N".** The eligible pool is
lopsided by sector:

| Sector | Eligible (active, primary, ≤6mo) |
|---|---|
| Banking | 2,367 |
| Insurance | 1,003 |
| Investment Banking | 666 |
| Professional Services | 342 |
| Private Banking | 269 |
| Asset Management | 75 |
| Digital Assets | 5 |

A global "newest 1,250 by `posted_at`" hands Banking ~50% of the board and
leaves Asset Management ~20 slots — it rewards whichever sector posts most
often, not whichever has the best roles. Capping each sector at the same number
(`BOARD_SECTOR_CAP`, 240) makes Banking and Private Banking equal citizens:
Banking cannot exceed 240, a small sector shows everything recent it has. The
board size is then `Σ min(sector_eligible, 240)` ≈ 1,280 today, tunable within
the 1,000–1,500 target by the one constant.

Sector is `hk_jobs/sector_classify.sector_case_sql("j.title", "j.company")` — a
title/company CASE with an `ELSE 'Banking'` arm, already the single source of
truth for the sector facet and filter. No enrichment dependency, no NULLs, one
rule list.

**Why 6 months is a hard cutoff, not another invisibility.** A Role whose
posting date is over 6 months old is almost certainly filled or withdrawn;
keeping it addressable (deep links, Saved Roles) preserves a link to a vacancy
that no longer exists. So the nightly sweep sets `is_active = 0` on it — the
same soft-delete `JobStore.deactivate()` uses for a Role that vanished from its
source (the row stays, a member's application history is intact, a later scrape
can revive it via `reactivate()`), and it leaves `Visibility.ADDRESSABLE` too.

**Why the "live roles" stat keeps the 1-month meaning and counts hidden Roles.**
The headline figure on the About page, the landing pages and the search hero
(`/api/stats` → `total_active_jobs`) is market context, not a description of the
board — ADR 0018 already exempts it from Research Scope for exactly that reason.
Holding it at "active + primary + posted within 1 month", **without** subtracting
`admin_hidden` and **without** the sector cap, keeps it stable at ~2,750 as the
board is curated down. The intent is deliberate: reduce what a visitor browses
without moving the number they first see.

## What changes

### `admin_hidden` — the invisible state

New `jobs.admin_hidden INTEGER NOT NULL DEFAULT 0` (migration phase 41; index
`idx_jobs_admin_hidden`). A hidden Role is:

- excluded from `BOARD_WHERE` and therefore from the list, every board-side
  count, the facets, and the Roles-for-you / resume-match feeds
  (`role_feed.py`, `BOARD_WHERE` at `job_read.py`)
- **still counted** by `LIVE_COUNT_WHERE` (the headline stat)
- returned unchanged to Admin Mode reads, with the flag surfaced
- toggled by Ultimate Admin from the job-edit drawer (`AdminJobEditDrawer.tsx`
  → a `job_edit.py` route), governed by ADR 0019; the toggle is reversible and
  loses nothing

A hidden Role does not occupy one of a sector's 240 slots — hiding is applied
before the cap, so hiding a Role lets the next-freshest one in that sector take
its place.

### Two predicates where there was one

`job_read.py` splits the single visibility fragment:

- **`LIVE_COUNT_WHERE`** = `j.is_active = 1 AND j.is_primary = 1 AND date(j.posted_at) >= date('now','-1 month')`
  — today's `BOARD_WHERE`, verbatim. Used **only** by `get_stats`'
  `total_active_jobs` (and nowhere else).
- **`BOARD_WHERE`** = `j.is_active = 1 AND j.is_primary = 1 AND NOT j.admin_hidden
  AND date(j.posted_at) >= date('now','-6 months')
  AND j.rowid IN (SELECT rowid FROM (SELECT rowid, ROW_NUMBER() OVER (PARTITION BY (<sector_case_sql>) ORDER BY j.posted_at DESC, j.rowid DESC) AS sr FROM jobs j WHERE <the four conditions above>) WHERE sr <= <BOARD_SECTOR_CAP>)`
  — used by `scope_where`, `list_jobs`, `research_facets`, `role_feed.roles_for_seeker`,
  and `main.py`'s aggregate GROUP BYs.

The invariant ADR 0018's `scope_where` was built to hold — every board-facing
count derives from one predicate so `/api/stats` and `/api/jobs` cannot disagree
about what an open Role is — is preserved: `BOARD_WHERE` is still one fragment,
still the only input to the browse-side counts. `LIVE_COUNT_WHERE` is a
second, deliberately narrower predicate with exactly one caller, not a
sixteenth ad-hoc copy.

### The nightly 6-month sweep

A maintenance step in the daily run (before the PocketBase mirror) runs
`UPDATE jobs SET is_active = 0, closed_at = COALESCE(closed_at, <now>) WHERE
is_active = 1 AND date(posted_at) < date('now','-6 months')`. Roles with a NULL
`posted_at` are swept once their `fetched_at` is over 6 months old — an
undateable Role that has not been re-seen in half a year is dead by the same
logic.

## Consequences

- The board is ~1,280 Roles, ~54% smaller. A genuinely-open Role can be off the
  public board because 240 fresher ones exist in its sector — this is intended,
  and `Visibility.ADDRESSABLE` (Saved Roles, deep links, resume matches already
  granted) is unaffected: a Seeker who saved a Role still sees it.
- A visitor can browse a Role posted up to 6 months ago while the "live roles"
  stat counts only the last month. The two describe different things on
  purpose; nothing on the page claims they are the same set, and the board's own
  "Showing N" line is honest about the slice.
- `BOARD_SECTOR_CAP` (240) and the sweep horizon (6 months) are the two knobs.
  Raising the cap widens every sector equally; there is no per-sector override
  and this ADR does not add one.
- The `ROW_NUMBER() OVER (PARTITION BY …)` subquery runs on every board-side
  count. At ~19k rows and ~5k eligible it is sub-millisecond in SQLite; revisit
  only if the table grows an order of magnitude.
- `hk_jobs/schema.py`, `hk_jobs/storage.py` (DDL, INSERT column list, ON
  CONFLICT), and the vendored `webapp/backend/hk_jobs/` copies all carry the new
  column. `tests/test_migrations.py` and `tests/test_job_read.py` pin the new
  predicates; a test is shown RED first per the project rule.
- `CLAUDE.md` and `CONTEXT.md` gain the term: a Role can be **Hidden**
  (admin-only) distinct from **Closed** (`is_active = 0`).

## Alternatives rejected

**Global freshest-N by `posted_at`.** Rejected as the whole point of the change —
it favours high-frequency sectors, which is the bias the owner explicitly called
out.

**Fair-share with redistribution** (give a small sector's unused slots back to
the big sectors, hitting exactly 1,250). More "efficient" use of the target, but
it needs either stored per-sector quotas recomputed nightly or a recursive CTE,
and it re-introduces exactly the drift risk — a number computed out-of-band that
the counts must trust — that ADR 0018's single-predicate rule exists to prevent.
The flat cap lands in the target band with one constant and no state.

**Invisibility instead of a 6-month hard cutoff.** Rejected: an admin toggle is
a per-Role decision for a human, not a place to absorb 500 stale Roles that
should simply be closed. Hiding also keeps the Role addressable, which is the
opposite of what "gone after 6 months" means.

**Moving the "live roles" stat to the 6-month window** (so it reads ~4,700).
Considered and declined by the owner: the headline number should not jump when
the board is curated down. It stays on the 1-month definition.
