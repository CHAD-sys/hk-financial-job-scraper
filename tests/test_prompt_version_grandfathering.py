"""A prompt change should not automatically re-bill the whole back catalogue.

`PROMPT_VERSION` is derived from the prompt text, so ANY edit — a typo fix, a
clarifying sentence, Morris's grade ladders — marks every stored estimate stale
and queues it for re-enrichment. At the real observed rate ($0.0065/Role, from
the billing dashboard) that is ~$40 across 6,188 active Roles, every time.

Sometimes that is exactly right: a recalibration SHOULD propagate. Usually it is
not: the change only needs to apply to Roles enriched from now on.

`salary.ACCEPTED_PRIOR_VERSIONS` is how an operator says which is which. A
version listed there is treated as current for staleness purposes, so its rows
are left alone — while the rows themselves keep their true `prompt_version`, so
it stays possible to tell which prompt actually produced which estimate. The
alternative (stamping old rows with the new version) would buy the same saving
by falsifying the provenance, and every later audit would inherit the lie.
"""

from __future__ import annotations

import sqlite3

import pytest

from hk_jobs import enrichment as enrichment_module
from hk_jobs import salary, salary_clamp
from hk_jobs.enrichers import deepseek
from hk_jobs.enrichers.deepseek import PROMPT_VERSION
from hk_jobs.enrichment import EnrichmentPipeline

_SCHEMA = """
CREATE TABLE jobs (
    source TEXT, source_id TEXT, title TEXT, company TEXT, company_slug TEXT,
    source_tier TEXT, description_clean TEXT, is_active INTEGER DEFAULT 1,
    category TEXT, fetched_at TEXT,
    -- ADR 0034: _fetch_unenriched now filters on board_visible_sql(), which
    -- needs these three. Every row here defaults to on-the-board so existing
    -- selection tests are unaffected by that filter.
    is_primary INTEGER DEFAULT 1, admin_hidden INTEGER DEFAULT 0, posted_at TEXT
);
CREATE TABLE job_enrichments (
    source TEXT, source_id TEXT, prompt_version TEXT, manually_edited_at TEXT,
    -- ADR 0036: _fetch_unenriched also selects a Role carrying NO salary figure,
    -- whatever its prompt_version. Rows here default to "already priced" so the
    -- staleness tests below keep testing staleness and nothing else.
    salary_estimated_min INTEGER DEFAULT 40000, salary_hkd_min INTEGER
);
"""


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(_SCHEMA)
    return connection


def _add(conn, source_id, *, version="__missing__", pinned=None, priced=40_000):
    from datetime import UTC, datetime

    posted_at = datetime.now(UTC).isoformat()  # always inside the 1-month board window
    conn.execute(
        "INSERT INTO jobs VALUES ('jobsdb',?,'Analyst','A Bank','a-bank',"
        "'mainstream','A description.',1,NULL,'2026-08-20',1,0,?)",
        (source_id, posted_at),
    )
    if version != "__missing__":
        conn.execute(
            "INSERT INTO job_enrichments (source, source_id, prompt_version, "
            "manually_edited_at, salary_estimated_min) VALUES ('jobsdb',?,?,?,?)",
            (source_id, version, pinned, priced),
        )


def _selected(conn, **kwargs):
    enricher = EnrichmentPipeline.__new__(EnrichmentPipeline)  # no API key needed for selection
    rows = enricher._fetch_unenriched(conn, limit=None, **kwargs)
    return {row["source_id"] for row in rows}


def test_a_job_with_no_enrichment_is_always_selected(conn):
    """The whole point: NEW Roles still get the new prompt."""
    _add(conn, "new-job")
    assert "new-job" in _selected(conn)


def test_a_grandfathered_version_is_left_alone(conn, monkeypatch):
    """RED before this change: an edited prompt re-enriched all 6,188 active Roles."""
    old = "prompt-v-old"
    monkeypatch.setattr(salary, "ACCEPTED_PRIOR_VERSIONS", frozenset({old}))
    _add(conn, "already-good", version=old)
    assert "already-good" not in _selected(conn)


def test_an_unlisted_older_version_is_still_re_enriched(conn, monkeypatch):
    """Grandfathering is opt-in per version, not a blanket 'never re-enrich'.

    A genuine recalibration must still be able to propagate — that is the whole
    reason the staleness check exists.
    """
    monkeypatch.setattr(salary, "ACCEPTED_PRIOR_VERSIONS", frozenset({"prompt-v-old"}))
    _add(conn, "genuinely-stale", version="some-much-older-version")
    assert "genuinely-stale" in _selected(conn)


def test_the_current_version_is_never_re_enriched(conn):
    _add(conn, "current", version=PROMPT_VERSION)
    assert "current" not in _selected(conn)


def test_a_null_version_is_still_re_enriched(conn, monkeypatch):
    """Unknown provenance is not the same as 'accepted'."""
    monkeypatch.setattr(salary, "ACCEPTED_PRIOR_VERSIONS", frozenset({"prompt-v-old"}))
    _add(conn, "unknown", version=None)
    assert "unknown" in _selected(conn)


def test_re_enrich_still_overrides_grandfathering(conn, monkeypatch):
    """The escape hatch has to keep working, or a real recalibration is unshippable."""
    old = "prompt-v-old"
    monkeypatch.setattr(salary, "ACCEPTED_PRIOR_VERSIONS", frozenset({old}))
    _add(conn, "already-good", version=old)
    assert "already-good" in _selected(conn, re_enrich=True)


def test_a_pinned_row_is_excluded_even_under_re_enrich(conn):
    """Unchanged behaviour, pinned here so grandfathering cannot regress it."""
    _add(conn, "pinned", version="anything", pinned="2026-08-19T00:00:00+00:00")
    assert "pinned" not in _selected(conn)
    assert "pinned" not in _selected(conn, re_enrich=True)


def test_a_deterministic_rule_change_selects_an_old_unpinned_estimate(conn, monkeypatch):
    """The completed rule fingerprint must reach the real replay selector."""
    old = PROMPT_VERSION
    _add(conn, "old-rule-result", version=old)
    monkeypatch.setattr(salary, "ACCEPTED_PRIOR_VERSIONS", frozenset())
    monkeypatch.setattr(salary_clamp, "INTERNSHIP_MAX_MONTHLY_HKD", 20_000)

    changed = salary.version(deepseek._MODEL, deepseek._SALARY_INSTRUCTIONS)
    assert changed != old
    monkeypatch.setattr(enrichment_module, "PROMPT_VERSION", changed)

    assert "old-rule-result" in _selected(conn)


def test_an_unpriced_role_is_selected_whatever_its_prompt_version(conn):
    """ADR 0036's other half. A Role carrying NO salary figure is always a
    candidate again — even on the CURRENT version, even on a grandfathered one.

    RED before ADR 0036: the 1,024 board Roles the coordinate-only gate left
    unpriced all held a current prompt_version, so every staleness arm said
    "nothing to do" and the only way to reach them was a full --re-enrich that
    would also re-bill the ~13,000 rows that were fine."""
    _add(conn, "unpriced-current", version=PROMPT_VERSION, priced=None)
    assert "unpriced-current" in _selected(conn)

    old = "prompt-v-old"
    conn.execute("DELETE FROM jobs")
    conn.execute("DELETE FROM job_enrichments")
    _add(conn, "unpriced-grandfathered", version=old, priced=None)
    assert "unpriced-grandfathered" in _selected(conn)


def test_a_priced_role_on_a_grandfathered_version_is_left_alone(conn, monkeypatch):
    """The pairing that makes ADR 0036's fix cheap: it reaches the Roles it was
    written for (unpriced) and no others (priced, on a listed version)."""
    old = "prompt-v-old"
    monkeypatch.setattr(salary, "ACCEPTED_PRIOR_VERSIONS", frozenset({old}))
    _add(conn, "priced-and-grandfathered", version=old, priced=40_000)
    assert "priced-and-grandfathered" not in _selected(conn)


def test_every_live_prompt_version_is_grandfathered():
    """ADR 0036 re-populates this list, reversing v14's empty set.

    The fix that made it necessary lands inside `finalise`, which
    `_clamp_logic_fingerprint` hashes — so PROMPT_VERSION moves and would
    otherwise mark all ~13,000 stored estimates stale. Nothing is lost: a Role
    that already carries a figure does not need the fix, and one that does not
    is reached by the "no salary figure" arm above regardless of its version.
    """
    assert salary.ACCEPTED_PRIOR_VERSIONS, "ADR 0036 grandfathers the live versions"
    # Read off the published catalogue, never computed locally: the AST-based
    # clamp fingerprint differs between Python versions, so a developer's
    # PROMPT_VERSION is not the CI runner's. See salary.ACCEPTED_PRIOR_VERSIONS.
    assert all(
        v.startswith("2026-07-21-v10-merged-3source-granular-prefix-cached")
        for v in salary.ACCEPTED_PRIOR_VERSIONS
    )
