# Hudson River Trading (hudson-river-trading) – careers recon (2026-10-28)

## Summary
- ATS: **Greenhouse** (public Job Board API). Board token: **`wehrtyou`** (NOT `hudsonrivertrading`, which 404s).
- Careers site www.hudsonrivertrading.com is WordPress behind Cloudflare; plain curl (even with browser UA) gets **403**. Do not scrape it. The Greenhouse API host is open.
- httpx-feasible: **YES** (no cookies, no auth, no special headers; verified with curl).
- Currently 86 jobs total; **3 jobs touch Hong Kong** (1 with location "Hong Kong", 2 listed with location "Singapore" but offices include Hong Kong).

## Endpoint recipe
Single request returns everything incl. descriptions:
```
GET https://boards-api.greenhouse.io/v1/boards/wehrtyou/jobs?content=true
```
Response: `{"jobs":[...], "meta":{"total":86}}`. No pagination. Per-job detail (optional): `GET https://boards-api.greenhouse.io/v1/boards/wehrtyou/jobs/{id}` (200, same fields, full content). `/offices` also exists (departments/jobs per office, HK office id 109397).
Add `?questions=true` not needed.

## HK filter
Client-side. location.name is a free-text string and is NOT reliable for multi-office roles (Hong Kong office roles can show location "Singapore"). Use:
`any("hong kong" in o["name"].lower() for o in job["offices"]) or "hong kong" in job["location"]["name"].lower()`
Observed strings: location.name = "Hong Kong"; offices[].name = "Hong Kong" (id 109397), "Singapore" (id 5226). Other location strings are semicolon-joined city lists ("London, United Kingdom; New York, NY, United States").
Result today: ids 6345536 (loc "Hong Kong"), 7566004 and 1229082 (loc "Singapore", offices [Hong Kong, Singapore]). Decision for the Job.locations: use offices[].name for the list (e.g. ['Hong Kong','Singapore']).

## Pagination
None; one response holds all jobs (86). meta.total = len(jobs). Sanity check that equality.

## Mapping to Job
- source: "greenhouse"; source_id: str(job["id"]) (e.g. "6345536"); also internal_job_id (804727) and requisition_id ("17") exist but id is the stable one used in URLs.
- company: "Hudson River Trading" (company_name field); company_slug "hudson-river-trading".
- title: job["title"] (strip; has trailing space e.g. "Software Engineer - Low Level (C++) ").
- url: job["absolute_url"] = https://www.hudsonrivertrading.com/careers/job/?gh_jid={id} (canonical; the site page itself is Cloudflare-blocked to bots, but it is the apply URL for users).
- description_raw: html.unescape(job["content"]) (content is HTML-entity-escaped HTML: `&lt;p&gt;...`); description_clean: strip tags after unescape.
- locations: offices[].name (fallback: location.name split on ";").
- posted_at: job["first_published"] (ISO with offset, e.g. 2024-10-22T13:01:13-04:00); updated_at is last edit (2026-10-01T10:37:16-04:00) - do not use as posted date. Note first_published may reflect original publication, possibly old.
- Extras: departments[0].name ("Trading Tech"), metadata (Employment Type "Full-Time", Job Type, Job Category e.g. "Software Engineering:C++"); metadata values may be string, list, or null (mixed types - handle). application_deadline null. Salary: none in structured fields (UNVERIFIED whether in content text).

## Samples (HK, truncated)
```json
{"id":6345536,"internal_job_id":804727,"requisition_id":"17","title":"Software Engineer - Low Level (C++) ",
 "absolute_url":"https://www.hudsonrivertrading.com/careers/job/?gh_jid=6345536",
 "location":{"name":"Hong Kong"},
 "offices":[{"id":109397,"name":"Hong Kong"},{"id":5226,"name":"Singapore"}],
 "departments":[{"id":75196,"name":"Trading Tech"}],
 "first_published":"2024-10-22T13:01:13-04:00","updated_at":"2026-10-01T10:37:16-04:00",
 "metadata":[{"name":"Employment Type","value":"Full-Time"},{"name":"Job Category","value":["Software Engineering:C++"]}],
 "content":"&lt;p&gt;&lt;span style=&quot;font-weight: 400;&quot;&gt;We are looking for engineers to power Hudson River Trading&#39;s continued expansion ... based out of our Hong Kong office ..."}
```
Also: 7566004 "Software Engineer - Distributed Compute" (location "Singapore", offices HK+SG); 1229082 "Software Engineer - Low Level (C++)" (location "Singapore", offices HK+SG).

## Risks
- Wrong board token (`hudsonrivertrading` 404s); token `wehrtyou` could change (UNVERIFIED stability; careers page embeds it).
- Location-name-only filtering would miss 2 of 3 HK jobs; must check offices[].
- Content is double-encoded (entity-escaped HTML): unescape once.
- Multi-office roles: same title may appear multiple times with different ids per region; dedupe by id only.
- Few HK jobs (3) and counts fluctuate; zero results is plausible, so don't treat empty as error if meta.total > 0.
- Cloudflare blocks the marketing site; never fetch absolute_url for descriptions.
- robots.txt on hudsonrivertrading.com disallows /wp-json/ and some AI bots (GPTBot, CCBot, Google-Extended); the Greenhouse API is a public documented endpoint. No rate limiting observed (single request, ~10ms upstream); one request per run is plenty.
