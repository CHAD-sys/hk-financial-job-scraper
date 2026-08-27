# Cross-posted matching groups by company name, not slug

**Status:** accepted (2026-08-27)

`JobStore.reconcile_cross_posted()` (`hk_jobs/storage.py`) is the whole of
duplicate-vacancy detection: it finds the same role posted on more than one
board and collapses it to one visible card. Until now it only ever compared
rows that shared a `company_slug` — the identifier a human assigns when
adding an entry to `companies.yaml` / `companies_longtail.yaml`.

## The gap

Cross-source matching for a company existed only if a human had deliberately
given two of that company's adapter entries the *same* slug (the documented
convention: a JobsDB entry and an eFinancialCareers entry both using
`aia-hk`). A live-config check found 52 of 78 mainstream companies pairs this
way — a curated minority. Every longtail boutique (68 companies), and any
mainstream company someone forgot to pair, got **zero** cross-source
matching, invisibly: the same real vacancy on two boards just rendered as two
separate cards, with nothing anywhere flagging it as a miss.

## The decision

`reconcile_cross_posted` now groups by `_company_group_key()` — the
company's display NAME, stripped of legal-suffix and punctuation noise
(`limited`, `ltd`, `holdings`, `group`, `hong kong`, `hk`, …), not the raw
`company_slug`. Two slugs whose rows carry the same normalized name are now
clustered, fuzzy-title-matched, and elected exactly as a same-slug pair
already was — no new code path, no new election rule, just a wider net
feeding the existing one.

The name match is **exact after normalization, never fuzzy**. Two different
employers accidentally landing in one group would hide one of their entire
boards behind the other's; the risk profile is not the same as fuzzy title
matching within a confirmed single employer's postings. A normalized name
under 3 characters — too little to trust — falls back to keying on the raw
slug alone, so two companies that both strip down to something generic never
collide.

## Consequence for scoped re-election

`mark_inactive_for_run()` calls `reconcile_cross_posted(company_slugs=...)`
scoped to just the slug(s) whose rows changed. Once grouping can span slugs,
a scope that only includes ONE of two slugs sharing a company name would see
an incomplete group, wrongly conclude it's single-source, and reset routing
— flapping the election on every incremental call. `reconcile_cross_posted`
now expands a given slug set to every sibling slug sharing its normalized
company key before loading rows, so a scoped call sees the same group a full
pass would.

## What this does not fix

This closes the "two slugs, same name" case only. It does not catch the same
employer scraped under two *differently spelled* names (e.g. "HSBC" from one
adapter's card extraction vs. "HSBC Holdings" surviving normalization
differently, or a genuine misspelling) — that remains a config/extraction
problem, not a matching one. It also does not address the separate,
already-known gaps from the same audit: no location signal in the match
(same-title, different-branch roles can still incorrectly collapse), and the
richest-source-wins election discarding a demoted copy's better data when
that assumption doesn't hold for a specific row.
