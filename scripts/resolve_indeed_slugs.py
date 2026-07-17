"""
Indeed /cmp slug resolver — extend the Indeed source to ALL firms (run locally).

WHY THIS EXISTS
    We want Indeed to be a universal cross-post source (apply-priority rank 2:
    efc → indeed → jobsdb), not just the primary source for Goldman/JPMorgan/DBS.
    To add an `adapter: indeed` entry for a firm we need its employer-page slug —
    the `<slug>` in hk.indeed.com/cmp/<slug>/jobs. That slug is NOT derivable from
    the company name (JPMorgan's is "Jpmorganchase-2", DBS's is "Dbs-Bank"), so it
    must be discovered against the live site and VERIFIED to return HK jobs.

    The sandbox blocks the live, Cloudflare-gated fetches, so this is a LOCAL
    helper — the same pattern as scripts/discover_companies.py (JobsDB) and the
    eFC resolver. It touches no DB and writes no config; it only PRINTS ready-to-
    paste YAML for the firms it can confirm. You review and paste the winners.

    ⚠ LEGAL: scraping Indeed violates its ToS (see hk_jobs/adapters/indeed.py).
    Each fetch drives a headless browser through a Cloudflare solve (~15 s), so a
    full run over ~45 firms with a few candidate slugs each is slow and heavy on a
    ToS-restricted source. Keep --limit small; do not run this on a schedule.

WHAT IT DOES
    For every ENABLED firm that does not already have an Indeed source:
      1. generate a handful of candidate /cmp slugs from the company name
      2. fetch page 1 of each candidate with the real IndeedAdapter (max_pages=1)
      3. keep the first candidate that returns HK job cards
      4. print an `adapter: indeed` YAML block sharing that firm's slug

USAGE (local, needs scrapling[fetchers] installed — see indeed.py header)
    caffeinate -i .venv/bin/python scripts/resolve_indeed_slugs.py            # all firms
    caffeinate -i .venv/bin/python scripts/resolve_indeed_slugs.py --limit 5  # first 5
    caffeinate -i .venv/bin/python scripts/resolve_indeed_slugs.py --only hsbc-hk,manulife-hk
    caffeinate -i .venv/bin/python scripts/resolve_indeed_slugs.py --slug-candidates 6

Output goes to stdout (paste-ready YAML) and progress to stderr.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

# Make hk_jobs importable when run as `python scripts/resolve_indeed_slugs.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hk_jobs.adapters.indeed import IndeedAdapter  # noqa: E402
from hk_jobs.config import load_companies  # noqa: E402

_POLITE_DELAY_SECS = 6.0  # gap between candidate fetches — be gentle on the source
_HK_HINTS = ("hong kong", "hk", "kowloon", "new territories", "central")


# ── candidate slug generation ──────────────────────────────────────────────────

def _title_slug(words: list[str]) -> str:
    """['goldman','sachs'] → 'Goldman-Sachs' (Indeed uses Title-Case-Hyphen)."""
    return "-".join(w.capitalize() for w in words if w)


def candidate_slugs(name: str, extra: int = 0) -> list[str]:
    """
    Best-effort /cmp slug guesses for a company name, most-likely first.

    Indeed slugs are Title-Cased and hyphenated, usually WITHOUT the "(Hong Kong)"
    / "HK" qualifier ("Dbs-Bank", "Standard-Chartered"). We try the cleaned full
    name, then progressively shorter cores. This will MISS opaque slugs like
    "Jpmorganchase-2" — those firms report NO MATCH and keep their manual entry.
    """
    cleaned = name.replace("&", " and ")
    cleaned = re.sub(r"\(.*?\)", " ", cleaned)          # drop "(Hong Kong)", "(HK)"
    cleaned = re.sub(r"[^A-Za-z0-9 ]", " ", cleaned)
    words = [w for w in cleaned.split() if w]

    # Drop trailing geography/qualifier tokens that Indeed usually omits.
    drop = {"hong", "kong", "hk", "china", "asia", "international", "group", "limited",
            "ltd", "holdings", "inc", "co", "corporation", "corp"}
    core = [w for w in words if w.lower() not in drop] or words

    cands: list[str] = []
    for token_list in (words, core, core[:3], core[:2], core[:1]):
        s = _title_slug(token_list)
        if s and s not in cands:
            cands.append(s)

    if extra:  # a couple of lowercase variants some employer pages use
        for token_list in (core, core[:2]):
            s = "-".join(w.lower() for w in token_list if w)
            if s and s not in cands:
                cands.append(s)

    return cands[: 4 + extra]


# ── verification via the real adapter ──────────────────────────────────────────

def _hk_count(jobs) -> int:
    """How many returned jobs look HK-based (hk.indeed.com is HK-scoped anyway)."""
    n = 0
    for j in jobs:
        loc = " ".join(j.locations).lower()
        if not loc or any(h in loc for h in _HK_HINTS):
            n += 1
    return n


def resolve_one(name: str, slug: str, n_candidates: int) -> dict | None:
    """Try candidate slugs for one firm; return the first that yields HK jobs."""
    for cand in candidate_slugs(name, extra=max(0, n_candidates - 4)):
        adapter = IndeedAdapter(
            company=name, company_slug=slug, indeed_slug=cand, max_pages=1,
        )
        try:
            jobs = adapter.fetch_jobs()  # _safe_fetch: returns [] on any failure
        except Exception as exc:  # noqa: BLE001 — resolver: report, never crash
            print(f"    {cand:32} → error {type(exc).__name__}", file=sys.stderr)
            time.sleep(_POLITE_DELAY_SECS)
            continue

        hk = _hk_count(jobs)
        status = f"{len(jobs)} cards ({hk} HK)" if jobs else "no cards"
        print(f"    {cand:32} → {status}", file=sys.stderr)
        if jobs and hk:
            return {"indeed_slug": cand, "total": len(jobs), "hk": hk}
        time.sleep(_POLITE_DELAY_SECS)
    return None


def _yaml_block(name: str, slug: str, res: dict) -> str:
    return (
        f"  - name: {name}\n"
        f"    slug: {slug}\n"
        f"    adapter: indeed\n"
        f"    enabled: true   # resolved {res['hk']} HK jobs on page 1 "
        f"(hk.indeed.com/cmp/{res['indeed_slug']}/jobs)\n"
        f"    config:\n"
        f"      indeed_slug: {res['indeed_slug']}\n"
        f"      max_pages: 8\n"
    )


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--limit", type=int, default=0, help="Only probe the first N firms (0=all)")
    p.add_argument("--only", default="", help="Comma-separated slugs to probe (overrides --limit)")
    p.add_argument("--slug-candidates", type=int, default=4, help="Max candidate slugs per firm")
    args = p.parse_args(argv)

    companies = load_companies()  # enabled only

    # One Indeed entry per unique slug; skip slugs that already have an Indeed source.
    already_indeed = {c.slug for c in companies if c.adapter == "indeed"}
    seen: set[str] = set()
    targets: list[tuple[str, str]] = []
    for c in companies:
        if c.slug in already_indeed or c.slug in seen:
            continue
        seen.add(c.slug)
        targets.append((c.name, c.slug))

    if args.only:
        want = {s.strip() for s in args.only.split(",") if s.strip()}
        targets = [t for t in targets if t[1] in want]
    elif args.limit:
        targets = targets[: args.limit]

    print(f"Resolving Indeed /cmp slugs for {len(targets)} firms "
          f"(skipping {len(already_indeed)} already on Indeed)…\n", file=sys.stderr)

    # Header printed up-front and each resolved block flushed to stdout the moment
    # it is found — so a kill (e.g. the machine sleeping mid-run) keeps every hit
    # already written to the output file, instead of losing them all at the end.
    print("# ── Indeed cross-post sources (resolve_indeed_slugs.py) ──", flush=True)
    print("# Review each before pasting into companies.yaml. Apply-priority is handled", flush=True)
    print("# automatically: efc → indeed → jobsdb for roles with no own-ATS copy.", flush=True)

    n_hits: int = 0
    misses: list[str] = []
    for i, (name, slug) in enumerate(targets, 1):
        print(f"[{i}/{len(targets)}] {name}  (slug={slug})", file=sys.stderr)
        res = resolve_one(name, slug, args.slug_candidates)
        if res:
            print("\n" + _yaml_block(name, slug, res), flush=True)  # persist immediately
            n_hits += 1
        else:
            misses.append(f"{name} ({slug})")
        if i < len(targets):
            time.sleep(_POLITE_DELAY_SECS)

    print("\n" + "=" * 74, file=sys.stderr)
    print(f"RESOLVED {n_hits}/{len(targets)}   |   NO MATCH: {len(misses)}", file=sys.stderr)
    if misses:
        print("No slug found (opaque slug / not on Indeed / blocked) — verify by hand:",
              file=sys.stderr)
        for m in misses:
            print(f"  · {m}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
