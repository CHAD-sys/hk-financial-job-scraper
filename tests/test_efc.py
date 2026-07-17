"""
Tests for the eFinancialCareers adapter (JSON API).

The HTTP layer is mocked via monkeypatching _fetch_page — no network calls.
These verify the API→Job mapping, pagination, and helpers. They do not prove the
live API shape; run scripts/try_efc_live.py to check against the real endpoint.
"""


from hk_jobs.adapters.efc import (
    EfcAdapter,
    _extract_efc_id,
    _map_employment_type,
    _parse_iso,
)

_SITE = "https://www.efinancialcareers.hk"


def _api_job(**over):
    d = {
        "jobId": 23991670,
        "id": "kVBdqj4wSq1dg7Zg",
        "title": "Senior Sanction Compliance Manager (Sanction Advisory)",
        "detailsPageUrl": "/jobs-Hong_Kong-Hong_Kong-Senior_Sanction_Compliance_Manager.id23991670",
        "clientBrandName": "Bank Of China (Hong Kong) Limited",
        "companyName": "Bank Of China (Hong Kong) Limited",
        "jobLocation": {"displayName": "Hong Kong", "city": "Hong Kong", "country": "Hong Kong"},
        "employmentType": "Full time",
        "postedDate": "2026-07-14T10:15:01.567Z",
        "description": "<p>Manage <b>sanctions</b> risk.</p>",
        "minSalary": 0, "maxSalary": 0, "salaryCurrency": "HKD",
    }
    d.update(over)
    return d


def _adapter(pages, monkeypatch, **cfg):
    """pages: list of (data_list, page_count) returned successively by _fetch_page."""
    calls = {"n": 0}

    def _mock_fetch_page(self, client, page):
        calls["n"] += 1
        return pages[page - 1]

    monkeypatch.setattr(EfcAdapter, "_fetch_page", _mock_fetch_page)
    monkeypatch.setattr(EfcAdapter, "_client", lambda self, timeout=25.0: _DummyClient())
    kw = dict(company="Bank of China (HK)", company_slug="bochk",
              efc_employer="Bank of China (Hong Kong) Limited",
              efc_brand="Bank Of China (Hong Kong) Limited")
    kw.update(cfg)
    a = EfcAdapter(**kw)
    a._calls = calls
    return a


class _DummyClient:
    def __enter__(self): return self
    def __exit__(self, *a): return False


# ── mapping ────────────────────────────────────────────────────────────────────

def test_maps_api_job_to_canonical(monkeypatch):
    a = _adapter([([_api_job()], 1)], monkeypatch)
    jobs = a.fetch_jobs()
    assert len(jobs) == 1
    j = jobs[0]
    assert j.source == "efinancialcareers"
    assert j.source_id == "23991670"                     # jobId
    assert j.company_slug == "bochk"
    assert j.company == "Bank Of China (Hong Kong) Limited"
    assert j.url == _SITE + _api_job()["detailsPageUrl"]
    assert j.locations == ["Hong Kong"]
    assert j.employment_type == "full-time"
    assert j.posted_at is not None and j.posted_at.year == 2026
    assert "sanctions" in j.description_clean.lower()    # HTML stripped
    assert "<b>" in j.description_raw                     # raw kept


def test_salary_zero_becomes_none(monkeypatch):
    a = _adapter([([_api_job(minSalary=0, maxSalary=0)], 1)], monkeypatch)
    j = a.fetch_jobs()[0]
    assert j.salary_min is None and j.salary_max is None and j.salary_currency is None


def test_salary_present_kept(monkeypatch):
    a = _adapter([([_api_job(minSalary=50000, maxSalary=90000)], 1)], monkeypatch)
    j = a.fetch_jobs()[0]
    assert j.salary_min == 50000 and j.salary_max == 90000 and j.salary_currency == "HKD"


# ── pagination ──────────────────────────────────────────────────────────────────

def test_follows_multiple_pages(monkeypatch):
    p1 = ([_api_job(jobId=1)], 2)
    p2 = ([_api_job(jobId=2)], 2)
    a = _adapter([p1, p2], monkeypatch)
    jobs = a.fetch_jobs()
    assert {j.source_id for j in jobs} == {"1", "2"}
    assert a._calls["n"] == 2


def test_stops_at_page_count(monkeypatch):
    a = _adapter([([_api_job()], 1), ([_api_job(jobId=999)], 1)], monkeypatch)
    a.fetch_jobs()
    assert a._calls["n"] == 1  # page_count=1 → only one request


def test_empty_result(monkeypatch):
    a = _adapter([([], 1)], monkeypatch)
    assert a.fetch_jobs() == []


def test_non_hk_jobs_are_filtered_out(monkeypatch):
    """A global brand returns worldwide jobs; only Hong Kong ones are kept."""
    hk = _api_job(jobId=1, jobLocation={"country": "Hong Kong", "displayName": "Hong Kong"})
    de = _api_job(jobId=2, jobLocation={"country": "Germany", "displayName": "Frankfurt"})
    us = _api_job(jobId=3, jobLocation={"country": "United States", "displayName": "New York"})
    a = _adapter([([hk, de, us], 1)], monkeypatch)
    jobs = a.fetch_jobs()
    assert [j.source_id for j in jobs] == ["1"]


# ── helpers ─────────────────────────────────────────────────────────────────────

def test_employment_type_map():
    assert _map_employment_type("Full time") == "full-time"
    assert _map_employment_type("Part time") == "part-time"
    assert _map_employment_type("Contract") == "contract"
    assert _map_employment_type("Internship") == "internship"
    assert _map_employment_type("Weird") is None
    assert _map_employment_type(None) is None


def test_parse_iso():
    dt = _parse_iso("2026-07-14T10:15:01.567Z")
    assert dt is not None and dt.tzinfo is not None
    assert _parse_iso("nonsense") is None
    assert _parse_iso(None) is None


def test_extract_id():
    assert _extract_efc_id("/jobs-x.id23991670") == "23991670"
    assert _extract_efc_id("/no-id-here") == "/no-id-here"


def test_brand_defaults_to_employer():
    a = EfcAdapter(company="X", company_slug="x", efc_employer="Acme Capital")
    assert a.efc_brand == "Acme Capital"
