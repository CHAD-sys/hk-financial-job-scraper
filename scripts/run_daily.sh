#!/usr/bin/env bash
# run_daily.sh — run the HK job scraper and export a fresh JSONL snapshot.
#
# Usage:
#   bash scripts/run_daily.sh                      # defaults
#   HK_JOBS_COMPANY=aia-hk bash scripts/run_daily.sh   # single company
#
# Environment variables (all optional):
#   HK_JOBS_DB        path to SQLite database  (default: data/jobs.db)
#   HK_JOBS_EXPORT    path for JSONL export    (default: data/jobs_YYYYMMDD.jsonl)
#   HK_JOBS_COMPANY   run only this company slug (default: all)
#   HK_JOBS_LOG       log level: DEBUG|INFO|WARNING|ERROR (default: INFO)
#
# Sample cron (runs at 02:00 HKT = 18:00 UTC previous day):
#   0 18 * * * cd /path/to/hk-job-scraper && bash scripts/run_daily.sh >> logs/scraper.log 2>&1
#
# Sample systemd timer: see docs in README.md

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

DB_PATH="${HK_JOBS_DB:-$PROJECT_DIR/data/jobs.db}"
EXPORT_PATH="${HK_JOBS_EXPORT:-$PROJECT_DIR/data/jobs_$(date +%Y%m%d).jsonl}"
LOG_LEVEL="${HK_JOBS_LOG:-INFO}"

mkdir -p "$PROJECT_DIR/data"

# Activate virtual environment (created by: python -m venv .venv)
if [[ -f "$PROJECT_DIR/.venv/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source "$PROJECT_DIR/.venv/bin/activate"
else
    echo "ERROR: .venv not found. Run: python -m venv .venv && pip install -r requirements.txt" >&2
    exit 1
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] Starting HK financial jobs scrape..."

PIPELINE_ARGS=(
    --db    "$DB_PATH"
    --export "$EXPORT_PATH"
    --log-level "$LOG_LEVEL"
)

if [[ -n "${HK_JOBS_COMPANY:-}" ]]; then
    PIPELINE_ARGS+=(--company "$HK_JOBS_COMPANY")
fi

python -m hk_jobs.pipeline "${PIPELINE_ARGS[@]}"

echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] Done."
echo "  Database : $DB_PATH"
echo "  Export   : $EXPORT_PATH"
