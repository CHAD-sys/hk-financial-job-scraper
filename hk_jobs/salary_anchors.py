"""
The salary anchor table, loaded once.

WHY THIS EXISTS
---------------
`salary_guidlines/hk_salary_anchors.json` is the calibrated source of every
salary number this project produces. It was read twice, independently, by two
modules that never referred to each other:

  - `hk_jobs/salary_clamp.py` parsed it into ladders/tables/grade-caps and
    enforced them AFTER the model answered;
  - `hk_jobs/enrichers/deepseek.py` rendered it into the prompt so the model
    would clamp itself BEFORE answering.

Two readers of one file is survivable. What was not is that the ceiling those
two enforce existed in THREE places — a constant in salary_clamp.py, the
`meta.global_max_monthly_hkd` field in the file, and a sentence in the prompt —
with a comment on the constant conceding that "that copy is documentation; this
constant is what's enforced". A number nobody can point to a single home for is
a number that eventually disagrees with itself.

The file is the source now. The constant below is a floor under a corrupt or
missing file, not a second opinion.

This module deliberately has no imports from the rest of `hk_jobs`, so both the
clamp and the enricher can depend on it without a cycle.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

ANCHORS_PATH = Path(__file__).resolve().parent.parent / "salary_guidlines" / "hk_salary_anchors.json"

#: Used only when the anchors file cannot be read. It is the value the file
#: carries, restated here so a corrupt file degrades to a conservative ceiling
#: rather than to no ceiling at all — the one thing that must never happen, since
#: an unclamped model estimate ran ~30% high in production (see `meta.
#: global_max_note`).
_FALLBACK_GLOBAL_MAX = 200_000


def _load() -> dict:
    try:
        return json.loads(ANCHORS_PATH.read_text(encoding="utf-8"))
    except Exception as exc:  # missing file, bad JSON, schema drift
        logger.warning(
            "Salary anchors unavailable (%s); tier/role/grade clamps disabled and the "
            "global ceiling falls back to HK$%s/month.", exc, f"{_FALLBACK_GLOBAL_MAX:,}",
        )
        return {}


ANCHORS: dict = _load()

META: dict = ANCHORS.get("meta", {})
LADDERS: dict = ANCHORS.get("ladders_monthly_hkd", {})
TABLES: dict = ANCHORS.get("tables_monthly_hkd", {})
GRADE_CAPS: dict = ANCHORS.get("management_grade_caps_monthly_hkd", {})
BANK_CAPS: dict = GRADE_CAPS.get("bank", {}).get("caps_monthly_hkd", {})
INSURANCE_CAPS: dict = GRADE_CAPS.get("insurance", {}).get("caps_monthly_hkd", {})

# ── Title-grade BANDS (Morris H., 2026-08-19) ────────────────────────────────
# The tables above are ceilings; these are ranges, and they supersede a ceiling
# wherever a title matches. Kept as a SEPARATE key from GRADE_CAPS on purpose:
# `fingerprint()` below hashes GRADE_CAPS, so folding these in would change
# `salary.version()` and mark ~13,000 stored estimates stale, re-paying DeepSeek
# for every one of them. The clamp reads the bands; the fingerprint does not.
GRADE_BANDS: dict = ANCHORS.get("title_grade_bands_monthly_hkd", {})
BANK_BANDS: dict = GRADE_BANDS.get("bank", {}).get("bands_monthly_hkd", {})
INSURANCE_BANDS: dict = GRADE_BANDS.get("insurance", {}).get("bands_monthly_hkd", {})

#: Grades allowed past `GLOBAL_MAX_MONTHLY_HKD` on a deterministic title match.
BANK_EXCEEDS_GLOBAL_MAX: bool = bool(GRADE_BANDS.get("bank", {}).get("exceeds_global_max"))

#: Chinese banks, where "General Manager"/"Deputy GM" is a Director-grade title.
CHINESE_BANK_SLUGS: frozenset = frozenset(
    GRADE_BANDS.get("bank", {}).get("chinese_bank_slugs", ())
)

#: Morris's Tier 1 insurers — the only ones his index applies to at face value.
INSURANCE_TIER_1_SLUGS: frozenset = frozenset(
    GRADE_BANDS.get("insurance", {}).get("tier_1_slugs", ())
)
#: Everyone else in the insurance set takes this discount off a matched band.
INSURANCE_TIER_2_DISCOUNT: float = float(
    GRADE_BANDS.get("insurance", {}).get("tier_2_discount") or 0.0
)

#: The one ceiling. Read from the file, so changing the calibration is one edit.
GLOBAL_MAX_MONTHLY_HKD: int = int(META.get("global_max_monthly_hkd") or _FALLBACK_GLOBAL_MAX)

#: Canonical tier keys, in the file's own low-to-high order.
TIER_KEYS: tuple[str, ...] = tuple(LADDERS.keys()) or (
    "front_office", "commercial_corporate_banking", "corporate_finance_accounting",
    "middle_office", "insurance", "retail_banking", "back_office_operations",
)


def vocabulary() -> dict:
    """The closed (tier -> role -> grade rows, WITH bands) vocabulary.

    Promoted out of `~/.claude/skills/fix-s/scripts/resolve.py`'s local copy so
    the coordinate-first prompt in `hk_jobs/enrichers/deepseek.py` and fix-s's
    offline resolver read one implementation instead of two that can drift.
    Every key here is a key `salary_clamp.price_from_coordinate` can look up, so
    a valid (tier, role, grade) answer is guaranteed to resolve to a band.
    """
    vocab: dict[str, dict] = {}
    for tier, tbl in TABLES.items():
        roles = {}
        for role, ladder in (tbl.get("roles") or {}).items():
            grades = {
                name: band
                for name, band in ladder.items()
                if isinstance(band, list) and len(band) == 2 and band[0] and band[1]
            }
            if grades:
                roles[role] = grades
        if roles:
            vocab[tier] = {"_desc": (tbl.get("_desc") or "").strip(), "roles": roles}
    return vocab


def blinded_vocabulary() -> dict:
    """`vocabulary()` with every dollar band stripped down to grade names only.

    This is what a classifier — the coordinate-first prompt, or fix-s's Opus
    pass — must be shown. Seeing the money lets a model pick the grade whose
    band suits the salary it already had in mind instead of the grade the
    posting actually describes, which turns independent evidence into a menu.
    Names only.
    """
    return {
        tier: {"_desc": t["_desc"], "roles": {r: sorted(g) for r, g in t["roles"].items()}}
        for tier, t in vocabulary().items()
    }


def fingerprint() -> str:
    """
    A short digest of the anchor data that actually affects an estimate.

    Feeds `hk_jobs.salary.version()`. Deliberately over the calibration data and
    not the whole file: re-wording `meta.source` must not invalidate 13,000
    stored estimates and re-pay for them at the model.
    """
    import hashlib

    payload = json.dumps(
        {"ladders": LADDERS, "tables": TABLES, "caps": GRADE_CAPS,
         "global_max": GLOBAL_MAX_MONTHLY_HKD},
        sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8]
