# Point72 (careers.point72.com) recon, 2026-10-28

## Summary
- careers.point72.com is a custom Salesforce Visualforce/Experience site (`server: sfdcedge`, paths `/CSCareerSearch`, `/CSJobDetail`, `/CSSitemap`). Not a standard ATS front-end.
- Apply links go to **Greenhouse** (board token `point72`), which is the ATS of record. The public Greenhouse Job Board API lists all 208 jobs, with full HTML description, first_published and updated_at.
- **httpx-feasible: YES.** Recommended: Greenhouse boards-api (clean JSON, one request, no auth, no cookies). Fallback: the SFDC careers page embeds the full job list as a JS string (`CSSearchModule.init('[...]', ...)`), also plain httpx.
- HK jobs on 2026-10-28: 22 on Greenhouse (verified), 22 on the SFDC site (verified, matches).

## Endpoint recipe (primary: Greenhouse)
```
GET https://boards-api.greenhouse.io/v1/boards/point72/jobs?content=true
```
No headers or cookies needed. HTTP 200, ~229 KB, `{"jobs":[...],"meta":{"total":208}}`. No pagination (all jobs in one response). Verified with plain curl.
Optional per-job: `GET https://boards-api.greenhouse.io/v1/boards/point72/jobs/{id}` (UNVERIFIED, standard GH API; not needed since content=true is inline).

Fallback (SFDC page): `GET https://careers.point72.com/CSCareerSearch` (also `/` returns the same page, 1.5 MB). Find `CSSearchModule.init('` and read the JS single-quoted string literal up to the first unescaped `'`. Unescape JS escapes (`\"`, `\\`, `\uXXXX`, `\/`) without eval, then `json.loads` -> list of 208 objects. NOTE: a naive `.replace('\\"','"')` breaks on `’` etc.; decode properly.
Sitemap `https://careers.point72.com/CSSitemap` lists 208 CSJobDetail URLs with lastmod.

## HK filter
Client-side only (no server param).
- Greenhouse: `"hong kong" in job["location"]["name"].lower()` (also `offices[].name == "Hong Kong"`). Location strings are free text and messy: `Hong Kong`, `Hong Kong ` (trailing space), `Hong Kong, Singapore `, `Hong Kong, Japan, Singapore, Central, Singapore`, `Dubai, Paris, Hong Kong, London, Sydney`, `New York, London, or Hong Kong`. Use substring match, then split on `,`/`or` and strip for `locations`. Use `offices[].name` as a cleaner secondary list.
- SFDC: `formattedLocation` uses ` | ` separator (`Hong Kong`, `Hong Kong | Singapore`, `New York | Stamford | London | Hong Kong`); raw `Posted_Location__c` uses `;`.
- Count: 22 HK/multi-location including HK, of which 13 are HK-only (SFDC).

## Pagination
None. Single response contains all jobs (total 208, `meta.total`). Sanity check: assert len(jobs)==meta.total.

## Mapping to Job fields
Greenhouse (primary):
- source="greenhouse" (or "point72"), source_id=str(job["id"]) (e.g. "8905015002"; stable). `requisition_id` (e.g. "2117") is a secondary ref, `internal_job_id` also present.
- url=job["absolute_url"] = `https://boards.greenhouse.io/point72/jobs/{id}?gh_jid={id}` (canonical apply URL; verified in SFDC Apply_Now_URL__c for the same ids).
- title=job["title"] (strip; some have trailing spaces).
- locations=parsed from location.name / offices (see above).
- description_raw=`html.unescape(job["content"])` (content is HTML-entity-escaped, e.g. `&lt;p&gt;`; must unescape once to get real HTML). description_clean = strip tags.
- posted_at=job["first_published"] (ISO8601 with -04:00/-05:00 offset, true first publish date). `updated_at` is the last update (note: all rows show the same 2026-10-22T12:15:32 bulk timestamp, so ignore it).
- Extras: `departments[].name` (team/dept), `metadata` (e.g. Time Type: Part Time), `company_name` ("Point72 ", trailing space), `application_deadline` (null).

SFDC fallback fields: source_id=`job.Job_Code__c` (e.g. IVS-0015472; the SFDC record Id `job.Id` also stable); title=`job.Name`; description_raw=`job.Job_Description_External__c` (HTML, inline); location=`formattedLocation`; date=`job.LastModifiedDate` / `lastModifiedDateFormatted` (this is last-modified, NOT posted date); apply URL=`job.Apply_Now_URL__c` (greenhouse boards URL or `https://grnh.se/<code>` short link; absent on 1 HK job LSI-0014448, so fall back to detail page); detail page `https://careers.point72.com/CSJobDetail?jobName={friendlyJobName}&jobCode={Job_Code__c}` (HTTP 200 with JSON-LD; verified). `Summary__c` sometimes present. `Team__c`, `Area__c`, `Experience__c`, RecordType.Name (Cubist / Investment Services / ...) available.

## Samples
Greenhouse (content truncated):
```json
{"id":8905015002,"title":"Associate, Investment Professional Development ","location":{"name":"Hong Kong"},
 "absolute_url":"https://boards.greenhouse.io/point72/jobs/8905015002?gh_jid=8905015002",
 "first_published":"2026-10-21T02:30:05-04:00","updated_at":"2026-10-22T12:15:32-04:00","requisition_id":"...",
 "offices":[{"id":4041654002,"name":"Hong Kong"}],"content":"&lt;h3&gt;A Career with Point72..."}
{"id":8870206002,"title":"Quantitative Developer","location":{"name":"Hong Kong"},"first_published":"2026-10-06T11:27:11-04:00"}
{"id":8658618002,"title":"AI Data Scientist","location":{"name":"Hong Kong, Singapore "},"first_published":"2026-07-30T11:38:49-04:00"}
```
SFDC embedded record:
```json
{"lastModifiedDateFormatted":"2026-10-21","friendlyJobName":"associate-investment-professional-development",
 "formattedLocation":"Hong Kong","formattedTeam":"Professional Development","formattedArea":"Talent & Engagement",
 "job":{"Id":"a03Vo00002HVOJNIA5","Job_Code__c":"IVS-0015472","Name":"Associate, Investment Professional Development",
  "Posted_Location__c":"Hong Kong","Experience__c":"Experienced Professionals",
  "Job_Description_External__c":"<h3>A Career with Point72...</h3>...",
  "Apply_Now_URL__c":"https://boards.greenhouse.io/point72/jobs/8905015002?gh_jid=8905015002",
  "LastModifiedDate":"2026-10-21T06:49:50.000+0000"}}
```
Current HK titles (22 on GH): Associate Investment Professional Development; Quantitative Developer x2; Equity Financing Trader APAC; International Trade Support Analyst; IS Administrative Assistant; Administrative Assistant; AV Support Specialist; AI Data Scientist; Cubist Business Analyst; Cubist Quantitative Researcher x3; Cubist Portfolio Manager; Point72 Academy programs x3; Analyst Coach IPD; Fund Flow Strategist; Quant Researcher Intern; Quant Researcher ML; Research Technology Support.

## Risks
- Greenhouse board token could change or the board be disabled (low); SFDC page is the backup. The two sources can differ slightly (GH titles have trailing spaces; GH has "Administrative Assistant" vs SFDC "PM Administrative Assistant, Hong Kong"; SFDC has 1 HK job without GH link: LSI-0014448 "Equity Financial Analyst - Asia ex-Japan" HK|Singapore, dated 2026-02-25, not in GH).
  The SFDC list is therefore a superset if complete coverage matters. Id spaces differ (GH numeric id vs SFDC Job_Code); pick one source per job to avoid duplicates, ideally GH id and key SFDC by the gh_jid parsed from Apply_Now_URL where available.
- Free-text location strings (see above); multi-office roles will match HK even if primarily elsewhere (decide policy).
- `content` is entity-escaped; unescape exactly once.
- SFDC page: JS-literal parse is fragile if markup changes (init call, quote escaping); the 1.5 MB payload; `/static/111213/` and `/resource/<ts>/` asset versions rotate (irrelevant to parsing).
- Anti-bot/ToS: no bot challenge, no cookies required; robots.txt on careers site is permissive (`User-agent: * Disallow:` empty) and sitemap provided. Greenhouse boards-api is a public documented API. No rate limit observed with a handful of requests (UNVERIFIED under load). ToS not reviewed.
- Salesforce site sets consent cookies but they are not needed.
