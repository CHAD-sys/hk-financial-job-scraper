# Graph Report - hk-job-scraper  (2026-06-21)

## Corpus Check
- 53 files · ~35,204 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 654 nodes · 1208 edges · 33 communities (27 shown, 6 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 77 edges (avg confidence: 0.51)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `b05c9a40`
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
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 33|Community 33]]

## God Nodes (most connected - your core abstractions)
1. `Job` - 49 edges
2. `enrich()` - 36 edges
3. `JobStore` - 31 edges
4. `_job()` - 30 edges
5. `run()` - 26 edges
6. `BaseAdapter` - 25 edges
7. `JobsDBAdapter` - 22 edges
8. `WorkdayAdapter` - 21 edges
9. `with_retry()` - 19 edges
10. `_job()` - 19 edges

## Surprising Connections (you probably didn't know these)
- `test_cannot_instantiate_base_directly()` --calls--> `BaseAdapter`  [EXTRACTED]
  tests/test_base_adapter.py → hk_jobs/adapters/base.py
- `Request` --uses--> `EightfoldAdapter`  [INFERRED]
  tests/test_eightfold.py → hk_jobs/adapters/eightfold.py
- `Response` --uses--> `EightfoldAdapter`  [INFERRED]
  tests/test_eightfold.py → hk_jobs/adapters/eightfold.py
- `Path` --uses--> `WorkdayAdapter`  [INFERRED]
  tests/test_config.py → hk_jobs/adapters/workday.py
- `Request` --uses--> `WorkdayAdapter`  [INFERRED]
  tests/test_workday.py → hk_jobs/adapters/workday.py

## Import Cycles
- 1-file cycle: `hk_jobs/adapters/jobsdb.py -> hk_jobs/adapters/jobsdb.py`
- 1-file cycle: `hk_jobs/pipeline.py -> hk_jobs/pipeline.py`
- 1-file cycle: `hk_jobs/storage.py -> hk_jobs/storage.py`

## Communities (33 total, 6 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.05
Nodes (42): _extract_source_id(), _is_challenge(), JobsDBAdapter, _parse_listing_date(), _parse_listing_html(), JobsDB fallback adapter.  ╔═════════════════════════════════════════════════════, Fetch url and return (http_status, html_string).          Single mockable seam —, Fetch one listing page, retrying on transient failures.          Two kinds of tr (+34 more)

### Community 1 - "Community 1"
Cohesion: 0.09
Nodes (47): _detect_employment_type(), _detect_remote_type(), _detect_seniority(), _detect_skills(), _detect_years(), enrich(), enrich_all(), enrich_with_llm() (+39 more)

### Community 2 - "Community 2"
Cohesion: 0.07
Nodes (41): BaseModel, Job, jobs_from_jsonl(), jobs_to_jsonl(), Canonical Job schema.  Every adapter — regardless of source ATS — maps its raw d, Write a list of Job objects to a newline-delimited JSON file (one job per line)., Read a JSONL file written by jobs_to_jsonl and return Job objects., Return a 12-character fingerprint that identifies this job posting.          Why (+33 more)

### Community 3 - "Community 3"
Cohesion: 0.05
Nodes (41): ABC, BaseAdapter, Abstract base class that every ATS adapter must implement.  An adapter's sole jo, Subclass this once per ATS type (Workday, Eightfold, etc.).      Subclasses set, Args:             company:      Human-readable name, e.g. "HSBC".             co, Fetch all active jobs from this source and return them as Job objects., Return a pre-configured httpx.Client.          Use as a context manager in adapt, Call fn(*args, **kwargs) and return its result.          If fn raises for any re (+33 more)

### Community 4 - "Community 4"
Cohesion: 0.18
Nodes (31): _parse_args(), Execute the full scrape-enrich-store pipeline.      Returns the list of per-comp, run(), _args(), _cfg(), _job(), _MockAdapter, Path (+23 more)

### Community 5 - "Community 5"
Cohesion: 0.18
Nodes (13): _BrokenAdapter, _EchoAdapter, Job, Tests for hk_jobs/adapters/base.py., test_cannot_instantiate_base_directly(), test_client_has_browser_user_agent(), test_client_includes_zh_hk_accept_language(), test_concrete_subclass_stores_fields() (+5 more)

### Community 6 - "Community 6"
Cohesion: 0.09
Nodes (25): CompanyConfig, CompanyConfig, load_companies(), Path, Company configuration loader.  Reads companies.yaml and returns validated Compan, One validated entry from companies.yaml., Instantiate and return the adapter for this company.          Returns a BaseAdap, Parse companies.yaml and return a list of validated CompanyConfig objects. (+17 more)

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
Cohesion: 0.09
Nodes (27): JobStore, Manages a SQLite database of job postings.      Usage:         store = JobStore(, Soft-delete jobs for a company that were NOT seen in this run.          After we, Close the underlying database connection., _job(), Path, Tests for hk_jobs/storage.py — SQLite persistence layer., store() (+19 more)

### Community 11 - "Community 11"
Cohesion: 0.21
Nodes (12): CompanyResult, _log_trend_changes(), _print_report(), datetime, Fetch, enrich, and store jobs for one company. Returns a CompanyResult.      db_, Retry companies that returned 0 jobs, one at a time with a delay.      A company, Print a concise end-of-run summary to stdout., Log companies whose trend changed significantly after the snapshot was recorded. (+4 more)

### Community 12 - "Community 12"
Cohesion: 0.14
Nodes (8): DeepSeekEnricher, DeepSeek LLM enricher — v3: includes job description for richer skill extraction, Single API call. Raises on error., Enrich jobs sequentially. Callers wrap this in ThreadPoolExecutor for parallelis, Any, Connection, Row, Phase 12: LLM-based job enrichment pipeline — optimized.  Uses ThreadPoolExecuto

### Community 13 - "Community 13"
Cohesion: 0.12
Nodes (17): CompanyResult, date, calculate_hiring_velocity(), export_trends_jsonl(), get_all_trends(), get_company_trend(), print_trends_report(), print_velocity_report() (+9 more)

### Community 14 - "Community 14"
Cohesion: 0.24
Nodes (9): _fetch_eightfold_description(), _fetch_jobsdb_description(), _fetch_workday_description(), FetchResult, Fetch full job descriptions from ATS JSON APIs.  Why this is a separate step: th, Derive the Workday JSON detail API URL from the human-facing URL and fetch., Call the Eightfold per-job detail API.      GET https://{tenant}.eightfold.ai/ap, Fetch full job description from JobsDB via their GraphQL API.      Discovered 20 (+1 more)

### Community 15 - "Community 15"
Cohesion: 0.24
Nodes (17): discover_one(), _dns_ok(), domain_from_website(), jobsdb_slugs(), load_known_names(), main(), _match_key(), _name_core() (+9 more)

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
Cohesion: 0.31
Nodes (7): Email notifications for pipeline events.  Sends two types of emails:   - Failure, Query today's stats and send a summary email., send_daily_summary(), _send_email(), generate_weekly_report(), Weekly hiring trends report — emailed every Monday 9 AM HKT.  Run manually:   py, Query the DB for the past 7 days and send a rich HTML summary email.

### Community 22 - "Community 22"
Cohesion: 0.31
Nodes (6): DescriptionFetcher, Connection, Row, Persist one batch of results. Returns (written, skipped, failed).          The `, Calls ATS JSON detail APIs to populate description_raw / description_clean., Namespace

### Community 25 - "Community 25"
Cohesion: 0.17
Nodes (12): backup_database(), Database backup utility.  Creates a dated copy of jobs.db in data/backups/ and e, EnrichmentPipeline, migrate_to_phase_11(), migrate_to_phase_12(), Database migrations for hk_jobs.  Each migration function is idempotent — safe t, Create job_history and company_metrics tables if they don't already exist., Create job_enrichments table if it doesn't already exist. (+4 more)

## Knowledge Gaps
- **33 isolated node(s):** `Any`, `hk-job-scraper`, `run_daily.sh script`, `What we are building`, `What an ATS is` (+28 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **6 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Job` connect `Community 2` to `Community 0`, `Community 1`, `Community 3`, `Community 4`, `Community 5`, `Community 6`, `Community 7`, `Community 10`?**
  _High betweenness centrality (0.342) - this node is a cross-community bridge._
- **Why does `JobsDBAdapter` connect `Community 0` to `Community 2`, `Community 3`, `Community 15`?**
  _High betweenness centrality (0.121) - this node is a cross-community bridge._
- **Why does `JobStore` connect `Community 10` to `Community 2`, `Community 4`, `Community 6`, `Community 11`, `Community 22`, `Community 25`, `Community 26`?**
  _High betweenness centrality (0.098) - this node is a cross-community bridge._
- **Are the 28 inferred relationships involving `Job` (e.g. with `BaseAdapter` and `EightfoldAdapter`) actually correct?**
  _`Job` has 28 INFERRED edges - model-reasoned connections that need verification._
- **Are the 11 inferred relationships involving `JobStore` (e.g. with `CompanyConfig` and `CompanyResult`) actually correct?**
  _`JobStore` has 11 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Adapter registry.  Maps the `ats` string from companies.yaml to the adapter clas`, `Abstract base class that every ATS adapter must implement.  An adapter's sole jo`, `Subclass this once per ATS type (Workday, Eightfold, etc.).      Subclasses set` to the rest of the system?**
  _159 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Community 0` be split into smaller, more focused modules?**
  _Cohesion score 0.054354178842782 - nodes in this community are weakly interconnected._