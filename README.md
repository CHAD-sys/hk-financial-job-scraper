<div align="center">

# HK Financial Job-Market Intelligence Platform

**Automated collection, AI enrichment, and market intelligence for Hong Kong's financial sector**

![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python&logoColor=white) ![FastAPI](https://img.shields.io/badge/API-FastAPI-009688?logo=fastapi&logoColor=white) ![React](https://img.shields.io/badge/UI-React%20%2B%20Vite-61DAFB?logo=react&logoColor=black) ![SQLite](https://img.shields.io/badge/Database-SQLite-003B57?logo=sqlite&logoColor=white) ![DeepSeek](https://img.shields.io/badge/AI-DeepSeek-8A2BE2) ![Sources](https://img.shields.io/badge/Sources-7-orange) ![Companies](https://img.shields.io/badge/Companies-190%2B-teal) ![Jobs](https://img.shields.io/badge/Active%20Jobs-5%2C000%2B-success) ![Enriched](https://img.shields.io/badge/AI%20Enriched-100%25-brightgreen) ![Private](https://img.shields.io/badge/Visibility-Private-lightgrey)

*Not just a scraper — a full pipeline that **collects** jobs from 7 sources, **enriches** every listing with AI, **analyses** hiring trends over time, and **delivers** it through a web board, a boss-facing mirror, PDF intelligence reports, and daily email.*

</div>

---

## Contents

- [Overview](#overview) · [Screenshots](#screenshots) · [The Daily Pipeline](#the-daily-pipeline) · [Data Sources](#data-sources)
- [AI Enrichment](#ai-enrichment--salary-calibration) · [Market Intelligence](#market-intelligence--analytics) · [Companies Covered](#companies-covered)
- [Architecture](#architecture) · [Tech Stack](#tech-stack) · [Database Schema](#database-schema) · [Delivery Surfaces](#delivery-surfaces)
- [Setup](#setup) · [Usage](#usage) · [Daily Automation](#daily-automation) · [Results](#results) · [Project Structure](#project-structure) · [Team](#team)

---

## Overview

A fully automated platform that tracks hiring across Hong Kong's largest banks, insurers, and asset managers. It runs end-to-end every day:

1. **Collect** — scrapes open roles from **seven sources**, each company resolved to its real Applicant Tracking System (ATS) and scraped through a **priority fallback chain**: a direct ATS JSON API where one exists → the finance-specialist board (eFinancialCareers) → general boards (JobsDB, Indeed, LinkedIn) → an LLM-based long-tail extractor for boutique firms with no structured feed.
2. **Enrich** — a single DeepSeek call per job adds seniority, skills, job category, remote type, an estimated HK salary range (calibrated against Hays anchors), and a plain-language card summary.
3. **Analyse** — records daily snapshots per company, computes rolling averages and growth/velocity, reconciles cross-posted roles, and generates market-intelligence and trend reports.
4. **Deliver** — a React job board, a read-only PocketBase mirror for stakeholders, a PDF intelligence report, and a daily summary email.

Every source maps into one canonical `Job` schema, so the rest of the system never knows or cares which board a listing came from. Adding a company is usually a single config entry.

> **7 sources · 190+ companies · 5,000+ active jobs · 100% AI-enriched · daily automation**

---

## Screenshots

<div align="center">

|  |  |
|:--:|:--:|
| **Main board** | **Active filters** |
| ![Main board](screenshots/main-board.png) | ![Filters active](screenshots/filters-active.png) |
| **Job detail (AI summary + salary)** | **Salary-sorted view** |
| ![Job detail](screenshots/job-detail.png) | ![Salary sort](screenshots/salary-sort.png) |

_About page_

![About](screenshots/about.png)

</div>

---

## The Daily Pipeline

`scripts/daily_run.sh` runs six phases in order (≈2 AM HKT):

| Phase | What it does | Module |
|:-----:|--------------|--------|
| **1** | Scrape listings from every enabled company via its fallback chain | `pipeline.py` |
| **2** | Fetch full descriptions (missing only) via JSON/GraphQL/REST | `description_fetcher.py` |
| **3** | DeepSeek AI enrichment of unenriched jobs (seniority, skills, salary, summary) | `enrichment.py` |
| **4** | Sync the read-only PocketBase mirror from SQLite (non-fatal) | `sync_pocketbase.py` |
| **5** | Back up the database (30-day rolling retention) | `backup.py` |
| **6** | Send the daily summary email (failure alerts fire immediately on any exception) | `notifications.py` |

Each company fails independently — one broken source never stops the run. Soft-delete only: a role that disappears is marked `is_active = False`, never hard-deleted.

---

## Data Sources

Seven adapters, tried per company in priority order. Every adapter implements the same contract — `fetch_jobs() -> list[Job]`.

| Adapter | Source | Access | Notes |
|---------|--------|--------|-------|
| `workday` | Company Workday ATS | JSON API | Most common ATS for large HK financial firms |
| `eightfold` | Company Eightfold ATS | JSON API | e.g. HSBC |
| `efinancialcareers` | eFinancialCareers (DHI) | JSON API | Finance-specialist board; **full description inline** + market signals (sponsored, expiry, parent company). Priority apply-link source |
| `jobsdb` | JobsDB (SEEK) | HTML via Scrapling | General board; Cloudflare-walled → headless bypass |
| `indeed` | Indeed employer pages | Embedded mosaic JSON | Listing-only (no full descriptions) |
| `linkedin` | LinkedIn guest jobs | JSON (no login) | Fallback only |
| `longtail` | Boutique careers pages | **LLM extraction** | Medium/small firms with no structured ATS feed (headless where needed) |

**Cross-posting:** when the same vacancy appears on multiple sources, `storage.reconcile_cross_posted()` fuzzy-matches titles and points the apply link at the richest copy (eFC preferred) — see `_SOURCE_PRIORITY`.

**Tech-role filter:** `tech_filter.py` soft-deletes non-finance software roles so the board stays finance-focused.

> ⚠️ **Legal note.** The `jobsdb`, `indeed`, `linkedin`, and `efinancialcareers` adapters call sources whose ToS restrict programmatic access. They are flagged prominently in-code and are for **prototype/verification only** — production requires written permission or a licensed data feed. This posture is documented, never buried.

---

## AI Enrichment & Salary Calibration

A single `deepseek-chat` call per job (`enrichers/deepseek.py`, 20 concurrent workers) produces:

- **Seniority · skills · job category · remote type**
- **Estimated HK salary range** (min / max / confidence) — calibrated against **Hays Asia salary-guide anchors** (`salary_guidlines/`) to keep estimates realistic and correct for systematic over-estimation
- **`description_summary`** — a condensed ≤3-sentence card summary (never overwrites the full description; empty, never hallucinated, when a job has no description e.g. Indeed rows)

A separate rule-based pass (`enrich.py`) handles deterministic fields (employment type, etc.) that don't need the model.

---

## Market Intelligence & Analytics

Beyond the raw board, the platform turns the data into market intelligence:

- **Trend & velocity reporting** (`analytics.py`) — daily `job_history` snapshots per company feed `company_metrics` (7-day / 30-day rolling averages + growth rates). `--report trends` / `--report velocity` rank who is hiring fastest.
- **PDF intelligence report** (`scripts/generate_intelligence_report.py`) — `outputs/HK_Job_Market_Intelligence_Report.pdf`: sector segmentation (banking / insurance / asset management), category taxonomy, salary bands, top hirers.
- **Full & trend reports** (`generate_full_report.py`, `generate_trend_report.py`) and a **weekly digest** (`--weekly-report`).
- **CSV export** (`scripts/export_jobs_csv.py`) and **JSONL trend export** (`--export-trends`).

---

## Companies Covered

**190+ active companies** across banking, insurance, and asset management, configured in `companies.yaml` (core-ATS sources) and `companies_longtail.yaml` (LLM long-tail). Representative names:

**Banking** — HSBC HK, Standard Chartered, DBS, Bank of China HK, Bank of East Asia, Citibank HK, ICBC Asia, CCB Asia, OCBC Wing Hang

**Insurance** — AIA HK, Prudential HK, FWD Insurance, Sun Life HK, AXA HK, Manulife HK, Zurich HK, Generali HK, China Taiping

**Asset Management** — BlackRock HK, UBS Asset Management, Fidelity International, Man Group, BNP Paribas AM, PIMCO HK, JPMorgan AM, Schroders HK, Value Partners, Macquarie, State Street

**Bulge-bracket via Indeed employer pages** — Goldman Sachs, JPMorgan, DBS *(near-zero clean JobsDB presence, so sourced from their employer-scoped `hk.indeed.com/cmp/…` pages instead).*

---

## Architecture

```
companies.yaml  →  pipeline.py  →  [adapter fallback chain]  →  enrich  →  storage.py  →  jobs.db
   (config)       (orchestrator)      (per company)          (AI + rules)  (SQLite)        │
                                                                                           ▼
                                          ┌───────────────────────┬──────────────────────┬─────────────────┐
                                          ▼                       ▼                      ▼                 ▼
                                    React web board        PocketBase mirror      PDF intelligence     daily email
                                    (FastAPI + Vite)      (boss-facing, RO)          report            (summary)
```

```
7 Data Sources (per-company priority fallback)
──────────────────────────────────────────────────────────────────────────────
 Workday · Eightfold · eFinancialCareers · JobsDB · Indeed · LinkedIn · Longtail(LLM)
        │
        ▼  Stage 1 — Listings   (direct JSON APIs · Scrapling headless for HTML boards · LLM for boutique pages)
        ▼  Stage 2 — Descriptions   (JobsDB GraphQL + Workday/Eightfold REST; eFC inline; Indeed listing-only)
        ▼  Stage 3 — AI Enrichment   (DeepSeek: seniority/skills/category/remote/salary + summary, Hays-calibrated)
        ▼  Storage   (SQLite: listings · enrichments · daily snapshots · cross-post reconciliation)
        ▼  Intelligence + Delivery   (analytics/trends · web board · PocketBase mirror · PDF report · email)
```

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.11 |
| Browser scraping | Scrapling (Playwright + Cloudflare bypass) |
| HTTP client | httpx (HTTP/2, timeouts) — shared retry helpers in `http_utils.py` |
| HTML parsing | selectolax |
| LLM extraction & enrichment | DeepSeek (`deepseek-chat`) via a shared `LLMClient` |
| Data validation | Pydantic v2 |
| Database | SQLite (WAL mode, Postgres-compatible SQL) |
| Parallelism | `ThreadPoolExecutor` (10 company workers · 20 enrichment workers) |
| Web app | FastAPI (backend) · React + TypeScript + Vite + Tailwind (frontend) |
| Stakeholder mirror | PocketBase (read-only mirror of `jobs.db`) |
| Reports | reportlab (PDF) |
| Scheduling | Cron / systemd |

---

## Database Schema

| Table | Purpose |
|-------|---------|
| `jobs` | Listings — title, company, URL, locations, posted_at, full description (`description_raw` / `description_clean`), source + cross-post links, `is_active` |
| `job_enrichments` | AI fields — seniority, skills, category, remote_type, salary (disclosed + estimated), `description_summary` |
| `job_history` | Daily snapshots per company for trend tracking |
| `company_metrics` | 7-day and 30-day rolling averages + growth rates |

The full job description on `jobs` is never overwritten — enrichment still reads it. Migrations are phased and idempotent (`migrations.py`).

---

## Delivery Surfaces

- **Web board** (`webapp/`) — FastAPI API + React/Vite UI: search, category/seniority/source filters, salary sort, job-detail modal with the AI summary, and saved jobs.
- **PocketBase mirror** — a one-way, read-only mirror of `jobs.db` for non-technical stakeholders (`sync_pocketbase.py`).
- **PDF intelligence report** — `outputs/HK_Job_Market_Intelligence_Report.pdf`.
- **Email** — daily summary on success; failure alert immediately on any phase exception.

---

## Setup

**Requirements:** Python 3.11+, DeepSeek API key

```bash
git clone <repo-url>
cd hk-job-scraper
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
scrapling install          # browser engine (first time only)
```

**Configuration** — create `config/api_keys.env` (gitignored):

```bash
export DEEPSEEK_API_KEY=your-key-here
```

---

## Usage

```bash
# Full scrape — all enabled companies
python -m hk_jobs.pipeline

# Fetch full descriptions (missing only)
python -m hk_jobs.pipeline --fetch-descriptions

# AI enrichment (unenriched only); --re-enrich re-runs every active job
python -m hk_jobs.pipeline --enrich
python -m hk_jobs.pipeline --enrich --re-enrich

# Only the LLM long-tail companies / skip them
python -m hk_jobs.pipeline --longtail-only
python -m hk_jobs.pipeline --no-longtail

# Reports & exports
python -m hk_jobs.pipeline --report trends
python -m hk_jobs.pipeline --report velocity
python -m hk_jobs.pipeline --weekly-report
python -m hk_jobs.pipeline --export-trends data/trends.jsonl

# Ops
python -m hk_jobs.pipeline --backup
python -m hk_jobs.pipeline --notify-summary

# Single-company test / dry run
python -m hk_jobs.pipeline --only hsbc-hk --dry-run -v

# Market-intelligence PDF
python scripts/generate_intelligence_report.py     # -> outputs/HK_Job_Market_Intelligence_Report.pdf

# Live-verify one source adapter (diagnostics)
python scripts/try_efc_live.py        # also try_workday/eightfold/jobsdb_live.py
```

### Web App

```bash
# Backend (FastAPI) — /api/jobs, /api/jobs/{source}/{source_id}, /api/filters, /api/stats
cd webapp/backend && uvicorn main:app --reload

# Frontend (React + Vite)
cd webapp/frontend && npm install && npm run dev
```

---

## Daily Automation

```bash
bash scripts/daily_run.sh          # all 6 phases
```

Cron (2 AM HKT = 18:00 UTC):

```bash
0 18 * * * /opt/hk-job-scraper/scripts/daily_run.sh
```

---

## Results

_Figures refresh on every daily run; snapshot from the latest run._

| Metric | Value |
|--------|-------|
| Active jobs | **~5,000+** |
| Data sources | **7** live (Workday · Eightfold · eFinancialCareers · JobsDB · Indeed · LinkedIn · Longtail) |
| Active companies | **~190** |
| Active jobs by source | JobsDB ~1,780 · Indeed ~950 · LinkedIn ~935 · eFC ~840 · Eightfold ~320 · Workday ~160 · Longtail ~140 |
| Enrichment coverage | **100%** of description-bearing jobs |
| Daily run time | **~30–45 min** (headless long-tail scraping dominates) |
| Monthly AI cost | **~$1 USD** |

---

## Project Structure

```
hk-job-scraper/
├── hk_jobs/
│   ├── adapters/
│   │   ├── base.py              # Abstract BaseAdapter (fetch_jobs -> list[Job])
│   │   ├── workday.py           # Workday JSON API
│   │   ├── eightfold.py         # Eightfold JSON API
│   │   ├── efc.py               # eFinancialCareers JSON API (inline descriptions + signals)
│   │   ├── jobsdb.py            # JobsDB via Scrapling + GraphQL pagination
│   │   ├── indeed.py            # Indeed employer pages (mosaic JSON)
│   │   ├── linkedin.py          # LinkedIn guest jobs API (fallback)
│   │   └── longtail.py          # LLM-based extraction for boutique firms
│   ├── enrichers/deepseek.py    # DeepSeek AI (seniority/skills/salary + summary)
│   ├── enrich.py                # Rule-based deterministic enrichment
│   ├── enrichment.py            # AI enrichment pipeline (20 workers)
│   ├── description_fetcher.py   # Description pipeline (GraphQL + REST)
│   ├── storage.py               # JobStore — upsert, soft-delete, cross-post reconcile
│   ├── analytics.py             # Trend/velocity reporting + JSONL export
│   ├── tech_filter.py           # Soft-deletes non-finance tech roles
│   ├── sync_pocketbase.py       # One-way jobs.db -> PocketBase mirror
│   ├── notifications.py         # Daily summary + failure-alert email
│   ├── backup.py                # Rolling DB backups
│   ├── migrations.py            # Phased, idempotent SQLite migrations
│   ├── llm_client.py            # Shared DeepSeek client
│   ├── http_utils.py            # Shared httpx retry/backoff helpers
│   ├── pipeline.py              # Orchestration + CLI (argparse)
│   ├── schema.py                # Pydantic Job model + dedup hashing
│   ├── companies.yaml           # Core-ATS company config
│   └── companies_longtail.yaml  # LLM long-tail company config
├── webapp/
│   ├── backend/                 # FastAPI — job board API
│   └── frontend/                # React + TypeScript + Vite job board UI
├── scripts/
│   ├── daily_run.sh             # Production cron wrapper (6 phases)
│   ├── generate_intelligence_report.py   # Market-intelligence PDF
│   ├── generate_full_report.py / generate_trend_report.py
│   ├── discover_companies.py    # Company discovery tooling
│   ├── resolve_indeed_slugs.py / resolve_linkedin_ids.py / fetch_linkedin_signals.py
│   └── try_*_live.py            # Per-adapter live verification diagnostics
├── tests/                       # pytest — adapters, storage, schema, cross-posting
├── salary_guidlines/            # Hays-derived salary calibration docs
├── outputs/                     # Generated reports (gitignored)
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
