"""
The one definition of "is this Role on the board" (docs/adr/0033, docs/adr/0034).

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
"""

from __future__ import annotations


def board_visible_sql(*, with_hidden: bool = False) -> str:
    """
    The BOARD predicate: open, primary, posted within the last calendar month,
    and — unless `with_hidden=True` — not admin-hidden (ADR 0032). A missing
    posting date fails closed: its age cannot be verified, so it is not "on
    the board" either. Expects the jobs table aliased `j`.

    `with_hidden=True` exists only for `job_read._BOARD_WHERE_WITH_HIDDEN`
    (Ultimate Admin's greyed hidden-Roles view, ADR 0032) — the enrichment
    write path never sets it: a hidden Role is not on the public board, so
    ADR 0034 excludes it from estimation exactly like anything else off-board.
    """
    return (
        "j.is_active = 1 AND j.is_primary = 1"
        + ("" if with_hidden else " AND NOT j.admin_hidden")
        + " AND date(j.posted_at) >= date('now', '-1 month')"
    )
