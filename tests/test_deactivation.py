"""
Deactivating a Listing, and the Role it can take with it.

`is_active = 0` had four writers. `JobStore.mark_inactive_for_run` was one;
`tech_filter.py`, `posts/expiry.py` and `scripts/remove_tech_roles.py` each
opened their own connection and ran their own UPDATE. All four were right about
the soft delete and three were wrong about what it costs.

`reconcile_cross_posted` elects exactly one copy of a cross-posted vacancy as
`is_primary = 1`, and the board shows only that copy. Deactivate the elected
copy without re-running the election and every survivor is `is_primary = 0`, so
the Role disappears while a live Listing still exists. `pipeline.run()` calls
`run_tech_filter` AFTER `reconcile_cross_posted()`, so that window opened on
every nightly run and stayed open until the next one.

These are the tests that would have caught it.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from hk_jobs.schema import Job
from hk_jobs.storage import JobStore


def job(source: str, source_id: str, *, title: str = "Data Engineer",
        slug: str = "testco", fetched_at: datetime | None = None) -> Job:
    # Company name defaults to the slug itself (not a shared literal like "Test
    # Co") — reconcile_cross_posted now groups by normalized company NAME, not
    # slug (ADR 0027), so two DIFFERENT slugs in these scoping tests need
    # genuinely different names or they'd collide into one group.
    return Job(
        source=source, source_id=source_id, company=slug, company_slug=slug,
        url=f"https://example.com/{source}/{source_id}", title=title,
        locations=["Hong Kong"], fetched_at=fetched_at or datetime.now(UTC),
    )


def rows(db: str) -> dict[str, tuple[int, int]]:
    conn = sqlite3.connect(db)
    try:
        return {
            r[0]: (r[1], r[2])
            for r in conn.execute("SELECT source, is_active, is_primary FROM jobs")
        }
    finally:
        conn.close()


def visible(db: str) -> int:
    """What the board shows — job_read.BOARD_WHERE, stated here so it is checkable."""
    conn = sqlite3.connect(db)
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE is_active = 1 AND is_primary = 1"
        ).fetchone()[0]
    finally:
        conn.close()


@pytest.fixture()
def db(tmp_path: Path) -> str:
    return str(tmp_path / "jobs.db")


# ── The regression ────────────────────────────────────────────────────────────

def test_deactivating_the_elected_copy_does_not_hide_the_role(db: str):
    """
    THE bug. A JobsDB + Workday pair: JobsDB is elected (it carries the
    description and the enrichment), Workday is suppressed. Deactivate the
    JobsDB copy — as tech_filter does, nightly, right after the election — and
    the board went from 1 visible to 0 with the Workday row still is_active=1.
    """
    with JobStore(db) as store:
        store.upsert_many([job("jobsdb", "J1"), job("workday", "W1")])
        store.reconcile_cross_posted()
        assert rows(db) == {"jobsdb": (1, 1), "workday": (1, 0)}
        assert visible(db) == 1

        store.deactivate([("jobsdb", "J1")], reason="hard-tech")

    assert rows(db) == {"jobsdb": (0, 1), "workday": (1, 1)}, "the survivor must be re-elected"
    assert visible(db) == 1, "the Role must not vanish while a live Listing exists"


def test_deactivating_a_suppressed_copy_leaves_the_elected_one_alone(db: str):
    with JobStore(db) as store:
        store.upsert_many([job("jobsdb", "J1"), job("workday", "W1")])
        store.reconcile_cross_posted()
        store.deactivate([("workday", "W1")], reason="hard-tech")

    assert visible(db) == 1
    assert rows(db)["jobsdb"] == (1, 1)


def test_deactivating_every_copy_leaves_nothing_visible(db: str):
    with JobStore(db) as store:
        store.upsert_many([job("jobsdb", "J1"), job("workday", "W1")])
        store.reconcile_cross_posted()
        store.deactivate([("jobsdb", "J1"), ("workday", "W1")], reason="hard-tech")

    assert visible(db) == 0


# ── Soft delete ───────────────────────────────────────────────────────────────

def test_deactivate_never_removes_a_row(db: str):
    """
    The repo-wide rule (CLAUDE.md): a Seeker may have saved the Role, and a
    Saved Role is a reference, so the row has to survive to show as Closed.
    """
    with JobStore(db) as store:
        store.upsert_many([job("jobsdb", "J1")])
        store.deactivate([("jobsdb", "J1")], reason="hard-tech")
        assert store.stats()["total"] == 1
        assert store.stats()["active"] == 0


def test_deactivate_returns_the_number_actually_changed(db: str):
    with JobStore(db) as store:
        store.upsert_many([job("jobsdb", "J1"), job("workday", "W1")])
        assert store.deactivate([("jobsdb", "J1")], reason="x") == 1
        assert store.deactivate([("jobsdb", "J1")], reason="x") == 0, "already inactive"


def test_deactivate_ignores_a_ref_that_does_not_exist(db: str):
    with JobStore(db) as store:
        store.upsert_many([job("jobsdb", "J1")])
        assert store.deactivate([("jobsdb", "nope")], reason="x") == 0


def test_deactivate_with_no_refs_is_a_no_op(db: str):
    with JobStore(db) as store:
        store.upsert_many([job("jobsdb", "J1")])
        assert store.deactivate([], reason="x") == 0
        assert store.stats()["active"] == 1


def test_deactivate_touches_only_the_named_refs(db: str):
    with JobStore(db) as store:
        store.upsert_many([
            job("jobsdb", "J1", slug="alpha"),
            job("jobsdb", "J2", slug="beta", title="Credit Analyst"),
        ])
        store.deactivate([("jobsdb", "J1")], reason="x")
        assert store.stats()["active"] == 1


def test_deactivate_handles_more_refs_than_sqlite_allows_in_one_expression(db: str):
    """
    SQLite caps expression-tree depth near 1000, so the IN (...) is chunked —
    the same limit and the same fix as the jobs read path.
    """
    listings = [job("jobsdb", f"J{i}", title=f"Role {i}") for i in range(450)]
    with JobStore(db) as store:
        store.upsert_many(listings)
        changed = store.deactivate([("jobsdb", f"J{i}") for i in range(450)], reason="x")
        assert changed == 450
        assert store.stats()["active"] == 0


# ── The scrape guards stay where they were ────────────────────────────────────

def test_a_zero_job_scrape_still_deactivates_nothing(db: str):
    """
    The anti-Cloudflare guard, unmoved. An empty scrape is far more likely a
    block than a company closing every vacancy overnight — and this guard is
    `mark_inactive_for_run`'s own business, not `deactivate`'s, because no other
    caller is asking "did a scrape fail?".
    """
    run = datetime.now(UTC)
    with JobStore(db) as store:
        store.upsert_many([job("jobsdb", "J1", fetched_at=run - timedelta(days=1))])
        assert store.mark_inactive_for_run("testco", run, new_job_count=0) == 0
        assert store.stats()["active"] == 1


def test_a_normal_scrape_deactivates_what_it_no_longer_sees(db: str):
    run = datetime.now(UTC)
    with JobStore(db) as store:
        store.upsert_many([
            job("jobsdb", "J1", fetched_at=run - timedelta(days=1)),
            job("jobsdb", "J2", fetched_at=run, title="Credit Analyst"),
        ])
        assert store.mark_inactive_for_run("testco", run, new_job_count=1) == 1
        assert store.stats()["active"] == 1


def test_the_scrape_path_also_re_elects(db: str):
    """
    `mark_inactive_for_run` goes through `deactivate` too, so a Role whose
    elected copy stops being listed keeps a visible survivor.
    """
    run = datetime.now(UTC)
    with JobStore(db) as store:
        store.upsert_many([
            job("jobsdb", "J1", fetched_at=run - timedelta(days=1)),
            job("workday", "W1", fetched_at=run),
        ])
        store.reconcile_cross_posted()
        assert rows(db)["jobsdb"] == (1, 1)

        store.mark_inactive_for_run("testco", run, new_job_count=1, source="jobsdb")

    assert visible(db) == 1
    assert rows(db)["workday"] == (1, 1)


# ── Scoped reconciliation ─────────────────────────────────────────────────────

def test_reconcile_can_be_scoped_to_named_companies(db: str):
    """
    A full pass is O(n^2) per company and takes ~22s over 5,000 active rows,
    which is why deactivate re-elects only the slugs it touched.
    """
    with JobStore(db) as store:
        store.upsert_many([
            job("jobsdb", "J1", slug="alpha"), job("workday", "W1", slug="alpha"),
            job("jobsdb", "J2", slug="beta"), job("workday", "W2", slug="beta"),
        ])
        store.reconcile_cross_posted()

        # Break beta's election by hand, then reconcile alpha only.
        conn = sqlite3.connect(db)
        with conn:
            conn.execute("UPDATE jobs SET is_primary = 0 WHERE company_slug = 'beta'")
        conn.close()

        store.reconcile_cross_posted(company_slugs=["alpha"])

    conn = sqlite3.connect(db)
    beta = conn.execute(
        "SELECT SUM(is_primary) FROM jobs WHERE company_slug='beta'"
    ).fetchone()[0]
    conn.close()
    assert beta == 0, "a company outside the scope must not be re-elected"


def test_reconcile_with_an_empty_scope_does_nothing(db: str):
    with JobStore(db) as store:
        store.upsert_many([job("jobsdb", "J1"), job("workday", "W1")])
        assert store.reconcile_cross_posted(company_slugs=[]) == (0, 0)


def test_reconcile_unscoped_still_covers_everything(db: str):
    with JobStore(db) as store:
        store.upsert_many([
            job("jobsdb", "J1", slug="alpha"), job("workday", "W1", slug="alpha"),
            job("jobsdb", "J2", slug="beta"), job("workday", "W2", slug="beta"),
        ])
        groups, _ = store.reconcile_cross_posted()
        assert groups == 2


# ── The other three writers ───────────────────────────────────────────────────

def test_the_tech_filter_re_elects(db: str, monkeypatch):
    """
    tech_filter ran a raw UPDATE on its own connection, immediately after the
    election in `pipeline.run()`. It is the writer that made this bug nightly.
    """
    from hk_jobs import tech_filter

    # The two boards spell the title differently in case. `_cluster_by_title`
    # normalises case so they are one Role, but tech_filter matches on exact
    # TRIM(title) — so it removes the JobsDB copy and leaves the Workday one.
    # That partial removal is what strands a Role, and it is why this test uses
    # two spellings rather than one: with both copies removed, the board is
    # empty either way and the test would not discriminate.
    with JobStore(db) as store:
        store.upsert_many([
            job("jobsdb", "J1", title="Data Engineer"),
            job("workday", "W1", title="data engineer"),
        ])
        store.reconcile_cross_posted()
        assert visible(db) == 1

    conn = sqlite3.connect(db)
    with conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS tech_title_cache (title TEXT PRIMARY KEY, is_tech INTEGER)"
        )
        conn.execute(
            "INSERT OR REPLACE INTO tech_title_cache VALUES ('Data Engineer', 1)"
        )
    conn.close()
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    _classified, removed = tech_filter.run_tech_filter(db)

    assert removed == 1, "only the exactly-matching title is hard tech"
    assert rows(db)["jobsdb"][0] == 0
    assert rows(db)["workday"] == (1, 1), "the survivor must be re-elected"
    assert visible(db) == 1, "the Role must not vanish"


def test_expiry_re_elects(db: str):
    """
    A recruiter post that expires must not take a live board Listing with it.
    """
    from hk_jobs.posts import expiry

    old = datetime.now(UTC) - timedelta(days=200)
    with JobStore(db) as store:
        store.upsert_many([
            job("linkedin_posts", "P1").model_copy(update={"posted_at": old}),
            job("jobsdb", "J1"),
        ])
        store.reconcile_cross_posted()

    before = rows(db)
    assert before["linkedin_posts"][0] == 1

    expiry.deactivate_stale_jobs(db, max_age_days=90)

    after = rows(db)
    assert after["linkedin_posts"][0] == 0, "the stale post is deactivated"
    assert after["jobsdb"] == (1, 1), "the live board Listing stays visible"
    assert visible(db) == 1


def test_no_module_writes_is_active_outside_the_store():
    """
    The structural guard. Four modules each had their own
    `UPDATE jobs SET is_active=0`; a fifth appearing is how this bug comes back.
    """
    import re

    root = Path(__file__).resolve().parent.parent
    offenders = []
    for path in list(root.glob("hk_jobs/**/*.py")) + list(root.glob("scripts/*.py")) \
            + list(root.glob("webapp/backend/*.py")):
        if path.name in ("storage.py", "migrations.py"):
            continue
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            if re.search(r"SET\s+is_active\s*=\s*0", line, re.I):
                offenders.append(f"{path.relative_to(root)}: {line.strip()}")
    assert offenders == [], (
        "these write is_active directly instead of via JobStore.deactivate(), "
        f"so they skip the primary re-election: {offenders}"
    )


# ── When it closed ────────────────────────────────────────────────────────────
# `is_active` says a Role is no longer open; `closed_at` says for how long it has
# not been, and Saved Roles need the difference (docs/adr/0011). The date is only
# trustworthy because deactivate() is the single write path — the guard above is
# what keeps that true, and these are what keep the date honest.

def closure(db: str, source: str) -> tuple[int, str | None]:
    conn = sqlite3.connect(db)
    try:
        return conn.execute(
            "SELECT is_active, closed_at FROM jobs WHERE source = ?", (source,)
        ).fetchone()
    finally:
        conn.close()


def test_deactivating_stamps_when_it_closed(db: str):
    with JobStore(db) as store:
        store.upsert_many([job("workday", "W1")])
        assert closure(db, "workday") == (1, None), "an open Listing has no closure date"

        store.deactivate([("workday", "W1")], reason="test")

    is_active, closed_at = closure(db, "workday")
    assert is_active == 0
    assert closed_at is not None, "a closed Listing must say when"
    stamped = datetime.fromisoformat(closed_at)
    assert abs((datetime.now(UTC) - stamped).total_seconds()) < 60


def test_a_reopened_listing_is_no_longer_closed_at_any_time(db: str):
    """
    THE one that matters most for the Seeker. A Listing that comes back keeps its
    stale `closed_at` unless the upsert clears it — and a fortnight later every
    Seeker holding that live Role would find it gone from their Saved Roles,
    because the date says it closed months ago.
    """
    with JobStore(db) as store:
        store.upsert_many([job("workday", "W1")])
        store.deactivate([("workday", "W1")], reason="test")
        assert closure(db, "workday")[1] is not None

        store.upsert_many([job("workday", "W1")])       # the source lists it again

    assert closure(db, "workday") == (1, None)


def test_one_run_closes_together(db: str):
    """
    Every Listing in a call shares one timestamp. A nightly run closing 5,000
    stale rows is one event, not 5,000 spread over however long the loop took.
    """
    with JobStore(db) as store:
        store.upsert_many([job("workday", f"W{i}") for i in range(5)])
        store.deactivate([("workday", f"W{i}") for i in range(5)], reason="test")

    conn = sqlite3.connect(db)
    try:
        stamps = {r[0] for r in conn.execute("SELECT closed_at FROM jobs")}
    finally:
        conn.close()
    assert len(stamps) == 1


def test_a_listing_that_was_already_closed_keeps_its_original_date(db: str):
    """
    deactivate() only touches rows that are currently active, so re-running it
    cannot push a long-closed Role's date forward and hand it a fresh fortnight
    in someone's Saved Roles.
    """
    with JobStore(db) as store:
        store.upsert_many([job("workday", "W1")])
        store.deactivate([("workday", "W1")], reason="first")
        first = closure(db, "workday")[1]

        assert store.deactivate([("workday", "W1")], reason="again") == 0

    assert closure(db, "workday")[1] == first
