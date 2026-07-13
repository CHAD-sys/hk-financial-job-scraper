# HK Financial Job Board Scraper

**Automated job intelligence for Hong Kong's financial sector**

![Python](https://img.shields.io/badge/Python-3.11-blue) ![SQLite](https://img.shields.io/badge/Database-SQLite-green) ![DeepSeek](https://img.shields.io/badge/AI-DeepSeek-purple) ![Jobs](https://img.shields.io/badge/Jobs-2%2C000%2B-orange) ![Sources](https://img.shields.io/badge/Sources-4-blue) ![Enriched](https://img.shields.io/badge/AI%20Enriched-100%25-brightgreen) ![Private](https://img.shields.io/badge/Visibility-Private-lightgrey)

---

## Overview

A fully automated pipeline that scrapes job listings from Hong Kong's largest financial institutions across **four sources** (JobsDB, Workday, Eightfold, and Indeed), fetches full job descriptions where available, and enriches every listing with AI-extracted structured data — seniority, skills, job category, remote type, an estimated HK salary range, and a short plain-language **description summary** for the job cards. Runs daily and tracks hiring trends over time.

> **72 companies → 2,200+ active jobs → 100% AI-enriched → AI salary estimates + card summaries**

---

## How It Works

| Step | Description | Time |
|------|-------------|------|
| **Scrape** | Collects listings from the enabled companies (up to N pages each) | ~9 min |
| **Describe** | Fetches full descriptions via GraphQL & REST APIs (direct-ATS + JobsDB) | ~2 min |
| **Enrich** | DeepSeek AI: seniority, skills, category, salary estimate + card summary | ~4 min |
| **Track** | Records daily snapshots for trend analysis | ~1 min |
| **Total** | Full daily pipeline | **~15 min** |

---

## Companies Covered

**72 enabled companies** across banking, insurance, and asset management. Representative names:

**Banking** — HSBC HK, Standard Chartered, DBS, Bank of China HK, Bank of East Asia, Citibank HK, ICBC Asia, CCB Asia, OCBC Wing Hang

**Insurance** — AIA HK, Prudential HK, FWD Insurance, Sun Life HK, AXA HK, Manulife HK, Zurich HK, Generali HK, China Taiping

**Asset Management** — BlackRock HK, UBS Asset Management, Fidelity International, Man Group, BNP Paribas AM, PIMCO HK, JPMorgan AM, Schroders HK, Value Partners

**Bulge-bracket via Indeed employer pages** — Goldman Sachs, JPMorgan, DBS *(these firms have near-zero clean JobsDB presence, so they are sourced from their employer-scoped `hk.indeed.com/cmp/…` pages instead).*

---

## Architecture

```
4 Data Sources
─────────────────────────────────────────────────────────────────────
JobsDB (64 companies) │ Workday (4) │ Eightfold (1 — HSBC) │ Indeed (3)
        │                    │              │                    │
        ▼                    ▼              ▼                    ▼

Stage 1 — Listings
Scrapling headless browser (Cloudflare bypass) + direct REST APIs
10 parallel company workers · paginate · stop-when-empty
        │
        ▼

Stage 2 — Descriptions
JobsDB GraphQL API + Workday REST + Eightfold REST
(Indeed is employer-scoped listing-only — no full descriptions fetched)
        │
        ▼

Stage 3 — AI Enrichment (DeepSeek deepseek-chat) — one call per job
Seniority · Skills · Job category · Remote type
Estimated HK salary range (min/max/confidence)
Condensed description_summary (≤3 sentences / ~50 words) for job cards
100% coverage · 20 concurrent workers
        │
        ▼

SQLite Database (data/jobs.db)
4 tables · ~2,262 active jobs · daily trend snapshots
        │
        ▼

Web App (webapp/) — FastAPI backend + React/Vite frontend
Job board UI · filters · detail modal showing the AI card summary
```

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.11 |
| Browser scraping | Scrapling (Playwright + Cloudflare bypass) |
| HTTP client | httpx (async-capable, HTTP/2) |
| HTML parsing | selectolax |
| Data validation | Pydantic v2 |
| Database | SQLite (WAL mode, Postgres-compatible SQL) |
| AI enrichment | DeepSeek API (`deepseek-chat`) |
| Parallelism | `ThreadPoolExecutor` (10 company workers, 20 API workers) |
| Web app | FastAPI (backend) · React + TypeScript + Vite + Tailwind (frontend) |
| Scheduling | Cron / systemd |

---

## Database Schema

| Table | Rows | Purpose |
|-------|------|---------|
| `jobs` | ~2,262 active | Listings — title, company, URL, locations, posted_at, full description |
| `job_enrichments` | ~2,262 | AI fields — seniority, skills, category, remote_type, salary (disclosed + estimated), `description_summary` |
| `job_history` | growing | Daily snapshots per company for trend tracking |
| `company_metrics` | 72 | 7-day and 30-day rolling averages + growth rates |

The full job description is kept on `jobs` (`description_raw` / `description_clean`) and never overwritten — the AI enrichment still reads it. `job_enrichments.description_summary` holds a separate condensed summary for display only.

---

## PocketBase storage backend (optional)

The pipeline can write to **PocketBase** instead of the raw SQLite file — same
data, exposed over a REST API. Intended split:

- **PocketBase** (on Railway) serves the public job board over HTTP.
- **The scraper** runs offline on a **VPS** (scheduled), and **pushes** data into
  the deployed PocketBase via its API — no public DB access needed.

PocketBase keeps *all* its state in one `pb_data/` folder (a SQLite `data.db` +
settings), so deployment is a single-file handoff.

### Local setup
```bash
# 1. Install PocketBase (pick the build for YOUR platform — see releases page)
#    macOS arm64 example:
mkdir -p pocketbase && cd pocketbase
curl -sL https://github.com/pocketbase/pocketbase/releases/download/v0.39.6/pocketbase_0.39.6_darwin_arm64.zip -o pb.zip
unzip -o pb.zip && chmod +x pocketbase && cd ..

# 2. Create an admin (superuser) and start it
./pocketbase/pocketbase superuser upsert admin@finex.local <password> --dir ./pocketbase/pb_data
./pocketbase/pocketbase serve --http 127.0.0.1:8090 --dir ./pocketbase/pb_data   # admin UI at /_/

# 3. Create the `jobs` collection (idempotent; matches the Job schema)
export POCKETBASE_URL=http://127.0.0.1:8090
export POCKETBASE_ADMIN_EMAIL=admin@finex.local
export POCKETBASE_ADMIN_PASSWORD=<password>
python scripts/setup_pocketbase.py
```

### Run the pipeline against PocketBase
```bash
# --storage=sqlite is the default; --storage=pocketbase writes via the REST API
python -m hk_jobs.pipeline --storage pocketbase --only aia-hk --only hung-sing
```
`hk_jobs/storage_pocketbase.py` mirrors the SQLite `JobStore` interface
(`upsert_many`, `mark_inactive_for_run`, `stats`, …) and upserts on `dedup_hash`.

### Deployment handoff (for your manager)
1. **Export** the local data as one portable file:
   ```bash
   scripts/export_pocketbase.sh          # -> pb_data_export_YYYYMMDD.tar.gz
   ```
   *(stop `pocketbase serve` first for a clean snapshot.)*
2. **Deploy PocketBase on Railway** (or any host):
   - New Railway project → deploy the official `pocketbase/pocketbase` image (or a
     tiny Dockerfile running `pocketbase serve --http 0.0.0.0:$PORT`).
   - Add a **Volume** mounted at the app's `pb_data` path so data persists.
   - **Restore the snapshot:** upload/extract `pb_data_export_*.tar.gz` into that
     volume with `scripts/import_pocketbase.sh <tarball> <pb_data_path>` (or unpack
     it there directly). The admin account + `jobs` collection travel inside it.
   - Railway gives you a public URL, e.g. `https://finex-pb.up.railway.app`.
3. **Point the VPS scraper at it** — on the VPS, set env and run the scraper on a
   schedule (cron):
   ```bash
   export POCKETBASE_URL=https://finex-pb.up.railway.app
   export POCKETBASE_ADMIN_EMAIL=admin@finex.local
   export POCKETBASE_ADMIN_PASSWORD=<prod-password>   # change from the local dev one!
   python -m hk_jobs.pipeline --storage pocketbase        # + --fetch-descriptions / --enrich
   ```
   The scraper authenticates as the superuser and pushes jobs into the deployed
   collection. Public users read the board from the same PocketBase over HTTP.

> ⚠️ Use a strong production admin password (not the local dev default), and keep
> it only in the VPS/Railway env — never commit it. `pocketbase/` and
> `pb_data_export_*.tar.gz` are gitignored.

---

## Setup

**Requirements:** Python 3.11+, DeepSeek API key

```bash
git clone <repo-url>
cd hk-job-scraper
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# Install Scrapling browser engine (first time only)
scrapling install
```

**Configuration:**
```bash
export DEEPSEEK_API_KEY=your-key-here
```

---

## Usage

```bash
# Full scrape — collect all listings from the enabled companies
python -m hk_jobs.pipeline

# Fetch full descriptions (GraphQL + REST, ~2 min)
python -m hk_jobs.pipeline --fetch-descriptions

# AI enrichment — seniority, skills, category, salary estimate + card summary
# (requires DEEPSEEK_API_KEY; produced in a single call per job)
python -m hk_jobs.pipeline --enrich

# Re-run enrichment across every active job (e.g. after a prompt change)
python -m hk_jobs.pipeline --enrich --re-enrich

# View hiring trends report
python -m hk_jobs.pipeline --report trends

# View hiring velocity ranking
python -m hk_jobs.pipeline --report velocity

# Export trend data to JSONL
python -m hk_jobs.pipeline --export-trends data/trends.jsonl

# Dry run — scrape without writing to database
python -m hk_jobs.pipeline --dry-run -v

# Custom parallelism (default: 10, max safe: 15)
python -m hk_jobs.pipeline --parallel-workers 15

# Single company test
python -m hk_jobs.pipeline --only hsbc-hk --dry-run -v

# Probe Indeed scrapeability for the employer pages (throwaway diagnostic)
python scripts/probe_indeed.py
```

### Web app

```bash
# Backend (FastAPI) — serves /api/jobs, /api/jobs/{source}/{source_id}, /api/filters, /api/stats
cd webapp/backend && uvicorn main:app --reload

# Frontend (React + Vite)
cd webapp/frontend && npm install && npm run dev
```

---

## Daily Automation

Cron job (runs at 2 AM HKT = 18:00 UTC):

```bash
0 18 * * * cd /opt/hk-job-scraper && source .venv/bin/activate && source config/api_keys.env && python -m hk_jobs.pipeline && python -m hk_jobs.pipeline --fetch-descriptions && python -m hk_jobs.pipeline --enrich >> logs/daily_runs.log 2>&1
```

Or use the included script:
```bash
bash scripts/daily_run.sh
```

---

## Results

| Metric | Value |
|--------|-------|
| Active jobs | **~2,262** |
| Companies tracked | **72 enabled** |
| Data sources | **4** (JobsDB · Workday · Eightfold · Indeed) |
| Active jobs by source | JobsDB 1,643 · Eightfold 253 · Indeed 206 · Workday 160 |
| Enrichment coverage | **100%** |
| Jobs with a card summary | **2,056** (all description-bearing jobs; Indeed is listing-only) |
| Daily run time | **~15 minutes** |
| Monthly AI cost | **~$0.55 USD** |

---

## Project Structure

```
hk-job-scraper/
├── hk_jobs/
│   ├── adapters/
│   │   ├── jobsdb.py            # Scrapling + GraphQL pagination
│   │   ├── workday.py           # Workday REST API adapter
│   │   ├── eightfold.py         # Eightfold REST API adapter
│   │   └── indeed.py            # Indeed employer pages (mosaic JSON, ?start=20)
│   ├── enrichers/
│   │   └── deepseek.py          # DeepSeek AI (seniority/skills/salary + summary)
│   ├── companies.yaml           # Config for all companies + ATS assignments
│   ├── pipeline.py              # Main orchestration + CLI (argparse)
│   ├── description_fetcher.py   # Description pipeline (GraphQL + REST)
│   ├── enrichment.py            # AI enrichment pipeline (20 concurrent workers)
│   ├── analytics.py             # Trend reporting and JSONL export
│   ├── migrations.py            # SQLite schema migrations
│   └── schema.py                # Pydantic Job model
├── webapp/
│   ├── backend/                 # FastAPI — job board API
│   └── frontend/                # React + TypeScript + Vite job board UI
├── scripts/
│   ├── daily_run.sh             # Production cron wrapper
│   ├── probe_indeed.py          # Indeed scrapeability probe (diagnostic)
│   └── generate_intelligence_report.py  # PDF report generator
├── tests/
├── data/                        # gitignored — SQLite DB files
├── config/                      # gitignored — API keys
├── requirements.txt
└── README.md
```

---

## Team

| Role | Name |
|------|------|
| Project Lead | Benjamin |
| AI & Development | Amine & Kenson |

---

> **Private repository — Finex Club members only**
