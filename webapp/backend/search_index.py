"""
Querying the board's full-text search index — the READ half only.

Deliberately self-contained rather than importing hk_jobs.search_index. The
backend is started as `uvicorn main:app` with webapp/backend as the working
directory (see Procfile / railway.json), so the repo root is not on sys.path
and hk_jobs is not importable without path surgery that would break on
deploy — the same reasoning mailer.py gives for not importing
hk_jobs.notifications, and the same fix.

Only the query side lives here. Building and rebuilding `jobs_fts` and
`search_vocab` is scraper-side work — it runs from the pipeline, against a
writable connection, on hk_jobs/search_index.py's schedule (after every scrape,
enrich, and description-fetch run) — and this module never needs it: every
connection job_read.py hands it is opened with `PRAGMA query_only=ON`
(main.py's `get_db`). It only ever reads the two tables the scraper already
built.

**Keep `matching_rowids`, `to_match_query`, `_correct_token`, `_has_prefix` and
`_levenshtein` identical to hk_jobs/search_index.py.** They are two copies of
the same algorithm by necessity, not by drift — if one changes how a query is
turned into a match expression or a typo is corrected, the other silently
starts ranking or matching differently for the same search. hk_jobs/search_index.py
carries the full design rationale (why porter, why a separate unstemmed
vocabulary, why the first-letter and length-floor rules on correction); read
that file if you're wondering "why does this do X" rather than duplicating the
explanation here.
"""

from __future__ import annotations

import logging
import re
import sqlite3

logger = logging.getLogger(__name__)

#: Must match hk_jobs/search_index.py's `_COLUMNS` order — bm25() weights are
#: positional.
_BM25_WEIGHTS = (10.0, 8.0, 4.0, 3.0, 1.0)

_TOKEN = re.compile(r"[^\w一-鿿]+", re.UNICODE)

# Must match hk_jobs/search_index.py. These are employer-group abbreviations
# people use in the market; each value is a set of ANDed FTS terms, with the
# alternatives ORed together.
_COMPANY_GROUP_ALIASES: dict[tuple[str, ...], tuple[tuple[str, ...], ...]] = {
    ("big", "four"): (
        ("kpmg",),
        ("deloitte",),
        ("pwc",),
        ("pricewaterhousecoopers",),
        ("pricewaterhouse", "coopers"),
        ("ey",),
        ("ernst", "young"),
    ),
    ("big", "4"): (
        ("kpmg",),
        ("deloitte",),
        ("pwc",),
        ("pricewaterhousecoopers",),
        ("pricewaterhouse", "coopers"),
        ("ey",),
        ("ernst", "young"),
    ),
    ("big4",): (
        ("kpmg",),
        ("deloitte",),
        ("pwc",),
        ("pricewaterhousecoopers",),
        ("pricewaterhouse", "coopers"),
        ("ey",),
        ("ernst", "young"),
    ),
    ("mbb",): (
        ("mckinsey",),
        ("bain",),
        ("bcg",),
        ("boston", "consulting", "group"),
    ),
    ("mckensey",): (("mckinsey",),),
}

_MIN_CORRECTABLE_LEN = 4
_MAX_EDITS_SHORT = 1  # words of length 4-5
_MAX_EDITS_LONG = 2   # words of length 6+


def _levenshtein(a: str, b: str, cap: int) -> int:
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
    row = conn.execute(
        "SELECT 1 FROM search_vocab WHERE word GLOB ? LIMIT 1", (token + "*",)
    ).fetchone()
    return row is not None


def _correct_token(conn: sqlite3.Connection, token: str) -> str:
    if len(token) < _MIN_CORRECTABLE_LEN or not token.isascii():
        return token

    # No vocabulary table → no correction, not an error.
    #
    # `matching_rowids` already promised to survive a database with no index,
    # and guarded the jobs_fts read to keep that promise. This is the half that
    # was left outside the guard: correction runs BEFORE the match query, so on
    # a database predating the index it threw first and the guard never ran —
    # which is why the production traceback named search_vocab rather than the
    # table it was protecting. The deployed board answered every search with a
    # 500 for exactly this reason (2026-08-05).
    #
    # Degraded separately from the index on purpose: a database that has
    # jobs_fts but no vocabulary can still search the words as typed, and only
    # loses typo tolerance. Correction is an enhancement, not a precondition.
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
    tokens = [t for t in _TOKEN.split((query or "").lower()) if t]
    if not tokens:
        return ""

    alias_lengths = sorted({len(key) for key in _COMPANY_GROUP_ALIASES}, reverse=True)
    clauses: list[str] = []
    i = 0
    while i < len(tokens):
        alternatives = None
        consumed = 0
        for size in alias_lengths:
            candidate = tuple(tokens[i : i + size])
            if len(candidate) == size and candidate in _COMPANY_GROUP_ALIASES:
                alternatives = _COMPANY_GROUP_ALIASES[candidate]
                consumed = size
                break

        if alternatives is not None:
            # Employer-group aliases must match the company field exactly.
            # Searching every field with a prefix made ``EY`` match ordinary
            # prose such as "eye-opening" in unrelated roles.
            options = [
                "(" + " AND ".join(f'company : \"{term}\"' for term in option) + ")"
                for option in alternatives
            ]
            clauses.append("(" + " OR ".join(options) + ")")
            i += consumed
            continue

        token = _correct_token(conn, tokens[i])
        suffix = "*" if i == len(tokens) - 1 else ""
        clauses.append(f'"{token}"{suffix}')
        i += 1

    return " AND ".join(clauses)


_PRIMARY_SEARCH_COLUMNS = ("title", "title_en", "company")
_SKILLS_SEARCH_COLUMN = "skills"


def _has_company_group_alias(tokens: list[str]) -> bool:
    """Whether tokens contain a configured employer-group alias."""
    for key in _COMPANY_GROUP_ALIASES:
        size = len(key)
        if any(tuple(tokens[i : i + size]) == key for i in range(len(tokens) - size + 1)):
            return True
    return False


def _primary_match_query(conn: sqlite3.Connection, query: str, match: str) -> str:
    """Prefer a cohesive title, translated-title, or employer match for a role query."""
    tokens = [t for t in _TOKEN.split((query or "").lower()) if t]
    if len(tokens) < 2 or _has_company_group_alias(tokens):
        return ""
    return " OR ".join(f"{column} : ({match})" for column in _PRIMARY_SEARCH_COLUMNS)


def _skills_match_query(conn: sqlite3.Connection, query: str, match: str) -> str:
    """Restrict an ordinary multi-word fallback to declared required skills."""
    tokens = [t for t in _TOKEN.split((query or "").lower()) if t]
    if len(tokens) < 2 or _has_company_group_alias(tokens):
        return ""
    return f"{_SKILLS_SEARCH_COLUMN} : ({match})"


def _exact_title_rowids(conn: sqlite3.Connection, query: str) -> set[int]:
    """Rows whose title is exactly an ordinary multi-word query."""
    tokens = [t for t in _TOKEN.split((query or "").lower()) if t]
    if len(tokens) < 2 or _has_company_group_alias(tokens):
        return set()
    phrase = " ".join(_correct_token(conn, token) for token in tokens)
    rows = conn.execute(
        "SELECT rowid FROM jobs_fts "
        "WHERE lower(trim(title)) = ? OR lower(trim(title_en)) = ?",
        (phrase, phrase),
    ).fetchall()
    return {row[0] for row in rows}


def _promote_exact_title_matches(
    conn: sqlite3.Connection, query: str, rowids: list[int]
) -> list[int]:
    """Move exact-title matches ahead of the existing BM25-ranked candidates."""
    exact = _exact_title_rowids(conn, query)
    if not exact:
        return rowids
    return [rowid for rowid in rowids if rowid in exact] + [
        rowid for rowid in rowids if rowid not in exact
    ]


def _exclude_opposite_title_matches(
    conn: sqlite3.Connection, query: str, rowids: list[int]
) -> list[int]:
    """Remove title-level semantic opposites of an unqualified role query."""
    tokens = [t for t in _TOKEN.split((query or "").lower()) if t]
    if "financial" not in tokens or "non" in tokens:
        return rowids
    rows = conn.execute(
        "SELECT rowid FROM jobs_fts WHERE jobs_fts MATCH ?",
        ('title : "non financial" OR title_en : "non financial"',),
    ).fetchall()
    opposites = {row[0] for row in rows}
    return [rowid for rowid in rowids if rowid not in opposites]


def match_reason(conn: sqlite3.Connection, rowid: int, query: str) -> str | None:
    """The strongest indexed field that makes one returned Role relevant."""
    match = to_match_query(conn, query)
    if not match:
        return None
    if rowid in _exact_title_rowids(conn, query):
        return "exact_title"

    tokens = [t for t in _TOKEN.split((query or "").lower()) if t]
    if _has_company_group_alias(tokens):
        return "company"

    for reason, column in (
        ("title", "title"),
        ("title_en", "title_en"),
        ("company", "company"),
        ("skills", "skills"),
        ("description", "description"),
    ):
        field_match = f"{column} : ({match})"
        row = conn.execute(
            "SELECT 1 FROM jobs_fts WHERE rowid = ? AND jobs_fts MATCH ?",
            (rowid, field_match),
        ).fetchone()
        if row is not None:
            return reason
    return None


def _matching_rowids_for_match(
    conn: sqlite3.Connection, match: str, *, limit: int
) -> list[int]:
    """Run one safe FTS expression in BM25 order."""
    weights = ", ".join(str(w) for w in _BM25_WEIGHTS)
    rows = conn.execute(
        f"SELECT rowid FROM jobs_fts WHERE jobs_fts MATCH ?"
        f" ORDER BY bm25(jobs_fts, {weights}) LIMIT ?",
        (match, limit),
    ).fetchall()
    return [r[0] for r in rows]


def matching_rowids(conn: sqlite3.Connection, query: str, *, limit: int = 20000) -> list[int]:
    """
    The `jobs.rowid`s matching `query`, most relevant first — or `[]` if the
    index is missing (a database that predates it) or the query matched
    nothing. `job_read.list_jobs` intersects this with its own WHERE clause and
    paging; see that module for how "matched nothing" (`[]`) differs from "no
    search requested" (`None`, handled by the caller, not here).

    `limit` must stay in sync with hk_jobs/search_index.py's — see that
    module's docstring for why 20,000 (not board-scale ~4,000): this table
    indexes every inactive/non-primary duplicate too, and a lower cap measured
    at losing two-thirds of a generic query's true board-visible matches to
    non-board rows outranking them in BM25 before visibility was ever applied.
    """
    match = to_match_query(conn, query)
    if not match:
        return []

    try:
        primary_match = _primary_match_query(conn, query, match)
        if primary_match and (rows := _matching_rowids_for_match(conn, primary_match, limit=limit)):
            return _exclude_opposite_title_matches(
                conn, query, _promote_exact_title_matches(conn, query, rows)
            )
        skills_match = _skills_match_query(conn, query, match)
        if skills_match and (rows := _matching_rowids_for_match(conn, skills_match, limit=limit)):
            return rows
        rows = _matching_rowids_for_match(conn, match, limit=limit)
    except sqlite3.OperationalError:
        logger.warning("Search index unavailable; query %r returned nothing.", query)
        return []

    return _exclude_opposite_title_matches(
        conn, query, _promote_exact_title_matches(conn, query, rows)
    )
