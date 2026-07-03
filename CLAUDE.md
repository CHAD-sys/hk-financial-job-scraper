# CLAUDE.md — HK Financial Job Scraper

> This file is persistent context for Claude Code. It is read automatically
> at the start of every session. Keep it accurate as the project evolves.

## What we are building

A daily job scraper for the 30 largest Hong Kong financial institutions
(banks, insurers, asset managers). It collects their open job postings,
extracts structured features from each posting (skills, seniority, location,
etc.), and stores them in a database. A later project (NOT in scope here)
will match member CVs against this database.

The deliverable for THIS project is the scraping + enrichment + storage
backend only. No web UI, no CV matching yet.

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
companies.yaml  →  pipeline.py  →  [adapter per company]  →  enrich.py  →  storage.py  →  jobs.db
   (config)        (orchestrator)   (Workday/Eightfold/        (extract     (SQLite)
                                      JobsDB/Indeed)             features)
```

The central abstraction is the **adapter**. Every source type has one
adapter. Every adapter implements the same method — `fetch_jobs() -> list[Job]`
— and maps its source's native data into one canonical `Job` schema. The
rest of the system only ever sees `Job` objects and never knows or cares
which ATS they came from. Adding a 31st company = one new entry in
`companies.yaml` (and a new adapter only if it uses a new ATS).

## Tech stack (decided — do not substitute without asking)

- Python 3.11+
- `httpx` for HTTP (NOT requests; we want timeouts + HTTP/2)
- `selectolax` for HTML parsing (fast, lightweight; NOT BeautifulSoup unless blocked)
- `PyYAML` for config
- `pydantic` v2 for the schema (validation + serialization)
- Standard-library `sqlite3` for storage (Postgres-compatible SQL so we can migrate later)
- `pytest` for tests
- `ruff` for linting/formatting
- NO paid services, NO aggregator APIs, NO headless browser unless a source
  genuinely cannot be reached any other way (and ask first if so).

## Project conventions

- One responsibility per file. Fetching, enriching, and storing are separate.
- Adapters live in `hk_jobs/adapters/`, one file per source type.
- All per-company settings live in `companies.yaml`, never hardcoded.
- Every adapter must fail gracefully: log the error, return `[]`, never crash
  the whole run. One broken company must not stop the other 29.
- Be polite to sources: rate-limit (≤3 req/s), real browser User-Agent,
  delays between detail calls.
- Soft-delete only: when a job disappears, set `is_active = False`. Never
  hard-delete (members may revisit past applications).
- Keep both `description_raw` (original HTML) and `description_clean`
  (stripped text). Raw enables re-extraction later; clean is for embedding.
- Write a test alongside every module. Network-dependent tests use recorded
  fixtures, not live calls.

## Working agreement with the human

- This is being built by someone newer to APIs/ATS concepts. Explain
  decisions in commit messages and docstrings in plain language.
- Work ONE phase at a time (see BUILD_PLAN.md). After each phase: run the
  tests, summarize what was built, and STOP for review before the next phase.
- The ATS configs in `companies.yaml` are GUESSES that need human
  verification against real careers pages. Do not assume they are correct.
  When live calls fail, surface it clearly rather than silently skipping.
- If a live network call is needed to verify something and the sandbox
  blocks it, say so and provide a script the human can run locally instead.
