# Two Sigma careers recon (slug: two-sigma)

Recon date 2026-10-28. All claims below verified with plain curl/httpx (no cookies, no browser) unless marked UNVERIFIED.

## Summary
- ATS: **Avature** (portal 106, hosted at `careers.twosigma.com`, tenant `twosigma.avature.net`). `www.twosigma.com/careers/` is a WordPress marketing page that just links to `https://careers.twosigma.com`.
- Access: server-rendered HTML list pages + HTML detail pages. No JSON API, no JSON-LD, no GraphQL.
- httpx-feasible: **YES** (no anti-bot hit on a normal browser UA; Cloudflare in front of www only sets a `__cf_bm` cookie).
- **Hong Kong jobs currently: 0** of 62 open roles (locations seen: US NY New York, US TX Houston, UK London, Japan Tokyo). Two Sigma has an HK office (listed in footer), so HK roles may appear later.

## Endpoint recipe
List: `GET https://careers.twosigma.com/careers/OpenRoles?jobRecordsPerPage=10&jobOffset={0,10,20,...}`
- Headers: only `User-Agent: Mozilla/5.0` used. No cookies/auth.
- Each job is `<article class="article article--result" id="article--N">`:
  - `h3.article__header__text__title a.link[href]` -> detail URL; link text -> title
  - `span.paragraph_inner-span` #1 -> location string, #2 -> Function, #3 -> Experience level (e.g. `Engineering`, `Experienced`)
- Detail: `GET https://careers.twosigma.com/careers/JobDetail/<slug>/<numericId>` (200, ~55-60KB).
  - `<title>` = `"<Title> - <City> - Two Sigma Careers"`.
  - Page has 3 `<section class="section js_views">`-ish blocks: (a) section with `article--details` holding title + `Location` label (city) + country; (b) description section: `article--details` with unlabeled `div.article__content__view__field__value` containing HTML (intro paragraphs + `<ul><li>` responsibilities/qualifications); (c) labeled fields Business / Function / Experience Level.
  - Description recipe: take the `section` that contains `<li>` (the last `section.js_views`), concatenate inner HTML of all `div.article__content__view__field__value` in it -> `description_raw`.
- Apply URL: `https://careers.twosigma.com/careers/Login?jobId=<id>` (login-gated; use the JobDetail URL as canonical `url`).
- Sitemap `https://careers.twosigma.com/careers/sitemap.xml` does NOT list JobDetail pages (only static pages); not usable.

## HK filter
- Client-side: keep articles whose location span contains `Hong Kong` (case-insens.) or whose URL slug starts with `Hong-Kong`. Observed location format on list: `"<Country> - <State/Region> <City>"` e.g. `United States - NY New York`, `United Kingdom - UK London`, `Japan -  Tokyo` (note double space). Expected HK format UNVERIFIED (probably `Hong Kong - Hong Kong` or `China - HK Hong Kong`), so match substring "hong kong" or "HK" token. Slug examples: `New-York-New-York-United-States-...`, `Tokyo-New-York-Japan-...`.
- Server-side facet exists: form field `5084` = Location (`?5084=<optionId>&listFilterMode=1`), same pattern as Function `5085` which uses numeric ids (e.g. `?5085=16718776&listFilterMode=1`). Location option ids are populated by JS; **not discovered** (UNVERIFIED). Passing `5084=Hong+Kong` text did not filter (still 10 results/page). Since total is ~62, just crawl all and filter client-side.

## Pagination
- `jobRecordsPerPage` is effectively fixed at 10 (100 ignored). Use `jobOffset` multiples of 10.
- Observed: offsets 0-50 give 10 each, offset 60 gives 2, offset >=70 returns a single non-job `article--result` (empty-state) with no JobDetail links. Stop when a page yields zero `JobDetail` links. Total 62 unique ids. No total-count element found in HTML; derive from crawl.
- Pagination links look like `OpenRoles/?jobRecordsPerPage=10&jobOffset=10`. Ordering is not stable across offsets? Ids appeared unique per page; dedupe by id anyway.

## Mapping to Job fields
- source: `avature` (or `two_sigma`); company: Two Sigma; company_slug: `two-sigma`
- source_id: trailing numeric id of JobDetail URL (e.g. `14322`)
- url: JobDetail URL
- title: list link text (or detail `<title>` / first field value)
- locations: detail `Location` field city + country (e.g. `Tokyo`, `Japan`), or list span
- department: `Function` label value; business unit `Business` (e.g. Investment Management); seniority hint: `Experience Level` (`Experienced`, Campus/Intern appear in titles)
- description_raw: HTML per recipe above; description_clean: strip tags
- posted_at: **not available** (no date on list/detail; no JSON-LD). Leave None; use first-seen.
- salary: not present in list/detail text sampled (UNVERIFIED for US roles that may carry pay ranges).

## Samples
List article (trimmed):
```html
<article class="article article--result" id="article--1">
 <h3 class="article__header__text__title title title--065">
  <a class="link" href="https://careers.twosigma.com/careers/JobDetail/New-York-United-States-AI-Fluency-Program-Manager/14291">AI Fluency: Program Manager</a></h3>
 <span class="paragraph_inner-span">United States - NY New York</span>
 <span class="paragraph_inner-span">Engineering</span>
 <span class="paragraph_inner-span">Experienced</span>
```
Detail (no HK available; Tokyo APAC sample): `JobDetail/Tokyo-New-York-Japan-Data-Operations-Analyst-Global-Data-Operations-Tokyo/14322` -> title "Data Operations Analyst - Global Data Operations (Tokyo)", Location "Tokyo", "Japan", Business "Investment Management", Experience "Experienced", description `<div><div><strong>You will take on the following responsibilities:</strong></div><div><ul><li>Investigate and remediate production alerts ...`.

## Risks
- robots.txt: `Allow: /careers`, `Disallow: /careers/*qtvc=` (avoid that param). Crawl politely (<=1 req/s; ~7 list + N detail requests).
- HTML scraping tied to Avature CSS classes (`article--result`, `paragraph_inner-span`, `article__content__view__field__value`); template change breaks it. Span positions (location/function/experience) could shift if a field is empty; prefer detail page labels.
- No HK jobs now; HK location string unverified; no posted date; no per-job API.
- Locale/region variants: URL slugs contain city names and can change with title edits, so key on numeric id.
- Fallback if blocked: Scrapling; not needed so far.

## Pseudocode
```
off=0
while True:
  html=get(OpenRoles,params={jobRecordsPerPage:10,jobOffset:off})
  links=re.findall(r'href="(https://careers.twosigma.com/careers/JobDetail/[^"]+/(\d+))"',html)  # dedupe
  if not links: break
  collect (url,id,title,loc_spans); off+=10
hk=[j for j in jobs if 'hong kong' in loc.lower() or '/Hong-Kong' in url]
for j in hk: fetch detail, parse description
```
