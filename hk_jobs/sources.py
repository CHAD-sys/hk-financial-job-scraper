"""
The sources a Listing can come from, and what is true about each.

WHY THIS EXISTS
---------------
There were five registries of sources, in four files and two languages, and no
two of them were checked against each other:

  1. `adapters/__init__.py`  ADAPTERS            — adapter name → class
  2. `config.py`             _REQUIRED_CONFIG_KEYS — adapter name → required YAML keys
  3. `storage.py`            _SOURCE_PRIORITY    — which copy we send you to APPLY on
  4. `storage.py`            _DISPLAY_PRIORITY   — which copy the board SHOWS
  5. `SourceBadges.tsx`      BOARDS/OWN_SITE/ORDER — the "Listed on" tags

Adding a source meant editing all five. The SAP SuccessFactors adapter, added
2026-08-02, was added to the first two and forgotten in the last three — and it
was forgotten precisely because those three are the ones that fail *quietly*.
`ADAPTERS[name]` raises KeyError the moment you get it wrong. An unregistered
source in a priority tuple just sorts last, and an unregistered source in the
frontend's ORDER is filtered out of the list.

The result, live: HKJC's nine active roles ranked below a recruiter's LinkedIn
post for both apply-routing and display, and rendered no "Listed on" section at
all — while the pipeline's own documented rule says the employer's own ATS is
the best apply target there is.

`SOURCES` is that list, once. `storage.py` derives both orders from it, and a
test in `tests/test_sources.py` binds the adapter registry and the frontend's
table to it — so the next source that is half-registered fails a test instead of
quietly sinking to the bottom of the board.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Source:
    """One place a Listing can come from."""

    #: The value stored in `jobs.source`.
    name: str

    #: How the board names it to a Seeker.
    label: str

    #: True when this is the employer's OWN careers page rather than a job
    #: board. Drives apply-routing (their own ATS is the best place to apply)
    #: and the frontend, which collapses every own-site source into one
    #: "Company site" tag rather than naming the ATS vendor at a Seeker.
    own_site: bool

    #: The `ADAPTERS` key that produces this source, or None when nothing
    #: scrapes it directly — `linkedin_posts` rows are promoted from the
    #: Secret Market pipeline, not fetched by an adapter.
    adapter: str | None


SOURCES: tuple[Source, ...] = (
    Source("workday", "Workday", own_site=True, adapter="workday"),
    Source("eightfold", "Eightfold", own_site=True, adapter="eightfold"),
    Source("successfactors", "SAP SuccessFactors", own_site=True, adapter="successfactors"),
    Source("longtail", "Company site", own_site=True, adapter="longtail"),
    Source("efinancialcareers", "eFinancialCareers", own_site=False, adapter="efinancialcareers"),
    Source("jobsdb", "JobsDB", own_site=False, adapter="jobsdb"),
    Source("linkedin", "LinkedIn", own_site=False, adapter="linkedin"),
    Source("indeed", "Indeed", own_site=False, adapter="indeed"),
    Source("linkedin_posts", "Recruiter post", own_site=False, adapter=None),
)

BY_NAME: dict[str, Source] = {s.name: s for s in SOURCES}
SOURCE_NAMES: frozenset[str] = frozenset(BY_NAME)
OWN_SITE: frozenset[str] = frozenset(s.name for s in SOURCES if s.own_site)


# ── The two orders ────────────────────────────────────────────────────────────
#
# Written as orders because that is what they are; a test asserts each is a
# permutation of SOURCES, so a source can be added to the registry and left out
# of an order only by making a test fail.

#: Where we send a Seeker to APPLY when one vacancy exists on several sources.
#:
#: Boutique own-site first (per the product directive), then the employer's own
#: ATS — its real careers page, and the best apply target after boutique — then
#: the aggregators. `linkedin_posts` is deliberately last: a real board listing
#: always beats a recruiter's post for the same vacancy
#: (PLAN_LINKEDIN_POSTS.md decision record).
APPLY_ORDER: tuple[str, ...] = (
    "longtail",
    "workday",
    "eightfold",
    "successfactors",
    "efinancialcareers",
    "linkedin",
    "indeed",
    "jobsdb",
    "linkedin_posts",
)

#: Which copy of a cross-posted vacancy the board SHOWS. Distinct from the apply
#: order above: we apply on eFinancialCareers, but we display the richest record.
#:
#: JobsDB first — per the product decision, and because JobsDB rows carry both a
#: full description AND the DeepSeek enrichment. The own-ATS sources come next;
#: `successfactors` sits with workday/eightfold because it is the same kind of
#: record and measures the same on the only axis this order is about — 9 of 9
#: active rows carry a full description (~3.3k chars), matching workday's and
#: eightfold's 100%. LinkedIn outranks indeed because LinkedIn rows carry a
#: fetched description, whereas indeed is listing-only. Suppressed copies get
#: is_primary=0.
DISPLAY_ORDER: tuple[str, ...] = (
    "jobsdb",
    "eightfold",
    "workday",
    "successfactors",
    "efinancialcareers",
    "longtail",
    "linkedin",
    "indeed",
    "linkedin_posts",
)


_warned: set[str] = set()


def _rank(order: tuple[str, ...], name: str) -> int:
    """
    Position in `order`, or last for a source nobody registered.

    Ranking an unknown source last rather than raising is deliberate: this runs
    inside the nightly reconciliation over live data, and an unrecognised value
    in one row must not abort a scrape of 147 companies. It warns instead —
    once per source per process — because silently sorting last is exactly how
    SuccessFactors spent two days below a recruiter's LinkedIn post. The real
    guard is `tests/test_sources.py`, which fails before any of this ships.
    """
    try:
        return order.index(name)
    except ValueError:
        if name not in _warned:
            _warned.add(name)
            logger.warning(
                "Source %r is not registered in hk_jobs/sources.py — ranking it last. "
                "Add it to SOURCES, APPLY_ORDER and DISPLAY_ORDER.",
                name,
            )
        return len(order)


def apply_rank(name: str) -> int:
    """Lower is a better place to send a Seeker to apply."""
    return _rank(APPLY_ORDER, name)


def display_rank(name: str) -> int:
    """Lower is a better copy to show on the board."""
    return _rank(DISPLAY_ORDER, name)
