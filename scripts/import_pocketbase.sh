#!/usr/bin/env bash
# Restore a pb_data tarball (produced by export_pocketbase.sh) into a FRESH
# directory, ready to run `pocketbase serve --dir <target>` on Railway / a VPS /
# anywhere. Refuses to overwrite an existing target so you never clobber live data.
#
# Usage:  scripts/import_pocketbase.sh <tarball> [target_dir]
#   default target_dir: ./pb_data_restored
set -euo pipefail

TARBALL="${1:?usage: import_pocketbase.sh <tarball> [target_dir]}"
TARGET="${2:-./pb_data_restored}"

if [[ ! -f "$TARBALL" ]]; then
  echo "ERROR: tarball not found: $TARBALL" >&2
  exit 1
fi
if [[ -e "$TARGET" ]]; then
  echo "ERROR: target already exists, refusing to overwrite: $TARGET" >&2
  exit 1
fi

mkdir -p "$TARGET"
tmp="$(mktemp -d)"
tar -xzf "$TARBALL" -C "$tmp"
# The tarball has a top-level pb_data/ dir — flatten its contents into TARGET.
inner="$(find "$tmp" -maxdepth 1 -type d -name pb_data | head -1)"
if [[ -n "$inner" ]]; then
  cp -R "$inner"/. "$TARGET"/
else
  cp -R "$tmp"/. "$TARGET"/
fi
rm -rf "$tmp"

echo "Restored $TARBALL -> $TARGET"
echo "Serve it with:  ./pocketbase/pocketbase serve --dir $TARGET"
