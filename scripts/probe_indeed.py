"""
THROWAWAY PROBE — Indeed company-page scrapeability check (Phase 1, verification only).

NOT part of the scraper. Touches no adapter, no config, no DB. Delete when done.

Goal: find out whether Indeed HK company pages are reachable past Cloudflare and how
clean the data is, BEFORE committing to a real adapter.

Mirrors the JobsDB approach: Scrapling StealthyFetcher, solve_cloudflare=True,
network_idle=False (Indeed also runs continuous background traffic).

Public pages only. Does NOT log in, submit credentials, or cross any human-verify /
login wall. If a page needs login to go further, it stops and reports that.

Run locally (a real headless browser + Cloudflare solve is required):

    caffeinate -i .venv/bin/python scripts/probe_indeed.py

Raw HTML for each page is dumped to /tmp so you can eyeball structure yourself.
"""

import json
import re
import sys
import time
from pathlib import Path

from scrapling.fetchers import StealthyFetcher

# One company profile page each. `/cmp/<slug>/jobs` is Indeed's employer job list.
TARGETS = [
    ("Goldman Sachs", "https://hk.indeed.com/cmp/Goldman-Sachs/jobs"),
    ("JPMorgan",      "https://hk.indeed.com/cmp/Jpmorganchase-2/jobs"),
    ("DBS",           "https://hk.indeed.com/cmp/Dbs-Bank/jobs"),
]

DUMP_DIR = Path("/tmp/indeed_probe")
POLITE_DELAY_SECS = 6  # gap between requests so we don't trip rate limiting

# Signals that we hit a login / human-verification wall rather than real content.
# NOTE: do NOT key off "secure.indeed.com" or "cf_chl" — both appear on a perfectly
# good content page (the former is the header "Sign in" nav link, the latter is the
# Cloudflare token echoed into that link's continue= param). Keying off them gave a
# false LOGIN_WALL on all three pages in the first run. Only genuine wall *text* counts.
_LOGIN_WALL_SIGNALS = (
    "verify you are human",
    "additional verification required",
    "enter the characters you see",
    "prove you're not a robot",
)
# Cloudflare "still challenging" signals (same idea as the jobsdb adapter's _is_challenge).
# "cf_chl" removed for the same reason — it lives in benign redirect URLs post-solve.
_CF_SIGNALS = ("just a moment", "checking your browser", "cf-challenge")


def _fetch(url: str) -> tuple[int, str, float]:
    """Fetch one URL. Returns (status, html, elapsed_secs). Never raises."""
    t0 = time.monotonic()
    try:
        page = StealthyFetcher.fetch(
            url,
            headless=True,
            solve_cloudflare=True,
            network_idle=False,
        )
    except Exception as exc:  # noqa: BLE001 — probe: report, don't crash
        return -1, f"__EXCEPTION__ {type(exc).__name__}: {exc}", time.monotonic() - t0
    status = getattr(page, "status", None) or getattr(page, "status_code", None) or 0
    html = str(getattr(page, "html_content", None) or getattr(page, "html", "") or "")
    return status, html, time.monotonic() - t0


def _classify(status: int, html: str) -> str:
    """One of: exception | cloudflare_challenge | login_wall | content | unknown."""
    low = html.lower()
    if status == -1:
        return "exception"
    if any(s in low for s in _LOGIN_WALL_SIGNALS):
        return "login_wall"
    if status in (403, 429) or (len(html) < 100_000 and any(s in low for s in _CF_SIGNALS)):
        return "cloudflare_challenge"
    if status == 200 and len(html) > 20_000:
        return "content"
    return "unknown"


def _find_embedded_json(html: str) -> list[str]:
    """
    Which embedded-JSON transport (if any) carries the job data.

    Indeed historically ships cards in a script blob rather than the rendered
    DOM — this tells us whether extraction can read structured JSON (like the
    JobsDB GraphQL win) or must scrape HTML.
    """
    hits = []
    probes = {
        "_initialData": r"window\._initialData\s*=",
        "mosaic-provider-jobcards": r"mosaic-provider-jobcards",
        "__NEXT_DATA__": r"__NEXT_DATA__",
        "window.mosaic": r"window\.mosaic",
        "jobmap / jobKeysWithInfo": r"jobmap\[|jobKeysWithInfo",
        "application/ld+json": r'type="application/ld\+json"',
    }
    for label, pat in probes.items():
        if re.search(pat, html):
            hits.append(label)
    return hits


def _extract_mosaic_cards(html: str, page_company: str) -> list[dict]:
    """
    Primary extractor: Indeed renders the card list as a JSON blob in a <script>,
    NOT in the DOM. This is the equivalent of the JobsDB GraphQL find — read the
    structured data directly instead of scraping rendered HTML.

        window.mosaic.providerData["mosaic-provider-jobcards"] = {...};

    On a /cmp/<slug>/jobs page each result's own `company` field is blank (the
    employer is implied by the page), so we stamp the page's company onto each.
    """
    m = re.search(
        r'window\.mosaic\.providerData\["mosaic-provider-jobcards"\]\s*=\s*(\{.*?\});',
        html, re.S,
    )
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except Exception:  # noqa: BLE001
        return []
    results = (
        data.get("metaData", {})
        .get("mosaicProviderJobCardsModel", {})
        .get("results", [])
    )
    out = []
    for j in results:
        out.append({
            "title": j.get("title") or j.get("displayTitle") or "",
            "company": j.get("company") or page_company,
            "location": j.get("formattedLocation", ""),
            "indeed_apply": bool(j.get("indeedApplyable")),  # apply-on-Indeed vs external ATS
        })
    return out


def _extract_cards(html: str) -> list[dict]:
    """
    Fallback title/company/location per card from rendered HTML.

    Tries several selector generations because Indeed rotates markup. This is a
    probe, not a parser — we just need enough to eyeball contamination.
    """
    from selectolax.parser import HTMLParser

    tree = HTMLParser(html)

    def first_text(node, selectors):
        for sel in selectors:
            hit = node.css_first(sel)
            if hit:
                txt = hit.text(strip=True)
                if txt:
                    return txt
        return ""

    # Candidate card containers, newest-ish first.
    card_selectors = [
        "div.job_seen_beacon",
        "[data-testid='slider_item']",
        "div.cardOutline",
        "li div.css-1ac2h1w",  # generic mosaic card wrapper seen on cmp pages
        "a[data-jk]",
    ]
    cards = []
    for sel in card_selectors:
        found = tree.css(sel)
        if found:
            cards = found
            break

    results = []
    for c in cards:
        title = first_text(c, [
            "h2.jobTitle span[title]", "h2.jobTitle", "[data-testid='jobTitle']",
            "a.jcs-JobTitle span", "a.jcs-JobTitle", "h2 a span", "h2 a",
        ])
        company = first_text(c, [
            "[data-testid='company-name']", "span.companyName",
            "[data-testid='inlineCompanyName']", ".company_location .companyName",
        ])
        location = first_text(c, [
            "[data-testid='text-location']", "div.companyLocation",
            "[data-testid='location']", ".company_location [data-testid]",
        ])
        if title or company or location:
            results.append({"title": title, "company": company, "location": location})
    return results


def _ldjson_jobs(html: str) -> list[dict]:
    """Pull JobPosting entries out of any ld+json blocks (clean structured fallback)."""
    out = []
    for m in re.finditer(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.S):
        try:
            data = json.loads(m.group(1).strip())
        except Exception:  # noqa: BLE001
            continue
        items = data if isinstance(data, list) else [data]
        for it in items:
            if isinstance(it, dict) and it.get("@type") == "JobPosting":
                org = it.get("hiringOrganization") or {}
                loc = it.get("jobLocation") or {}
                if isinstance(loc, list):
                    loc = loc[0] if loc else {}
                addr = (loc.get("address") if isinstance(loc, dict) else {}) or {}
                out.append({
                    "title": it.get("title", ""),
                    "company": org.get("name", "") if isinstance(org, dict) else "",
                    "location": addr.get("addressLocality", "") if isinstance(addr, dict) else "",
                })
    return out


def probe(label: str, url: str, dump_name: str) -> dict:
    print(f"\n{'='*70}\n{label}  —  {url}")
    status, html, elapsed = _fetch(url)
    kind = _classify(status, html)
    dump_path = DUMP_DIR / f"{dump_name}.html"
    if html and not html.startswith("__EXCEPTION__"):
        dump_path.write_text(html, encoding="utf-8")

    print(f"  HTTP status      : {status}")
    print(f"  fetch time       : {elapsed:.1f}s")
    print(f"  html length      : {len(html):,} chars")
    print(f"  classified as    : {kind.upper()}")
    if kind == "exception":
        print(f"  error            : {html}")
        return {"label": label, "kind": kind, "jobs": [], "elapsed": elapsed}
    if kind in ("login_wall", "cloudflare_challenge"):
        which = [s for s in (_LOGIN_WALL_SIGNALS + _CF_SIGNALS) if s in html.lower()]
        print(f"  STOP — blocked by: {which}  (not attempting to bypass)")
        print(f"  raw html dumped  : {dump_path}")
        return {"label": label, "kind": kind, "jobs": [], "elapsed": elapsed}

    json_transports = _find_embedded_json(html)
    print(f"  embedded JSON    : {json_transports or 'none detected (HTML-only render)'}")

    # on-page total count ("N jobs") — company-level total, not necessarily HK-only
    tot = re.search(r'([\d,]+)\s+jobs?\b', html)
    print(f"  on-page total    : {tot.group(0) if tot else 'not found'}")

    cards = _extract_mosaic_cards(html, label)  # JSON-first (the real transport)
    if not cards:
        cards = _extract_cards(html) or _ldjson_jobs(html)  # DOM / ld+json fallback
    print(f"  cards on page 1  : {len(cards)}")
    for i, c in enumerate(cards, 1):
        apply = "indeed-apply" if c.get("indeed_apply") else "external-ATS"
        print(f"    {i:>2}. {c['title'][:60]:60} | {c['company'][:20]:20} | "
              f"{c['location'][:22]:22} | {apply}")
    print(f"  raw html dumped  : {dump_path}")
    return {"label": label, "kind": kind, "jobs": cards, "elapsed": elapsed,
            "json_transports": json_transports, "url": url}


def probe_pagination(label: str, url: str, dump_name: str) -> None:
    """
    Fetch page 2 to see if pagination works without login.

    NOTE: /cmp/<slug>/jobs paginates in steps of 20 (?start=20,40,60,...), NOT 10.
    ?start=10 is rounded back to page 1 (returns the identical result set) — that
    tripped the first run into a false "pagination works" with duplicate jobs.
    Indeed also re-surfaces some sponsored/featured cards across pages, so real
    extraction must dedup by `jobkey`.
    """
    page2 = url + ("&start=20" if "?" in url else "?start=20")
    print(f"\n  -- pagination check (page 2) : {page2}")
    status, html, elapsed = _fetch(page2)
    kind = _classify(status, html)
    (DUMP_DIR / f"{dump_name}_page2.html").write_text(
        html if html and not html.startswith('__EXCEPTION__') else '', encoding="utf-8")
    print(f"     status={status}  time={elapsed:.1f}s  classified={kind.upper()}")
    if kind == "content":
        cards = _extract_mosaic_cards(html, label) or _extract_cards(html) or _ldjson_jobs(html)
        titles = [c["title"] for c in cards]
        print(f"     page-2 cards found : {len(cards)}  -> pagination works WITHOUT login")
        for t in titles[:5]:
            print(f"       · {t[:70]}")
    else:
        print(f"     page 2 is {kind.upper()} -> pagination likely walls after page 1")


def main() -> int:
    DUMP_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Indeed probe — raw HTML dumps in {DUMP_DIR}")
    summary = []
    for idx, (label, url) in enumerate(TARGETS):
        slug = re.sub(r"[^a-z0-9]+", "_", label.lower())
        res = probe(label, url, slug)
        summary.append(res)
        # Only bother testing pagination where page 1 actually gave us content.
        if res["kind"] == "content" and res["jobs"]:
            time.sleep(POLITE_DELAY_SECS)
            probe_pagination(label, url, slug)
        if idx < len(TARGETS) - 1:
            time.sleep(POLITE_DELAY_SECS)

    print(f"\n{'='*70}\nSUMMARY")
    for r in summary:
        print(f"  {r['label']:14}  {r['kind']:22}  {len(r['jobs'])} jobs  ({r['elapsed']:.0f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
