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
    "/jobs": "JobBoardPage.tsx",
    "/learning": "LearningPage.tsx",
}
_LAYOUT_ROUTES = {"/get-started", "/post-a-role"}


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
    assert set(_ROUTE_META) == set(_PAGE_FOR_ROUTE) | _LAYOUT_ROUTES


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
