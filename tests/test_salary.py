"""
The salary module: producing one estimate, and knowing when it went stale.

`salary_clamp` has its own 39 tests for the seven transforms. These cover the
layer above it — the two operations that turn a model answer into a stored
number, and the version string that decides whether a stored number still counts
as current.

That version is the reason this file exists. It used to be a hand-edited
constant whose comment asked a human to bump it whenever the model, the prompt,
or the clamp changed. The comment also records what happened when someone
didn't: the 2026-07-21 boutique-discount and single-value-range fixes "silently
skip[ped] ~200 already-'fresh'-marked rows until a one-off manual patch caught
them".
"""

from __future__ import annotations

import json

import pytest

from hk_jobs import salary, salary_anchors, salary_clamp

MODEL = "deepseek-v4-flash"
PROMPT = "estimate a monthly HKD base salary"


def _version() -> str:
    return salary.version(MODEL, PROMPT)


# ── The ceiling has one home ──────────────────────────────────────────────────

def test_the_ceiling_comes_from_the_anchors_file():
    """
    It was a hardcoded constant in salary_clamp.py, with a comment telling the
    reader to keep it in sync with the same number in the anchors file — and
    conceding the file's copy was "documentation". One number, one source.
    """
    on_disk = json.loads(salary_anchors.ANCHORS_PATH.read_text(encoding="utf-8"))
    assert salary_anchors.GLOBAL_MAX_MONTHLY_HKD == on_disk["meta"]["global_max_monthly_hkd"]
    assert salary_clamp.GLOBAL_MAX_MONTHLY_HKD == salary_anchors.GLOBAL_MAX_MONTHLY_HKD


def test_the_anchors_are_read_once():
    """Two modules used to parse the same file independently."""
    from hk_jobs.enrichers import deepseek

    assert deepseek.salary_anchors.ANCHORS is salary_anchors.ANCHORS
    assert salary_clamp.salary_anchors.ANCHORS is salary_anchors.ANCHORS


# ── finalise ──────────────────────────────────────────────────────────────────

def test_finalise_clamps_to_the_global_ceiling():
    _, hi = salary.finalise(300_000, 900_000, tier="front_office", seniority="lead")
    assert hi <= salary_anchors.GLOBAL_MAX_MONTHLY_HKD


def test_finalise_repairs_thousands_shorthand():
    """
    DeepSeek occasionally emits "31-48" meaning HK$31,000-48,000, with no unit
    marker — found in production across 18 rows on 2026-07-22. Repairing this
    has to precede the clamp: a bare 48 sails under every ceiling and gets
    stored verbatim.
    """
    lo, hi = salary.finalise(31, 48, tier="middle_office", seniority="mid")
    assert (lo, hi) == (31_000, 48_000)


def test_finalise_leaves_a_normally_scaled_estimate_alone():
    lo, hi = salary.finalise(40_000, 60_000, tier="middle_office", seniority="mid")
    assert lo >= 10_000 and hi <= salary_anchors.GLOBAL_MAX_MONTHLY_HKD


def test_finalise_passes_none_through():
    assert salary.finalise(None, None, tier="middle_office", seniority="mid") == (None, None)


def test_coordinate_only_prices_from_an_exact_coordinate_when_it_resolves():
    """The coordinate is still PREFERRED: a resolvable cell prices the Role
    outright, with no band from the model at all."""
    assert salary.finalise(
        None, None,
        tier="middle_office", role="product_management", grade="Analyst",
        seniority="junior", coordinate_only=True,
    ) == (25_000, 40_000)


def test_coordinate_only_falls_back_to_the_clamped_model_band():
    """docs/adr/0036 — the coordinate is preferred, NOT required.

    RED before this change: `finalise` returned (None, None) here, and that is
    how 1,024 of 2,169 board Roles ended up with no salary at all. The model's
    own band is still clamped down through the tier/role/title/global ceilings,
    which is what stops the over-estimation the old gate was aimed at.
    """
    lo, hi = salary.finalise(
        40_000, 60_000, tier="middle_office", seniority="mid", coordinate_only=True,
    )
    assert lo is not None and hi is not None
    assert lo <= hi <= salary_anchors.GLOBAL_MAX_MONTHLY_HKD


def test_coordinate_only_still_refuses_when_there_is_nothing_to_price_from():
    """No resolvable coordinate AND no band from the model — there is genuinely
    nothing to publish, so nothing is."""
    assert salary.finalise(
        None, None, tier=None, role=None, grade=None,
        seniority=None, coordinate_only=True,
    ) == (None, None)


def test_finalise_never_returns_a_flat_point():
    """A range that collapses to min == max reads as a precise figure it is not."""
    lo, hi = salary.finalise(200_000, 200_000, tier="front_office", seniority="lead")
    if lo is not None and hi is not None:
        assert lo < hi


def test_boutique_employers_are_scaled_down():
    _, mainstream = salary.finalise(60_000, 90_000, tier="middle_office",
                                    seniority="mid", source_tier="mainstream")
    _, boutique = salary.finalise(60_000, 90_000, tier="middle_office",
                                  seniority="mid", source_tier="boutique")
    assert boutique < mainstream


# ── lowered ───────────────────────────────────────────────────────────────────

def test_lowered_refuses_to_raise_an_estimate():
    """
    The audit may lower a number and never raise one. A second pass that moves a
    number in both directions is not an audit, it is a re-run — and it would
    fight the first pass indefinitely.
    """
    assert salary.lowered(50_000, 90_000, current_max=80_000,
                          tier="middle_office", seniority="mid") is None


def test_lowered_returns_the_revised_pair_when_it_is_lower():
    revised = salary.lowered(30_000, 50_000, current_max=80_000,
                             tier="middle_office", seniority="mid")
    assert revised is not None
    lo, hi = revised
    assert hi < 80_000 and lo < hi


def test_lowered_repairs_thousands_shorthand_before_comparing():
    """
    The subtle one, and why this is not `finalise` with extra arguments.

    The audit judge is an LLM too, and hits the same thousands-shorthand glitch:
    "31-48" meaning HK$31,000-48,000. Unrepaired, a bare 48 passes the
    lower-than-80,000 test trivially and gets stored as HK$48/month — which is
    the production bug found on 2026-07-22 across 18 rows. Repaired first, it is
    a real 48,000 that still lowers the estimate honestly.
    """
    revised = salary.lowered(31, 48, current_max=80_000,
                             tier="middle_office", seniority="mid")
    assert revised is not None
    lo, hi = revised
    assert hi > salary_clamp.MAGNITUDE_GLITCH_CEILING, "48 must not be stored as HK$48/month"
    assert hi < 80_000 and lo < hi


def test_lowered_widens_a_ceiling_with_no_floor():
    revised = salary.lowered(None, 40_000, current_max=90_000,
                             tier="middle_office", seniority="mid")
    assert revised is not None
    lo, hi = revised
    assert lo is not None and lo < hi


def test_lowered_ignores_a_verdict_with_no_numbers():
    assert salary.lowered(None, None, current_max=80_000,
                          tier="middle_office", seniority="mid") is None


# ── version ───────────────────────────────────────────────────────────────────

def test_version_is_stable_across_calls():
    assert _version() == _version()


def test_version_changes_with_the_model():
    assert salary.version("deepseek-v4-pro", PROMPT) != salary.version("deepseek-v4-flash", PROMPT)


def test_version_changes_with_the_prompt():
    assert salary.version(MODEL, PROMPT) != salary.version(MODEL, PROMPT + " conservatively")


@pytest.mark.parametrize(
    "constant,new_value",
    [
        ("BOUTIQUE_SALARY_MULTIPLIER", 0.65),
        ("SINGLE_VALUE_MIN_FRACTION", 0.6),
        ("GLOBAL_MAX_MONTHLY_HKD", 180_000),
        ("INTERNSHIP_MAX_MONTHLY_HKD", 20_000),
        ("MAGNITUDE_GLITCH_CEILING", 4_000),
    ],
)
def test_version_changes_when_a_clamp_constant_changes(monkeypatch, constant, new_value):
    """
    THE regression this module exists for. Each of these moves a stored number,
    and each used to require a human to remember to bump a string in a different
    module. The 2026-07-21 boutique-discount change is literally the first case.
    """
    before = _version()
    monkeypatch.setattr(salary_clamp, constant, new_value)
    assert _version() != before


@pytest.mark.parametrize(
    ("rule_name", "changed_value"),
    [
        ("_BANK_BANDS", {"assistant_vice_president": [51_000, 81_000]}),
        ("_BANK_FUNCTION_BANDS", {"private_banking_business_manager": [61_000, 91_000]}),
        ("_BIG_FOUR_BANDS", {"manager": [51_000, 61_000]}),
        (
            "_EMPLOYER_SALARY_OVERLAYS",
            (
                {
                    "key": "probe",
                    "company_slug": "probe",
                    "title_pattern": "probe",
                    "band_monthly_hkd": [1, 2],
                },
            ),
        ),
        (
            "_MANAGER_GRADE_FLOORS",
            {
                "smaller_or_unclassified": {
                    "minimum_monthly_hkd": 41_000,
                    "fallback_maximum_monthly_hkd": 56_000,
                }
            },
        ),
    ],
)
def test_version_changes_when_any_deterministic_rule_table_changes(
    monkeypatch, rule_name, changed_value
):
    """Every table read by ``clamp_salary`` must participate in staleness.

    These rule families were added after the original fingerprint and changed
    published estimates without changing ``prompt_version``. The Daily Run then
    had no signal that an older estimate needed to be reconsidered.
    """
    before = _version()
    monkeypatch.setattr(salary_clamp, rule_name, changed_value)
    assert _version() != before


def test_version_changes_when_a_title_matching_rule_changes(monkeypatch):
    """Regexes are salary rules too; changing who matches must change the version."""
    before = _version()
    pattern = salary_clamp._INTERNSHIP_PATTERN
    monkeypatch.setattr(
        salary_clamp,
        "_INTERNSHIP_PATTERN",
        salary_clamp.re.compile(pattern.pattern + r"|\bapprentice\b", pattern.flags),
    )
    assert _version() != before


def test_version_changes_when_the_clamp_control_flow_changes(monkeypatch):
    """A logic edit with unchanged constants must not rely on a manual version bump."""
    before = _version()
    monkeypatch.setattr(salary, "_clamp_logic_fingerprint", lambda: "changed-logic")
    assert _version() != before


def test_logic_fingerprint_ignores_comments_but_not_executable_changes():
    original = "def rule(value):\n    return min(value, 10)\n"
    comment_only = "# clearer wording\ndef rule(value):\n    return min(value, 10)\n"
    changed = "def rule(value):\n    return min(value, 20)\n"

    assert salary._normalised_python_logic(original) == salary._normalised_python_logic(
        comment_only
    )
    assert salary._normalised_python_logic(original) != salary._normalised_python_logic(changed)


def test_version_changes_when_the_employer_allowlists_change(monkeypatch):
    before = _version()
    monkeypatch.setattr(salary_clamp, "_BANK_SLUGS",
                        frozenset(salary_clamp._BANK_SLUGS | {"a-new-bank"}))
    assert _version() != before


def test_version_changes_when_the_anchor_calibration_changes(monkeypatch):
    before = _version()
    monkeypatch.setattr(salary_anchors, "LADDERS",
                        {**salary_anchors.LADDERS, "invented_tier": [[1, 2]]})
    assert _version() != before


def test_version_changes_when_a_new_anchor_rule_section_is_added(monkeypatch):
    """Future rule sections are covered automatically, not by another allowlist."""
    before = _version()
    monkeypatch.setattr(
        salary_anchors,
        "ANCHORS",
        {**salary_anchors.ANCHORS, "future_salary_rule": {"band": [12_345, 23_456]}},
    )
    assert _version() != before


def test_version_changes_when_role_table_semantics_change(monkeypatch):
    """Changing catalogue-versus-ladder behaviour must make old estimates stale."""
    before = _version()
    changed = json.loads(json.dumps(salary_anchors.ANCHORS))
    changed["role_table_semantics"]["tiers"]["middle_office"]["risk_credit"] = {
        "kind": "title_catalog"
    }
    monkeypatch.setattr(salary_anchors, "ANCHORS", changed)

    assert _version() != before


def test_version_ignores_prose_in_the_anchors_file(monkeypatch):
    """
    Re-wording `meta.source` must NOT invalidate 13,000 estimates and re-pay for
    them at the model. The fingerprint is over the calibration data, not the
    whole file — a deliberate line, so that editing documentation stays free.
    """
    before = _version()
    changed = json.loads(json.dumps(salary_anchors.ANCHORS))
    changed["tables_monthly_hkd"]["front_office"]["_desc"] = "clearer table wording"
    changed["title_grade_bands_monthly_hkd"]["bank"]["note"] = "clearer rule note"
    monkeypatch.setattr(salary_anchors, "ANCHORS", changed)
    monkeypatch.setattr(salary_anchors, "META",
                        {**salary_anchors.META, "source": "reworded for clarity"})
    assert _version() == before


def test_explain_version_names_every_component():
    parts = salary.explain_version(MODEL, PROMPT)
    assert set(parts) == {"manual_tag", "model", "prompt", "anchors", "clamp", "version"}
    for key in ("model", "prompt", "anchors", "clamp"):
        assert str(parts[key]) in parts["version"]


def test_the_enricher_stamps_the_derived_version():
    from hk_jobs.enrichers import deepseek

    assert deepseek.PROMPT_VERSION == salary.version(deepseek._MODEL, deepseek._SALARY_INSTRUCTIONS)
    assert salary.MANUAL_TAG in deepseek.PROMPT_VERSION
