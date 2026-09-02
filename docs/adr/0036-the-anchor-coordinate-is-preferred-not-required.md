# The anchor coordinate is preferred, not required — and we never destroy an estimate

**Status:** accepted (2026-09-02)
**Supersedes:** the `coordinate_only` gate added by `2193f47` (2026-08-27,
"Classify salary anchors before deterministic pricing") and that commit's
emptying of `salary.ACCEPTED_PRIOR_VERSIONS`.
**Builds on:** ADR 0034 (estimation only targets the board), ADR 0035 (the
board is capped per employer).

Three rules, in order of importance:

1. **We never destroy an existing salary estimate.** A run may replace a figure
   with another figure, or fill a blank. It may never turn a figure into a
   blank.
2. **The anchor coordinate is PREFERRED, not REQUIRED.** An exact
   `(tier, role, grade)` cell still prices a Role outright when the model names
   one. When it does not, the model's own band is clamped down through the
   tier, role, title-grade, internship and global ceilings and stored — instead
   of nothing.
3. **A Role carrying no salary figure is always a re-enrichment candidate**,
   whatever its `prompt_version`.

## Why

A backlog run on 2026-09-02 re-priced the board and produced this:

| | |
|---|---:|
| board Roles (post ADR 0035 cap) | 2,169 |
| **with a salary figure** | **994 (46%)** |
| ran the current method, got no figure | 1,024 |
| — of those, model returned `salary_tier = null` | **916** |
| — had a full description anyway | 951 |
| **Roles that LOST a good estimate in the run** | **336** |
| Roles that gained one | 385 |
| net movement for $13.42 | **+49** |

Two independent faults, both introduced by `2193f47`.

**The gate.** `salary.finalise(..., coordinate_only=True)` returned
`(None, None)` unless `price_from_coordinate(tier, role, grade)` resolved to an
exact cell — all three parts present, cell populated. Its code comment called a
missing coordinate "a review fallback", meaning a manual `/fix-s` Opus pass was
expected to price the remainder by hand. **That pass is deliberately not
something this project runs** — the anchor table exists precisely so DeepSeek
can do this work without Opus. So 54% of the board simply had no salary, and
nothing was ever going to fill it.

The gate was also unnecessary on its own terms. It was added to stop the
model's free-form band over-estimating (historically ~30% high). But
`clamp_salary` — which runs immediately after, and which the gate short-circuits
— already clips that band down through the tier ladder, the role ceiling, the
title-grade ceiling, the internship cap and the HK$200,000 global cap, and
already adopts the coordinate outright when it resolves. The whole ladder the
gate was protecting against was sitting one line below it, unreached.

**The empty grandfather list.** The same commit set
`ACCEPTED_PRIOR_VERSIONS = frozenset()`, so every stored estimate was
permanently stale and every run re-processed the entire board. Combined with
the gate, a re-run was actively destructive: 336 Roles that an earlier prompt
had priced sensibly (Compliance Manager 35,000–48,000; Director, Transaction
Banking Sales 133,000–141,500; Project Manager 45,000–55,000) came back with
`salary_tier = null` on the re-run and had their figures replaced with NULL.

Sampling the 916 tier-less Roles shows they are not unclassifiable: *Structured
Rates Trader* (StanChart), *Relationship Manager – Private Banking*, *AVP Loan
Origination & Syndication* (OCBC), *Manager, International Tax* (Deloitte),
*Database Administrator* (ICBC). The taxonomy has a slot for every one. The
model declines because the prompt tells it to — *"Declining is free and costs
nothing"*, *"no reason to force a pick you are not sure of"* — and because
Step 2b (a declinable coordinate) and Step 3b (a mandatory tier) both write the
single `salary_tier` field, so the permissive instruction wins. Fixing that
prompt ambiguity is worth doing and is **not** part of this ADR; this ADR makes
the pipeline correct whether or not the model declines.

## What changes

### `hk_jobs/salary.py`

`finalise` refuses only when there is nothing to price **from** — neither a
resolvable coordinate nor any band:

```python
if (coordinate_only
        and price_from_coordinate(tier, role, grade) is None
        and raw_min is None and raw_max is None):
    return None, None
```

`clamp_salary` is otherwise reached exactly as before, and still prefers the
coordinate: when the cell resolves it replaces both endpoints outright.

`ACCEPTED_PRIOR_VERSIONS` is re-populated with the four `prompt_version` strings
observed on the live catalogue. This edit lands inside
`_clamp_logic_fingerprint`'s window (it hashes `finalise` itself), so
PROMPT_VERSION moves and would otherwise mark ~13,000 stored estimates stale and
re-pay DeepSeek for all of them. Nothing is lost by grandfathering: a Role that
already carries a figure does not need this fix, and one that does not is
reached by the new selection arm below regardless of its version.

> Those four strings are **read off the published database, never computed
> locally**. `_clamp_logic_fingerprint` normalises an AST, and `ast.dump()`
> output differs between Python versions — the CI runner (3.11) and a
> developer's interpreter (3.13) produce different fingerprints for identical
> source. That is a latent bug in its own right; it is recorded here and not
> fixed here.

### `hk_jobs/enrichment.py`

**Selection** gains a third arm. A Role is a candidate when it has no enrichment
row, **or** its version is stale and un-grandfathered, **or** it carries no
salary figure at all (`salary_estimated_min IS NULL AND salary_hkd_min IS
NULL`). The third arm is what lets a *pricing fix* reach the rows it was written
for without a full `--re-enrich` that would also churn the rows that are fine.

**The write** keeps an existing estimate when the new one is NULL. `min`, `max`,
`confidence`, `tier`, `role` and `grade` move as one block, keyed on the new
`min`, so a kept figure keeps the coordinate that actually produced it rather
than being re-described by a classification that priced nothing.

### `hk_jobs/enrichers/deepseek.py`

`MAX_TOKENS_WITH_DESCRIPTION` 16,000 → **24,000**, `MAX_TOKENS_TITLE_ONLY`
8,000 → **12,000**. The backlog run lost 243 of 1,694 Roles (14%) to
`finish_reason="length"` at the old ceilings — a full reasoning trace generated,
billed, and discarded for a 0-character answer. The raise is close to free:
`max_tokens` is a limit, not an allocation, so a call that already fits costs
the same, and the only calls that grow are the ones currently returning nothing.
It stays a firm ceiling; a trace that cannot finish inside 24,000 is a runaway
and `TruncatedAnswer` remains the right outcome.

### Tests

- `tests/test_enrichment_never_destroys_an_estimate.py` (new) — pins rule 1 at
  the write path: an unpriceable run leaves the figure, its confidence and its
  coordinate intact; the summary/seniority/version still refresh; a figure may
  still be replaced by another figure; a never-priced Role stays blank.
- `tests/test_prompt_version_grandfathering.py` — an unpriced Role is selected
  whatever its version (current or grandfathered); a priced Role on a
  grandfathered version is left alone. Replaces the v14 assertion that
  `ACCEPTED_PRIOR_VERSIONS` must be empty.
- `tests/test_salary.py` — the coordinate still prices outright when it
  resolves; otherwise the clamped model band is stored; `(None, None)` only when
  there is neither.
- `tests/test_deepseek_request.py` — the new token ceilings.

All shown RED against the pre-0036 code.

## Consequences

- Salary coverage on the board should return to roughly what the pre-2026-08-27
  method achieved (~99% of Roles the model answers for), with the anchor
  coordinate still winning wherever it resolves. **The exact figure depends on
  the model reliably producing its Step-3 band**, which the prompt mandates but
  which the old gate made unobservable — so this ships behind a small verified
  run before the full backlog pass, not a bulk run on faith.
- A stored estimate is now strictly monotonic in information: it can improve or
  hold, never vanish. The cost is that a genuinely bad old estimate is no longer
  cleared by a run that cannot re-price it — it must be corrected (Ultimate
  Admin, `/norm-it`, `/price-it`) or forced with `--re-enrich`.
- Re-populating `ACCEPTED_PRIOR_VERSIONS` means this change costs nothing on the
  ~13,000 already-priced rows. Only the ~1,024 unpriced board Roles are
  re-processed.
- The prompt ambiguity that makes the model decline a tier on classifiable
  Roles is **not** fixed here. It remains the reason coverage is not 100%, and
  is the next thing to address — along with extending
  `salary_guidlines/hk_salary_anchors.json` with the role/grade rows the board
  actually needs, so more Roles resolve to an exact cell instead of a clamped
  band.

## Alternatives rejected

**Keep the gate, run `/fix-s` (Opus) to fill the gap.** This is what the gate
assumed. The owner built the anchor table specifically to stop paying for Opus,
and a monthly manual pass over ~1,000 Roles is not a pipeline. Rejected on the
owner's explicit instruction.

**Delete `coordinate_only` entirely.** It still expresses a real preference —
an exact cell is better evidence than a model band, and `clamp_salary` treats it
that way. Keeping the parameter and narrowing what it refuses preserves the
intent while restoring coverage.

**Only fix the write guard, leave the gate.** That stops the destruction but
leaves 54% of the board permanently unpriced, which is the complaint that
started this.
