"""The MT discovery gate intentionally favours precision over recall."""

from hk_jobs.mt_classifier import classify_mt_role


def test_watchlist_company_and_explicit_mt_title_are_required():
    result = classify_mt_role("Hang Seng Bank", "2027 Management Trainee Programme")

    assert result.is_mt is True
    assert result.watchlist_company == "Hang Seng Bank"


def test_known_company_aliases_are_exact_not_fuzzy():
    result = classify_mt_role("Bank Of China (Hong Kong) Limited", "Wealth Management Trainee Programme")

    assert result.is_mt is True
    assert result.watchlist_company == "Bank of China (Hong Kong) [BOCHK]"


def test_ambiguous_and_non_watchlist_roles_are_rejected():
    assert classify_mt_role("Hang Seng Bank", "Early Careers Programme").is_mt is False
    assert classify_mt_role("Hang Seng Bank", "Management Trainee Internship").is_mt is False
    assert classify_mt_role("KPMG", "Audit Graduate Programme").is_mt is False
    assert classify_mt_role("EY", "Graduate Analyst Programme").is_mt is False
    assert classify_mt_role("HKTV", "Management Trainee & Graduate Trainee Programme").is_mt is False
    assert classify_mt_role("Unlisted Bank", "Management Trainee Programme").is_mt is False
    assert classify_mt_role("KPMG", "KPMG 2026-27 Audit Graduate Programme - Macau").is_mt is False
