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

# Phase 2: Fetch full descriptions (GraphQL + REST)
log "--- Phase 2: Fetching descriptions ---"
python -m hk_jobs.pipeline --fetch-descriptions 2>&1 | tee -a "$LOG_FILE"
log "Phase 2 complete"

# Phase 3: AI enrichment (new jobs only)
log "--- Phase 3: DeepSeek enrichment ---"
python -m hk_jobs.pipeline --enrich 2>&1 | tee -a "$LOG_FILE"
log "Phase 3 complete"

log "=== Daily pipeline finished ==="
