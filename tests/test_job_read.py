"""
Specification for the jobs read module.

These are not characterization tests. They state what the read path SHOULD do,
including the two things it did not do before it had a module:

  - a Role reached by reference comes back whatever state it is in, marked
    `closed`, rather than silently looking live or vanishing;
  - the paging count is built from the same join as the rows it counts.

They talk to the module through a plain `sqlite3.Connection`. No TestClient, no
app import, no `sys.modules` surgery — that is the point of the seam.
"""

from __future__ import annotations

import sqlite3
import sys

import pytest

from .support import BACKEND, days_ago, enrichment, job, make_jobs_db, signals

sys.path.insert(0, str(BACKEND))

from job_read import (  # noqa: E402
    CatalogueAudience,
    JobFilters,
    Sort,
    Visibility,
    get_job,
    has_research_scope,
    jobs_by_refs,
    list_jobs,
    prepare,
    research_facets,
    scope_where,
)

LIVE = ("workday", "LIVE")
CLOSED = ("workday", "CLOSED")
SECONDARY = ("workday", "SECONDARY")
ABSENT = ("ghost", "GONE")


@pytest.fixture()
def conn(tmp_path) -> sqlite3.Connection:
    db = tmp_path / "jobs.db"
    make_jobs_db(
        db,
        jobs=[
            job(source="workday", source_id="LIVE", company="HSBC",
                title="Credit Risk Analyst", posted_at=days_ago(1)),
            job(source="workday", source_id="CLOSED", company="HSBC",
                title="Closed Role", posted_at="2026-06-01", is_active=0),
            job(source="workday", source_id="SECONDARY", company="HSBC",
                title="Secondary Copy", posted_at="2026-05-01", is_primary=0),
            job(source="jobsdb", source_id="XPOST", company="DBS",
                title="Shared Role", posted_at=days_ago(4),
                cross_posted=1, apply_url="https://apply.test/x",
                board_signals=signals(applicant_count=3)),
            job(source="indeed", source_id="XPOST_HIDDEN", company="DBS",
                title="Shared Role", posted_at="2026-04-01", is_primary=0,
                cross_posted=1, apply_url="https://apply.test/x",
                board_signals=signals(urgently_hiring=True)),
        ],
        enrichments=[
            enrichment(source="workday", source_id="LIVE",
                       salary_hkd_min=40_000, salary_hkd_max=60_000, seniority="mid"),
        ],
    )
    c = prepare(sqlite3.connect(db))
    yield c
    c.close()


def _ids(jobs) -> list[str]:
    return [j.source_id for j in jobs]


# ── Research Scope gate (ADR 0018) ──────────────────────────────────────────
# Used to be a bare `2` retyped at three HTTP routes plus once more in the
# frontend. These pin the one number every caller now shares.


def test_research_scope_requires_the_minimum_length():
    assert has_research_scope("a") is False
    assert has_research_scope("ab") is True


def test_research_scope_trims_whitespace_before_counting():
    assert has_research_scope(" a ") is False
    assert has_research_scope(" ab ") is True


def test_research_scope_rejects_empty_and_none():
    assert has_research_scope("") is False
    assert has_research_scope(None) is False


# ── Catalogue scope (main.py's aggregate routes reuse this) ────────────────
# get_stats, the hub page and the landing-page index used to each hand-write
# their own "visible, audience-scoped" WHERE fragment. This is the one
# predicate all of them share now — pinned here against list_jobs' own count
# so the aggregate routes and the ordinary listing can never quietly disagree
# about what a live Role is, the exact failure job_read.py's own module
# docstring says already happened once.


def test_scope_where_unscoped_matches_list_jobs_own_board_count(conn):
    scoped = scope_where(conn, audience=CatalogueAudience.PUBLIC)
    total = conn.execute(f"SELECT COUNT(*) FROM jobs j WHERE {scoped}").fetchone()[0]
    listed = list_jobs(
        conn, JobFilters(), visibility=Visibility.BOARD,
        audience=CatalogueAudience.PUBLIC, page_size=100,
    )
    assert total == listed.total


def test_scope_where_narrows_to_the_query_not_the_whole_scope(conn):
    scoped = scope_where(conn, audience=CatalogueAudience.PUBLIC, query="credit risk")
    ids = {
        r[0] for r in conn.execute(
            f"SELECT source_id FROM jobs j WHERE {scoped}"
        ).fetchall()
    }
    assert ids == {"LIVE"}  # "Credit Risk Analyst" — the only title carrying both words


def test_scope_where_with_an_unmatched_query_excludes_everything(conn):
    # A query the index matches nothing for must scope to nothing, not to
    # everything — the same "empty means match nothing, not no filter" rule
    # `matching_rowids` documents.
    scoped = scope_where(conn, audience=CatalogueAudience.PUBLIC, query="zzznonexistent")
    total = conn.execute(f"SELECT COUNT(*) FROM jobs j WHERE {scoped}").fetchone()[0]
    assert total == 0


# ── Cross-post seniority consensus (jobs.grp_seniority) ────────────────────
# JobStore.refresh_seniority_consensus (hk_jobs/storage.py) resolves a real
# disagreement across a cross-posted vacancy's copies — see
# tests/test_seniority_consensus.py for the voting logic itself. These check
# only that the READ path (SELECT, filter, facets) actually prefers
# grp_seniority over the primary row's own possibly-outvoted e.seniority.

def test_list_jobs_prefers_grp_seniority_over_the_primarys_own_value(tmp_path):
    db = tmp_path / "grp-seniority.db"
    make_jobs_db(
        db,
        jobs=[job(source_id="LIVE", title="Relationship Manager", grp_seniority="senior")],
        enrichments=[enrichment(source_id="LIVE", seniority="mid")],
    )
    connection = prepare(sqlite3.connect(db))
    try:
        # is_admin=True: JobSummary.seniority is admin-gated (job_read.py's
        # _to_summary) — irrelevant to what's under test (the grp_seniority
        # COALESCE), so opted in explicitly to actually see the field.
        role = list_jobs(connection, JobFilters(), page_size=100, is_admin=True).jobs[0]
    finally:
        connection.close()
    assert role.seniority == "senior", (
        "grp_seniority is the resolved cluster consensus — it must win over "
        "this row's own outvoted e.seniority"
    )


def test_list_jobs_falls_back_to_the_rows_own_seniority_when_grp_seniority_is_null(tmp_path):
    db = tmp_path / "grp-seniority-null.db"
    make_jobs_db(
        db,
        jobs=[job(source_id="LIVE", grp_seniority=None)],
        enrichments=[enrichment(source_id="LIVE", seniority="mid")],
    )
    connection = prepare(sqlite3.connect(db))
    try:
        role = list_jobs(connection, JobFilters(), page_size=100, is_admin=True).jobs[0]
    finally:
        connection.close()
    assert role.seniority == "mid"


def test_seniority_filter_matches_on_grp_seniority_not_the_outvoted_own_value(tmp_path):
    """
    THE regression this whole consensus mechanism exists for: a Seeker
    filtering for "senior" must reach a Role whose primary copy's OWN
    e.seniority says "mid" but whose resolved cluster consensus says
    "senior" — otherwise the filter silently drops a genuinely senior Role
    because of which copy happened to win the primary election.
    """
    db = tmp_path / "grp-seniority-filter.db"
    make_jobs_db(
        db,
        jobs=[job(source_id="LIVE", title="Relationship Manager", grp_seniority="senior")],
        enrichments=[enrichment(source_id="LIVE", seniority="mid")],
    )
    connection = prepare(sqlite3.connect(db))
    try:
        senior_hits = list_jobs(
            connection, JobFilters.of(seniority=["senior"]), page_size=100
        ).jobs
        mid_hits = list_jobs(
            connection, JobFilters.of(seniority=["mid"]), page_size=100
        ).jobs
    finally:
        connection.close()
    assert _ids(senior_hits) == ["LIVE"]
    assert _ids(mid_hits) == []


def test_research_facets_seniority_levels_reflect_grp_seniority(tmp_path):
    db = tmp_path / "grp-seniority-facets.db"
    make_jobs_db(
        db,
        jobs=[job(source_id="LIVE", title="Relationship Manager", grp_seniority="senior")],
        enrichments=[enrichment(source_id="LIVE", seniority="mid")],
    )
    connection = prepare(sqlite3.connect(db))
    try:
        facets = research_facets(connection, "relationship manager")
    finally:
        connection.close()
    assert facets.seniority_levels == ["senior"]


# ── Visibility: browsing is filtered ──────────────────────────────────────────

def test_board_hides_closed_and_non_primary(conn):
    ids = _ids(list_jobs(conn, JobFilters(), page_size=100).jobs)
    assert ids == ["LIVE", "XPOST"]


def test_board_is_the_default(conn):
    """A caller that says nothing must get the safe rule, not the permissive one."""
    default = list_jobs(conn, JobFilters(), page_size=100)
    explicit = list_jobs(conn, JobFilters(), page_size=100, visibility=Visibility.BOARD)
    assert _ids(default.jobs) == _ids(explicit.jobs)


def test_addressable_listing_sees_everything(conn):
    ids = _ids(list_jobs(conn, JobFilters(), page_size=100,
                         visibility=Visibility.ADDRESSABLE).jobs)
    assert set(ids) == {"LIVE", "CLOSED", "SECONDARY", "XPOST", "XPOST_HIDDEN"}


def test_board_hides_roles_posted_more_than_one_calendar_month_ago(tmp_path):
    """ADR 0033 reverted ADR 0032's six-month board window back to one month —
    a Role past it is still reachable by reference, never hard-deleted."""
    db = tmp_path / "posting-age.db"
    clock = sqlite3.connect(":memory:")
    boundary, stale, fresh = clock.execute(
        "SELECT date('now', '-1 month'), date('now', '-1 month', '-1 day'), "
        "date('now', '-7 days')"
    ).fetchone()
    clock.close()
    make_jobs_db(
        db,
        jobs=[
            job(source_id="BOUNDARY", posted_at=boundary),
            job(source_id="STALE", posted_at=stale),
            job(source_id="FRESH", posted_at=fresh),
        ],
    )
    connection = prepare(sqlite3.connect(db))
    try:
        board_ids = _ids(list_jobs(connection, JobFilters(), page_size=100).jobs)
        addressed_ids = _ids(
            list_jobs(
                connection,
                JobFilters(),
                page_size=100,
                visibility=Visibility.ADDRESSABLE,
            ).jobs
        )
    finally:
        connection.close()

    assert set(board_ids) == {"BOUNDARY", "FRESH"}
    assert set(addressed_ids) == {"BOUNDARY", "STALE", "FRESH"}


def _company_cap_db(tmp_path):
    """One mega-poster with more Roles than BOARD_COMPANY_CAP, plus a small
    employer well under it — all open and inside the 1-month window (minutes
    apart, so >60 for one employer still fit)."""
    from datetime import datetime, timedelta, timezone

    from hk_jobs.board_visibility import BOARD_COMPANY_CAP

    now = datetime.now(timezone.utc)

    def ago(m: int) -> str:
        return (now - timedelta(minutes=m)).isoformat()

    db = tmp_path / "company-cap.db"
    rows = []
    for i in range(BOARD_COMPANY_CAP + 5):  # 5 over the cap; BIG000 newest
        rows.append(job(source="jobsdb", source_id=f"BIG{i:03d}", company="Bank of China (HK)",
                        company_slug="bochk", title=f"Analyst {i}", posted_at=ago(i + 1)))
    for i in range(3):
        rows.append(job(source="jobsdb", source_id=f"SMALL{i:02d}", company="Tiny Boutique",
                        company_slug="tiny-boutique", title=f"Associate {i}", posted_at=ago(i + 1)))
    make_jobs_db(db, jobs=rows)
    return db, BOARD_COMPANY_CAP


def test_board_caps_each_employer_newest_first_but_leaves_small_employers_whole(tmp_path):
    """ADR 0035: an employer shows at most BOARD_COMPANY_CAP Roles on the board,
    the freshest ones; the capped-out Roles stay open and addressable."""
    db, cap = _company_cap_db(tmp_path)
    connection = prepare(sqlite3.connect(db))
    try:
        board_ids = _ids(list_jobs(connection, JobFilters(), page_size=500).jobs)
        addressed_ids = _ids(list_jobs(connection, JobFilters(), page_size=500,
                                       visibility=Visibility.ADDRESSABLE).jobs)
    finally:
        connection.close()

    big_on_board = sorted(i for i in board_ids if i.startswith("BIG"))
    # days_ago(i+1): BIG000 is newest. Exactly the freshest `cap` survive.
    assert big_on_board == [f"BIG{i:03d}" for i in range(cap)]
    assert sum(i.startswith("SMALL") for i in board_ids) == 3
    # The 5 capped-out Roles are still open, just off the browse board.
    dropped = {f"BIG{i:03d}" for i in range(cap, cap + 5)}
    assert dropped.isdisjoint(board_ids)
    assert dropped <= set(addressed_ids)


def test_board_total_reflects_the_company_cap(tmp_path):
    """Every board-side count derives from BOARD_WHERE, so `total` drops with it."""
    db, cap = _company_cap_db(tmp_path)
    connection = prepare(sqlite3.connect(db))
    try:
        res = list_jobs(connection, JobFilters(), page_size=10)
    finally:
        connection.close()
    assert res.total == cap + 3  # capped mega-poster + the 3 uncapped


def test_board_hides_admin_hidden_roles_but_keeps_them_addressable(tmp_path):
    """ADR 0032: the Hidden state removes a Role from the board without closing
    it — still reachable by reference, still `is_active`."""
    db = tmp_path / "hidden.db"
    make_jobs_db(
        db,
        jobs=[
            job(source_id="SHOWN", posted_at=days_ago(2)),
            job(source_id="HIDDEN", posted_at=days_ago(1), admin_hidden=1),
        ],
    )
    connection = prepare(sqlite3.connect(db))
    try:
        board_ids = _ids(list_jobs(connection, JobFilters(), page_size=100).jobs)
        addressed_ids = _ids(
            list_jobs(
                connection, JobFilters(), page_size=100,
                visibility=Visibility.ADDRESSABLE,
            ).jobs
        )
    finally:
        connection.close()

    assert board_ids == ["SHOWN"]
    assert set(addressed_ids) == {"SHOWN", "HIDDEN"}


def _hidden_db(tmp_path):
    db = tmp_path / "admin-hidden.db"
    make_jobs_db(
        db,
        jobs=[
            job(source_id="SHOWN1", posted_at=days_ago(2)),
            job(source_id="SHOWN2", posted_at=days_ago(3)),
            job(source_id="HIDDEN1", posted_at=days_ago(1), admin_hidden=1),
        ],
    )
    return prepare(sqlite3.connect(db))


def test_admin_hidden_default_excludes_hidden_roles(tmp_path):
    """ADR 0032: with no admin_hidden filter (the public board, and a normal
    admin), a hidden Role is not in the list."""
    conn = _hidden_db(tmp_path)
    try:
        ids = _ids(list_jobs(conn, JobFilters(), page_size=100).jobs)
    finally:
        conn.close()
    assert set(ids) == {"SHOWN1", "SHOWN2"}


def test_admin_hidden_include_ranks_hidden_into_the_board(tmp_path):
    conn = _hidden_db(tmp_path)
    try:
        res = list_jobs(conn, JobFilters(admin_hidden="include"), page_size=100, is_admin=True)
    finally:
        conn.close()
    by_id = {s.source_id: s for s in res.jobs}
    assert set(by_id) == {"SHOWN1", "SHOWN2", "HIDDEN1"}
    assert by_id["HIDDEN1"].admin_hidden is True
    assert by_id["SHOWN1"].admin_hidden is False


def test_admin_hidden_only_returns_just_the_hidden_roles(tmp_path):
    conn = _hidden_db(tmp_path)
    try:
        ids = _ids(list_jobs(conn, JobFilters(admin_hidden="only"), page_size=100, is_admin=True).jobs)
    finally:
        conn.close()
    assert ids == ["HIDDEN1"]


def test_admin_hidden_flag_is_not_leaked_to_a_non_admin_read(tmp_path):
    """`admin_hidden` on the summary is gated on is_admin, same as the salary
    estimate — a public read never carries it even if the column says 1."""
    conn = _hidden_db(tmp_path)
    try:
        # is_admin defaults False; "only" would be refused at the route, but even
        # if it reached here the summary must not expose the bit.
        res = list_jobs(conn, JobFilters(admin_hidden="only"), page_size=100)
    finally:
        conn.close()
    assert all(s.admin_hidden is False for s in res.jobs)


# ── Visibility: addressing is not ─────────────────────────────────────────────

def test_get_job_reaches_a_closed_role(conn):
    """The behaviour a Saved Role depends on: the Role is still readable after it
    closes, which is why the row is soft-deleted rather than removed."""
    detail = get_job(conn, *CLOSED)
    assert detail is not None
    assert detail.closed is True
    assert detail.title == "Closed Role"


def test_get_job_reaches_a_non_primary_copy(conn):
    """A deep link names one specific copy. Requiring is_primary would 404 a link
    whose copy stopped being primary at the last reconciliation."""
    assert get_job(conn, *SECONDARY) is not None


def test_get_job_returns_none_rather_than_raising(conn):
    """This module does not know what a 404 is."""
    assert get_job(conn, *ABSENT) is None


def test_get_job_under_board_visibility_hides_a_closed_role(conn):
    """The rule is a parameter, so the caller can still ask for the strict one."""
    assert get_job(conn, *CLOSED, visibility=Visibility.BOARD) is None


@pytest.mark.parametrize(
    ("description", "salary_max", "expected_period"),
    [
        ("Salary up to HK$30K.", 30_000, "month"),
        ("Salary HKD720000 per annum.", 720_000, "year"),
        ("Monthly salary HK$240,000.", 240_000, "month"),
        ("Annual salary HK$180,000.", 180_000, "year"),
    ],
)
def test_disclosed_salary_period_uses_source_evidence_then_hk_market_default(
    tmp_path, description, salary_max, expected_period
):
    db = tmp_path / "salary-period.db"
    make_jobs_db(
        db,
        jobs=[
            job(
                source="linkedin_posts",
                source_id="SALARY",
                source_tier="social",
                description_clean=description,
            )
        ],
        enrichments=[
            enrichment(
                source="linkedin_posts",
                source_id="SALARY",
                salary_hkd_max=salary_max,
                description_summary=description,
            )
        ],
    )
    connection = prepare(sqlite3.connect(db))
    try:
        detail = get_job(connection, "linkedin_posts", "SALARY")
    finally:
        connection.close()

    assert detail is not None
    assert detail.salary_period == expected_period


# ── closed ────────────────────────────────────────────────────────────────────

def test_closed_is_true_exactly_when_the_row_is_inactive(conn):
    got = {j.source_id: j.closed
           for j in list_jobs(conn, JobFilters(), page_size=100,
                              visibility=Visibility.ADDRESSABLE).jobs}
    assert got["CLOSED"] is True
    assert got["LIVE"] is False
    assert got["SECONDARY"] is False


def test_the_board_never_returns_a_closed_role(conn):
    assert all(not j.closed for j in list_jobs(conn, JobFilters(), page_size=100).jobs)


# ── Count and rows agree ──────────────────────────────────────────────────────

def test_total_counts_the_rows_it_returns(conn):
    page = list_jobs(conn, JobFilters(), page_size=100)
    assert page.total == len(page.jobs)


def test_total_survives_a_filter(conn):
    page = list_jobs(conn, JobFilters(companies=("HSBC",)), page_size=100)
    assert page.total == len(page.jobs) == 1


def test_total_is_not_affected_by_paging(conn):
    first = list_jobs(conn, JobFilters(), page=1, page_size=1)
    assert first.total == 2 and len(first.jobs) == 1 and first.total_pages == 2


# ── Saved Roles ───────────────────────────────────────────────────────────────

def test_refs_keep_the_callers_order(conn):
    """seekers.db returns newest-saved-first; the database's order is irrelevant."""
    assert _ids(jobs_by_refs(conn, [CLOSED, LIVE])) == ["CLOSED", "LIVE"]
    assert _ids(jobs_by_refs(conn, [LIVE, CLOSED])) == ["LIVE", "CLOSED"]


def test_a_closed_ref_comes_back_marked_not_hidden(conn):
    """The whole reason Saved Roles beat a localStorage snapshot."""
    saved = jobs_by_refs(conn, [CLOSED])
    assert [j.source_id for j in saved] == ["CLOSED"]
    assert saved[0].closed is True


def test_an_absent_ref_is_dropped_not_an_error(conn):
    """A row that has left jobs.db entirely leaves nothing to render."""
    assert _ids(jobs_by_refs(conn, [LIVE, ABSENT])) == ["LIVE"]


def test_no_refs_is_no_query(conn):
    assert jobs_by_refs(conn, []) == []


# ── Vacancy-id sibling fallback (ADR 0030) ──────────────────────────────────────
# A Saved Role references (source, source_id) of whichever copy was primary
# when saved. reconcile_cross_posted recomputes is_primary from scratch every
# run, so that exact copy can close while the same real vacancy stays open
# under a sibling source sharing its vacancy_id — the fallback this section
# specifies exists so the Seeker is not wrongly told the role has closed.


@pytest.fixture()
def vacancy_conn(tmp_path) -> sqlite3.Connection:
    db = tmp_path / "vacancy.db"
    make_jobs_db(
        db,
        jobs=[
            # The exact copy a Seeker saved: was primary, has since closed.
            job(source="jobsdb", source_id="WAS_PRIMARY", company="DBS",
                title="Shared Role", posted_at="2026-04-01", is_active=0,
                is_primary=0, cross_posted=1, vacancy_id="V1"),
            # Its sibling: same vacancy_id, still open.
            job(source="indeed", source_id="STILL_OPEN", company="DBS",
                title="Shared Role", posted_at="2026-04-01", is_active=1,
                is_primary=1, cross_posted=1, vacancy_id="V1"),
            # A closed role that was never cross-posted — no sibling to fall
            # back to, must behave exactly as before this feature existed.
            job(source="workday", source_id="NEVER_CROSSPOSTED", company="HSBC",
                title="Solo Role", posted_at="2026-03-01", is_active=0,
                vacancy_id=None),
            # A closed role whose sibling is ALSO closed — no active sibling
            # exists, so it must stay reported as closed too.
            job(source="jobsdb", source_id="BOTH_CLOSED_A", company="AIA",
                title="Dead Role", posted_at="2026-02-01", is_active=0,
                cross_posted=1, vacancy_id="V2"),
            job(source="indeed", source_id="BOTH_CLOSED_B", company="AIA",
                title="Dead Role", posted_at="2026-02-01", is_active=0,
                cross_posted=1, vacancy_id="V2"),
        ],
    )
    c = prepare(sqlite3.connect(db))
    yield c
    c.close()


def test_saved_role_resolves_to_an_active_sibling_when_its_copy_closes(vacancy_conn):
    got = jobs_by_refs(vacancy_conn, [("jobsdb", "WAS_PRIMARY")])
    assert len(got) == 1
    assert got[0].closed is False
    assert got[0].source_id == "STILL_OPEN"  # resolved to the sibling, not the closed copy


def test_saved_role_with_no_vacancy_id_behaves_exactly_as_before(vacancy_conn):
    """No sibling to fall back to — the pre-existing 'closed, not hidden' behavior."""
    got = jobs_by_refs(vacancy_conn, [("workday", "NEVER_CROSSPOSTED")])
    assert len(got) == 1
    assert got[0].source_id == "NEVER_CROSSPOSTED"
    assert got[0].closed is True


def test_saved_role_stays_closed_when_its_sibling_is_also_closed(vacancy_conn):
    got = jobs_by_refs(vacancy_conn, [("jobsdb", "BOTH_CLOSED_A")])
    assert len(got) == 1
    assert got[0].source_id == "BOTH_CLOSED_A"
    assert got[0].closed is True


def test_vacancy_fallback_also_applies_to_saved_roles(vacancy_conn):
    """saved_roles shares _by_refs with jobs_by_refs — same fallback, same result."""
    from job_read import saved_roles
    got = saved_roles(vacancy_conn, [("jobsdb", "WAS_PRIMARY")])
    assert len(got) == 1
    assert got[0].closed is False
    assert got[0].source_id == "STILL_OPEN"


def test_refs_beyond_sqlites_expression_limit(conn):
    """
    The failure this pins: an OR-chain of ~1000 (source, source_id) pairs exceeds
    SQLite's expression-tree depth limit, so a Seeker with enough Saved Roles got
    a 500 on every read — and could not unsave their way out, because the list is
    what crashed. Chunking makes the ref count irrelevant.
    """
    refs = [("ghost", f"G{i}") for i in range(1200)] + [LIVE]
    assert _ids(jobs_by_refs(conn, refs)) == ["LIVE"]


# ── Cross-post signals ────────────────────────────────────────────────────────

def test_a_card_collects_signals_from_copies_the_board_hides(conn):
    card = next(j for j in list_jobs(conn, JobFilters(), page_size=100).jobs
                if j.source_id == "XPOST")
    assert card.board_signals == {
        "jobsdb": {"applicant_count": 3},
        "indeed": {"urgently_hiring": True},
    }


def test_saved_roles_get_group_signals_too(conn):
    """Same vacancy, same signals, whichever door you came in through."""
    saved = jobs_by_refs(conn, [("jobsdb", "XPOST")])
    assert set(saved[0].board_signals) == {"jobsdb", "indeed"}


def test_detail_lists_every_board_the_role_is_on(conn):
    assert sorted(get_job(conn, "jobsdb", "XPOST").sources) == ["indeed", "jobsdb"]


# ── Sectors ───────────────────────────────────────────────────────────────────

def test_banking_is_defined_as_none_of_the_others(conn):
    """
    Banking is the fallthrough bucket, so filtering for it negates every other
    sector. Derived from the same table the CASE is built from — the old
    hand-written negation had to be updated whenever a sector was added, and
    forgetting it made Banking silently double-count.
    """
    banking = list_jobs(conn, JobFilters(sectors=("Banking",)), page_size=100)
    assert set(_ids(banking.jobs)) == {"LIVE", "XPOST"}
    assert all(j.sector == "Banking" for j in banking.jobs)


def test_a_named_sector_selects_only_itself(conn):
    assert list_jobs(conn, JobFilters(sectors=("Insurance",)), page_size=100).total == 0


# ── Sort ──────────────────────────────────────────────────────────────────────

def test_sort_is_an_enum_so_a_typo_cannot_silently_mean_newest(conn):
    with pytest.raises(ValueError):
        Sort("salaray_high")


def test_salary_sort_sinks_rows_with_no_salary(conn):
    ids = _ids(list_jobs(conn, JobFilters(), sort=Sort.SALARY_HIGH, page_size=100).jobs)
    assert ids == ["LIVE", "XPOST"]


# ── Recruiter Posts boost ─────────────────────────────────────────────────────


@pytest.fixture()
def boost_conn(tmp_path) -> sqlite3.Connection:
    """9 mainstream rows newer than 3 Recruiter Posts — plain NEWEST would sink
    every Recruiter Post to the bottom of the list."""
    db = tmp_path / "boost.db"
    mainstream = [
        job(source="jobsdb", source_id=f"M{i}", company="HSBC",
            title=f"Role M{i}", posted_at=days_ago(i))
        for i in range(1, 10)
    ]
    social = [
        job(source="linkedin_posts", source_id=f"S{i}", company="Recruiter",
            title=f"Role S{i}", source_tier="social", posted_at=days_ago(15 + i))
        for i in range(1, 4)
    ]
    make_jobs_db(db, jobs=mainstream + social)
    c = prepare(sqlite3.connect(db))
    yield c
    c.close()


def test_boost_off_by_default_is_plain_newest(boost_conn):
    """No caller asked for the boost, so a Recruiter Post ranks purely on its
    own posted_at, same as before this feature existed."""
    ids = _ids(list_jobs(
        boost_conn, JobFilters(), sort=Sort.NEWEST, page_size=100,
        audience=CatalogueAudience.MEMBER,
    ).jobs)
    assert ids == ["M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9", "S1", "S2", "S3"]


def test_boost_interleaves_recruiter_posts_at_a_fixed_cadence(boost_conn):
    """One slot in every 4 goes to the next Recruiter Post (by the caller's own
    sort); the other slots keep the mainstream rows in their own newest-first
    order. Not pinned to the very top, not randomly mixed."""
    ids = _ids(list_jobs(
        boost_conn, JobFilters(), sort=Sort.NEWEST, page_size=100,
        audience=CatalogueAudience.MEMBER, boost_recruiter_posts=True,
    ).jobs)
    assert ids == [
        "M1", "M2", "S1", "M3", "M4", "M5", "S2", "M6", "M7", "M8", "S3", "M9",
    ]


def test_boost_does_not_change_the_total(boost_conn):
    plain = list_jobs(boost_conn, JobFilters(), page_size=100, audience=CatalogueAudience.MEMBER)
    boosted = list_jobs(
        boost_conn, JobFilters(), page_size=100,
        audience=CatalogueAudience.MEMBER, boost_recruiter_posts=True,
    )
    assert boosted.total == plain.total == 12
    assert {j.source_id for j in boosted.jobs} == {j.source_id for j in plain.jobs}


def test_boost_is_a_noop_when_only_one_tier_is_present(boost_conn):
    """Filtering down to a single tier (a tier tab, or a PUBLIC audience that
    excludes 'social' entirely) leaves nothing to interleave, so the boosted
    order must equal the plain order exactly."""
    filters = JobFilters(tier="mainstream")
    plain = _ids(list_jobs(boost_conn, filters, page_size=100,
                            audience=CatalogueAudience.MEMBER).jobs)
    boosted = _ids(list_jobs(boost_conn, filters, page_size=100,
                              audience=CatalogueAudience.MEMBER,
                              boost_recruiter_posts=True).jobs)
    assert boosted == plain == ["M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9"]


def test_boost_paginates_without_gaps_or_duplicates(boost_conn):
    """The boosted order is a real total order over every matching row, so
    paging through it must behave exactly like paging any other order."""
    page1 = list_jobs(boost_conn, JobFilters(), page=1, page_size=5,
                       audience=CatalogueAudience.MEMBER, boost_recruiter_posts=True)
    page2 = list_jobs(boost_conn, JobFilters(), page=2, page_size=5,
                       audience=CatalogueAudience.MEMBER, boost_recruiter_posts=True)
    page3 = list_jobs(boost_conn, JobFilters(), page=3, page_size=5,
                       audience=CatalogueAudience.MEMBER, boost_recruiter_posts=True)
    seen = _ids(page1.jobs) + _ids(page2.jobs) + _ids(page3.jobs)
    assert len(seen) == len(set(seen)) == 12


# ── A recruiter is not an employer ────────────────────────────────────────────
# `company` on a social-tier row never holds an employer a Seeker could filter a
# board by. It holds either "Confidential via {recruiter}" — the RECRUITER's own
# name — or a name the LLM extracted from post prose, which on the live board has
# included outright sentence fragments ("business leaders to", lifted from
# "Partner with business leaders to forecast talent needs"). Both are category
# errors in the employer dimension, so the whole tier stays out of it.


@pytest.fixture()
def employer_conn(tmp_path) -> sqlite3.Connection:
    """One real employer, plus recruiter posts of all three shapes the live board
    actually contains: a "Confidential via …" recruiter name, an LLM-extracted
    sentence fragment, and an extracted name that COLLIDES with a real employer."""
    db = tmp_path / "employer.db"
    make_jobs_db(
        db,
        jobs=[
            job(source="workday", source_id="REAL", company="HSBC",
                title="Credit Analyst finexscope", posted_at=days_ago(1)),
            job(source="linkedin_posts", source_id="CONF", source_tier="social",
                company="Confidential via Janice Wong",
                title="Credit Analyst finexscope", posted_at=days_ago(2)),
            job(source="linkedin_posts", source_id="FRAGMENT", source_tier="social",
                company="business leaders to",
                title="Credit Analyst finexscope", posted_at=days_ago(3)),
            job(source="linkedin_posts", source_id="COLLIDES", source_tier="social",
                company="HSBC",
                title="Credit Analyst finexscope", posted_at=days_ago(4)),
        ],
    )
    c = prepare(sqlite3.connect(db))
    yield c
    c.close()


def test_a_recruiter_is_never_offered_as_an_employer(employer_conn):
    """The employer facet is a list of EMPLOYERS. A recruiter's name in it invites
    a Seeker to filter the board by a person who does not employ anyone."""
    facets = research_facets(employer_conn, "finexscope",
                             audience=CatalogueAudience.MEMBER)
    names = [c.name for c in facets.companies]
    assert not any(n.startswith("Confidential via") for n in names)
    assert "business leaders to" not in names


def test_the_employer_facet_holds_only_real_employers(employer_conn):
    """Three of the four rows are recruiter posts, so exactly one employer is on
    offer — and its count is 1, not 2, because the colliding post is not an HSBC
    vacancy just because the model wrote "HSBC"."""
    facets = research_facets(employer_conn, "finexscope",
                             audience=CatalogueAudience.MEMBER)
    assert [(c.name, c.count) for c in facets.companies] == [("HSBC", 1)]


def test_a_company_filter_never_returns_a_recruiter_post(employer_conn):
    """The rule, stated directly: no company filter, for any audience, by any
    name, may hand back a recruiter's post."""
    for name in ("Confidential via Janice Wong", "business leaders to", "HSBC"):
        page = list_jobs(employer_conn, JobFilters(companies=(name,)), page_size=100,
                         audience=CatalogueAudience.MEMBER)
        assert all(j.source != "linkedin_posts" for j in page.jobs), name


def test_a_company_filter_on_a_real_employer_returns_only_its_own_role(employer_conn):
    """Filtering HSBC must reach the Workday vacancy and NOT the recruiter post
    whose employer name the LLM guessed as "HSBC"."""
    page = list_jobs(employer_conn, JobFilters(companies=("HSBC",)), page_size=100,
                     audience=CatalogueAudience.MEMBER)
    assert _ids(page.jobs) == ["REAL"]
    assert page.total == 1


def test_recruiter_posts_stay_reachable_outside_the_employer_dimension(employer_conn):
    """Leaving the employer dimension is not leaving the board. The Secret Market
    is a member benefit; only the company filter and facet stop carrying it."""
    everything = list_jobs(employer_conn, JobFilters(), page_size=100,
                           audience=CatalogueAudience.MEMBER)
    assert set(_ids(everything.jobs)) == {"REAL", "CONF", "FRAGMENT", "COLLIDES"}

    social = list_jobs(employer_conn, JobFilters(tier="social"), page_size=100,
                       audience=CatalogueAudience.MEMBER)
    assert set(_ids(social.jobs)) == {"CONF", "FRAGMENT", "COLLIDES"}


# ── The employer's own words are not ours to republish ────────────────────────
# `description_clean` is the employer's job description, stored verbatim. It is
# kept so features can be re-extracted without re-scraping (see storage.py), and
# reading it server-side — salary-period evidence, search indexing, admin editing
# — is exactly what it is for.
#
# Publishing it is not. main.py's SEO block already states the rule for its own
# surface: "a short AI summary — never `description_clean`". The Seeker-facing
# routes never followed it. `description_excerpt` was the first 200 characters of
# the employer's text on every row of every list response, anonymous included,
# and `JobDetail.description_clean` shipped the whole thing; the detail panel then
# rendered it whenever the AI summary was missing, which on the live board was 539
# Roles averaging ~3,600 characters each.
#
# So the AI summary is now the ONLY description that leaves the API.

@pytest.fixture()
def description_conn(tmp_path) -> sqlite3.Connection:
    """Two Roles with a full employer description: one summarised, one not."""
    db = tmp_path / "descriptions.db"
    make_jobs_db(
        db,
        jobs=[
            job(source="workday", source_id="SUMMARISED", company="HKEX",
                title="IAM Analyst finexscope", posted_at=days_ago(2),
                description_clean="Company Introduction: We're home to Asia's most "
                                  "dynamic and vibrant capital markets. Connecting "
                                  "capital, ideas, inspiration and innovation."),
            job(source="workday", source_id="BARE", company="FWD Insurance",
                title="MI Planning Manager finexscope", posted_at=days_ago(1),
                description_clean="KEY ACCOUNTABILITIES Develop and execute "
                                  "Management Information, Planning & Analysis "
                                  "strategy and policies for FWD Malaysia."),
        ],
        enrichments=[
            enrichment(source="workday", source_id="SUMMARISED",
                       description_summary="An identity and access management role "
                                           "at a Hong Kong market operator."),
        ],
    )
    c = prepare(sqlite3.connect(db))
    yield c
    c.close()


def _by_id(page, source_id):
    return next(j for j in page.jobs if j.source_id == source_id)


def test_the_list_excerpt_is_never_the_employers_own_text(description_conn):
    """The widest exposure: this excerpt was on every row of every list response,
    including for anonymous visitors."""
    page = list_jobs(description_conn, JobFilters(), page_size=100)
    for j in page.jobs:
        assert "Company Introduction" not in j.description_excerpt
        assert "KEY ACCOUNTABILITIES" not in j.description_excerpt


def test_the_list_excerpt_comes_from_the_ai_summary(description_conn):
    page = list_jobs(description_conn, JobFilters(), page_size=100)
    assert _by_id(page, "SUMMARISED").description_excerpt.startswith(
        "An identity and access management role")


def test_a_role_with_no_summary_gets_an_empty_excerpt_not_the_source(description_conn):
    """Nothing to say is said by saying nothing. The Role still lists."""
    page = list_jobs(description_conn, JobFilters(), page_size=100)
    assert _by_id(page, "BARE").description_excerpt == ""
    assert {j.source_id for j in page.jobs} == {"SUMMARISED", "BARE"}


def test_the_detail_payload_does_not_carry_the_employers_full_text(description_conn):
    """Removing it from the render is not enough — it was in the JSON, so it was
    published whether or not anything drew it on screen."""
    detail = get_job(description_conn, "workday", "BARE")
    assert detail is not None
    assert not hasattr(detail, "description_clean")
    assert "KEY ACCOUNTABILITIES" not in detail.model_dump_json()


def test_the_detail_payload_still_carries_the_summary(description_conn):
    detail = get_job(description_conn, "workday", "SUMMARISED")
    assert detail is not None
    assert detail.description_summary.startswith("An identity and access management")


def test_reading_the_employers_text_server_side_still_works(tmp_path):
    """The point is that it stops being PUBLISHED, not that it stops being used.
    salary_period infers month-vs-year from the employer's own wording."""
    db = tmp_path / "salary.db"
    make_jobs_db(
        db,
        jobs=[job(source="workday", source_id="PAID",
                  description_clean="Salary HKD720000 per annum.")],
        enrichments=[enrichment(source="workday", source_id="PAID",
                                salary_hkd_max=720_000)],
    )
    conn = prepare(sqlite3.connect(db))
    try:
        detail = get_job(conn, "workday", "PAID")
        assert detail is not None
        assert detail.salary_period == "year"      # read from description_clean
        assert "per annum" not in detail.model_dump_json()   # but not published
    finally:
        conn.close()


# ── annual figures must not outrank monthly ones ──────────────────────────────
# Found live 2026-08-19: 31 of ~4,180 board rows carry a salary the employer quoted
# PER YEAR. `_salary_period` already infers that correctly for display, but the sort
# and filter expressions read the raw column, so a role quoted at HK$10,000,000/year
# ranked above every monthly-paid job and topped "Highest salary".


@pytest.fixture()
def periods(tmp_path) -> sqlite3.Connection:
    """Three rows: one annual, one monthly, one estimate-only."""
    db = tmp_path / "periods.db"
    make_jobs_db(
        db,
        jobs=[
            job(source="workday", source_id="ANNUAL", title="Director, Legal Counsel"),
            job(source="workday", source_id="MONTHLY", title="Head of Cash Operations"),
            job(source="workday", source_id="ESTIMATE", title="Credit Analyst"),
        ],
        enrichments=[
            # HK$1.65M a YEAR = HK$137,500 a month. Below the monthly row.
            enrichment(source="workday", source_id="ANNUAL",
                       salary_hkd_min=1_400_000, salary_hkd_max=1_650_000),
            enrichment(source="workday", source_id="MONTHLY",
                       salary_hkd_min=150_000, salary_hkd_max=180_000),
            enrichment(source="workday", source_id="ESTIMATE",
                       salary_estimated_min=30_000, salary_estimated_max=45_000),
        ],
    )
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    return prepare(conn)


def test_an_annual_salary_does_not_outrank_a_higher_monthly_one(periods):
    ids = _ids(list_jobs(periods, JobFilters(), sort=Sort.SALARY_HIGH, page_size=10).jobs)
    assert ids.index("MONTHLY") < ids.index("ANNUAL"), (
        "HK$180,000/month outranks HK$1.65M/year (HK$137,500/month) — the raw "
        "annual figure must not be compared against monthly ones"
    )


def test_salary_low_sort_also_normalises_the_period(periods):
    ids = _ids(list_jobs(periods, JobFilters(), sort=Sort.SALARY_LOW, page_size=10).jobs)
    assert ids.index("ESTIMATE") < ids.index("ANNUAL") < ids.index("MONTHLY")


def test_the_salary_filter_reads_an_annual_figure_as_monthly(periods):
    """A seeker filtering "up to HK$140,000" should see the HK$137,500/month role."""
    found = _ids(list_jobs(periods, JobFilters(salary_max=140_000), page_size=10).jobs)
    assert "ANNUAL" in found, "HK$1.65M/year is HK$137,500/month and is under the cap"
    assert "MONTHLY" not in found, "HK$180,000/month is over the cap"


def test_a_monthly_figure_is_left_alone_by_the_filter(periods):
    found = _ids(list_jobs(periods, JobFilters(salary_min=150_000), page_size=10).jobs)
    assert found == ["MONTHLY"]
