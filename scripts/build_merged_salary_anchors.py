#!/usr/bin/env python3
"""Build the merged, granular salary anchor table from immutable inputs.

Sources (all in salary_guidlines/):
  - hays_2026.json              -> Hays 2026 (legacy monthly package proxy)
  - persolkelly_2025.json       -> PERSOLKELLY 2025 (annual /12; conservative)
  - adecco_2026.json            -> Adecco 2026 (monthly; mid-market)
  - hk_salary_anchor_overrides.json -> reviewed additions/corrections after the merge

Package-free rule (2026-08-25): Hays reports total annual package, so it never
participates when PERSOLKELLY or Adecco covers the same (role, grade) cell. The
package-free candidates are ranked by midpoint ascending and merged with the
existing conservative 60% / 25% weights. Hays remains only as an explicit
temporary fallback where neither package-free source has coverage.
Every output value is capped at HK$200,000/month and rounded to the nearest 500.

Banking roles are standardised onto the Analyst / Associate / VP / Director / MD
grade ladder; insurance roles onto PERSOLKELLY's 4-grade ladder. Hays'
idiosyncratic ladders are sampled at grade fractions to line them up. Roles that
only Hays covers are carried over unchanged.

Output: reproduces hk_salary_anchors.json from those four inputs.  Existing output
is never silently overwritten: use --capture-overrides after a reviewed manual edit,
or --force after intentionally changing a published guide input.
"""
from __future__ import annotations

import argparse
import copy
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from hk_jobs.salary_anchor_schema import (
    derive_role_table_semantics,
    validate_role_table_semantics,
)

GUIDE_DIR = PROJECT_ROOT / "salary_guidlines"
ANCHORS_PATH = GUIDE_DIR / "hk_salary_anchors.json"
HAYS_PATH = GUIDE_DIR / "hays_2026.json"
OVERRIDES_PATH = GUIDE_DIR / "hk_salary_anchor_overrides.json"
GLOBAL_MAX = 200_000
WEIGHTS = [0.60, 0.25, 0.15]  # most conservative -> least, renormalised per cell

hays = json.loads(HAYS_PATH.read_text(encoding="utf-8"))
pk = json.loads((GUIDE_DIR / "persolkelly_2025.json").read_text(encoding="utf-8"))
adecco = json.loads((GUIDE_DIR / "adecco_2026.json").read_text(encoding="utf-8"))

H = hays["tables_monthly_hkd"]

BANK_GRADES = ["Analyst", "Associate", "VP", "Director", "MD"]
BANK_FRACS = [0.0, 0.25, 0.5, 0.75, 1.0]
PK_BANK_KEYS = ["analyst", "associate", "vp", "director", "md"]
INS_GRADES = ["Officer / Senior Analyst", "Assistant Manager / Manager",
              "Senior Manager / Senior Director", "Head"]
INS_FRACS = [0.0, 1 / 3, 2 / 3, 1.0]
PK_INS_KEYS = ["officer_senior_analyst", "asst_manager_manager",
               "senior_manager_senior_director", "head"]


class MappedBand(list):
    """A JSON-compatible band that carries its declared guide-row lineage in memory."""

    def __init__(self, band, mappings=()):
        super().__init__(band)
        self.mappings = tuple(dict(mapping) for mapping in mappings)


def _mapping(source: str, native_role: str, native_experience_band: str) -> dict[str, str]:
    return {
        "source": source,
        "native_role": native_role,
        "native_experience_band": native_experience_band,
    }


def _norm(band):
    """[lo, hi|None] -> (lo, hi_est) with an estimated top for open-ended bands."""
    lo, hi = band
    if hi is None:
        hi = round(lo * 1.25)
    return lo, hi


def hays_at(tier: str, role: str, frac: float):
    """Sample a Hays role ladder at a grade fraction. None if role missing."""
    ladder = H.get(tier, {}).get("roles", {}).get(role)
    if not ladder:
        return None
    rows = [(label, band) for label, band in ladder.items() if isinstance(band, list)]
    idx = round(frac * (len(rows) - 1))
    label, band = rows[idx]
    return MappedBand(
        _norm(band), [_mapping("hays_2026", f"{tier}/{role}", label)]
    )


def hays_row(tier: str, role: str, label: str):
    band = H.get(tier, {}).get("roles", {}).get(role, {}).get(label)
    return (
        MappedBand(_norm(band), [_mapping("hays_2026", f"{tier}/{role}", label)])
        if band
        else None
    )


def hays_ladder(tier: str, role: str):
    """Copy one Hays ladder while retaining every native row label."""
    return {
        label: MappedBand(
            band, [_mapping("hays_2026", f"{tier}/{role}", label)]
        )
        for label, band in H[tier]["roles"][role].items()
    }


def pk_annual(section: str, role: str, key: str):
    band = pk[section].get(role, {}).get(key)
    if not band:
        return None
    lo, hi = band
    return MappedBand(
        [round(lo / 12), GLOBAL_MAX if hi is None else round(hi / 12)],
        [_mapping("persolkelly_2025", f"{section}/{role}", key)],
    )


def adecco_cell(section: str, role: str, title: str):
    band = adecco[section].get(role, {}).get(title)
    if not band:
        return None
    lo, hi = band
    return MappedBand(
        [lo, GLOBAL_MAX if hi is None else hi],
        [_mapping("adecco_2026", f"{section}/{role}", title)],
    )


def merge(cells):
    """Weighted average of candidate bands; conservative-ranked 60/25/15."""
    cells = [c for c in cells if c]
    if not cells:
        return None
    cells.sort(key=lambda c: (c[0] + c[1]) / 2)
    w = WEIGHTS[: len(cells)]
    total = sum(w)
    w = [x / total for x in w]
    lo = sum(c[0] * wi for c, wi in zip(cells, w))
    hi = sum(c[1] * wi for c, wi in zip(cells, w))
    lo, hi = min(round(lo / 500) * 500, GLOBAL_MAX), min(round(hi / 500) * 500, GLOBAL_MAX)
    if lo >= hi:  # keep a sane spread in the reference itself
        lo = round(hi * 0.8 / 500) * 500
    mappings = [mapping for cell in cells for mapping in getattr(cell, "mappings", ())]
    return MappedBand([lo, hi], mappings)


def _average(cells):
    """Average same-publisher rows without losing their individual native coordinates."""
    return MappedBand(
        [
            round(sum(cell[0] for cell in cells) / len(cells)),
            round(sum(cell[1] for cell in cells) / len(cells)),
        ],
        [mapping for cell in cells for mapping in getattr(cell, "mappings", ())],
    )


def merge_package_fallback(hays_package, package_free_cells):
    """Merge package-free evidence, falling back to Hays only when it is all we have."""
    compatible = [cell for cell in package_free_cells if cell]
    if compatible:
        return merge(compatible)
    return merge([hays_package])


def bank_ladder(hays_ref=None, pk_roles=(), adecco_map=None):
    """Build a 5-grade Analyst..MD ladder from any mix of sources.

    hays_ref: (tier, role) sampled at grade fractions.
    pk_roles: list of (section, role) — multiple PK ladders are pre-averaged so
              one source never gets two votes in the weighting.
    adecco_map: {grade_name: (section, role, title)} explicit per-grade cells.
    """
    out = {}
    for grade, frac, pk_key in zip(BANK_GRADES, BANK_FRACS, PK_BANK_KEYS):
        hays_package = hays_at(*hays_ref, frac) if hays_ref else None
        package_free_cells = []
        pk_cells = [pk_annual(sec, role, pk_key) for sec, role in pk_roles]
        pk_cells = [c for c in pk_cells if c]
        if pk_cells:
            package_free_cells.append(_average(pk_cells))
        if adecco_map and grade in adecco_map:
            package_free_cells.append(adecco_cell(*adecco_map[grade]))
        band = merge_package_fallback(hays_package, package_free_cells)
        if band:
            out[grade] = band
    return out


def ins_ladder(hays_ref=None, pk_roles=()):
    """Build a 4-grade insurance ladder (PK labels), same weighting rules."""
    out = {}
    for grade, frac, pk_key in zip(INS_GRADES, INS_FRACS, PK_INS_KEYS):
        hays_package = hays_at(*hays_ref, frac) if hays_ref else None
        package_free_cells = []
        pk_cells = [pk_annual("insurance_annual_hkd", role, pk_key) for role in pk_roles]
        pk_cells = [c for c in pk_cells if c]
        if pk_cells:
            package_free_cells.append(_average(pk_cells))
        band = merge_package_fallback(hays_package, package_free_cells)
        if band:
            out[grade] = band
    return out


def direct_ladder(
    section_dict: dict,
    *,
    source: str,
    native_role: str | dict[str, str],
    annual: bool = False,
):
    """Carry a single-source title-keyed ladder through cap+round unchanged."""
    out = {}
    for title, band in section_dict.items():
        lo, hi = band
        if annual:
            lo = round(lo / 12)
            hi = GLOBAL_MAX if hi is None else round(hi / 12)
        elif hi is None:
            hi = GLOBAL_MAX
        role = native_role[title] if isinstance(native_role, dict) else native_role
        source_band = MappedBand([lo, hi], [_mapping(source, role, title)])
        band = merge([source_band])
        out[title] = band
    return out


def _native_roles(*sections: tuple[str, dict]) -> dict[str, str]:
    """Declare the native section for every title in a combined direct ladder."""
    return {
        title: native_role
        for native_role, rows in sections
        for title in rows
    }


_NO_CHANGE = object()


def apply_merge_patch(base: Any, patch: Any) -> Any:
    """Apply a JSON Merge Patch without mutating either input.

    Objects merge recursively, arrays and scalar values replace their target,
    and ``null`` deletes an object key.  This keeps the reviewed delta compact
    while still making every non-guide cell a declared build input.
    """
    if not isinstance(patch, dict):
        return copy.deepcopy(patch)
    result = copy.deepcopy(base) if isinstance(base, dict) else {}
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
        else:
            result[key] = apply_merge_patch(result.get(key), value)
    return result


def make_merge_patch(base: Any, target: Any) -> Any:
    """Return the smallest JSON Merge Patch that turns ``base`` into ``target``."""
    if isinstance(base, dict) and isinstance(target, dict):
        patch: dict[str, Any] = {}
        for key in sorted(base.keys() - target.keys()):
            patch[key] = None
        for key, target_value in target.items():
            if key not in base:
                patch[key] = copy.deepcopy(target_value)
                continue
            child = make_merge_patch(base[key], target_value)
            if child is not _NO_CHANGE:
                patch[key] = child
        return patch if patch else _NO_CHANGE
    if base == target:
        return _NO_CHANGE
    return copy.deepcopy(target)


tables: dict = {}

# ── FRONT OFFICE ────────────────────────────────────────────────────────────────
fo = {"_desc": H["front_office"]["_desc"], "roles": {}}
R = fo["roles"]
R["equity_research"] = bank_ladder(("front_office", "research_strategy_ficc_equity"),
                                   [("banking_financial_services_annual_hkd", "equity_research")])
R["global_markets_trading"] = bank_ladder(("front_office", "global_markets_trading"),
                                          [("banking_financial_services_annual_hkd", "sales_trading")])
R["financial_markets_sales"] = hays_ladder("front_office", "financial_markets_sales")
R["corporate_finance_ma_ecm_dcm"] = hays_ladder("front_office", "corporate_finance_ma_ecm_dcm")
R["private_equity"] = hays_ladder("front_office", "private_equity")
R["hedge_fund_investment"] = hays_ladder("front_office", "hedge_fund_investment")
R["asset_management_research"] = bank_ladder(("front_office", "asset_management_research"),
                                             [("banking_financial_services_annual_hkd", "am_research")])
R["asset_management_portfolio"] = bank_ladder(("front_office", "asset_management_fund"),
                                              [("banking_financial_services_annual_hkd", "am_portfolio_management")])
R["asset_management_sales"] = bank_ladder(("front_office", "asset_management_sales"),
                                          [("banking_financial_services_annual_hkd", "am_institutional_distribution_sales")])
R["private_banking_rm"] = bank_ladder(("front_office", "private_banking_rm"),
                                      [("banking_financial_services_annual_hkd", "private_banking_rm")])
R["assistant_private_banker"] = bank_ladder(None, [("banking_financial_services_annual_hkd", "assistant_private_banker")])
R["investment_counsellor"] = hays_ladder("front_office", "investment_counsellor")
R["digital_assets_sales"] = bank_ladder(None, [("banking_financial_services_annual_hkd", "digital_assets_institutional_sales")])
R["digital_assets_quant_trading"] = bank_ladder(None, [("banking_financial_services_annual_hkd", "digital_assets_quant_traders")])
tables["front_office"] = fo

# ── COMMERCIAL / CORPORATE BANKING ─────────────────────────────────────────────
ccb = {"_desc": H["commercial_corporate_banking"]["_desc"], "roles": {}}
R = ccb["roles"]
R["corporate_banking_rm"] = bank_ladder(("commercial_corporate_banking", "corporate_banking_rm"),
                                        [("banking_financial_services_annual_hkd", "corporate_banking_rm")])
for keep in ["commercial_banking_rm", "sme_banking_rm", "fi_banking_rm",
             "transaction_banking_rm", "wealth_management"]:
    R[keep] = hays_ladder("commercial_corporate_banking", keep)
tables["commercial_corporate_banking"] = ccb

# ── RETAIL BANKING (Hays only — carried over) ──────────────────────────────────
tables["retail_banking"] = {
    "_desc": H["retail_banking"]["_desc"],
    "roles": {
        role: hays_ladder("retail_banking", role)
        for role in H["retail_banking"]["roles"]
    },
}

# ── MIDDLE OFFICE ──────────────────────────────────────────────────────────────
mo = {"_desc": H["middle_office"]["_desc"] + " Includes legal, company secretarial, "
      "IT leadership/governance and cybersecurity at financial firms.", "roles": {}}
R = mo["roles"]
R["risk_credit"] = hays_ladder("middle_office", "risk_credit")
R["risk_market"] = hays_ladder("middle_office", "risk_market")
R["risk_management_general"] = bank_ladder(("middle_office", "risk_ops_enterprise"),
                                           [("banking_financial_services_annual_hkd", "risk_management")])
R["risk_climate_modeling_validation"] = hays_ladder("middle_office", "risk_climate_modeling_validation")
R["compliance_banking"] = bank_ladder(("middle_office", "compliance_banking"),
                                      [("banking_financial_services_annual_hkd", "compliance_banking")])
R["fcc_aml"] = bank_ladder(None, [("banking_financial_services_annual_hkd", "fcc_aml"),
                                  ("banking_financial_services_annual_hkd", "anti_bribery_corruption")])
R["kyc_cdd_client_onboarding"] = bank_ladder(None, [("banking_financial_services_annual_hkd", "kyc_cdd"),
                                                    ("banking_financial_services_annual_hkd", "operations_kyc_cdd_onboarding")])
R["audit_banking"] = bank_ladder(("middle_office", "audit_banking"),
                                 [("banking_financial_services_annual_hkd", "internal_audit_banking")],
                                 {"Analyst": ("accounting_finance_monthly_hkd", "audit", "auditor"),
                                  "Associate": ("accounting_finance_monthly_hkd", "audit", "senior_auditor"),
                                  "VP": ("accounting_finance_monthly_hkd", "audit", "audit_manager"),
                                  "Director": ("accounting_finance_monthly_hkd", "audit", "head_of_audit")})
R["trade_support"] = hays_ladder("middle_office", "trade_support")
R["product_management"] = hays_ladder("middle_office", "product_management")
R["change_project_management"] = bank_ladder(("middle_office", "change_project_management"),
                                             [("banking_financial_services_annual_hkd", "project_management_banking")])
R["performance_investment_risk"] = hays_ladder("middle_office", "performance_investment_risk")
R["forensic_accounting"] = bank_ladder(None, [("banking_financial_services_annual_hkd", "forensic_accounting")])
R["legal_counsel"] = bank_ladder(None, [("banking_financial_services_annual_hkd", "legal_counsel_banking")],
                                 {"Analyst": ("legal_compliance_monthly_hkd", "legal_inhouse", "associate_legal_counsel"),
                                  "Associate": ("legal_compliance_monthly_hkd", "legal_inhouse", "legal_counsel"),
                                  "VP": ("legal_compliance_monthly_hkd", "legal_inhouse", "senior_legal_counsel"),
                                  "Director": ("legal_compliance_monthly_hkd", "legal_inhouse", "head_of_legal_general_counsel")})
R["company_secretarial"] = direct_ladder(adecco["legal_compliance_monthly_hkd"]["company_secretarial"], source="adecco_2026", native_role="legal_compliance_monthly_hkd/company_secretarial")
R["compliance_corporate_inhouse"] = direct_ladder(adecco["legal_compliance_monthly_hkd"]["compliance_inhouse"], source="adecco_2026", native_role="legal_compliance_monthly_hkd/compliance_inhouse")
R["it_executive_leadership"] = direct_ladder(adecco["information_technology_monthly_hkd"]["it_executive_leadership"], source="adecco_2026", native_role="information_technology_monthly_hkd/it_executive_leadership")
R["it_management"] = direct_ladder(adecco["information_technology_monthly_hkd"]["it_management"], source="adecco_2026", native_role="information_technology_monthly_hkd/it_management")
R["it_governance_risk_compliance"] = direct_ladder(adecco["information_technology_monthly_hkd"]["it_governance_risk_compliance"], source="adecco_2026", native_role="information_technology_monthly_hkd/it_governance_risk_compliance")
R["cybersecurity"] = direct_ladder(adecco["information_technology_monthly_hkd"]["cybersecurity"], source="adecco_2026", native_role="information_technology_monthly_hkd/cybersecurity")
tables["middle_office"] = mo

# ── BACK OFFICE / OPERATIONS ───────────────────────────────────────────────────
bo = {"_desc": H["back_office_operations"]["_desc"] + " Also HR, admin/secretarial, "
      "customer service, marketing and hands-on IT/engineering at financial firms.", "roles": {}}
R = bo["roles"]
R["operations_general"] = bank_ladder(("back_office_operations", "operations_general"),
                                      [("banking_financial_services_annual_hkd", "operations_administration")])
R["payment_operation"] = bank_ladder(("back_office_operations", "payment_operation"),
                                     [("banking_financial_services_annual_hkd", "remittance")])
R["fund_operations"] = bank_ladder(("back_office_operations", "fund_investment_operations"),
                                   [("banking_financial_services_annual_hkd", "am_fund_operation")])
R["fund_accounting"] = bank_ladder(None, [("banking_financial_services_annual_hkd", "am_fund_accounting")])
R["collateral_management"] = hays_ladder("back_office_operations", "collateral_management")
R["loans_operation"] = bank_ladder(None, [("banking_financial_services_annual_hkd", "loans_operation")])
R["trade_services"] = bank_ladder(None, [("banking_financial_services_annual_hkd", "trade_services")])
R["documentation_operations"] = bank_ladder(None, [("banking_financial_services_annual_hkd", "operations_documentation")])
R["client_services_am"] = bank_ladder(None, [("banking_financial_services_annual_hkd", "am_client_services")])
R["rfp_proposals"] = bank_ladder(None, [("banking_financial_services_annual_hkd", "am_rfp")])
R["human_resources"] = direct_ladder(adecco["corporate_support_monthly_hkd"]["human_resources"], source="adecco_2026", native_role="corporate_support_monthly_hkd/human_resources")
_admin = adecco["corporate_support_monthly_hkd"]["administrative"]
_secretarial = adecco["corporate_support_monthly_hkd"]["secretarial"]
R["secretarial_admin"] = direct_ladder(
    {**_admin, **_secretarial},
    source="adecco_2026",
    native_role=_native_roles(
        ("corporate_support_monthly_hkd/administrative", _admin),
        ("corporate_support_monthly_hkd/secretarial", _secretarial),
    ),
)
R["customer_service"] = direct_ladder(adecco["customer_service_monthly_hkd"]["customer_service"], source="adecco_2026", native_role="customer_service_monthly_hkd/customer_service")
_marketing = adecco["marketing_monthly_hkd"]["marketing"]
_public_relations = adecco["marketing_monthly_hkd"]["public_relations"]
R["marketing_communications"] = direct_ladder(
    {**_marketing, **_public_relations},
    source="adecco_2026",
    native_role=_native_roles(
        ("marketing_monthly_hkd/marketing", _marketing),
        ("marketing_monthly_hkd/public_relations", _public_relations),
    ),
)
R["ecommerce_digital"] = direct_ladder(adecco["marketing_monthly_hkd"]["ecommerce_digital"], source="adecco_2026", native_role="marketing_monthly_hkd/ecommerce_digital")
R["software_data_engineering"] = direct_ladder(adecco["information_technology_monthly_hkd"]["software_data_engineering"], source="adecco_2026", native_role="information_technology_monthly_hkd/software_data_engineering")
R["it_infrastructure_support"] = direct_ladder(adecco["information_technology_monthly_hkd"]["it_infrastructure_support"], source="adecco_2026", native_role="information_technology_monthly_hkd/it_infrastructure_support")
tables["back_office_operations"] = bo

# ── CORPORATE FINANCE & ACCOUNTING ─────────────────────────────────────────────
cfa = {"_desc": H["corporate_finance_accounting"]["_desc"], "roles": {}}
R = cfa["roles"]
R["banking_industry_finance"] = bank_ladder(("corporate_finance_accounting", "banking_industry_finance"),
                                            [("banking_financial_services_annual_hkd", "financial_control_reporting")])
R["regulatory_reporting"] = bank_ladder(None, [("banking_financial_services_annual_hkd", "regulatory_reporting")])
R["management_reporting"] = bank_ladder(None, [("banking_financial_services_annual_hkd", "management_reporting")])
R["treasury"] = bank_ladder(("corporate_finance_accounting", "treasury"),
                            [("banking_financial_services_annual_hkd", "treasury_banking")])
R["product_control"] = bank_ladder(("corporate_finance_accounting", "product_control"),
                                   [("banking_financial_services_annual_hkd", "product_control")])
R["tax"] = hays_ladder("corporate_finance_accounting", "tax")
R["shared_service_centre"] = hays_ladder("corporate_finance_accounting", "shared_service_centre")
R["accounting_support"] = hays_ladder("corporate_finance_accounting", "accounting_support")
R["professional_practice_advisory"] = hays_ladder("corporate_finance_accounting", "professional_practice_advisory")

# corporate accounting/finance: package-free sources first, Hays only as fallback
_pkc = "corporate_professionals_finance_annual_hkd"
_adf = "accounting_finance_monthly_hkd"
corp_rows = {
    "Accounts Clerk": (
        None,
        [
            adecco_cell(_adf, "accounting", "account_clerk_assistant"),
            pk_annual(_pkc, "financial_accounting_corporate", "accounts_clerk"),
        ],
    ),
    "Assistant Accountant": (
        hays_row("corporate_finance_accounting", "in_house_finance_ci", "Senior Accountant"),
        [
            adecco_cell(_adf, "accounting", "assistant_accountant"),
            pk_annual(_pkc, "financial_accounting_corporate", "assistant_accountant"),
        ],
    ),
    "Accountant / Financial Analyst": (
        hays_row("corporate_finance_accounting", "in_house_finance_ci", "Financial Analyst"),
        [adecco_cell(_adf, "finance", "financial_analyst")],
    ),
    "Finance Manager": (
        hays_row("corporate_finance_accounting", "in_house_finance_ci", "FP&A Manager"),
        [
            adecco_cell(_adf, "finance", "finance_manager"),
            pk_annual(_pkc, "financial_accounting_corporate", "finance_manager"),
        ],
    ),
    "Senior Finance Manager / Controller": (
        hays_row("corporate_finance_accounting", "in_house_finance_ci", "Financial Controller"),
        [
            pk_annual(_pkc, "financial_accounting_corporate", "controller"),
            adecco_cell(_adf, "finance", "financial_controller"),
        ],
    ),
    "Finance Director": (
        hays_row("corporate_finance_accounting", "in_house_finance_ci", "FP&A Director"),
        [
            adecco_cell(_adf, "finance", "finance_director"),
            pk_annual(_pkc, "financial_accounting_corporate", "director_department_head"),
        ],
    ),
    "CFO": (
        hays_row("corporate_finance_accounting", "in_house_finance_ci", "Finance Director / CFO"),
        [
            adecco_cell(_adf, "finance", "cfo"),
            pk_annual(_pkc, "financial_accounting_corporate", "cfo"),
        ],
    ),
}
R["corporate_accounting_finance"] = {
    label: merge_package_fallback(hays_package, package_free_cells)
    for label, (hays_package, package_free_cells) in corp_rows.items()
}

audit_corp_rows = {
    "Internal Auditor": [adecco_cell(_adf, "audit", "senior_auditor"),
                         pk_annual(_pkc, "audit_internal_control_corporate", "internal_auditor")],
    "Audit Manager": [adecco_cell(_adf, "audit", "audit_manager"),
                      pk_annual(_pkc, "audit_internal_control_corporate", "internal_audit_manager")],
    "Head of Audit": [adecco_cell(_adf, "audit", "head_of_audit"),
                      pk_annual(_pkc, "audit_internal_control_corporate", "head_of_audit")],
}
R["audit_internal_control_corporate"] = {label: merge(cells) for label, cells in audit_corp_rows.items()}
R["fpa_corporate"] = direct_ladder(pk[_pkc]["fpa_corporate"], source="persolkelly_2025", native_role=f"{_pkc}/fpa_corporate", annual=True)
tables["corporate_finance_accounting"] = cfa

# ── INSURANCE ──────────────────────────────────────────────────────────────────
ins = {"_desc": H["insurance"]["_desc"], "roles": {}}
R = ins["roles"]
R["actuarial"] = ins_ladder(("insurance", "actuarial"),
                            ["actuarial_bancassurance", "actuarial_agency", "actuarial_brokerage"])
R["actuarial_pricing"] = hays_ladder("insurance", "actuarial_pricing")
R["investment"] = hays_ladder("insurance", "investment")
R["underwriting"] = ins_ladder(("insurance", "underwriting"), ["insurance_underwriting"])
R["claims"] = ins_ladder(("insurance", "claims"), ["insurance_claims"])
R["agency_distribution"] = ins_ladder(("insurance", "agency"), ["distribution_agency"])
R["bancassurance_distribution"] = ins_ladder(("insurance", "distribution_bancassurance"),
                                             ["distribution_bancassurance"])
R["brokerage_distribution"] = ins_ladder(None, ["distribution_brokerage"])
R["distribution_training"] = ins_ladder(None, ["distribution_training_development"])
R["insurance_marketing"] = ins_ladder(None, ["insurance_marketing"])
R["risk_insurance"] = ins_ladder(("insurance", "risk_insurance"), ["insurance_risk"])
R["compliance_insurance"] = ins_ladder(("insurance", "compliance_insurance"), ["insurance_compliance"])
R["audit_insurance"] = ins_ladder(("insurance", "audit_insurance"), ["insurance_auditing"])
R["accounting_insurance"] = ins_ladder(("insurance", "accounting_insurance"),
                                       ["insurance_accounting_generalist", "insurance_financial_reporting"])
R["legal_insurance"] = ins_ladder(None, ["insurance_legal"])
R["policy_administration"] = ins_ladder(None, ["insurance_policy_administration"])
R["insurance_customer_service"] = ins_ladder(None, ["insurance_customer_service"])
R["insurance_hr"] = ins_ladder(None, ["insurance_hr_generalist", "insurance_hr_comp_benefits"])
R["strategic_operations"] = hays_ladder("insurance", "strategic_operations")
R["product_development"] = hays_ladder("insurance", "product_development")
R["pension_operations"] = hays_ladder("insurance", "pension_operations")
tables["insurance"] = ins


def declared_native_source_rows() -> dict[str, list[dict[str, str]]]:
    """Return exact guide rows attached to every reproducible baseline cell.

    The mapping exists only in memory because salary bands must remain plain JSON
    arrays at runtime. The provenance builder imports this function and writes the
    mappings to its separate audit ledger.
    """
    declared: dict[str, list[dict[str, str]]] = {}
    for tier, table in tables.items():
        for role, ladder in table["roles"].items():
            for grade, band in ladder.items():
                mappings = getattr(band, "mappings", ())
                if not mappings:
                    continue
                unique = {tuple(sorted(mapping.items())): mapping for mapping in mappings}
                declared[f"{tier}/{role}/{grade}"] = [
                    unique[key] for key in sorted(unique)
                ]
    return declared


# ── derive coarse per-tier ladders (loose envelope: min-lo / max-hi per grade) ──
GRADE_TO_LEVEL = {"junior": 0.0, "mid": 1 / 3, "senior": 2 / 3, "lead": 1.0}
ladders = {}
for tier, tdata in tables.items():
    tier_ladder = {}
    for level, frac in GRADE_TO_LEVEL.items():
        los, his = [], []
        for role, ladder in tdata["roles"].items():
            rows = [b for b in ladder.values() if isinstance(b, list) and b[1] is not None]
            if not rows:
                continue
            idx = round(frac * (len(rows) - 1))
            los.append(rows[idx][0])
            his.append(rows[idx][1])
        if los:
            tier_ladder[level] = [min(los), min(max(his), GLOBAL_MAX)]
    ladders[tier] = tier_ladder

# ── assemble the published baseline ───────────────────────────────────────────
hays["meta"]["source"] = (
    "Package-free merge 2026-08-25: PERSOLKELLY annual base /12 and Adecco monthly salary "
    "with stated exclusions. Hays annual total-package proxies are used only where neither "
    "package-free source covers the cell."
)
hays["meta"]["merge_script"] = "scripts/build_merged_salary_anchors.py (rerun after editing source JSONs)"
hays["meta"]["grade_ladder_note"] = (
    "Banking roles use Analyst/Associate/VP/Director/MD rows (PERSOLKELLY year bands: 0-3/3-7/"
    "7-10/10+/15+). Insurance roles use Officer-Senior Analyst / AsstMgr-Manager / SrMgr-SrDirector "
    "/ Head. Roles only covered by one source carry that source's own row labels."
)
hays["tables_monthly_hkd"] = tables
hays["ladders_monthly_hkd"] = ladders


def _render(anchors: dict[str, Any]) -> str:
    return json.dumps(anchors, indent=2, ensure_ascii=False) + "\n"


def _describe(anchors: dict[str, Any]) -> str:
    output_tables = anchors["tables_monthly_hkd"]
    n_roles = sum(len(table["roles"]) for table in output_tables.values())
    n_rows = sum(
        len(grades)
        for table in output_tables.values()
        for grades in table["roles"].values()
    )
    return f"{len(output_tables)} tiers, {n_roles} roles, {n_rows} salary rows"


def _published_build(*, include_overrides: bool = True) -> dict[str, Any]:
    if include_overrides:
        if not OVERRIDES_PATH.exists():
            raise FileNotFoundError(
                f"Missing reviewed overlay: {OVERRIDES_PATH}. "
                "Run with --capture-overrides only if the current published table is correct."
            )
        overrides = json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
        published = apply_merge_patch(hays, overrides)
    else:
        published = copy.deepcopy(hays)

    # Derived after the reviewed overlay so every added/removed role is typed.
    # The generated section is never hand-edited and cannot drift from the table.
    published["role_table_semantics"] = derive_role_table_semantics(
        published["tables_monthly_hkd"]
    )
    # The immutable raw Hays snapshot contains one cap-collapsed 200k/200k cell.
    # ``--without-overrides`` exists only for provenance sensitivity and must
    # reproduce that source artifact verbatim. The publishable, overlaid build is
    # strict and repairs/rejects it before it can reach runtime.
    if include_overrides:
        errors = validate_role_table_semantics(
            published["tables_monthly_hkd"], published["role_table_semantics"]
        )
        if errors:
            raise ValueError("Invalid salary role-table schema:\n- " + "\n- ".join(errors))
    return published


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="fail if hk_salary_anchors.json is not reproducible from its declared inputs",
    )
    mode.add_argument(
        "--capture-overrides",
        action="store_true",
        help="capture reviewed differences in the current published file as the overlay",
    )
    parser.add_argument(
        "--without-overrides",
        action="store_true",
        help="build only the three-guide baseline (used by provenance sensitivity checks)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace a differing published file after backing it up",
    )
    args = parser.parse_args(argv)

    if args.capture_overrides:
        if args.without_overrides or args.force:
            parser.error("--capture-overrides cannot be combined with --without-overrides/--force")
        if not ANCHORS_PATH.exists():
            parser.error(f"cannot capture overrides: {ANCHORS_PATH} does not exist")
        published = json.loads(ANCHORS_PATH.read_text(encoding="utf-8"))
        # Role-table semantics are generated from the final merged table. Keeping
        # them out of the manual overlay prevents derived data becoming a second
        # source of truth.
        published_without_semantics = copy.deepcopy(published)
        published_without_semantics.pop("role_table_semantics", None)
        patch = make_merge_patch(hays, published_without_semantics)
        if patch is _NO_CHANGE:
            patch = {}
        OVERRIDES_PATH.write_text(_render(patch), encoding="utf-8")
        reproduced = _published_build()
        if reproduced != published:
            raise RuntimeError("captured overlay does not reproduce the published table")
        print(f"Captured reviewed overlay: {OVERRIDES_PATH.name} ({_describe(published)})")
        return 0

    desired = _published_build(include_overrides=not args.without_overrides)
    rendered = _render(desired)
    existing = ANCHORS_PATH.read_text(encoding="utf-8") if ANCHORS_PATH.exists() else None
    existing_data = json.loads(existing) if existing is not None else None

    if existing_data == desired:
        print(f"Salary anchors are reproducible ({_describe(desired)}).")
        return 0
    if args.check:
        print(
            "Salary anchors are not reproducible from their declared inputs. "
            "Review the published edits, then run --capture-overrides; or rebuild "
            "an intentional guide change with --force.",
            file=sys.stderr,
        )
        return 1
    if existing is not None and not args.force:
        print(
            f"Refusing to overwrite differing {ANCHORS_PATH.name}. "
            "Use --capture-overrides for reviewed manual edits or --force for an "
            "intentional source-guide rebuild.",
            file=sys.stderr,
        )
        return 1

    if existing is not None:
        backup = ANCHORS_PATH.with_suffix(f".json.bak-{datetime.now():%Y%m%d-%H%M%S}")
        shutil.copy2(ANCHORS_PATH, backup)
        print(f"Backup: {backup.name}")
    ANCHORS_PATH.write_text(rendered, encoding="utf-8")
    print(f"Built salary anchors: {_describe(desired)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
