"""The MT discovery gate intentionally favours precision over recall."""

import pytest

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


# ── The watchlist parse must not fail quietly ────────────────────────────────
#
# Every gate in classify_mt_role is "company must be on the watchlist", so a
# regex that stops matching does not raise — it rejects every Role in turn and
# the MT feed goes dark, indistinguishable from a quiet week. The file is
# TypeScript parsed by regex and already holds two different shapes, so a
# reformat is a live possibility rather than a hypothetical.

def test_the_real_workbook_still_parses(monkeypatch):
    """A tripwire on the checked-in file: if a reformat breaks the regexes, this
    fails in CI rather than in production as an empty feed."""
    from hk_jobs import mt_classifier

    mt_classifier.watchlist_company_aliases.cache_clear()
    aliases = mt_classifier.watchlist_company_aliases()

    assert len(set(aliases.values())) >= mt_classifier.MIN_WATCHLIST_COMPANIES
    # Employers the directory is built around; if these stop resolving, the
    # parse is wrong even when the count still looks healthy.
    for known in ("the hong kong jockey club", "hong kong monetary authority"):
        assert known in aliases, f"{known!r} no longer resolves from the workbook"


def test_a_reformatted_workbook_raises_instead_of_emptying_the_feed(tmp_path, monkeypatch):
    """RED before MIN_WATCHLIST_COMPANIES: double-quoting the file (what a
    Prettier config change would do) matched nothing, `watchlist_company_aliases`
    returned {}, and every MT Role was then rejected as "not on the supplied MT
    watchlist" — silently, with a 200 and an empty list."""
    from hk_jobs import mt_classifier

    reformatted = tmp_path / "managementTraineePrograms.ts"
    reformatted.write_text(
        'export const MT_PROGRAMMES = [\n'
        '  ["The Hong Kong Jockey Club", "香港賽馬會"],\n'
        '  ["Hong Kong Monetary Authority", "香港金融管理局"],\n'
        ']\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(mt_classifier, "PROGRAMMES_FILE", reformatted)
    mt_classifier.watchlist_company_aliases.cache_clear()

    with pytest.raises(RuntimeError, match="format has almost certainly changed"):
        mt_classifier.watchlist_company_aliases()

    mt_classifier.watchlist_company_aliases.cache_clear()
