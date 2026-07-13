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

# Activate virtual environment
source .venv/bin/activate

# Load API keys (create config/api_keys.env with: export DEEPSEEK_API_KEY=sk-...)
if [[ -f config/api_keys.env ]]; then
    source config/api_keys.env
fi

if [[ -z "${DEEPSEEK_API_KEY:-}" ]]; then
    log "ERROR: DEEPSEEK_API_KEY not set. Create config/api_keys.env or set env var."
    exit 1
fi

# Phase 1: Scrape listings from all 27 companies
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

# Phase 4: Refresh the PocketBase verification mirror (jobs.db -> PocketBase, one-way).
# Keeps the boss-facing PB admin UI current. Requires PocketBase to be STOPPED; the sync
# self-guards (refuses if PB is serving on :8090). Non-fatal on purpose — a running PB or a
# sync hiccup must never abort the pipeline, so we swallow the error and just log a warning.
log "--- Phase 4: Syncing PocketBase mirror ---"
python -m hk_jobs.sync_pocketbase 2>&1 | tee -a "$LOG_FILE" \
    || log "WARNING: PocketBase sync skipped/failed (is PocketBase running? — non-fatal)"
log "Phase 4 complete"

# Phase 5: Backup database (30-day rolling retention)
log "--- Phase 5: Backing up database ---"
python -m hk_jobs.pipeline --backup 2>&1 | tee -a "$LOG_FILE"
log "Phase 5 complete"

# Phase 6: Send daily summary email
log "--- Phase 6: Sending daily summary email ---"
python -m hk_jobs.pipeline --notify-summary 2>&1 | tee -a "$LOG_FILE"
log "Phase 6 complete"

log "=== Daily pipeline finished ==="
