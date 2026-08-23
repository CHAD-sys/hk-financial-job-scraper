"""
Characterization tests for /api/jobs and /api/jobs/{source}/{source_id}.

WHY THESE EXIST
---------------
The board's read path had no tests at all. It was about to be lifted out of
main.py into its own module, and a move with no net under it is a rewrite you
find out about in production.

So these pin what the endpoints do *today*, deliberately including behaviour
nobody has written down anywhere else: which rows are visible, how the four
sorts sink their edge cases, that the paging count agrees with the rows it
counts, how a cross-posted card collects signals from copies the board never
shows, and where the apply link actually points.

They are written against the HTTP surface rather than the internals precisely so
they survive the move. If one of these goes red during the refactor, the refactor
changed behaviour — that is the whole job of this file.

The one thing they do NOT pin is Saved Roles: that behaviour is knowingly wrong
(a closed Role renders as live) and is being changed. Its tests live in
test_job_read.py, written as a specification rather than a characterization.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from .support import enrichment, job, make_app, make_bundle, make_jobs_db, signals

# Companies chosen so SECTOR_SQL puts each in a different bucket.
BANKING = "HSBC"

#: Stamped into every fixture row's `description_clean` — the employer's own text.
#: No public response may echo it back. See test_no_public_response_echoes_the_
#: employers_own_text, which is the blocker: it does not care what a field is
#: called, only whether the employer's words reach the wire.
EMPLOYER_TEXT_SENTINEL = "QQEMPLOYERVERBATIMQQ"
IB = "Goldman Sachs"
INSURANCE = "AIA"
ASSET_MGMT = "BlackRock"
PRO_SERVICES = "KPMG"


def _seed():
    """
    The corpus every test in this file reads.

    Rows are named for the property they pin, so a failure message points at the
    behaviour rather than at a row number.
    """
    jobs = [
        # Ordinary visible rows, one per sector.
        job(source="workday", source_id="BANK", company=BANKING,
            title="Credit Risk Analyst", posted_at="2026-07-01",
            description_clean="Analyse credit risk."),
        job(source="workday", source_id="IB", company=IB,
            title="Equity Research Associate", posted_at="2026-06-01"),
        job(source="eightfold", source_id="INS", company=INSURANCE,
            title="Actuarial Manager", posted_at="2026-05-01"),
        job(source="jobsdb", source_id="AM", company=ASSET_MGMT,
            title="Portfolio Analyst", posted_at="2026-04-01"),

        # Must never appear in the board listing.
        job(source="workday", source_id="CLOSED", company=BANKING,
            title="Closed Role", is_active=0, posted_at="2026-07-02"),
        job(source="workday", source_id="SECONDARY", company=BANKING,
            title="Secondary Copy", is_primary=0, posted_at="2026-07-03"),

        # A posted_at in the future is bad data, not "newest" — it must sink.
        job(source="workday", source_id="FUTURE", company=BANKING,
            title="Future Dated", posted_at="2099-01-01"),
        # No date at all also sinks.
        job(source="workday", source_id="NODATE", company=BANKING,
            title="Undated Role", posted_at=None),

        # Cross-posted pair sharing an apply_url. PRIMARY is the displayed card;
        # HIDDEN is never listed but its signals must reach the card.
        job(source="jobsdb", source_id="XPOST", company=BANKING,
            title="Cross Posted Role", posted_at="2026-03-01",
            cross_posted=1, apply_url="https://apply.test/shared",
            board_signals=signals(applicant_count=4)),
        job(source="indeed", source_id="XPOST_HIDDEN", company=BANKING,
            title="Cross Posted Role", posted_at="2026-03-01", is_primary=0,
            cross_posted=1, apply_url="https://apply.test/shared",
            board_signals=signals(urgently_hiring=True)),

        # Internship word-boundary behaviour: one true, one deliberate near-miss.
        job(source="workday", source_id="INTERN", company=PRO_SERVICES,
            title="Summer Intern, Audit", posted_at="2026-02-01"),
        job(source="workday", source_id="INTERNAL", company=PRO_SERVICES,
            title="Internal Audit Manager", posted_at="2026-02-02"),

        # A long description, to pin excerpt truncation.
        job(source="workday", source_id="LONGDESC", company=BANKING,
            title="Long Description Role", posted_at="2026-01-01",
            description_clean="x" * 500),

        # Member-only discovery tiers. They share the research term below but
        # must never enter an anonymous result, facet or direct detail read.
        job(source="longtail", source_id="MEDIUM", company="Harbour Capital",
            title="Treasury Analyst", source_tier="boutique", posted_at="2026-01-03"),
        job(source="linkedin_posts", source_id="RECRUITER", company="Confidential",
            title="Risk Manager", source_tier="social", posted_at="2026-01-02"),
    ]
    enrichments = [
        # Salary sorts read COALESCE(disclosed, estimated).
        enrichment(source="workday", source_id="BANK",
                   salary_hkd_min=40_000, salary_hkd_max=60_000,
                   seniority="mid", remote_type="on-site",
                   description_summary="A credit risk role at a Hong Kong bank.",
                   required_skills='["credit risk"]', years_experience_required=5),
        # Truncation is a property of the SUMMARY now, so the long text under
        # test has to be a summary. 'y' here, 'x' in the row's own description:
        # the excerpt test asserts it sees the former and never the latter.
        enrichment(source="workday", source_id="LONGDESC",
                   description_summary="y" * 500),
        enrichment(source="workday", source_id="IB",
                   salary_estimated_min=80_000, salary_estimated_max=120_000,
                   seniority="senior", remote_type="hybrid"),
        enrichment(source="eightfold", source_id="INS",
                   salary_hkd_min=20_000, salary_hkd_max=30_000,
                   seniority="junior"),
        # AM has NO salary at all — it must sink in BOTH salary directions.
    ]
    # A fixture-only research term shared by every row. Tests that exercise
    # filtering/sorting can work inside one legitimate research scope without
    # reopening the production endpoint's former unscoped catalogue access.
    for row in jobs:
        row["description_clean"] = (
            f"{row['description_clean']} finexscope {EMPLOYER_TEXT_SENTINEL}".strip()
        )
    return jobs, enrichments


@pytest.fixture()
def client(tmp_path):
    db = tmp_path / "jobs.db"
    jobs, enrichments = _seed()
    make_jobs_db(db, jobs=jobs, enrichments=enrichments)
    dist = tmp_path / "dist"
    make_bundle(dist)
    return TestClient(make_app(db, dist, tmp_path, cookie_secure=False))


def _ids(body) -> list[str]:
    return [j["source_id"] for j in body["jobs"]]


def _get(client, **params):
    params.setdefault("search", "finexscope")
    r = client.get("/api/jobs", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _detail(client, source: str, source_id: str):
    listing = _get(client, page_size=100)
    grant = next(
        job["access_token"]
        for job in listing["jobs"]
        if job["source"] == source and job["source_id"] == source_id
    )
    return client.get(
        f"/api/jobs/{source}/{source_id}", headers={"X-Role-Access": grant}
    )


def _register_member(client):
    response = client.post("/api/auth/register", json={
        "email": f"member-{uuid4().hex}@example.com",
        "password": "correct horse battery staple",
        "display_name": "Member",
    })
    assert response.status_code == 201, response.text
    assert client.cookies.get("finex_session")


# ── Visibility ────────────────────────────────────────────────────────────────

def test_listing_excludes_inactive_and_non_primary(client):
    """The board shows one card per live vacancy: soft-deleted rows and the
    non-primary copies of a cross-posted role are both invisible."""
    ids = _ids(_get(client, page_size=100))
    assert "CLOSED" not in ids
    assert "SECONDARY" not in ids
    assert "XPOST_HIDDEN" not in ids
    assert "XPOST" in ids


def test_anonymous_research_hides_recruiter_and_medium_company_roles(client):
    ids = set(_ids(_get(client, page_size=100)))
    assert "MEDIUM" not in ids
    assert "RECRUITER" not in ids


def test_signed_in_seeker_research_includes_member_only_roles(client):
    _register_member(client)
    ids = set(_ids(_get(client, page_size=100)))
    assert {"MEDIUM", "RECRUITER"} <= ids


def test_research_facets_follow_the_same_member_boundary(client):
    public = client.get("/api/filters", params={"search": "finexscope"}).json()
    assert public["tier_counts"].get("boutique", 0) == 0
    assert public["tier_counts"].get("social", 0) == 0
    assert all(item["name"] != "Harbour Capital" for item in public["companies"])

    _register_member(client)
    member = client.get("/api/filters", params={"search": "finexscope"}).json()
    assert member["tier_counts"]["boutique"] == 1
    assert member["tier_counts"]["social"] == 1
    assert any(item["name"] == "Harbour Capital" for item in member["companies"])


def test_member_role_grant_stops_working_after_sign_out(client):
    _register_member(client)
    listing = _get(client, page_size=100)
    role = next(item for item in listing["jobs"] if item["source_id"] == "MEDIUM")
    headers = {"X-Role-Access": role["access_token"]}
    assert client.get("/api/jobs/longtail/MEDIUM", headers=headers).status_code == 200

    client.post("/api/auth/logout")
    assert client.get("/api/jobs/longtail/MEDIUM", headers=headers).status_code == 404


def test_listing_refuses_an_unscoped_catalogue_read(client):
    response = client.get("/api/jobs", params={"page_size": 100})
    assert response.status_code == 422
    assert "specific search" in response.json()["detail"]


# ── Admin browse (ADR 0019) ───────────────────────────────────────────────────
# Research Scope binds visitors and Seekers. It does not bind staff, who need to
# page through Roles nobody would think to search for. Every test below went RED
# before the exemption: each empty-query call returned 422.


def test_an_untouched_estimate_is_not_marked_verified(client):
    body = _get(client, page_size=100)
    assert all(job["salary_verified"] is False for job in body["jobs"])


def _register_admin(client, *, super_admin: bool = False):
    """A signed-in admin on this client's session, by promoting a fresh Seeker."""
    import seekers_store

    email = f"admin-{uuid4().hex}@example.com"
    response = client.post("/api/auth/register", json={
        "email": email, "password": "correct horse battery staple", "display_name": "Admin",
    })
    assert response.status_code == 201, response.text
    store = seekers_store.get_store()
    row = store.get_seeker_by_email(email)
    # Deliberately NOT set_admin as well when super_admin is asked for: the two
    # columns are independent in the store, and the point of this branch is that
    # is_super_admin ALONE is enough.
    if super_admin:
        store.set_super_admin(row["id"], True)
    else:
        store.set_admin(row["id"], True)
    return row["id"]


def test_an_admin_may_browse_the_catalogue_with_no_query(client):
    _register_admin(client)
    response = client.get("/api/jobs", params={"page_size": 100})
    assert response.status_code == 200
    # Not "some rows" — the whole live catalogue, member tiers included.
    ids = set(_ids(response.json()))
    assert {"MEDIUM", "RECRUITER"} <= ids


# ── AI salary estimate visibility (2026-08-21) ─────────────────────────────────
# "IB" carries only an AI estimate (salary_estimated_*), no employer-disclosed
# figure — the exact shape a wrong estimate reaches a visitor as. "BANK" is the
# opposite: employer-disclosed only. Together they pin that the gate hides the
# ESTIMATE specifically, never a disclosed salary, for either role.


def _job(body, source_id: str) -> dict:
    return next(j for j in body["jobs"] if j["source_id"] == source_id)


def test_salary_estimate_is_hidden_from_an_anonymous_visitor(client):
    ib = _job(_get(client, page_size=100), "IB")
    assert ib["salary_estimated_min"] is None
    assert ib["salary_estimated_max"] is None
    assert ib["salary_estimated_confidence"] is None


def test_salary_estimate_is_hidden_from_a_signed_in_seeker(client):
    _register_member(client)
    ib = _job(_get(client, page_size=100), "IB")
    assert ib["salary_estimated_min"] is None
    assert ib["salary_estimated_max"] is None


def test_salary_estimate_is_visible_to_an_admin(client):
    _register_admin(client)
    ib = _job(_get(client, page_size=100), "IB")
    assert (ib["salary_estimated_min"], ib["salary_estimated_max"]) == (80_000, 120_000)


def test_salary_estimate_is_visible_to_a_super_admin_only_account(client):
    # is_super_admin alone, no is_admin — the account shape the detail
    # endpoint's OWN narrow admin check would wrongly exclude if the salary
    # gate reused it instead of the broad _is_admin_session check.
    _register_admin(client, super_admin=True)
    ib = _job(_get(client, page_size=100), "IB")
    assert (ib["salary_estimated_min"], ib["salary_estimated_max"]) == (80_000, 120_000)


def test_disclosed_salary_is_never_hidden_anonymous_or_admin(client):
    anon = _job(_get(client, page_size=100), "BANK")
    assert (anon["salary_hkd_min"], anon["salary_hkd_max"]) == (40_000, 60_000)

    _register_admin(client)
    admin = _job(_get(client, page_size=100), "BANK")
    assert (admin["salary_hkd_min"], admin["salary_hkd_max"]) == (40_000, 60_000)


def test_salary_estimate_gate_also_applies_to_the_detail_endpoint(client):
    anon_detail = _detail(client, "workday", "IB")
    assert anon_detail.status_code == 200
    assert anon_detail.json()["salary_estimated_min"] is None

    _register_admin(client)
    admin_detail = _detail(client, "workday", "IB")
    assert admin_detail.status_code == 200
    assert admin_detail.json()["salary_estimated_min"] == 80_000


def test_ultimate_admin_alone_may_browse_with_no_query(client):
    """is_super_admin without is_admin still counts as staff — the two bits are
    independent columns, and create_admin.py setting both is a convention, not a
    constraint the store enforces."""
    _register_admin(client, super_admin=True)
    assert client.get("/api/jobs", params={"page_size": 100}).status_code == 200


def test_admin_browse_still_hides_closed_and_duplicate_rows(client):
    """The exemption lifts the QUERY requirement, not Visibility.BOARD. An admin
    browsing everything must still see one card per live vacancy."""
    _register_admin(client)
    ids = set(_ids(client.get("/api/jobs", params={"page_size": 100}).json()))
    assert "CLOSED" not in ids
    assert "SECONDARY" not in ids
    assert "XPOST_HIDDEN" not in ids


def test_an_ordinary_seeker_is_still_refused_without_a_query(client):
    """The exemption is staff-only. A signed-in non-admin gets the same 422 an
    anonymous visitor does — being logged in is not being staff."""
    _register_member(client)
    response = client.get("/api/jobs", params={"page_size": 100})
    assert response.status_code == 422
    assert "specific search" in response.json()["detail"]


def test_admin_facets_cover_the_whole_catalogue_when_browsing(client):
    """A filter bar over an unscoped grid has to offer what that grid contains."""
    _register_admin(client)
    facets = client.get("/api/filters", params={"search": ""})
    assert facets.status_code == 200
    body = facets.json()
    assert body["tier_counts"]["boutique"] == 1
    assert body["tier_counts"]["social"] == 1
    assert any(item["name"] == "Harbour Capital" for item in body["companies"])


def test_an_empty_facet_request_is_still_refused_for_everyone_else(client):
    response = client.get("/api/filters", params={"search": ""})
    assert response.status_code == 422
    assert "specific search" in response.json()["detail"]


def test_total_counts_the_same_rows_it_returns(client):
    """The count is built from a hand-retyped copy of the listing's join, so it
    can drift from the rows without anything failing. Pin them together."""
    body = _get(client, page_size=100)
    assert body["total"] == len(body["jobs"])


def test_total_respects_filters(client):
    assert _get(client, sectors=["Insurance"], page_size=100)["total"] == 1


# ── Sorting ───────────────────────────────────────────────────────────────────

def test_newest_sinks_future_dates_and_nulls(client):
    """A posted_at beyond tomorrow is a source's date-parsing bug. It must not
    dominate the top of the board, and neither must a missing date."""
    ids = _ids(_get(client, sort="newest", page_size=100))
    assert ids[0] == "BANK"
    assert ids.index("FUTURE") > ids.index("AM")
    assert ids.index("NODATE") > ids.index("AM")


def test_salary_high_sorts_desc_and_sinks_missing(client):
    ids = _ids(_get(client, sort="salary_high", page_size=100))
    assert ids[:3] == ["IB", "BANK", "INS"]
    assert ids.index("AM") > ids.index("INS")


def test_salary_low_sorts_asc_and_still_sinks_missing(client):
    """The sink must hold in BOTH directions — relying on SQLite NULL ordering
    would float the no-salary rows to the top here."""
    ids = _ids(_get(client, sort="salary_low", page_size=100))
    assert ids[:3] == ["INS", "BANK", "IB"]
    assert ids.index("AM") > ids.index("IB")


def test_company_sorts_alphabetically(client):
    companies = [j["company"] for j in _get(client, sort="company", page_size=100)["jobs"]]
    assert companies == sorted(companies)


def test_unknown_sort_is_rejected(client):
    """
    Changed deliberately. `sort` used to be a free string resolved with
    `.get(sort, newest)`, so `?sort=slaary_high` quietly returned newest-first
    and the caller never learned their parameter was ignored. It is an enum now,
    so FastAPI rejects it at the edge.
    """
    assert client.get("/api/jobs", params={"sort": "not_a_sort"}).status_code == 422


# ── Paging ────────────────────────────────────────────────────────────────────

def test_paging_splits_without_overlap(client):
    first = _get(client, page=1, page_size=3, sort="company")
    second = _get(client, page=2, page_size=3, sort="company")
    assert len(first["jobs"]) == 3
    assert first["total"] == second["total"]
    assert first["total_pages"] == -(-first["total"] // 3)
    assert set(_ids(first)).isdisjoint(_ids(second))


def test_empty_result_reports_zero_pages(client):
    body = _get(client, companies=["Nobody Ltd"])
    assert body == {"total": 0, "page": 1, "page_size": 24, "total_pages": 0, "jobs": []}


# ── Derived columns ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("source_id,sector", [
    ("BANK", "Banking"), ("IB", "Investment Banking"), ("INS", "Insurance"),
    ("AM", "Asset Management"), ("INTERN", "Professional Services"),
])
def test_sector_is_derived_from_company(client, source_id, sector):
    body = _get(client, page_size=100)
    got = {j["source_id"]: j["sector"] for j in body["jobs"]}
    assert got[source_id] == sector


def test_internship_matches_whole_words_only(client):
    """"Internal Audit" must not read as an internship — the regex uses word
    boundaries precisely so "internal"/"international" never match."""
    got = {j["source_id"]: j["is_internship"] for j in _get(client, page_size=100)["jobs"]}
    assert got["INTERN"] is True
    assert got["INTERNAL"] is False


def test_excerpt_is_truncated_with_an_ellipsis(client):
    body = _get(client, companies=[BANKING], page_size=100)
    excerpt = next(j for j in body["jobs"] if j["source_id"] == "LONGDESC")["description_excerpt"]
    assert len(excerpt) == 201 and excerpt.endswith("…")
    # Truncated from the AI summary, never from the employer's own description.
    assert excerpt.startswith("y") and "x" not in excerpt


def test_the_list_never_puts_the_employers_own_words_on_the_wire(client):
    """The exposure this replaced: description_excerpt was description_clean[:200]
    for every row of every list response, anonymous included."""
    body = _get(client, page_size=100)
    for row in body["jobs"]:
        assert "x" * 20 not in row["description_excerpt"]


def test_apply_url_wins_over_the_source_url(client):
    """For a cross-posted role the displayed card is the richest copy but apply
    must route to the preferred board."""
    body = _get(client, page_size=100)
    by_id = {j["source_id"]: j for j in body["jobs"]}
    assert by_id["XPOST"]["url"] == "https://apply.test/shared"
    assert by_id["BANK"]["url"] == "https://example.test/x"


# ── Cross-posted signal aggregation ───────────────────────────────────────────

def test_card_collects_signals_from_copies_it_never_shows(client):
    """XPOST_HIDDEN is not listed anywhere, but its board's signals belong to the
    same vacancy and must appear on the card that IS shown."""
    body = _get(client, page_size=100)
    card = next(j for j in body["jobs"] if j["source_id"] == "XPOST")
    assert card["board_signals"]["jobsdb"] == {"applicant_count": 4}
    assert card["board_signals"]["indeed"] == {"urgently_hiring": True}


def test_single_source_card_shows_only_its_own_signals(client):
    body = _get(client, page_size=100)
    card = next(j for j in body["jobs"] if j["source_id"] == "BANK")
    assert card["board_signals"] == {}


# ── Filters ───────────────────────────────────────────────────────────────────

def test_search_matches_title(client):
    assert _ids(_get(client, search="Actuarial")) == ["INS"]


def test_search_matches_company(client):
    assert _ids(_get(client, search="BlackRock")) == ["AM"]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("Big4", {"KPMG_ALIAS", "EY_ALIAS", "DELOITTE_ALIAS", "PWC_ALIAS"}),
        ("MBB", {"MCKINSEY_ALIAS", "BAIN_ALIAS", "BCG_ALIAS"}),
        ("mckensey", {"MCKINSEY_ALIAS"}),
    ],
)
def test_company_group_aliases_work_through_the_public_api(tmp_path, query, expected):
    """The deployable backend copy, not just the scraper-side index, expands aliases."""
    db = tmp_path / "aliases.db"
    make_jobs_db(
        db,
        jobs=[
            job(source="jobsdb", source_id="KPMG_ALIAS", company="KPMG", title="Audit Associate"),
            job(source="jobsdb", source_id="EY_ALIAS", company="EY", title="Tax Consultant"),
            job(
                source="jobsdb", source_id="DELOITTE_ALIAS", company="Deloitte",
                title="Risk Analyst",
            ),
            job(source="jobsdb", source_id="PWC_ALIAS", company="PwC", title="Deals Associate"),
            job(
                source="jobsdb", source_id="MCKINSEY_ALIAS", company="McKinsey & Company",
                title="Business Analyst",
            ),
            job(
                source="jobsdb", source_id="BAIN_ALIAS", company="Bain & Company",
                title="Associate Consultant",
            ),
            job(
                source="jobsdb", source_id="BCG_ALIAS", company="Boston Consulting Group",
                title="Consultant",
            ),
        ],
    )
    dist = tmp_path / "dist"
    make_bundle(dist)
    alias_client = TestClient(make_app(db, dist, tmp_path, cookie_secure=False))

    response = alias_client.get("/api/jobs", params={"search": query, "page_size": 100})
    assert response.status_code == 200, response.text
    assert set(_ids(response.json())) == expected


def test_company_filter(client):
    assert _ids(_get(client, companies=[IB])) == ["IB"]


def test_seniority_filter(client):
    assert _ids(_get(client, seniority=["senior"])) == ["IB"]


def test_remote_type_filter(client):
    assert _ids(_get(client, remote_type=["hybrid"])) == ["IB"]


def test_skills_filter(client):
    assert _ids(_get(client, skills=["credit risk"])) == ["BANK"]


def test_salary_min_uses_the_estimate_when_nothing_is_disclosed(client):
    ids = _ids(_get(client, salary_min=70_000, page_size=100))
    assert ids == ["IB"]


def test_experience_filter(client):
    assert _ids(_get(client, exp_min=4, exp_max=6)) == ["BANK"]


def test_internship_filter(client):
    assert _ids(_get(client, is_internship=True)) == ["INTERN"]


# ── Detail endpoint ───────────────────────────────────────────────────────────

def test_detail_returns_the_role(client):
    r = _detail(client, "workday", "BANK")
    assert r.status_code == 200
    body = r.json()
    assert body["company"] == BANKING
    assert body["description_summary"].startswith("A credit risk role")


def test_detail_never_puts_the_employers_own_words_on_the_wire(client):
    """This assertion used to be its opposite — the test asserted the payload
    DID carry description_clean, which is part of why it shipped for seven weeks."""
    body = _detail(client, "workday", "BANK").json()
    assert "description_clean" not in body
    assert "Analyse credit risk." not in _detail(client, "workday", "BANK").text


def test_detail_404s_for_an_unknown_role(client):
    assert client.get("/api/jobs/workday/NOPE").status_code == 404


def test_detail_lists_every_board_the_role_is_on(client):
    """The cross-post group is keyed by the shared apply_url, so the detail must
    name both boards even though only one copy is ever listed."""
    body = _detail(client, "jobsdb", "XPOST").json()
    assert sorted(body["sources"]) == ["indeed", "jobsdb"]


def test_detail_of_a_single_source_role_lists_only_itself(client):
    assert _detail(client, "workday", "BANK").json()["sources"] == ["workday"]


def test_detail_does_not_expose_a_guessed_non_primary_copy(client):
    assert client.get("/api/jobs/indeed/XPOST_HIDDEN").status_code == 404


def test_detail_does_not_expose_a_guessed_closed_role(client):
    assert client.get("/api/jobs/workday/CLOSED").status_code == 404


def test_detail_grant_cannot_be_reused_for_another_role(client):
    bank = next(job for job in _get(client, page_size=100)["jobs"] if job["source_id"] == "BANK")
    response = client.get(
        "/api/jobs/workday/IB", headers={"X-Role-Access": bank["access_token"]}
    )
    assert response.status_code == 404


def test_the_board_never_returns_a_closed_role(client):
    """The other half of the rule: browsing stays filtered."""
    assert all(j["closed"] is False for j in _get(client, page_size=100)["jobs"])


# ── The aggregates agree with the board ───────────────────────────────────────

def test_stats_and_jobs_agree_on_what_is_open(client):
    """
    /api/stats and /api/jobs used to spell the visibility rule out separately —
    sixteen hand-typed copies across /api/filters and /api/stats — so they could
    drift on what an open Role is and nothing would fail. They read one constant
    now; this pins them together so a future edit to one has to move the other.
    """
    stats_total = client.get("/api/stats").json()["total_active_jobs"]
    jobs_total = _get(client, page_size=1)["total"]
    assert stats_total == jobs_total


def test_filters_lists_only_sectors_that_are_open(client):
    """Every sector the filter bar offers must return at least one Role — an
    option that yields nothing is the visible symptom of the two disagreeing."""
    facets = client.get("/api/filters", params={"search": "finexscope"}).json()
    for sector in facets["sectors"]:
        assert _get(client, sectors=[sector["name"]], page_size=1)["total"] == sector["count"]


def test_filter_facets_are_scoped_to_the_research_results(client):
    response = client.get("/api/filters", params={"search": "Actuarial"})
    assert response.status_code == 200
    body = response.json()
    assert body["research_total"] == 1
    assert body["companies"] == [{"name": INSURANCE, "count": 1}]
    assert body["sectors"] == [{"name": "Insurance", "count": 1}]


def test_filter_facets_refuse_a_global_catalogue_read(client):
    assert client.get("/api/filters").status_code == 422


def test_stats_counts_internships_the_same_way_the_filter_does(client):
    stats = client.get("/api/stats").json()
    assert stats["internship_count"] == _get(client, is_internship=True, page_size=1)["total"]


# ── The blocker ───────────────────────────────────────────────────────────────
# Publishing the employer's own job description is a licensing problem, and it
# reached production twice over — once as `description_clean[:200]` in every list
# response, once as the whole field in every detail response — because each was
# reviewed as a display detail rather than as a publication decision.
#
# The two tests below are the standing gate. They are deliberately NOT written as
# "no field called description_clean": a differently-named field, a new route, or
# a debug echo would all pass that and still publish the text. Instead every
# fixture row carries a sentinel inside its stored employer text, and the sweep
# asserts no public response contains it. Anything that starts serving the
# employer's words fails here, whatever it is called.

#: Every ungated or Seeker-facing surface that carries Role data. A new one added
#: without a line here is the gap this list exists to make obvious.
def _public_surfaces(client):
    listing = _get(client, page_size=100)
    grant = listing["jobs"][0]["access_token"]
    ref = listing["jobs"][0]
    yield "/api/jobs", client.get("/api/jobs", params={"search": "finexscope"})
    yield "/api/filters", client.get("/api/filters", params={"search": "finexscope"})
    yield "/api/stats", client.get("/api/stats")
    yield "/api/jobs/{source}/{id}", client.get(
        f"/api/jobs/{ref['source']}/{ref['source_id']}",
        headers={"X-Role-Access": grant},
    )
    yield "/sitemap.xml", client.get("/sitemap.xml")
    yield "public teaser page", client.get(
        f"/jobs/{ref['source']}/{ref['source_id']}", follow_redirects=True
    )


def test_no_public_response_echoes_the_employers_own_text(client):
    """The gate. Not 'no field named description_clean' — no employer text, at all,
    under any field name, on any of these surfaces."""
    checked = 0
    for name, response in _public_surfaces(client):
        assert response.status_code in (200, 301, 302, 404), f"{name}: {response.status_code}"
        assert EMPLOYER_TEXT_SENTINEL not in response.text, (
            f"{name} published the employer's own description"
        )
        checked += 1
    assert checked == 6, "a surface was dropped from the sweep without being replaced"


def test_the_sentinel_is_really_in_the_database(client):
    """Guards the guard. If the sentinel stopped being stored, the sweep above
    would pass for the wrong reason and this whole gate would be theatre —
    which is the failure mode CLAUDE.md warns about: a test that passes while
    asserting nothing."""
    body = _get(client, page_size=100)
    assert body["total"] > 0
    # It is searchable, because the index legitimately reads the employer's text
    # server-side. That is the point: stored and indexed, never served.
    found = client.get("/api/jobs", params={"search": EMPLOYER_TEXT_SENTINEL})
    assert found.status_code == 200
    assert found.json()["total"] > 0, "sentinel is not in description_clean any more"
