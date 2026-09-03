# CLAUDE.md — HK Financial Job Scraper

> This file is persistent context for Claude Code. It is read automatically
> at the start of every session. Keep it accurate as the project evolves.

## What we are building

**FinEx Careers** — a Hong Kong financial-sector job board, fed by a daily
multi-source scraping pipeline. It collects open postings, extracts structured
features from each one (skills, seniority, location, an estimated salary), and
stores them in SQLite; a React web app serves them to Seekers.

Two things this file used to say that are no longer true, kept here because the
old shape still shows in places:

- **It is not 30 companies.** As of 2026-08-13: **266 configured entries, 249
  enabled** — 179 in `companies.yaml`, 70 in `companies_longtail.yaml`. Read the
  count from the config, never from prose.
- **The web app is built and in scope.** `webapp/` is a React 19 + Vite SPA
  served by a FastAPI backend (ADR 0005), with Seeker accounts, Saved Roles and
  a public board. This file described a headless backend for months after that
  shipped.

**CV matching remains out of scope here** — it is being built by another team
member. Seeker accounts exist as the identity foundation for it (ADR 0001);
nothing on the board is gated (ADR 0002).

`CONTEXT.md` is the domain glossary — Seeker, Role, Listing, Tier, Saved Role,
Closed, Hidden, Board. Use those words. Decisions live in `docs/adr/`; do not
re-litigate one without reading it.

The **Board** shows every open, primary, not-Hidden Role posted within the last
calendar month — **up to 60 per employer, newest first** (ADR 0035). That cap
brought the board from ~3,250 to ~2,100 so the nightly enrichment covers all of
it: before it, ~1,600 visible Roles had no salary figure and ~1,300 no card
summary, worst on the freshest Roles. It replaces the ~26 mega-posters' oldest
Roles only; ~55 smaller employers are untouched, and a capped-out Role stays
open and addressable (Saved Roles, deep links), just off the browse board.
`job_read.BOARD_WHERE` and `hk_jobs.enrichment._fetch_unenriched` both read one
function, `board_visible_sql()` — touch the predicate and both move together.
(ADR 0032 tried a per-*sector* cap + 6-month window; ADR 0033 reverted that same
day. What survives 0032: the `admin_hidden` column, which `BOARD_WHERE` still
excludes and `job_edit.py` still sets — but **not** the Ultimate-Admin filter
that could pull hidden Roles back into view, removed 2026-09-03 at the owner's
request. Nothing in production calls `board_visible_sql(with_hidden=True)` now.
Also surviving: `JobStore.deactivate_aged_out()`, which retires anything posted
over 6 months ago every scrape.) The "X live roles"
headline stat (`LIVE_COUNT_WHERE`) is deliberately **uncapped** (~3,220) — it
counts market context, not what a visitor browses.

**Scraped board signals expire after a week** (`job_read.SCRAPED_SIGNAL_DAYS`).
Some things a board tells us are standing properties of the Role; others are
point-in-time facts — true when scraped, quietly false later, with nothing in
the data to say so. **We scrape those, we never derive them**, which is why only
some Roles carry them (37 of 62 Indeed rows report an applicant count; `new_job`
comes only from LinkedIn). That patchiness is the source being honest, not a gap
to fill. What they lacked was an expiry: the "New" badge rode `grp_new` for up to
28 days, and a Role posted three weeks ago still advertised "1 applicant" scraped
when it was new. Both now expire 7 days after `posted_at` — the only workable
clock, since `fetched_at` is overwritten every scrape and a first-seen column
could not be backfilled. `PERISHABLE_SIGNALS` names what expires; expiry is
applied where signals reach the WIRE (`_own_signals` AND the cross-post merge in
`_attach_group_signals`, which would otherwise hand a stale count straight back),
so no client can render one.

**Ordering, separately from membership (ADR 0038):** on `/api/jobs` a Role whose
card shows no salary figure ranks after the priced ones. **Under `RELEVANCE` —
what the board switches to the moment a Seeker types in the search box
(`JobBoardPage.tsx:145`) — that is across the whole result set**, so a search
fills its early pages with cards that carry a figure; BM25 orders within each
group. Under `NEWEST` it is bucketed by posting day and under `COMPANY` by
employer, so those labels stay true. Enrichment is a queue, so the freshest
Roles are the least likely to be priced, and page 1 was made of them. This is
order only: the Role stays on the board, stays addressable, and still counts in
`total` — a search matching only unpriced Roles still returns them all. It is
opt-in per caller (`list_jobs(demote_unpriced=True)`) and **only `/api/jobs`
opts in** — `role_feed` re-ranks its own window, and `salary_audit_rows` is the
Ultimate Admin screen for *finding* unpriced Roles, so the rule must never live
inside `_SORT_SQL` itself.

## Core domain knowledge (read this — it drives every design decision)

### What an ATS is
Companies don't hand-edit their careers webpages. They use an **Applicant
Tracking System (ATS)** — software that manages job postings and
applications. When you visit a company's careers page, you're really
looking at their ATS with the company logo on top. The job data lives in
the ATS's database.

### Which ATS each company uses (and why it matters)
You can identify a company's ATS from its careers-page URL:

| URL contains          | ATS              | Scrapeable via |
|-----------------------|------------------|----------------|
| `myworkdayjobs.com`   | Workday          | JSON API (easy, no browser) |
| `eightfold.ai`        | Eightfold AI     | JSON API (easy) |
| `successfactors`      | SAP SuccessFactors | HTML parse (medium) |
| `taleo.net`           | Oracle Taleo     | hostile — use fallback |
| `icims.com`           | iCIMS            | hostile — use fallback |

Large HK financial firms almost all use Workday, Eightfold, or
SuccessFactors. None use the tech-startup ATSs (Greenhouse, Lever, Ashby).

**What that turned into in practice.** The direct-ATS route reached far fewer
firms than expected — of 248 enabled companies, only **7** are on a first-party
ATS (5 Workday, 1 Eightfold, 1 SuccessFactors). The rest come from aggregators
and LLM extraction. Live enabled counts by adapter:

| adapter | companies | what it is |
|---------|-----------|------------|
| `longtail` | 68 | LLM extraction from a boutique's own careers page |
| `jobsdb` | 65 | JobsDB employer page (HTML) |
| `linkedin` | 48 | LinkedIn guest job search |
| `indeed` | 37 | Indeed employer page (embedded JSON, listing-only) |
| `efinancialcareers` | 23 | eFinancialCareers employer page |
| `workday` | 5 | first-party ATS, JSON API |
| `eightfold` | 1 | first-party ATS, JSON API |
| `successfactors` | 1 | first-party ATS, HTML parse |

Plus `linkedin_posts` — recruiter posts promoted by the Secret Market pipeline,
the one source with no adapter.

### What an API is (the key insight)
Modern careers pages load mostly empty, then their JavaScript fetches the
real job data from a separate URL that returns **JSON** (structured text).
That URL is the API. We skip the human-facing page entirely and call the
API directly — far faster and more reliable than driving a headless
browser.

- Workday listing endpoint: `POST https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs`
- Workday detail endpoint:  `GET  https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/job/{externalPath}`
- Eightfold endpoint:       `GET  https://{tenant}.eightfold.ai/api/apply/v2/jobs?domain={domain}&...`

### The fallback strategy
Some companies use hostile ATSs (Taleo, heavily-protected iCIMS) that fight
scraping. But almost every HK employer ALSO posts on JobsDB
(`hk.jobsdb.com/{Company-Slug}-jobs`). So for hostile sources, we scrape
JobsDB's HTML instead. **Legal note: this violates JobsDB's ToS. Acceptable
for a prototype; for production we need permission or a paid data feed.
Flag this clearly in code and docs; do not bury it.**

A few large firms (Goldman Sachs, JPMorgan, DBS) have near-zero *clean* JobsDB
presence, so we source them from their employer-scoped Indeed pages instead
(`hk.indeed.com/cmp/{Slug}/jobs`). The Indeed adapter reads the embedded
`mosaic-provider-jobcards` JSON (not the DOM), paginates `?start=20` with
`jobkey` dedup, and is **listing-only** (no per-job detail fetch, so these rows
have no full description). **Same legal posture as JobsDB — scraping Indeed
violates its ToS; flagged identically in the adapter.**

### AI enrichment output
A single DeepSeek call per job produces: seniority, skills, job category,
remote type, an estimated HK salary range (min/max/confidence), and a condensed
`description_summary` (≤3 sentences / ~50 words, plain prose) used on the web
app's job cards. The full description on `jobs` is never overwritten — enrichment
still reads it. When a job has no description (e.g. Indeed rows), the summary is
an empty string, never hallucinated.

**Salaries come from DeepSeek + the HK anchor table, and nothing else.** The
model returns a `(tier, role, grade)` coordinate; `salary_guidlines/hk_salary_anchors.json`
supplies the number; `hk_jobs/salary_clamp.clamp_salary` clips it through the
tier, role, title-grade, internship and global ceilings. **The coordinate is
PREFERRED, not REQUIRED (ADR 0036)** — when the model names no usable
coordinate, its own band is clamped through the same stack and stored. It is
never Opus, and `/fix-s` is not part of the pipeline.

**HARD RULE — never changes (ADR 0036): WE NEVER DESTROY AN EXISTING SALARY
ESTIMATE.** A run may replace a figure with another figure, or fill a blank. It
may never turn a figure into a blank — the write path in
`hk_jobs/enrichment.py` keeps the stored `min`/`max`/`confidence`/coordinate as
one block whenever the new estimate is NULL. This exists because a re-pricing
run on 2026-09-02 blanked the salary on **336 Roles that already had a good
one**. A Role carrying no figure is a re-enrichment candidate whatever its
`prompt_version`, so a pricing fix reaches exactly the rows it was written for.

**HARD RULE — never changes (ADR 0034): we do not estimate the salary of a Role
that is not on the board.** `hk_jobs.enrichment._fetch_unenriched` filters on
`hk_jobs.board_visibility.board_visible_sql()` — the exact predicate
`webapp/backend/job_read.BOARD_WHERE` uses (open, primary, not `admin_hidden`,
posted within one month, and among the freshest 60 for the employer — ADR
0035). No `--enrich` / `--re-enrich` / `--enrich-boutique` carve-out. This exists because a bulk run once spent 66% of its budget on
duplicate cross-post copies, month-old postings, and undated rows a Seeker could
never see. If you touch the board predicate, both sides move together because
they share that one function — do not re-introduce a second copy.

## Architecture (the shape of the solution)

```
                    cli.py  ──  PipelineArgs + MODES + migrate()
                      │
companies.yaml  →  pipeline.py  →  [adapter per company]  →  enrich.py  →  storage.py  →  jobs.db
   (config)        (the scrape)     (8 adapters, one per       (DeepSeek)    (SQLite)       │
                                      source type)                                          │
                                                                                            ▼
                                         webapp/backend (FastAPI)  ←  job_read.py  ←────────┘
                                                   │
                                         webapp/frontend (React 19 + Vite)
```

The central abstraction is the **adapter**. Every source type has one adapter,
each implementing `fetch_jobs() -> list[Job]` and mapping its source's native
data into one canonical `Job` schema. The rest of the system only ever sees
`Job` objects and never knows which ATS they came from. Adding a company = one
entry in `companies.yaml` (a new adapter only if it uses a new source type).

**Four registries you must keep in step.** Each was added because something
drifted, and each now fails a test rather than failing quietly:

- `hk_jobs/sources.py` — **every fact about a source**: apply order, display
  order, own-site-or-board, which adapter writes it. Adding a source means one
  entry here; `tests/test_sources.py` binds the adapter registry,
  `companies.yaml` validation and the frontend's "Listed on" tags to it. This
  exists because SuccessFactors was registered in two of five places and ranked
  below a recruiter's post for two days.
- `hk_jobs/migrations.py` — `MIGRATIONS` is the one ordered list; `migrate(db)`
  applies whatever a database has not recorded in `schema_migrations`. Add a
  phase by appending to that tuple. **Never edit an applied migration** — the
  ledger will not run it again.
- `hk_jobs/cli.py` — `PipelineArgs` (one typed field per setting) and `MODES`
  (the 16 non-scrape modes, in precedence order).
- `hk_jobs/adapters/__init__.py` — `ADAPTERS`, adapter name → class.

## Tech stack (decided — do not substitute without asking)

- Python 3.11+
- `httpx` for HTTP (NOT requests; we want timeouts + HTTP/2)
- `selectolax` for HTML parsing (fast, lightweight; NOT BeautifulSoup unless blocked)
- `PyYAML` for config
- `pydantic` v2 for the schema (validation + serialization)
- Standard-library `sqlite3` for storage (Postgres-compatible SQL so we can migrate later)
- `pytest` for tests
- `ruff` for linting/formatting

The web app, added later and under the same rule (do not substitute without
asking):

- FastAPI + uvicorn, serving both the API and the built React bundle from one
  origin (ADR 0005)
- React 19 + Vite 8 + TypeScript + Tailwind 4
- Vitest + Testing Library + jsdom for frontend tests
- Argon2id for Seeker passwords (ADR 0004); Seeker data in its own
  `data/seekers.db` (ADR 0006)
- `npm run build` is the real check, not `tsc --noEmit` — the build runs
  `tsc -b`, which has caught a broken page the looser check passed
- NO paid services, NO aggregator APIs, NO headless browser unless a source
  genuinely cannot be reached any other way (and ask first if so).

### Exception: LinkedIn recruiter posts ("Secret Market")

The "NO paid services" rule above is consciously overturned for ONE source
only, by explicit owner decision (2026-07-19, see `docs/PLAN_LINKEDIN_POSTS.md`):
LinkedIn posts by recruiters/headhunters are fetched via a paid third-party
API, **Apify/HarvestAPI** (`hk_jobs/posts/vendor_client.py`), because DIY
scraping of LinkedIn posts was evaluated and rejected (authwall, legal
escalation risk, anti-bot arms race — see the plan's §3 for the full posture).

- **Hard cap: $30/month**, self-enforced by `hk_jobs/posts/budget.py` against
  a running `vendor_costs` ledger — new Apify calls are refused once the
  month-to-date spend hits the cap, not just logged as a warning.
- **The watchlist poll runs every pipeline run** — daily, not one run in three
  (`hk_jobs/posts/cadence.py`, ADR 0031, supersedes ADR 0012's three). Read
  ADR 0012 before touching the interval again: Apify bills per RESULT and the
  poll is watermarked, so polling less often returns proportionally more posts
  per poll and **does not reduce the bill**. Steady-state spend is
  ~$0.71/month, 14% of the $5 free credit, unchanged by cadence; the
  scary-looking $4.29 July figure is 95% one-off backfill. Daily was chosen to
  cut latency (a post is now at most one pipeline run stale, not three) at the
  cost of the actor-run reduction the slower cadence bought (ADR 0031). The
  interval and the poll's catch-up floor both live in `cadence.py`, and the
  floor is DERIVED from the interval — a fixed 48h floor is only safe for a
  daily poll; it silently truncates the lookback for any slower cadence.
- This exception applies ONLY to `hk_jobs/posts/`. Every other source in this
  repo stays on the no-paid-services line.
- Same "no login, no credentials, no authwall" posture as the JobsDB/Indeed/
  LinkedIn-guest adapters otherwise — the vendor performs the LinkedIn access,
  our code never does.

## Project conventions

- One responsibility per file. Fetching, enriching, and storing are separate.
- Adapters live in `hk_jobs/adapters/`, one file per source type.
- All per-company settings live in `companies.yaml`, never hardcoded.
- Every adapter must fail gracefully: log the error, return `[]`, never crash
  the whole run. One broken company must not stop the other 247.
- Be polite to sources: rate-limit (≤3 req/s), real browser User-Agent,
  delays between detail calls.
- Soft-delete only: when a job disappears, set `is_active = False`. Never
  hard-delete (members may revisit past applications).
- Keep both `description_raw` (original HTML) and `description_clean`
  (stripped text). Raw enables re-extraction later; clean is for embedding.
- Write a test alongside every module. Network-dependent tests use recorded
  fixtures, not live calls.
- A test must be shown to go RED on the bug it claims to catch. Two tests in
  this repo passed for months while asserting the opposite of what the code
  correctly did.
- Prefer one typed object over `getattr(obj, name, default)`. A silent default
  is how the test suite's idea of the arguments drifted from production's.

## Repository mirroring (keep both remotes identical)

This project lives in two GitHub repos that MUST stay byte-identical on every
shared branch and tag:

| Remote | Repo | Role |
|--------|------|------|
| `origin` | `FinEx-Club/hk-job-scraper` (private) | **canonical** — all work merges here |
| `personal` | `CHAD-sys/hk-financial-job-scraper` (public) | one-way mirror of `origin` |

Sync is **one-way, `origin` → `personal`**, enforced two ways:

1. **Local fan-out push.** `origin` has two push URLs, so `git push origin <ref>`
   pushes to BOTH repos at once. Re-add on a fresh clone with:
   ```
   git remote set-url --add --push origin https://github.com/FinEx-Club/hk-job-scraper.git
   git remote set-url --add --push origin https://github.com/CHAD-sys/hk-financial-job-scraper.git
   ```
   If the `personal` half is rejected (non-fast-forward), run the mirror workflow
   or `git push --force personal <ref>` — `personal` is a mirror, `origin` wins.
2. **`.github/workflows/mirror-from-finex-club.yml`** — runs on `CHAD-sys` every
   10 min + on demand, force-syncs every `origin` branch/tag. Catches merges made
   with GitHub's web Merge button. Needs the `MIRROR_TOKEN` secret on `CHAD-sys`.

Rules:
- After any merge to `master` (or any shared branch), it must land on both repos —
  the fan-out push does this; verify with `git ls-remote personal master`.
- Never commit work only to `personal`. It is overwritten on the next mirror run.
- `backup/*` branches are allowed to exist on `personal` only and are exempt from
  the "must match" rule (the mirror never prunes them).
- Never `git push --mirror` / `--prune` to `personal` — it would delete `backup/*`.

## Where the daily pipeline runs (CHAD-sys, not FinEx-Club)

Since 2026-09-01 the scheduled pipeline runs from the **`CHAD-sys`** repo's
GitHub Actions, not `FinEx-Club`'s — `CHAD-sys` is public, so Actions minutes
are free/unlimited, and the private `FinEx-Club` repo was burning its capped
minutes on a 30-60 min nightly scrape.

- `Daily HK Jobs Scrape` and `Refresh Learning content` are **disabled** on
  `FinEx-Club` (`gh workflow disable`, a repo-level state the mirror does not
  touch) and **enabled** on `CHAD-sys`. To fail back, flip the two with
  `gh workflow enable/disable`.
- Both workflows POST to `finex-careers.up.railway.app/api/admin/pipeline/*`
  (the `finex-jobs-demo` Railway project's `backend` service — same box that
  serves `finexcareers.com`). Railway is **not** GitHub-connected; Actions only
  pushes data to the running backend over HTTP with `PIPELINE_SYNC_TOKEN`.
- `CHAD-sys` needs these Actions secrets: `PIPELINE_SYNC_TOKEN` (must equal the
  backend's Railway var), `DEEPSEEK_API_KEY`, `SMTP_USER`, `SMTP_PASS`. The
  daily summary email recipients are hardcoded in `daily.yml`
  (`NOTIFY_EMAILS`), currently `amine@finexclub.org,mohamedaminechahid@gmail.com`.
- There is no auto-deploy Railway project watching `CHAD-sys` — the old
  `energetic-motivation` project (7 straight failed builds, no data) was
  deleted 2026-09-01. Web-app deploys are still CLI-only via `/rail-it`.

## Working agreement with the human

- This is being built by someone newer to APIs/ATS concepts. Explain
  decisions in commit messages and docstrings in plain language.
- Work ONE thing at a time. After each: run the tests, summarise what was
  built, and STOP for review. (There is no BUILD_PLAN.md — this file pointed
  at one that does not exist. Current plans live in `docs/PLAN_*.md`.)
- The ATS configs in `companies.yaml` are GUESSES that need human
  verification against real careers pages. Do not assume they are correct.
  When live calls fail, surface it clearly rather than silently skipping.
- If a live network call is needed to verify something and the sandbox
  blocks it, say so and provide a script the human can run locally instead.
