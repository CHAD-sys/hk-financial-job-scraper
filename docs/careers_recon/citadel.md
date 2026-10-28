# Citadel / Citadel Securities careers recon (2026-10-28)

## Summary
- ATS: custom WordPress (Yoast SEO plugin, CPT `career`), NOT Greenhouse/Lever/Workday etc. Sites: www.citadel.com and www.citadelsecurities.com (same stack, header `x-citadel-cf-tenant: 1`).
- Access: everything except sitemaps/robots is behind a Cloudflare INTERACTIVE managed challenge (Turnstile "Verify you are human", `cf-mitigated: challenge`, HTTP 403). Verified 403 with curl+browser UA for: /careers/, /careers/open-opportunities/, /careers/details/<slug>/, /wp-json/, /wp-json/wp/v2/career, /wp-admin/admin-ajax.php. The built-in browser also got stuck on the Turnstile checkbox (not solved: bypassing CAPTCHA is out of bounds).
- httpx-feasible: NO for listings/descriptions. PARTIAL for discovery only (sitemaps are open, 200).
- Scrapling (stealth) might pass the challenge: UNVERIFIED. Treat as high-risk/flaky; also ToS/ethics concern about bypassing bot protection.
- HK jobs currently: could not be determined (job pages unreadable). Sitemap slugs contain no "hong-kong"/"hk" token on either site.

## Endpoint recipe (what works without a browser)
- robots: https://www.citadel.com/robots.txt -> `Crawl-delay: 10`, `Disallow: /cdn-cgi/` only; lists both sitemap_index.xml.
- Sitemap index: `https://www.citadel.com/sitemap_index.xml` and `https://www.citadelsecurities.com/sitemap_index.xml` (200 via curl) -> `career-sitemap.xml` (+ career-perspectives, not jobs).
- Job URL pattern: `https://www.<site>/careers/details/<slug>/` ; Citadel: 63 URLs, Citadel Securities: 78 URLs (as of today).
- Each sitemap `<url>` has `<lastmod>` (ISO, e.g. 2026-10-28T01:14:14+00:00; appears to be bulk-touched = crawl/refresh time, NOT a posted date) and hreflang alternates.
```
curl -s -A "Mozilla/5.0" https://www.citadelsecurities.com/career-sitemap.xml | grep -o '<loc>[^<]*'
```
- Listing UI is at /careers/open-opportunities/ (filters by location/team are client-side XHR to an unknown endpoint: UNVERIFIED, could not load past challenge).

## HK filter
- UNVERIFIED. Slug heuristics only: Citadel Securities uses region tokens in slugs (`...-asia`, `-us-new-york`, `-us-miami`) e.g. `quantitative-researcher-phd-graduate-asia`, `quantitative-trading-intern-asia` (APAC roles, likely HK/Singapore/Sydney; location only visible on the detail page). Citadel (hedge fund) HK roles would need page fetch.
- Must read the location field on each detail page (behind challenge).

## Pagination
- Sitemap: none (single file, all jobs). Listing UI pagination: UNVERIFIED.

## Mapping to Job fields
- source: "citadel" / "citadel_securities"; company_slug: citadel / citadel-securities
- source_id: slug from URL (only stable ID seen without page access; WordPress post slug). Real numeric ID UNVERIFIED.
- url: `https://www.<site>/careers/details/<slug>/` (apply link likely on page; UNVERIFIED; likely external ATS form).
- title/locations/description_raw/posted_at: UNVERIFIED (page blocked). posted_at: no source known; sitemap lastmod is not reliable.

## Samples
Sitemap rows (verified):
- https://www.citadel.com/careers/details/equities-engineering-product-frontend-engineer-new-york/
- https://www.citadelsecurities.com/careers/details/quantitative-researcher-phd-graduate-asia/
- https://www.citadelsecurities.com/careers/details/quantitative-trading-intern-asia/
No HK job JSON/HTML sample obtainable.

## Risks
- Cloudflare interactive challenge blocks all HTML/JSON; fingerprint/cookie (`cf_clearance`) required and short-lived.
- Crawl-delay 10s per robots.
- Slug-only discovery cannot filter to HK; needs a challenge-capable fetcher (Scrapling StealthyFetcher / real browser with human-solved cookie) - UNVERIFIED.
- Alternatives worth checking by the caller: third-party aggregators/Google Jobs JSON-LD (not checked), or manual cf_clearance cookie reuse.
- Recommended: mark Citadel as "blocked / needs stealth browser"; at most use sitemap lastmod to detect new slugs, then fetch details with Scrapling if allowed.
