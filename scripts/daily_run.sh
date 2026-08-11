#!/usr/bin/env bash
# Thin local adapter for the canonical Python Daily Run module.
# Cron at 02:00 HKT: 0 18 * * * /path/to/scripts/daily_run.sh

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$REPO_DIR/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/daily_runs.log"

cd "$REPO_DIR"
export PATH="$REPO_DIR/.venv/bin:$PATH"

if [[ -f config/api_keys.env ]]; then
    # shellcheck disable=SC1091
    source config/api_keys.env
fi

ARGS=(
    --profile local
    --record data/daily-run.json
    --database data/jobs.db
    --export data/jobs.jsonl
)
if [[ "${PIPELINE_DAILY_EMAIL:-0}" == "1" ]]; then
    ARGS+=(--email)
fi

python -m hk_jobs.daily_run "${ARGS[@]}" 2>&1 | tee -a "$LOG_FILE"
