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

import ast
import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

from hk_jobs import salary_anchors
from hk_jobs.salary_clamp import clamp_salary, fix_salary_magnitude, price_from_coordinate

logger = logging.getLogger(__name__)


def finalise(
    raw_min: int | None,
    raw_max: int | None,
    *,
    tier: str | None,
    seniority: str | None,
    role: str | None = None,
    grade: str | None = None,
    company_slug: str | None = None,
    title: str | None = None,
    source_tier: str | None = None,
    coordinate_only: bool = False,
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

    `coordinate_only` means "prefer an exact table coordinate" — `clamp_salary`
    adopts the (tier, role, grade) cell outright when it resolves. It does NOT
    mean "publish nothing without one": see the comment below and docs/adr/0036.
    """
    # The coordinate is PREFERRED, not REQUIRED (docs/adr/0036).
    #
    # v13 made this gate absolute: no valid (tier, role, grade) cell -> store
    # nothing, on the reasoning that a missing coordinate is "a review fallback"
    # for a manual /fix-s pass to price by hand. Measured on the live board
    # 2026-09-02, that cost 54% of it any salary at all: 1,024 of 2,169 visible
    # Roles carried no figure, 916 of them purely because the model returned
    # salary_tier = null — and a re-enrichment run STRIPPED a good estimate from
    # 336 Roles that already had one. The manual Opus pass the gate assumed
    # would cover the gap is deliberately not something this project runs.
    #
    # `clamp_salary` below already does the right thing on its own: it REPLACES
    # both endpoints when the coordinate resolves, and otherwise clips the
    # model's own band DOWN through the tier ladder, the role ceiling, the
    # title-grade ceiling, the internship cap and the global cap. The
    # over-estimation this gate was added to prevent is precisely what that
    # stack exists for, and it applies either way.
    #
    # So refuse only when there is nothing to price FROM — neither a resolvable
    # coordinate nor any band from the model.
    if (
        coordinate_only
        and price_from_coordinate(tier, role, grade) is None
        and raw_min is None
        and raw_max is None
    ):
        return None, None

    fixed_min, fixed_max = fix_salary_magnitude(raw_min, raw_max)
    return clamp_salary(
        tier, seniority, fixed_min, fixed_max,
        role=role, grade=grade, company_slug=company_slug, title=title, source_tier=source_tier,
    )


def lowered(
    corrected_min: int | None,
    corrected_max: int | None,
    *,
    current_max: int | None,
    tier: str | None,
    seniority: str | None,
    role: str | None = None,
    grade: str | None = None,
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
        role=role, grade=grade, company_slug=company_slug, title=title, source_tier=source_tier,
    )


#: Bumped by hand for an external change the fingerprints cannot see, or for a
#: deliberate full replay whose model/prompt/anchor/clamp inputs are unchanged.
MANUAL_TAG = "2026-07-21-v10-merged-3source-granular-prefix-cached"


_UNSERIALISABLE = object()


class _WithoutDocstrings(ast.NodeTransformer):
    """Remove prose from an AST while retaining executable string constants."""

    @staticmethod
    def _strip(node: ast.AST) -> ast.AST:
        body = getattr(node, "body", None)
        if (
            isinstance(body, list)
            and body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            del body[0]
        return node

    def visit_Module(self, node: ast.Module) -> ast.AST:  # noqa: N802 - ast API name
        self.generic_visit(node)
        return self._strip(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:  # noqa: N802
        self.generic_visit(node)
        return self._strip(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:  # noqa: N802
        self.generic_visit(node)
        return self._strip(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST:  # noqa: N802
        self.generic_visit(node)
        return self._strip(node)


def _normalised_python_logic(source: str, names: frozenset[str] | None = None) -> str:
    """A comment/docstring-insensitive representation of executable Python.

    When ``names`` is supplied, only those top-level functions are retained.
    This lets the salary fingerprint include ``finalise``/``lowered`` without
    recursively hashing the versioning implementation itself.
    """
    tree = ast.parse(source)
    if names is not None:
        tree.body = [
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in names
        ]
    tree = _WithoutDocstrings().visit(tree)
    ast.fix_missing_locations(tree)
    return ast.dump(tree, annotate_fields=True, include_attributes=False)


def _source_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        # Source ships in both the repository and Railway image. Failing closed
        # here is safer than silently publishing a partial version fingerprint.
        raise RuntimeError(f"Cannot fingerprint salary logic at {path}: {exc}") from exc


def _clamp_logic_fingerprint() -> str:
    """Digest executable finishing/clamp logic while ignoring prose edits."""
    from hk_jobs import salary_clamp

    clamp_path = Path(salary_clamp.__file__).resolve()
    finishing_path = Path(__file__).resolve()
    payload = "|".join(
        (
            _normalised_python_logic(_source_text(clamp_path)),
            _normalised_python_logic(
                _source_text(finishing_path), frozenset({"finalise", "lowered"})
            ),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8]


def _canonical_rule_value(value: Any) -> Any:
    """Convert one clamp-rule value to stable JSON, or mark it unsupported."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, re.Pattern):
        return {"pattern": value.pattern, "flags": int(value.flags)}
    if isinstance(value, dict):
        converted: dict[str, Any] = {}
        for key, item in value.items():
            name = str(key).lower()
            if name in {"_desc", "_source", "note"} or name.endswith("_note"):
                continue
            canonical = _canonical_rule_value(item)
            if canonical is _UNSERIALISABLE:
                return _UNSERIALISABLE
            converted[str(key)] = canonical
        return converted
    if isinstance(value, (list, tuple)):
        converted_items = [_canonical_rule_value(item) for item in value]
        if any(item is _UNSERIALISABLE for item in converted_items):
            return _UNSERIALISABLE
        return converted_items
    if isinstance(value, (set, frozenset)):
        converted_items = [_canonical_rule_value(item) for item in value]
        if any(item is _UNSERIALISABLE for item in converted_items):
            return _UNSERIALISABLE
        return sorted(
            converted_items,
            key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")),
        )
    return _UNSERIALISABLE


def _clamp_rule_state() -> dict[str, Any]:
    """Every serialisable uppercase global that can parameterise the clamp."""
    from hk_jobs import salary_clamp

    state: dict[str, Any] = {}
    for name, value in vars(salary_clamp).items():
        if not name.lstrip("_").isupper():
            continue
        canonical = _canonical_rule_value(value)
        if canonical is not _UNSERIALISABLE:
            state[name] = canonical
    return state


def _clamp_fingerprint() -> str:
    """
    A digest of every clamp rule value and its executable control flow.

    The prior hand-maintained allowlist missed the internship ceiling, magnitude
    repair, regexes and every employer/title rule added later. Runtime rule
    state is now discovered by convention (uppercase globals); executable logic
    is normalised through Python's AST so comments and docstrings remain free to
    edit while a real branch/order/formula change invalidates the version.
    """
    payload = json.dumps(
        {
            "logic": _clamp_logic_fingerprint(),
            "rules": _clamp_rule_state(),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
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
#: `--re-enrich` still overrides everything here.
#:
#: 2026-09-02 — every prompt_version observed on the live catalogue is
#: grandfathered, because the change that made this list non-empty again is a
#: fix to `finalise` (docs/adr/0036: the coordinate is preferred, not
#: required). That edit lands inside `_clamp_logic_fingerprint`'s window, so it
#: moves PROMPT_VERSION and would otherwise mark all ~13,000 stored estimates
#: stale and re-pay DeepSeek for every one of them.
#:
#: Nothing is lost by grandfathering them. A row that already carries a figure
#: does not need the fix — the fix only changes what happens when the model
#: returns NO usable coordinate, which is exactly the case that stored nothing.
#: Those rows are reached instead by `_fetch_unenriched`'s "no salary figure"
#: arm, which ignores prompt_version entirely. So the fix reaches precisely the
#: Roles it was written for, and no others.
#:
#: These four strings are read off the published database, not computed here:
#: `_clamp_logic_fingerprint` normalises an AST and its output differs between
#: Python versions, so the CI runner's (3.11) fingerprint is not the one a
#: developer's interpreter produces. Copy from `SELECT DISTINCT prompt_version
#: FROM job_enrichments`, never from a local `PROMPT_VERSION`.
_V10 = "2026-07-21-v10-merged-3source-granular-prefix-cached+deepseek-v4-flash"
ACCEPTED_PRIOR_VERSIONS: frozenset[str] = frozenset({
    # The bulk of the back catalogue (~10,300 rows), pre-coordinate pricing.
    f"{_V10}+pac7b0b6b+adb2136ef+c0bba64e1",
    # Coordinate-pricing era, current on the board until this change (~2,900).
    f"{_V10}+p0d74585a+aabc6a639+c16c9cda8",
    f"{_V10}+pbc5764cc+adb2136ef+c0bba64e1",
    f"{_V10}+p020fb8c9+ac9f4c710+c0bba64e1",
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
