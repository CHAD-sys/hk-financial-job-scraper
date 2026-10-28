# Optiver careers recon (2026-10-28)

## Summary
- ATS: none known. Custom Optimizely (Episerver/CMP) CMS site with React-hydrated components; own JSON endpoint. Apply flow is on-site (`.../apply` suffix), not a third-party ATS (UNVERIFIED what the apply page embeds; not needed).
- Access: plain JSON GET, no cookies, no special headers (a normal User-Agent was used; bare curl UA not tested). httpx-feasible: YES. Scrapling not needed.
- **Hong Kong jobs currently: 0.** 160 live jobs across Amsterdam 34, Shanghai 29, Sydney 27, Chicago 26, New York 11, London 9, Singapore 7, Austin 7, Mumbai 6, Taipei 4. Optiver has an HK office (sitemap has /join-us/locations/hong-kong/ and category pages /join-us/jobs/{trading,strategy,risk-finance-and-legal}/hong-kong/) but no postings now. "hong-kong" is NOT in the site's location filter list.

## Endpoint recipe
`GET https://www.optiver.com/en/api/v1/jobs` (apex optiver.com 301-redirects to www; use www, follow redirects). Returns `{"items":[...], "totalCount":N}`. Page size fixed at 16.
```
curl -sL -A "Mozilla/5.0" "https://www.optiver.com/en/api/v1/jobs?location=hong-kong&from=0"
```
Query params verified: `location=<slug>` (singapore -> 7 items, hong-kong -> `{"items":[],"totalCount":0}`), `department=<slug>`, `level=<early-careers|experienced|graduate|internship>`, `q=<text>` (search; totalCount reflects it), `from=<offset>`. Ignored (no effect): page, pageNumber, pageIndex, skip, offset, take, limit, pageSize, size, count, cursor, search, keyword. Unknown location slug with space (`hong%20kong`) is ignored and returns everything, so always use slug `hong-kong`.

## HK filter
Server-side: `location=hong-kong` (slug guessed from other slugs like `new-york`; returns valid empty result now, so it is UNVERIFIED that it matches once HK jobs exist). Safer: fetch all (10 requests) and client-side filter `item["location"] == "Hong Kong"` (expected label, UNVERIFIED; seen labels are plain city names like "New York", "Singapore") or `"/hong-kong/" in item["href"]` (href format `/join-us/jobs/{department-slug}/{location-slug}/{job-slug}/`). Use both server filter and client check; also alert if totalCount of unfiltered > 0 and no known office slug matches.

## Pagination
Offset via `from`, 16 per page. Loop: `from=0,16,32,...` until `from >= totalCount` or empty items. Verified: 10 pages gave 160 items = totalCount, 160 unique hrefs and componentIDs. Unfiltered `from=16` returned different first item than page 1.

## Mapping to Job fields
List item keys: title, location, experience, domain, href, componentID, jobClickTracking{vacancyName,vacancyOffice,vacancyDomain,vacancyLevel}, culture.
- source = "optiver"; company "Optiver"; company_slug "optiver"
- source_id = `componentID` (CMS page ID, int, stable per page; unique across 160). Fallback: href slug path.
- url = `https://www.optiver.com` + href (canonical; JSON-LD `url` matches). Apply URL = url + `apply` (e.g. `<href>apply`, from SummaryCard cta, verified present in HTML).
- title = item.title; locations = [item.location]
- Extra: experience (level), domain (department).
- posted_at: only on detail page JSON-LD `datePosted` ("2026-10-16", date only). Not in list API.
- description_raw: detail page HTML only. The JSON-LD `description` is EMPTY. Real description is in the hydration script: `React.createElement(Components.RichText,{...,"text":"<p>...</p>..."})` — regex `React\.createElement\(Components\.RichText,(\{.*?\})\)\);` then `json.loads(...)["text"]` gives HTML (6.7k chars for sample). Use first RichText on the page (page has a single one for the sample; check others). description_clean = strip HTML.
- Detail page also has SummaryCard metadata (Level, Location, Department) in the same hydration data.

## Samples
List item (real):
```json
{"title":"Financial Controller","location":"Amsterdam","experience":"Experienced","domain":"Risk, Finance & Legal","href":"/join-us/jobs/risk-finance-and-legal/amsterdam/financial-controller/","componentID":<int>,"culture":"en"}
{"title":"Market Risk Internship 2027 - Singapore","location":"Singapore", ...}
```
No HK sample exists. Detail JSON-LD (real):
`{"@type":"JobPosting","title":"Financial Controller","url":"https://www.optiver.com/join-us/jobs/risk-finance-and-legal/amsterdam/financial-controller/","datePosted":"2026-10-16","hiringOrganization":{"name":"Optiver"},"jobLocation":{"@type":"Place","name":"Amsterdam"},"description":""}`

## Risks
- Undocumented internal API (`apiEndpoint` field in page props says `/en/api/v1/jobs`); params could change. Check `totalCount` equals collected count; fail loudly otherwise.
- Pagination param `from` found by guessing; page-size 16 fixed. Ignored params silently return page 1 (infinite-loop risk): dedupe by componentID and stop on no new IDs.
- HK location label/slug unverified because zero HK jobs. Zero results is likely the legit state, not a bug.
- Description extraction depends on regex over hydration script; JSON-LD description empty. Postings per-detail fetch = 1 request each (low volume for HK).
- Multi-location roles: one item per location in list (unverified for multi-office).
- Anti-bot: Cloudflare in front; plain httpx with browser-like UA worked, no challenge, no rate limit hit over ~40 requests. robots.txt: `User-agent: *`, `Disallow: /externalContentView/` only; /api and /join-us allowed. ToS not reviewed. Be polite (sleep ~0.5s between requests).
- Sitemap https://www.optiver.com/sitemap.xml lists ~233 /join-us/jobs/ URLs (includes category pages) with lastmod; usable as cross-check for HK job URLs (`/join-us/jobs/<dept>/hong-kong/<slug>/`).
