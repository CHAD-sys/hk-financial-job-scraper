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
    category TEXT, fetched_at TEXT
);
CREATE TABLE job_enrichments (
    source TEXT, source_id TEXT, prompt_version TEXT, manually_edited_at TEXT
);
"""


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(_SCHEMA)
    return connection


def _add(conn, source_id, *, version="__missing__", pinned=None):
    conn.execute(
        "INSERT INTO jobs VALUES ('jobsdb',?,'Analyst','A Bank','a-bank',"
        "'mainstream','A description.',1,NULL,'2026-08-20')",
        (source_id,),
    )
    if version != "__missing__":
        conn.execute(
            "INSERT INTO job_enrichments VALUES ('jobsdb',?,?,?)",
            (source_id, version, pinned),
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


def test_classification_recalibration_does_not_grandfather_legacy_estimates():
    """v14 must reach old active Roles; it changes coordinate selection itself."""
    assert salary.ACCEPTED_PRIOR_VERSIONS == frozenset()
