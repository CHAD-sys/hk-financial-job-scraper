"""
The board's full-text search index.

Search used to be one line of SQL in the read path:

    (LOWER(j.title) LIKE ? OR LOWER(j.company) LIKE ?)

That is a substring test on two columns, and it was wrong in four separate ways
at once. Against the live board of ~3,900 Roles: "python" reached 3 of the 306
Roles that ask for it, because skills were never searched; "senior analyst"
reached none of the Roles titled "Senior … Analyst", because `%…%` needs the
words adjacent; "vp" returned every AVP and FVP posting, because a substring has
no idea where a word begins; and a Chinese-titled Role was unreachable by its
English name even though enrichment had stored that name all along. On top of
all of it, results came back in date order, so the Role named for your query
ranked below an unrelated newer one whose EMPLOYER happened to contain the
string.

This module replaces that with SQLite's own FTS5 index, plus a second, small
piece a plain FTS index does not give you: forgiveness for a typo. No new
dependency for either — FTS5 and its `fts5vocab` companion are compiled into
the stdlib `sqlite3` — which is what keeps this inside the project's
no-new-infrastructure line.

Four decisions worth stating, because none is reversible cheaply:

  - **The FTS table is standalone, not `content=jobs`.** An external-content
    FTS5 table mirrors exactly one table. The text worth searching spans two:
    the title and description on `jobs`, and the English title and extracted
    skills on `job_enrichments`. There is no single content table to point at,
    so the index stores its own copy of the text. It costs disk and it costs a
    rebuild; it is the only shape that can search what enrichment produces.

  - **The tokenizer is `porter`.** It folds a word to its stem, which is what
    makes "actuary" find "Actuarial Analyst" and "derivative" find
    "derivatives". Measured on the real board's vocabulary against plain
    `unicode61`, which unifies neither.

  - **Typo correction runs against a SEPARATE, unstemmed vocabulary
    (`search_vocab`), not the FTS index's own stemmed terms.** The obvious
    shortcut — `fts5vocab`, built into FTS5 for free — stores "actuari", not
    "actuarial". Edit distance from a typo like "aktuarial" to the real word
    "actuarial" is 1; to the stem "actuari" it is larger, and the correction
    misses. `search_vocab` is real words, extracted with the same tokenizer the
    query side uses, so a typo is compared against what a person actually
    typed wrong — not what the stemmer reduced it to.

  - **A word under 4 characters is never corrected, and a candidate must share
    the first letter.** Both cut the two failure modes short candidate lists
    invite: "riks" nearly became "is" without them (2 edits, 2-character
    words are all near-neighbours of everything), and a search for "vp" must
    never silently become a search for "up". Google's own suggestion engine
    leans on the same first-letter heuristic for the same reason — most typos
    do not touch the first character.

Chinese text does not tokenize meaningfully under either tokenizer option —
that needs ICU, which is not compiled in. This is why `title_en` is indexed and
not merely nice to have: for the ~3,900 Roles enrichment gives an English title
to, that column IS the searchable handle on a Chinese posting. A Chinese-
language QUERY still will not work, and no amount of weighting hides that.

QUERY-SIDE COPY
----------------
`webapp/backend/search_index.py` carries a second copy of everything from
`to_match_query` down: the tokenizer regex, the correction thresholds, the
Levenshtein function, `matching_rowids`. Not drift — the backend cannot import
this package (see that file's docstring for why) and mailer.py already sets
the precedent of duplicating rather than doing import path surgery that breaks
on deploy. If you change how a query is turned into a match expression, a typo
is corrected, or a column is weighted, change both copies.
"""

from __future__ import annotations

import logging
import re
import sqlite3

logger = logging.getLogger(__name__)


#: The indexed columns, most specific first. Order is load-bearing: `bm25()`
#: takes one weight per column IN THIS ORDER, so `_BM25_WEIGHTS` below is
#: positional and the two must be edited together.
_COLUMNS = ("title", "title_en", "company", "skills", "description")

#: Relevance weights, positionally matched to `_COLUMNS`.
#:
#: A title match is the strongest evidence a Role is what you asked for, so it
#: outweighs a description mention by 10:1 — a description is thousands of words
#: and will mention nearly anything in passing. `title_en` sits just below the
#: native title (it is a translation, one step removed). Skills rank above the
#: description because they are an extracted, deliberate list rather than prose.
_BM25_WEIGHTS = (10.0, 8.0, 4.0, 3.0, 1.0)

_FTS_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS jobs_fts USING fts5(
    title, title_en, company, skills, description,
    tokenize = 'porter unicode61 remove_diacritics 2'
);
"""

#: The spelling vocabulary: every distinct word actually seen in the indexed
#: text, unstemmed, with how many Roles carry it. `first`/`len` are stored
#: rather than computed at query time so a correction lookup can use the
#: `(first, len)` index instead of scanning all ~20-30k words.
_VOCAB_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS search_vocab (
    word      TEXT NOT NULL PRIMARY KEY,
    first     TEXT NOT NULL,
    len       INTEGER NOT NULL,
    doc_count INTEGER NOT NULL
);
"""
_VOCAB_INDEX_DDL = """
CREATE INDEX IF NOT EXISTS idx_search_vocab_lookup ON search_vocab(first, len);
"""

#: The text of one Role, assembled from both tables. `rowid` ties a row of the
#: index back to its row in `jobs`, which is how a caller joins the two.
#:
#: LEFT JOIN, not JOIN: a Role with no enrichment row yet must still be
#: searchable by its title. An inner join here would have silently dropped every
#: not-yet-enriched Role out of search entirely.
_SOURCE_SELECT = """
SELECT
    j.rowid,
    j.title,
    COALESCE(e.title_en, ''),
    j.company,
    COALESCE(e.required_skills, ''),
    COALESCE(j.description_clean, '')
FROM jobs j
LEFT JOIN job_enrichments e
  ON j.source = e.source AND j.source_id = e.source_id
"""

#: Anything that is not a word character, a digit or CJK. Splitting on this and
#: re-quoting each piece is what makes the query box safe to type into, and it
#: is also how `search_vocab` is built — a word means the same thing on both
#: sides of a search.
_TOKEN = re.compile(r"[^\w一-鿿]+", re.UNICODE)


def rebuild_search_index(conn: sqlite3.Connection) -> int:
    """
    Rebuild the FTS index AND the spelling vocabulary from `jobs` +
    `job_enrichments`, in one pass over the source rows. Returns rows indexed.

    A full rebuild rather than incremental triggers. Triggers would have to fire
    from two tables to keep one index coherent, and the pipeline writes both in
    separate phases — enrichment lands after storage — so a trigger-maintained
    index is stale for part of every run no matter which table it watches. A
    rebuild is one pass, runs in low single-digit seconds at this board's size
    (~15k rows), and cannot half-apply.

    `DELETE FROM jobs_fts` / `search_vocab` before re-inserting is what makes
    calling this twice the same as calling it once; without it every rebuild
    doubles every Role.
    """
    with conn:
        conn.execute(_FTS_DDL)
        conn.execute(_VOCAB_TABLE_DDL)
        conn.execute(_VOCAB_INDEX_DDL)
        conn.execute("DELETE FROM jobs_fts")
        conn.execute("DELETE FROM search_vocab")

        rows = conn.execute(_SOURCE_SELECT).fetchall()
        if rows:
            conn.executemany(
                f"INSERT INTO jobs_fts (rowid, {', '.join(_COLUMNS)}) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                rows,
            )

        # One vocabulary pass over the same rows already in memory — no second
        # scan of `jobs`/`job_enrichments`. `doc_count` counts ROLES a word
        # appears in (a set per row), not raw occurrences, so a word repeated
        # six times in one description doesn't outrank one that appears once
        # each in six different Roles' titles.
        vocab: dict[str, int] = {}
        for row in rows:
            words: set[str] = set()
            for text in row[1:]:
                for w in _TOKEN.split(text.lower()):
                    if len(w) >= 2 and w.isascii():
                        words.add(w)
            for w in words:
                vocab[w] = vocab.get(w, 0) + 1

        if vocab:
            conn.executemany(
                "INSERT INTO search_vocab (word, first, len, doc_count) VALUES (?, ?, ?, ?)",
                [(w, w[0], len(w), n) for w, n in vocab.items()],
            )

        count = conn.execute("SELECT COUNT(*) FROM jobs_fts").fetchone()[0]

    logger.info(
        "Search index rebuilt: %s Role(s), %s vocabulary word(s).", count, len(vocab)
    )
    return count


# ── Typo correction ─────────────────────────────────────────────────────────

#: Below this length a word is never corrected. Short words have too many
#: legitimate near-neighbours ("vp" vs "up", "ib" vs "hr") for edit-distance
#: guessing to be safe, and Hong Kong finance is full of short, deliberate
#: abbreviations that must survive untouched.
_MIN_CORRECTABLE_LEN = 4

#: Edit-distance budget, tighter for shorter words for the same reason as the
#: length floor above — a 2-edit budget on a 5-letter word tolerates almost
#: anything being "close" to it.
_MAX_EDITS_SHORT = 1  # words of length 4-5
_MAX_EDITS_LONG = 2   # words of length 6+


def _levenshtein(a: str, b: str, cap: int) -> int:
    """Edit distance, capped: anything beyond `cap` returns `cap + 1`."""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr.append(min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost))
        prev = curr
    return prev[-1]


def _has_prefix(conn: sqlite3.Connection, token: str) -> bool:
    """True if some indexed word starts with `token` — i.e. it needs no fix."""
    row = conn.execute(
        "SELECT 1 FROM search_vocab WHERE word GLOB ? LIMIT 1", (token + "*",)
    ).fetchone()
    return row is not None


def _correct_token(conn: sqlite3.Connection, token: str) -> str:
    """
    `token` if it (or a word it's a prefix of) is already in the vocabulary,
    otherwise the closest vocabulary word within budget — falling back to
    `token` unchanged if nothing is close enough to guess.

    The `(first, len)` index keeps the candidate scan small: only words that
    share a first letter and land within the edit budget on length are ever
    compared, not the full ~20-30k-word vocabulary.
    """
    if len(token) < _MIN_CORRECTABLE_LEN or not token.isascii():
        return token

    # No vocabulary table → no correction, not an error. Kept identical to
    # webapp/backend/search_index.py, per this module's "keep them identical"
    # rule; that copy is where it matters, because the backend reads databases
    # it did not build (a hand-uploaded volume snapshot predating the index
    # answered every live search with a 500 on 2026-08-05). Scraper-side this
    # branch should never fire — rebuild_search_index() creates both tables —
    # but the two implementations drifting is the failure this rule exists to
    # prevent, so the guard lives in both.
    try:
        if _has_prefix(conn, token):
            return token

        cap = _MAX_EDITS_SHORT if len(token) <= 5 else _MAX_EDITS_LONG
        candidates = conn.execute(
            "SELECT word, doc_count FROM search_vocab WHERE first = ? AND len BETWEEN ? AND ?",
            (token[0], len(token) - cap, len(token) + cap),
        ).fetchall()
    except sqlite3.OperationalError:
        logger.warning(
            "Search vocabulary unavailable; %r searched without typo correction.", token
        )
        return token

    best, best_dist, best_doc = None, cap + 1, -1
    for word, doc_count in candidates:
        d = _levenshtein(token, word, cap)
        if d <= cap and (d < best_dist or (d == best_dist and doc_count > best_doc)):
            best, best_dist, best_doc = word, d, doc_count
    return best or token


def to_match_query(conn: sqlite3.Connection, query: str) -> str:
    """
    Turn what a human typed into an FTS5 MATCH expression. `""` means "no query".

    FTS5 MATCH is a grammar, not a string: `AND`, `OR`, `NOT`, `NEAR`, `*`, `^`,
    `(`, `:` and `"` are all operators. A search box receives none of that on
    purpose and all of it by accident — someone searching `C++` or typing a stray
    quote would otherwise get an OperationalError and a 500, not zero results.

    So every token is spelling-corrected (see `_correct_token`), stripped to
    word characters and wrapped in double quotes, which demotes it to a literal
    string. The tokens are then implicitly ANDed, because a searcher adding a
    word means to NARROW: "risk analyst" should find the Roles that are both,
    not the union of everything risk and everything analyst.

    A trailing `*` is attached to the LAST token so a half-typed word still
    matches — "compl" finds compliance. Only the last one, because that is the
    word a live-search caller is still in the middle of typing.
    """
    tokens = [t for t in _TOKEN.split((query or "").lower()) if t]
    if not tokens:
        return ""

    corrected = [_correct_token(conn, t) for t in tokens]
    quoted = [f'"{t}"' for t in corrected[:-1]]
    quoted.append(f'"{corrected[-1]}"*')
    return " AND ".join(quoted)


def matching_rowids(conn: sqlite3.Connection, query: str, *, limit: int = 20000) -> list[int]:
    """
    The `jobs.rowid`s matching `query`, most relevant first.

    Returns rowids rather than rows so the caller keeps ownership of its own
    SELECT — the board still has 17 filters, its own visibility rule and its own
    paging to apply, and none of that belongs in here. The read path intersects
    this list with its WHERE clause.

    `limit` bounds this index's scan, not the board's visible result count —
    the two are NOT close. This module indexes every row this table holds
    (~15k: every inactive and non-primary duplicate from every re-scrape, not
    just the ~3,900 the board shows), and a generic single word ranks plenty of
    those above some of the board-visible rows a caller actually wants. A limit
    of 2,000 measured against "compliance" here returned 546 board-visible
    matches; the true count is 1,816 — the missing ~1,270 were real matches
    that lost the BM25 ranking to non-board duplicates and got cut before the
    caller's own visibility filter ever ran. 20,000 clears this table's full
    row count, so nothing is lost; the cost is a caller building a RELEVANCE
    ordering from as many rowids as this returns (job_read.py's
    `_relevance_order_sql` — a few hundred ms in the worst case, at this
    table's size).

    An empty or all-punctuation query returns `[]`, meaning "matched nothing".
    The caller decides whether no query means no filter — this cannot know.
    """
    match = to_match_query(conn, query)
    if not match:
        return []

    weights = ", ".join(str(w) for w in _BM25_WEIGHTS)
    try:
        rows = conn.execute(
            f"SELECT rowid FROM jobs_fts WHERE jobs_fts MATCH ?"
            f" ORDER BY bm25(jobs_fts, {weights}) LIMIT ?",
            (match, limit),
        ).fetchall()
    except sqlite3.OperationalError:
        # The index is missing (a database that predates it, or a caller that
        # never rebuilt). Degrade to "no matches" rather than 500 the board.
        logger.warning("Search index unavailable; query %r returned nothing.", query)
        return []

    return [r[0] for r in rows]
