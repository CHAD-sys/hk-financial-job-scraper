"""
The source registry, and the four things that must agree with it.

There were five registries of sources in four files and two languages, and
nothing checked any of them against the others. The SAP SuccessFactors adapter
was added to two and forgotten in three — the three that fail *quietly*.

Every test here is one of those five, bound to `hk_jobs/sources.py`. The point
is not that the lists are currently right; it is that the next one to be
half-registered fails here rather than shipping.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from hk_jobs.adapters import ADAPTERS
from hk_jobs.config import _REQUIRED_CONFIG_KEYS
from hk_jobs.sources import (
    APPLY_ORDER,
    BY_NAME,
    DISPLAY_ORDER,
    OWN_SITE,
    SOURCE_NAMES,
    SOURCES,
    apply_rank,
    display_rank,
)

_REPO = Path(__file__).resolve().parent.parent
_BADGES_TSX = _REPO / "webapp" / "frontend" / "src" / "components" / "SourceBadges.tsx"


# ── The registry is internally consistent ─────────────────────────────────────

def test_source_names_are_unique():
    names = [s.name for s in SOURCES]
    assert len(names) == len(set(names))


@pytest.mark.parametrize("order,label", [(APPLY_ORDER, "APPLY_ORDER"),
                                         (DISPLAY_ORDER, "DISPLAY_ORDER")])
def test_each_order_covers_exactly_the_registry(order, label):
    """
    THE regression. `successfactors` was in neither order, so it sorted last —
    below a recruiter's LinkedIn post — for both apply-routing and display.
    Nothing raised, because an unregistered source just ranks last.
    """
    assert set(order) == SOURCE_NAMES, (
        f"{label} disagrees with SOURCES — "
        f"missing: {sorted(SOURCE_NAMES - set(order))}, "
        f"unknown: {sorted(set(order) - SOURCE_NAMES)}"
    )
    assert len(order) == len(set(order)), f"{label} lists a source twice"


# ── Registry 1: the adapters ──────────────────────────────────────────────────

def test_every_adapter_produces_a_registered_source():
    """
    An adapter whose `source_name` is not in SOURCES writes rows that every
    ranking treats as unknown — which is the whole SuccessFactors story.
    """
    unregistered = {
        key: cls.source_name
        for key, cls in ADAPTERS.items()
        if cls.source_name not in SOURCE_NAMES
    }
    assert unregistered == {}, f"adapters writing unregistered sources: {unregistered}"


def test_every_source_with_an_adapter_names_a_real_one():
    for source in SOURCES:
        if source.adapter is None:
            continue
        assert source.adapter in ADAPTERS, f"{source.name}: no adapter {source.adapter!r}"
        assert ADAPTERS[source.adapter].source_name == source.name, (
            f"{source.name}: adapter {source.adapter!r} writes "
            f"{ADAPTERS[source.adapter].source_name!r}"
        )


def test_the_only_source_without_an_adapter_is_recruiter_posts():
    """
    `linkedin_posts` rows are promoted by the Secret Market pipeline rather than
    fetched, so it is the one source with no adapter. A second one showing up
    here means either a new promotion path or a forgotten registration.
    """
    assert {s.name for s in SOURCES if s.adapter is None} == {"linkedin_posts"}


# ── Registry 2: config.py's YAML validation ───────────────────────────────────

def test_every_adapter_declares_its_required_config_keys():
    """
    An adapter missing from `_REQUIRED_CONFIG_KEYS` accepts any YAML entry and
    fails later, at fetch time, on a missing kwarg — far from the typo.
    """
    assert set(_REQUIRED_CONFIG_KEYS) == set(ADAPTERS), (
        f"missing: {sorted(set(ADAPTERS) - set(_REQUIRED_CONFIG_KEYS))}, "
        f"unknown: {sorted(set(_REQUIRED_CONFIG_KEYS) - set(ADAPTERS))}"
    )


# ── Registry 5: the frontend's "Listed on" tags ───────────────────────────────

def _tsx_literal_members(source: str, name: str) -> set[str]:
    """Pull the string members out of `const NAME = new Set([...])` or `= [...]`."""
    match = re.search(rf"const {name}\s*=\s*(?:new Set\()?\[(.*?)\]", source, re.S)
    assert match, f"could not find {name} in SourceBadges.tsx"
    return set(re.findall(r"['\"]([^'\"]+)['\"]", match.group(1)))


def _tsx_boards(source: str) -> set[str]:
    """The keys of the BOARDS record."""
    match = re.search(r"const BOARDS: Record<string, Board> = \{(.*?)\n\}", source, re.S)
    assert match, "could not find BOARDS in SourceBadges.tsx"
    return set(re.findall(r"^\s{2}(\w+):", match.group(1), re.M))


def test_the_frontend_can_render_every_source():
    """
    The cross-language seam, checked from the side that can see both.

    `SourceBadges.normalise()` maps a source to 'company' if it is in OWN_SITE,
    otherwise keeps its name — then filters against ORDER. A source in neither
    OWN_SITE nor ORDER survives no branch and vanishes: no tag, no error, no
    clue. `successfactors` fell through exactly this hole, and HKJC's nine
    active roles rendered no "Listed on" section at all.
    """
    tsx = _BADGES_TSX.read_text(encoding="utf-8")
    own_site = _tsx_literal_members(tsx, "OWN_SITE")
    order = _tsx_literal_members(tsx, "ORDER")

    renderable = own_site | order
    missing = SOURCE_NAMES - renderable
    assert missing == set(), (
        f"SourceBadges.tsx renders nothing for {sorted(missing)} — add each to "
        f"OWN_SITE (employer's own careers page) or to BOARDS and ORDER (a job board)"
    )


def test_the_frontends_own_site_set_matches_the_registry():
    tsx = _BADGES_TSX.read_text(encoding="utf-8")
    assert _tsx_literal_members(tsx, "OWN_SITE") == set(OWN_SITE)


def test_every_frontend_board_has_a_colour_and_a_mark():
    """
    ORDER drives the render and BOARDS supplies the styling; a name in ORDER
    with no BOARDS entry reaches `<BoardTag board={undefined}>` and throws on
    `board.color`. 'company' is the exception — it renders CompanyTag instead.
    """
    tsx = _BADGES_TSX.read_text(encoding="utf-8")
    order = _tsx_literal_members(tsx, "ORDER") - {"company"}
    assert order <= _tsx_boards(tsx), f"in ORDER but not BOARDS: {sorted(order - _tsx_boards(tsx))}"


def test_the_frontend_names_no_source_the_pipeline_cannot_produce():
    tsx = _BADGES_TSX.read_text(encoding="utf-8")
    named = (_tsx_literal_members(tsx, "OWN_SITE") | _tsx_boards(tsx)) - {"company"}
    assert named <= SOURCE_NAMES, f"unknown to the pipeline: {sorted(named - SOURCE_NAMES)}"


# ── Ranking ───────────────────────────────────────────────────────────────────

def test_the_employers_own_ats_outranks_every_aggregator_for_applying():
    """
    The pipeline's documented rule, asserted rather than commented. This is what
    SuccessFactors was silently violating: HKJC's own careers page ranked below
    JobsDB, Indeed, and a recruiter's post.
    """
    worst_own_site = max(apply_rank(s.name) for s in SOURCES if s.own_site)
    best_board = min(apply_rank(s.name) for s in SOURCES if not s.own_site)
    assert worst_own_site < best_board


def test_recruiter_posts_rank_last_in_both_orders():
    """
    A real board listing always beats a recruiter's post for the same vacancy —
    PLAN_LINKEDIN_POSTS.md's decision record, and true of both orders.
    """
    assert APPLY_ORDER[-1] == "linkedin_posts"
    assert DISPLAY_ORDER[-1] == "linkedin_posts"


def test_successfactors_ranks_with_the_other_own_ats_sources():
    """
    It ranked last in both orders — below a recruiter's post — for two days.

    The two orders disagree about JobsDB on purpose: we send a Seeker to the
    employer's own ATS to apply, but we display the richest record, and JobsDB
    rows carry both a full description and the enrichment. So the assertion for
    display is only that SuccessFactors sits with workday/eightfold, which it
    matches on the axis that order is about — 9 of 9 active rows have a full
    description, the same 100% those two manage.
    """
    assert apply_rank("successfactors") < apply_rank("jobsdb")
    assert apply_rank("successfactors") < apply_rank("indeed")

    assert abs(display_rank("successfactors") - display_rank("workday")) == 1
    assert display_rank("successfactors") < display_rank("indeed")

    for rank in (apply_rank, display_rank):
        assert rank("successfactors") < rank("linkedin_posts")


def test_an_unregistered_source_ranks_last_and_says_so(caplog):
    """
    Not an exception: this runs inside the nightly reconciliation over live
    data, and one unrecognised value must not abort a scrape of 147 companies.
    It warns, and the tests above are the real guard.
    """
    import logging

    from hk_jobs import sources

    sources._warned.discard("brand-new-board")
    with caplog.at_level(logging.WARNING):
        assert apply_rank("brand-new-board") == len(APPLY_ORDER)
    assert any("not registered" in m for m in caplog.messages)


def test_the_unregistered_warning_is_not_repeated_per_row(caplog):
    """One line per source per process, not one per row of a 15,000-row table."""
    import logging

    from hk_jobs import sources

    sources._warned.discard("another-new-board")
    with caplog.at_level(logging.WARNING):
        for _ in range(50):
            apply_rank("another-new-board")
    assert len([m for m in caplog.messages if "another-new-board" in m]) == 1


# ── Lookup ────────────────────────────────────────────────────────────────────

def test_by_name_covers_the_registry():
    assert set(BY_NAME) == SOURCE_NAMES
    assert BY_NAME["successfactors"].own_site is True
    assert BY_NAME["jobsdb"].own_site is False
