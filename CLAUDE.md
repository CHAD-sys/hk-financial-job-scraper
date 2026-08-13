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
Closed. Use those words. Decisions live in `docs/adr/`; do not re-litigate one
without reading it.

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
- **The watchlist poll runs one pipeline run in three**, not nightly
  (`hk_jobs/posts/cadence.py`, ADR 0012). Read that ADR before touching the
  interval: Apify bills per RESULT and the poll is watermarked, so polling less
  often returns proportionally more posts per poll and **does not reduce the
  bill**. Steady-state spend is ~$0.71/month, 14% of the $5 free credit; the
  scary-looking $4.29 July figure is 95% one-off backfill. The interval and the
  poll's catch-up floor both live in `cadence.py`, and the floor is DERIVED from
  the interval — at a fixed 48h it silently truncated the lookback to two days
  of a three-day gap.
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
