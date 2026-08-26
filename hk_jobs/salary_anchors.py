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

from hk_jobs import employer_segments
from hk_jobs.salary_anchor_schema import validate_role_table_semantics

logger = logging.getLogger(__name__)

ANCHORS_PATH = (
    Path(__file__).resolve().parent.parent / "salary_guidlines" / "hk_salary_anchors.json"
)
PROVENANCE_PATH = ANCHORS_PATH.with_name("hk_salary_anchor_provenance.json")

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
            "global ceiling falls back to HK$%s/month.",
            exc,
            f"{_FALLBACK_GLOBAL_MAX:,}",
        )
        return {}


ANCHORS: dict = _load()
EMPLOYER_GROUPS: dict = ANCHORS.get("employer_groups", {})
BIG_FOUR_SLUGS = employer_segments.slugs_for("big_four")
BIG_FOUR_BANDS: dict = EMPLOYER_GROUPS.get("big_four", {}).get(
    "bands_monthly_hkd", {}
)
BANK_PRODUCT_MANAGEMENT_GROUP: dict = EMPLOYER_GROUPS.get("bank_product_management", {})
BANK_PRODUCT_MANAGEMENT_BANDS: dict = BANK_PRODUCT_MANAGEMENT_GROUP.get(
    "bands_monthly_hkd", {}
)
JPMORGAN_GROUP: dict = EMPLOYER_GROUPS.get("jpmorgan", {})
JPMORGAN_SLUGS = employer_segments.slugs_for("jpmorgan")
JPMORGAN_BANDS: dict = JPMORGAN_GROUP.get("bands_monthly_hkd", {})
HSBC_SIZED_BANKS_GROUP: dict = EMPLOYER_GROUPS.get("hsbc_sized_banks", {})
HSBC_SIZED_BANK_SLUGS = employer_segments.slugs_for("hsbc_sized_banks")
HSBC_SIZED_BANK_BANDS: dict = HSBC_SIZED_BANKS_GROUP.get("bands_monthly_hkd", {})
DBS_SIZED_BANKS_GROUP: dict = EMPLOYER_GROUPS.get("dbs_sized_banks", {})
DBS_SIZED_BANK_SLUGS = employer_segments.slugs_for("dbs_sized_banks")
DBS_SIZED_BANK_BANDS: dict = DBS_SIZED_BANKS_GROUP.get("bands_monthly_hkd", {})
MARKET_INFRASTRUCTURE_GROUP: dict = EMPLOYER_GROUPS.get("market_infrastructure", {})
MARKET_INFRASTRUCTURE_SLUGS = employer_segments.slugs_for("market_infrastructure")
MARKET_INFRASTRUCTURE_BANDS: dict = MARKET_INFRASTRUCTURE_GROUP.get(
    "bands_monthly_hkd", {}
)
ICBC_SIZED_BANKS_GROUP: dict = EMPLOYER_GROUPS.get("icbc_sized_banks", {})
ICBC_SIZED_BANK_SLUGS = employer_segments.slugs_for("icbc_sized_banks")
ICBC_SIZED_BANK_BANDS: dict = ICBC_SIZED_BANKS_GROUP.get("bands_monthly_hkd", {})
ICBC_SIZED_BANK_TITLE_PATTERN: str = str(
    ICBC_SIZED_BANKS_GROUP.get("title_pattern", "")
)
FWD_SIZED_INSURERS_GROUP: dict = EMPLOYER_GROUPS.get("fwd_sized_insurers", {})
FWD_SIZED_INSURER_SLUGS = employer_segments.slugs_for("fwd_sized_insurers")
FWD_SIZED_INSURER_BANDS: dict = FWD_SIZED_INSURERS_GROUP.get("bands_monthly_hkd", {})
DEUTSCHE_MIXED_GROUP: dict = EMPLOYER_GROUPS.get(
    "deutsche_bank_mixed_director_vp", {}
)
DEUTSCHE_MIXED_SLUGS = employer_segments.slugs_for("deutsche_bank_mixed_director_vp")
DEUTSCHE_MIXED_BANDS: dict = DEUTSCHE_MIXED_GROUP.get("bands_monthly_hkd", {})


def _load_provenance() -> dict:
    """Load the audit-only cell ledger without ever disabling salary pricing."""
    try:
        return json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    except Exception as exc:  # provenance is useful, never a production dependency
        logger.warning("Salary-anchor provenance unavailable (%s); pricing remains enabled.", exc)
        return {}


ANCHOR_PROVENANCE: dict = _load_provenance()

META: dict = ANCHORS.get("meta", {})
LADDERS: dict = ANCHORS.get("ladders_monthly_hkd", {})
TABLES: dict = ANCHORS.get("tables_monthly_hkd", {})
ROLE_TABLE_SEMANTICS_CONFIG: dict = ANCHORS.get("role_table_semantics", {})
ROLE_TABLE_SCHEMA_ERRORS: tuple[str, ...] = tuple(
    validate_role_table_semantics(TABLES, ROLE_TABLE_SEMANTICS_CONFIG)
)
if ROLE_TABLE_SCHEMA_ERRORS:
    logger.error(
        "Salary role-table semantics are invalid; coarse role/seniority pricing disabled: %s",
        "; ".join(ROLE_TABLE_SCHEMA_ERRORS),
    )
    ROLE_TABLE_SEMANTICS: dict = {}
else:
    ROLE_TABLE_SEMANTICS = ROLE_TABLE_SEMANTICS_CONFIG.get("tiers", {})
GRADE_CAPS: dict = ANCHORS.get("management_grade_caps_monthly_hkd", {})
BANK_CAPS: dict = GRADE_CAPS.get("bank", {}).get("caps_monthly_hkd", {})
INSURANCE_CAPS: dict = GRADE_CAPS.get("insurance", {}).get("caps_monthly_hkd", {})

# ── Title-grade BANDS (Morris H., 2026-08-19) ────────────────────────────────
# The tables above are ceilings; these are ranges, and they supersede a ceiling
# wherever a title matches. They stay separate from GRADE_CAPS because they are
# a different kind of evidence, but every salary-bearing section participates in
# fingerprint() now. ACCEPTED_PRIOR_VERSIONS records the explicit decision to
# grandfather a prior table; omission can no longer happen invisibly.
GRADE_BANDS: dict = ANCHORS.get("title_grade_bands_monthly_hkd", {})
AMBIGUOUS_MULTI_GRADE_TITLE_BAND: dict = GRADE_BANDS.get(
    "ambiguous_multi_grade_title_band", {}
)
BANK_BANDS: dict = GRADE_BANDS.get("bank", {}).get("bands_monthly_hkd", {})
INSURANCE_BANDS: dict = GRADE_BANDS.get("insurance", {}).get("bands_monthly_hkd", {})
PRODUCT_MANAGER_DIRECTOR_MIN_RAW_MAX_HKD: int = int(
    GRADE_BANDS.get("bank", {}).get("product_manager_director_min_raw_max_hkd") or 0
)
SMALLER_BANK: dict = GRADE_BANDS.get("bank", {}).get("smaller_bank", {})
SMALLER_BANK_SLUGS = employer_segments.slugs_for("smaller_banks")
SMALLER_BANK_DISCOUNT: float = float(SMALLER_BANK.get("discount") or 0.0)
SMALLER_BANK_ROUNDING_INCREMENT_HKD: int = int(
    SMALLER_BANK.get("rounding_increment_hkd") or 1
)
SMALLER_BANK_REVIEWED_TITLE_BANDS: dict = SMALLER_BANK.get(
    "reviewed_title_bands_monthly_hkd", {}
)
MID_SIZED_BANK_DEPARTMENT_HEAD: dict = GRADE_BANDS.get("bank", {}).get(
    "mid_sized_bank_large_department_head", {}
)
MID_SIZED_BANK_DEPARTMENT_HEAD_SLUGS = employer_segments.slugs_for(
    "mid_sized_bank_department_heads"
)
BEA_SIZED_BANK_ASSISTANT_MANAGER: dict = GRADE_BANDS.get("bank", {}).get(
    "bea_sized_bank_functional_assistant_manager", {}
)
BEA_SIZED_BANK_ASSISTANT_MANAGER_SLUGS = employer_segments.slugs_for("bea_sized_banks")
SUN_LIFE_SIZED_INSURER_GRADES: dict = GRADE_BANDS.get("insurance", {}).get(
    "sun_life_sized_insurer_grades", {}
)
SUN_LIFE_SIZED_INSURER_SLUGS = employer_segments.slugs_for("sun_life_sized_insurers")
MID_SIZED_INSURER_SENIOR_MANAGER: dict = GRADE_BANDS.get("insurance", {}).get(
    "mid_sized_insurer_senior_manager", {}
)
MID_SIZED_INSURER_SENIOR_MANAGER_SLUGS = employer_segments.slugs_for("mid_sized_insurers")

# A tiny set of role-and-title-specific corrections that must win over the
# broader corporate-grade bands above. Kept separate so a sentence in the
# notes cannot accidentally become an estimator rule.
TITLE_FUNCTION_BANDS: dict = ANCHORS.get("title_function_bands_monthly_hkd", {})
BANK_FUNCTION_BANDS: dict = TITLE_FUNCTION_BANDS.get("bank", {})
INSURANCE_FUNCTION_BANDS: dict = TITLE_FUNCTION_BANDS.get("insurance", {})

# Employer overlays are intentionally separate from general anchors and title-grade
# bands.  Each one is a narrowly evidenced exception for a named employer and
# function-bearing title; it must never quietly become a rule for every employer
# that happens to use the same grade word.
EMPLOYER_SALARY_OVERLAYS: tuple[dict, ...] = tuple(
    ANCHORS.get("employer_salary_overlays_monthly_hkd", {}).get("rules", ())
)

# Morris's Manager-grade floor is separate from the anchor cells: it is a
# cross-function protection applied only after a title has passed the clamp's
# finance-grade classifier. The JSON owns the numbers and explicit additional
# large-employer registry; bank/insurer membership remains in the clamp because
# those existing allowlists are the project's source of truth for those groups.
MANAGER_GRADE_FLOORS: dict = ANCHORS.get("manager_grade_floors_monthly_hkd", {})

#: Grades allowed past `GLOBAL_MAX_MONTHLY_HKD` on a deterministic title match.
BANK_EXCEEDS_GLOBAL_MAX: bool = bool(GRADE_BANDS.get("bank", {}).get("exceeds_global_max"))

#: Chinese banks, where "General Manager"/"Deputy GM" is a Director-grade title.
CHINESE_BANK_SLUGS = employer_segments.slugs_for("chinese_banks")

#: Morris's Tier 1 insurers — the only ones his index applies to at face value.
INSURANCE_TIER_1_SLUGS = employer_segments.slugs_for("insurance_tier_1")
#: Reviewed Tier 2 insurers. An unclassified insurer is not silently Tier 2.
INSURANCE_TIER_2_SLUGS = employer_segments.slugs_for("insurance_tier_2")
#: Discount applied only to an explicitly reviewed Tier 2 insurer.
INSURANCE_TIER_2_DISCOUNT: float = float(
    GRADE_BANDS.get("insurance", {}).get("tier_2_discount") or 0.0
)

#: The one ceiling. Read from the file, so changing the calibration is one edit.
GLOBAL_MAX_MONTHLY_HKD: int = int(META.get("global_max_monthly_hkd") or _FALLBACK_GLOBAL_MAX)

#: Canonical tier keys, in the file's own low-to-high order.
TIER_KEYS: tuple[str, ...] = tuple(LADDERS.keys()) or (
    "front_office",
    "commercial_corporate_banking",
    "corporate_finance_accounting",
    "middle_office",
    "insurance",
    "retail_banking",
    "back_office_operations",
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


def provenance_for(tier: str | None, role: str | None, grade: str | None) -> dict | None:
    """Audit lineage for one exact anchor coordinate, never used to price it."""
    if not tier or not role or not grade:
        return None
    return ANCHOR_PROVENANCE.get("cells", {}).get(f"{tier}/{role}/{grade}")


def _behaviour_only(value):
    """Strip explanatory fields while retaining every salary-bearing value."""
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            name = str(key).lower()
            if name in {"_desc", "_source", "note"} or name.endswith("_note"):
                continue
            cleaned[key] = _behaviour_only(item)
        return cleaned
    if isinstance(value, list):
        return [_behaviour_only(item) for item in value]
    return value


def fingerprint() -> str:
    """
    A short digest of the anchor data that actually affects an estimate.

    Feeds `hk_jobs.salary.version()`. Every top-level configuration section is
    behaviour unless it is prose-only ``meta``. This matters because employer
    groups, title/function bands, overlays and Manager floors were added after
    the original ladders/tables/caps allowlist and silently changed estimates
    without changing the version.

    ``meta.global_max_monthly_hkd`` is the one behavioural metadata field. The
    rest of ``meta`` is deliberately excluded, so re-wording source notes does
    not invalidate stored estimates and re-pay for them at the model.
    """
    import hashlib

    configuration = _behaviour_only(
        {key: value for key, value in ANCHORS.items() if key != "meta"}
    )
    payload = json.dumps(
        {
            "configuration": configuration,
            # Keep the three historical runtime objects explicit. Besides
            # documenting the important core, this makes the fingerprint honest
            # if a test or long-lived process replaces one after module load.
            "runtime_ladders": _behaviour_only(LADDERS),
            "runtime_tables": _behaviour_only(TABLES),
            "runtime_caps": _behaviour_only(GRADE_CAPS),
            "global_max": GLOBAL_MAX_MONTHLY_HKD,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8]
