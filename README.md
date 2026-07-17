<div align="center">

# HK Financial Job Board Scraper

**Automated job intelligence for Hong Kong's financial sector**

![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python&logoColor=white) ![FastAPI](https://img.shields.io/badge/API-FastAPI-009688?logo=fastapi&logoColor=white) ![React](https://img.shields.io/badge/UI-React%20%2B%20Vite-61DAFB?logo=react&logoColor=black) ![SQLite](https://img.shields.io/badge/Database-SQLite-003B57?logo=sqlite&logoColor=white) ![DeepSeek](https://img.shields.io/badge/AI-DeepSeek-8A2BE2) ![Sources](https://img.shields.io/badge/Sources-7-orange) ![Enriched](https://img.shields.io/badge/AI%20Enriched-100%25-brightgreen) ![Private](https://img.shields.io/badge/Visibility-Private-lightgrey)

*Scrapes HK's largest banks, insurers and asset managers · fetches full descriptions · enriches every listing with AI · serves it through a clean job-board UI.*

</div>

---

## Contents

- [Overview](#overview) · [Screenshots](#screenshots) · [How It Works](#how-it-works) · [Data Sources](#data-sources) · [Companies Covered](#companies-covered)
- [Architecture](#architecture) · [Tech Stack](#tech-stack) · [Database Schema](#database-schema)
- [Setup](#setup) · [Usage](#usage) · [Web App](#web-app) · [Daily Automation](#daily-automation)
- [Results](#results) · [Project Structure](#project-structure) · [Team](#team)

---

## Overview

A fully automated pipeline that scrapes job listings from Hong Kong's largest financial institutions across **seven sources**, fetches full job descriptions where available, and enriches every listing with AI-extracted structured data — seniority, skills, job category, remote type, an estimated HK salary range, and a short plain-language **description summary** for the job cards. It runs daily and tracks hiring trends over time.

Each company is resolved to its real Applicant Tracking System (ATS) and scraped through a **priority fallback chain** — a direct ATS JSON API when one exists, dropping to specialist boards (eFinancialCareers), then general boards (JobsDB, Indeed, LinkedIn), then an LLM-based long-tail extractor for boutique firms with no structured feed.

> **Banking · Insurance · Asset Management → thousands of active jobs → 100% AI-enriched → salary estimates + card summaries**

---

## Screenshots

<div align="center">

|  |  |
|:--:|:--:|
| **Main board** | **Active filters** |
| ![Main board](screenshots/main-board.png) | ![Filters active](screenshots/filters-active.png) |
| **Job detail (AI summary)** | **Salary-sorted view** |
| ![Job detail](screenshots/job-detail.png) | ![Salary sort](screenshots/salary-sort.png) |

_About page_

![About](screenshots/about.png)

</div>

---

## How It Works

| Step | Description | Time |
|------|-------------|------|
| **Scrape** | Collects listings from every enabled company via its ATS/board fallback chain | ~9 min |
| **Describe** | Fetches full descriptions via JSON/GraphQL/REST APIs (direct-ATS + JobsDB) | ~2 min |
| **Enrich** | DeepSeek AI: seniority, skills, category, salary estimate + card summary | ~4 min |
| **Track** | Records daily snapshots for trend analysis | ~1 min |
| **Total** | Full daily pipeline | **~15 min** |

---

## Data Sources

Seven adapters, tried per company in priority order. Every adapter implements the same contract — `fetch_jobs() -> list[Job]` — and maps its source's native payload into one canonical `Job`. The rest of the system never knows which source a job came from.

| Adapter | Source | Access | Notes |
|---------|--------|--------|-------|
| `workday` | Company Workday ATS | JSON API | Most common ATS for large HK financial firms |
| `eightfold` | Company Eightfold ATS | JSON API | e.g. HSBC |
| `efinancialcareers` | eFinancialCareers (DHI) | JSON API | Finance-specialist board; **full description inline** + market signals (sponsored, expiry, parent company). Priority apply-link source |
| `jobsdb` | JobsDB (SEEK) | HTML via Scrapling | General board; Cloudflare-walled → headless bypass |
| `indeed` | Indeed employer pages | Embedded mosaic JSON | Listing-only (no full descriptions) |
| `linkedin` | LinkedIn guest jobs | JSON (no login) | Fallback only |
| `longtail` | Boutique careers pages | **LLM extraction** | For medium/small firms with no structured ATS feed |

> ⚠️ **Legal note.** The `jobsdb`, `indeed`, `linkedin` and `efinancialcareers` adapters call sources whose ToS restrict programmatic access. They are flagged prominently in-code and are for **prototype/verification only** — production requires written permission or a licensed data feed. This posture is documented, never buried.

---

## Companies Covered

Companies span **banking, insurance, and asset management**, each configured in `companies.yaml` (core ATS sources) or `companies_longtail.yaml` (LLM long-tail). Representative names:

**Banking** — HSBC HK, Standard Chartered, DBS, Bank of China HK, Bank of East Asia, Citibank HK, ICBC Asia, CCB Asia, OCBC Wing Hang

**Insurance** — AIA HK, Prudential HK, FWD Insurance, Sun Life HK, AXA HK, Manulife HK, Zurich HK, Generali HK, China Taiping

**Asset Management** — BlackRock HK, UBS Asset Management, Fidelity International, Man Group, BNP Paribas AM, PIMCO HK, JPMorgan AM, Schroders HK, Value Partners

**Bulge-bracket via Indeed employer pages** — Goldman Sachs, JPMorgan, DBS *(near-zero clean JobsDB presence, so sourced from their employer-scoped `hk.indeed.com/cmp/…` pages instead).*

---

## Architecture

```
companies.yaml  →  pipeline.py  →  [adapter fallback chain]  →  enrich.py  →  storage.py  →  jobs.db
   (config)       (orchestrator)      (per company)            (AI extract)   (SQLite)
```

```
7 Data Sources (per-company priority fallback)
──────────────────────────────────────────────────────────────────────────────
 Workday · Eightfold · eFinancialCareers · JobsDB · Indeed · LinkedIn · Longtail(LLM)
        │
        ▼
Stage 1 — Listings
Direct ATS JSON APIs where available · Scrapling headless (Cloudflare bypass) for
HTML boards · LLM extraction for boutique careers pages
10 parallel company workers · paginate · stop-when-empty · graceful per-company failure
        │
        ▼
Stage 2 — Descriptions
JobsDB GraphQL + Workday/Eightfold REST (eFC ships descriptions inline; Indeed is
listing-only — no full descriptions fetched)
        │
        ▼
Stage 3 — AI Enrichment (DeepSeek deepseek-chat) — one call per job
Seniority · Skills · Job category · Remote type
Estimated HK salary range (min/max/confidence), calibrated against Hays anchors
Condensed description_summary (≤3 sentences / ~50 words) for job cards
100% coverage · 20 concurrent workers
        │
        ▼
SQLite Database (data/jobs.db)
Listings · enrichments · daily trend snapshots · cross-post reconciliation
        │
        ▼
Web App (webapp/) — FastAPI backend + React/Vite frontend
Job board UI · filters · detail modal with the AI card summary · saved jobs
```

Cross-posting: when the same vacancy appears on multiple sources, `storage.reconcile_cross_posted()` points the apply link at the richest copy (eFC preferred) — see `_SOURCE_PRIORITY`.

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.11 |
| Browser scraping | Scrapling (Playwright + Cloudflare bypass) |
| HTTP client | httpx (HTTP/2, timeouts) |
| HTML parsing | selectolax |
| LLM extraction | DeepSeek (`deepseek-chat`) via a shared `LLMClient` |
| Data validation | Pydantic v2 |
| Database | SQLite (WAL mode, Postgres-compatible SQL) |
| AI enrichment | DeepSeek API (`deepseek-chat`) |
| Parallelism | `ThreadPoolExecutor` (10 company workers, 20 API workers) |
| Web app | FastAPI (backend) · React + TypeScript + Vite + Tailwind (frontend) |
| Verification mirror | PocketBase (boss-facing read-only mirror of `jobs.db`) |
| Scheduling | Cron / systemd |

---

## Database Schema

| Table | Purpose |
|-------|---------|
| `jobs` | Listings — title, company, URL, locations, posted_at, full description (`description_raw` / `description_clean`), source + cross-post links |
| `job_enrichments` | AI fields — seniority, skills, category, remote_type, salary (disclosed + estimated), `description_summary` |
| `job_history` | Daily snapshots per company for trend tracking |
| `company_metrics` | 7-day and 30-day rolling averages + growth rates |

The full job description on `jobs` is never overwritten — the AI enrichment still reads it. `job_enrichments.description_summary` holds a separate condensed summary for display only. When a job has no description (e.g. Indeed rows), the summary is an empty string, never hallucinated.

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

**Configuration** — create `config/api_keys.env` (gitignored):

```bash
export DEEPSEEK_API_KEY=your-key-here
```

---

## Usage

```bash
# Full scrape — collect all listings from the enabled companies
python -m hk_jobs.pipeline

# Fetch full descriptions (JSON/GraphQL/REST, ~2 min)
python -m hk_jobs.pipeline --fetch-descriptions

# AI enrichment — seniority, skills, category, salary estimate + card summary
python -m hk_jobs.pipeline --enrich

# Re-run enrichment across every active job (e.g. after a prompt change)
python -m hk_jobs.pipeline --enrich --re-enrich

# Trend + velocity reports
python -m hk_jobs.pipeline --report trends
python -m hk_jobs.pipeline --report velocity

# Export trend data to JSONL
python -m hk_jobs.pipeline --export-trends data/trends.jsonl

# Dry run — scrape without writing to database
python -m hk_jobs.pipeline --dry-run -v

# Single company test
python -m hk_jobs.pipeline --only hsbc-hk --dry-run -v

# Live-verify a single source adapter (diagnostics)
python scripts/try_workday_live.py
python scripts/try_efc_live.py
python scripts/try_eightfold_live.py
python scripts/try_jobsdb_live.py
```

### Web App

```bash
# Backend (FastAPI) — serves /api/jobs, /api/jobs/{source}/{source_id}, /api/filters, /api/stats
cd webapp/backend && uvicorn main:app --reload

# Frontend (React + Vite)
cd webapp/frontend && npm install && npm run dev
```

---

## Daily Automation

The full pipeline (scrape → describe → enrich → PocketBase sync → backup → email) runs from one script:

```bash
bash scripts/daily_run.sh
```

Cron (2 AM HKT = 18:00 UTC):

```bash
0 18 * * * /opt/hk-job-scraper/scripts/daily_run.sh
```

---

## Results

_Figures refresh on every daily run; the snapshot below is representative._

| Metric | Value |
|--------|-------|
| Active jobs | **~2,000+** |
| Data sources | **7** (Workday · Eightfold · eFinancialCareers · JobsDB · Indeed · LinkedIn · Longtail) |
| Enrichment coverage | **100%** |
| Card summaries | all description-bearing jobs (Indeed is listing-only) |
| Daily run time | **~15 minutes** |
| Monthly AI cost | **~$0.55 USD** |

---

## Project Structure

```
hk-job-scraper/
├── hk_jobs/
│   ├── adapters/
│   │   ├── base.py              # Abstract BaseAdapter (fetch_jobs -> list[Job])
│   │   ├── workday.py           # Workday JSON API adapter
│   │   ├── eightfold.py         # Eightfold JSON API adapter
│   │   ├── efc.py               # eFinancialCareers JSON API (inline descriptions)
│   │   ├── jobsdb.py            # JobsDB via Scrapling + GraphQL pagination
│   │   ├── indeed.py            # Indeed employer pages (mosaic JSON)
│   │   ├── linkedin.py          # LinkedIn guest jobs API (fallback)
│   │   └── longtail.py          # LLM-based extraction for boutique firms
│   ├── enrichers/
│   │   └── deepseek.py          # DeepSeek AI (seniority/skills/salary + summary)
│   ├── companies.yaml           # Core-ATS company config
│   ├── companies_longtail.yaml  # LLM long-tail company config
│   ├── pipeline.py              # Main orchestration + CLI (argparse)
│   ├── description_fetcher.py   # Description pipeline (GraphQL + REST)
│   ├── enrichment.py            # AI enrichment pipeline (20 concurrent workers)
│   ├── analytics.py             # Trend reporting and JSONL export
│   ├── llm_client.py            # Shared DeepSeek client
│   ├── tech_filter.py           # Filters out non-finance tech roles
│   ├── migrations.py            # SQLite schema migrations (phased, idempotent)
│   ├── storage.py               # JobStore — upsert, soft-delete, cross-post reconcile
│   ├── sync_pocketbase.py       # One-way jobs.db -> PocketBase mirror
│   └── schema.py                # Pydantic Job model + dedup hashing
├── webapp/
│   ├── backend/                 # FastAPI — job board API
│   └── frontend/                # React + TypeScript + Vite job board UI
├── scripts/
│   ├── daily_run.sh             # Production cron wrapper (6 phases)
│   ├── try_*_live.py            # Per-adapter live verification diagnostics
│   └── generate_intelligence_report.py  # Market intelligence report generator
├── tests/                       # pytest — adapters, storage, schema, cross-posting
├── salary_guidlines/            # Hays-derived salary calibration docs
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

<div align="center">

**Private repository — Finex Club members only**

</div>
