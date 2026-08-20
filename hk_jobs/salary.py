"""
Producing one salary estimate.

WHY THIS EXISTS
---------------
Understanding how a single number reaches the board meant opening seven files.
The model is asked for a figure by `enrichers/deepseek.py`, whose prompt renders
the anchor table and instructs the model to clamp itself; the answer is then
passed through `fix_salary_magnitude` and `clamp_salary` in `salary_clamp.py`,
whose seven transforms are described in a sixty-line docstring; the result is
written by `enrichment.py`; and `salary_audit.py` later re-reads it, runs the
same two functions again, and overwrites the same columns.

Two specific things this module fixes.

**Both writers hand-rolled the finishing steps.** `enrichment.py` and
`salary_audit.py` each reached past this layer into `fix_salary_magnitude` and
`clamp_salary` directly. They are not doing the same thing — the estimator
finalises a fresh answer, the auditor lowers an existing one and abandons the
correction if it is not actually lower — which is precisely why leaving both to
assemble the primitives themselves invited them to drift. `finalise()` and
`lowered()` are the two operations, each stated once.

**The version had to be remembered.** `PROMPT_VERSION` gates re-enrichment: a
row whose stored version differs from the current one is re-estimated on the
next run. Its comment asked a human to bump it "whenever the model, the salary
prompt, OR the deterministic clamp changes materially" — a rule spanning three
modules, enforced by nobody. It failed exactly as you would expect, and the
comment records it: the 2026-07-21 boutique-discount and single-value-range
fixes "silently skip[ped] ~200 already-'fresh'-marked rows until a one-off
manual patch caught them".

`version()` derives that string instead. A clamp change now invalidates stored
estimates on its own.
"""

from __future__ import annotations

import hashlib
import logging

from hk_jobs import salary_anchors
from hk_jobs.salary_clamp import clamp_salary, fix_salary_magnitude

logger = logging.getLogger(__name__)


def finalise(
    raw_min: int | None,
    raw_max: int | None,
    *,
    tier: str | None,
    seniority: str | None,
    role: str | None = None,
    company_slug: str | None = None,
    title: str | None = None,
    source_tier: str | None = None,
) -> tuple[int | None, int | None]:
    """
    Turn a raw model answer into the number that gets stored.

    Two steps, and the order matters. The magnitude fix first: DeepSeek
    occasionally emits the figure in thousands shorthand — "66" for HK$66,000,
    with no unit marker — and a bare 66 compared against the anchor ceilings
    would sail under every one of them and be stored verbatim. Only a
    correctly-scaled figure is worth clamping.

    Every caller that turns a fresh model estimate into a stored one goes
    through here, so there is one answer to "what happened to this number
    between the model and the database".
    """
    fixed_min, fixed_max = fix_salary_magnitude(raw_min, raw_max)
    return clamp_salary(
        tier, seniority, fixed_min, fixed_max,
        role=role, company_slug=company_slug, title=title, source_tier=source_tier,
    )


def lowered(
    corrected_min: int | None,
    corrected_max: int | None,
    *,
    current_max: int | None,
    tier: str | None,
    seniority: str | None,
    role: str | None = None,
    company_slug: str | None = None,
    title: str | None = None,
    source_tier: str | None = None,
) -> tuple[int | None, int | None] | None:
    """
    A stored estimate revised DOWN by the audit, or `None` to leave it alone.

    Not `finalise()` with different arguments, and the difference is the whole
    reason this is its own function: the magnitude fix has to happen BEFORE the
    "is this actually lower?" test. The audit judge is an LLM too and hits the
    same thousands-shorthand glitch, so an unrepaired "48" would pass the
    lower-than test trivially and then be stored as HK$48/month. Only what
    survives that test, repaired, is worth clamping.

    The audit is allowed to lower an estimate and never to raise one. A second
    model pass that can move a number in both directions is not an audit, it is
    a re-run — and it would fight the first pass indefinitely.
    """
    if isinstance(corrected_min, int) or isinstance(corrected_max, int):
        corrected_min, corrected_max = fix_salary_magnitude(
            corrected_min if isinstance(corrected_min, int) else None,
            corrected_max if isinstance(corrected_max, int) else None,
        )

    if not isinstance(corrected_max, int) or (current_max is not None and corrected_max >= current_max):
        return None

    if not isinstance(corrected_min, int):
        # A ceiling with no floor: widen rather than store a flat point, the same
        # rule clamp_salary applies via SINGLE_VALUE_MIN_FRACTION.
        corrected_min = round(corrected_max * 0.5)

    return clamp_salary(
        tier, seniority, corrected_min, corrected_max,
        role=role, company_slug=company_slug, title=title, source_tier=source_tier,
    )


#: Bumped by hand for a change a fingerprint cannot see — a materially different
#: instruction to the model that happens to leave the prompt the same length, or
#: a decision to re-estimate everything for its own sake.
MANUAL_TAG = "2026-07-21-v10-merged-3source-granular-prefix-cached"


def _clamp_fingerprint() -> str:
    """
    A digest of the clamp's behaviour-defining constants.

    Constants, deliberately, not the module's source text. Hashing the file
    would make a typo in a comment invalidate every stored estimate and re-pay
    for 13,000 model calls — which would teach everyone to stop touching the
    file, the opposite of what this is for.

    The trade is explicit: a change to the *logic* that does not move any of
    these values will not be caught, and needs MANUAL_TAG. Every past incident
    was a constant change, which is what this closes.
    """
    from hk_jobs import salary_clamp

    # Read through the module, not through names imported at the top of this
    # file: `from salary_clamp import BOUTIQUE_SALARY_MULTIPLIER` binds the
    # VALUE once, so the fingerprint would keep reporting whatever the constant
    # was when this module was first imported.
    payload = "|".join(str(x) for x in (
        salary_clamp.GLOBAL_MAX_MONTHLY_HKD,
        salary_clamp.BOUTIQUE_SALARY_MULTIPLIER,
        salary_clamp.SINGLE_VALUE_MIN_FRACTION,
        sorted(salary_clamp._BANK_SLUGS),
        sorted(salary_clamp._INSURANCE_SLUGS),
        [name for name, _ in salary_clamp._BANK_GRADE_PATTERNS],
        [name for name, _ in salary_clamp._INSURANCE_GRADE_PATTERNS],
        sorted(salary_clamp._GRADE_ROW_NAMES.items()),
    ))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8]


#: Stored `prompt_version` values that are accepted as current — their rows are
#: NOT queued for re-enrichment even though the string no longer matches.
#:
#: `version()` below is derived from the prompt text, so ANY edit to that text —
#: a typo, a clarifying sentence, a new grade ladder — marks every stored
#: estimate stale. Measured against the real billing dashboard that is ~$40 of
#: DeepSeek across 6,188 active Roles ($0.0065/Role observed), every time anyone
#: touches the prompt.
#:
#: Sometimes propagating IS the point: a recalibration should reach the back
#: catalogue. Usually it is not, and the change only needs to apply to Roles
#: enriched from now on. This list is where that judgement is recorded, one
#: version at a time, with a reason.
#:
#: Note what this deliberately does NOT do: it does not rewrite old rows' stored
#: `prompt_version`. Stamping them with the new string would buy the same saving
#: by falsifying provenance, and every later audit would inherit the lie. The
#: rows keep saying which prompt actually produced them; this list only says
#: "and that is fine".
#:
#: `--re-enrich` still overrides everything here, so a genuine recalibration
#: remains shippable.
ACCEPTED_PRIOR_VERSIONS: frozenset[str] = frozenset({
    # 2026-08-20 — Morris H.'s bank/insurance grade ladders were added to the
    # DeepSeek prompt. Grandfathered by owner decision: the ladders are enforced
    # deterministically by hk_jobs/salary_clamp.py on every row regardless of
    # which prompt produced it, so re-running the model over the back catalogue
    # would buy nothing the clamp does not already deliver for free.
    "2026-07-21-v10-merged-3source-granular-prefix-cached"
    "+deepseek-v4-flash+pac7b0b6b+adb2136ef+c0bba64e1",
    # 2026-08-20 — Step 6 was added to the salary prompt: how to treat the
    # "HUMAN CORRECTIONS" block that hk_jobs/salary_corrections.py appends when
    # an admin has already priced a similar Role by hand.
    #
    # Grandfathered because the instruction is INERT without that block, and the
    # block is per-job and did not exist when these rows were written. Re-running
    # the back catalogue would cost ~$40 (6,188 active Roles at the observed
    # $0.0065) to hand most of them a rule with nothing to apply it to.
    #
    # To propagate deliberately once enough corrections have accumulated, delete
    # this entry: every stored row becomes stale on the next run and is
    # re-estimated with the corrections in front of the model. That is a real
    # recalibration and a real bill — make it a decision, not an accident.
    "2026-07-21-v10-merged-3source-granular-prefix-cached"
    "+deepseek-v4-flash+pc9d76b29+adb2136ef+c0bba64e1",
})


def version(model: str, prompt: str) -> str:
    """
    The version stored alongside an enrichment, and compared on the next run.

    Derived from everything that changes the answer: the model, the prompt text,
    the anchor calibration, and the clamp's constants. Change any of them and
    the string changes, so `enrichment.py`'s
    `WHERE e.prompt_version != <current>` re-estimates the affected rows without
    anyone having to remember to say so.
    """
    prompt_digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:8]
    return f"{MANUAL_TAG}+{model}+p{prompt_digest}+a{salary_anchors.fingerprint()}+c{_clamp_fingerprint()}"


def explain_version(model: str, prompt: str) -> dict[str, str]:
    """The parts of `version()`, for debugging a surprise re-enrichment."""
    return {
        "manual_tag": MANUAL_TAG,
        "model": model,
        "prompt": hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:8],
        "anchors": salary_anchors.fingerprint(),
        "clamp": _clamp_fingerprint(),
        "version": version(model, prompt),
    }
