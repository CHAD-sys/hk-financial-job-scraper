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
from pathlib import Path

import pytest

from .support import BACKEND, enrichment, job, make_jobs_db, signals

sys.path.insert(0, str(BACKEND))

from job_read import (  # noqa: E402
    CatalogueAudience,
    JobFilters,
    Sort,
    Visibility,
    get_job,
    jobs_by_refs,
    list_jobs,
    prepare,
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
                title="Credit Risk Analyst", posted_at="2026-07-01"),
            job(source="workday", source_id="CLOSED", company="HSBC",
                title="Closed Role", posted_at="2026-06-01", is_active=0),
            job(source="workday", source_id="SECONDARY", company="HSBC",
                title="Secondary Copy", posted_at="2026-05-01", is_primary=0),
            job(source="jobsdb", source_id="XPOST", company="DBS",
                title="Shared Role", posted_at="2026-04-01",
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
            title=f"Role M{i}", posted_at=f"2026-07-{10 - i:02d}")
        for i in range(1, 10)
    ]
    social = [
        job(source="linkedin_posts", source_id=f"S{i}", company="Recruiter",
            title=f"Role S{i}", source_tier="social", posted_at=f"2026-06-{4 - i:02d}")
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
