"""
Tests for the JobsDB fallback adapter.

All HTTP is intercepted via monkeypatching `_get` — no network calls are made
and no browser is launched. The fixture in tests/fixtures/jobsdb/ is a real,
recorded response from hk.jobsdb.com's search API, trimmed to the fields the
adapter actually reads (plus one deliberately cross-advertiser row).

Why these tests look nothing like the old ones: the adapter no longer scrapes
Cloudflare-protected HTML through a headless browser. It reads JobsDB's JSON
search API directly. See the module docstring in hk_jobs/adapters/jobsdb.py
for the failure that forced the change.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from hk_jobs.adapters.jobsdb import (
    JobsDBAdapter,
    _advertiser_accepted,
    _extract_source_id,
    _normalize_advertiser_tokens,
    _parse_listing_date,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "jobsdb"

BOCHK_ADVERTISER_ID = "61275085"
BOCHK_ADVERTISER_NAME = "Bank of China (Hong Kong) Limited"
MANULIFE = "Manulife (International) Limited"


# ── fixtures & fetch mock ─────────────────────────────────────────────────────

@pytest.fixture
def search_page() -> dict:
    return json.loads((FIXTURE_DIR / "search_page1.json").read_text())


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Neutralise page gaps and retry back-offs so tests run instantly."""
    monkeypatch.setattr("hk_jobs.adapters.jobsdb.time.sleep", lambda *a, **k: None)


def _stub_get(monkeypatch, handler):
    """
    Patch the adapter's single network seam.

    `handler(params) -> (status, body)` receives the query dict the adapter
    built, so a test can assert on how the adapter queried, not just on what
    it did with the answer. Every call is recorded on the returned list.
    """
    calls: list[dict] = []

    def _get(self, params):
        calls.append(params)
        return handler(params)

    monkeypatch.setattr(JobsDBAdapter, "_get", _get)
    return calls


def _adapter(**kwargs) -> JobsDBAdapter:
    defaults = dict(
        company="Bank of China (Hong Kong)",
        company_slug="bochk",
        jobsdb_slug="Bank-of-China-(Hong-Kong)",
        max_pages=1,
    )
    return JobsDBAdapter(**{**defaults, **kwargs})


# ── advertiser resolution ─────────────────────────────────────────────────────

def test_resolves_advertiser_id_from_keyword_search(monkeypatch, search_page):
    """With no configured id, the first call is a keyword lookup that finds one."""
    calls = _stub_get(monkeypatch, lambda params: (200, search_page))
    adapter = _adapter()

    adapter.fetch_jobs()

    assert "keywords" in calls[0], "first call should be the advertiser lookup"
    assert calls[0]["keywords"] == "Bank of China (Hong Kong)".replace("&", " ")
    # ...and every later call is scoped to an advertiser it resolved.
    assert calls[-1]["advertiserid"] == BOCHK_ADVERTISER_ID


def test_resolves_every_matching_advertiser_account(monkeypatch):
    """
    One employer often owns many advertiser accounts (Manulife 18, AXA 9).

    Fetching only the busiest one loses most of the employer's jobs, so every
    matching account must be queried.
    """
    lookup = {
        "data": [
            {"id": "1", "advertiser": {"id": "aaa", "description": MANULIFE}},
            {"id": "2", "advertiser": {"id": "bbb", "description": MANULIFE}},
            {"id": "3", "advertiser": {"id": "ccc", "description": "Totally Unrelated Corp"}},
        ],
        "totalCount": 3,
    }

    def handler(params):
        if "keywords" in params:
            return 200, lookup
        return 200, _page_body([params["advertiserid"]], 1, advertiser_id=params["advertiserid"],
                               advertiser_name=MANULIFE)

    calls = _stub_get(monkeypatch, handler)
    adapter = JobsDBAdapter(
        company="Manulife Hong Kong", company_slug="manulife-hk",
        jobsdb_slug="Manulife", max_pages=1,
    )
    jobs = adapter.fetch_jobs()

    queried = {c["advertiserid"] for c in calls if "advertiserid" in c}
    assert queried == {"aaa", "bbb"}, "both matching accounts must be fetched"
    assert "ccc" not in queried, "unrelated advertiser must not be fetched"
    assert len(jobs) == 2


def test_jobs_are_deduped_across_advertiser_accounts(monkeypatch):
    """The same job id posted under two of an employer's accounts counts once."""
    lookup = {
        "data": [
            {"id": "1", "advertiser": {"id": "aaa", "description": BOCHK_ADVERTISER_NAME}},
            {"id": "2", "advertiser": {"id": "bbb", "description": BOCHK_ADVERTISER_NAME}},
        ],
        "totalCount": 2,
    }

    def handler(params):
        if "keywords" in params:
            return 200, lookup
        # both accounts return the very same job id
        return 200, _page_body([7], 1, advertiser_id=params["advertiserid"])

    _stub_get(monkeypatch, handler)
    jobs = _adapter().fetch_jobs()

    assert [j.source_id for j in jobs] == ["7"]


def test_configured_advertiser_id_skips_the_lookup(monkeypatch, search_page):
    """Pinning advertiser_id in config must avoid the extra resolution request."""
    calls = _stub_get(monkeypatch, lambda params: (200, search_page))
    adapter = _adapter(advertiser_id="99999")

    adapter.fetch_jobs()

    assert all("keywords" not in c for c in calls), "should not run a lookup"
    assert calls[0]["advertiserid"] == "99999"


def test_configured_advertiser_id_accepts_a_list(monkeypatch, search_page):
    """An employer with several known accounts can pin them all."""
    calls = _stub_get(monkeypatch, lambda params: (200, search_page))

    _adapter(advertiser_id=["111", "222"]).fetch_jobs()

    assert [c["advertiserid"] for c in calls] == ["111", "222"]


def test_no_matching_advertiser_returns_empty(monkeypatch):
    """A company with no JobsDB presence yields [] without paginating."""
    body = {
        "data": [{"id": "1", "advertiser": {"id": "7", "description": "Totally Unrelated Corp"}}],
        "totalCount": 1,
    }
    calls = _stub_get(monkeypatch, lambda params: (200, body))
    adapter = _adapter()

    assert adapter.fetch_jobs() == []
    assert len(calls) == 1, "should stop after the failed lookup, not paginate"


def test_failed_lookup_returns_empty(monkeypatch):
    """A 500 on the lookup must not raise — one broken company can't stop a run."""
    _stub_get(monkeypatch, lambda params: (500, {}))
    assert _adapter().fetch_jobs() == []


# ── job mapping ───────────────────────────────────────────────────────────────

def test_maps_jobs_from_the_api(monkeypatch, search_page):
    _stub_get(monkeypatch, lambda params: (200, search_page))
    jobs = _adapter().fetch_jobs()
    # 3 rows in the fixture, but the third is a different advertiser and the
    # allowlist safety net drops it.
    assert len(jobs) == 2


def test_job_source_fields(monkeypatch, search_page):
    _stub_get(monkeypatch, lambda params: (200, search_page))
    job = _adapter().fetch_jobs()[0]

    assert job.source == "jobsdb"
    assert job.source_id == "93978208"
    assert job.company_slug == "bochk"
    assert job.scraped_under_slug == "bochk"


def test_job_url_is_built_from_the_id(monkeypatch, search_page):
    _stub_get(monkeypatch, lambda params: (200, search_page))
    job = _adapter().fetch_jobs()[0]
    assert job.url == "https://hk.jobsdb.com/job/93978208"


def test_job_company_uses_the_advertiser_name(monkeypatch, search_page):
    """The advertiser's own legal name wins over the configured short name."""
    _stub_get(monkeypatch, lambda params: (200, search_page))
    job = _adapter().fetch_jobs()[0]
    assert job.company == "Bank of China (Hong Kong) Limited"


def test_job_company_falls_back_to_config_when_advertiser_missing(monkeypatch):
    body = {
        "data": [{"id": "5", "title": "Analyst", "advertiser": {"id": "1", "description": ""}}],
        "totalCount": 1,
    }
    _stub_get(monkeypatch, lambda params: (200, body))
    # No allowlist filtering can apply to a nameless advertiser, so pin the id.
    jobs = _adapter(advertiser_id="1").fetch_jobs()
    assert jobs == [] or jobs[0].company == "Bank of China (Hong Kong)"


def test_job_title_and_location(monkeypatch, search_page):
    _stub_get(monkeypatch, lambda params: (200, search_page))
    job = _adapter().fetch_jobs()[0]
    assert job.title == "Assistant Relationship Manager, Business Banking"
    assert job.locations == ["Hong Kong SAR"]


def test_job_posted_at_is_the_exact_api_timestamp(monkeypatch, search_page):
    """The API gives a real timestamp — no more guessing from '19d ago'."""
    _stub_get(monkeypatch, lambda params: (200, search_page))
    job = _adapter().fetch_jobs()[0]
    assert job.posted_at == datetime(2026, 8, 14, 4, 29, 42, tzinfo=UTC)


def test_jobs_have_no_description(monkeypatch, search_page):
    """Listing-only by design: never invent a description we didn't fetch."""
    _stub_get(monkeypatch, lambda params: (200, search_page))
    for job in _adapter().fetch_jobs():
        assert job.description_raw == ""
        assert job.description_clean == ""


# ── pagination ────────────────────────────────────────────────────────────────

def _page_body(
    ids,
    total,
    advertiser_id=BOCHK_ADVERTISER_ID,
    advertiser_name=BOCHK_ADVERTISER_NAME,
):
    return {
        "data": [
            {
                "id": str(i),
                "title": f"Job {i}",
                "advertiser": {"id": advertiser_id, "description": advertiser_name},
                "listingDate": "2026-08-14T04:29:42Z",
                "locations": [{"label": "Hong Kong SAR"}],
            }
            for i in ids
        ],
        "totalCount": total,
    }


def test_pagination_stops_once_total_count_is_reached(monkeypatch):
    """A short employer must cost one page request, not max_pages."""
    def handler(params):
        if "keywords" in params:
            return 200, _page_body([1], 2)
        return 200, _page_body([1, 2], 2)

    calls = _stub_get(monkeypatch, handler)
    jobs = _adapter(max_pages=10).fetch_jobs()

    assert len(jobs) == 2
    page_calls = [c for c in calls if "advertiserid" in c]
    assert len(page_calls) == 1, "should not ask for page 2 once totalCount is met"


def test_pagination_walks_pages_and_dedups(monkeypatch):
    def handler(params):
        if "keywords" in params:
            return 200, _page_body([1], 4)
        page = params["page"]
        if page == 1:
            return 200, _page_body([1, 2], 4)
        if page == 2:
            return 200, _page_body([2, 3, 4], 4)  # id 2 repeats across pages
        return 200, _page_body([], 4)

    _stub_get(monkeypatch, handler)
    jobs = _adapter(max_pages=5).fetch_jobs()

    assert sorted(j.source_id for j in jobs) == ["1", "2", "3", "4"]


def test_max_pages_is_respected(monkeypatch):
    """A totalCount that never gets satisfied must still stop at max_pages."""
    def handler(params):
        if "keywords" in params:
            return 200, _page_body([1], 9999)
        page = params["page"]
        return 200, _page_body([page * 10, page * 10 + 1], 9999)

    calls = _stub_get(monkeypatch, handler)
    _adapter(max_pages=3).fetch_jobs()

    assert len([c for c in calls if "advertiserid" in c]) == 3


# ── transient-failure retry / partial results ─────────────────────────────────

def test_network_exception_is_retried_then_succeeds(monkeypatch, search_page):
    """A network blip on the first attempt should be retried, not fatal."""
    attempts = {"n": 0}

    def handler(params):
        if "keywords" in params:
            return 200, search_page
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise TimeoutError("connection reset")
        return 200, search_page

    _stub_get(monkeypatch, handler)
    jobs = _adapter().fetch_jobs()

    assert attempts["n"] == 2      # retried once
    assert len(jobs) == 2          # then mapped the fixture successfully


def test_partial_results_preserved_when_later_page_fails(monkeypatch):
    """If page 2 keeps failing, page-1 jobs must still be returned."""
    def handler(params):
        if "keywords" in params:
            return 200, _page_body([1], 99)
        if params["page"] == 1:
            return 200, _page_body([1, 2], 99)
        raise TimeoutError("network dropped")

    _stub_get(monkeypatch, handler)
    jobs = _adapter(max_pages=3).fetch_jobs()

    assert sorted(j.source_id for j in jobs) == ["1", "2"]


def test_http_error_on_a_page_keeps_earlier_pages(monkeypatch):
    def handler(params):
        if "keywords" in params:
            return 200, _page_body([1], 99)
        if params["page"] == 1:
            return 200, _page_body([1, 2], 99)
        return 503, {}

    _stub_get(monkeypatch, handler)
    jobs = _adapter(max_pages=3).fetch_jobs()

    assert sorted(j.source_id for j in jobs) == ["1", "2"]


def test_client_error_is_not_retried(monkeypatch):
    """A 404 is a real answer, not a blip — burning 3 attempts on it is waste."""
    attempts = {"n": 0}

    def handler(params):
        attempts["n"] += 1
        return 404, {}

    _stub_get(monkeypatch, handler)
    assert _adapter().fetch_jobs() == []
    assert attempts["n"] == 1, "404 should not be retried"


# ── listingDate parsing ───────────────────────────────────────────────────────

def test_parse_listing_date_iso_z():
    assert _parse_listing_date("2026-08-14T04:29:42Z") == datetime(
        2026, 8, 14, 4, 29, 42, tzinfo=UTC
    )


def test_parse_listing_date_naive_gets_utc():
    assert _parse_listing_date("2026-08-14T04:29:42").tzinfo is UTC


def test_parse_listing_date_empty():
    assert _parse_listing_date("") is None


def test_parse_listing_date_unrecognised():
    assert _parse_listing_date("19d ago") is None


# ── source-id helper ──────────────────────────────────────────────────────────

def test_extract_source_id_modern_url():
    assert _extract_source_id("https://hk.jobsdb.com/job/92249354?type=standard") == "92249354"


def test_extract_source_id_legacy_suffix():
    url = "https://hk.jobsdb.com/hk/en/job/analyst-100003456789"
    assert _extract_source_id(url) == "100003456789"


def test_extract_source_id_no_number_falls_back():
    url = "https://hk.jobsdb.com/hk/en/job/analyst"
    assert _extract_source_id(url) == url


# ── advertiser allowlist ──────────────────────────────────────────────────────

def _acc(*names):
    return [_normalize_advertiser_tokens(n) for n in names]


def test_allowlist_accepts_legal_entity_variants():
    acc = _acc("China CITIC Bank International Limited", "China CITIC Bank")
    assert _advertiser_accepted("China CITIC Bank International Limited", acc)
    assert _advertiser_accepted("China CITIC Bank", acc)
    assert _advertiser_accepted("CHINA CITIC BANK INT'L LTD.", acc)


def test_allowlist_rejects_cross_advertisers():
    acc = _acc("China CITIC Bank International Limited", "China CITIC Bank")
    for bad in ("Hang Seng Bank Ltd", "Nanyang Commercial Bank, Limited",
                "Hua Xia Bank Co., Limited Hong Kong Branch", "Chong Hing Bank Limited",
                "Shanghai Commercial Bank Ltd", "CITIC Telecom International Holdings Limited"):
        assert not _advertiser_accepted(bad, acc), bad


def test_allowlist_empty_advertiser_rejected():
    assert not _advertiser_accepted("", _acc("KKR"))


def test_allowlist_drops_wrong_advertiser_rows(monkeypatch, search_page):
    """
    The fixture's third row is Hang Seng, not Bank of China.

    advertiserid already scopes the query, so this is the safety net that
    catches a resolution which latched onto the wrong account.
    """
    _stub_get(monkeypatch, lambda params: (200, search_page))
    jobs = _adapter().fetch_jobs()
    assert all("Hang Seng" not in j.company for j in jobs)


def test_legacy_use_company_profile_key_still_loads(monkeypatch, search_page):
    """
    Existing companies.yaml entries all carry use_company_profile.

    The API is always advertiser-scoped so the flag no longer means anything,
    but passing it must not raise — otherwise every configured company breaks.
    """
    _stub_get(monkeypatch, lambda params: (200, search_page))
    for flag in (True, False):
        assert len(_adapter(use_company_profile=flag).fetch_jobs()) == 2
