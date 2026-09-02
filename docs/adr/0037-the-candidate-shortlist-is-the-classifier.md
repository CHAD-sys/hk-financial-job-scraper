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

---

## Follow-up (2026-09-03) — what the verification pass left behind

The 40-Role pass took pricing from **12/38 (32%) to 31/38 (82%)**, with 0
estimates lost and the partial rung firing 5 times. The 7 that stayed unpriced
split cleanly, and both halves are addressed here.

**Two were retrieval, again.** A UOB *"Dealer, Structured Products Team"* was
offered `back_office_operations/human_resources` as its **only** candidate, and
a Morgan Stanley *"Senior Load Balancer Engineer"* had `it_infrastructure_support`
tied at score 3 with `corporate_finance_ma_ecm_dcm` and `private_banking_rm`.
`global_markets_trading`, `financial_markets_sales` and `it_infrastructure_support`
gain the words a HK advert actually uses (`dealer`, `structured products`,
`market making`, `load balancer`, `network engineer`, `site reliability`, …).
Both now rank first.

**Five were the model declining despite a good shortlist**, and they concentrate
hard by employer, not by title shape:

| cohort | priced |
|---|---:|
| everything else | 27/29 (93%) |
| **Big 4 (KPMG, Deloitte, PwC, EY)** | **4/9 (44%)** |
| single-grade titles | 23/25 (92%) |
| grade-menu titles (`a / b / c`) | 8/13 (62%) |

Grade menus at banks price fine; grade menus at advisory firms do not. The
clincher: for KPMG *"Manager/Associate Director, Technology Risk"*,
`professional_practice_advisory` ranked **#1** — carrying the exact Big-4 ladder
(Consultant → Senior Consultant → Assistant Manager → Manager → Senior Manager →
Associate Director → Director / Partner) — and the model still returned all-null.
The table was never the gap.

Two prompt rules answer it concretely rather than by exhortation:

- **3a** — a title advertising several grades is *one job open to a range of
  levels*, not an ambiguous one. Always return tier and role; take the **lowest**
  advertised grade, because a HK advert leads with the most senior title it will
  consider.
- **3b** — advisory / consulting / assurance work **at** a professional-services
  firm is a priced function belonging to `professional_practice_advisory` or
  `strategy_business_consulting`, with a specialism (cyber security, technology
  risk, internal audit) preferred where the block offers one.

At 303 Big-4 Roles on the board and only 121 priced (40%), this is the largest
remaining block — roughly 180 Roles.

### The candidate cap stays at 12

Raising it to 16 was considered and **rejected on measurement**. Over 800
postings:

| | |
|---|---:|
| postings exceeding a 12-cap | 396 (50%) |
| chosen role ranked 1st / 2nd / 3rd | 206 / 81 / 43 — **77% in the top 3** |
| chosen role ranked 9–12 | 14 |
| **chosen role ranked beyond 12** | **3 of 431 (0.7%)** |

Sixteen would rescue about three postings while adding four more mostly-noise
options to half of every prompt — the wrong trade for a classifier whose failure
mode is declining when unsure.

Priced-Role retention through both changes: **480/500 (96%)**, up from 477.

---

## Follow-up 2 (2026-09-03) — three ways a correct answer was being thrown away

The first full-scale run (nightly 33678359225, 500 Roles) priced **66%** of what
it answered — well short of usable. Breaking the misses down showed only a
minority were genuinely hard postings:

| of 500 attempted | |
|---|---:|
| never got an answer (timeout / truncation / connect) | 162 |
| answered and priced | 222 |
| **answered and NOT priced** | **116** |

Of those 116: **26 had a tier and role the model got right**, and **90 were
outright declines — 28 of them while our own scorer had already found the
answer** (`Receptionist → secretarial_admin`, `Cyber Security → cybersecurity(37)`,
`FICC Software Engineer → software_data_engineering(21)`).

### A. The model answers with the GRADE in the role field

The candidate block prints a role's grades in the same snake_case a role key
uses, so `- middle_office / cybersecurity: security_engineer | ...` invites
exactly this. Each of these had an exact published cell waiting and was binned:

```
network_engineer    is a grade in it_infrastructure_support      45,000-65,000
security_engineer   is a grade in cybersecurity                  35,000-65,000
it_audit_security   is a grade in it_governance_risk_compliance  65,000-80,000
hr_business_partner is a grade in human_resources                40,000-50,000
```

`salary_clamp.normalise_coordinate()` repairs it by pure lookup — it can only
move a name into the field the table itself says it belongs in, never invent
one. `enrichment.py` repairs BEFORE pricing and stores the repaired triple, so
the stored coordinate and the figure it produced always describe each other.

### B. A wide ladder is narrowed by seniority rather than refused

Follow-up 1's `MAX_ENVELOPE_WIDTH_RATIO` correctly refuses a junior-to-Head span
as an estimate — but refusing outright wasted valid classifications. When the
seniority is known, take the slice of the ladder that seniority occupies
(`_SENIORITY_LADDER_WINDOW`); the rows are ordered by pay, so a junior sits in
the bottom of them. Still entirely the published table, just a narrower window
on it. The 3× guard still applies when there is no seniority to narrow with.

### C. Adopt our own top candidate when the model declines

**The model is not the last word on which anchor row a job belongs to.** It is
one of two opinions, and the other is a deterministic scorer we can measure.
When the model returns a null coordinate AND our top candidate scores at least
`AUTOFILL_MIN_SCORE` (6 — one strong token matched in the *title*, i.e. the
title literally names the role), we take our own pick, mark the confidence
"low", and log it.

It never overrides a coordinate the model *did* name — it read the posting and
we did not. The figure still comes only from the anchor table and still passes
through the whole clamp.

### Measured by replaying all 116 real misses

| | recovered |
|---|---:|
| A — role/grade repair | 10 |
| B — seniority window | 15 |
| C — adopt top candidate | 50 |
| **total** | **60 (52% of the misses)** |

**Answered-and-priced: 66% → 83%.**

## What is left, and it is now one thing

Of the 56 still unpriced, **38 (68%) are internships** — "Summer Analyst",
"Graduate Programme", "Part-Time". `clamp_salary` gates the coordinate rung on
`not internship` (correctly: the whole internship failure mode is a genuine
intern matching a full-time band), so an intern with no model estimate falls
through every rung and stores nothing.

The clamp knows `INTERNSHIP_MAX_MONTHLY_HKD = 15000` but there is **no published
internship BAND anywhere in the anchors file** — only a ceiling. Pricing them
needs a floor, and inventing one would break the rule every figure on this board
follows: it comes from a published guide. That is a decision for the owner, not
a fix to slip in here. 96 Roles on the board are internships.
