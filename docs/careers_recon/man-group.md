# Man Group / Man AHL - careers recon (2026-10-28)

## Summary
- ATS: **Greenhouse** (EU-hosted board token `mangroup`). man.com/careers links out to `job-boards.eu.greenhouse.io/mangroup`.
- Access: public Greenhouse Job Board API, plain httpx, no auth/cookies. **httpx-feasible: YES.**
- HK jobs right now: **0 of 65** (verified). Locations seen: London 24, Sofia 12, New York 7, Shanghai 4, China 3, Boston, Fort Worth, Pfaffikon, Seattle, Massachusetts. No Hong Kong/APAC entry (the offices list may have an HK office, but with no jobs). The existing eFinancialCareers fallback (1 HK job, 2026-07-14) is therefore likely a role not currently on Greenhouse; a Greenhouse feed would replace it only when HK roles are posted. Recommend adding Greenhouse as an additional source and keeping the eFC fallback.

## Endpoint recipe
```
GET https://boards-api.greenhouse.io/v1/boards/mangroup/jobs?content=true
```
No special headers needed (200, ~876 KB, all jobs in one response). Verified with curl.
Per-job detail (optional): `GET https://boards-api.greenhouse.io/v1/boards/mangroup/jobs/{id}`. Offices: `.../v1/boards/mangroup/offices`.

## HK filter
Client-side only (no server filter). Case-insensitive match of "hong kong" or "HK" in `location.name`, also check `offices[].name` and the `metadata` "Primary Location" value (format e.g. `GB London Riverbank House`, so an HK one would likely be `HK Hong Kong ...`; UNVERIFIED since none exist). Location strings are messy: trailing spaces ("Shanghai "), `;` separators for multi-location ("Boston; New York"). Split on `;` and strip.

## Pagination
None: response `{"jobs":[...],"meta":{"total":65}}` returns everything. Assert `len(jobs)==meta.total`.

## Field mapping (Job)
- source=`greenhouse`, source_id=`str(id)` (e.g. 5003542101); requisition_id (JR007440) is an alternate stable ID.
- url=`absolute_url` (https://job-boards.eu.greenhouse.io/mangroup/jobs/{id}); is the apply page.
- title=`title`; company "Man Group" (company_name).
- description_raw=`content` (inline with content=true). NOTE it is HTML-entity-escaped (`&lt;div...`): run html.unescape once to get HTML, then strip for description_clean.
- locations=split(`location.name`) ; also `offices[].name`.
- posted_at=`first_published` (ISO with offset); `updated_at` also available. `application_deadline` is usually null.
- Extra: departments[].name (e.g. Operations, AHL), metadata.

## Samples
HK: none. Representative (non-HK) record: id 5003542101, "Analyst, Solutions Middle Office", location.name "London", first_published "2026-10-14T03:40:01-04:00", requisition_id JR007440, offices [{"id":4015744101,"name":"London"}], metadata [{"name":"Primary Location","value":"GB London Riverbank House"}].

## Risks
- Currently zero HK jobs, so adapter will emit nothing until Man posts in HK; keep eFC fallback.
- Location strings inconsistent (spaces, `;`, country-only "China"); HK roles might be labelled "Hong Kong, China" or just "APAC" - match loosely.
- content is double-escaped HTML.
- Board token could move between boards-api.greenhouse.io hosts/EU; the boards-api host worked for the EU board in testing. robots.txt on greenhouse returned 200; API is documented as public. No rate limiting seen in 3 requests.
- Repo has no generic greenhouse adapter yet (adapters: workday, eightfold, successfactors, ...); one is needed, or a generic config-driven one (board token `mangroup`).
