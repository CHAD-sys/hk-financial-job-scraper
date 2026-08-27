"""
Tests for Phase 19 cross-source apply routing:
  - JobStore.reconcile_cross_posted()   (apply_url + cross_posted)
  - source-scoped JobStore.mark_inactive_for_run()

A job on two sources shares a dedup_hash (company_slug | title | first-location),
which is how "the same vacancy on two boards" is detected.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from hk_jobs.schema import Job
from hk_jobs.storage import JobStore


def _job(source: str, source_id: str, *, slug="man-group-hk", title="Quant Researcher",
         loc="Hong Kong", url=None, company="Man Group", **overrides) -> Job:
    overrides.setdefault("fetched_at", datetime.now(UTC))
    return Job(
        source=source,
        source_id=source_id,
        company=company,
        company_slug=slug,
        url=url or f"https://{source}.example/{source_id}",
        title=title,
        locations=[loc],
        **overrides,
    )


@pytest.fixture
def store(tmp_path: Path):
    s = JobStore(str(tmp_path / "x.db"))
    yield s
    s.close()


def test_same_vacancy_two_sources_shares_dedup_hash():
    a = _job("jobsdb", "1")
    b = _job("efinancialcareers", "2")
    assert a.dedup_hash() == b.dedup_hash()


def test_reconcile_prefers_efc_apply_url(store):
    jobsdb = _job("jobsdb", "1", url="https://hk.jobsdb.com/job/1")
    efc = _job("efinancialcareers", "2", url="https://efc.hk/jobs-x.id2")
    store.upsert_many([jobsdb, efc])

    groups, rows = store.reconcile_cross_posted()
    assert groups == 1
    assert rows == 2  # both copies updated

    got = {
        r["source"]: (r["apply_url"], r["cross_posted"])
        for r in store._conn.execute("SELECT source, apply_url, cross_posted FROM jobs")
    }
    # Both copies point at the eFC URL and are flagged cross-posted.
    assert got["jobsdb"] == ("https://efc.hk/jobs-x.id2", 1)
    assert got["efinancialcareers"] == ("https://efc.hk/jobs-x.id2", 1)


def test_reconcile_prefers_own_ats_over_efc(store):
    """
    Own-ATS carve-out: when a role is found on the company's own ATS (Workday /
    Eightfold) AND on eFC, the apply link must point at the own ATS — the real
    careers page always wins over any aggregator.
    """
    workday = _job("workday", "1", url="https://aia.wd3.myworkdayjobs.com/job/1")
    efc = _job("efinancialcareers", "2", url="https://efc.hk/jobs-x.id2")
    store.upsert_many([workday, efc])

    store.reconcile_cross_posted()
    got = {
        r["source"]: r["apply_url"]
        for r in store._conn.execute("SELECT source, apply_url FROM jobs")
    }
    assert got["workday"] == "https://aia.wd3.myworkdayjobs.com/job/1"
    assert got["efinancialcareers"] == "https://aia.wd3.myworkdayjobs.com/job/1"


def test_reconcile_prefers_indeed_over_jobsdb(store):
    """Aggregator fallback order: Indeed outranks JobsDB for the apply link."""
    jobsdb = _job("jobsdb", "1", url="https://hk.jobsdb.com/job/1")
    indeed = _job("indeed", "2", url="https://hk.indeed.com/viewjob?jk=2")
    store.upsert_many([jobsdb, indeed])

    store.reconcile_cross_posted()
    got = {
        r["source"]: r["apply_url"]
        for r in store._conn.execute("SELECT source, apply_url FROM jobs")
    }
    assert got["jobsdb"] == "https://hk.indeed.com/viewjob?jk=2"
    assert got["indeed"] == "https://hk.indeed.com/viewjob?jk=2"


def test_reconcile_matches_despite_different_location_strings(store):
    """
    The real case that drove matches to zero: same role, but eFC says "Hong Kong"
    while JobsDB says "Hong Kong SAR". Matching must ignore the location phrasing.
    """
    efc = _job("efinancialcareers", "1",
               title="Assistant Relationship Manager, Business Banking", loc="Hong Kong",
               url="https://efc.hk/x.id1")
    jobsdb = _job("jobsdb", "2",
                  title="Assistant Relationship Manager, Business Banking", loc="Hong Kong SAR")
    # Different dedup_hash (location differs) — reconciliation must still match them.
    assert efc.dedup_hash() != jobsdb.dedup_hash()
    store.upsert_many([efc, jobsdb])

    groups, _ = store.reconcile_cross_posted()
    assert groups == 1
    rows = store._conn.execute("SELECT apply_url, cross_posted FROM jobs").fetchall()
    assert all(r["cross_posted"] == 1 and r["apply_url"] == "https://efc.hk/x.id1" for r in rows)


# ── Named-district guard (ADR 0028, 2026-08-27) ─────────────────────────────────
# A fuzzy-matching title at two DIFFERENT named branches is two real openings,
# not one cross-posted vacancy — the failure mode the "location-independent"
# design above reopened for multi-branch employers.


def test_reconcile_refuses_same_title_at_different_named_districts(store):
    """Same fuzzy title, different named branches: two real openings, not one."""
    central = _job("efinancialcareers", "1", title="Relationship Manager",
                   loc="Central, Hong Kong", url="https://efc.hk/x.id1")
    kwun_tong = _job("jobsdb", "2", title="Relationship Manager",
                     loc="Kwun Tong, Kowloon East, Hong Kong")
    store.upsert_many([central, kwun_tong])

    groups, _ = store.reconcile_cross_posted()
    assert groups == 0
    rows = store._conn.execute("SELECT is_primary FROM jobs").fetchall()
    assert all(r["is_primary"] == 1 for r in rows)  # both stay visible


def test_reconcile_still_matches_same_named_district(store):
    """Sanity check: agreeing on the SAME named district must still merge."""
    a = _job("efinancialcareers", "1", title="Relationship Manager",
             loc="Central, Hong Kong", url="https://efc.hk/x.id1")
    b = _job("jobsdb", "2", title="Relationship Manager", loc="Central, Hong Kong Island")
    store.upsert_many([a, b])
    groups, _ = store.reconcile_cross_posted()
    assert groups == 1


def test_reconcile_matches_when_only_one_side_names_a_district(store):
    """One side generic ('Hong Kong'), the other specific: no signal to refuse on."""
    a = _job("efinancialcareers", "1", title="Relationship Manager",
             loc="Hong Kong", url="https://efc.hk/x.id1")
    b = _job("jobsdb", "2", title="Relationship Manager", loc="Central, Hong Kong")
    store.upsert_many([a, b])
    groups, _ = store.reconcile_cross_posted()
    assert groups == 1


def test_reconcile_matches_despite_punctuation_and_case(store):
    efc = _job("efinancialcareers", "1", title="(Deputy / Senior) Product Manager",
               url="https://efc.hk/x.id1")
    jobsdb = _job("jobsdb", "2", title="Deputy / Senior  Product  Manager")
    store.upsert_many([efc, jobsdb])
    groups, _ = store.reconcile_cross_posted()
    assert groups == 1


def test_fuzzy_matches_reordered_title(store):
    """Different word order / punctuation for the same role still matches."""
    efc = _job("efinancialcareers", "1", title="Product Manager, Global Corporate Banking",
               url="https://efc.hk/x.id1")
    jobsdb = _job("jobsdb", "2", title="Global Corporate Banking - Product Manager")
    store.upsert_many([efc, jobsdb])
    assert store.reconcile_cross_posted()[0] == 1


def test_fuzzy_respects_seniority(store):
    """Fuzzy match must NOT collapse different seniority levels of the same job."""
    senior = _job("efinancialcareers", "1", title="Senior Risk Analyst")
    junior = _job("jobsdb", "2", title="Risk Analyst")
    store.upsert_many([senior, junior])
    groups, _ = store.reconcile_cross_posted()
    assert groups == 0  # different level → distinct roles
    rows = store._conn.execute("SELECT is_primary FROM jobs").fetchall()
    assert all(r["is_primary"] == 1 for r in rows)  # both stay visible


def test_fuzzy_ignores_weak_overlap(store):
    """Titles that merely share one common word are not merged."""
    a = _job("efinancialcareers", "1", title="Compliance Manager")
    b = _job("jobsdb", "2", title="Technology Manager")
    store.upsert_many([a, b])
    assert store.reconcile_cross_posted()[0] == 0


def test_cross_posted_display_prefers_jobsdb_as_primary(store):
    """One card per cross-posted role: JobsDB copy is primary (rich), eFC hidden."""
    efc = _job("efinancialcareers", "1", url="https://efc.hk/x.id1")
    jobsdb = _job("jobsdb", "2", url="https://hk.jobsdb.com/job/2")
    store.upsert_many([efc, jobsdb])
    store.reconcile_cross_posted()
    prim = {
        r["source"]: r["is_primary"]
        for r in store._conn.execute("SELECT source, is_primary FROM jobs")
    }
    assert prim["jobsdb"] == 1          # displayed (has description + enrichment)
    assert prim["efinancialcareers"] == 0  # hidden duplicate


# ── Richness overrides a thin default (ADR 0029, 2026-08-27) ────────────────────


def test_a_thin_jobsdb_copy_loses_primary_to_a_fuller_efc_copy(store):
    """JobsDB usually wins display, but not when THIS JobsDB row is empty."""
    efc = _job("efinancialcareers", "1", url="https://efc.hk/x.id1",
               description_clean="Full role description here.", salary_min=40_000)
    jobsdb = _job("jobsdb", "2", url="https://hk.jobsdb.com/job/2",
                  description_clean="")  # listing-only scrape, no description
    store.upsert_many([efc, jobsdb])
    store.reconcile_cross_posted()
    prim = {
        r["source"]: r["is_primary"]
        for r in store._conn.execute("SELECT source, is_primary FROM jobs")
    }
    assert prim["efinancialcareers"] == 1  # richer copy wins despite lower priority
    assert prim["jobsdb"] == 0


def test_jobsdb_keeps_primary_when_both_copies_are_rich(store):
    """Richness is a tie (both have a description) — DISPLAY_ORDER default stands."""
    efc = _job("efinancialcareers", "1", url="https://efc.hk/x.id1",
               description_clean="Also has a description.")
    jobsdb = _job("jobsdb", "2", url="https://hk.jobsdb.com/job/2",
                  description_clean="Full role description here.")
    store.upsert_many([efc, jobsdb])
    store.reconcile_cross_posted()
    prim = {
        r["source"]: r["is_primary"]
        for r in store._conn.execute("SELECT source, is_primary FROM jobs")
    }
    assert prim["jobsdb"] == 1
    assert prim["efinancialcareers"] == 0


def test_jobsdb_keeps_primary_when_it_is_also_the_richer_copy(store):
    """The common case: JobsDB is both the priority default AND the richer row."""
    efc = _job("efinancialcareers", "1", url="https://efc.hk/x.id1", description_clean="")
    jobsdb = _job("jobsdb", "2", url="https://hk.jobsdb.com/job/2",
                  description_clean="Full role description here.", salary_min=40_000)
    store.upsert_many([efc, jobsdb])
    store.reconcile_cross_posted()
    prim = {
        r["source"]: r["is_primary"]
        for r in store._conn.execute("SELECT source, is_primary FROM jobs")
    }
    assert prim["jobsdb"] == 1
    assert prim["efinancialcareers"] == 0


def test_single_source_stays_primary(store):
    """A role on only one board is always displayed."""
    store.upsert_many([_job("efinancialcareers", "1")])
    store.reconcile_cross_posted()
    row = store._conn.execute("SELECT is_primary FROM jobs").fetchone()
    assert row["is_primary"] == 1


def test_same_source_duplicates_both_stay_visible(store):
    """Two rows from the SAME source with a shared title are NOT de-duped."""
    a = _job("jobsdb", "1", title="Analyst")
    b = _job("jobsdb", "2", title="Analyst")
    store.upsert_many([a, b])
    store.reconcile_cross_posted()
    vis = [r["is_primary"] for r in store._conn.execute("SELECT is_primary FROM jobs")]
    assert vis == [1, 1]  # both visible — likely distinct roles, not a cross-post


def test_reconcile_leaves_single_source_untouched(store):
    store.upsert_many([_job("jobsdb", "1")])
    groups, rows = store.reconcile_cross_posted()
    assert groups == 0
    row = store._conn.execute("SELECT apply_url, cross_posted FROM jobs").fetchone()
    assert row["apply_url"] == ""
    assert row["cross_posted"] == 0


def test_reconcile_is_idempotent_and_clears_stale(store):
    jobsdb = _job("jobsdb", "1")
    efc = _job("efinancialcareers", "2")
    store.upsert_many([jobsdb, efc])
    store.reconcile_cross_posted()

    # eFC copy disappears (soft-deleted); the JobsDB copy should be un-flagged.
    store._conn.execute("UPDATE jobs SET is_active=0 WHERE source='efinancialcareers'")
    store._conn.commit()

    groups, _ = store.reconcile_cross_posted()
    assert groups == 0
    row = store._conn.execute(
        "SELECT apply_url, cross_posted FROM jobs WHERE source='jobsdb'"
    ).fetchone()
    assert row["apply_url"] == ""
    assert row["cross_posted"] == 0


def test_mark_inactive_is_source_scoped(store):
    """A JobsDB run must not deactivate the eFC rows sharing the same slug."""
    old = datetime.now(UTC) - timedelta(days=2)
    store.upsert_many([
        _job("jobsdb", "1", fetched_at=old),
        _job("efinancialcareers", "2", fetched_at=old),
    ])

    run_time = datetime.now(UTC)
    # Simulate today's JobsDB scrape finding nothing new for this slug, then the
    # source-scoped soft-delete pass. new_job_count high enough to bypass the
    # low-count safety guard.
    deactivated = store.mark_inactive_for_run(
        "man-group-hk", run_time, new_job_count=5, source="jobsdb"
    )

    active = {
        r["source"]: r["is_active"]
        for r in store._conn.execute("SELECT source, is_active FROM jobs")
    }
    assert active["jobsdb"] == 0            # stale JobsDB row deactivated
    assert active["efinancialcareers"] == 1  # eFC row left active
    assert deactivated == 1


# ── Cross-slug matching (ADR 0027, 2026-08-27) ─────────────────────────────────
# Two companies.yaml/companies_longtail.yaml entries for the SAME employer, given
# different slugs because nobody paired them. Grouping used to be by raw
# company_slug alone, so these got zero cross-source matching, invisibly.


def test_reconcile_matches_across_slugs_for_the_same_employer(store):
    """A longtail slug and a JobsDB slug for the same company must still merge."""
    longtail = _job("longtail", "1", slug="man-group-boutique", company="Man Group",
                     url="https://man.example/careers/1")
    jobsdb = _job("jobsdb", "2", slug="man-group-hk-jobsdb", company="Man Group",
                  url="https://hk.jobsdb.com/job/2")
    store.upsert_many([longtail, jobsdb])

    groups, _ = store.reconcile_cross_posted()
    assert groups == 1
    rows = store._conn.execute(
        "SELECT source, cross_posted, is_primary FROM jobs"
    ).fetchall()
    assert all(r["cross_posted"] == 1 for r in rows)
    assert sum(r["is_primary"] for r in rows) == 1  # exactly one card shown


def test_reconcile_ignores_legal_suffix_noise_across_slugs(store):
    """'Man Group' vs 'Man Group (Hong Kong) Limited' are the same employer."""
    a = _job("longtail", "1", slug="slug-a", company="Man Group",
             url="https://man.example/1")
    b = _job("jobsdb", "2", slug="slug-b", company="Man Group (Hong Kong) Limited",
             url="https://hk.jobsdb.com/job/2")
    store.upsert_many([a, b])
    groups, _ = store.reconcile_cross_posted()
    assert groups == 1


def test_reconcile_does_not_merge_genuinely_different_companies(store):
    """Two unrelated employers with different slugs must never collapse."""
    a = _job("longtail", "1", slug="slug-a", company="Man Group",
             url="https://man.example/1")
    b = _job("jobsdb", "2", slug="slug-b", company="Deutsche Bank",
             url="https://hk.jobsdb.com/job/2")
    store.upsert_many([a, b])
    groups, _ = store.reconcile_cross_posted()
    assert groups == 0
    rows = store._conn.execute("SELECT is_primary FROM jobs").fetchall()
    assert all(r["is_primary"] == 1 for r in rows)  # both stay visible


def test_scoped_reelection_sees_the_sibling_slug(store):
    """
    A scoped reconcile touching only ONE of two slugs sharing a company name
    must still see the OTHER slug's rows, or it wrongly concludes the group is
    single-slug/single-source and resets routing set by the full pass.
    """
    longtail = _job("longtail", "1", slug="man-group-boutique", company="Man Group",
                     url="https://man.example/1")
    jobsdb = _job("jobsdb", "2", slug="man-group-hk-jobsdb", company="Man Group",
                  url="https://hk.jobsdb.com/job/2")
    store.upsert_many([longtail, jobsdb])
    store.reconcile_cross_posted()  # full pass establishes the cross-post

    # Scoped call naming only ONE of the two slugs — as mark_inactive_for_run
    # does after a deactivation confined to that slug's source.
    groups, _ = store.reconcile_cross_posted(company_slugs=["man-group-boutique"])
    assert groups == 1
    rows = store._conn.execute(
        "SELECT source, cross_posted, is_primary FROM jobs"
    ).fetchall()
    assert all(r["cross_posted"] == 1 for r in rows)
    assert sum(r["is_primary"] for r in rows) == 1
