# Plan — LinkedIn Posts "Secret Market" Section

> Status: **APPROVED PLAN — not yet built.** Work one phase at a time (LP-0 → LP-6),
> stop for review after each, per the repo working agreement.
> Decisions below were made explicitly by the project owner on 2026-07-19.

## 1. Goal & thesis

Research shows a meaningful share of vacancies never reach job boards: they live
only as **LinkedIn posts by recruiters and headhunters** ("my client, a top-tier
hedge fund, seeks…"). We add a new pipeline source that captures those posts for
the HK financial sector, converts them into canonical `Job` rows, and surfaces
them on the board as a dedicated **"secret market"** section.

This is NOT the LinkedIn Jobs section (already covered by `adapters/linkedin.py`).
This is the *content feed*: posts authored by people.

## 2. Decision record (owner-confirmed)

| # | Decision | Choice |
|---|----------|--------|
| 1 | Ingestion philosophy | Capture ALL job-bearing posts; dedupe downstream. "Hidden" is a computed flag, not an ingestion filter |
| 2 | Discovery | Hybrid: daily watchlist polling + weekly keyword post-search that feeds NEW recruiters into the watchlist (+ $0 Google-index side channel experiment) |
| 3 | Watchlist tiers | Agency recruiters, independent headhunters, agency company pages. NO in-house TA (duplicate signal vs own-ATS scraping) |
| 4 | Bootstrap | Three-way: (a) search-driven harvest of active posters from first runs, (b) manual list enumerated on the boss's side, (c) known agency headhunters |
| 5 | Vendor | **DECIDED (LP-0 complete, 2026-07-19): Apify/HarvestAPI.** `linkedin-profile-posts` for watchlist polling, `linkedin-post-search` for discovery, both $2/1k results. Piloterr disqualified — its live endpoint catalog has no post-discovery endpoint (`post/info` only enriches a known post ID). See `docs/BAKEOFF_RESULTS.md`. Total bake-off cost: $0.21 |
| 6 | Budget | **$30/month cap** steady state |
| 7 | Confidential employers | `company = "Confidential via {recruiter}"`, `company_slug = "confidential-{recruiter-slug}"`, LLM `employer_hint` in `board_signals`. Never guess the employer, never drop the post |
| 8 | Quality bar | Two-tier: ALL scraped posts land in raw `linkedin_posts` table (replayable); promotion to `jobs` requires concrete title + HK-plausible location + stored confidence |
| 9 | UI shape | Dedicated section, PLUS contextual sub-section inside filtered views (e.g. "urgently hiring" filter also shows matching secret-market jobs as a distinct block) |
| 10 | Recruiter emails | In scope, shown on cards. Watchlist recruiters only (~$1–2 one-time via HarvestAPI email search) |
| 11 | Pilot gate | 3–4 days on ~30 bootstrap recruiters → report {promoted jobs, % truly hidden, precision spot-check} → boss decides go/no-go for v1 |
| 12 | Metrics permanence | The same 3 metrics are computed on EVERY daily run forever (see §7); the v1 decision still uses only the pilot window |

Defaults taken (owner did not object):
- Cadence: daily, inside `daily_run.sh`
- Posts rank LOWEST in `_SOURCE_PRIORITY` — apply-routing always prefers a real ATS/board listing when the same vacancy exists there
- Config file `recruiters.yaml` mirrors the `companies.yaml` convention

## 3. Legal & privacy posture

Same **prototype-only** posture as the JobsDB / Indeed / LinkedIn-guest adapters,
with two changes — document both in the module docstring banner:

1. **Vendor-mediated access.** We call a paid third-party API (Apify/Piloterr);
   the vendor performs the LinkedIn access. This does not launder the ToS issue —
   LinkedIn's terms prohibit scraping regardless of who runs the browser — but it
   keeps OUR code on the same "no login, no credentials, no authwall" line the
   repo already draws. DIY authenticated scraping was considered and REJECTED
   (legal escalation + anti-bot arms race + economically irrational at our volume).
2. **Personal data (PDPO).** Recruiter names, profile URLs, and (decision #10)
   harvested emails are personal data. Mitigations: internal boss-facing board,
   attribution always links back to the original public post, purpose is limited
   to contacting recruiters about mandates they publicly advertised, and rows are
   soft-deleted per repo convention.

**CLAUDE.md amendment required** (part of LP-2): the tech-stack rule
"NO paid services, NO aggregator APIs" is consciously overturned FOR THIS SOURCE
ONLY, by owner decision, with the $30/mo cap written next to it.

## 4. Architecture

```
recruiters.yaml ──► posts_fetcher.py ──► linkedin_posts (raw table, tier 1)
 (watchlist)         (vendor API)              │
                                               ▼
weekly search ──► discovery run ──► post_extractor.py (DeepSeek: classify → extract)
 (new authors → review → yaml)                 │  promotion gate: title + HK location
                                               ▼
                                        jobs table (tier 2, source='linkedin_posts')
                                               │  reconcile_cross_posted()
                                               ▼
                                   hidden flag + apply routing (posts = lowest priority)
                                               │
                                               ▼
                                  PocketBase mirror ──► webapp (secret-market section)
```

New components (all inside `hk_jobs/`, one responsibility per file):
- `posts/vendor_client.py` — thin client for the winning vendor; retries, cost logging
- `posts/fetcher.py` — polls watchlist feeds (last-24h posts) + weekly search runs
- `posts/extractor.py` — two-stage LLM: (1) is this a job post? (2) extract fields.
  Reuses `llm_client.py` / DeepSeek; prompt stored alongside, replayable over raw table
- `posts/promote.py` — promotion gate, confidential-identity construction, Job mapping
- `recruiters.yaml` — watchlist config: slug, name, tier (agency|independent|agency_page),
  profile URL, added_by (search|manual|roster), active flag
- Migration: `linkedin_posts` raw table + `recruiter_email` columns

Schema mapping notes:
- `source="linkedin_posts"`, `source_id = post URN/ID`, `url = post permalink`
- `source_tier = "social"` (new value; queryable like 'boutique')
- `board_signals` carries: `recruiter_name`, `recruiter_profile_url`, `recruiter_email`,
  `employer_hint`, `engagement` (likes/comments), `post_created_at`
- `extraction_confidence` from the extractor (as longtail already does)
- Named-employer posts use the REAL company slug so `dedup_hash()` matches board
  listings; confidential posts use the recruiter-based slug (dedup then only
  collapses the recruiter's own reposts — intended)

## 5. Phases

### LP-0 — Vendor bake-off — ✅ COMPLETE (2026-07-19, cost $0.21)
- Piloterr disqualified by catalog inspection before spending on a live test — no
  post-discovery endpoint exists (see `docs/BAKEOFF_RESULTS.md`)
- Apify `linkedin-profile-posts` tested against 10 real HK finance recruiters
  (sourced from Hays/Selby Jennings/Morgan McKinley public team pages): 90 posts,
  8/10 profiles yielded content, `query.targetUrl` correctly links results back to
  watchlist entries, repost attribution is correct, 62% job-signal keyword rate
- Apify `linkedin-post-search` tested against 3 discovery queries: 14 results,
  ~65–70% true precision on manual read — confirms LP-3's two-stage LLM classifier
  is necessary (keyword matching alone overstates precision)
- **Decision: Apify/HarvestAPI wins.** Full results in `docs/BAKEOFF_RESULTS.md`

### LP-1 — Watchlist bootstrap (~2 days, parallel with boss's manual list)
- Run one-off searches over last 30 days; collect authors of genuine job posts;
  rank by posting frequency; human-review top ~50
- Merge with boss-side manual list + known agency headhunters
- Deliverable: `recruiters.yaml` with ~30 ACTIVE profiles for the pilot (cap keeps
  pilot cost trivial); the rest staged inactive
- **STOP for review**

### LP-2 — Ingestion backbone — ✅ BUILT (2026-07-22), pending your review
- Migration (`migrate_to_phase_26`): `linkedin_posts` raw table (post_urn PK,
  recruiter_slug, source_run, author, text, engagement, fetched_at,
  vendor_payload_json, extraction_status), plus `recruiter_fetch_state`
  (per-recruiter last_fetched_at watermark) and `vendor_costs` (spend ledger)
- `hk_jobs/posts/vendor_client.py` — Apify/HarvestAPI client for both actors
  (`linkedin-profile-posts`, `linkedin-post-search`), single mockable seam,
  retries transient failures up to 2 attempts (not the repo's usual 3, since
  every retry on a paid vendor call is billable), never retries a clean 4xx
- `hk_jobs/posts/fetcher.py` — watchlist poll uses `since = max(last_fetched_at,
  now - 48h floor)` instead of a fixed last-24h window, so a missed/delayed
  cron run doesn't silently create a gap; weekly discovery search uses the
  same 3 seed queries validated in the LP-0 bake-off; per-recruiter/per-query
  failure isolation (one bad entry never stops the rest)
- `hk_jobs/posts/budget.py` — $30/mo hard cap is self-enforced (new Apify
  calls refused once month-to-date spend hits the cap, not just logged),
  warns at $25
- `hk_jobs/recruiters_config.py` — unlike `companies.yaml`'s crash-loud
  validation, a malformed `recruiters.yaml` entry is skipped + logged, not
  fatal — chosen because this list is actively growing (LP-1 bootstrap →
  LP-6 discovery queue) and one bad row shouldn't block ~30 others' daily fetch
- CLAUDE.md amendment done (paid-service exception, scoped to `hk_jobs/posts/`
  only, cap stated explicitly)
- `--fetch-posts` / `--posts-discovery` wired into `daily_run.sh` as
  non-fatal phases (5 / 5b, discovery Mondays only) after the PocketBase sync
- 30 tests, recorded fixtures from real LP-0 bake-off data (no live calls)
- **Live-verified 2026-07-22** via `scripts/try_linkedin_posts_live.py`: both
  actors confirmed working against the real Apify API. `linkedin-profile-posts`
  (`targetUrls`) returned 3 real posts for Gillian Lam, exact field shapes as
  coded. `linkedin-post-search` (`searchQueries`) returned 3 results for a
  compliance/private-bank query — one genuine hit, one empty-content company
  post, one hashtag-only post, which is exactly the ~65–70% precision problem
  the LP-0 bake-off predicted and LP-3's classifier exists to solve. Total
  verification cost: $0.012.
- Watchlist grown to 47 recruiters (28 LP-1 bootstrap + 19 boss-supplied
  2026-07-22; one duplicate URL — Grace Su/`ida1101` — correctly skipped)
- **STOP for review** — code + live calls verified; not yet run against the
  full 47-recruiter watchlist or wired into a live daily_run.sh cron

### LP-3 — Extraction & promotion (~2–3 days)
- `extractor.py`: stage 1 classifier (job post? y/n + confidence), stage 2 field
  extraction (title, employer or hint, location, seniority, salary if stated, skills)
- `promote.py`: gate (concrete title + HK-plausible location), confidential identity
  rule, Job construction, insert via existing `JobStore`
- Add `linkedin_posts` as lowest rung of `_SOURCE_PRIORITY`; verify
  `reconcile_cross_posted()` marks board-duplicated posts (this yields the
  **hidden flag**: promoted post-job with no cross-source match = truly hidden)
- Metrics module (§7) wired into the run summary
- **STOP for review**

### LP-4 — PILOT — ✅ BUILT + CONNECTED (2026-07-22), gate compressed by owner decision
- `hk_jobs/posts/pilot_report.py` + `--posts-pilot-report [PATH]`: the one-page
  deliverable — promoted count, % truly hidden, cost so far (real Apify spend
  from `vendor_costs`; DeepSeek call count stated, NOT a fabricated dollar
  figure — no cost tracking exists for DeepSeek anywhere in this codebase),
  extrapolated monthly, and a random sample of promoted jobs sized for a human
  manual precision spot-check (this module cannot perform that read itself)
- `daily_run.sh` phases 5/5b/5c (fetch / weekly discovery / promote) are now
  driven by a real crontab entry (`0 18 * * *`, installed 2026-07-22) — the
  full LP-2+LP-3 pipeline runs unattended daily against real recruiters.yaml
  and real Apify/DeepSeek spend from now on
- Owner decision (2026-07-22): the plan's original "3-4 days elapsed, then
  boss gate before LP-5" ritual is explicitly COMPRESSED — build proceeded
  straight into LP-5 after a single manual pilot run (see below), not a
  multi-day elapsed window. Recorded here for the audit trail; not a plan
  violation, a conscious amendment by the person the gate exists to serve
- First real run: 47/47 recruiters, 29 posts, 17 promoted, 100% truly hidden
  on this small sample, $0.058 Apify spend, 28 DeepSeek calls. Full report:
  `data/lp4_pilot_report_2026-07-22.md` (gitignored, local only — see caveat
  in the file: extrapolated monthly cost from a <1-day window is noisy,
  don't read $49.96/mo as a real steady-state number)

### LP-5 — UI + PocketBase (post-GO, ~3–4 days)
- PB mirror: new fields/collection via `sync_pocketbase.py`
- Webapp: dedicated "Secret Market" section (recruiter attribution, employer or
  hint, link to original post, "DM to apply" CTA, recruiter email on card)
- Contextual injection: active filters (e.g. urgently-hiring) render a distinct
  secret-market sub-section alongside main results — never intermixed rows
- One-time email harvest for watchlist recruiters (~$1–2), refresh quarterly

### LP-6 — Steady state (post-GO)
- Scale watchlist toward ~100 active profiles (stay under $30/mo; cost counter
  alerts at $25)
- Weekly discovery search appends CANDIDATE recruiters to a review queue —
  human approves before they enter `recruiters.yaml`
- $0 experiment: Google Custom Search (`site:linkedin.com/posts`) as a
  supplementary discovery channel; keep only if it finds posts the vendor missed
- Daily metrics (§7) appended to the daily report artifacts

## 6. Cost model (verified 2026-07-19)

| Item | Basis | Monthly |
|---|---|---|
| Watchlist polling (100 profiles, last-24h) | ~100–500 posts/day × $1.50/1k | ~$5–25 |
| Weekly discovery search | ~1–2k posts/mo × $1.50/1k | ~$2–3 |
| Extraction (DeepSeek) | existing plumbing, ~1–2k short calls/mo | ~$1 |
| Email harvest | ~150 profiles × $10/1k, one-time + quarterly | ~$0.50 amortized |
| **Steady state** | | **≈ $10–30 ≤ cap** |

One-time: bake-off ~$5, bootstrap search runs ~$2–5.
Piloterr alternative: $49/mo floor (18k credits) — only if bake-off shows clearly better data.

## 7. Daily metrics (permanent, every run)

1. **Promoted jobs** — posts promoted to `jobs` this run (plus cumulative active)
2. **% truly hidden** — promoted post-jobs with no cross-source match / all promoted
3. **Precision proxy** — automated daily: share of promotions with
   extraction_confidence ≥ threshold + classifier/extractor agreement; a sampled
   low-confidence review queue surfaces the worst 5 for eyeball check.
   MANUAL spot-check (the pilot method) repeated monthly, not daily.

v1 go/no-go uses ONLY the pilot window's numbers (owner decision #11/#12).

## 8. Risks

| Risk | Mitigation |
|---|---|
| Vendor data stale/truncated | LP-0 bake-off before any code depends on it; loser as fallback |
| Vendor dies / bans / price hike | Raw-tier replayability; vendor_client is the only file that knows the vendor |
| Extraction hallucination shames the board | Two-tier gate; never guess employers; confidence stored; review queue |
| Duplicate cards erode trust | Posts lowest in `_SOURCE_PRIORITY`; reconciliation before display; badge instead of second card when matched |
| ToS/PDPO exposure | §3 posture; internal board; attribution + linkback; soft delete |
| Watchlist rot | Weekly discovery feeds candidates; `active` flag + last-posted tracking in recruiters.yaml |
