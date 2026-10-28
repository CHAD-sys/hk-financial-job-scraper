# Squarepoint Capital - careers recon (verified 2026-10-28)

## Summary
- ATS: **Greenhouse** (public Job Board API), board token `squarepointcapital`. The marketing site (squarepoint-capital.com, Next.js SPA) only wraps it: `/open-opportunities` renders client-side from `https://boards-api.greenhouse.io/v1/boards/squarepointcapital/` (found in `_next/static/chunks/app/(open-opportunities)/layout-*.js`).
- Access: plain JSON GET, no auth, no cookies, no special headers. httpx-feasible: **YES** (no browser/Scrapling needed).
- Currently 91 jobs total; 19 flagged Hong Kong by office (17 by location string). `/careers` is 404; real pages are `/open-opportunities`, `/early-careers`, `/experienced-professionals`.

## Endpoint recipe
```
GET https://boards-api.greenhouse.io/v1/boards/squarepointcapital/jobs?content=true
```
Returns `{"jobs":[...], "meta":{"total":91}}`, ~690 KB, description included inline (HTML, entity-escaped). Verified with plain curl (200).
Optional per-job: `GET .../jobs/{id}` (200, same fields, same escaped `content`); not needed since `content=true` is inline.
```python
r = httpx.get(URL, params={"content":"true"}, timeout=30); r.raise_for_status()
for j in r.json()["jobs"]:
    if not is_hk(j): continue
    desc = html.unescape(j["content"])   # content is HTML-escaped (&lt;p&gt;); unescape once -> real HTML
```

## HK filter
Client-side only (no server param). Use the union:
- `any(o["name"] == "Hong Kong" for o in j["offices"])` (19 jobs; offices[].name is clean; HK office id 63648), OR
- regex `hong\s*kong|honk\s*kong` (case-insens.) on `j["location"]["name"]` (17 jobs; the data contains the typo "Honk Kong", job 3277003).
- Offices and location string disagree for 2 jobs (6099883, 7006450, "Network Specialist - ULL" location is "Montreal, London, New York" but offices include HK). Prefer `offices` as truth; log the discrepancy. Union = 19.
- Most HK jobs are multi-location (e.g. "London, Montreal, Singapore, Honk Kong"); only 1 is HK-first ("Hong Kong, Singapore"). Location strings are free text with stray spaces, "&", "and" separators; `locations` field for Job: use `[o["name"] for o in j["offices"]]` (clean list) rather than splitting the string.

## Pagination
None. All jobs returned in one response; `per_page`/`page` params are ignored (per_page=5 still returned 91). Total in `meta.total`. Assert `len(jobs)==meta.total`.

## Mapping to Job fields
- source = "greenhouse"; source_id = `str(j["id"])` (e.g. 8002291; stable). `requisition_id` (e.g. "101893", "R-100627") and `internal_job_id` are secondary.
- company "Squarepoint Capital"; slug "squarepoint".
- title = `j["title"].strip()` (trailing spaces seen).
- url = `j["absolute_url"]` = `https://www.squarepoint-capital.com/open-opportunities?id=<id>&gh_jid=<id>` (opens the SPA with the job; canonical apply link). Alternative form `https://www.squarepoint-capital.com/opportunity-details?id=<id>&gh_jid=<id>` is used by the site's own code (200). `job-boards.greenhouse.io/squarepointcapital/jobs/<id>` 302s.
- description_raw = `html.unescape(j["content"])`; description_clean = strip tags.
- locations = offices[].name (see above).
- posted_at = `first_published` (ISO with offset, e.g. "2026-09-11T06:53:55-04:00"). Can be null for some jobs (observed a None) - guard it, fallback `updated_at` (always present). Note first_published can be years old for re-used reqs (2019-2026 seen), so it may not reflect a repost.
- Extras: `departments[0].name` (Investment, Technology...), `metadata` "Employment Type" (Employee-Regular/Full-time) and "Job Board Experience Level" (Experienced Professional / Early Careers Opportunity).

## Samples (trimmed)
```json
{"id":8002291,"title":"APAC Delta One Trader","requisition_id":"101893","internal_job_id":3469767,
 "location":{"name":"Hong Kong, Singapore"},
 "offices":[{"id":63648,"name":"Hong Kong"},{"id":14634,"name":"Singapore"}],
 "departments":[{"id":86658,"name":"Investment"}],
 "first_published":"2026-09-11T06:53:55-04:00","updated_at":"2026-09-11T06:53:55-04:00",
 "absolute_url":"https://www.squarepoint-capital.com/open-opportunities?id=8002291&gh_jid=8002291",
 "metadata":[{"name":"Employment Type","value":"Employee-Regular"},{"name":"Job Board Experience Level","value":"Experienced Professional"}],
 "content":"&lt;p&gt;&lt;strong&gt;Position Overview:&lt;/strong&gt;&lt;/p&gt;\n&lt;ul&gt;..."}
```
Other HK jobs: 2546549 Desk Quant Analyst (location "London, Madrid, Montreal, Bangalore, Singapore, Hong Kong, Warsaw", first_published 2020-12-21); 6100081 Graduate Trading Applications Specialist. Full HK list (19 ids incl.): 8002291, 2546549, 6100081, 243853 Intern Quant Researcher, 239376 / 6069464 Junior Quant Researcher, 7006450 Network Specialist - ULL, 6212084 Platform Application Specialist, 3277003 Quant Developer (KDB), 1433622 Quant Developer (Python), 6099883, ...

## Risks
- Greenhouse public API is stable and documented; low-risk. No rate limit hit; robots.txt on squarepoint-capital.com is Allow: /; API is the intended public feed. No anti-bot seen.
- Location text is dirty (typo "Honk Kong", 2 office/location mismatches) - use offices union; HK jobs are mostly global multi-office reqs (apply-once talent-pool style postings, many duplicates by title), so dedupe by `id` only.
- `content` double-escaped HTML: unescape exactly once.
- `first_published` may be null/old. No salary fields; no pagination.
- Board token or site could change if they migrate ATS (re-check the layout chunk for `boards-api.greenhouse.io`). If a repo greenhouse adapter exists, config only: token `squarepointcapital`.
