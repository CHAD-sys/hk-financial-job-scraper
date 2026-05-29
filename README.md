# HK Financial Job Scraper

A daily scraper for open job postings at the 30 largest Hong Kong financial institutions (banks, insurers, asset managers). It reads each company's ATS (Applicant Tracking System) JSON API directly, enriches each posting with structured features (seniority, skills, employment type), and persists everything to a SQLite database with soft-delete semantics.

---

## Quick start

```bash
# 1. Clone and create a virtual environment
git clone <repo-url>
cd hk-job-scraper
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Verify the test suite
pytest                          # 200+ tests, all should pass

# 4. Smoke-test one company (no database write)
python scripts/try_workday_live.py --tenant aia --site External --wd wd3

# 5. Run the full pipeline
bash scripts/run_daily.sh       # writes data/jobs.db + data/jobs_YYYYMMDD.jsonl

# Or directly:
python -m hk_jobs.pipeline --db data/jobs.db --export data/jobs.jsonl

# One company only (useful while verifying configs):
python -m hk_jobs.pipeline --company aia-hk --db data/jobs.db
```

---

## What's where

| File | One-sentence description |
|---|---|
| `hk_jobs/schema.py` | The canonical `Job` Pydantic model — one format every adapter maps into. |
| `hk_jobs/adapters/base.py` | Abstract `BaseAdapter` with browser User-Agent, retry helper, and `_safe_fetch` error isolation. |
| `hk_jobs/adapters/workday.py` | Hits Workday's internal JSON API (POST /jobs → paginate → GET detail). Used by ~13 companies. |
| `hk_jobs/adapters/eightfold.py` | Hits Eightfold AI's JSON API (GET /api/apply/v2/jobs). Used by HSBC group companies. |
| `hk_jobs/adapters/jobsdb.py` | **Prototype fallback only** — scrapes hk.jobsdb.com HTML. Used when a company's own ATS is hostile. See legal note below. |
| `hk_jobs/http_utils.py` | `with_retry()` — exponential backoff on timeouts, network errors, and 429/5xx responses. |
| `hk_jobs/enrich.py` | Rule-based feature extraction: seniority, employment type, remote type, years of experience, and skills from a 100-term HK finance vocabulary. |
| `hk_jobs/storage.py` | `JobStore` — SQLite with upsert-on-conflict and soft-delete. Lists stored as JSON; datetimes as ISO text. |
| `hk_jobs/config.py` | Loads and validates `companies.yaml`; returns `CompanyConfig` objects with `build_adapter()`. |
| `hk_jobs/pipeline.py` | Orchestrator: loads config → runs adapters (with per-company timeout) → enriches → upserts → marks inactive → prints summary. |
| `hk_jobs/companies.yaml` | All 30 companies with ATS config. **Every value is a guess — see verification guide below.** |
| `scripts/run_daily.sh` | One-command full run + export. |
| `scripts/try_workday_live.py` | Live smoke-test for Workday — run locally to verify a tenant config. |
| `scripts/try_eightfold_live.py` | Live smoke-test for Eightfold. |
| `scripts/try_jobsdb_live.py` | Live smoke-test for JobsDB fallback. |
| `.github/workflows/daily.yml` | GitHub Actions workflow — runs at 02:00 HKT, uploads JSONL artifact. |

---

## How scraping works: the ATS strategy

Companies don't hand-edit careers pages. They use an **ATS (Applicant Tracking System)** that serves job data via an internal JSON API. We call that API directly — far faster and more reliable than driving a headless browser.

| ATS | URL pattern | Our approach | Companies |
|---|---|---|---|
| **Workday** | `*.myworkdayjobs.com` | POST `/wday/cxs/{tenant}/{site}/jobs` → paginate → GET detail | Standard Chartered, AIA, Manulife, BlackRock, and ~9 others |
| **Eightfold AI** | `*.eightfold.ai` | GET `/api/apply/v2/jobs?domain=…` → paginate | HSBC, Hang Seng Bank, HSBC Life |
| **JobsDB fallback** | `hk.jobsdb.com` | HTML scrape with `selectolax` | BOCHK, Citibank HK, and ~11 others whose own ATS is hostile |

Hostile ATSes (Taleo, iCIMS) fight scraping aggressively. Since almost every HK employer also posts on JobsDB, we fall back there.

---

## Verifying ATS configs (do this before the first live run)

Every `adapter:`, `tenant:`, `site:`, `domain:`, and `jobsdb_slug:` in `companies.yaml` is marked `# TODO verify` unless explicitly confirmed. Here's how to verify each one in ~2 minutes:

1. Open the company's careers page in Chrome.
2. Open DevTools → **Network** tab → tick **Fetch/XHR**.
3. Type in the job-search box or scroll the listing.
4. Look at the request URLs:
   - `myworkdayjobs.com` in the URL → `adapter: workday`. The path is `/wday/cxs/{tenant}/{site}/jobs` — copy `tenant` and `site`.
   - `eightfold.ai` in the URL → `adapter: eightfold`. Subdomain is `{tenant}.eightfold.ai`. Check the `domain` query parameter.
   - `taleo.net` or `icims.com` → `adapter: jobsdb` (hostile, use fallback).
5. For the JobsDB slug: search the company on `hk.jobsdb.com`, click their company page, and copy the slug from the URL before `-jobs`.
6. Remove the `# TODO verify` comment from `companies.yaml` once confirmed.

Then test with:
```bash
python -m hk_jobs.pipeline --company <slug> --db /tmp/test.db
```

---

## Scheduling

### cron
```cron
# Runs at 18:00 UTC = 02:00 HKT (UTC+8)
0 18 * * * cd /path/to/hk-job-scraper && bash scripts/run_daily.sh >> logs/scraper.log 2>&1
```

### systemd timer
```ini
# /etc/systemd/system/hk-jobs.service
[Unit]
Description=HK Financial Job Scraper

[Service]
Type=oneshot
WorkingDirectory=/path/to/hk-job-scraper
ExecStart=/path/to/hk-job-scraper/scripts/run_daily.sh
StandardOutput=append:/var/log/hk-jobs.log
StandardError=inherit
```
```ini
# /etc/systemd/system/hk-jobs.timer
[Unit]
Description=Run HK jobs scraper daily at 02:00 HKT

[Timer]
OnCalendar=*-*-* 18:00:00 UTC
Persistent=true

[Install]
WantedBy=timers.target
```
```bash
systemctl enable --now hk-jobs.timer
```

### GitHub Actions
See `.github/workflows/daily.yml`. Runs at 02:00 HKT, uploads a JSONL artifact (`jobs-<run-id>`) retained for 30 days. Trigger a manual run from the Actions tab and optionally pass a `company` slug to run only one company.

---

## End-of-run report

The pipeline always prints a summary:

```
==============================================================
  RUN COMPLETE  2024-03-01 18:02 UTC
==============================================================
  Companies run  : 30
  Jobs fetched   : 1,847  (312 new, 1,535 updated)
  Active in DB   : 1,847 / 2,103 total

  ⚠  2 companies returned 0 jobs — check config:
       China Taiping Insurance  (china-taiping)
       Man Group Hong Kong      (man-group-hk)
==============================================================
```

**0-job companies** almost always mean a broken config (wrong slug/tenant, ATS URL changed) or an anti-bot block — not genuinely zero openings. Investigate with the matching `scripts/try_*_live.py` script.

---

## Pipeline flags

```
python -m hk_jobs.pipeline [options]

  --db PATH           SQLite database path (default: data/jobs.db)
  --export PATH       Export active jobs to JSONL after the run
  --company SLUG      Run only one company by slug (e.g. aia-hk)
  --no-enrich         Skip rule-based enrichment (faster, but no skills/seniority)
  --config PATH       Override the default companies.yaml path
  --log-level LEVEL   DEBUG | INFO | WARNING | ERROR (default: INFO)
```

---

## Legal notices and caveats

### JobsDB scraping
The `jobsdb` adapter scrapes `hk.jobsdb.com`, which **violates JobsDB's Terms of Service**. It exists only as a prototype fallback for companies whose own ATS is too hostile to scrape directly. **Do not use in production** without either (a) written permission from JobsDB / SEEK or (b) a paid data-feed arrangement. See `hk_jobs/adapters/jobsdb.py` for the full warning.

### ATS config values are guesses
Every `tenant:`, `site:`, `domain:`, and `jobsdb_slug:` in `companies.yaml` is an educated guess. The pipeline logs a clear error when a config is wrong; it will never silently return 0 jobs without a warning. Verify each company before relying on its data (see verification guide above).

### Hong Kong PDPO (Personal Data Privacy Ordinance)
Job postings collected here are publicly advertised and are **not personal data** under the PDPO. However, the downstream project that matches member CVs against this database will handle personal data. When building that project, ensure:
- CVs are collected only with explicit member consent.
- Retention periods are defined and enforced.
- Members can request deletion of their CV data.
- Matching results are not disclosed to third parties without consent.

Consult `hk.pcpd.org.hk` for current PCPD guidance on employment-related data processing.
