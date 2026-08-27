"""
Specification for the full-text search index.

These state what searching the board SHOULD do. Every one of them fails against
the `LIKE '%q%'` on title-and-company that came before, and each names the
defect it catches:

  - a query only the DESCRIPTION or the SKILLS answer finds nothing, because
    neither column was searched. On the live board "python" matched 3 Roles of
    the 306 that actually ask for it;
  - a query whose words are all present but not ADJACENT finds nothing, because
    `%risk management%` is a contiguous substring, not two terms. "senior risk
    management analyst" returned zero against a board holding exactly that Role;
  - a word is matched inside a longer word, so searching the VP level also
    returns every AVP and FVP posting;
  - a Chinese-titled Role is unreachable by its English name, though enrichment
    has stored that name in `title_en` all along.

The index is a table, so these talk to it through a plain `sqlite3.Connection`,
the same seam `test_job_read.py` uses. No app, no TestClient.
"""

from __future__ import annotations

import sqlite3

import pytest

from hk_jobs.search_index import match_reason, matching_rowids, rebuild_search_index

from .support import enrichment, job, make_jobs_db


@pytest.fixture()
def conn(tmp_path) -> sqlite3.Connection:
    db = tmp_path / "jobs.db"
    make_jobs_db(
        db,
        jobs=[
            # Its skills carry Python; its title does not say so. The recall bug.
            job(source="workday", source_id="QUANT", company="HSBC",
                title="Quantitative Developer",
                description_clean="Build pricing models for the rates desk."),
            # The words are there, in that order, but not adjacent.
            job(source="workday", source_id="SRRMA", company="HSBC",
                title="Senior Risk Management Analyst",
                description_clean="Second line of defence."),
            # VP and AVP are different jobs. A substring match cannot tell them apart.
            job(source="jobsdb", source_id="VP", company="DBS",
                title="VP, Credit Risk"),
            job(source="jobsdb", source_id="AVP", company="DBS",
                title="AVP, Credit Risk"),
            # Chinese title; the English name lives only in enrichment.title_en.
            job(source="jobsdb", source_id="CN", company="Hang Seng Bank",
                title="風險管理主任"),
            # Only the description mentions derivatives.
            job(source="indeed", source_id="DESC", company="UBS",
                title="Associate, Markets",
                description_clean="Coverage of equity derivatives and structured "
                                  "products, supporting quantitative analysis."),
            # A stemming-resistant typo target: porter reduces "actuarial" to
            # "actuari", which is far enough from a misspelling that only real
            # edit-distance correction — not the stemmer — can bridge it.
            job(source="jobsdb", source_id="ACT", company="Manulife",
                title="Actuarial Analyst"),
            # The short employer name ``EY`` must never turn a Big Four search
            # into a prefix search across descriptions: ``eye-opening`` is not
            # evidence that this Manulife role belongs to EY.
            job(source="jobsdb", source_id="EYE", company="Manulife",
                title="Customer Service Officer",
                description_clean="An eye-opening opportunity for service talent."),
            # Both words occur in this description, but the vacancy itself is
            # not a financial-manager role.  It mirrors the live false
            # positives: generic finance boilerplate plus a management
            # requirement admitting unrelated technology postings.
            job(source="jobsdb", source_id="NOISY", company="Tech Co",
                title="Senior Data Engineer",
                description_clean="Build platforms for financial services and manage "
                "reliable data pipelines."),
            job(source="jobsdb", source_id="FIN_MANAGER", company="DBS",
                title="Financial Planning Manager"),
            # BM25 rewards repeated words, but a clean exact role title is a
            # stronger expression of intent than a keyword-stuffed title.
            job(source="jobsdb", source_id="EXACT_FIN_MANAGER", company="HSBC",
                title="Financial Manager"),
            job(source="jobsdb", source_id="STUFFED_FIN_MANAGER", company="Other",
                title="Financial Manager Financial Manager Financial Manager "
                "Financial Manager"),
            # Hyphenation is tokenised as a space by FTS, so without an
            # explicit semantic guard this opposite role answers a financial
            # manager query just as if it were a financial role.
            job(source="jobsdb", source_id="NON_FINANCIAL_MANAGER", company="Morgan Stanley",
                title="Non-Financial Risk Manager"),
            # A multi-skill search has no title-level equivalent here, so the
            # precision gate must fall back to the broad index and retain it.
            job(source="jobsdb", source_id="SKILLS", company="HSBC",
                title="Operations Associate"),
            # This role mentions the same skills only in prose.  When the
            # deliberate skills field answers a multi-skill query, prose must
            # not dilute that result set.
            job(source="jobsdb", source_id="DESCRIPTION_SKILLS", company="Tech Co",
                title="Data Engineer",
                description_clean="Build Python and SQL data pipelines."),
            # Employer names used by the organisation-group search aliases.
            # None of their titles mention the group, so this verifies that a
            # group query expands to its constituent firms rather than merely
            # looking for the literal abbreviation in a posting.
            job(source="jobsdb", source_id="KPMG", company="KPMG",
                title="Audit Associate"),
            job(source="jobsdb", source_id="EY", company="EY",
                title="Tax Consultant"),
            job(source="jobsdb", source_id="DELOITTE", company="Deloitte",
                title="Risk Advisory Analyst"),
            job(source="jobsdb", source_id="PWC", company="PwC",
                title="Deals Associate"),
            job(source="jobsdb", source_id="MCKINSEY", company="McKinsey & Company",
                title="Business Analyst"),
            job(source="jobsdb", source_id="BAIN", company="Bain & Company",
                title="Associate Consultant"),
            job(source="jobsdb", source_id="BCG", company="Boston Consulting Group",
                title="Consultant"),
        ],
        enrichments=[
            enrichment(source="workday", source_id="QUANT",
                       required_skills='["Python", "C++"]'),
            enrichment(source="jobsdb", source_id="CN", title_en="Risk Management Officer"),
            enrichment(source="jobsdb", source_id="SKILLS",
                       required_skills='["Python", "SQL"]'),
        ],
    )
    c = sqlite3.connect(db)
    rebuild_search_index(c)
    yield c
    c.close()


def _hits(conn: sqlite3.Connection, query: str) -> set[str]:
    """The source_ids a query reaches, order-independent."""
    rowids = matching_rowids(conn, query)
    if not rowids:
        return set()
    marks = ",".join("?" * len(rowids))
    rows = conn.execute(
        f"SELECT source_id FROM jobs WHERE rowid IN ({marks})", list(rowids)
    ).fetchall()
    return {r[0] for r in rows}


def _rowid(conn: sqlite3.Connection, source_id: str) -> int:
    return conn.execute("SELECT rowid FROM jobs WHERE source_id = ?", (source_id,)).fetchone()[0]


# ── Recall: the indexed text is more than the title ───────────────────────────

def test_a_skill_finds_the_role_that_requires_it(conn):
    """RED before FTS: required_skills was never searched, so this returned nothing."""
    assert _hits(conn, "python") == {"QUANT", "SKILLS", "DESCRIPTION_SKILLS"}


def test_a_word_only_the_description_uses_finds_the_role(conn):
    """RED before FTS: description_clean was never searched."""
    assert _hits(conn, "derivatives") == {"DESC"}


def test_an_english_query_reaches_a_chinese_titled_role(conn):
    """
    RED before FTS: `title_en` was never searched, so the 3,904 Roles carrying an
    enrichment-supplied English title were reachable only by their employer name.
    """
    assert "CN" in _hits(conn, "risk management officer")


# ── Terms, not substrings ─────────────────────────────────────────────────────

def test_all_the_words_match_without_being_adjacent(conn):
    """
    RED before FTS: `%senior analyst%` is one contiguous string, so it missed the
    Role titled "Senior Risk Management Analyst" — every word of the query is in
    the title, and two other words sit between them.
    """
    assert _hits(conn, "senior analyst") == {"SRRMA"}


def test_word_order_does_not_decide_the_match(conn):
    """RED before FTS: 'management risk' matched nothing at all."""
    assert "SRRMA" in _hits(conn, "management risk")


def test_multi_word_role_search_excludes_description_only_noise(conn):
    """A role query needs all concepts in one high-intent field when possible."""
    assert _hits(conn, "financial manager") == {
        "FIN_MANAGER", "EXACT_FIN_MANAGER", "STUFFED_FIN_MANAGER"
    }


def test_non_financial_query_can_still_request_the_opposite_role(conn):
    assert "NON_FINANCIAL_MANAGER" in _hits(conn, "non financial manager")


def test_exact_title_outranks_a_keyword_stuffed_title(conn):
    """An exact role title beats term frequency in a much longer title."""
    rowids = matching_rowids(conn, "financial manager")
    ids = [
        conn.execute("SELECT source_id FROM jobs WHERE rowid = ?", (rowid,)).fetchone()[0]
        for rowid in rowids
    ]
    assert ids.index("EXACT_FIN_MANAGER") < ids.index("STUFFED_FIN_MANAGER")


def test_multi_skill_search_falls_back_when_no_primary_match_exists(conn):
    """Precision must not hide a role that only its deliberate skills answer."""
    assert _hits(conn, "python sql") == {"SKILLS"}


def test_match_reason_describes_the_strongest_field_that_matched(conn):
    """Card labels must describe actual search evidence, never a guess."""
    assert match_reason(conn, _rowid(conn, "EXACT_FIN_MANAGER"), "financial manager") == "exact_title"
    assert match_reason(conn, _rowid(conn, "FIN_MANAGER"), "financial manager") == "title"
    assert match_reason(conn, _rowid(conn, "PWC"), "big four") == "company"
    assert match_reason(conn, _rowid(conn, "SKILLS"), "python sql") == "skills"
    assert match_reason(conn, _rowid(conn, "DESC"), "derivatives") == "description"


# ── Organisation group aliases ──────────────────────────────────────────────

@pytest.mark.parametrize("query", ["big four", "Big4", "big 4"])
def test_big_four_aliases_reach_each_constituent_firm(conn, query):
    """A group name is a useful employer search, not literal posting text."""
    assert _hits(conn, query) == {"KPMG", "EY", "DELOITTE", "PWC"}


def test_big_four_alias_does_not_match_a_non_member_description(conn):
    """Employer-group aliases are employer evidence, never prose keywords."""
    assert "EYE" not in _hits(conn, "big four")


def test_mbb_and_the_common_mckensey_misspelling_reach_the_right_firms(conn):
    assert _hits(conn, "MBB") == {"MCKINSEY", "BAIN", "BCG"}
    assert _hits(conn, "mckensey") == {"MCKINSEY"}


def test_a_query_does_not_match_inside_a_longer_word(conn):
    """
    RED before FTS: `%vp%` matched AVP and FVP, so filtering to the VP level
    returned the very levels a candidate was trying to exclude.
    """
    assert _hits(conn, "vp") == {"VP"}


# ── Stemming ──────────────────────────────────────────────────────────────────

def test_a_singular_query_reaches_its_plural(conn):
    """The porter tokenizer is why 'derivative' and 'derivatives' are one term."""
    assert _hits(conn, "derivative") == {"DESC"}


# ── Ranking ───────────────────────────────────────────────────────────────────

def test_a_title_match_outranks_a_description_match(conn):
    """
    Relevance, not recency, is what a search engine returns.

    "quantitative" names one Role in its TITLE and appears in another's
    description. Both must come back — that half is RED before FTS, which never
    read descriptions — and the one named for the query must come back first.
    """
    order = matching_rowids(conn, "quantitative")
    ids = [
        conn.execute("SELECT source_id FROM jobs WHERE rowid = ?", (r,)).fetchone()[0]
        for r in order
    ]
    assert set(ids) == {"QUANT", "DESC"}
    assert ids[0] == "QUANT"


# ── Robustness ────────────────────────────────────────────────────────────────

def test_punctuation_in_a_query_is_not_a_syntax_error(conn):
    """
    FTS5 MATCH has an operator grammar: a bare quote or `*` from a human's query
    string raises OperationalError. A search box takes whatever is typed, so the
    query must be escaped rather than passed through.
    """
    for hostile in ['c++ "', "AND", "*", "risk AND/OR", "NEAR(", ""]:
        matching_rowids(conn, hostile)  # must not raise


def test_an_empty_query_matches_nothing(conn):
    assert matching_rowids(conn, "   ") == []


def test_rebuilding_twice_does_not_duplicate_rows(conn):
    rebuild_search_index(conn)
    assert _hits(conn, "python") == {"QUANT", "SKILLS", "DESCRIPTION_SKILLS"}
    assert len(matching_rowids(conn, "python")) == 3


# ── Typo tolerance ────────────────────────────────────────────────────────────
# "Similar to Google": a misspelled query still finds the Role, as long as
# something close enough exists in the board's own vocabulary. Every case here
# was checked to fail on porter stemming + prefix matching ALONE, with
# `_correct_token` stubbed to a no-op — otherwise the stemmer, not the
# correction this module adds, would get the credit. ("quantitive" and
# "managment", tried first, both turned out to already survive on stemming
# alone — porter folds them onto the same stem as the correct spelling — which
# is why "aktuarial" and "derivatibes" are the cases actually asserted below.)

def test_a_letter_swap_the_stemmer_cannot_absorb_still_finds_the_role(conn):
    """
    RED with correction disabled: porter stems "actuarial" to "actuari"; a
    "k" for "c" swap in "aktuarial" is not a prefix of that stem, so only
    edit-distance correction against the real word bridges it.
    """
    assert "ACT" in _hits(conn, "aktuarial")


def test_correction_does_not_cross_the_first_letter(conn):
    """
    RED with correction disabled: "derivatibes" (one letter swapped) does not
    stem-match "derivatives" as a prefix. The first-letter rule matters here
    too — without it, an unconstrained edit-distance search over the whole
    vocabulary could land on an unrelated word.
    """
    assert "DESC" in _hits(conn, "derivatibes")


def test_a_token_below_the_length_floor_is_never_autocorrected(conn):
    """
    "rsk" is one edit from "risk", which is in this vocabulary — but at 3
    characters it is below `_MIN_CORRECTABLE_LEN`, so it is never handed to
    edit-distance matching at all. It searches for exactly what was typed and,
    typed wrong, finds nothing. The floor exists because short tokens have too
    many legitimate near-neighbours ("vp" vs "up", "ib" vs "hr") for a 1-edit
    guess to be safe.
    """
    assert _hits(conn, "rsk") == set()


def test_a_word_already_in_the_vocabulary_is_never_rewritten(conn):
    """
    'python' is spelled correctly and present. Nothing about correction should
    touch it — this pins down that the fast "already valid" path is taken
    before any edit-distance scan runs at all.
    """
    from hk_jobs.search_index import to_match_query

    assert to_match_query(conn, "python") == '"python"*'
