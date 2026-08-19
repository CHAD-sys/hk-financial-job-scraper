"""
The server's route metadata and the React app's must say the same thing.

WHY THIS EXISTS
---------------
The same title and description now live in two places, because they have to:
the backend writes them into index.html for clients that never run JavaScript
(Bing, an unfurler, a phishing classifier), and React sets them again once it
boots for clients that do. Google indexes the RENDERED page, so if the two
disagree, the version Google files is the React one and the server's careful
copy is decoration.

That is the exact failure the old index.html comment was trying to avoid by
carrying no tags at all — "a static tag here would sit in the DOM alongside a
page's own and leave search engines to guess which one wins". The tags are back
because a blank shell cost us more, so the ambiguity is settled by this test
instead of by omission.

This repo already binds its registries this way rather than trusting prose —
see tests/test_sources.py.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "webapp" / "backend"
PAGES = ROOT / "webapp" / "frontend" / "src" / "pages"
APP_TSX = ROOT / "webapp" / "frontend" / "src" / "App.tsx"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from main import _NOINDEX_PREFIXES, _ROUTE_META  # noqa: E402

#: Which page component owns each indexable route's own head tags. The two routes
#: that are not here are served by App.tsx's DefaultTitleLayout instead.
_PAGE_FOR_ROUTE = {
    "/": "LandingPage.tsx",
    "/about": "AboutPage.tsx",
    "/learning": "LearningPage.tsx",
    "/privacy": "PrivacyPage.tsx",
}
_LAYOUT_ROUTES = {"/get-started", "/post-a-role"}
#: "/jobs" builds its head copy from the active query rather than writing a
#: literal, so it is checked by its own two tests below instead.
_COMPUTED_ROUTES = {"/jobs"}


def _unescape(text: str) -> str:
    return text.replace("&amp;", "&").replace("&nbsp;", " ")


def _title_in(source: str) -> str | None:
    found = re.search(r"<title>(.*?)</title>", source, re.S)
    return _unescape(found.group(1).strip()) if found else None


def _description_in(source: str) -> str | None:
    found = re.search(
        r'<meta\s*\n?\s*name="description"\s*\n?\s*content=\s*"([^"]+)"', source
    )
    return _unescape(found.group(1)) if found else None


@pytest.mark.parametrize(("route", "filename"), sorted(_PAGE_FOR_ROUTE.items()))
def test_page_component_matches_the_server_for_that_route(route, filename):
    source = (PAGES / filename).read_text(encoding="utf-8")
    server_title, server_description = _ROUTE_META[route]
    assert _title_in(source) == server_title, (
        f"{filename} title differs from _ROUTE_META['{route}']"
    )
    assert _description_in(source) == server_description, (
        f"{filename} description differs from _ROUTE_META['{route}']"
    )


@pytest.mark.parametrize("route", sorted(_LAYOUT_ROUTES))
def test_layout_route_matches_the_server(route):
    source = APP_TSX.read_text(encoding="utf-8")
    server_title, server_description = _ROUTE_META[route]
    assert f"title: '{server_title}'" in source, (
        f"App.tsx ROUTE_META has no matching title for {route}"
    )
    assert server_description in source, (
        f"App.tsx ROUTE_META has no matching description for {route}"
    )


def test_every_indexable_route_is_covered_by_one_of_the_two_mechanisms():
    """A route added to the server table must get client tags too, or it drifts."""
    assert set(_ROUTE_META) == set(_PAGE_FOR_ROUTE) | _LAYOUT_ROUTES | _COMPUTED_ROUTES


def test_the_sitemap_lists_exactly_the_indexable_routes(tmp_path):
    """
    Every page we give a title and description is a page we tell Google exists.
    Asserted against the XML the endpoint actually serves, not the source that
    builds it, so a refactor of how static_paths is derived cannot hide a gap.
    """
    from fastapi.testclient import TestClient

    from .support import make_app, make_bundle, make_jobs_db

    db = tmp_path / "jobs.db"
    make_jobs_db(db, jobs=[], enrichments=[])
    dist = tmp_path / "dist"
    make_bundle(dist)
    client = TestClient(make_app(db, dist, tmp_path, cookie_secure=False))

    body = client.get("/sitemap.xml").text
    locs = set(re.findall(r"<loc>([^<]+)</loc>", body))
    paths = {loc.split("testserver", 1)[-1] or "/" for loc in locs}
    assert set(_ROUTE_META) <= paths, (
        f"routes with metadata missing from sitemap: {sorted(set(_ROUTE_META) - paths)}"
    )


def test_no_route_is_both_indexable_and_noindex():
    for route in _ROUTE_META:
        assert not route.startswith(_NOINDEX_PREFIXES), (
            f"{route} has indexable metadata but matches a noindex prefix"
        )


# ── The discipline list ───────────────────────────────────────────────────────

SEARCH_HERO = ROOT / "webapp" / "frontend" / "src" / "components" / "SearchHero.tsx"


def test_the_discipline_list_is_the_same_on_both_sides():
    """
    BOARD_CATEGORIES (main.py) builds the sitemap entries and the per-discipline
    titles; MAJOR_CATEGORIES (SearchHero.tsx) builds the links a crawler follows.
    A discipline in one but not the other is either a sitemap entry pointing at a
    page nothing links to, or a linked page with no metadata and no sitemap row.
    """
    from main import BOARD_CATEGORIES

    source = SEARCH_HERO.read_text(encoding="utf-8")
    block = re.search(r"const MAJOR_CATEGORIES = \[(.*?)\]", source, re.S)
    assert block, "could not find MAJOR_CATEGORIES in SearchHero.tsx"
    client_side = re.findall(r"'([^']+)'", block.group(1))
    assert client_side == list(BOARD_CATEGORIES), (
        f"client {client_side} != server {list(BOARD_CATEGORIES)}"
    )


def test_the_category_links_use_the_param_the_board_reads():
    """
    The board parses its query from `?q=` (searchParamsToFilters in client.ts).
    A link built with any other key lands on /jobs with no query — which is the
    Soft 404 page these links exist to route around.
    """
    from main import BOARD_QUERY_PARAM

    assert BOARD_QUERY_PARAM == "q"
    assert f"/jobs?{BOARD_QUERY_PARAM}=$" in SEARCH_HERO.read_text(encoding="utf-8")
    client = ROOT / "webapp" / "frontend" / "src" / "api" / "client.ts"
    assert f"p.get('{BOARD_QUERY_PARAM}')" in client.read_text(encoding="utf-8")


def test_the_discipline_title_rule_is_the_same_on_both_sides():
    """
    The server writes a discipline's title into the served HTML; JobBoardPage
    writes it again once React boots. Google indexes the rendered page, so a
    mismatch means the server's careful, keyword-targeted title is decoration
    and all thirteen pages share one generic heading in the index.

    The strings are built by a rule rather than a table, so this pins the rule:
    the same template, the same >60 fallback, the same description sentence.
    """
    from main import BOARD_CATEGORIES, _category_meta

    source = (ROOT / "webapp" / "frontend" / "src" / "pages" / "JobBoardPage.tsx").read_text(
        encoding="utf-8"
    )

    # The template and its fallback, exactly as the server spells them.
    assert "${activeQuery} Jobs in Hong Kong — FinEx Careers" in source
    assert "${activeQuery} Jobs — FinEx Careers" in source
    assert "longForm.length <= 60" in source, "the server truncates at 60 characters"

    # The description sentence, split across lines in both languages.
    assert "roles across Hong Kong's banks, funds and boutiques. " in source
    assert "Indexed daily from employer sites and major boards, with an AI salary " in source
    assert "estimate on every listing." in source

    # And the rule the server applies, restated here so a change to _category_meta
    # that this file does not follow fails loudly rather than silently.
    for category in BOARD_CATEGORIES:
        title, description = _category_meta(category)
        long_form = f"{category} Jobs in Hong Kong — FinEx Careers"
        expected = long_form if len(long_form) <= 60 else f"{category} Jobs — FinEx Careers"
        assert title == expected, category
        assert description.startswith(f"Open {category.lower()} roles across Hong Kong's")


def test_the_board_falls_back_to_the_servers_words_when_there_is_no_query():
    """
    With no query the board is bare /jobs, and both sides must still agree — it
    is the page people share even though Google is told not to index it.
    """
    source = (ROOT / "webapp" / "frontend" / "src" / "pages" / "JobBoardPage.tsx").read_text(
        encoding="utf-8"
    )
    title, description = _ROUTE_META["/jobs"]
    assert f"'{title}'" in source, f"JobBoardPage has no fallback title matching {title!r}"
    for fragment in description.split(" — "):
        assert fragment.split(",")[0] in source
