"""
The one definition of "is this Role on the board" (docs/adr/0033, docs/adr/0034,
docs/adr/0035).

Shared by the READ path (`webapp/backend/job_read.BOARD_WHERE`, what a Seeker
browses) and the WRITE path (`hk_jobs.enrichment._fetch_unenriched`, what gets
sent to DeepSeek) so they cannot drift apart the way they just did: a bulk
enrichment run spent $5.24 on 1,164 Roles, and 66% of them — duplicate copies
of a cross-posted vacancy, postings over a month old, rows with no posting
date — could never have been shown to a Seeker. That was not a bug in either
predicate; it was two predicates that had no reason to agree, because only one
of them existed. See ADR 0034 for the decision this enforces:

    WE DO NOT ESTIMATE THE SALARY OF A ROLE THAT IS NOT ON THE BOARD.

`hk_jobs` has no dependency on `webapp/backend` (the pipeline runs standalone,
without the web app installed), so this predicate lives on the pipeline side
and `job_read.py` imports it — the same direction `job_read.py` already
imports `hk_jobs.sector_classify` from.

ADR 0035 adds the per-company cap: at most `BOARD_COMPANY_CAP` Roles per
employer, newest first. The board had drifted to ~3,250 Roles — more than the
nightly DeepSeek run can enrich, so the freshest, most-viewed Roles sat on the
board with no salary figure. A handful of mega-posters (Bank of China ~300,
HKEX ~220, AIA ~160) drove most of that volume; capping every employer at the
same number brings the board to ~2,100 — a size the nightly run covers in
full — while leaving ~55 smaller employers untouched.
"""

from __future__ import annotations

#: ADR 0035. At most this many Roles per employer (`jobs.company_slug`) on the
#: board, ranked newest-first. One knob: raising it widens every employer
#: equally, there is no per-employer override. ~60 lands the board near 2,100
#: on the 2026-09 catalogue; the nightly `--enrich` limit (500/night since
#: ADR 0035) then covers the whole board with headroom for the daily inflow.
BOARD_COMPANY_CAP = 60


def board_visible_sql(*, with_hidden: bool = False) -> str:
    """
    The BOARD predicate: open, primary, posted within the last calendar month,
    not admin-hidden (unless `with_hidden=True`, ADR 0032), AND — ADR 0035 —
    among the freshest `BOARD_COMPANY_CAP` Roles for its employer. A missing
    posting date fails closed: its age cannot be verified, so it is not "on
    the board" and cannot be ranked for the cap either. Expects the jobs table
    aliased `j`.

    `with_hidden=True` exists only for `job_read._BOARD_WHERE_WITH_HIDDEN`
    (Ultimate Admin's greyed hidden-Roles view, ADR 0032) — the enrichment
    write path never sets it: a hidden Role is not on the public board, so
    ADR 0034 excludes it from estimation exactly like anything else off-board.
    When it IS set, the `NOT admin_hidden` clause is dropped from BOTH the core
    predicate and the cap's own subquery, so hidden Roles rank in.

    The cap subquery is NOT correlated: it ranks the whole eligible set once,
    partitioned by `company_slug`, newest first, and yields the top
    `BOARD_COMPANY_CAP` rowids per employer. Needs SQLite window functions
    (>= 3.25; every target has them). At ~19k rows / ~3k eligible it is
    sub-millisecond; revisit only if the table grows an order of magnitude.
    """
    core = (
        "j.is_active = 1 AND j.is_primary = 1"
        + ("" if with_hidden else " AND NOT j.admin_hidden")
        + " AND date(j.posted_at) >= date('now', '-1 month')"
    )
    cap = (
        "j.rowid IN ("
        "SELECT rowid FROM ("
        "SELECT j.rowid AS rowid, ROW_NUMBER() OVER ("
        "PARTITION BY j.company_slug "
        "ORDER BY j.posted_at DESC, j.rowid DESC"
        ") AS _company_rank "
        f"FROM jobs j WHERE {core}"
        f") WHERE _company_rank <= {BOARD_COMPANY_CAP})"
    )
    return f"{core} AND {cap}"
