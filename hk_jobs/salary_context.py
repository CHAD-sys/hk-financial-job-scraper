"""Deterministic context and a short coordinate candidate set for salary classification.

The salary table is a reusable market grid, not a prompt-sized catalogue.  This
module turns one posting into the small, auditable part of that grid that could
plausibly apply.  The LLM then chooses *only* a role/grade coordinate from that
set; it never prices a job from a 700-cell menu.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from hk_jobs import employer_segments, salary_anchors


_TOKEN = re.compile(r"[a-z0-9+#]+")
#: Words that carry no FUNCTION signal, so a role key made only of these has no
#: identity of its own. Two groups:
#:   * sector/filler nouns that appear in most finance boilerplate;
#:   * GRADE words (docs/adr/0037) — "Assistant Compliance Manager" was ranking
#:     `assistant_private_banker` above every compliance role, because
#:     "assistant" is a strong token of that role key and matched the title.
#:     A grade word says how senior a job is, never what it does.
#: These are not discarded: `_role_vocabulary` keeps them as WEAK tokens, scored
#: against the title only.
_GENERIC = frozenset({
    "and", "banking", "business", "corporate", "finance", "financial", "for",
    "general", "insurance", "management", "market", "markets", "of", "office",
    "operations", "services", "support", "the", "to",
    # grade / seniority words
    "assistant", "associate", "analyst", "deputy", "director", "executive",
    "head", "junior", "lead", "manager", "officer", "president", "senior",
    "specialist", "vice",
})

# The frequent/ambiguous financial functions get explicit vocabulary.  Every
# remaining row is still discoverable from its role key below; this is a boost,
# not a second hidden taxonomy.
_ROLE_TERMS: dict[str, tuple[str, ...]] = {
    "product_management": (
        "product manager", "product owner", "product management", "产品经理", "產品經理",
    ),
    "private_banking_rm": (
        "private banking", "wealth management", "relationship manager", "私人财富", "私人財富",
        "财富管理", "財富管理",
    ),
    "commercial_banking_rm": (
        "relationship manager", "commercial banking", "客户经理", "客戶經理",
    ),
    "sme_banking_rm": ("relationship manager", "sme banking"),
    "relationship_management": (
        "relationship manager", "retail relationship", "personal banking",
        "premier banking", "priority banking", "personal financial services",
    ),
    "financial_markets_sales": (
        "global markets sales", "markets sales", "sales trading",
        "structured products sales", "fx sales", "rates sales",
    ),
    "risk_credit": ("credit risk", "counterparty risk", "credit approval", "信用风险", "信用風險"),
    "risk_market": ("market risk", "var", "value at risk", "市场风险", "市場風險"),
    "risk_operational": ("operational risk", "non-financial risk", "operations risk"),
    "compliance_banking": ("compliance", "aml", "financial crime", "sanctions"),
    "audit_banking": ("internal audit", "audit"),
    "underwriting": ("underwriter", "underwriting", "核保"),
    "claims": ("claims", "claim handling"),
    "actuarial": ("actuar", "pricing actuary"),
    "strategic_operations": ("transformation", "pmo", "strategy", "operating model"),
    "professional_practice_advisory": (
        "advisory", "consulting", "forensics", "transaction services",
    ),
    "corporate_finance_ma_ecm_dcm": (
        "m&a", "mergers", "acquisitions", "ecm", "dcm", "investment banking",
        "financial sponsors", "origination", "capital markets",
    ),
    "global_markets_trading": (
        "trader", "trading", "rates", "fx", "equities",
        # A structured-products desk at UOB was offered back_office/human_resources
        # as its ONLY candidate (docs/adr/0037 follow-up): "dealer" and
        # "structured products" are what a HK trading-desk advert actually says.
        "dealer", "structured products", "structuring", "market making",
        "flow trading", "derivatives trading", "交易員", "交易员",
    ),
    "trade_support": ("trade support", "middle office"),
    "payment_operation": ("payment operations", "payments", "remittance", "支付", "付款", "汇款", "匯款"),
    "fund_operations": ("fund operations", "fund administration"),
    "human_resources": ("human resources", "people", "talent acquisition"),
    "software_data_engineering": ("software engineer", "data engineer", "developer"),
    # ── docs/adr/0037 ───────────────────────────────────────────────────────
    # 81 of the 105 published roles had NO vocabulary here and were reachable
    # only if their own key's tokens happened to appear in the posting. Since
    # `_GENERIC` strips "operations", "management", "finance", "banking",
    # "insurance", "corporate", "business", "services" and "general", several
    # keys reduced to nothing at all and could never be offered — including
    # `operations_general`, the catch-all for the board's single largest
    # unpriced family (103 Roles). The entries below are the highest-volume
    # gaps measured against the 2026-09-02 board; every one is a term a HK
    # posting for that role actually uses.
    "operations_general": (
        "back office", "processing officer", "operations officer", "operations support",
        "processing", "營運", "运营", "處理", "处理",
    ),
    "fcc_aml": (
        "financial crime", "transaction monitoring", "sanctions screening",
        "anti-money laundering", "aml", "fraud",
    ),
    "kyc_cdd_client_onboarding": (
        "kyc", "cdd", "client onboarding", "customer due diligence", "due diligence",
        "client lifecycle", "account opening", "account maintenance",
    ),
    "documentation_operations": (
        "documentation", "doc services", "post acceptance", "loan documentation",
    ),
    "exchange_clearing_operations": ("settlement", "clearing", "post trade", "結算", "结算"),
    "loans_operation": ("loan operations", "credit administration", "loan admin"),
    "trade_services": ("trade finance", "trade services", "letters of credit", "貿易融資"),
    "fund_accounting": ("fund accounting", "net asset value", "nav"),
    "fpa_corporate": (
        "fp&a", "financial planning", "budgeting", "forecasting", "cost management",
        "financial budgeting",
    ),
    "management_reporting": ("management reporting", "financial reporting"),
    "regulatory_reporting": ("regulatory reporting", "prudential reporting"),
    "product_control": ("product control", "valuation control"),
    "treasury": ("treasury", "asset liability", "alm", "liquidity"),
    "tax": ("tax", "transfer pricing", "稅務", "税务"),
    "corporate_accounting_finance": ("accounting", "general ledger", "會計", "会计"),
    "accounting_support": ("accounts payable", "accounts receivable", "bookkeeping"),
    "secretarial_admin": (
        "administrative assistant", "administration assistant", "receptionist",
        "secretary", "clerk", "行政", "文員",
    ),
    "customer_service": (
        "customer service", "client service", "call centre", "call center",
        "contact centre", "counter service", "客戶服務", "客户服务",
    ),
    "it_infrastructure_support": (
        "infrastructure", "helpdesk", "help desk", "system administrator",
        "database administrator", "network", "desktop support",
        # "Senior Load Balancer Engineer" tied this at score 3 with
        # corporate_finance_ma_ecm_dcm and private_banking_rm.
        "load balancer", "network engineer", "systems engineer", "middleware",
        "site reliability", "sre", "platform engineer",
    ),
    "cybersecurity": (
        "cyber security", "cybersecurity", "information security",
        "penetration testing", "red team", "security operations",
    ),
    "it_management": ("it manager", "technology manager", "head of technology"),
    "change_project_management": (
        "project manager", "programme manager", "program manager", "pmo",
        "business analyst", "change management", "scrum",
    ),
    "strategy_business_consulting": ("consultant", "strategy", "advisory", "transformation"),
    "marketing_communications": (
        "marketing", "communications", "brand", "digital marketing", "content",
    ),
    "branch_management": ("branch manager", "branch head", "分行"),
    "policy_administration": ("policy administration", "policy servicing", "保單"),
    "pension_operations": ("mpf", "pension", "retirement scheme", "強積金", "强积金"),
    "insurance_customer_service": ("policy holder service", "insurance customer service"),
    "agency_distribution": (
        "agency", "financial planner", "insurance agent", "financial consultant",
    ),
    "legal_counsel": ("legal counsel", "company secretary", "法律"),
    "corporate_banking_rm": ("corporate banking", "corporate relationship"),
    "audit_internal_control_corporate": ("internal control", "assurance", "internal audit"),
}

# Where each kind of evidence is worth what. Title evidence dominates, and a
# phrase found only in the DESCRIPTION is worth far less than one in the title
# — that inversion is what let a single boilerplate "wealth management" in an
# employer blurb rank `private_banking_rm` (12) above `compliance_banking` (5)
# on a job whose title says "Compliance Manager". See docs/adr/0037.
_TITLE_PHRASE = 12
_DESCRIPTION_PHRASE = 3
_TITLE_STRONG_TOKEN = 6
_DESCRIPTION_STRONG_TOKEN = 1
#: A token from the role key that `_GENERIC` would otherwise discard, counted
#: ONLY against the title. It is weak evidence in a description ("operations"
#: appears in half of all finance boilerplate) but real evidence in a title
#: ("Operations Officer"). This is what makes `operations_general` reachable.
_TITLE_WEAK_TOKEN = 2
#: 5. It went 8 -> 12 while retrieval was still mis-ranking and the right role
#: could sit 9th. With scoring fixed the chosen role lands in the top three 77%
#: of the time and beyond 12 only 3 times in 431, so the extra rows are noise a
#: declining classifier has to wade through. A Sonnet-5 benchmark over 54 Roles
#: never used a candidate below rank 3. Fewer, better options also cut the one
#: part of the prompt that is NOT prefix-cached (the per-job block).
_DEFAULT_CANDIDATE_LIMIT = 5

#: One strong description token alone is not enough; two are — the same bar the
#: original `title_hits + description_hits < 2` gate set.
_MIN_SCORE = 2


def _tokens(value: str) -> frozenset[str]:
    return frozenset(_TOKEN.findall(value.lower()))


def _is_phrase(term: str) -> bool:
    """A multi-word or CJK term — specific enough to be strong evidence."""
    return " " in term or any(ord(character) > 127 for character in term)


def _role_terms(role: str) -> tuple[str, ...]:
    explicit = _ROLE_TERMS.get(role, ())
    key_terms = tuple(token for token in role.split("_") if token not in _GENERIC)
    return explicit + key_terms


def _role_vocabulary(role: str) -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
    """(phrases, strong tokens, weak tokens) for one role key.

    Weak tokens are the parts of the role key `_GENERIC` filters out. They are
    kept — and scored, but only against the title — instead of discarded,
    because for a handful of keys they are the entire identity:
    `operations_general` and `insurance_finance_operations` reduce to nothing
    once "operations", "general", "insurance" and "finance" are removed, so
    before docs/adr/0037 neither could ever be offered to the model at all.
    """
    explicit = _ROLE_TERMS.get(role, ())
    phrases = frozenset(term for term in explicit if _is_phrase(term))
    strong = frozenset(term for term in explicit if not _is_phrase(term))
    key_tokens = frozenset(role.split("_"))
    strong |= {token for token in key_tokens if token not in _GENERIC}
    weak = {token for token in key_tokens if token in _GENERIC} - strong
    return phrases, strong, frozenset(weak)


@dataclass(frozen=True)
class SalaryCandidate:
    tier: str
    role: str
    grades: tuple[str, ...]
    score: int

    def render(self) -> str:
        return f"- {self.tier} / {self.role}: " + " | ".join(self.grades)


@dataclass(frozen=True)
class SalaryContext:
    company_slug: str | None
    cohorts: tuple[str, ...]
    candidates: tuple[SalaryCandidate, ...]

    @property
    def requires_review(self) -> bool:
        return not self.candidates

    def render(self) -> str:
        employer = ", ".join(self.cohorts) if self.cohorts else "no reviewed cohort"
        if not self.candidates:
            return (
                f"Employer cohorts: {employer}.\n"
                "No anchor candidates matched this posting. Return null for salary_tier, "
                "salary_role, salary_grade, salary_estimated_min and salary_estimated_max."
            )
        return "\n".join((
            f"Employer cohorts: {employer}.",
            "Pick the ONE coordinate below that best fits this posting. These are "
            "ranked by how well they already match, so the first is usually right. "
            "Return null ONLY if nothing below is even plausibly related to the job:",
            *(candidate.render() for candidate in self.candidates),
        ))


def build_salary_context(
    *,
    title: str,
    description: str = "",
    company_slug: str | None = None,
    limit: int = _DEFAULT_CANDIDATE_LIMIT,
) -> SalaryContext:
    """Return the highest-signal valid role/grade coordinates for one posting.

    Title evidence counts three times description evidence.  A candidate needs a
    role-specific phrase or at least two meaningful role-key tokens, so unrelated
    jobs do not get a false, broad salary guess merely because they mention
    "finance" or "operations" in boilerplate.
    """
    title_text = title.lower()
    description_text = description.lower()
    title_tokens = _tokens(title)
    description_tokens = _tokens(description)
    candidates: list[SalaryCandidate] = []

    for tier, table in salary_anchors.TABLES.items():
        for role, ladder in (table.get("roles") or {}).items():
            phrases, strong, weak = _role_vocabulary(role)
            score = (
                sum(_TITLE_PHRASE for term in phrases if term in title_text)
                + sum(
                    _DESCRIPTION_PHRASE
                    for term in phrases
                    if term not in title_text and term in description_text
                )
                + len(strong & title_tokens) * _TITLE_STRONG_TOKEN
                + len((strong & description_tokens) - title_tokens)
                * _DESCRIPTION_STRONG_TOKEN
                + len(weak & title_tokens) * _TITLE_WEAK_TOKEN
            )
            if score < _MIN_SCORE:
                continue
            grades = tuple(
                grade for grade, band in ladder.items()
                if isinstance(band, list) and len(band) == 2 and all(isinstance(value, int) for value in band)
            )
            if grades:
                candidates.append(SalaryCandidate(tier, role, grades, score))

    candidates.sort(key=lambda candidate: (-candidate.score, candidate.tier, candidate.role))
    return SalaryContext(
        company_slug=company_slug,
        cohorts=tuple(sorted(employer_segments.cohorts_for(company_slug))),
        candidates=tuple(candidates[:limit]),
    )
