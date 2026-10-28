# Jane Street careers recon (2026-10-28)

## Summary
- ATS: custom front end over Greenhouse data (ids end in `...002`, Greenhouse-style; apply is on janestreet.com, `/join-jane-street/apply/<id>/`). Not a public Greenhouse board API (UNVERIFIED whether boards-api.greenhouse.io/v1/boards/janestreet works; not needed).
- Access: ONE static JSON file, `GET https://www.janestreet.com/jobs/main.json` (678 KB, all offices, descriptions inline). No auth, no cookies, no special headers. Plain curl works.
- httpx-feasible: YES, trivially. Currently 220 jobs, 57 with city `HKG`.

## Endpoint recipe
```
GET https://www.janestreet.com/jobs/main.json     (content-type application/json, cache-control max-age=300, has ETag/Last-Modified)
```
Optional: `GET /jobs/internships.json` = list of CLOSED internships (status "closed"); ignore.
The listing page `/join-jane-street/open-roles/` is an empty shell hydrated by `/assets/pg/open_positions-<hash>.js`, which fetches main.json and also `/static/position-directories.json` (a whitelist of ids; verified it contains all 220 ids, so it is a no-op filter today. NOTE robots.txt has `Disallow: /static/`, so do not fetch it).

Pseudocode:
```
r = httpx.get(URL, headers={"User-Agent": "..."}); jobs = r.json()
hk = [j for j in jobs if j["city"] == "HKG"]
```

## HK filter
Client-side on field `city`. Codes seen across file: NYC 89, LDN 58, HKG 57, SGP 14, CHI 1, ATX 1. Hong Kong = exactly `"HKG"` (site JS maps HKG -> "Hong Kong"). Site JS also knows a multi-city value `"NYC/HKG"` (not present today); safest filter: `"HKG" in city.split("/")`. Map to locations=["Hong Kong"].
HK availability today: Full-Time: Experienced 40, Summer Internship 10, Full-Time: New Grad 7.

## Pagination
None. Single response, whole list. Total = len(array). IDs unique (220/220).

## Field mapping (raw -> Job)
- source = "janestreet" (custom); source_id = str(`id`) (int, stable Greenhouse job id)
- title = `position` (WARNING: some titles use homoglyph characters, e.g. "ꓟachine ꓡearning ꓣesearcher" with Lisu letters U+A4DF etc. Normalize via NFKC does NOT fix these; consider mapping Lisu look-alikes (ꓟ->M, ꓡ->L, ꓣ->R) or fall back to the detail page `<title>`. Seen on internship rows; verify per run.)
- url = `https://www.janestreet.com/join-jane-street/position/{id}/` (detail page, HTTP 200 plain curl, `<title>AV Engineer, Hong Kong :: Jane Street`). Apply URL = `https://www.janestreet.com/join-jane-street/apply/{id}/`. Note robots.txt disallows ONE specific position id (7304961002); skip it.
- description_raw = `overview` (HTML, inline, non-empty for all 57 HK; starts with `<h3>About the Position</h3>` or `<p><strong>About the position</strong>`); description_clean = strip HTML (contains `&nbsp;`/`&#39;` entities, unescape).
- locations = ["Hong Kong"] from `city`
- department/category = `category`; team = `team`
- employment type / seniority = `availability` ("Full-Time: Experienced", "Full-Time: New Grad", "Summer Internship"); `duration` ("Permanent", "May-August")
- salary: `min_salary`, `max_salary` present but null for HK rows (checked first rows; some other offices may populate).
- posted_at: NOT AVAILABLE in main.json or detail page (no ld+json datePosted found). Leave None; use first-seen date.

## Samples (HK, overview truncated)
```json
{"id":7979592002,"position":"AV Engineer","category":"Technology","availability":"Full-Time: Experienced","city":"HKG","overview":"<h3>About the Position</h3>\n<p>We are looking for an Audio/Video (AV) Engineer ...","team":"IT and Systems Engineering","duration":"Permanent","min_salary":null,"max_salary":null}
{"id":8469230002,"position":"Campus Recruiter","category":"HR and Recruiting","availability":"Full-Time: Experienced","city":"HKG","overview":"<h3>About the Position</h3>\n<p>We are looking for an experienced Campus Recruiter ...","team":"Recruiting","duration":"Permanent","min_salary":null,"max_salary":null}
{"id":8596771002,"position":"ꓟachine ꓡearning ꓣesearcher","category":"Trading, Research, and Machine Learning","availability":"Summer Internship","city":"HKG","overview":"<p><strong>About the position</strong></p>...","team":"Machine Learning","duration":"May-August","min_salary":null,"max_salary":null}
```

## Risks
- Undocumented internal file; could be renamed/moved (JS fetches "/jobs/main.json"; re-check the open_positions JS if 404).
- No posted date. Homoglyph titles. Internship rows may be seasonal/closed pools (internships.json lists closed ones; main.json rows are open).
- Possible multi-city codes like "NYC/HKG". Cache 5 min; poll no more than that.
- Anti-bot: none seen with default curl UA (nginx, no challenge). robots.txt allows /jobs/ and /join-jane-street/position/ (except one id). ToS not reviewed (UNVERIFIED). Only 1 request needed; detail fetch unnecessary since description is inline.
