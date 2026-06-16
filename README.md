# HK Financial Job Board Scraper

**Automated job intelligence for Hong Kong's financial sector**

![Python](https://img.shields.io/badge/Python-3.11-blue) ![SQLite](https://img.shields.io/badge/Database-SQLite-green) ![DeepSeek](https://img.shields.io/badge/AI-DeepSeek-purple) ![Jobs](https://img.shields.io/badge/Jobs-2%2C000%2B-orange) ![Coverage](https://img.shields.io/badge/Descriptions-99.9%25-brightgreen) ![Public](https://img.shields.io/badge/Visibility-Public-brightgreen)

---

## Overview

A fully automated pipeline that scrapes job listings from 27 of Hong Kong's largest financial institutions, fetches full job descriptions, and enriches every listing with AI-extracted structured data (seniority, skills, job category, remote type). Runs daily and tracks hiring trends over time.

> **27 companies → 2,000+ active jobs → 99.9% descriptions → 100% AI-enriched**

---

## How It Works

| Step | Description | Time |
|------|-------------|------|
| **Scrape** | Collects listings from 27 companies (up to 5 pages each) | ~9 min |
| **Describe** | Fetches full descriptions via GraphQL & REST APIs | ~2 min |
| **Enrich** | Extracts seniority, skills, category via DeepSeek AI | ~4 min |
| **Track** | Records daily snapshots for trend analysis | ~1 min |
| **Total** | Full daily pipeline | **~15 min** |

---

## Companies Covered

**Banking (9)**
HSBC HK, Standard Chartered, DBS, Bank of China HK, Bank of East Asia, Citibank HK, ICBC Asia, CCB Asia, OCBC Wing Hang

**Insurance (9)**
AIA HK, Prudential HK, FWD Insurance, Sun Life HK, AXA HK, Manulife HK, Zurich HK, Generali HK, China Taiping

**Asset Management (9)**
BlackRock HK, UBS Asset Management, Fidelity International, Man Group, BNP Paribas AM, PIMCO HK, JPMorgan AM, Schroders HK, Value Partners

---

## Architecture

```
3 Data Sources
─────────────────────────────────────────────────────
JobsDB (22 companies)  │  Workday (4 companies)  │  Eightfold (1 — HSBC)
         │                        │                        │
         ▼                        ▼                        ▼

Stage 1 — Listings
Scrapling headless browser (Cloudflare bypass) + Direct REST APIs
10 parallel company workers · 5 pages per company · stop-when-empty
         │
         ▼

Stage 2 — Descriptions
JobsDB GraphQL API + Workday REST + Eightfold REST
99.9% coverage · ~100 ms per job · no browser needed
         │
         ▼

Stage 3 — AI Enrichment (DeepSeek deepseek-chat)
Seniority (junior/mid/senior/lead) · Required skills · Job category · Remote type
100% coverage · avg 5.0 skills per job · 20 concurrent workers
         │
         ▼

SQLite Database (data/jobs.db)
4 tables · 1,592 active jobs · daily trend snapshots
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
| Scheduling | Cron / systemd |

---

## Database Schema

| Table | Rows | Purpose |
|-------|------|---------|
| `jobs` | 1,592 active | Listings — title, company, URL, locations, posted_at |
| `job_enrichments` | 1,592 | AI fields — seniority, skills, category, remote_type, salary |
| `job_history` | 28+ | Daily snapshots per company for trend tracking |
| `company_metrics` | 28 | 7-day and 30-day rolling averages + growth rates |

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
# Full scrape — collect all listings from 27 companies
python -m hk_jobs.pipeline

# Fetch full descriptions (GraphQL + REST, ~2 min)
python -m hk_jobs.pipeline --fetch-descriptions

# AI enrichment — seniority, skills, category (requires DEEPSEEK_API_KEY)
python -m hk_jobs.pipeline --enrich

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
| Active jobs | **1,592** |
| Companies tracked | **27** |
| Description coverage | **99.9%** |
| Enrichment coverage | **100%** |
| Avg skills per job | **5.0** |
| Daily run time | **~15 minutes** |
| Monthly AI cost | **~$0.55 USD** |

---

## Project Structure

```
hk-job-scraper/
├── hk_jobs/
│   ├── adapters/
│   │   ├── jobsdb.py            # Scrapling + GraphQL pagination (5 pages/company)
│   │   ├── workday.py           # Workday REST API adapter
│   │   └── eightfold.py         # Eightfold REST API adapter
│   ├── enrichers/
│   │   └── deepseek.py          # DeepSeek AI (title + description, v5 prompt)
│   ├── companies.yaml           # Config for all 30 companies
│   ├── pipeline.py              # Main orchestration + CLI (argparse)
│   ├── description_fetcher.py   # Description pipeline (GraphQL + REST)
│   ├── enrichment.py            # AI enrichment pipeline (20 concurrent workers)
│   ├── analytics.py             # Trend reporting and JSONL export
│   ├── migrations.py            # SQLite schema migrations
│   └── schema.py                # Pydantic Job model
├── scripts/
│   ├── daily_run.sh             # Production cron wrapper
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

> **Private repository — Finex Members Only**
