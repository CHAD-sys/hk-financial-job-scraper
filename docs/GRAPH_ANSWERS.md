# Graph Answers — open questions resolved against the live system (2026-07-29)

Verified answers to the questions the knowledge graph raised but could not answer
from source text alone. Each answer was checked against the actual config files
and the live `data/jobs.db`, not inferred. Where an answer contradicts
`CLAUDE.md`, that is stated plainly — `CLAUDE.md` is the older document.

Method: read `hk_jobs/companies.yaml` and `hk_jobs/companies_longtail.yaml` with
PyYAML, counted adapters, and queried `data/jobs.db` with sqlite3. Verified at
commit `7fbbc18`.

## The scope is 147 companies, not 30

`CLAUDE.md` opens with "the 30 largest Hong Kong financial institutions". That
number is stale by ~5x. The real configured scope, split across two files:

| File | Entries | Enabled | Unique company slugs |
|---|---|---|---|
| `hk_jobs/companies.yaml` | 196 | 179 | 78 |
| `hk_jobs/companies_longtail.yaml` | 69 | 69 | 69 |
| **Total** | **265** | **248** | **147** |

Entries outnumber companies because one company gets one entry *per source*
(e.g. Bank of China HK appears under both `jobsdb` and `efinancialcareers`). The
adapter test docstring in `tests/test_successfactors.py` that says "the other
190-odd" is counting enabled *entries*, and is roughly right at 179+69=248 — the
docstring is closer to reality than the project brief is.

## Confirmed: fallback sources carry 96% of coverage

This confirms the graph's `Fallback Sources Carry 96% of Coverage (contradicts
the ATS table)` claim, with exact numbers. Enabled entries in
`hk_jobs/companies.yaml` by adapter:

| Adapter | Entries | Kind |
|---|---|---|
| `jobsdb` | 65 | scraped fallback (ToS-violating) |
| `linkedin` | 48 | scraped fallback (guest pages) |
| `indeed` | 37 | scraped fallback (ToS-violating) |
| `efinancialcareers` | 23 | scraped fallback |
| `workday` | 4 | real ATS JSON API |
| `eightfold` | 1 | real ATS JSON API |
| `successfactors` | 1 | real ATS HTML parse |

Clean ATS API sources are **6 of 179 enabled entries (3.4%)**; scraped fallbacks
are **173 of 179 (96.6%)**. The ATS table in `CLAUDE.md` ("Large HK financial
firms almost all use Workday, Eightfold, or SuccessFactors") describes the
*intended* architecture, not the shipped one. The legal exposure is therefore the
dominant case, not the exception — the ToS-violation note in `CLAUDE.md` applies
to nearly the whole corpus.

## The single Eightfold tenant is HSBC; the single SuccessFactors tenant is HKJC

The two "easy JSON API" adapters each carry exactly one employer. `hsbc-hk` is
the lone Eightfold tenant (578 rows, 318 active). `hkjc` is the lone
SuccessFactors tenant (19 rows, 10 active) — the newest source, added in commit
`266f14a`, and the only ingestion that ran on 2026-07-29.

## The nightly run is 10 phases, and Phase 5b is Monday-only

Confirms the graph's `Nightly Run Has Ten Steps, Not Six` claim.
`scripts/daily_run.sh` (115 lines) runs, in order:

1. Phase 1 — scrape listings: `python -m hk_jobs.pipeline`
2. Phase 2 — fetch descriptions: `--fetch-descriptions` (missing only)
3. Phase 3 — DeepSeek enrichment: `--enrich` (unenriched only)
4. Phase 3b — salary outlier audit: `--audit-salaries`
5. Phase 4 — PocketBase mirror: `python -m hk_jobs.sync_pocketbase`
6. Phase 5 — LinkedIn recruiter posts (watchlist): `--fetch-posts`
7. Phase 5b — LinkedIn discovery search: `--posts-discovery` — **Monday only**, gated by a weekday check
8. Phase 5c — promote posts (LP-3): `--promote-posts`
9. Phase 6 — DB backup: `--backup` (30-day rolling retention)
10. Phase 7 — daily summary email: `--notify-summary`

The `docs/architecture_guide` hyperedge "The Six-Phase Nightly Run" counts only
the pre-LinkedIn phases and predates LP-2/LP-3. Six is the old shape; ten is
current. Phases 3b, 4, 5, 5b, 5c are individually non-fatal (each is
`|| true`-style guarded), so a vendor or PocketBase outage cannot abort the run.

## Confirmed: the "all 27 companies" comment in daily_run.sh is stale

`scripts/daily_run.sh:35` reads `# Phase 1: Scrape listings from all 27
companies`. Phase 1 passes no `--only` flag, so it actually scrapes every enabled
entry in *both* YAML files — 248 entries / 147 companies. The comment is off by
an order of magnitude and should say "all enabled companies".

## `companies.yaml` is no longer the single source of company config

`CLAUDE.md` states "All per-company settings live in `companies.yaml`, never
hardcoded". There are now **two** company config files, both loaded by
`hk_jobs/pipeline.py:74-80`: `companies.yaml` (ATS + board fallbacks) and
`companies_longtail.yaml` (69 boutique firms with bespoke careers pages, routed
to `LongtailAdapter`). The longtail file is merged in automatically unless
`--no-longtail` is passed; `--longtail-only` isolates it. The convention holds in
spirit (nothing is hardcoded) but the "one file" part is out of date.

## The live database is `data/jobs.db`, not `jobs.db`

The architecture diagram in `CLAUDE.md` ends at `jobs.db`. The real path is
`data/jobs.db` — 110 MB, 13,537 rows, 4,968 active, 37 distinct fetch dates from
2026-05-31 to 2026-07-29. There is also `data/jobs_demo.db` (101 MB, a demo
snapshot) and `data/backups/` holding ~12 dated rolling backups.

### Rows by source (total / active)

| Source | Rows | Active |
|---|---|---|
| `jobsdb` | 6,862 | 1,711 |
| `indeed` | 2,128 | 970 |
| `linkedin` | 1,546 | 618 |
| `efinancialcareers` | 1,163 | 839 |
| `linkedin_posts` | 579 | 197 |
| `eightfold` | 578 | 318 |
| `longtail` | 339 | 147 |
| `workday` | 323 | 158 |
| `successfactors` | 19 | 10 |

The soft-delete convention is visibly working: 63% of rows are `is_active=0`
history rather than deletions. 197 distinct `company_slug` values appear
historically (163 active) — more than the 147 currently configured, because
retired slugs keep their rows.

## Enrichment coverage is 99.4% of rows

13,459 of 13,537 rows carry a non-null `seniority`, i.e. a DeepSeek enrichment
pass has touched them. The `job_enrichments` table holds 11,120 rows (it is the
audit trail, not the join key — enrichment fields are denormalised onto `jobs`).
The ~78 unenriched rows are consistent with Phase 3 running "unenriched only" and
today's 19 new SuccessFactors rows not yet having gone through it.

## The Apify $30/month cap has never been approached

`vendor_costs` holds **133 calls totalling $4.216, all in 2026-07** — 14% of the
one-month cap. Every call so far is
`harvestapi/linkedin-profile-posts` under `run_kind='watchlist'`, at roughly
$0.002 per item. The hard cap in `hk_jobs/posts/budget.py` is real (it refuses
pre-call, per the graph's `Apify $30/mo Cap Confirmed as a Hard Pre-Call Refusal`
node) but has never actually fired in production.

## Delivery surfaces beyond the DB

`CLAUDE.md` says "No web UI" is in scope. That is no longer true; the repo now
ships the delivery layer too:

- `webapp/backend/` — FastAPI app (`main.py`) with a Railway `Procfile` +
  `railway.json`, an SMTP `mailer.py`, and `env_file.py` reading
  `config/api_keys.env`.
- `webapp/frontend/` — the Vite/React job board (job cards, filter bar, detail
  modal, source badges, Learning page, post-a-role flow).
- `pocketbase/` — the one-way verification mirror refreshed by Phase 4.

## What stayed exactly as `CLAUDE.md` describes

Worth recording, since most of the above are drifts: the **adapter abstraction
held completely**. Every one of the seven sources is a `BaseAdapter` subclass
returning canonical `Job` objects, `Job` is still the graph's most-connected node
(90 edges), and adding the 147th company genuinely was one YAML entry. The
error-isolation rule held too — `_safe_fetch` wraps every adapter's entry point,
which is why 96% fallback coverage has not produced cascading run failures.
