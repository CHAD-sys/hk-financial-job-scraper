# Graph Report - hk-job-scraper  (2026-07-22)

## Corpus Check
- 122 files · ~274,980 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1425 nodes · 2477 edges · 91 communities (75 shown, 16 thin omitted)
- Extraction: 95% EXTRACTED · 5% INFERRED · 0% AMBIGUOUS · INFERRED: 121 edges (avg confidence: 0.53)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `7a73ca10`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- [[_COMMUNITY_Company Config Loader|Company Config Loader]]
- [[_COMMUNITY_Workday Adapter|Workday Adapter]]
- [[_COMMUNITY_Rule-based Enrichment|Rule-based Enrichment]]
- [[_COMMUNITY_eFinancialCareers Adapter|eFinancialCareers Adapter]]
- [[_COMMUNITY_JobStore (SQLite)|JobStore (SQLite)]]
- [[_COMMUNITY_DB Migrations|DB Migrations]]
- [[_COMMUNITY_Base Adapter (ABC)|Base Adapter (ABC)]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Frontend Illustrations|Frontend Illustrations]]
- [[_COMMUNITY_Frontend Job Card|Frontend Job Card]]
- [[_COMMUNITY_FastAPI Backend API|FastAPI Backend API]]
- [[_COMMUNITY_DeepSeek Enricher|DeepSeek Enricher]]
- [[_COMMUNITY_JSONL ImportExport|JSONL Import/Export]]
- [[_COMMUNITY_Cross-Posting Dedup Tests|Cross-Posting Dedup Tests]]
- [[_COMMUNITY_Description Fetcher|Description Fetcher]]
- [[_COMMUNITY_Intelligence Report Gen|Intelligence Report Gen]]
- [[_COMMUNITY_Eightfold Adapter Tests|Eightfold Adapter Tests]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Indeed Parsing|Indeed Parsing]]
- [[_COMMUNITY_JobsDB Adapter|JobsDB Adapter]]
- [[_COMMUNITY_Frontend Deps (package.json)|Frontend Deps (package.json)]]
- [[_COMMUNITY_Full Report Generator|Full Report Generator]]
- [[_COMMUNITY_JobsDB Parsing Tests|JobsDB Parsing Tests]]
- [[_COMMUNITY_LinkedIn Adapter|LinkedIn Adapter]]
- [[_COMMUNITY_Frontend API Client|Frontend API Client]]
- [[_COMMUNITY_Indeed Adapter|Indeed Adapter]]
- [[_COMMUNITY_Enrichment Pipeline Orchestrator|Enrichment Pipeline Orchestrator]]
- [[_COMMUNITY_Longtail LLM Adapter (module)|Longtail LLM Adapter (module)]]
- [[_COMMUNITY_Longtail Adapter (class)|Longtail Adapter (class)]]
- [[_COMMUNITY_Frontend TS Config|Frontend TS Config]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 35|Community 35]]
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
- [[_COMMUNITY_Community 50|Community 50]]
- [[_COMMUNITY_Community 51|Community 51]]
- [[_COMMUNITY_Community 52|Community 52]]
- [[_COMMUNITY_Community 53|Community 53]]
- [[_COMMUNITY_Community 54|Community 54]]
- [[_COMMUNITY_Community 55|Community 55]]
- [[_COMMUNITY_Community 56|Community 56]]
- [[_COMMUNITY_Community 57|Community 57]]
- [[_COMMUNITY_Community 58|Community 58]]
- [[_COMMUNITY_Community 59|Community 59]]
- [[_COMMUNITY_Community 60|Community 60]]
- [[_COMMUNITY_Community 61|Community 61]]
- [[_COMMUNITY_Community 62|Community 62]]
- [[_COMMUNITY_Community 63|Community 63]]
- [[_COMMUNITY_Community 64|Community 64]]
- [[_COMMUNITY_Community 65|Community 65]]
- [[_COMMUNITY_Community 66|Community 66]]
- [[_COMMUNITY_Community 67|Community 67]]
- [[_COMMUNITY_Community 68|Community 68]]
- [[_COMMUNITY_Community 69|Community 69]]
- [[_COMMUNITY_Community 70|Community 70]]
- [[_COMMUNITY_Community 71|Community 71]]
- [[_COMMUNITY_Community 72|Community 72]]
- [[_COMMUNITY_Community 73|Community 73]]
- [[_COMMUNITY_Community 74|Community 74]]
- [[_COMMUNITY_Community 75|Community 75]]
- [[_COMMUNITY_Community 76|Community 76]]
- [[_COMMUNITY_Community 77|Community 77]]
- [[_COMMUNITY_Community 78|Community 78]]
- [[_COMMUNITY_Community 79|Community 79]]
- [[_COMMUNITY_Community 80|Community 80]]
- [[_COMMUNITY_Community 81|Community 81]]
- [[_COMMUNITY_Community 82|Community 82]]
- [[_COMMUNITY_Community 86|Community 86]]
- [[_COMMUNITY_Community 87|Community 87]]
- [[_COMMUNITY_Community 89|Community 89]]

## God Nodes (most connected - your core abstractions)
1. `Job` - 70 edges
2. `BaseAdapter` - 43 edges
3. `enrich()` - 36 edges
4. `JobStore` - 36 edges
5. `_job()` - 30 edges
6. `run()` - 27 edges
7. `IndeedAdapter` - 26 edges
8. `JobsDBAdapter` - 25 edges
9. `LinkedInAdapter` - 25 edges
10. `load_companies()` - 24 edges

## Surprising Connections (you probably didn't know these)
- `Request` --uses--> `WorkdayAdapter`  [INFERRED]
  tests/test_workday.py → hk_jobs/adapters/workday.py
- `Response` --uses--> `WorkdayAdapter`  [INFERRED]
  tests/test_workday.py → hk_jobs/adapters/workday.py
- `Job` --uses--> `Job`  [INFERRED]
  tests/test_schema.py → hk_jobs/schema.py
- `Connection` --uses--> `DeepSeekEnricher`  [INFERRED]
  scripts/reestimate_salaries.py → hk_jobs/enrichers/deepseek.py
- `test_cannot_instantiate_base_directly()` --calls--> `BaseAdapter`  [EXTRACTED]
  tests/test_base_adapter.py → hk_jobs/adapters/base.py

## Import Cycles
- 1-file cycle: `hk_jobs/adapters/efc.py -> hk_jobs/adapters/efc.py`
- 1-file cycle: `hk_jobs/adapters/indeed.py -> hk_jobs/adapters/indeed.py`
- 1-file cycle: `hk_jobs/adapters/jobsdb.py -> hk_jobs/adapters/jobsdb.py`
- 1-file cycle: `hk_jobs/adapters/linkedin.py -> hk_jobs/adapters/linkedin.py`
- 1-file cycle: `hk_jobs/adapters/longtail.py -> hk_jobs/adapters/longtail.py`
- 1-file cycle: `hk_jobs/pipeline.py -> hk_jobs/pipeline.py`
- 1-file cycle: `hk_jobs/storage.py -> hk_jobs/storage.py`

## Hyperedges (group relationships)
- **Adapter-Based Scraping Architecture** — claude_adapter_pattern, claude_canonical_job_schema, claude_fallback_strategy, claude_ats_concept [INFERRED 0.85]
- **Recorded HTML Test Fixtures** — indeed_listing_page1, jobsdb_listing, linkedin_listing_page1 [INFERRED 0.75]
- **Company Source Configuration** — hk_jobs_companies, hk_jobs_companies_longtail, docs_data_model [INFERRED 0.75]
- **** — screenshots_main_board_job_card, screenshots_main_board_company_avatar, screenshots_main_board_job_title, screenshots_main_board_salary_estimate [INFERRED 0.85]
- **** — screenshots_main_board_filter_bar, screenshots_filters_active_selected_chip, screenshots_filters_active_active_filter_pill, screenshots_filters_active_clear_all [INFERRED 0.85]
- **AI salary estimation drives sorting, card chips, and detail badge** — screenshots_salary_sort_salary_sort_control, screenshots_salary_sort_salary_estimate_chip, screenshots_job_detail_estimated_salary_badge [INFERRED 0.85]
- **Hero Section Composition** — screenshots_about_hero_headline, screenshots_about_location_badge, screenshots_about_cta_buttons, screenshots_about_trust_signals [INFERRED 0.85]
- **Metrics & Data Provenance Section** — screenshots_about_stat_cards, screenshots_about_ai_supported, screenshots_about_footer [INFERRED 0.75]

## Communities (91 total, 16 thin omitted)

### Community 0 - "Company Config Loader"
Cohesion: 0.22
Nodes (26): Execute the full scrape-enrich-store pipeline.      Returns the list of per-comp, run(), _args(), _cfg(), _job(), _MockAdapter, Path, Tests for hk_jobs/pipeline.py — pipeline orchestrator. (+18 more)

### Community 1 - "Workday Adapter"
Cohesion: 0.10
Nodes (13): _parse_locations(), Convert an HTML job description to clean plain text.      Block-level tags (p, b, Split Workday's locationsText into a list.      Workday uses pipe-separation for, _strip_html(), Tests for the Workday adapter.  All HTTP is intercepted by a custom httpx transp, test_parse_locations_empty(), test_parse_locations_pipe_separated(), test_parse_locations_single() (+5 more)

### Community 2 - "Rule-based Enrichment"
Cohesion: 0.09
Nodes (47): _detect_employment_type(), _detect_remote_type(), _detect_seniority(), _detect_skills(), _detect_years(), enrich(), enrich_all(), enrich_with_llm() (+39 more)

### Community 3 - "eFinancialCareers Adapter"
Cohesion: 0.08
Nodes (34): _efc_signals(), EfcAdapter, _extract_efc_id(), _map_employment_type(), _parse_iso(), eFinancialCareers adapter (per-company, JSON API).  ╔═══════════════════════════, Fetch one API page; return (job_dicts, total_page_count). Retries throttles., P2/P3 market signals from one eFC job object (only non-empty ones). (+26 more)

### Community 4 - "JobStore (SQLite)"
Cohesion: 0.16
Nodes (19): _job(), Tests for hk_jobs/storage.py — SQLite persistence layer., test_context_manager(), test_insert_two_new_jobs(), test_mark_inactive_deactivates_stale_rows(), test_mark_inactive_leaves_current_rows_active(), test_mark_inactive_only_affects_target_company(), test_mark_inactive_returns_count() (+11 more)

### Community 5 - "DB Migrations"
Cohesion: 0.09
Nodes (21): migrate_to_phase_11(), migrate_to_phase_13(), migrate_to_phase_14(), migrate_to_phase_15(), migrate_to_phase_16(), migrate_to_phase_18(), migrate_to_phase_19(), migrate_to_phase_20() (+13 more)

### Community 6 - "Base Adapter (ABC)"
Cohesion: 0.14
Nodes (12): ABC, BaseAdapter, Abstract base class that every ATS adapter must implement.  An adapter's sole jo, Subclass this once per ATS type (Workday, Eightfold, etc.).      Subclasses set, Args:             company:      Human-readable name, e.g. "HSBC".             co, Fetch all active jobs from this source and return them as Job objects., Call fn(*args, **kwargs) and return its result.          If fn raises for any re, Eightfold AI ATS adapter.  Eightfold is used by HSBC, Hang Seng Bank, and HSBC L (+4 more)

### Community 7 - "Community 7"
Cohesion: 0.15
Nodes (12): LinkedInAdapter, Scrapes one employer's public guest job listings from linkedin.com.      Plain h, Job, adapter(), Single-page adapter serving the page-1 fixture for every fetch., test_authwall_returns_empty_list(), test_block_status_returns_empty_list(), test_geo_id_included_in_url() (+4 more)

### Community 8 - "Frontend Illustrations"
Cohesion: 0.09
Nodes (15): fetchStats(), CoverageRadar(), DataFlow(), DATAFLOW_OUTS, DATAFLOW_SOURCES, GROWTH_BAR_HEIGHTS, GrowthBars(), SkylineTrend() (+7 more)

### Community 9 - "Frontend Job Card"
Cohesion: 0.13
Nodes (20): fetchJobDetail(), CardFooter(), CardHeader(), JobCard(), MetaRow(), SectorColor, JobDetailModal(), MetaGrid() (+12 more)

### Community 10 - "FastAPI Backend API"
Cohesion: 0.14
Nodes (26): _build_where(), ExperienceRange, FiltersResponse, get_db(), get_filters(), get_job(), get_stats(), JobDetail (+18 more)

### Community 11 - "DeepSeek Enricher"
Cohesion: 0.06
Nodes (44): DeepSeekEnricher, _fmt_band(), _fmt_k(), _load_salary_reference(), DeepSeek LLM enricher — v4: adds English translation of Chinese postings.  v1: t, Enrich jobs sequentially. Callers wrap this in ThreadPoolExecutor for parallelis, Single API call. Raises on error., Render the JSON anchor ladders into a compact prompt block (high tier → low). (+36 more)

### Community 12 - "JSONL Import/Export"
Cohesion: 0.16
Nodes (14): _cluster_by_title(), _preferred_apply_url(), _primary_rowid(), Row, SQLite persistence layer.  Design principles:   - SQL is written to be Postgres-, Return the URL of the highest-priority source among cross-posted copies., rowid of the copy to display (highest display priority) among a group., Word set of a title (lowercased, punctuation folded) for overlap scoring. (+6 more)

### Community 13 - "Cross-Posting Dedup Tests"
Cohesion: 0.11
Nodes (27): _job(), Tests for Phase 19 cross-source apply routing:   - JobStore.reconcile_cross_post, The real case that drove matches to zero: same role, but eFC says "Hong Kong", Different word order / punctuation for the same role still matches., Fuzzy match must NOT collapse different seniority levels of the same job., Titles that merely share one common word are not merged., One card per cross-posted role: JobsDB copy is primary (rich), eFC hidden., A role on only one board is always displayed. (+19 more)

### Community 14 - "Description Fetcher"
Cohesion: 0.22
Nodes (9): DescriptionFetcher, FetchResult, Connection, Row, Persist one batch of results. Returns (written, skipped, failed).          Also, Repair mislabeled company fields for existing JobsDB rows.          Calls the li, Calls ATS JSON detail APIs to populate description_raw / description_clean., Namespace (+1 more)

### Community 15 - "Intelligence Report Gen"
Cohesion: 0.13
Nodes (11): build_styles(), fmt_date(), fmt_skills(), group_by_company(), load_data(), main(), Generate a comprehensive PDF: architecture overview + all 1,592 jobs. Output: ou, ReportDoc (+3 more)

### Community 16 - "Eightfold Adapter Tests"
Cohesion: 0.06
Nodes (15): _ef_signals(), EightfoldAdapter, P2/P3 market signals from one Eightfold position (only non-empty ones)., Fetches jobs from Eightfold AI's public JSON API.      'tenant' is the subdomain, Public entry point — wraps _fetch_all in _safe_fetch for error isolation., Client, Job, main() (+7 more)

### Community 17 - "Community 17"
Cohesion: 0.13
Nodes (15): CompanyConfig, Job, Return a 12-character fingerprint that identifies this job posting.          Why, JobStore, datetime, Manages a SQLite database of job postings.      Usage:         store = JobStore(, Soft-delete jobs for a company that were NOT seen in this run.          After we, Close the underlying database connection. (+7 more)

### Community 18 - "Indeed Parsing"
Cohesion: 0.14
Nodes (16): _epoch_ms_to_dt(), _extract_signals(), _parse_listing_json(), Indeed fallback adapter.  ╔═════════════════════════════════════════════════════, Convert an Indeed epoch-milliseconds timestamp to a UTC datetime., Extract job cards from an Indeed company listing page's embedded JSON.      The, Pull P2/P3 market signals out of one Indeed mosaic card (only non-empty ones)., datetime (+8 more)

### Community 19 - "JobsDB Adapter"
Cohesion: 0.11
Nodes (17): _is_challenge(), JobsDBAdapter, Return True if we got a Cloudflare or bot-protection response.      Only scans f, Scrapes listing pages for one company from hk.jobsdb.com.      Uses Scrapling's, Fetch url and return (http_status, html_string).          Single mockable seam —, Fetch one listing page, retrying on transient failures.          Two kinds of tr, For plain-listing companies, drop cards whose advertiser isn't accepted., Job (+9 more)

### Community 20 - "Frontend Deps (package.json)"
Cohesion: 0.08
Nodes (24): dependencies, lucide-react, react, react-dom, react-router-dom, tailwindcss, @tailwindcss/vite, devDependencies (+16 more)

### Community 21 - "Full Report Generator"
Cohesion: 0.14
Nodes (13): Drawing, bar_chart(), by_category(), fmt_exp(), fmt_salary(), fmt_skills(), fmt_source(), FullReport (+5 more)

### Community 22 - "JobsDB Parsing Tests"
Cohesion: 0.09
Nodes (22): _parse_listing_html(), Extract job cards from a JobsDB company listing page.      data-automation value, Tests for the JobsDB fallback adapter.  All HTTP is intercepted via monkeypatchi, Fix A: company is extracted from the card, not stamped from config., Card 3 has no advertiser node — must fall back to config company., Listing-only: only 1 URL should be fetched (the listing page)., Without detail pages, descriptions are empty strings — expected., Card 1 has data-automation='jobAdvertiser' — must be extracted. (+14 more)

### Community 23 - "LinkedIn Adapter"
Cohesion: 0.13
Nodes (11): _parse_cards(), Extract job cards from a LinkedIn guest-search HTML fragment.      Each card is, Tests for the LinkedIn guest-jobs fallback adapter.  All HTTP is intercepted by, Fallback: extract the numeric id from the /jobs/view/ link if urn is missing., test_parse_card_fields(), test_parse_card_posted_at(), test_parse_card_url_stripped_of_tracking(), test_parse_cards_empty_html() (+3 more)

### Community 24 - "Frontend API Client"
Cohesion: 0.11
Nodes (21): countActiveFilters(), DEFAULT_FILTERS, fetchFilters(), fetchJobs(), filtersToSearchParams(), Job, JobDetail, JobListResponse (+13 more)

### Community 25 - "Indeed Adapter"
Cohesion: 0.11
Nodes (17): IndeedAdapter, Scrapes the employer-scoped listing pages for one company from hk.indeed.com., Job, adapter(), Page 2 repeats one card (ccc333) — output must contain 5 unique jobs, not 6., If a page returns only jobs we've seen, pagination stops (no spin to max_pages)., A login/verify wall must yield [] and never raise — we do not cross it., Single-page adapter serving page-1 fixture for every fetch. (+9 more)

### Community 26 - "Enrichment Pipeline Orchestrator"
Cohesion: 0.16
Nodes (16): EnrichmentPipeline, CompanyResult, _log_trend_changes(), _NullLock, _print_report(), datetime, Pipeline orchestrator.  Reads companies.yaml, instantiates the right adapter for, Fetch, enrich, and store jobs for one company. Returns a CompanyResult.      db_ (+8 more)

### Community 27 - "Longtail LLM Adapter (module)"
Cohesion: 0.07
Nodes (34): LongtailAdapter, _needs_browser(), _parse_posted_date(), Longtail adapter — LLM-based extraction for medium/boutique HK companies that ar, Best-effort parse of the LLM's posted_date string, with sanity bounds.     Retur, Scrapling page_action for click-to-reveal careers pages (e.g. Pioneer): the job, LLM-extraction adapter for one boutique company's careers page., Static fetch via httpx → (status, html); (0, '') on error. Mockable seam. (+26 more)

### Community 28 - "Longtail Adapter (class)"
Cohesion: 0.22
Nodes (13): candidate_slugs(), extract_company_ids(), _fetch(), _hk_count(), main(), LinkedIn company-id resolver — extend the LinkedIn source to firms (run locally), Pull ALL candidate numeric company ids from a company page, most-likely first., HK job count for f_C=<cid> via the real adapter (0 on failure/none). (+5 more)

### Community 29 - "Frontend TS Config"
Cohesion: 0.11
Nodes (18): compilerOptions, allowImportingTsExtensions, erasableSyntaxOnly, jsx, lib, module, moduleDetection, moduleResolution (+10 more)

### Community 30 - "Community 30"
Cohesion: 0.18
Nodes (18): _classify(), _extract_cards(), _extract_mosaic_cards(), _fetch(), _find_embedded_json(), _ldjson_jobs(), main(), probe() (+10 more)

### Community 31 - "Community 31"
Cohesion: 0.12
Nodes (17): CompanyResult, date, calculate_hiring_velocity(), export_trends_jsonl(), get_all_trends(), get_company_trend(), print_trends_report(), print_velocity_report() (+9 more)

### Community 32 - "Community 32"
Cohesion: 0.24
Nodes (17): discover_one(), _dns_ok(), domain_from_website(), jobsdb_slugs(), load_known_names(), main(), _match_key(), _name_core() (+9 more)

### Community 33 - "Community 33"
Cohesion: 0.18
Nodes (13): _BrokenAdapter, _EchoAdapter, Job, Tests for hk_jobs/adapters/base.py., test_cannot_instantiate_base_directly(), test_client_has_browser_user_agent(), test_client_includes_zh_hk_accept_language(), test_concrete_subclass_stores_fields() (+5 more)

### Community 34 - "Community 34"
Cohesion: 0.06
Nodes (33): AI Enrichment & Salary Calibration, Architecture, Companies Covered, Contents, Daily Automation, Data Sources, Database Schema, Delivery Surfaces (+25 more)

### Community 35 - "Community 35"
Cohesion: 0.12
Nodes (16): compilerOptions, allowImportingTsExtensions, erasableSyntaxOnly, lib, module, moduleDetection, noEmit, noFallthroughCasesInSwitch (+8 more)

### Community 36 - "Community 36"
Cohesion: 0.20
Nodes (15): Any, Shared HTTP utilities used across adapters.  with_retry() wraps a single HTTP ca, Call fn() up to max_attempts times, retrying on transient HTTP errors.      Retr, with_retry(), Tests for hk_jobs/http_utils.py — retry-with-backoff helper., test_does_not_retry_403(), test_does_not_retry_404(), test_raises_after_max_attempts_429() (+7 more)

### Community 37 - "Community 37"
Cohesion: 0.23
Nodes (7): Public entry point — wraps _fetch_all in _safe_fetch for error isolation., Fetches jobs from Workday's internal JSON API.      Each company that uses Workd, WorkdayAdapter, Client, Job, main(), Live smoke-test for the Workday adapter.  Run this LOCALLY (not in CI) to verify

### Community 38 - "Community 38"
Cohesion: 0.12
Nodes (26): jobs_from_jsonl(), jobs_to_jsonl(), Canonical Job schema.  Every adapter — regardless of source ATS — maps its raw d, Write a list of Job objects to a newline-delimited JSON file (one job per line)., Read a JSONL file written by jobs_to_jsonl and return Job objects., _make_job(), Job, Tests for hk_jobs/schema.py — the canonical Job model. (+18 more)

### Community 39 - "Community 39"
Cohesion: 0.14
Nodes (13): FiltersResponse, JobFilters, FilterBar(), Props, SECTORS, ApplicantsFields(), ExpFields(), FilterRow() (+5 more)

### Community 40 - "Community 40"
Cohesion: 0.18
Nodes (15): _ensure_pb_fields(), _ensure_pb_indexes(), _field_def(), main(), _map_row(), _pb_is_running(), Connection, Row (+7 more)

### Community 41 - "Community 41"
Cohesion: 0.24
Nodes (14): build_story(), date_str(), detect_sector(), load_jobs(), loc_str(), main(), make_header_footer(), make_table() (+6 more)

### Community 42 - "Community 42"
Cohesion: 0.17
Nodes (14): migrate_to_phase_12(), migrate_to_phase_17(), Add the category column to the jobs table.      Holds a boutique company's busin, Create job_enrichments table if it doesn't already exist., Email notifications for pipeline events.  Sends two types of emails:   - Failure, Query today's stats and send a summary email., Send an immediate alert when the pipeline raises an exception., send_daily_summary() (+6 more)

### Community 43 - "Community 43"
Cohesion: 0.67
Nodes (3): Hero Illustration (Layered Cards), Isometric Stacked Card Motif, Purple Gradient Accent

### Community 44 - "Community 44"
Cohesion: 0.06
Nodes (33): Adapter Abstraction (fetch_jobs -> list[Job]), DeepSeek AI Enrichment, AI enrichment output, Architecture (the shape of the solution), Applicant Tracking System (ATS), Canonical Job Schema, CLAUDE.md — HK Financial Job Scraper, Core domain knowledge (read this — it drives every design decision) (+25 more)

### Community 45 - "Community 45"
Cohesion: 0.20
Nodes (10): _parse_listing_date(), JobsDB fallback adapter.  ╔═════════════════════════════════════════════════════, Parse a JobsDB relative date string into a UTC datetime.      Live page formats, # IMPORTANT: these selectors could not be verified against live Cloudflare-, datetime, test_parse_listing_date_days_ago(), test_parse_listing_date_empty(), test_parse_listing_date_hours_ago() (+2 more)

### Community 46 - "Community 46"
Cohesion: 0.18
Nodes (8): _is_challenge(), Fetch url and return (http_status, html_string).          Single mockable seam —, page 1 → base URL; page N → ?start=(N-1)*20 (steps of 20, never 10)., Fetch one listing page, retrying on transient failures.          Mirrors the Job, Return True if we got a Cloudflare or bot-protection response.      Only scans f, test_is_challenge_false_on_large_content_page(), test_is_challenge_on_403(), test_is_challenge_on_short_challenge_page()

### Community 47 - "Community 47"
Cohesion: 0.30
Nodes (10): build(), detect_sector(), fmt_num(), fmt_pct(), load(), main(), make_header_footer(), make_table() (+2 more)

### Community 48 - "Community 48"
Cohesion: 0.20
Nodes (7): _is_authwall(), Fetch url and return (http_status, html_string).          Single mockable seam —, Fetch one listing page, retrying on transient failures / block responses., True if LinkedIn gated us behind sign-in / a rate-limit block., test_authwall_false_on_content(), test_authwall_on_block_statuses(), test_authwall_on_signin_text()

### Community 49 - "Community 49"
Cohesion: 0.22
Nodes (7): adapter(), _MockTransport, Request, Response, Serves fixture data without touching the network., WorkdayAdapter wired to mock transport; detail sleep removed., test_no_detail_fetch_skips_get()

### Community 50 - "Community 50"
Cohesion: 0.40
Nodes (5): _classify_batch(), Tech-role filter — keep the board FINANCE-only by dropping hard tech/IT roles., Classify any NEW tech-candidate titles, then soft-delete active jobs whose     t, Return indices (into `titles`) the model labels TECH., run_tech_filter()

### Community 51 - "Community 51"
Cohesion: 0.13
Nodes (17): load_companies(), Parse companies.yaml and return a list of validated CompanyConfig objects., Path, Tests for hk_jobs/config.py — companies.yaml loader and validator., A company may be scraped from more than one source under the SAME slug (e.g., Sanity-check we have a reasonable mix — not all jobsdb fallbacks., test_adapter_distribution(), test_disabled_entry_still_validated() (+9 more)

### Community 52 - "Community 52"
Cohesion: 0.24
Nodes (8): Board, BOARDS, BoardTag(), normalise(), ORDER, OWN_SITE, SourceBadges(), tint()

### Community 53 - "Community 53"
Cohesion: 0.31
Nodes (8): _advertiser_accepted(), _normalize_advertiser_tokens(), Lowercase, strip punctuation + corporate-suffix noise, return token set., True if `advertiser` matches any accepted name.      Match is token-subset in ei, _acc(), test_allowlist_accepts_legal_entity_variants(), test_allowlist_empty_advertiser_rejected(), test_allowlist_rejects_cross_advertisers()

### Community 54 - "Community 54"
Cohesion: 0.40
Nodes (5): _extract_source_id(), Extract trailing numeric job ID from a JobsDB URL; fall back to full URL., test_extract_source_id_legacy_suffix(), test_extract_source_id_modern_url(), test_extract_source_id_no_number_falls_back()

### Community 55 - "Community 55"
Cohesion: 0.12
Nodes (12): _extract_mosaic_json(), Pull the `mosaic-provider-jobcards` JSON object out of the page.      Indeed ass, Tests for the Indeed fallback adapter.  All HTTP is intercepted by monkeypatchin, Card company is blank on employer pages → stamp the configured company name., Listing-only: exactly one URL fetched (the page-1 listing)., The brace-matcher must not stop at a nested '}' inside the object., test_extract_mosaic_json_absent_returns_none(), test_extract_mosaic_json_brace_match_survives_nested_braces() (+4 more)

### Community 56 - "Community 56"
Cohesion: 0.25
Nodes (8): _clean_view_url(), _extract_job_id(), _parse_date(), LinkedIn fallback adapter (public *guest* jobs API — no login).  ╔══════════════, Pull the numeric job id from the card's entity-urn, falling back to its link., Read the ISO date from the card's <time datetime="YYYY-MM-DD"> element., Strip tracking query params from a /jobs/view/ link., datetime

### Community 57 - "Community 57"
Cohesion: 0.33
Nodes (5): plugins, rules, react/only-export-components, react/rules-of-hooks, $schema

### Community 58 - "Community 58"
Cohesion: 0.67
Nodes (3): _map_time_type(), Map Workday's timeType string to our canonical employment_type value., test_map_time_type()

### Community 59 - "Community 59"
Cohesion: 0.47
Nodes (5): export(), _flatten(), main(), Export the jobs database to a single CSV (a shareable, spreadsheet-friendly copy, A JSON list stored as text -> 'a; b; c'; leave plain strings/None alone.

### Community 60 - "Community 60"
Cohesion: 0.40
Nodes (5): _is_login_wall(), True if the page is a login / human-verification wall we must not cross., The benign header 'Sign in' link (secure.indeed.com) must NOT read as a wall., test_login_wall_detected(), test_login_wall_not_triggered_by_signin_link()

### Community 61 - "Community 61"
Cohesion: 0.50
Nodes (4): _classify_batch(), main(), Soft-delete "hard tech" roles from jobs.db, using DeepSeek to decide.  This job, Return the set of indices (into `titles`) the model labels TECH.

### Community 62 - "Community 62"
Cohesion: 0.18
Nodes (11): _fetch_eightfold_description(), _fetch_indeed_description(), _fetch_jobsdb_description(), _fetch_linkedin_description(), _fetch_workday_description(), Fetch full job descriptions from ATS JSON APIs.  Why this is a separate step: th, Fetch one LinkedIn job's description HTML via the guest jobPosting endpoint., Fetch one Indeed job's description HTML from its viewjob detail page.      Indee (+3 more)

### Community 65 - "Community 65"
Cohesion: 0.07
Nodes (26): Accessibility Compliance, Anti-Patterns (from ui-ux-pro-max), Brand Accent, Color Tokens, Component Patterns, Elevation / Shadow Scale, FinEx Careers — Design System, Fonts (+18 more)

### Community 70 - "Community 70"
Cohesion: 0.24
Nodes (11): candidate_slugs(), _hk_count(), main(), Indeed /cmp slug resolver — extend the Indeed source to ALL firms (run locally)., How many returned jobs look HK-based (hk.indeed.com is HK-scoped anyway)., Try candidate slugs for one firm; return the first that yields HK jobs., ['goldman','sachs'] → 'Goldman-Sachs' (Indeed uses Title-Case-Hyphen)., Best-effort /cmp slug guesses for a company name, most-likely first.      Indeed (+3 more)

### Community 73 - "Community 73"
Cohesion: 0.18
Nodes (9): _job_to_row(), Any, Job, Insert or update a batch of jobs.          Returns (inserted, updated) counts. A, Return summary counts for monitoring and reporting.          Shape:, Write all active jobs to a JSONL file, sorted by company then title.          Re, Flatten a Job into a dict of SQLite-compatible scalar values., Reconstruct a Job from a SQLite row (inverse of _job_to_row). (+1 more)

### Community 75 - "Community 75"
Cohesion: 0.25
Nodes (7): CompanyConfig, Company configuration loader.  Reads companies.yaml and returns validated Compan, Raise ValueError with the company name if the config is invalid., One validated entry from companies.yaml., Instantiate and return the adapter for this company.          Returns a BaseAdap, _validate(), test_build_adapter_returns_correct_type()

### Community 78 - "Community 78"
Cohesion: 0.32
Nodes (7): Path, _field_of(), main(), Merge resolved Indeed entries into companies.yaml — safely, with validation.  Ta, Split resolver output into individual '  - name: …' entry blocks (drop banner)., # NOTE: read the target file (args.yaml), not the default, so --yaml works., _split_blocks()

### Community 79 - "Community 79"
Cohesion: 0.40
Nodes (4): parse_detail_signals(), Extract P2 market signals from a LinkedIn guest job-detail page.      Returns {a, _fetch(), Fetch LinkedIn detail-page market signals (applicant count, reposted) and merge

### Community 80 - "Community 80"
Cohesion: 0.40
Nodes (5): _parse_args(), test_company_flag_still_accepted_by_parse_args(), test_only_flag_accepted_by_parse_args(), test_only_flag_accepts_multiple_slugs(), test_verbose_flag_parsed()

## Knowledge Gaps
- **164 isolated node(s):** `Surface`, `Ink (Text)`, `Brand Accent`, `Semantic`, `Fonts` (+159 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **16 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Job` connect `Community 17` to `Company Config Loader`, `Rule-based Enrichment`, `eFinancialCareers Adapter`, `JobStore (SQLite)`, `Base Adapter (ABC)`, `Community 7`, `FastAPI Backend API`, `JSONL Import/Export`, `Cross-Posting Dedup Tests`, `Eightfold Adapter Tests`, `Indeed Parsing`, `JobsDB Adapter`, `Indeed Adapter`, `Longtail LLM Adapter (module)`, `Community 33`, `Community 37`, `Community 38`, `Community 45`, `Community 56`, `Community 73`, `Community 81`?**
  _High betweenness centrality (0.239) - this node is a cross-community bridge._
- **Why does `JobStore` connect `Community 17` to `Company Config Loader`, `JobStore (SQLite)`, `Community 73`, `JSONL Import/Export`, `Cross-Posting Dedup Tests`, `Description Fetcher`, `Enrichment Pipeline Orchestrator`?**
  _High betweenness centrality (0.076) - this node is a cross-community bridge._
- **Why does `EnrichmentPipeline` connect `Enrichment Pipeline Orchestrator` to `Community 42`, `DeepSeek Enricher`, `Description Fetcher`?**
  _High betweenness centrality (0.063) - this node is a cross-community bridge._
- **Are the 43 inferred relationships involving `Job` (e.g. with `BaseAdapter` and `EfcAdapter`) actually correct?**
  _`Job` has 43 INFERRED edges - model-reasoned connections that need verification._
- **Are the 24 inferred relationships involving `BaseAdapter` (e.g. with `Job` and `EfcAdapter`) actually correct?**
  _`BaseAdapter` has 24 INFERRED edges - model-reasoned connections that need verification._
- **Are the 12 inferred relationships involving `JobStore` (e.g. with `CompanyConfig` and `CompanyResult`) actually correct?**
  _`JobStore` has 12 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Surface`, `Ink (Text)`, `Brand Accent` to the rest of the system?**
  _446 weakly-connected nodes found - possible documentation gaps or missing edges._