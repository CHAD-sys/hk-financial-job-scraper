"""
Proof-of-concept: can Scrapling's StealthyFetcher bypass JobsDB's Cloudflare block?

Run:  python scripts/test_scrapling_jobsdb.py
Requires:  pip install "scrapling[fetchers]" && scrapling install

Tests two URLs:
  1. A company listing page  (the main target for the jobsdb adapter)
  2. A generic search page   (to confirm general access)
"""

import sys

from scrapling.fetchers import StealthyFetcher

_URLS = [
    (
        "company listing",
        "https://hk.jobsdb.com/bank-of-china-hong-kong-jobs",
    ),
    (
        "search page",
        "https://hk.jobsdb.com/hk/search?keyword=analyst&location=hong-kong",
    ),
]


def test_url(label: str, url: str) -> bool:
    print(f"\n── {label} ──────────────────────────────────────")
    print(f"URL: {url}")
    try:
        page = StealthyFetcher.fetch(
            url,
            headless=True,
            solve_cloudflare=True,
            network_idle=True,
        )
    except Exception as exc:
        print(f"❌ Exception: {type(exc).__name__}: {exc}")
        return False

    # Scrapling uses .status (int), not .status_code
    status = getattr(page, "status", None) or getattr(page, "status_code", None)
    print(f"Status: {status}")

    if status != 200:
        print("❌ Non-200 response")
        html_attr = getattr(page, "html", None) or getattr(page, "text", "") or ""
        snippet = html_attr[:300].replace("\n", " ")
        print(f"Body snippet: {snippet!r}")
        return False

    print("✅ 200 OK")

    # Get raw HTML to pass to selectolax (how the adapter will actually use it)
    html = getattr(page, "html", None) or getattr(page, "text", "") or ""
    print(f"   HTML length               : {len(html):,} chars")

    # Try Scrapling's own CSS selectors to see what it finds
    try:
        cards = page.css("[data-automation^='job-card']")
        job_titles = page.css("[data-automation='job-title']")
        total_node = page.css("[data-automation='totalJobCount']")
        print(f"   data-automation job cards : {len(cards)}")
        print(f"   data-automation job-title : {len(job_titles)}")
        if total_node:
            txt = getattr(total_node[0], "text", None) or ""
            print(f"   totalJobCount text        : {txt.strip()!r}")
        if job_titles:
            txt = getattr(job_titles[0], "text", None) or ""
            print(f"   First title               : {txt.strip()[:80]!r}")
    except Exception as sel_exc:
        print(f"   (CSS selector error: {sel_exc})")

    # Verify selectolax can parse what Scrapling fetched — this is what the adapter uses
    if html:
        from selectolax.parser import HTMLParser
        tree = HTMLParser(html)
        slx_cards = tree.css("[data-automation^='job-card']")
        slx_titles = tree.css("[data-automation='job-title']")
        print(f"   selectolax job cards      : {len(slx_cards)}")
        print(f"   selectolax job-title      : {len(slx_titles)}")
        if slx_titles:
            title_node = slx_titles[0].css_first("a") or slx_titles[0]
            print(f"   First title (slx)         : {title_node.text(strip=True)[:80]!r}")

    return bool(html) and len(html) > 10_000  # real page, not a tiny error page


if __name__ == "__main__":
    results = []
    for label, url in _URLS:
        results.append(test_url(label, url))

    print("\n══════════════════════════════════════════")
    if all(results):
        print("✅ All URLs passed — Scrapling can bypass Cloudflare on JobsDB")
        print("   Safe to integrate into the adapter.")
    elif any(results):
        print("⚠  Partial success — some URLs worked, some didn't")
    else:
        print("❌ No URLs passed — Scrapling could not bypass Cloudflare here")
        print("   The block may be session/IP-specific; try again or check browser install.")
    sys.exit(0 if all(results) else 1)
