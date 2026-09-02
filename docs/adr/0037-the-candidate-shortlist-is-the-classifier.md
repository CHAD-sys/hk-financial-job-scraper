# The candidate shortlist is the classifier — fix retrieval, and pick a best fit

**Status:** accepted (2026-09-02)
**Builds on:** ADR 0036 (the coordinate is preferred, not required; never destroy
an estimate). Supersedes the "return null when ambiguous" half of the v14 salary
policy introduced by `2193f47`.

Four changes, one goal — stop the board's Roles arriving with `salary_tier = null`:

1. **`salary_context` retrieval is fixed.** Title evidence outranks description
   evidence, grade words stop counting as function evidence, and no published
   role can be unreachable.
2. **The shortlist grows from 8 to 12 candidates.**
3. **The prompt's default flips from decline to best-fit.**
4. **A partial `(tier, role)` coordinate prices** from that role's own published
   band instead of storing nothing.

## Why

ADR 0036 restored the fallback in `finalise`. A verified 40-Role run afterwards
showed it firing **0 times**:

| verification run 33635783230 | |
|---|---:|
| priced | 12 / 38 |
| — via an exact coordinate | 12 |
| — via the restored fallback band | **0** |
| lost an existing estimate | **0** ✅ |

The fallback had nothing to fall back to. The live v14 policy forbids the model
from ever producing a band (*"salary_estimated_min and salary_estimated_max must
be null unless an explicit base-salary range is disclosed"*), so when it declines
a coordinate it returns nothing at all.

> **A trap worth recording:** `_SALARY_INSTRUCTIONS` is assigned twice in
> `deepseek.py`. The long v13 text — Steps 1-4, the 471-cell reference table,
> *"ALSO estimate a band … treat it as required"* — is **reassigned away and never
> sent**. Reading it as the live prompt produced a wrong root-cause diagnosis in
> this very investigation. The dead block now carries a loud marker.

So why does the model decline? Because v14 also stopped showing it the table.
It sees a per-posting shortlist from `salary_context.build_salary_context()` and
is told to return null if nothing fits. **That makes retrieval the real
classifier** — and retrieval was handing it the wrong list:

```
▸ Assistant Manager / Manager, Cost Management (Financial Budgeting)
    score=2   front_office/asset_management_sales      ← the ONLY candidate offered

▸ Assistant Manager, Transaction Monitoring   (an AML job)
    score=4   commercial_banking_rm, sme_banking_rm, transaction_banking_rm,
              private_banking_rm, relationship_management …   (fcc_aml NOT offered)

▸ Assistant Compliance Manager / Compliance Manager
    score=16  front_office/private_banking_rm      ← ranked FIRST
    score=5   middle_office/compliance_banking     ← the right answer, 2nd
```

Handed that, `null` is the correct answer. The model was not being lazy.

### Three faults in the scorer

**Description phrases scored like title phrases.** A phrase hit was worth 12
whether it appeared in the title or anywhere in the description. One boilerplate
*"wealth management"* in an employer blurb therefore ranked `private_banking_rm`
above every compliance role on a job titled "Compliance Manager".

**`_GENERIC` erased whole role identities.** A candidate needed a phrase hit or
≥2 non-generic token hits, and tokens came from the role key with
`operations, management, finance, banking, insurance, corporate, business,
services, general` stripped. `back_office_operations/operations_general` —
the catch-all for the board's **largest** unpriced family (103 Roles) — reduced
to nothing and **could never be offered to the model at all**. Nor could
`insurance/insurance_finance_operations`. 32 further roles were left with a
single usable token.

**Grade words counted as function evidence.** `assistant_private_banker` matched
any title containing "Assistant".

**And 81 of 105 roles had no vocabulary at all** — `fcc_aml`,
`kyc_cdd_client_onboarding`, `documentation_operations`, `fpa_corporate`,
`management_reporting` and the rest were reachable only by coincidence on their
key name.

## What changes

### `hk_jobs/salary_context.py`

Scoring is split by where the evidence is, with weights that say the title is
what a job *is*:

| evidence | weight |
|---|---:|
| phrase in the **title** | 12 |
| phrase in the **description** only | 3 |
| strong token in the title | 6 |
| strong token in the description only | 1 |
| **weak** (generic) token in the title | 2 |
| weak token in a description | 0 |

`_role_vocabulary()` replaces the old flat term list and returns
`(phrases, strong tokens, weak tokens)`. Generic tokens are no longer discarded
— they are demoted to **weak** and scored against the title only. "Operations"
in a description is noise; "Operations Officer" in a title is not. That alone
makes `operations_general` reachable.

`_GENERIC` gains the grade words (`assistant, associate, analyst, deputy,
director, executive, head, junior, lead, manager, officer, president, senior,
specialist, vice`). A grade word says how senior a job is, never what it does.

`_ROLE_TERMS` grows from 24 to 55 roles, covering the highest-volume gaps
measured against the 2026-09-02 board.

`_DEFAULT_CANDIDATE_LIMIT` is **12**, up from 8. The model now picks a best fit
rather than declining, so a slightly longer list costs a little prompt and buys
the correct role a place on it.

**Measured against the live board (n=500 each):**

| | before | after |
|---|---:|---:|
| unpriced Roles with an **empty** shortlist | 5% | **1%** |
| already-priced Roles whose chosen role is still offered | — | **477/500 (95%)** |

The 23 non-retained are mostly cases where the old pick was wrong (a
*Quantitative Volatility Trading* posting had been matched to
`software_data_engineering`). None can lose its stored figure — ADR 0036's
write guard holds.

### The prompt (`deepseek.py` v14 policy)

Instruction 2 becomes "pick the ONE candidate that BEST fits"; instruction 3
becomes:

> Prefer a partial answer to no answer. If the ROLE is clear but no single grade
> row is a confident match, return `salary_tier` and `salary_role` and leave
> `salary_grade` null — the runtime prices that from the role's own published
> range. Return null for all three ONLY when the candidate block is empty, or
> when nothing in it is even plausibly related to this job. Declining is not the
> safe choice it looks like: a Role you decline shows a Seeker no salary at all,
> which is the worst outcome available.

The candidate block's own header flips the same way.

### `hk_jobs/salary_clamp.py`

`price_from_role_envelope(tier, role)` and `price_from_partial_coordinate(tier,
role, seniority)` are new. The partial rung prefers the **seniority-mapped grade
row** (`compliance_banking` + `mid` = 50,000–75,000) and only falls back to the
role's whole envelope when that mapping does not resolve.

`MAX_ENVELOPE_WIDTH_RATIO = 3.0` refuses an envelope wider than 3× — a whole
ladder spans junior to Head (`compliance_banking` is 21,500–200,000; `tax` is
22,000–300,000), and a range that wide is noise wearing a number's clothes. Real
grade rows run about 1.4–1.7× wide.

`clamp_salary` uses the partial rung **only when there is no estimate at all**.
It exists to replace a blank, never to move a number: a role matched without a
grade is weaker evidence than every ceiling and floor above it. (An earlier draft
intersected it with an existing estimate and broke
`test_floor_raise_does_not_apply_to_idiosyncratic_fallback_roles`, which encodes
exactly that principle.)

`price_from_coordinate` is unchanged — still all-three-or-nothing — because
`/fix-s` and `salary_repair` depend on its exactness.

### Tests

`tests/test_salary_context_retrieval.py` (new) pins every fault above, plus that
an unrelated title still declines. `tests/test_salary.py` gains four
partial-coordinate cases. **8 shown RED against the pre-0037 behaviour.**

## Consequences

- Coverage should rise well past ADR 0036's 46%, but **by how much is a model
  question that only a run can answer** — the shortlist is now right far more
  often, and the prompt now asks for a best fit, but neither guarantees the model
  commits. This ships behind a 40-Role verified pass, same as ADR 0036.
- Some Roles will get the wider seniority-row band rather than an exact cell.
  That is intended: a real published range for the right job family beats a
  blank. `salary_estimated_confidence` is "low" for those.
- `PROMPT_VERSION` moves (prompt text, `_clamp_logic_fingerprint`, and
  `MAX_ENVELOPE_WIDTH_RATIO` in the rule state). ADR 0036's
  `ACCEPTED_PRIOR_VERSIONS` keeps the ~13,000 already-priced rows from being
  re-billed; the "no salary figure" selection arm reaches the unpriced ones.
- The anchor table is **not** extended here, and the gap analysis says it should
  not be: every function family in the unpriced set already has a role key. The
  fault was retrieval, not coverage — `operations_general` existed all along and
  simply could not be offered.

## Alternatives rejected

**Extend `hk_salary_anchors.json` with new roles and web-sourced figures.** The
owner asked for this first. Measured, it would not have helped: all 105 roles
were already present and the largest unpriced family's role key was in the table
but unreachable. It would also splice unsourced numbers into a package-free
merge of three published guides (ADR 0025), and lengthen the vocabulary the
classifier has to choose from.

**Let the model emit a free-form band again.** Simpler, and `clamp_salary` would
cap it — but it re-opens the ~30% over-estimation that classification-first was
built to close, and throws away the table's precision for the many Roles where
the coordinate does resolve.
