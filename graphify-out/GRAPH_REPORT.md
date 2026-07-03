# Graph Report - hk-job-scraper  (2026-07-03)

## Corpus Check
- 84 files · ~59,119 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 994 nodes · 1747 edges · 60 communities (50 shown, 10 thin omitted)
- Extraction: 95% EXTRACTED · 5% INFERRED · 0% AMBIGUOUS · INFERRED: 79 edges (avg confidence: 0.51)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `631c4730`
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
- [[_COMMUNITY_Community 37|Community 37]]
- [[_COMMUNITY_Community 38|Community 38]]
- [[_COMMUNITY_Community 39|Community 39]]
- [[_COMMUNITY_Community 40|Community 40]]
- [[_COMMUNITY_Community 41|Community 41]]
- [[_COMMUNITY_Community 42|Community 42]]
- [[_COMMUNITY_Community 43|Community 43]]
- [[_COMMUNITY_Community 44|Community 44]]
- [[_COMMUNITY_Community 45|Community 45]]
- [[_COMMUNITY_Community 46|Community 46]]
- [[_COMMUNITY_Community 47|Community 47]]
- [[_COMMUNITY_Community 48|Community 48]]
- [[_COMMUNITY_Community 49|Community 49]]
- [[_COMMUNITY_Community 51|Community 51]]
- [[_COMMUNITY_Community 52|Community 52]]
- [[_COMMUNITY_Community 53|Community 53]]
- [[_COMMUNITY_Community 54|Community 54]]
- [[_COMMUNITY_Community 55|Community 55]]
- [[_COMMUNITY_Community 56|Community 56]]
- [[_COMMUNITY_Community 57|Community 57]]
- [[_COMMUNITY_Community 58|Community 58]]
- [[_COMMUNITY_Community 59|Community 59]]

## God Nodes (most connected - your core abstractions)
1. `Job` - 52 edges
2. `enrich()` - 36 edges
3. `JobStore` - 30 edges
4. `_job()` - 30 edges
5. `BaseAdapter` - 28 edges
6. `run()` - 26 edges
7. `IndeedAdapter` - 25 edges
8. `JobsDBAdapter` - 25 edges
9. `WorkdayAdapter` - 21 edges
10. `with_retry()` - 19 edges

## Surprising Connections (you probably didn't know these)
- `Job` --uses--> `Job`  [INFERRED]
  tests/test_schema.py → hk_jobs/schema.py
- `Request` --uses--> `EightfoldAdapter`  [INFERRED]
  tests/test_eightfold.py → hk_jobs/adapters/eightfold.py
- `Response` --uses--> `EightfoldAdapter`  [INFERRED]
  tests/test_eightfold.py → hk_jobs/adapters/eightfold.py
- `Path` --uses--> `WorkdayAdapter`  [INFERRED]
  tests/test_config.py → hk_jobs/adapters/workday.py
- `Request` --uses--> `WorkdayAdapter`  [INFERRED]
  tests/test_workday.py → hk_jobs/adapters/workday.py

## Import Cycles
- 1-file cycle: `hk_jobs/adapters/indeed.py -> hk_jobs/adapters/indeed.py`
- 1-file cycle: `hk_jobs/adapters/jobsdb.py -> hk_jobs/adapters/jobsdb.py`
- 1-file cycle: `hk_jobs/pipeline.py -> hk_jobs/pipeline.py`
- 1-file cycle: `hk_jobs/storage.py -> hk_jobs/storage.py`

## Communities (60 total, 10 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.08
Nodes (27): _parse_listing_date(), _parse_listing_html(), Extract job cards from a JobsDB company listing page.      data-automation value, Parse a JobsDB relative date string into a UTC datetime.      Live page formats, Tests for the JobsDB fallback adapter.  All HTTP is intercepted via monkeypatchi, Fix A: company is extracted from the card, not stamped from config., Card 3 has no advertiser node — must fall back to config company., Listing-only: only 1 URL should be fetched (the listing page). (+19 more)

### Community 1 - "Community 1"
Cohesion: 0.09
Nodes (47): _detect_employment_type(), _detect_remote_type(), _detect_seniority(), _detect_skills(), _detect_years(), enrich(), enrich_all(), enrich_with_llm() (+39 more)

### Community 2 - "Community 2"
Cohesion: 0.12
Nodes (26): jobs_from_jsonl(), jobs_to_jsonl(), Write a list of Job objects to a newline-delimited JSON file (one job per line)., Read a JSONL file written by jobs_to_jsonl and return Job objects., Write all active jobs to a JSONL file, sorted by company then title.          Re, _make_job(), Job, Tests for hk_jobs/schema.py — the canonical Job model. (+18 more)

### Community 3 - "Community 3"
Cohesion: 0.06
Nodes (12): EightfoldAdapter, Fetches jobs from Eightfold AI's public JSON API.      'tenant' is the subdomain, Public entry point — wraps _fetch_all in _safe_fetch for error isolation., Job, main(), Live smoke-test for the Eightfold adapter.  Run this LOCALLY (not in CI) to conf, adapter(), _MockTransport (+4 more)

### Community 4 - "Community 4"
Cohesion: 0.06
Nodes (63): CompanyConfig, CompanyConfig, load_companies(), Company configuration loader.  Reads companies.yaml and returns validated Compan, One validated entry from companies.yaml., Instantiate and return the adapter for this company.          Returns a BaseAdap, Parse companies.yaml and return a list of validated CompanyConfig objects., Raise ValueError with the company name if the config is invalid. (+55 more)

### Community 5 - "Community 5"
Cohesion: 0.24
Nodes (9): _advertiser_accepted(), _normalize_advertiser_tokens(), For plain-listing companies, drop cards whose advertiser isn't accepted., Lowercase, strip punctuation + corporate-suffix noise, return token set., True if `advertiser` matches any accepted name.      Match is token-subset in ei, _acc(), test_allowlist_accepts_legal_entity_variants(), test_allowlist_empty_advertiser_rejected() (+1 more)

### Community 6 - "Community 6"
Cohesion: 0.06
Nodes (43): countActiveFilters(), DEFAULT_FILTERS, fetchFilters(), fetchJobDetail(), fetchJobs(), fetchStats(), FiltersResponse, filtersToSearchParams() (+35 more)

### Community 7 - "Community 7"
Cohesion: 0.09
Nodes (16): _map_time_type(), _parse_locations(), Convert an HTML job description to clean plain text.      Block-level tags (p, b, Split Workday's locationsText into a list.      Workday uses pipe-separation for, Map Workday's timeType string to our canonical employment_type value., _strip_html(), Tests for the Workday adapter.  All HTTP is intercepted by a custom httpx transp, test_map_time_type() (+8 more)

### Community 8 - "Community 8"
Cohesion: 0.13
Nodes (11): build_styles(), fmt_date(), fmt_skills(), group_by_company(), load_data(), main(), Generate a comprehensive PDF: architecture overview + all 1,592 jobs. Output: ou, ReportDoc (+3 more)

### Community 9 - "Community 9"
Cohesion: 0.14
Nodes (13): Drawing, bar_chart(), by_category(), fmt_exp(), fmt_salary(), fmt_skills(), fmt_source(), FullReport (+5 more)

### Community 10 - "Community 10"
Cohesion: 0.14
Nodes (21): _job(), Tests for hk_jobs/storage.py — SQLite persistence layer., test_context_manager(), test_insert_two_new_jobs(), test_mark_inactive_deactivates_stale_rows(), test_mark_inactive_leaves_current_rows_active(), test_mark_inactive_only_affects_target_company(), test_mark_inactive_returns_count() (+13 more)

### Community 11 - "Community 11"
Cohesion: 0.21
Nodes (14): EnrichmentPipeline, CompanyResult, _log_trend_changes(), _print_report(), datetime, Pipeline orchestrator.  Reads companies.yaml, instantiates the right adapter for, Fetch, enrich, and store jobs for one company. Returns a CompanyResult.      db_, Retry companies that returned 0 jobs, one at a time with a delay.      A company (+6 more)

### Community 12 - "Community 12"
Cohesion: 0.11
Nodes (15): DeepSeekEnricher, DeepSeek LLM enricher — v3: includes job description for richer skill extraction, Enrich jobs sequentially. Callers wrap this in ThreadPoolExecutor for parallelis, Single API call. Raises on error., Any, _clean_summary(), _coerce_int(), _norm_confidence() (+7 more)

### Community 13 - "Community 13"
Cohesion: 0.15
Nodes (13): calculate_hiring_velocity(), export_trends_jsonl(), get_all_trends(), get_company_trend(), print_trends_report(), print_velocity_report(), Job history analytics: snapshot recording and trend reporting.  Called by the pi, Return daily history rows for one company over the last N days. (+5 more)

### Community 14 - "Community 14"
Cohesion: 0.14
Nodes (15): DescriptionFetcher, _fetch_eightfold_description(), _fetch_jobsdb_description(), _fetch_workday_description(), FetchResult, Connection, Row, Fetch full job descriptions from ATS JSON APIs.  Why this is a separate step: th (+7 more)

### Community 15 - "Community 15"
Cohesion: 0.24
Nodes (17): discover_one(), _dns_ok(), domain_from_website(), jobsdb_slugs(), load_known_names(), main(), _match_key(), _name_core() (+9 more)

### Community 16 - "Community 16"
Cohesion: 0.13
Nodes (14): Public entry point — wraps _fetch_all in _safe_fetch for error isolation., Fetches jobs from Workday's internal JSON API.      Each company that uses Workd, WorkdayAdapter, Client, Job, main(), Live smoke-test for the Workday adapter.  Run this LOCALLY (not in CI) to verify, adapter() (+6 more)

### Community 17 - "Community 17"
Cohesion: 0.24
Nodes (14): build_story(), date_str(), detect_sector(), load_jobs(), loc_str(), main(), make_header_footer(), make_table() (+6 more)

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
Cohesion: 0.08
Nodes (25): dependencies, lucide-react, react, react-dom, react-router-dom, recharts, tailwindcss, @tailwindcss/vite (+17 more)

### Community 24 - "Community 24"
Cohesion: 0.10
Nodes (20): _is_challenge(), JobsDBAdapter, Return True if we got a Cloudflare or bot-protection response.      Only scans f, Scrapes listing pages for one company from hk.jobsdb.com.      Uses Scrapling's, Fetch url and return (http_status, html_string).          Single mockable seam —, Fetch one listing page, retrying on transient failures.          Two kinds of tr, Job, main() (+12 more)

### Community 25 - "Community 25"
Cohesion: 0.17
Nodes (11): migrate_to_phase_11(), migrate_to_phase_12(), migrate_to_phase_13(), migrate_to_phase_14(), migrate_to_phase_15(), Database migrations for hk_jobs.  Each migration function is idempotent — safe t, Add scraped_under_slug column to jobs table.      This column records which comp, Add AI salary-estimate columns to job_enrichments.      These hold DeepSeek's *e (+3 more)

### Community 26 - "Community 26"
Cohesion: 0.09
Nodes (22): Accessibility Compliance, Anti-Patterns (from ui-ux-pro-max), Brand Accent, Color Tokens, Component Patterns, Elevation / Shadow Scale, FinEx Careers — Design System, Fonts (+14 more)

### Community 27 - "Community 27"
Cohesion: 0.11
Nodes (17): _epoch_ms_to_dt(), _parse_listing_json(), Convert an Indeed epoch-milliseconds timestamp to a UTC datetime., Extract job cards from an Indeed company listing page's embedded JSON.      The, Tests for the Indeed fallback adapter.  All HTTP is intercepted by monkeypatchin, Card company is blank on employer pages → stamp the configured company name., Listing-only: exactly one URL fetched (the page-1 listing)., Employer-scoped /cmp/ pages leave each card's company blank. (+9 more)

### Community 36 - "Community 36"
Cohesion: 0.15
Nodes (24): _build_where(), ExperienceRange, FiltersResponse, get_db(), get_filters(), get_job(), get_stats(), JobDetail (+16 more)

### Community 37 - "Community 37"
Cohesion: 0.11
Nodes (18): compilerOptions, allowImportingTsExtensions, erasableSyntaxOnly, jsx, lib, module, moduleDetection, moduleResolution (+10 more)

### Community 38 - "Community 38"
Cohesion: 0.25
Nodes (5): Args:             company:      Human-readable name, e.g. "HSBC".             co, Fetch all active jobs from this source and return them as Job objects., Call fn(*args, **kwargs) and return its result.          If fn raises for any re, Any, Job

### Community 39 - "Community 39"
Cohesion: 0.19
Nodes (12): _BrokenAdapter, _EchoAdapter, Job, Tests for hk_jobs/adapters/base.py., test_client_has_browser_user_agent(), test_client_includes_zh_hk_accept_language(), test_concrete_subclass_stores_fields(), test_fetch_jobs_returns_job_objects() (+4 more)

### Community 40 - "Community 40"
Cohesion: 0.13
Nodes (19): ABC, BaseAdapter, Abstract base class that every ATS adapter must implement.  An adapter's sole jo, Subclass this once per ATS type (Workday, Eightfold, etc.).      Subclasses set, Return a pre-configured httpx.Client.          Use as a context manager in adapt, Eightfold AI ATS adapter.  Eightfold is used by HSBC, Hang Seng Bank, and HSBC L, Indeed fallback adapter.  ╔═════════════════════════════════════════════════════, Adapter registry.  Maps the `ats` string from companies.yaml to the adapter clas (+11 more)

### Community 41 - "Community 41"
Cohesion: 0.12
Nodes (16): compilerOptions, allowImportingTsExtensions, erasableSyntaxOnly, lib, module, moduleDetection, noEmit, noFallthroughCasesInSwitch (+8 more)

### Community 42 - "Community 42"
Cohesion: 0.20
Nodes (15): Any, Shared HTTP utilities used across adapters.  with_retry() wraps a single HTTP ca, Call fn() up to max_attempts times, retrying on transient HTTP errors.      Retr, with_retry(), Tests for hk_jobs/http_utils.py — retry-with-backoff helper., test_does_not_retry_403(), test_does_not_retry_404(), test_raises_after_max_attempts_429() (+7 more)

### Community 43 - "Community 43"
Cohesion: 0.13
Nodes (14): IndeedAdapter, Scrapes the employer-scoped listing pages for one company from hk.indeed.com., BaseAdapter, Job, Page 2 repeats one card (ccc333) — output must contain 5 unique jobs, not 6., A login/verify wall must yield [] and never raise — we do not cross it., test_403_returns_empty_list(), test_challenge_returns_empty_list() (+6 more)

### Community 44 - "Community 44"
Cohesion: 0.30
Nodes (10): build(), detect_sector(), fmt_num(), fmt_pct(), load(), main(), make_header_footer(), make_table() (+2 more)

### Community 45 - "Community 45"
Cohesion: 0.29
Nodes (7): _extract_mosaic_json(), Pull the `mosaic-provider-jobcards` JSON object out of the page.      Indeed ass, The brace-matcher must not stop at a nested '}' inside the object., test_extract_mosaic_json_absent_returns_none(), test_extract_mosaic_json_brace_match_survives_nested_braces(), test_extract_mosaic_json_malformed_returns_none(), test_extract_mosaic_json_returns_model()

### Community 46 - "Community 46"
Cohesion: 0.16
Nodes (11): _job_to_row(), Any, datetime, Job, Row, SQLite persistence layer.  Design principles:   - SQL is written to be Postgres-, Insert or update a batch of jobs.          Returns (inserted, updated) counts. A, Return summary counts for monitoring and reporting.          Shape: (+3 more)

### Community 47 - "Community 47"
Cohesion: 0.33
Nodes (5): plugins, rules, react/only-export-components, react/rules-of-hooks, $schema

### Community 48 - "Community 48"
Cohesion: 0.50
Nodes (3): Expanding the Oxlint configuration, React Compiler, React + TypeScript + Vite

### Community 51 - "Community 51"
Cohesion: 0.18
Nodes (18): _classify(), _extract_cards(), _extract_mosaic_cards(), _fetch(), _find_embedded_json(), _ldjson_jobs(), main(), probe() (+10 more)

### Community 52 - "Community 52"
Cohesion: 0.40
Nodes (5): _extract_source_id(), Extract trailing numeric job ID from a JobsDB URL; fall back to full URL., test_extract_source_id_legacy_suffix(), test_extract_source_id_modern_url(), test_extract_source_id_no_number_falls_back()

### Community 54 - "Community 54"
Cohesion: 0.18
Nodes (8): _is_challenge(), Fetch url and return (http_status, html_string).          Single mockable seam —, page 1 → base URL; page N → ?start=(N-1)*20 (steps of 20, never 10)., Fetch one listing page, retrying on transient failures.          Mirrors the Job, Return True if we got a Cloudflare or bot-protection response.      Only scans f, test_is_challenge_false_on_large_content_page(), test_is_challenge_on_403(), test_is_challenge_on_short_challenge_page()

### Community 58 - "Community 58"
Cohesion: 0.40
Nodes (5): _is_login_wall(), True if the page is a login / human-verification wall we must not cross., The benign header 'Sign in' link (secure.indeed.com) must NOT read as a wall., test_login_wall_detected(), test_login_wall_not_triggered_by_signin_link()

### Community 59 - "Community 59"
Cohesion: 0.50
Nodes (4): CompanyResult, date, Write one job_history row per company and refresh company_metrics.      Called a, record_scrape_snapshot()

## Knowledge Gaps
- **125 isolated node(s):** `Connection`, `Row`, `StatsResponse`, `Any`, `hk-job-scraper` (+120 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **10 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Job` connect `Community 40` to `Community 1`, `Community 2`, `Community 3`, `Community 4`, `Community 36`, `Community 38`, `Community 39`, `Community 10`, `Community 43`, `Community 46`, `Community 16`, `Community 24`?**
  _High betweenness centrality (0.255) - this node is a cross-community bridge._
- **Why does `JobsDBAdapter` connect `Community 24` to `Community 40`, `Community 0`, `Community 5`, `Community 15`?**
  _High betweenness centrality (0.082) - this node is a cross-community bridge._
- **Why does `IndeedAdapter` connect `Community 43` to `Community 40`, `Community 54`, `Community 55`, `Community 56`, `Community 27`?**
  _High betweenness centrality (0.061) - this node is a cross-community bridge._
- **Are the 30 inferred relationships involving `Job` (e.g. with `BaseAdapter` and `EightfoldAdapter`) actually correct?**
  _`Job` has 30 INFERRED edges - model-reasoned connections that need verification._
- **Are the 10 inferred relationships involving `JobStore` (e.g. with `CompanyConfig` and `CompanyResult`) actually correct?**
  _`JobStore` has 10 INFERRED edges - model-reasoned connections that need verification._
- **Are the 12 inferred relationships involving `BaseAdapter` (e.g. with `Job` and `EightfoldAdapter`) actually correct?**
  _`BaseAdapter` has 12 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Adapter registry.  Maps the `ats` string from companies.yaml to the adapter clas`, `Indeed fallback adapter.  ╔═════════════════════════════════════════════════════`, `Return True if we got a Cloudflare or bot-protection response.      Only scans f` to the rest of the system?**
  _301 weakly-connected nodes found - possible documentation gaps or missing edges._