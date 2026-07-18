"""Deterministic salary-estimate clamp.

The DeepSeek enricher returns a Hong Kong monthly BASE salary estimate that is only
*soft*-guided by the prompt's Hays bands — so it can still drift above them, especially
at lead level (an ambiguous role mis-tiered as front office jumps to the 333k ceiling).

This module clips the model's estimate DOWN to the ceiling of the matching
(function tier, seniority) band in ``salary_guidlines/hk_salary_anchors.json`` — the same
anchors the prompt is rendered from. It makes over-estimation *structurally* impossible
regardless of what the model returns.

Design choices:
- **Down-only.** We only cap the top; we never raise a low estimate. The problem we are
  solving is over-estimation, and silently inflating a conservative estimate would be a
  surprising side effect.
- **Fail open.** If the tier/seniority is missing or unknown, or the anchor file can't be
  read, the estimate is returned unchanged. A broken clamp must never zero out salaries.

The enricher supplies the tier via the ``salary_tier`` field it now returns (the exact key
of the tier it used in the prompt's Step 3b).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_ANCHORS_PATH = Path(__file__).resolve().parent.parent / "salary_guidlines" / "hk_salary_anchors.json"


def _load_ladders() -> dict:
    try:
        return json.loads(_ANCHORS_PATH.read_text(encoding="utf-8"))["ladders_monthly_hkd"]
    except Exception as exc:  # missing file, bad JSON, schema drift
        logger.warning("Salary anchors unavailable for clamp (%s); clamp disabled.", exc)
        return {}


# Loaded once at import; the ladders are small and static for a given Hays edition.
_LADDERS = _load_ladders()

# Valid tier keys, exposed so the enricher/tests can reference the canonical set.
TIER_KEYS = tuple(_LADDERS.keys()) or (
    "front_office", "commercial_corporate_banking", "corporate_finance_accounting",
    "middle_office", "insurance", "retail_banking", "back_office_operations",
)


def clamp_salary(
    tier: str | None,
    seniority: str | None,
    est_min: int | None,
    est_max: int | None,
) -> tuple[int | None, int | None]:
    """Clip (est_min, est_max) DOWN to the (tier, seniority) band ceiling.

    Returns the estimate unchanged when the tier/seniority is unknown, the anchor file is
    unavailable, or the estimate already sits at/below the band ceiling. Never raises an
    estimate. ``est_min``/``est_max`` may be None (unable-to-estimate) and pass through.
    """
    band = _LADDERS.get(tier or "", {}).get(seniority or "")
    if not band:
        return est_min, est_max
    ceiling = band[1]
    if ceiling is None:  # open-ended band ("+"): nothing to cap against
        return est_min, est_max

    new_max = min(est_max, ceiling) if est_max is not None else None
    new_min = est_min
    # Keep min <= the (possibly lowered) max so the range never inverts.
    if new_min is not None and new_max is not None and new_min > new_max:
        new_min = new_max
    return new_min, new_max
