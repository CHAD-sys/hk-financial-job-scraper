from __future__ import annotations

from hk_jobs.salary_context import (
    _DEFAULT_CANDIDATE_LIMIT,
    build_salary_context,
)


def _coordinates(context):
    return {(candidate.tier, candidate.role) for candidate in context.candidates}


def test_product_manager_gets_a_short_valid_product_candidate_set():
    context = build_salary_context(
        title="Senior Product Manager, Wealth and Investments",
        description="Own the wealth product roadmap and investment proposition.",
        company_slug="dbs-hk",
    )

    assert ("middle_office", "product_management") in _coordinates(context)
    assert len(context.candidates) <= _DEFAULT_CANDIDATE_LIMIT
    assert "dbs_sized_banks" in context.cohorts
    product = next(candidate for candidate in context.candidates if candidate.role == "product_management")
    assert "Senior Manager" in product.grades


def test_unknown_title_is_an_explicit_review_fallback_not_a_fake_coordinate():
    context = build_salary_context(title="Office Happiness Champion")

    assert context.requires_review
    assert "Return null" in context.render()


def test_context_never_returns_a_coordinate_outside_the_published_table():
    context = build_salary_context(
        title="Vice President, Global Markets Sales",
        description="Cross-border institutional markets sales coverage.",
        company_slug="icbc-asia",
    )

    assert ("front_office", "financial_markets_sales") in _coordinates(context)
    for candidate in context.candidates:
        assert candidate.grades


def test_common_chinese_product_title_gets_a_valid_candidate_without_translation():
    context = build_salary_context(title="贸易融资产品经理 - 公司银行市场规划部")

    assert ("middle_office", "product_management") in _coordinates(context)
