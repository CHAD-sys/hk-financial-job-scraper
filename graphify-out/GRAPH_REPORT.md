# Graph Report - hk-job-scraper  (2026-06-27)

## Corpus Check
- 54 files · ~39,436 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 682 nodes · 1251 edges · 38 communities (31 shown, 7 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 69 edges (avg confidence: 0.51)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `a8465d69`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 23|Community 23]]
- [[_COMMUNITY_Community 24|Community 24]]
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 36|Community 36]]
- [[_COMMUNITY_Community 39|Community 39]]

## God Nodes (most connected - your core abstractions)
1. `Job` - 47 edges
2. `enrich()` - 36 edges
3. `JobStore` - 31 edges
4. `_job()` - 30 edges
5. `JobsDBAdapter` - 26 edges
6. `run()` - 26 edges
7. `BaseAdapter` - 23 edges
8. `WorkdayAdapter` - 20 edges
9. `with_retry()` - 19 edges
10. `_job()` - 19 edges

## Surprising Connections (you probably didn't know these)
- `test_build_adapter_returns_correct_type()` --calls--> `CompanyConfig`  [EXTRACTED]
  tests/test_config.py → hk_jobs/config.py
- `CompanyConfig` --uses--> `Job`  [INFERRED]
  tests/test_pipeline.py → hk_jobs/schema.py
- `_BrokenAdapter` --uses--> `Job`  [INFERRED]
  tests/test_base_adapter.py → hk_jobs/schema.py
- `_EchoAdapter` --uses--> `Job`  [INFERRED]
  tests/test_base_adapter.py → hk_jobs/schema.py
- `Job` --uses--> `Job`  [INFERRED]
  tests/test_base_adapter.py → hk_jobs/schema.py

## Import Cycles
- 1-file cycle: `hk_jobs/adapters/jobsdb.py -> hk_jobs/adapters/jobsdb.py`
- 1-file cycle: `hk_jobs/pipeline.py -> hk_jobs/pipeline.py`
- 1-file cycle: `hk_jobs/storage.py -> hk_jobs/storage.py`

## Communities (38 total, 7 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.09
Nodes (22): _parse_listing_html(), Extract job cards from a JobsDB company listing page.      data-automation value, Tests for the JobsDB fallback adapter.  All HTTP is intercepted via monkeypatchi, Fix A: company is extracted from the card, not stamped from config., Card 3 has no advertiser node — must fall back to config company., Listing-only: only 1 URL should be fetched (the listing page)., Without detail pages, descriptions are empty strings — expected., Card 1 has data-automation='jobAdvertiser' — must be extracted. (+14 more)

### Community 1 - "Community 1"
Cohesion: 0.09
Nodes (47): _detect_employment_type(), _detect_remote_type(), _detect_seniority(), _detect_skills(), _detect_years(), enrich(), enrich_all(), enrich_with_llm() (+39 more)

### Community 2 - "Community 2"
Cohesion: 0.09
Nodes (35): BaseModel, Job, jobs_from_jsonl(), jobs_to_jsonl(), Canonical Job schema.  Every adapter — regardless of source ATS — maps its raw d, Write a list of Job objects to a newline-delimited JSON file (one job per line)., Read a JSONL file written by jobs_to_jsonl and return Job objects., Return a 12-character fingerprint that identifies this job posting.          Why (+27 more)

### Community 4 - "Community 4"
Cohesion: 0.12
Nodes (40): CompanyConfig, CompanyConfig, Company configuration loader.  Reads companies.yaml and returns validated Compan, One validated entry from companies.yaml., Instantiate and return the adapter for this company.          Returns a BaseAdap, Raise ValueError with the company name if the config is invalid., _validate(), _parse_args() (+32 more)

### Community 5 - "Community 5"
Cohesion: 0.31
Nodes (8): _advertiser_accepted(), _normalize_advertiser_tokens(), Lowercase, strip punctuation + corporate-suffix noise, return token set., True if `advertiser` matches any accepted name.      Match is token-subset in ei, _acc(), test_allowlist_accepts_legal_entity_variants(), test_allowlist_empty_advertiser_rejected(), test_allowlist_rejects_cross_advertisers()

### Community 6 - "Community 6"
Cohesion: 0.12
Nodes (16): load_companies(), Path, Parse companies.yaml and return a list of validated CompanyConfig objects., Path, Tests for hk_jobs/config.py — companies.yaml loader and validator., Sanity-check we have a reasonable mix — not all jobsdb fallbacks., test_adapter_distribution(), test_build_adapter_returns_correct_type() (+8 more)

### Community 7 - "Community 7"
Cohesion: 0.06
Nodes (30): _map_time_type(), _parse_locations(), Public entry point — wraps _fetch_all in _safe_fetch for error isolation., Convert an HTML job description to clean plain text.      Block-level tags (p, b, Split Workday's locationsText into a list.      Workday uses pipe-separation for, Map Workday's timeType string to our canonical employment_type value., Fetches jobs from Workday's internal JSON API.      Each company that uses Workd, _strip_html() (+22 more)

### Community 8 - "Community 8"
Cohesion: 0.13
Nodes (11): build_styles(), fmt_date(), fmt_skills(), group_by_company(), load_data(), main(), Generate a comprehensive PDF: architecture overview + all 1,592 jobs. Output: ou, ReportDoc (+3 more)

### Community 9 - "Community 9"
Cohesion: 0.14
Nodes (13): Drawing, bar_chart(), by_category(), fmt_exp(), fmt_salary(), fmt_skills(), fmt_source(), FullReport (+5 more)

### Community 10 - "Community 10"
Cohesion: 0.07
Nodes (32): Any, _job_to_row(), JobStore, Manages a SQLite database of job postings.      Usage:         store = JobStore(, Insert or update a batch of jobs.          Returns (inserted, updated) counts. A, Soft-delete jobs for a company that were NOT seen in this run.          After we, Return summary counts for monitoring and reporting.          Shape:, Close the underlying database connection. (+24 more)

### Community 11 - "Community 11"
Cohesion: 0.16
Nodes (16): EnrichmentPipeline, CompanyResult, _log_trend_changes(), _NullLock, _print_report(), datetime, Pipeline orchestrator.  Reads companies.yaml, instantiates the right adapter for, Fetch, enrich, and store jobs for one company. Returns a CompanyResult.      db_ (+8 more)

### Community 12 - "Community 12"
Cohesion: 0.14
Nodes (8): DeepSeekEnricher, DeepSeek LLM enricher — v3: includes job description for richer skill extraction, Single API call. Raises on error., Enrich jobs sequentially. Callers wrap this in ThreadPoolExecutor for parallelis, Any, Connection, Row, Phase 12: LLM-based job enrichment pipeline — optimized.  Uses ThreadPoolExecuto

### Community 13 - "Community 13"
Cohesion: 0.12
Nodes (17): CompanyResult, date, calculate_hiring_velocity(), export_trends_jsonl(), get_all_trends(), get_company_trend(), print_trends_report(), print_velocity_report() (+9 more)

### Community 14 - "Community 14"
Cohesion: 0.15
Nodes (14): Connection, DescriptionFetcher, _fetch_eightfold_description(), _fetch_jobsdb_description(), _fetch_workday_description(), FetchResult, Fetch full job descriptions from ATS JSON APIs.  Why this is a separate step: th, Persist one batch of results. Returns (written, skipped, failed).          Also (+6 more)

### Community 15 - "Community 15"
Cohesion: 0.24
Nodes (17): discover_one(), _dns_ok(), domain_from_website(), jobsdb_slugs(), load_known_names(), main(), _match_key(), _name_core() (+9 more)

### Community 16 - "Community 16"
Cohesion: 0.05
Nodes (41): ABC, BaseAdapter, Abstract base class that every ATS adapter must implement.  An adapter's sole jo, Subclass this once per ATS type (Workday, Eightfold, etc.).      Subclasses set, Args:             company:      Human-readable name, e.g. "HSBC".             co, Fetch all active jobs from this source and return them as Job objects., Return a pre-configured httpx.Client.          Use as a context manager in adapt, Call fn(*args, **kwargs) and return its result.          If fn raises for any re (+33 more)

### Community 17 - "Community 17"
Cohesion: 0.20
Nodes (7): count_by(), fmt_date(), fmt_skills(), load_jobs(), main(), Generate a PDF report of all enriched HK financial sector jobs, organised by cat, ReportBuilder

### Community 18 - "Community 18"
Cohesion: 0.14
Nodes (13): Companies config (hk_jobs/companies.yaml), Company list (name → adapter → slug → enabled), Current contents, Data Model & Pipeline Inputs, Database (data/jobs.db), Discovery inputs/outputs (scripts/*.csv), Discovery results (discovered_companies.csv), Master list (companies_master_list.csv) (+5 more)

### Community 19 - "Community 19"
Cohesion: 0.14
Nodes (13): Architecture, Companies Covered, Daily Automation, Database Schema, HK Financial Job Board Scraper, How It Works, Overview, Project Structure (+5 more)

### Community 20 - "Community 20"
Cohesion: 0.17
Nodes (11): Architecture (the shape of the solution), CLAUDE.md — HK Financial Job Scraper, Core domain knowledge (read this — it drives every design decision), Project conventions, Tech stack (decided — do not substitute without asking), The fallback strategy, What an API is (the key insight), What an ATS is (+3 more)

### Community 21 - "Community 21"
Cohesion: 0.26
Nodes (10): Email notifications for pipeline events.  Sends two types of emails:   - Failure, Query today's stats and send a summary email., Send an immediate alert when the pipeline raises an exception., send_daily_summary(), _send_email(), send_failure_alert(), main(), generate_weekly_report() (+2 more)

### Community 22 - "Community 22"
Cohesion: 0.40
Nodes (5): _extract_source_id(), Extract trailing numeric job ID from a JobsDB URL; fall back to full URL., test_extract_source_id_legacy_suffix(), test_extract_source_id_modern_url(), test_extract_source_id_no_number_falls_back()

### Community 24 - "Community 24"
Cohesion: 0.12
Nodes (16): JobsDBAdapter, Scrapes listing pages for one company from hk.jobsdb.com.      Uses Scrapling's, For plain-listing companies, drop cards whose advertiser isn't accepted., BaseAdapter, Job, main(), Live smoke-test for the JobsDB fallback adapter.  ⚠  LEGAL: This script scrapes, adapter() (+8 more)

### Community 25 - "Community 25"
Cohesion: 0.25
Nodes (7): migrate_to_phase_11(), migrate_to_phase_12(), migrate_to_phase_13(), Database migrations for hk_jobs.  Each migration function is idempotent — safe t, Add scraped_under_slug column to jobs table.      This column records which comp, Create job_history and company_metrics tables if they don't already exist., Create job_enrichments table if it doesn't already exist.

### Community 27 - "Community 27"
Cohesion: 0.20
Nodes (10): _parse_listing_date(), JobsDB fallback adapter.  ╔═════════════════════════════════════════════════════, Parse a JobsDB relative date string into a UTC datetime.      Live page formats, # IMPORTANT: these selectors could not be verified against live Cloudflare-, datetime, test_parse_listing_date_days_ago(), test_parse_listing_date_empty(), test_parse_listing_date_hours_ago() (+2 more)

### Community 36 - "Community 36"
Cohesion: 0.33
Nodes (4): _is_challenge(), Return True if we got a Cloudflare or bot-protection response.      Only scans f, Fetch url and return (http_status, html_string).          Single mockable seam —, Fetch one listing page, retrying on transient failures.          Two kinds of tr

### Community 39 - "Community 39"
Cohesion: 0.18
Nodes (13): _BrokenAdapter, _EchoAdapter, Job, Tests for hk_jobs/adapters/base.py., test_cannot_instantiate_base_directly(), test_client_has_browser_user_agent(), test_client_includes_zh_hk_accept_language(), test_concrete_subclass_stores_fields() (+5 more)

## Knowledge Gaps
- **34 isolated node(s):** `Path`, `Any`, `hk-job-scraper`, `run_daily.sh script`, `What we are building` (+29 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **7 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Job` connect `Community 2` to `Community 1`, `Community 4`, `Community 7`, `Community 39`, `Community 10`, `Community 16`, `Community 24`, `Community 27`?**
  _High betweenness centrality (0.348) - this node is a cross-community bridge._
- **Why does `JobsDBAdapter` connect `Community 24` to `Community 0`, `Community 2`, `Community 36`, `Community 5`, `Community 15`, `Community 16`, `Community 26`, `Community 27`?**
  _High betweenness centrality (0.145) - this node is a cross-community bridge._
- **Why does `JobStore` connect `Community 10` to `Community 2`, `Community 11`, `Community 4`?**
  _High betweenness centrality (0.093) - this node is a cross-community bridge._
- **Are the 26 inferred relationships involving `Job` (e.g. with `BaseAdapter` and `EightfoldAdapter`) actually correct?**
  _`Job` has 26 INFERRED edges - model-reasoned connections that need verification._
- **Are the 11 inferred relationships involving `JobStore` (e.g. with `CompanyConfig` and `CompanyResult`) actually correct?**
  _`JobStore` has 11 INFERRED edges - model-reasoned connections that need verification._
- **Are the 2 inferred relationships involving `JobsDBAdapter` (e.g. with `BaseAdapter` and `Job`) actually correct?**
  _`JobsDBAdapter` has 2 INFERRED edges - model-reasoned connections that need verification._
- **What connects `JobsDB fallback adapter.  ╔═════════════════════════════════════════════════════`, `Lowercase, strip punctuation + corporate-suffix noise, return token set.`, `True if `advertiser` matches any accepted name.      Match is token-subset in ei` to the rest of the system?**
  _173 weakly-connected nodes found - possible documentation gaps or missing edges._