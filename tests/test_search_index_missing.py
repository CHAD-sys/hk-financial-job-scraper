"""
Searching a database that has no search index.

WHY THIS EXISTS
---------------
This shape was assumed impossible. `support.make_jobs_db` says so in as many
words — a stand-in without `jobs_fts`/`search_vocab` "would make every `search=`
test exercise a database shape that cannot occur outside a test".

It occurs. On 2026-08-05 the deployed board answered every search with HTTP 500:

    sqlite3.OperationalError: no such table: search_vocab

Production reads a SQLite snapshot uploaded to a Railway volume by hand, and
building the index is scraper-side work that runs against a *local* database.
The snapshot on the volume predates the search feature, so it has neither table
while the frontend happily offers a search box.

`matching_rowids` already meant to survive this — its docstring promises `[]`
"if the index is missing (a database that predates it)", and it wraps the
`jobs_fts` query in `try/except sqlite3.OperationalError` to keep that promise.
The hole was upstream of the guard: `to_match_query` runs first, and its typo
correction reads `search_vocab`. That throw escaped, which is why the traceback
names the vocabulary table and not the index it was guarding.

So: typo correction is an enhancement, not a precondition. Without a vocabulary
the words are searched as typed; without an index there are no matches. Neither
is a 500.
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from .support import make_app, make_bundle, make_jobs_db


def _db_without(path, *tables: str):
    """A seeded jobs.db with the named index tables dropped."""
    make_jobs_db(path)
    conn = sqlite3.connect(path)
    try:
        for table in tables:
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.commit()
    finally:
        conn.close()
    return path


def _client(tmp_path, *dropped: str) -> TestClient:
    db = _db_without(tmp_path / "jobs.db", *dropped)
    dist = tmp_path / "dist"
    make_bundle(dist)
    return TestClient(make_app(db, dist, tmp_path))


def test_search_survives_a_database_with_no_vocabulary(tmp_path):
    # The exact production shape as of 2026-08-05: no vocabulary table, so typo
    # correction cannot run. Searching must still answer.
    client = _client(tmp_path, "search_vocab")
    r = client.get("/api/jobs", params={"search": "compliance"})
    assert r.status_code == 200, r.text


def test_search_survives_a_database_with_no_index_at_all(tmp_path):
    # A snapshot predating the whole feature — neither table. Still 200, and
    # honestly empty rather than pretending to have searched.
    client = _client(tmp_path, "search_vocab", "jobs_fts")
    r = client.get("/api/jobs", params={"search": "compliance"})
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 0


@pytest.mark.parametrize("sort", ["relevance", "newest", "salary_high"])
def test_every_sort_survives_a_missing_index(tmp_path, sort):
    # "Best match" is the sort the UI selects automatically on a fresh query,
    # so it is the one a visitor hits first — but a missing index must not take
    # the ordinary sorts down with it either.
    client = _client(tmp_path, "search_vocab", "jobs_fts")
    r = client.get("/api/jobs", params={"search": "compliance", "sort": sort})
    assert r.status_code == 200, r.text


def test_missing_index_does_not_reopen_unscoped_catalogue_access(tmp_path):
    client = _client(tmp_path, "search_vocab", "jobs_fts")
    r = client.get("/api/jobs")
    assert r.status_code == 422, r.text
