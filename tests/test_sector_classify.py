"""
Specification for deterministic sector classification.

The bug this exists to catch: a Private Banking / Wealth Management posting
at a bulge-bracket bank (UBS, JPMorgan Chase, Morgan Stanley, ...) used to be
stamped sector="Investment Banking" purely because of who was hiring — the
old classifier only ever looked at the employer's name. Every test title
below is a REAL posting title pulled from data/jobs.db while diagnosing the
bug, not an invented example.
"""

from __future__ import annotations

from hk_jobs.sector_classify import (
    BANKING_FALLBACK,
    classify_sector,
    sector_case_sql,
    sector_condition_sql,
)


def test_private_banking_title_wins_over_investment_bank_employer():
    # This is the exact misclassification reported: clicking "Investment
    # Banking" surfaced Private Banking roles, because the old classifier
    # only ever read the company name.
    assert classify_sector("Investment Consultant – Private Banking", "UBS Asset Management HK") == "Private Banking"
    assert classify_sector("International Private Bank, Wealth Advisory, Associate", "JPMorgan Chase") == "Private Banking"
    assert classify_sector("Wealth Management KYC Associate", "JPMorgan Chase") == "Private Banking"


def test_generic_title_at_an_investment_bank_still_falls_back_to_the_employer():
    # A title with no sector signal of its own should still resolve via the
    # company-name fallback, exactly as before.
    assert classify_sector("Analyst", "Goldman Sachs") == "Investment Banking"
    assert classify_sector("Associate, Equities", "Morgan Stanley") == "Investment Banking"


def test_private_banking_title_wins_regardless_of_employer():
    # Title rules are checked before ANY company rule, not just the
    # investment-banking one — a private-banking title at an insurer's
    # employer should not fall into Insurance either.
    assert classify_sector("Private Banking Relationship Manager", "AIA") == "Private Banking"


def test_company_only_rules_are_unchanged():
    assert classify_sector("Actuarial Analyst", "AIA") == "Insurance"
    assert classify_sector("Portfolio Manager", "BlackRock") == "Asset Management"
    assert classify_sector("Auditor", "KPMG") == "Professional Services"
    assert classify_sector("Auditor", "EY") == "Professional Services"
    # "ey" must be an exact company match, not a substring — a "%ey%" LIKE
    # would wrongly match names containing "money", "survey", "key", etc.
    assert classify_sector("Analyst", "Money Matters Ltd") != "Professional Services"
    assert classify_sector("Blockchain Engineer", "HashKey") == "Digital Assets"


def test_no_match_falls_back_to_banking():
    assert classify_sector("Credit Risk Analyst", "HSBC") == BANKING_FALLBACK
    assert classify_sector(None, None) == BANKING_FALLBACK


def test_sql_case_expression_agrees_with_python_for_every_rule():
    import sqlite3

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE j (title TEXT, company TEXT)")
    rows = [
        ("Investment Consultant – Private Banking", "UBS Asset Management HK"),
        ("International Private Bank, Wealth Advisory, Associate", "JPMorgan Chase"),
        ("Analyst", "Goldman Sachs"),
        ("Actuarial Analyst", "AIA"),
        ("Portfolio Manager", "BlackRock"),
        ("Auditor", "EY"),
        ("Blockchain Engineer", "HashKey"),
        ("Credit Risk Analyst", "HSBC"),
    ]
    conn.executemany("INSERT INTO j VALUES (?, ?)", rows)

    case_sql = sector_case_sql("j.title", "j.company")
    got = conn.execute(f"SELECT title, company, ({case_sql}) FROM j").fetchall()
    for title, company, sql_sector in got:
        assert sql_sector == classify_sector(title, company), (title, company)


def test_sector_condition_sql_selects_only_its_own_sector():
    import sqlite3

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE j (title TEXT, company TEXT)")
    conn.executemany(
        "INSERT INTO j VALUES (?, ?)",
        [
            ("Investment Consultant – Private Banking", "UBS Asset Management HK"),
            ("Analyst", "Goldman Sachs"),
            ("Credit Risk Analyst", "HSBC"),
        ],
    )

    cond = sector_condition_sql("Private Banking", "j.title", "j.company")
    rows = conn.execute(f"SELECT title FROM j WHERE {cond}").fetchall()
    assert [r[0] for r in rows] == ["Investment Consultant – Private Banking"]

    banking_cond = sector_condition_sql(BANKING_FALLBACK, "j.title", "j.company")
    rows = conn.execute(f"SELECT title FROM j WHERE {banking_cond}").fetchall()
    assert [r[0] for r in rows] == ["Credit Risk Analyst"]
