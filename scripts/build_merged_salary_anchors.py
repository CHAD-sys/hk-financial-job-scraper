#!/usr/bin/env python3
"""Build the merged, granular salary anchor table from three recruiter guides.

Sources (all in salary_guidlines/):
  - hk_salary_anchors.json      -> Hays 2026 (monthly, already capped; skews HIGH)
  - persolkelly_2025.json       -> PERSOLKELLY 2025 (annual /12; conservative)
  - adecco_2026.json            -> Adecco 2026 (monthly; mid-market)

Merge rule (agreed 2026-07-21): where sources overlap on a (role, grade) cell,
rank the candidate bands by midpoint ascending (most conservative first) and take
a weighted average with weights 60% / 25% / 15% (renormalised when fewer than
three sources cover the cell). Where only one source covers a cell, use it as-is.
Every output value is capped at HK$200,000/month and rounded to the nearest 500.

Banking roles are standardised onto the Analyst / Associate / VP / Director / MD
grade ladder; insurance roles onto PERSOLKELLY's 4-grade ladder. Hays'
idiosyncratic ladders are sampled at grade fractions to line them up. Roles that
only Hays covers are carried over unchanged.

Output: rewrites tables_monthly_hkd + ladders_monthly_hkd inside
hk_salary_anchors.json (backing up the previous file first). meta and
management_grade_caps_monthly_hkd are preserved/updated.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

GUIDE_DIR = Path(__file__).resolve().parents[1] / "salary_guidlines"
ANCHORS_PATH = GUIDE_DIR / "hk_salary_anchors.json"
GLOBAL_MAX = 200_000
WEIGHTS = [0.60, 0.25, 0.15]  # most conservative -> least, renormalised per cell

hays = json.loads(ANCHORS_PATH.read_text(encoding="utf-8"))
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
    rows = [b for b in ladder.values() if isinstance(b, list)]
    idx = round(frac * (len(rows) - 1))
    return _norm(rows[idx])


def hays_row(tier: str, role: str, label: str):
    band = H.get(tier, {}).get("roles", {}).get(role, {}).get(label)
    return _norm(band) if band else None


def pk_annual(section: str, role: str, key: str):
    band = pk[section].get(role, {}).get(key)
    if not band:
        return None
    lo, hi = _norm(band)
    return round(lo / 12), round(hi / 12)


def adecco_cell(section: str, role: str, title: str):
    band = adecco[section].get(role, {}).get(title)
    return _norm(band) if band else None


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
    return [lo, hi]


def bank_ladder(hays_ref=None, pk_roles=(), adecco_map=None):
    """Build a 5-grade Analyst..MD ladder from any mix of sources.

    hays_ref: (tier, role) sampled at grade fractions.
    pk_roles: list of (section, role) — multiple PK ladders are pre-averaged so
              one source never gets two votes in the weighting.
    adecco_map: {grade_name: (section, role, title)} explicit per-grade cells.
    """
    out = {}
    for grade, frac, pk_key in zip(BANK_GRADES, BANK_FRACS, PK_BANK_KEYS):
        cells = []
        if hays_ref:
            cells.append(hays_at(*hays_ref, frac))
        pk_cells = [pk_annual(sec, role, pk_key) for sec, role in pk_roles]
        pk_cells = [c for c in pk_cells if c]
        if pk_cells:
            cells.append((round(sum(c[0] for c in pk_cells) / len(pk_cells)),
                          round(sum(c[1] for c in pk_cells) / len(pk_cells))))
        if adecco_map and grade in adecco_map:
            cells.append(adecco_cell(*adecco_map[grade]))
        band = merge(cells)
        if band:
            out[grade] = band
    return out


def ins_ladder(hays_ref=None, pk_roles=()):
    """Build a 4-grade insurance ladder (PK labels), same weighting rules."""
    out = {}
    for grade, frac, pk_key in zip(INS_GRADES, INS_FRACS, PK_INS_KEYS):
        cells = []
        if hays_ref:
            cells.append(hays_at(*hays_ref, frac))
        pk_cells = [pk_annual("insurance_annual_hkd", role, pk_key) for role in pk_roles]
        pk_cells = [c for c in pk_cells if c]
        if pk_cells:
            cells.append((round(sum(c[0] for c in pk_cells) / len(pk_cells)),
                          round(sum(c[1] for c in pk_cells) / len(pk_cells))))
        band = merge(cells)
        if band:
            out[grade] = band
    return out


def direct_ladder(section_dict: dict, monthly: bool = True, annual: bool = False):
    """Carry a single-source title-keyed ladder through cap+round unchanged."""
    out = {}
    for title, band in section_dict.items():
        lo, hi = _norm(band)
        if annual:
            lo, hi = round(lo / 12), round(hi / 12)
        band = merge([(lo, hi)])
        out[title] = band
    return out


tables: dict = {}

# ── FRONT OFFICE ────────────────────────────────────────────────────────────────
fo = {"_desc": H["front_office"]["_desc"], "roles": {}}
R = fo["roles"]
R["equity_research"] = bank_ladder(("front_office", "research_strategy_ficc_equity"),
                                   [("banking_financial_services_annual_hkd", "equity_research")])
R["global_markets_trading"] = bank_ladder(("front_office", "global_markets_trading"),
                                          [("banking_financial_services_annual_hkd", "sales_trading")])
R["financial_markets_sales"] = H["front_office"]["roles"]["financial_markets_sales"]
R["corporate_finance_ma_ecm_dcm"] = H["front_office"]["roles"]["corporate_finance_ma_ecm_dcm"]
R["private_equity"] = H["front_office"]["roles"]["private_equity"]
R["hedge_fund_investment"] = H["front_office"]["roles"]["hedge_fund_investment"]
R["asset_management_research"] = bank_ladder(("front_office", "asset_management_research"),
                                             [("banking_financial_services_annual_hkd", "am_research")])
R["asset_management_portfolio"] = bank_ladder(("front_office", "asset_management_fund"),
                                              [("banking_financial_services_annual_hkd", "am_portfolio_management")])
R["asset_management_sales"] = bank_ladder(("front_office", "asset_management_sales"),
                                          [("banking_financial_services_annual_hkd", "am_institutional_distribution_sales")])
R["private_banking_rm"] = bank_ladder(("front_office", "private_banking_rm"),
                                      [("banking_financial_services_annual_hkd", "private_banking_rm")])
R["assistant_private_banker"] = bank_ladder(None, [("banking_financial_services_annual_hkd", "assistant_private_banker")])
R["investment_counsellor"] = H["front_office"]["roles"]["investment_counsellor"]
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
    R[keep] = H["commercial_corporate_banking"]["roles"][keep]
tables["commercial_corporate_banking"] = ccb

# ── RETAIL BANKING (Hays only — carried over) ──────────────────────────────────
tables["retail_banking"] = H["retail_banking"]

# ── MIDDLE OFFICE ──────────────────────────────────────────────────────────────
mo = {"_desc": H["middle_office"]["_desc"] + " Includes legal, company secretarial, "
      "IT leadership/governance and cybersecurity at financial firms.", "roles": {}}
R = mo["roles"]
R["risk_credit"] = H["middle_office"]["roles"]["risk_credit"]
R["risk_market"] = H["middle_office"]["roles"]["risk_market"]
R["risk_management_general"] = bank_ladder(("middle_office", "risk_ops_enterprise"),
                                           [("banking_financial_services_annual_hkd", "risk_management")])
R["risk_climate_modeling_validation"] = H["middle_office"]["roles"]["risk_climate_modeling_validation"]
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
R["trade_support"] = H["middle_office"]["roles"]["trade_support"]
R["product_management"] = H["middle_office"]["roles"]["product_management"]
R["change_project_management"] = bank_ladder(("middle_office", "change_project_management"),
                                             [("banking_financial_services_annual_hkd", "project_management_banking")])
R["performance_investment_risk"] = H["middle_office"]["roles"]["performance_investment_risk"]
R["forensic_accounting"] = bank_ladder(None, [("banking_financial_services_annual_hkd", "forensic_accounting")])
R["legal_counsel"] = bank_ladder(None, [("banking_financial_services_annual_hkd", "legal_counsel_banking")],
                                 {"Analyst": ("legal_compliance_monthly_hkd", "legal_inhouse", "associate_legal_counsel"),
                                  "Associate": ("legal_compliance_monthly_hkd", "legal_inhouse", "legal_counsel"),
                                  "VP": ("legal_compliance_monthly_hkd", "legal_inhouse", "senior_legal_counsel"),
                                  "Director": ("legal_compliance_monthly_hkd", "legal_inhouse", "head_of_legal_general_counsel")})
R["company_secretarial"] = direct_ladder(adecco["legal_compliance_monthly_hkd"]["company_secretarial"])
R["compliance_corporate_inhouse"] = direct_ladder(adecco["legal_compliance_monthly_hkd"]["compliance_inhouse"])
R["it_executive_leadership"] = direct_ladder(adecco["information_technology_monthly_hkd"]["it_executive_leadership"])
R["it_management"] = direct_ladder(adecco["information_technology_monthly_hkd"]["it_management"])
R["it_governance_risk_compliance"] = direct_ladder(adecco["information_technology_monthly_hkd"]["it_governance_risk_compliance"])
R["cybersecurity"] = direct_ladder(adecco["information_technology_monthly_hkd"]["cybersecurity"])
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
R["collateral_management"] = H["back_office_operations"]["roles"]["collateral_management"]
R["loans_operation"] = bank_ladder(None, [("banking_financial_services_annual_hkd", "loans_operation")])
R["trade_services"] = bank_ladder(None, [("banking_financial_services_annual_hkd", "trade_services")])
R["documentation_operations"] = bank_ladder(None, [("banking_financial_services_annual_hkd", "operations_documentation")])
R["client_services_am"] = bank_ladder(None, [("banking_financial_services_annual_hkd", "am_client_services")])
R["rfp_proposals"] = bank_ladder(None, [("banking_financial_services_annual_hkd", "am_rfp")])
R["human_resources"] = direct_ladder(adecco["corporate_support_monthly_hkd"]["human_resources"])
R["secretarial_admin"] = direct_ladder({**adecco["corporate_support_monthly_hkd"]["administrative"],
                                        **adecco["corporate_support_monthly_hkd"]["secretarial"]})
R["customer_service"] = direct_ladder(adecco["customer_service_monthly_hkd"]["customer_service"])
R["marketing_communications"] = direct_ladder({**adecco["marketing_monthly_hkd"]["marketing"],
                                               **adecco["marketing_monthly_hkd"]["public_relations"]})
R["ecommerce_digital"] = direct_ladder(adecco["marketing_monthly_hkd"]["ecommerce_digital"])
R["software_data_engineering"] = direct_ladder(adecco["information_technology_monthly_hkd"]["software_data_engineering"])
R["it_infrastructure_support"] = direct_ladder(adecco["information_technology_monthly_hkd"]["it_infrastructure_support"])
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
R["tax"] = H["corporate_finance_accounting"]["roles"]["tax"]
R["shared_service_centre"] = H["corporate_finance_accounting"]["roles"]["shared_service_centre"]
R["accounting_support"] = H["corporate_finance_accounting"]["roles"]["accounting_support"]
R["professional_practice_advisory"] = H["corporate_finance_accounting"]["roles"]["professional_practice_advisory"]

# corporate accounting/finance: explicit 3-source row mapping
_pkc = "corporate_professionals_finance_annual_hkd"
_adf = "accounting_finance_monthly_hkd"
corp_rows = {
    "Accounts Clerk": [adecco_cell(_adf, "accounting", "account_clerk_assistant"),
                       pk_annual(_pkc, "financial_accounting_corporate", "accounts_clerk")],
    "Assistant Accountant": [adecco_cell(_adf, "accounting", "assistant_accountant"),
                             pk_annual(_pkc, "financial_accounting_corporate", "assistant_accountant"),
                             hays_row("corporate_finance_accounting", "in_house_finance_ci", "Senior Accountant")],
    "Accountant / Financial Analyst": [adecco_cell(_adf, "finance", "financial_analyst"),
                                       hays_row("corporate_finance_accounting", "in_house_finance_ci", "Financial Analyst")],
    "Finance Manager": [adecco_cell(_adf, "finance", "finance_manager"),
                        pk_annual(_pkc, "financial_accounting_corporate", "finance_manager"),
                        hays_row("corporate_finance_accounting", "in_house_finance_ci", "FP&A Manager")],
    "Senior Finance Manager / Controller": [pk_annual(_pkc, "financial_accounting_corporate", "controller"),
                                            adecco_cell(_adf, "finance", "financial_controller"),
                                            hays_row("corporate_finance_accounting", "in_house_finance_ci", "Financial Controller")],
    "Finance Director": [adecco_cell(_adf, "finance", "finance_director"),
                         pk_annual(_pkc, "financial_accounting_corporate", "director_department_head"),
                         hays_row("corporate_finance_accounting", "in_house_finance_ci", "FP&A Director")],
    "CFO": [adecco_cell(_adf, "finance", "cfo"),
            pk_annual(_pkc, "financial_accounting_corporate", "cfo"),
            hays_row("corporate_finance_accounting", "in_house_finance_ci", "Finance Director / CFO")],
}
R["corporate_accounting_finance"] = {label: merge(cells) for label, cells in corp_rows.items()}

audit_corp_rows = {
    "Internal Auditor": [adecco_cell(_adf, "audit", "senior_auditor"),
                         pk_annual(_pkc, "audit_internal_control_corporate", "internal_auditor")],
    "Audit Manager": [adecco_cell(_adf, "audit", "audit_manager"),
                      pk_annual(_pkc, "audit_internal_control_corporate", "internal_audit_manager")],
    "Head of Audit": [adecco_cell(_adf, "audit", "head_of_audit"),
                      pk_annual(_pkc, "audit_internal_control_corporate", "head_of_audit")],
}
R["audit_internal_control_corporate"] = {label: merge(cells) for label, cells in audit_corp_rows.items()}
R["fpa_corporate"] = direct_ladder(pk[_pkc]["fpa_corporate"], annual=True)
tables["corporate_finance_accounting"] = cfa

# ── INSURANCE ──────────────────────────────────────────────────────────────────
ins = {"_desc": H["insurance"]["_desc"], "roles": {}}
R = ins["roles"]
R["actuarial"] = ins_ladder(("insurance", "actuarial"),
                            ["actuarial_bancassurance", "actuarial_agency", "actuarial_brokerage"])
R["actuarial_pricing"] = H["insurance"]["roles"]["actuarial_pricing"]
R["investment"] = H["insurance"]["roles"]["investment"]
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
R["strategic_operations"] = H["insurance"]["roles"]["strategic_operations"]
R["product_development"] = H["insurance"]["roles"]["product_development"]
R["pension_operations"] = H["insurance"]["roles"]["pension_operations"]
tables["insurance"] = ins

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

# ── write output ───────────────────────────────────────────────────────────────
backup = ANCHORS_PATH.with_suffix(f".json.bak-{datetime.now():%Y%m%d-%H%M%S}")
shutil.copy2(ANCHORS_PATH, backup)

hays["meta"]["source"] = (
    "Merged 2026-07-21: Hays Asia Salary Guide 2026 (HK) + PERSOLKELLY Salary Guide 2025 (HK) "
    "+ Adecco Hong Kong Salary Guide 2026. Weighted average where sources overlap: 60% most "
    "conservative / 25% middle / 15% highest (by band midpoint). Monthly BASE HKD."
)
hays["meta"]["merge_script"] = "scripts/build_merged_salary_anchors.py (rerun after editing source JSONs)"
hays["meta"]["grade_ladder_note"] = (
    "Banking roles use Analyst/Associate/VP/Director/MD rows (PERSOLKELLY year bands: 0-3/3-7/"
    "7-10/10+/15+). Insurance roles use Officer-Senior Analyst / AsstMgr-Manager / SrMgr-SrDirector "
    "/ Head. Roles only covered by one source carry that source's own row labels."
)
hays["tables_monthly_hkd"] = tables
hays["ladders_monthly_hkd"] = ladders

ANCHORS_PATH.write_text(json.dumps(hays, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

n_roles = sum(len(t["roles"]) for t in tables.values())
n_rows = sum(len(l) for t in tables.values() for l in t["roles"].values())
print(f"Backup: {backup.name}")
print(f"Merged table: {len(tables)} tiers, {n_roles} roles, {n_rows} salary rows")
for tier, t in tables.items():
    print(f"  {tier}: {len(t['roles'])} roles")
