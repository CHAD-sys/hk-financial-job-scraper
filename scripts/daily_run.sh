#!/usr/bin/env bash
# daily_run.sh — Full HK Job Scraper pipeline
# Designed to run as a cron job at 2 AM HKT (18:00 UTC)
# Cron: 0 18 * * * /opt/hk-job-scraper/scripts/daily_run.sh

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$REPO_DIR/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/daily_runs.log"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

log "=== Daily pipeline started ==="
cd "$REPO_DIR"

# Activate virtual environment.
# NOTE: the repo was moved and .venv/bin/activate still hardcodes the OLD path
# (/Users/mohamedaminechahid/hk-job-scraper). Sourcing it would put a dead dir on
# PATH and fall through to system Python. Prepending the venv's bin dir does the
# only thing activation actually needs, and keeps working after a venv rebuild.
export PATH="$REPO_DIR/.venv/bin:$PATH"

# Load API keys (create config/api_keys.env with: export DEEPSEEK_API_KEY=sk-...)
if [[ -f config/api_keys.env ]]; then
    source config/api_keys.env
fi

if [[ -z "${DEEPSEEK_API_KEY:-}" ]]; then
    log "ERROR: DEEPSEEK_API_KEY not set. Create config/api_keys.env or set env var."
    exit 1
fi

# Phase 1: Scrape listings from every enabled company in both config files
log "--- Phase 1: Scraping listings ---"
python -m hk_jobs.pipeline 2>&1 | tee -a "$LOG_FILE"
log "Phase 1 complete"

# Phase 2: Fetch descriptions (full mode — only touches jobs with no description).
# NOT --incremental: that filters on DATE(fetched_at)=today, which silently no-ops
# whenever the scrape runs long or crosses UTC midnight. Full mode already skips
# jobs that already have descriptions, so it's both safe and complete.
log "--- Phase 2: Fetching descriptions (full — missing only) ---"
python -m hk_jobs.pipeline --fetch-descriptions 2>&1 | tee -a "$LOG_FILE"
log "Phase 2 complete"

# Phase 3: Enrich (full mode — only touches unenriched jobs). Not --incremental,
# for the same date-filter reason as Phase 2.
log "--- Phase 3: DeepSeek enrichment (full — unenriched only) ---"
python -m hk_jobs.pipeline --enrich 2>&1 | tee -a "$LOG_FILE"
log "Phase 3 complete"

# Phase 3b: Salary outlier audit — re-judges the estimates most likely to be wrong
# (>=120k, cluster outliers, ambiguous "Team Head"-style titles). Down-only
# auto-corrections with an audit trail in salary_audit_log; upward suggestions are
# only reported, never applied. Non-fatal — an audit hiccup must not abort the run.
log "--- Phase 3b: Salary outlier audit ---"
python -m hk_jobs.pipeline --audit-salaries 2>&1 | tee -a "$LOG_FILE" \
    || log "WARNING: salary audit failed (non-fatal)"
log "Phase 3b complete"

# Phase 4: Refresh the PocketBase verification mirror (jobs.db -> PocketBase, one-way).
# Keeps the boss-facing PB admin UI current. Requires PocketBase to be STOPPED; the sync
# self-guards (refuses if PB is serving on :8090). Non-fatal on purpose — a running PB or a
# sync hiccup must never abort the pipeline, so we swallow the error and just log a warning.
log "--- Phase 4: Syncing PocketBase mirror ---"
python -m hk_jobs.sync_pocketbase 2>&1 | tee -a "$LOG_FILE" \
    || log "WARNING: PocketBase sync skipped/failed (is PocketBase running? — non-fatal)"
log "Phase 4 complete"

# Phase 5: LP-2 "Secret Market" — poll the recruiters.yaml watchlist for new
# LinkedIn posts via Apify (raw ingestion only, see docs/PLAN_LINKEDIN_POSTS.md).
# Non-fatal on purpose, same reasoning as phases 3b/4: this is a separate,
# non-critical vendor source — an Apify outage, a hit budget cap, or a missing
# APIFY_API_TOKEN must never abort the core job-board pipeline. Runs AFTER the
# PocketBase sync (phase 4) since posts don't feed jobs/PB yet (that's LP-3/LP-5);
# runs BEFORE the backup (phase 6) so today's backup includes whatever posts
# were fetched.
log "--- Phase 5: Fetching LinkedIn recruiter posts (watchlist) ---"
python -m hk_jobs.pipeline --fetch-posts 2>&1 | tee -a "$LOG_FILE" \
    || log "WARNING: LinkedIn posts fetch failed (non-fatal — is APIFY_API_TOKEN set?)"
log "Phase 5 complete"

# Phase 5b: LP-2 weekly discovery search — keyword search for new job-bearing
# posts, independent of the watchlist poll above. Runs Mondays only (plan's
# "weekly" cadence); non-fatal for the same reasons as phase 5.
if [[ "$(date '+%u')" == "1" ]]; then
    log "--- Phase 5b: LinkedIn posts discovery search (weekly, Monday) ---"
    python -m hk_jobs.pipeline --posts-discovery 2>&1 | tee -a "$LOG_FILE" \
        || log "WARNING: LinkedIn posts discovery search failed (non-fatal)"
    log "Phase 5b complete"
fi

# Phase 5c: LP-3 — classify+extract+promote pending LinkedIn posts into the
# jobs table. Non-fatal for the same reasons as phase 5 (separate, non-
# critical vendor-adjacent source; a DeepSeek hiccup must never abort the
# core job-board pipeline). Runs after both fetch phases so anything fetched
# today (or the Monday discovery batch) gets a chance to be promoted today.
log "--- Phase 5c: Promoting LinkedIn posts (LP-3 extract + promote) ---"
python -m hk_jobs.pipeline --promote-posts 2>&1 | tee -a "$LOG_FILE" \
    || log "WARNING: LinkedIn posts promotion failed (non-fatal — is DEEPSEEK_API_KEY set?)"
log "Phase 5c complete"

# Phase 6: Backup database (30-day rolling retention)
log "--- Phase 6: Backing up database ---"
python -m hk_jobs.pipeline --backup 2>&1 | tee -a "$LOG_FILE"
log "Phase 6 complete"

# Phase 7: Send daily summary email
log "--- Phase 7: Sending daily summary email ---"
python -m hk_jobs.pipeline --notify-summary 2>&1 | tee -a "$LOG_FILE"
log "Phase 7 complete"

log "=== Daily pipeline finished ==="
