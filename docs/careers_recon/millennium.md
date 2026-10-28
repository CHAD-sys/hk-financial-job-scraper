# Millennium Management (mlp.com/careers) recon

Recon date: 2026-10-28. Read-only; all claims below verified with live httpx/curl unless marked UNVERIFIED.

## Summary
- ATS: **Eightfold** (tenant `mlp`, domain `mlp.com`). `https://www.mlp.com/careers/` is a WordPress marketing page behind Cloudflare (plain curl gets 403 "Attention Required"); its "Search jobs" links go to `https://mlp.eightfold.ai/careers?domain=mlp.com`. Student/campus microsite: `https://app.eightfold.ai/careers?domain=mlp.com&microsite=campus-site` (not probed).
- (A Workday tenant `mlp.wd5.myworkdayjobs.com/mlpcareers` also responds 200 but returns total=0: legacy/empty, ignore.)
- Access: public JSON GET, no cookies, no auth, no special headers beyond a normal User-Agent.
- httpx-feasible: **YES**. Existing `hk_jobs/adapters/eightfold.py` (`/api/apply/v2/jobs`, `domain`, `start`, `num`, `location`) maps directly with tenant=`mlp`, domain=`mlp.com`. Never touch www.mlp.com (Cloudflare 403).
- Currently 37 HK jobs (of 223 total).

## Endpoint recipe
Listing (GET):
```
curl -s -A "Mozilla/5.0" "https://mlp.eightfold.ai/api/apply/v2/jobs?domain=mlp.com&start=0&num=10&location=Hong%20Kong"
```
Response: big JSON with `count` (total matching) and `positions[]`; other keys (branding, facets, candidate...) are noise.
Detail (GET, 200 verified):
```
curl -s -A "Mozilla/5.0" "https://mlp.eightfold.ai/api/apply/v2/jobs/755959321326?domain=mlp.com"
```
Returns same fields plus full HTML `job_description` and `urls`.

## HK filter
- Server-side: `location=Hong Kong` -> count 37 (unfiltered = 223). All 37 returned positions contain "Hong Kong, Hong Kong" in `locations`, so the filter was exact in practice. Still apply a client-side guard: `any("Hong Kong" in l for l in locations)`.
- Exact location strings seen: `"Hong Kong, Hong Kong"`; multi-location roles also list `"Singapore, Singapore"`, `"Tokyo, Tokyo, Japan"`, `"Dubai, United Arab Emirates"`, `"Shanghai, Shanghai, China"` (7 of 37 are multi-office). `latlongs` = `22.3193039,114.1693611`.

## Pagination
- `start` (offset) + `num`. **Server caps page size at 10** (num=100 returned 10 rows), so use num=10 and loop `start += len(positions)` until empty or `start >= count`. 37 rows = 4 requests; ids unique across pages (37/37).
- NOTE: existing adapter `_PAGE_SIZE` must be <=10 or it loops wrongly if it assumes its own size; advance by `len(positions)`, not the requested num. (Did not read adapter's constant; CHECK.)
- `sort_by=timestamp` accepted and gives newest-first (verified order of t_create); default relevance order is fine since we fetch all.

## Mapping to Job fields
| Job field | Source |
|---|---|
| source_id | `str(id)` (e.g. 755959321326), stable numeric |
| url | `canonicalPositionUrl` = `https://mlp.eightfold.ai/careers/job/{id}` (also acts as apply URL) |
| title | `name` (== `posting_name`) |
| locations | `locations[]` |
| department | `department` (e.g. Trading, Execution Services); `business_unit` also available (e.g. Equities) |
| posted_at | `t_create` unix seconds UTC (e.g. 1792627200 = 2026-10-22); `t_update` also present |
| description_raw | `job_description` — **EMPTY in listing, only in detail endpoint** (listing sample showed `""`); so one detail GET per HK job (37 calls) is required |
| external req id | `ats_job_id` / `display_job_id` = `REQ-31618` (put in board_signals if wanted) |
| other | `work_location_option` ("onsite"), `hot`, `isPrivate` |
The existing adapter's `_map_position` reads `job_description` from the listing, so for this firm it would yield empty descriptions unless it adds a detail fetch (UNVERIFIED whether adapter already does that; its `_map_position` shown does not).

## Samples
Listing item (description stripped):
```json
{"id":755959285873,"name":"AI Analyst","posting_name":"AI Analyst","location":"Hong Kong, Hong Kong",
 "locations":["Hong Kong, Hong Kong"],"department":"Trading","business_unit":"Equities",
 "t_update":1792454400,"t_create":1792454400,"ats_job_id":"REQ-31583","display_job_id":"REQ-31583",
 "type":"ATS","locale":"en-US","work_location_option":"onsite","isPrivate":false,
 "canonicalPositionUrl":"https://mlp.eightfold.ai/careers/job/755959285873","latlongs":"22.3193039,114.1693611"}
```
Other HK job: id 755959321326 "Quantitative Developer - Central Liquidity Strategies", Execution Services / Quantitative Research & Development, REQ-31618, posted 2026-10-22. Detail `job_description` starts: `Quantitative Developer - ...<p></p><p></p><p><b>About Millennium</b><br />Millennium is a global, diversified alternative investment firm...` (HTML; title is prefixed as plain text, strip or accept).

## Risks
- Description only via per-job detail call; add ~0.3-1s sleep. Total ~41 requests per run.
- Page-size cap of 10 is a server behavior that may change; always advance by returned length.
- Eightfold robots.txt allows `/api/apply` and `/careers`; no rate limiting or bot challenge encountered. www.mlp.com robots.txt has `Crawl-delay: 10` but the site is Cloudflare-blocked for curl and not needed. ToS UNVERIFIED.
- `location=` is a text/fuzzy search param; keep client-side HK guard. Multi-location roles include non-HK offices; keep full list.
- Tenant/domain rename or Eightfold API version change (`v2`) would break; low risk. `count` may include `isPrivate` positions (none seen).
- Detail description begins with duplicated title text; cosmetic.
