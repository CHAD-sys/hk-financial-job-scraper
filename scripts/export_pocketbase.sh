#!/usr/bin/env bash
# Package the entire PocketBase pb_data directory into ONE portable tarball for the
# deployment handoff. PocketBase keeps all state (the SQLite data.db + settings +
# uploads) inside pb_data, so this single file is everything needed to stand the
# instance back up elsewhere (Railway / VPS) via `pocketbase serve`.
#
# Usage:  scripts/export_pocketbase.sh [pb_data_dir] [output.tar.gz]
#   defaults: ./pocketbase/pb_data  ->  pb_data_export_YYYYMMDD.tar.gz
#
# TIP: stop `pocketbase serve` first for a clean snapshot of the SQLite file.
set -euo pipefail

PB_DATA="${1:-./pocketbase/pb_data}"
OUT="${2:-pb_data_export_$(date +%Y%m%d).tar.gz}"

if [[ ! -d "$PB_DATA" ]]; then
  echo "ERROR: pb_data directory not found: $PB_DATA" >&2
  exit 1
fi

tar -czf "$OUT" -C "$(dirname "$PB_DATA")" "$(basename "$PB_DATA")"
echo "Exported $PB_DATA -> $OUT ($(du -h "$OUT" | cut -f1))"
