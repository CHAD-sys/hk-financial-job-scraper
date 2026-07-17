"""
Merge resolved Indeed entries into companies.yaml — safely, with validation.

Takes the paste-ready YAML that scripts/resolve_indeed_slugs.py emits and splices
it into companies.yaml under the INDEED_CROSS_POST_MARKER line, then re-loads the
config to PROVE every entry still parses. Comments in companies.yaml are preserved
(we text-append the resolved blocks rather than re-dumping the whole file).

It is safe to re-run: entries whose slug already has an Indeed source are skipped,
so a second merge won't create duplicates.

USAGE
    # dry-run: show what would be added + validation, write nothing
    .venv/bin/python scripts/merge_indeed_entries.py --in "$TMP/indeed_entries.yaml" --dry-run

    # do it (writes companies.yaml, keeps a .bak backup)
    .venv/bin/python scripts/merge_indeed_entries.py --in "$TMP/indeed_entries.yaml"

Checks reported after merge:
  · total / enabled / indeed entry counts
  · every NEW indeed slug shares a slug with a non-indeed entry (so its jobs will
    cross-post-match and route apply_url) — orphans are flagged, not fatal.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hk_jobs.config import _DEFAULT_YAML, load_companies  # noqa: E402

_MARKER = "# INDEED_CROSS_POST_MARKER"
_BLOCK_START = re.compile(r"^\s*-\s+name:")


def _split_blocks(resolver_text: str) -> list[str]:
    """Split resolver output into individual '  - name: …' entry blocks (drop banner)."""
    lines = resolver_text.splitlines()
    blocks: list[list[str]] = []
    cur: list[str] | None = None
    for ln in lines:
        if _BLOCK_START.match(ln):
            if cur is not None:
                blocks.append(cur)
            cur = [ln]
        elif cur is not None:
            cur.append(ln)
        # lines before the first block (resolver banner comments) are ignored
    if cur is not None:
        blocks.append(cur)
    # trim trailing blank lines inside each block
    out = []
    for b in blocks:
        while b and not b[-1].strip():
            b.pop()
        out.append("\n".join(b))
    return out


def _field_of(block: str, field: str) -> str | None:
    m = re.search(rf"^\s*{field}:\s*(.+?)\s*$", block, re.M)
    return m.group(1).strip() if m else None


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--in", dest="infile", required=True, help="Resolver output YAML file")
    p.add_argument("--yaml", default=str(_DEFAULT_YAML), help="companies.yaml path")
    p.add_argument("--marker", default=_MARKER, help="Marker comment to insert blocks after")
    p.add_argument("--dry-run", action="store_true", help="Show plan + validate, write nothing")
    args = p.parse_args(argv)

    resolver_text = Path(args.infile).read_text(encoding="utf-8")
    new_blocks = _split_blocks(resolver_text)
    if not new_blocks:
        print("No entry blocks found in resolver output — nothing to merge.", file=sys.stderr)
        return 0

    yaml_path = Path(args.yaml)
    original = yaml_path.read_text(encoding="utf-8")
    if args.marker not in original:
        print(f"ERROR: marker {args.marker!r} not found in {yaml_path}. Add the "
              f"section header first.", file=sys.stderr)
        return 1

    # (slug, adapter) pairs that ALREADY exist → skip to stay idempotent, and the
    # set of all slugs (any adapter) for the orphan check. Source-agnostic: works
    # for indeed, linkedin, or any adapter the resolver emits.
    # NOTE: read the target file (args.yaml), not the default, so --yaml works.
    current = load_companies(path=yaml_path, include_disabled=True)
    existing_pairs = {(c.slug, c.adapter) for c in current}
    all_slugs = {c.slug for c in current}

    to_add, skipped_dup, orphans = [], [], []
    seen_new: set[tuple[str, str | None]] = set()
    for block in new_blocks:
        slug = _field_of(block, "slug")
        adapter = _field_of(block, "adapter")
        pair = (slug, adapter)
        if pair in existing_pairs or pair in seen_new:
            skipped_dup.append(f"{slug}/{adapter}")
            continue
        seen_new.add(pair)
        if slug not in all_slugs:
            orphans.append(slug)  # still added, but flagged: nothing to cross-post with
        to_add.append(block)

    print(f"Resolver blocks: {len(new_blocks)}  |  new: {len(to_add)}  |  "
          f"skipped (already present / dup): {len(skipped_dup)}", file=sys.stderr)
    if orphans:
        print(f"⚠ {len(orphans)} slug(s) have no other entry to cross-post with "
              f"(added as standalone rows): {orphans}", file=sys.stderr)

    if not to_add:
        print("Nothing new to add.", file=sys.stderr)
        return 0

    # Splice the new blocks in right after the marker line.
    marker_line_end = original.index(args.marker) + len(args.marker)
    line_end = original.index("\n", marker_line_end)
    insertion = "\n\n" + "\n\n".join(to_add) + "\n"
    merged = original[: line_end] + insertion + original[line_end:]

    if args.dry_run:
        print("\n--- would insert (dry-run) ---")
        print(insertion.strip())
    else:
        shutil.copy2(yaml_path, str(yaml_path) + ".bak")
        yaml_path.write_text(merged, encoding="utf-8")
        print(f"\nWrote {yaml_path}  (backup at {yaml_path}.bak)", file=sys.stderr)

    # Validate: parse the merged content (from disk if written, else in-memory).
    text_to_check = merged if args.dry_run else yaml_path.read_text(encoding="utf-8")
    try:
        yaml.safe_load(text_to_check)  # YAML well-formed?
    except yaml.YAMLError as e:
        print(f"✗ MERGED YAML IS INVALID: {e}", file=sys.stderr)
        return 1
    # And that the real loader (adapter + required-key validation) accepts it.
    if not args.dry_run:
        all_c = load_companies(path=yaml_path, include_disabled=True)
        added_adapters = {a for a in (_field_of(b, "adapter") for b in to_add) if a}
        counts = " ".join(
            f"{a}={sum(1 for c in all_c if c.adapter == a)}" for a in sorted(added_adapters)
        )
        enabled_n = len(load_companies(path=yaml_path))
        print(f"✓ load_companies OK — total {len(all_c)}, enabled {enabled_n}  ({counts})",
              file=sys.stderr)
    else:
        print("✓ merged YAML is well-formed (dry-run; loader check runs on real write)",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
