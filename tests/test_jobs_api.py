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

import pytest
from fastapi.testclient import TestClient

from .support import enrichment, job, make_app, make_bundle, make_jobs_db, signals

# Companies chosen so SECTOR_SQL puts each in a different bucket.
BANKING = "HSBC"
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
    ]
    enrichments = [
        # Salary sorts read COALESCE(disclosed, estimated).
        enrichment(source="workday", source_id="BANK",
                   salary_hkd_min=40_000, salary_hkd_max=60_000,
                   seniority="mid", remote_type="on-site",
                   required_skills='["credit risk"]', years_experience_required=5),
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
        row["description_clean"] = f"{row['description_clean']} finexscope".strip()
    return jobs, enrichments


@pytest.fixture()
def client(tmp_path):
    db = tmp_path / "jobs.db"
    jobs, enrichments = _seed()
    make_jobs_db(db, jobs=jobs, enrichments=enrichments)
    dist = tmp_path / "dist"
    make_bundle(dist)
    return TestClient(make_app(db, dist, tmp_path))


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


# ── Visibility ────────────────────────────────────────────────────────────────

def test_listing_excludes_inactive_and_non_primary(client):
    """The board shows one card per live vacancy: soft-deleted rows and the
    non-primary copies of a cross-posted role are both invisible."""
    ids = _ids(_get(client, page_size=100))
    assert "CLOSED" not in ids
    assert "SECONDARY" not in ids
    assert "XPOST_HIDDEN" not in ids
    assert "XPOST" in ids


def test_listing_refuses_an_unscoped_catalogue_read(client):
    response = client.get("/api/jobs", params={"page_size": 100})
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
    assert body["description_clean"].startswith("Analyse credit risk.")


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
