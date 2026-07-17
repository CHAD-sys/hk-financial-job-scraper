"""
LinkedIn company-id resolver — extend the LinkedIn source to firms (run locally).

WHY THIS EXISTS
    The LinkedIn guest jobs adapter is scoped to one employer by its numeric
    company id (the `f_C` param, e.g. 1382 = Goldman Sachs). That number is NOT
    derivable from the company name. But the company's *vanity slug* IS name-
    derived (linkedin.com/company/goldman-sachs), and the company page embeds the
    numeric id (`urn:li:organization:<id>` and a `?f_C=<id>` jobs link). So we:

      1. guess candidate vanity slugs from the company name
      2. fetch linkedin.com/company/<slug>/  (plain httpx — no login)
      3. extract the numeric org id from the page
      4. VERIFY it by running the real LinkedInAdapter (f_C=<id>, 1 page) and
         checking HK job cards come back
      5. print a paste-ready `adapter: linkedin` YAML block

    Anything that doesn't resolve (opaque slug, gated page, no HK jobs) goes to a
    NO-MATCH list for you to look up by hand: open the company's LinkedIn page,
    click "See all jobs", and copy the f_C=<id> from the URL.

    ⚠ LEGAL: scraping LinkedIn violates its ToS (see hk_jobs/adapters/linkedin.py).
    Public guest pages only — this never logs in. Keep --limit small; LinkedIn
    rate-limits (429/999) aggressively, so we go slowly and politely.

USAGE (local)
    .venv/bin/python scripts/resolve_linkedin_ids.py --limit 5
    .venv/bin/python scripts/resolve_linkedin_ids.py --only hsbc-hk,manulife-hk
    .venv/bin/python scripts/resolve_linkedin_ids.py > "$TMP/linkedin_entries.yaml"

Merge the winners with scripts/merge_indeed_entries.py (it is source-agnostic —
just point --in at this file's output; the marker comment can be reused or add a
LinkedIn section). Progress goes to stderr; paste-ready YAML to stdout.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from collections import Counter
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hk_jobs.adapters.linkedin import LinkedInAdapter  # noqa: E402
from hk_jobs.config import load_companies  # noqa: E402

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
_POLITE_DELAY_SECS = 5.0
_HK_HINTS = ("hong kong", "hk", "kowloon", "new territories", "central")

_ORG_RE = re.compile(r"urn:li:organization:(\d+)")
_FC_RE = re.compile(r"[?&]f_C=(\d+)")


# ── candidate vanity slugs ─────────────────────────────────────────────────────

# Verified slug/id overrides for firms whose LinkedIn slug can't be derived from
# their name (opaque or brand-different). Keyed by company_slug. Tried FIRST.
# The ids in comments were confirmed live to return HK jobs.
SLUG_OVERRIDES: dict[str, list[str]] = {
    "jpmorgan": ["jpmorganchase"],                 # f_C 1068 (10 HK)
    "citibank-hk": ["citi"],                        # f_C 11448 (10 HK)
    "kpmg": ["kpmg-china"],                          # f_C 2525297 (10 HK)
    "hkex": ["hkex"],
    "standard-chartered-hk": ["standard-chartered-bank", "standardchartered"],
    "ey": ["ernstandyoung"],
    "smbc": ["smbc-group"],
    "mufg": ["mufgemea", "mufg"],
    "ping-an": ["ping-an-insurance-group-of-china"],
    "macquarie": ["macquariegroup"],                # f_C 3537 (10 HK)
    "invesco": ["invesco-ltd"],                      # f_C 3582438 (10 HK, 2nd id on page)
    "barclays": ["barclays-bank"],                   # f_C 1426 (10 HK)
    "allianz": ["allianz-commercial"],               # f_C 98116883 (4 HK; insurance arm)
    "china-life": ["china-life-insurance-company-limited"],
}

# Word-tail strips: "citibank"→"citi", "manulife"→"manu"? Only strip these
# business tails that commonly form a shorter LinkedIn brand slug.
_TAIL_STRIP = ("bank", "insurance", "securities", "financial")


def candidate_slugs(name: str, slug: str | None = None) -> list[str]:
    """
    Best-effort LinkedIn vanity slugs for a company name, most-likely first.

    LinkedIn slugs are lowercase, usually hyphenated but sometimes run together
    (jpmorganchase) or brand-shortened (citibank→citi). We try any verified
    override first, then the cleaned full name, no-separator and shorter-core
    forms, a few common suffixes, an acronym, and tail-stripped variants. Opaque
    slugs still MISS and go to the NO-MATCH list.
    """
    cleaned = name.replace("&", " and ")
    cleaned = re.sub(r"\(.*?\)", " ", cleaned)          # drop "(Hong Kong)", "(HK)"
    cleaned = re.sub(r"[^A-Za-z0-9 ]", " ", cleaned)
    words = [w.lower() for w in cleaned.split() if w]

    drop = {"hong", "kong", "hk", "limited", "ltd", "inc", "co", "corporation", "corp", "group"}
    core = [w for w in words if w not in drop] or words

    forms: list[str] = list(SLUG_OVERRIDES.get(slug or "", []))
    forms += [
        "-".join(words),
        "-".join(core),
        "".join(core),
        "-".join(core[:2]),
        core[0] if core else "",
    ]
    # common LinkedIn suffix variants
    for suf in ("-group", "-china", "-hong-kong"):
        forms.append("-".join(core[:2]) + suf)
    # tail-stripped first word (citibank→citi)
    if core:
        for tail in _TAIL_STRIP:
            if core[0].endswith(tail) and len(core[0]) > len(tail):
                forms.append(core[0][: -len(tail)])
    # acronym of the core words (hkma-style), only if 2–5 words
    if 2 <= len(core) <= 5:
        forms.append("".join(w[0] for w in core))

    cands: list[str] = []
    for form in forms:
        if form and form not in cands:
            cands.append(form)
    return cands[:8]


# ── company-page → id extraction ───────────────────────────────────────────────

def extract_company_ids(html: str, limit: int = 6) -> list[str]:
    """
    Pull ALL candidate numeric company ids from a company page, most-likely first.

    A big multinational's page often carries several org ids: the parent that
    aggregates jobs AND regional/showcase pages that have zero guest jobs (e.g.
    HSBC's page has 1241 — 10 HK jobs — and 93338773 — 0). Picking only the most
    frequent id misses the parent, so we return every id (f_C links first, then
    org urns), ranked by frequency, and let the caller verify each against the
    guest search and keep the one that actually returns HK jobs.
    """
    ranked: list[str] = []
    for counter in (Counter(_FC_RE.findall(html)), Counter(_ORG_RE.findall(html))):
        for cid, _ in counter.most_common():
            if cid not in ranked:
                ranked.append(cid)
    return ranked[:limit]


def _fetch(url: str) -> tuple[int, str]:
    try:
        r = httpx.get(url, headers=_UA, timeout=20, follow_redirects=True)
        return r.status_code, r.text
    except Exception as exc:  # noqa: BLE001 — resolver: report, never crash
        return -1, f"__ERR__ {type(exc).__name__}"


def _hk_count(jobs) -> int:
    n = 0
    for j in jobs:
        loc = " ".join(j.locations).lower()
        if not loc or any(h in loc for h in _HK_HINTS):
            n += 1
    return n


def _verify_id(name: str, slug: str, cid: str) -> int:
    """HK job count for f_C=<cid> via the real adapter (0 on failure/none)."""
    adapter = LinkedInAdapter(company=name, company_slug=slug,
                              linkedin_company_id=cid, max_pages=1)
    return _hk_count(adapter.fetch_jobs())  # _safe_fetch: [] on failure


def resolve_one(name: str, slug: str) -> dict | None:
    """
    Try candidate slugs → enumerate all ids on the page → verify each via guest
    search, keeping the first id that returns HK jobs. First hit wins.
    """
    for cand in candidate_slugs(name, slug):
        status, html = _fetch(f"https://www.linkedin.com/company/{cand}/")
        if status != 200 or html.startswith("__ERR__"):
            print(f"    company/{cand:28} → page status {status}", file=sys.stderr)
            time.sleep(_POLITE_DELAY_SECS)
            continue
        ids = extract_company_ids(html)
        if not ids:
            print(f"    company/{cand:28} → no id in page", file=sys.stderr)
            time.sleep(_POLITE_DELAY_SECS)
            continue

        # A page can carry several ids (parent + jobless showcase pages). Verify
        # each until one returns HK jobs — that's the id that actually has roles.
        for cid in ids:
            hk = _verify_id(name, slug, cid)
            print(f"    company/{cand:22} f_C={cid:>11} → {hk} HK", file=sys.stderr)
            if hk:
                return {"linkedin_company_id": cid, "slug_used": cand, "hk": hk}
            time.sleep(2.0)
        time.sleep(_POLITE_DELAY_SECS)
    return None


def _yaml_block(name: str, slug: str, res: dict) -> str:
    return (
        f"  - name: {name}\n"
        f"    slug: {slug}\n"
        f"    adapter: linkedin\n"
        f"    enabled: true   # resolved {res['hk']} HK jobs "
        f"(linkedin.com/company/{res['slug_used']}, f_C={res['linkedin_company_id']})\n"
        f"    config:\n"
        f"      linkedin_company_id: \"{res['linkedin_company_id']}\"\n"
        f"      max_pages: 8\n"
    )


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--limit", type=int, default=0, help="Only probe the first N firms (0=all)")
    p.add_argument("--only", default="", help="Comma-separated slugs to probe (overrides --limit)")
    args = p.parse_args(argv)

    companies = load_companies()
    already = {c.slug for c in companies if c.adapter == "linkedin"}
    seen: set[str] = set()
    targets: list[tuple[str, str]] = []
    for c in companies:
        if c.slug in already or c.slug in seen:
            continue
        seen.add(c.slug)
        targets.append((c.name, c.slug))

    if args.only:
        want = {s.strip() for s in args.only.split(",") if s.strip()}
        targets = [t for t in targets if t[1] in want]
    elif args.limit:
        targets = targets[: args.limit]

    print(f"Resolving LinkedIn company ids for {len(targets)} firms "
          f"(skipping {len(already)} already on LinkedIn)…\n", file=sys.stderr)

    # Header printed up-front and each resolved block flushed to stdout the moment
    # it is found — so a kill (e.g. the machine sleeping mid-run) keeps every hit
    # already written to the output file, instead of losing them all at the end.
    print("# ── LinkedIn sources (resolved by scripts/resolve_linkedin_ids.py) ──", flush=True)
    print("# Review each before pasting into companies.yaml.", flush=True)

    n_hits, misses = 0, []
    for i, (name, slug) in enumerate(targets, 1):
        print(f"[{i}/{len(targets)}] {name}  (slug={slug})", file=sys.stderr)
        res = resolve_one(name, slug)
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
        print("No id found (opaque slug / gated page / no HK jobs) — look up by hand:",
              file=sys.stderr)
        for m in misses:
            print(f"  · {m}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
