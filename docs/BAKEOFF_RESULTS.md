# LP-0 — Vendor Bake-off Results

**Date:** 2026-07-19
**Verdict: Apify (HarvestAPI actors). Piloterr disqualified before spend — see below.**
**Total cost: $0.21** (well under the ~$5 budgeted)

## Why Piloterr was disqualified without a live test

Checked the user's actual active endpoint catalog on Piloterr (not marketing pages):

```
company/info  finder-linkedin-industries  job-count  job-info
job-search    job-suggest   post/info     product-info   profile-info
```

No endpoint lists a profile's/company's recent posts, and no endpoint searches posts by
keyword. `post/info` requires a post ID/URL you already have — it's an enrichment
endpoint, not a discovery one. `job/*` is LinkedIn's Jobs board (already covered by the
existing `adapters/linkedin.py`), not posts. A marketing page for "Advanced Post
Search" exists but is not in the live catalog and other sources note it's suspended.
Since discovery (watchlist polling + keyword search) is the entire mechanism the
pipeline depends on, spending money to confirm this further wasn't worthwhile — the
catalog itself is conclusive. Piloterr `post/info` stays on the shelf as a possible
future enrichment step only (e.g. re-verify a post surfaced by another channel).

## Apify test 1 — `harvestapi/linkedin-profile-posts` (watchlist simulation)

**Input:** 10 real HK finance recruiter profile URLs (Hays, Selby Jennings, Morgan
McKinley — sourced from each agency's own public team pages), `maxPosts=10`, no
reactions/comments scraping.

**Result:** 90 posts returned across 8/10 profiles (2 profiles — Hailey Tai, Scarlett
Sy — returned zero; plausibly inactive posters, not a vendor fault. This is expected,
normal watchlist behavior: some entries will be quiet on a given day).

| Check | Result |
|---|---|
| Full post text | Yes, untruncated |
| Author metadata | name, public LinkedIn ID, headline, profile URL — all present |
| **Query linkage** (`query.targetUrl`) | Present — maps every post straight back to which watchlist entry produced it |
| Repost handling | Correctly separates reposting author from the original post's author (`repost.author` nested) — critical for not misattributing a mandate to the wrong recruiter |
| Freshness | Dates ranged from days-old to ~2 years old; `postedLimitDate` param available to scope to "since yesterday" for real daily polling |
| Job-signal keyword match | 56/90 (62%) |

**Sample hit** (Gillian Lam, Selby Jennings, posted ~1 month prior):
> "Hiring Momentum Continues in Private Banking! ... strong hiring demand in Hong Kong
> for Assistant Relationship Managers... Taiwan Desk – International Private Bank,
> Greater China Desk – Swiss Private Bank, EAM Desk..."

This is exactly the hidden-market pattern the project targets: a confidential mandate,
no named employer, that would map to `company="Confidential via Gillian Lam"` per
decision #7.

## Apify test 2 — `harvestapi/linkedin-post-search` (discovery simulation)

**Input:** 3 queries (`hiring Hong Kong compliance private bank`, `confidential
mandate Hong Kong relationship manager`, `hiring Hong Kong hedge fund analyst`),
`postedLimit=month`, `sortBy=date`.

Note: actual input field is `searchQueries`, not `queries` — first attempt with the
wrong field name silently returned 0 results (actor exits cleanly with no error on an
unrecognized field). Confirmed the correct schema via the actor's build definition.

**Result:** 14 posts.

| Check | Result |
|---|---|
| Keyword match | 14/14 (100%) — but keyword matching alone overstates precision |
| **Manual-read precision** | ~65-70% — genuine job posts (PineSearch's KYC Compliance Director, Janice Wong's Fixed Income Trader role) mixed with false positives that merely mention "hiring" (thought-leadership articles, opinion posts) |

This confirms LP-3's design choice: a keyword filter alone is not enough. The two-stage
LLM classifier (is this a job post? → extract fields) is necessary, not optional.

## Cost model check

Both actors bill **$2/1,000 results** (posts), consistent with the plan's $1.50-2/1k
estimate. At steady-state volumes (§6 of the plan), this stays comfortably under the
$30/month cap.

## Decision

**Vendor: Apify / HarvestAPI**, using `linkedin-profile-posts` for watchlist polling and
`linkedin-post-search` for discovery. Plan's decision #5 updated accordingly. Piloterr
`post/info` remains a documented fallback for post enrichment only, not primary.

Next: LP-1 (watchlist bootstrap).
