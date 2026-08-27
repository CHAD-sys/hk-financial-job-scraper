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
_GENERIC = frozenset({
    "and", "banking", "business", "corporate", "finance", "financial", "for",
    "general", "insurance", "management", "market", "markets", "of", "office",
    "operations", "services", "support", "the", "to",
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
    "commercial_banking_rm": ("relationship manager", "commercial banking", "客户经理", "客戶經理"),
    "sme_banking_rm": ("relationship manager", "sme banking"),
    "relationship_management": ("relationship manager", "retail relationship"),
    "financial_markets_sales": ("global markets sales", "markets sales", "sales trading"),
    "risk_credit": ("credit risk", "counterparty risk", "credit approval", "信用风险", "信用風險"),
    "risk_market": ("market risk", "var", "value at risk", "市场风险", "市場風險"),
    "risk_operational": ("operational risk", "non-financial risk"),
    "compliance_banking": ("compliance", "aml", "financial crime", "sanctions"),
    "audit_banking": ("internal audit", "audit"),
    "underwriting": ("underwriter", "underwriting"),
    "claims": ("claims", "claim handling"),
    "actuarial": ("actuar", "pricing actuary"),
    "strategic_operations": ("transformation", "pmo", "strategy", "operating model"),
    "professional_practice_advisory": ("advisory", "consulting", "forensics", "transaction services"),
    "corporate_finance_ma_ecm_dcm": ("m&a", "mergers", "acquisitions", "ecm", "dcm"),
    "global_markets_trading": ("trader", "trading", "rates", "fx", "equities"),
    "trade_support": ("trade support", "middle office"),
    "payment_operation": ("payment operations", "payments", "remittance", "支付", "付款", "汇款", "匯款"),
    "fund_operations": ("fund operations", "fund administration"),
    "human_resources": ("human resources", "people", "talent acquisition"),
    "software_data_engineering": ("software engineer", "data engineer", "developer"),
}


def _tokens(value: str) -> frozenset[str]:
    return frozenset(_TOKEN.findall(value.lower()))


def _role_terms(role: str) -> tuple[str, ...]:
    explicit = _ROLE_TERMS.get(role, ())
    key_terms = tuple(token for token in role.split("_") if token not in _GENERIC)
    return explicit + key_terms


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
                "No safe anchor candidates were found. Return null for salary_tier, "
                "salary_role, salary_grade, salary_estimated_min and salary_estimated_max."
            )
        return "\n".join((
            f"Employer cohorts: {employer}.",
            "Choose exactly one coordinate below only when the posting clearly fits it; "
            "otherwise return null coordinate and null estimate:",
            *(candidate.render() for candidate in self.candidates),
        ))


def build_salary_context(
    *,
    title: str,
    description: str = "",
    company_slug: str | None = None,
    limit: int = 8,
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
            terms = _role_terms(role)
            phrase_hits = sum(
                1
                for term in terms
                if (" " in term or any(ord(character) > 127 for character in term))
                and (term in title_text or term in description_text)
            )
            token_terms = frozenset(token for term in terms for token in _tokens(term) if token not in _GENERIC)
            title_hits = len(token_terms & title_tokens)
            description_hits = len(token_terms & description_tokens)
            score = phrase_hits * 12 + title_hits * 3 + description_hits
            if not phrase_hits and title_hits + description_hits < 2:
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
