# Flow Traders careers recon (slug: flow-traders)

Recon date 2026-10-28. All claims below verified with plain curl unless marked UNVERIFIED.

## Summary
- ATS: **Greenhouse** (board token `flowtraders`). flowtraders.com/careers is an Umbraco site that calls the public Greenhouse Boards API client-side (CSP connect-src allows boards-api.greenhouse.io; page source references `boards-api.greenhouse.io/v1/boards/flowtraders/jobs?content=true`). Canonical apply pages live at job-boards.greenhouse.io/flowtraders/jobs/<id>.
- Access: public JSON, no auth, no cookies, no special headers. **httpx-feasible: YES.** No browser/Scrapling needed.
- Current state: 47 jobs total, **12 with location "Hong Kong"** (+4 multi-office postings that list Hong Kong office but have primary location New York/Amsterdam).

## Endpoint recipe
```
GET https://boards-api.greenhouse.io/v1/boards/flowtraders/jobs?content=true
```
No headers required (default UA works). Returns `{"jobs":[...], "meta":{"total":47}}`, whole board in one response (~ few hundred KB). `content=true` inlines the HTML description, so no per-job call is needed.
Optional single job: `GET .../v1/boards/flowtraders/jobs/<id>` (same fields incl. content; also `?questions=true` exists, not needed).

## HK filter
Client-side only (no server filter). Primary field `location.name` (exact strings seen: `Hong Kong`, `New York`, `Amsterdam`, `Amsterdam ` and `London ` with trailing whitespace, `London`, `Chicago`). **Strip whitespace before compare.**
Recommended rule: keep job if `any(o["location"].strip() == "Hong Kong" for o in job["offices"])` OR `location.name.strip()=="Hong Kong"`. Offices entry: `{"id":26355,"name":"Hong Kong office","location":"Hong Kong"}`. Verified the two rules differ: 4 jobs (ids 7862011, 8278361, 8156203, 8266897; Digital Assets Trader / PhD Graduate Quantitative Researcher) have location New York or Amsterdam but offices include Hong Kong. Decide whether to include these; the union gives 16. Offices-based rule is the more faithful one (they are genuinely open in HK; 7770955 and 8213037 are the same roles listed with location Hong Kong). Beware duplicates of the same title across ids.
`locations` for Job: `[o["location"] for o in offices]` (e.g. "Amsterdam, Noord-Holland, Netherlands", "Hong Kong", "New York, New York, United States") or just ["Hong Kong"] if only HK is relevant.

## Pagination
None. Single response contains all jobs (`meta.total` = 47 = len(jobs)). Greenhouse supports no page params on this endpoint; assert `len(jobs)==meta.total`.

## Mapping to Job fields
| Job field | Source |
|---|---|
| source | "greenhouse" |
| source_id | `str(job["id"])` (stable; `internal_job_id` is a different, requisition-level id, 3573491 etc.; `requisition_id` e.g. "1609" is non-unique, shared by similar roles) |
| url | `job["absolute_url"]` = https://job-boards.greenhouse.io/flowtraders/jobs/<id> (verified format; apply form is on that page) |
| title | `job["title"].strip()` (trailing spaces seen) |
| description_raw | `html.unescape(job["content"])` — content is HTML-entity-escaped (`&lt;p&gt;`), must unescape once to get real HTML |
| description_clean | strip tags from the unescaped HTML |
| locations | see HK filter |
| posted_at | `first_published` (ISO 8601 with offset, e.g. `2026-03-11T22:23:52-04:00`) ; `updated_at` is last edit, not posting date. Caveat: reposted/refreshed roles keep old first_published (4003450 shows 2022-03-04, still live) |
| extras | `departments` (may be empty), `metadata` list: Division (Trading/Technology/Events/Business Support), Start Date, Contact, High priority; `company_name` |
Salary: not in API (UNVERIFIED whether description text mentions pay; none inspected).

## Samples (real, trimmed)
```json
{"id":7431246,"title":"Senior Research Engineer","location":{"name":"Hong Kong"},
 "absolute_url":"https://job-boards.greenhouse.io/flowtraders/jobs/7431246",
 "first_published":"2025-11-30T21:30:37-05:00","updated_at":"2026-10-20T05:17:56-04:00",
 "requisition_id":"1560","internal_job_id":null,
 "offices":[{"id":26355,"name":"Hong Kong office","location":"Hong Kong"}],
 "metadata":[{"name":"Division","value":"Technology"},{"name":"Contact","value":"Christy Wong\nRecruiter\nHong Kong\n+852 2593 3050\ncareers.hongkong@hk.flowtraders.com"}],
 "content":"&lt;p&gt;Flow Traders is looking for a Senior Research Engineer to join our&lt;em&gt; &lt;/em&gt;Hong Kong&amp;nbsp;office. ..."}
```
Other HK ids: 8222298 Experienced MFT Quantitative Researcher (first_published 2026-09-21), 8102618 Trading Intern (2026-08-04), 7708220 Delta One Trader, 7770955 Digital Assets Trader (offices AMS/HK/NY), 7978456 Operations Specialist, 8213037 PhD Graduate Quant Researcher, 7064123 Python Engineer Trading Automation, 8168790 Risk Manager, 6993714 Senior SWE C++, 8212740 Senior SWE C++ (Market Data), 4003450 Experienced Quantitative Researcher.
(internal_job_id value for 7431246 not recorded in this note; other jobs e.g. 8258529 had 3573491.)

## Risks
- Entity-escaped `content` (double-decode risk: unescape exactly once; `&amp;nbsp;` inside becomes `&nbsp;`).
- Trailing whitespace in titles/location names; use strip().
- Multi-office postings: primary `location.name` can omit HK; use offices. Possible near-duplicate postings (same title, different id) — dedupe by source_id only.
- `first_published` unreliable as "new" signal for evergreen roles.
- Board token or move to another ATS would 404 (`{"status":404,"error":"Job not found"}`); fail loudly if `meta.total != len(jobs)` or jobs empty.
- robots.txt on flowtraders.com disallows only admin paths (/bin, /umbraco, etc.); the Greenhouse API is the public, documented board API intended for this use. No rate limiting or anti-bot observed (Cloudflare fronts flowtraders.com only). One request per run suffices.
