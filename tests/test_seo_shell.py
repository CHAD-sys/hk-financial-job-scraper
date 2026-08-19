"""
What a crawler that does NOT run JavaScript gets for the app's own pages.

WHY THESE EXIST
---------------
The Role teaser pages in test_seo.py were always server-rendered. Every OTHER
route — "/", "/about", "/jobs", "/learning", "/get-started" and the sign-in
pages — served the bare Vite index.html: no title, no description, no Open
Graph, no body copy. Four of twenty-one page components set a title, and they
set it in React, which only exists once JS has run.

Two things broke because of that, and both are the reason this file exists:

1. Search: the five static URLs in sitemap.xml are the brand pages, and they
   were the weakest pages on the site. Google renders JS eventually; Bing,
   DuckDuckGo, Yandex and Baidu largely do not.
2. Reputation: LinkedIn/Slack/X unfurlers do not run JS either. A sign-in
   page that answers a bot with an empty document and a human with a login
   form is the cloaking signature phishing kits use, and this site was
   showing a LinkedIn sign-in warning while that was true.

So: every indexable route must carry its identity in the HTML itself.
"""

from __future__ import annotations

import json
import re
from html import unescape
from urllib.parse import quote_plus


def _q(label: str) -> str:
    return f"/jobs?q={quote_plus(label)}"

import pytest
from fastapi.testclient import TestClient

from .support import enrichment, job, make_app, make_bundle, make_jobs_db

_INDEXABLE = ["/", "/about", "/jobs", "/learning", "/get-started", "/post-a-role"]


@pytest.fixture()
def client(tmp_path):
    jobs = [
        job(source="workday", source_id="MAIN", company="HSBC",
            title="Risk Management Officer", posted_at="2026-07-01",
            description_clean="SECRET FULL DESCRIPTION mainstream."),
        # Enough HSBC Roles to clear _MIN_ROLES_FOR_A_LANDING_PAGE. An employer
        # below that threshold deliberately gets no page — see the thin-content
        # test — so the fixture has to be over it for the page to exist at all.
        *[
            job(source="workday", source_id=f"HSBC{n}", company="HSBC",
                title=f"Banking Operations Officer {n}", posted_at="2026-07-04")
            for n in range(1, 6)
        ],
        # The two tiers an anonymous visitor must never be served (ADR 0018).
        # They exist here so the server-rendered block can be shown NOT to leak
        # them, which is the whole risk of writing Roles into public HTML.
        job(source="longtail", source_id="BOUT", company="Harbour Capital",
            title="Treasury Analyst", source_tier="boutique", posted_at="2026-07-02"),
        job(source="linkedin_posts", source_id="SOC", company="Confidential",
            title="Risk Manager", source_tier="social", posted_at="2026-07-03"),
    ]
    enrichments = [
        enrichment(source="workday", source_id="MAIN",
                   description_summary="Manage risk at HSBC.",
                   salary_hkd_min=40_000, salary_hkd_max=60_000),
        *[
            enrichment(source="workday", source_id=f"HSBC{n}",
                       description_summary="Run banking operations at HSBC.")
            for n in range(1, 6)
        ],
        enrichment(source="longtail", source_id="BOUT",
                   description_summary="Manage treasury operations."),
        enrichment(source="linkedin_posts", source_id="SOC",
                   description_summary="Lead risk management."),
    ]
    db = tmp_path / "jobs.db"
    make_jobs_db(db, jobs=jobs, enrichments=enrichments)
    dist = tmp_path / "dist"
    make_bundle(dist)
    return TestClient(make_app(db, dist, tmp_path, cookie_secure=False))


def _head(client, path: str) -> str:
    r = client.get(path)
    assert r.status_code == 200, f"{path} -> {r.status_code}"
    return r.text


@pytest.mark.parametrize("path", _INDEXABLE)
def test_every_indexable_route_has_a_title_in_the_html(client, path):
    """RED before: index.html carried no <title>, so a non-JS client got none."""
    body = _head(client, path)
    titles = re.findall(r"<title[^>]*>(.*?)</title>", body, re.S)
    assert titles, f"{path} served no <title> without JavaScript"
    assert "FinEx Careers" in titles[0]


@pytest.mark.parametrize("path", _INDEXABLE)
def test_every_indexable_route_has_its_own_description(client, path):
    body = _head(client, path)
    found = re.search(r'<meta[^>]*name="description" content="([^"]+)"', body)
    assert found, f"{path} served no meta description without JavaScript"
    assert len(found.group(1)) > 40


def test_route_titles_are_distinct_not_one_generic_shell(client):
    """A single shared title across every route is not indexable copy."""
    titles = []
    for path in _INDEXABLE:
        titles.append(re.findall(r"<title[^>]*>(.*?)</title>", _head(client, path), re.S)[0])
    assert len(set(titles)) == len(titles), f"duplicate titles across routes: {titles}"


@pytest.mark.parametrize("path", _INDEXABLE)
def test_every_indexable_route_is_shareable(client, path):
    """The unfurl card an unfurler builds with no JS — the reputation surface."""
    body = _head(client, path)
    for tag in ("og:title", "og:description", "og:url", "og:image", "og:site_name"):
        assert f'property="{tag}"' in body, f"{path} missing {tag}"
    assert 'name="twitter:card" content="summary_large_image"' in body


@pytest.mark.parametrize("path", _INDEXABLE)
def test_every_indexable_route_declares_its_canonical_on_the_real_domain(client, path):
    body = _head(client, path)
    found = re.search(r'<link[^>]*rel="canonical" href="([^"]+)"', body)
    assert found, f"{path} has no canonical"
    assert found.group(1).startswith("http")


def test_the_home_page_identifies_the_organisation_to_search_engines(client):
    """
    Organization + WebSite structured data is how Google ties this site to a
    real entity. Absent it, a young domain running an OAuth login is exactly
    the shape of a phishing site, which is the reputation problem this fixes.
    """
    body = _head(client, "/")
    blocks = re.findall(r'<script[^>]*type="application/ld\+json">(.*?)</script>', body, re.S)
    kinds = {json.loads(b).get("@type") for b in blocks}
    assert "Organization" in kinds, f"no Organization JSON-LD on /, saw {kinds}"
    org = next(json.loads(b) for b in blocks if json.loads(b).get("@type") == "Organization")
    assert org["name"]
    assert org["url"].startswith("http")
    # sameAs is the entity link that says "this brand exists elsewhere too".
    assert org.get("sameAs"), "Organization has no sameAs entity links"


def test_private_routes_are_not_indexable(client):
    """Sign-in and account pages should render, but must not be indexed."""
    for path in ("/signin", "/account", "/saved", "/register", "/employer/signin"):
        body = client.get(path).text
        assert re.search(r'<meta[^>]*name="robots" content="[^"]*noindex', body), (
            f"{path} is indexable; it should be noindex"
        )


def test_a_client_side_only_route_still_falls_through_to_the_spa(client):
    """The injection must not turn an unknown path into a 404 or a wrong title."""
    r = client.get("/some/deep/client/route")
    assert r.status_code == 200
    assert "id='root'" in r.text or 'id="root"' in r.text


def test_injected_tags_are_marked_so_the_client_can_hand_over(client):
    """
    React sets its own head tags once it boots. The server-injected ones carry
    data-ssr so the app can drop the ones React re-renders and leave exactly one
    of each, rather than two competing titles in the DOM.

    Only title, description and JSON-LD are dropped — see main.tsx. Canonical and
    og:* have no React equivalent, so they stay; Google indexes the rendered page,
    and stripping them would leave the canonical visible only to clients that
    never run JS.
    """
    body = _head(client, "/about")
    assert body.count("data-ssr") >= 3
    assert '<title data-ssr>' in body
    assert '<meta data-ssr name="description"' in body
    assert '<link data-ssr rel="canonical"' in body


@pytest.mark.parametrize("path", _INDEXABLE)
def test_titles_and_descriptions_fit_what_a_result_page_shows(client, path):
    """
    Google truncates a title around 60 characters and a description around 160.
    A title that gets cut mid-phrase reads as careless on the results page, which
    is the first impression this whole exercise is about.
    """
    body = _head(client, path)
    # Unescape first: "&amp;" is five characters in the source and one on the
    # results page, and it is the results page this limit is about.
    title = unescape(re.findall(r"<title[^>]*>(.*?)</title>", body, re.S)[0])
    description = unescape(
        re.search(r'<meta[^>]*name="description" content="([^"]+)"', body).group(1)
    )
    assert len(title) <= 60, f"{path} title is {len(title)} chars: {title}"
    assert "FinEx Careers" in title, f"{path} title carries no brand: {title}"
    assert 70 <= len(description) <= 200, f"{path} description is {len(description)} chars"


# ── The duplicate origin ──────────────────────────────────────────────────────
#
# Railway answers on its own *.up.railway.app hostname as well as the address we
# publish, and it served the whole site there at 200 with "Allow: /". That is a
# second copy of every page for Google to choose between, and a sign-in form on a
# free-hosting subdomain for a phishing classifier to find.


def test_the_published_host_is_indexable(client, monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://testserver")
    body = client.get("/robots.txt").text
    assert "Allow: /" in body
    assert "Disallow: /\n" not in body
    assert client.get("/").headers.get("X-Robots-Tag") is None


def test_any_other_host_is_told_not_to_index_anything(client, monkeypatch):
    """Still serves — health checks live here — but never gets indexed."""
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://www.finexcareers.com")

    robots = client.get("/robots.txt").text
    assert "Disallow: /" in robots
    assert "Allow: /" not in robots

    page = client.get("/")
    assert page.status_code == 200, "a non-canonical host must still serve"
    assert page.headers["X-Robots-Tag"] == "noindex, nofollow"


def test_a_role_page_on_the_wrong_host_is_not_indexable_either(client, monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://www.finexcareers.com")
    r = client.get("/jobs/workday/MAIN/credit-risk-analyst-hsbc")
    assert r.status_code == 200
    assert r.headers["X-Robots-Tag"] == "noindex, nofollow"


def test_security_txt_names_someone_accountable(client):
    body = client.get("/.well-known/security.txt").text
    assert "Contact:" in body
    assert "mailto:" in body


def test_account_paths_are_disallowed_in_robots(client, monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://testserver")
    body = client.get("/robots.txt").text
    for path in ("/account", "/admin", "/signin", "/register", "/employer/"):
        assert f"Disallow: {path}" in body, f"{path} is crawlable"


# ── Discipline landing pages ──────────────────────────────────────────────────
#
# "/jobs" answers a crawler with no roles at all: no session and no query means
# the API correctly refuses (ADR 0018). Google inspected it on 2026-08-18 and
# returned Soft 404 — right, given the page promised jobs and delivered none.
# "/jobs?q=<discipline>" carries a query, so it answers with real roles while
# leaving the "no enumerable catalogue" rule completely alone.


def test_each_discipline_is_its_own_indexable_page(client):
    from main import BOARD_CATEGORIES, _category_path

    for category in BOARD_CATEGORIES:
        body = _head(client, _category_path(category))
        title = unescape(re.findall(r"<title[^>]*>(.*?)</title>", body, re.S)[0])
        assert category.split(",")[0] in title, f"{category}: wrong title {title!r}"
        assert len(title) <= 60, f"{category}: title is {len(title)} chars"
        assert 'content="index,follow"' in body, f"{category} is not indexable"


def test_a_discipline_canonical_keeps_its_query(client):
    """Canonicalising these to bare /jobs would collapse 13 pages into one."""
    from main import _category_path

    body = _head(client, _category_path("Private Banking"))
    canonical = re.search(r'<link[^>]*rel="canonical" href="([^"]+)"', body).group(1)
    assert "q=Private+Banking" in unescape(canonical), canonical


def test_an_arbitrary_search_is_not_indexable(client):
    """
    A free-text board offers a crawler an infinite space of near-identical URLs.
    Only the thirteen known disciplines are indexable; everything else renders
    for the human who typed it and is noindex for everyone else.
    """
    body = _head(client, "/jobs?q=some+visitor+typed+this")
    assert re.search(r'<meta[^>]*name="robots" content="[^"]*noindex', body)
    assert 'content="index,follow"' not in body


def test_the_sitemap_lists_every_discipline(client):
    from main import BOARD_CATEGORIES

    body = client.get("/sitemap.xml").text
    for category in BOARD_CATEGORIES:
        assert f"q={quote_plus(category)}" in unescape(body), f"{category} not in sitemap"



def test_bare_jobs_is_a_hub_not_an_empty_search_box(client):
    """
    /jobs was noindex for part of 2026-08-18, on the reading that a page ADR 0018
    leaves with no Roles has nothing to rank. That reading was made while
    robots.txt still blocked /api/, so BOTH Soft 404 verdicts were passed on a
    page Google could not get any data for at all.

    With the API allowed it renders the market totals and thirteen disciplines,
    which is a real hub page — so it is indexable again, and it carries that
    content in the HTML rather than depending on anyone's renderer.
    """
    body = _head(client, "/jobs")
    assert 'content="index,follow"' in body
    assert 'id="ssr-hub"' in body
    # Thirteen discipline links a crawler can follow with no JavaScript.
    assert body.count('<li><a href="/jobs?q=') == 13
    assert "Browse by discipline" in body


def test_the_hub_never_shows_roles_it_may_not_show(client):
    """The hub carries public totals and links — never Roles, and never a tier."""
    body = _head(client, "/jobs")
    assert 'id="ssr-roles"' not in body
    assert "Treasury Analyst" not in body, "a boutique Role leaked onto the hub"
    assert "Risk Manager" not in body, "a recruiter-posted Role leaked onto the hub"


def test_a_discipline_page_carries_its_roles_without_javascript(client):
    """
    RED before: the served document was an empty <div id="root">, and every Role
    on it arrived through a client-side call to /api/jobs. Google returned Soft
    404 on /jobs?q=Risk+Management even though a browser renders 24 cards there.

    These pages no longer depend on anyone's renderer.
    """
    from main import _category_path

    body = _head(client, _category_path("Risk Management"))
    assert 'id="ssr-roles"' in body, "no server-rendered Roles in the document"
    assert "Risk Management Officer" in body, "the matching Role is not in the HTML"
    # Every Role is a real route into the catalogue, not just text.
    assert body.count('<li><a href="/jobs/') >= 1


def test_server_rendered_roles_respect_the_anonymous_audience(client):
    """
    ADR 0018: an anonymous visitor receives mainstream Roles only. This block is
    served with no session at all, so boutique and recruiter-posted Roles must
    not appear in it — otherwise the SEO surface quietly becomes the catalogue
    hole the ADR closed.
    """
    from main import _category_path

    body = _head(client, _category_path("Treasury"))
    assert "Treasury Analyst" not in body, "a boutique-tier Role leaked into the HTML"
    assert "Risk Manager" not in body, "a recruiter-posted Role leaked into the HTML"


def test_an_unknown_query_gets_no_server_rendered_roles(client):
    """Only the thirteen chosen disciplines are worth a database read per request."""
    body = _head(client, "/jobs?q=whatever+someone+typed")
    assert 'id="ssr-roles"' not in body


# ── The robots.txt rule that cost us the board ────────────────────────────────
#
# Googlebot obeys robots.txt for the XHRs a page makes while rendering. With
# "Disallow: /api/" and nothing else, it fetched /jobs?q=..., ran the bundle, had
# every data call refused (499 in its own console), rendered "No roles match
# these filters" and called the page a Soft 404. Three attempts to fix that page
# failed because the page was never the problem.


@pytest.mark.parametrize(
    "endpoint", ["/api/jobs", "/api/filters", "/api/stats"]
)
def test_the_board_can_fetch_what_it_needs_to_render(client, monkeypatch, endpoint):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://testserver")
    body = client.get("/robots.txt").text
    assert f"Allow: {endpoint}" in body, f"{endpoint} is blocked; the board renders empty"
    # Longest-match wins in robots.txt, so the Allow must be more specific than
    # the Disallow it overrides — and must appear at all.
    assert "Disallow: /api/" in body
    assert len(endpoint) > len("/api/")


def test_the_rest_of_the_api_stays_closed(client, monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://testserver")
    body = client.get("/robots.txt").text
    for endpoint in ("/api/auth/me", "/api/me/saved", "/api/me/resume"):
        assert f"Allow: {endpoint}" not in body


def test_api_responses_are_fetchable_but_never_indexable(client):
    """Allowing a crawler to read JSON is not wanting that JSON in the index."""
    r = client.get("/api/stats")
    assert r.status_code == 200
    assert r.headers["X-Robots-Tag"] == "noindex"


# ── Employer and sector landing pages ─────────────────────────────────────────
#
# "/jobs?q=HSBC" always answered a signed-out visitor correctly — 308 Roles in
# production — it simply was not indexable, because only the thirteen curated
# disciplines were. These are the queries with real intent behind them, and the
# ones this board can actually win.


def test_an_employer_with_enough_roles_gets_an_indexable_page(client):
    from main import _category_path

    body = _head(client, _category_path("HSBC"))
    title = unescape(re.findall(r"<title[^>]*>(.*?)</title>", body, re.S)[0])
    assert "HSBC" in title, title
    assert len(title) <= 60
    assert 'content="index,follow"' in body
    assert 'id="ssr-roles"' in body, "an employer page must carry its Roles too"


def test_a_thin_employer_gets_no_page_at_all(client):
    """
    A landing page with two Roles on it is thin content, and a hundred of them
    is a worse signal than not having them. Below the threshold an employer is
    served like any other free-text query: rendered for the human, noindex.
    """
    from main import _category_path

    body = _head(client, _category_path("Harbour Capital"))
    assert re.search(r'<meta[^>]*name="robots" content="[^"]*noindex', body)
    assert 'content="index,follow"' not in body


def test_a_sector_gets_its_own_page(client):
    from main import _category_path

    body = _head(client, _category_path("Banking"))
    assert 'content="index,follow"' in body
    assert "Banking" in unescape(re.findall(r"<title[^>]*>(.*?)</title>", body, re.S)[0])


def test_the_curated_disciplines_win_a_name_collision(client):
    """
    An employer named "Treasury" must not take the discipline's page. The
    disciplines are the chosen set; everything else is derived from data that
    changes nightly.
    """
    from main import _category_path, _category_meta

    body = _head(client, _category_path("Treasury"))
    title = unescape(re.findall(r"<title[^>]*>(.*?)</title>", body, re.S)[0])
    assert title == _category_meta("Treasury")[0]


def test_every_landing_page_is_in_the_sitemap(client):
    body = unescape(client.get("/sitemap.xml").text)
    assert "q=HSBC" in body, "employer pages are missing from the sitemap"
    assert "q=Banking" in body, "sector pages are missing from the sitemap"
    assert "q=Risk+Management" in body, "discipline pages are missing from the sitemap"


# ── A Role page is no longer a dead end ───────────────────────────────────────


def test_a_role_page_links_onward_to_pages_that_exist(client):
    """
    RED before: a teaser linked to "/", "/get-started" and "/jobs" and nothing
    else, so 4,273 Role pages were 4,273 dead ends — no authority moved between
    them and the sitemap was the only route in.
    """
    body = client.get("/jobs/workday/MAIN/risk-management-officer-hsbc").text
    assert "More jobs at HSBC" in body
    assert _q("HSBC") in body, "the employer link must point at the employer page"
    assert "jobs in Hong Kong</a>" in body, "no sector link"


def test_the_onward_links_go_to_indexable_pages(client):
    """A link into a noindex page passes nothing on; these must be real pages."""
    body = client.get("/jobs/workday/MAIN/risk-management-officer-hsbc").text
    for href in re.findall(r'href="(/jobs\?q=[^"]+)"', body):
        target = _head(client, unescape(href))
        assert 'content="index,follow"' in target, f"{href} is not indexable"
