"""
Tests for the SAP SuccessFactors (RMK) adapter.

All HTTP is intercepted by monkeypatching _fetch_url — no network calls are
made. The fixtures in tests/fixtures/successfactors/ are trimmed captures of
careers.hkjc.com taken on 2026-07-29; the job rows and the detail page's
div.job are verbatim live markup, so these tests exercise the real page shape.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from hk_jobs.adapters.successfactors import (
    SuccessFactorsAdapter,
    _extract_description,
    _extract_source_id,
    _map_shift_type,
    _parse_listing_date,
    _parse_listing_html,
    _tidy_text,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "successfactors"
BASE = "https://careers.hkjc.com"


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def page1_html():
    return (FIXTURE_DIR / "listing_page1.html").read_text(encoding="utf-8")


@pytest.fixture
def page2_html():
    return (FIXTURE_DIR / "listing_page2.html").read_text(encoding="utf-8")


@pytest.fixture
def detail_html():
    return (FIXTURE_DIR / "detail.html").read_text(encoding="utf-8")


def _adapter(monkeypatch, pages, detail=None, **kwargs):
    """
    Build an adapter whose _fetch_url serves `pages` in order, and `detail`
    for any /job/ URL. Records every URL requested on adapter._calls.
    """
    monkeypatch.setattr("hk_jobs.adapters.successfactors.time.sleep", lambda *a, **k: None)
    calls: list[str] = []
    remaining = list(pages)

    def _mock(self, url: str) -> tuple[int, str]:
        calls.append(url)
        if "/job/" in url:
            return (200, detail) if detail else (404, "")
        return (200, remaining.pop(0)) if remaining else (200, "")

    monkeypatch.setattr(SuccessFactorsAdapter, "_fetch_url", _mock)
    kwargs.setdefault("fetch_details", False)
    kwargs.setdefault("search_query", "Finance")
    a = SuccessFactorsAdapter(
        company="Hong Kong Jockey Club",
        company_slug="hkjc",
        sf_host="careers.hkjc.com",
        **kwargs,
    )
    a._calls = calls
    return a


# ── pure helpers ──────────────────────────────────────────────────────────────

def test_extract_source_id_from_job_url():
    href = "/job/Causeway-Bay-Deputy-Executive-Manager%2C-Finance-Hong/1358056566/"
    assert _extract_source_id(href) == "1358056566"


def test_extract_source_id_absolute_url():
    href = "https://careers.hkjc.com/job/Happy-Valley-Manager%2C-Investments-Hong/1328764066/"
    assert _extract_source_id(href) == "1328764066"


def test_extract_source_id_unparseable_falls_back_to_href():
    """An unrecognised link must still yield a stable id, not an empty collision."""
    assert _extract_source_id("/careers/apply") == "/careers/apply"
    assert _extract_source_id("") == ""


def test_parse_listing_date_rmk_format():
    assert _parse_listing_date("26 Jul 2026") == datetime(2026, 7, 26, tzinfo=UTC)


def test_parse_listing_date_single_digit_day():
    assert _parse_listing_date("3 Jun 2026") == datetime(2026, 6, 3, tzinfo=UTC)


@pytest.mark.parametrize("bad", ["", "   ", "yesterday", "Just posted"])
def test_parse_listing_date_unrecognised_returns_none(bad):
    """A missing posted_at is survivable; an exception mid-run is not."""
    assert _parse_listing_date(bad) is None


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Full-time", "full-time"),
        ("full time", "full-time"),
        ("Part-time", "part-time"),
        ("Contract", "contract"),
        ("Temporary", "contract"),
        ("Internship", "internship"),
        ("Something Else", None),
        ("", None),
    ],
)
def test_map_shift_type(raw, expected):
    assert _map_shift_type(raw) == expected


# ── listing parse ─────────────────────────────────────────────────────────────

def test_parse_listing_html_extracts_every_row(page1_html):
    cards = _parse_listing_html(page1_html, BASE)
    assert len(cards) == 6


def test_parse_listing_html_skips_header_row(page1_html):
    """RMK's header <tr> shares the data-row class but has no title link."""
    assert all(c["title"] and c["source_id"] for c in _parse_listing_html(page1_html, BASE))


def test_parse_listing_html_field_mapping(page1_html):
    first = _parse_listing_html(page1_html, BASE)[0]
    assert first["title"] == "Deputy Executive Manager, Finance"
    assert first["source_id"] == "1358056566"
    assert first["url"].startswith("https://careers.hkjc.com/job/")
    assert first["facility"] == "Finance"
    assert first["location"] == "Causeway Bay, Hong Kong Island, HK"
    assert first["shift_type"] == "Full-time"
    assert first["posted"] == "26 Jul 2026"


def test_parse_listing_html_empty_input():
    assert _parse_listing_html("", BASE) == []
    assert _parse_listing_html("<html><body>no jobs</body></html>", BASE) == []


# ── facility allowlist (the q= full-text precision problem) ───────────────────

def test_facility_allowlist_drops_non_finance_rows(monkeypatch, page1_html):
    """
    q=Finance is a full-text match: the page-1 fixture holds 4 Finance rows and
    2 'Charities and Community' rows that merely mention the word.
    """
    a = _adapter(monkeypatch, [page1_html], facility_allowlist=["Finance"])
    jobs = a.fetch_jobs()
    assert len(jobs) == 4
    assert {j.department for j in jobs} == {"Finance"}


def test_no_allowlist_keeps_everything(monkeypatch, page1_html):
    a = _adapter(monkeypatch, [page1_html])
    assert len(a.fetch_jobs()) == 6


def test_allowlist_is_case_insensitive(monkeypatch, page1_html):
    a = _adapter(monkeypatch, [page1_html], facility_allowlist=["fInAnCe"])
    assert len(a.fetch_jobs()) == 4


# ── pagination ────────────────────────────────────────────────────────────────

def test_pagination_uses_startrow_steps(monkeypatch, page1_html, page2_html):
    monkeypatch.setattr("hk_jobs.adapters.successfactors._PAGE_SIZE", 6)
    a = _adapter(monkeypatch, [page1_html, page2_html])
    a.fetch_jobs()
    assert "startrow" not in a._calls[0]           # page 1 carries no startrow
    assert "startrow=6" in a._calls[1]


def test_pagination_dedups_repeated_rows(monkeypatch, page1_html, page2_html):
    """
    Page 2 repeats page 1's first posting. 6 + 4 rows must yield 9 unique jobs,
    not 10.
    """
    monkeypatch.setattr("hk_jobs.adapters.successfactors._PAGE_SIZE", 6)
    a = _adapter(monkeypatch, [page1_html, page2_html])
    jobs = a.fetch_jobs()
    assert len(jobs) == 9
    assert len({j.source_id for j in jobs}) == 9


def test_short_page_stops_pagination(monkeypatch, page1_html, page2_html):
    """A page with fewer than _PAGE_SIZE rows is the last page — fetch no more."""
    a = _adapter(monkeypatch, [page1_html, page2_html])  # real _PAGE_SIZE = 25
    a.fetch_jobs()
    assert len(a._calls) == 1


def test_truncation_at_max_pages_warns_loudly(monkeypatch, page1_html, caplog):
    """
    Silent truncation looks identical to 'that's all the jobs'. Since we now
    paginate the whole listing rather than searching, an under-set max_pages is
    the one way to quietly lose roles — it must shout.
    """
    monkeypatch.setattr("hk_jobs.adapters.successfactors._PAGE_SIZE", 6)
    # Every page is full (6 rows) and every row is unique, so the loop can only
    # end by exhausting max_pages.
    pages = []
    for n in range(3):
        pages.append(page1_html.replace('/1358056566/', f'/999000{n}/'))
    a = _adapter(monkeypatch, pages, max_pages=3)
    with caplog.at_level("WARNING"):
        a.fetch_jobs()
    assert any("TRUNCATED" in r.message for r in caplog.records)


def test_no_truncation_warning_on_short_final_page(monkeypatch, page1_html, page2_html, caplog):
    monkeypatch.setattr("hk_jobs.adapters.successfactors._PAGE_SIZE", 6)
    a = _adapter(monkeypatch, [page1_html, page2_html], max_pages=5)
    with caplog.at_level("WARNING"):
        a.fetch_jobs()
    assert not any("TRUNCATED" in r.message for r in caplog.records)


def test_empty_search_query_paginates_whole_listing(monkeypatch, page1_html):
    """search_query='' must produce the bare listing URL, not a q=Finance search."""
    a = _adapter(monkeypatch, [page1_html], search_query="")
    a.fetch_jobs()
    assert a._calls[0] == "https://careers.hkjc.com/search/?q="


def test_max_pages_is_respected(monkeypatch, page1_html):
    monkeypatch.setattr("hk_jobs.adapters.successfactors._PAGE_SIZE", 6)
    a = _adapter(monkeypatch, [page1_html, page1_html, page1_html], max_pages=1)
    a.fetch_jobs()
    assert len(a._calls) == 1


# ── Job mapping ───────────────────────────────────────────────────────────────

def test_job_field_mapping(monkeypatch, page1_html):
    a = _adapter(monkeypatch, [page1_html], facility_allowlist=["Finance"])
    job = a.fetch_jobs()[0]
    assert job.source == "successfactors"
    assert job.source_id == "1358056566"
    assert job.company == "Hong Kong Jockey Club"
    assert job.company_slug == "hkjc"
    assert job.title == "Deputy Executive Manager, Finance"
    assert job.department == "Finance"
    assert job.employment_type == "full-time"
    assert job.posted_at == datetime(2026, 7, 26, tzinfo=UTC)
    assert job.is_active is True


def test_location_kept_whole_not_split_on_commas(monkeypatch, page1_html):
    """
    'Causeway Bay, Hong Kong Island, HK' is ONE office. Splitting on commas
    would fabricate three locations out of one.
    """
    a = _adapter(monkeypatch, [page1_html], facility_allowlist=["Finance"])
    assert a.fetch_jobs()[0].locations == ["Causeway Bay, Hong Kong Island, HK"]


# ── detail pages ──────────────────────────────────────────────────────────────

def test_extract_description_strips_script_and_style(detail_html):
    """
    RMK inlines <style> and <script> inside div.job. If they survive, CSS rules
    and JS end up in description_clean and get fed to the enricher.
    """
    raw = _extract_description(detail_html)
    assert raw, "expected a description from div.job"
    assert "<script" not in raw.lower()
    assert "<style" not in raw.lower()
    assert "navigator.clipboard" not in raw
    assert "font-weight: bold" not in raw


def test_tidy_text_drops_whitespace_only_lines():
    """
    RMK's nested empty blocks leave lines holding a single space or \\xa0.
    _strip_html's \\n{3,} collapse can't see those — they aren't empty.
    """
    raw = "Job Summary\n \n\xa0\n \n\nThe job holder\n \n \nApply now"
    assert _tidy_text(raw) == "Job Summary\nThe job holder\nApply now"


def test_tidy_text_preserves_real_content_lines():
    assert _tidy_text("A\nB\nC") == "A\nB\nC"
    assert _tidy_text("") == ""


def test_description_clean_is_mostly_content(monkeypatch, page1_html, detail_html):
    """Guards the regression: >70% of stored lines were once whitespace-only."""
    a = _adapter(
        monkeypatch, [page1_html], detail=detail_html,
        facility_allowlist=["Finance"], fetch_details=True,
    )
    clean = a.fetch_jobs()[0].description_clean
    lines = clean.split("\n")
    assert lines, "expected some description text"
    assert all(ln.strip() for ln in lines), "no whitespace-only lines should survive"
    assert "\xa0" not in clean


def test_extract_description_absent_returns_empty():
    assert _extract_description("<html><body><p>no job div</p></body></html>") == ""
    assert _extract_description("") == ""


def test_fetch_details_populates_description(monkeypatch, page1_html, detail_html):
    a = _adapter(
        monkeypatch, [page1_html], detail=detail_html,
        facility_allowlist=["Finance"], fetch_details=True,
    )
    jobs = a.fetch_jobs()
    assert all(j.description_raw for j in jobs)
    assert all("Job Summary" in j.description_clean for j in jobs)
    # clean text must carry no markup and none of the stripped JS
    assert all("<" not in j.description_clean for j in jobs)
    assert all("clipboard" not in j.description_clean for j in jobs)


def test_fetch_details_false_makes_no_detail_calls(monkeypatch, page1_html):
    a = _adapter(monkeypatch, [page1_html], fetch_details=False)
    jobs = a.fetch_jobs()
    assert not any("/job/" in u for u in a._calls)
    assert all(j.description_clean == "" for j in jobs)


def test_failed_detail_page_keeps_the_job(monkeypatch, page1_html):
    """A dead detail page must not drop the posting — listing data still counts."""
    a = _adapter(
        monkeypatch, [page1_html], detail=None,  # /job/ URLs return 404
        facility_allowlist=["Finance"], fetch_details=True,
    )
    jobs = a.fetch_jobs()
    assert len(jobs) == 4
    assert all(j.description_clean == "" for j in jobs)


# ── failure isolation ─────────────────────────────────────────────────────────

def test_non_200_listing_returns_empty_list(monkeypatch):
    monkeypatch.setattr("hk_jobs.adapters.successfactors.time.sleep", lambda *a, **k: None)
    monkeypatch.setattr(
        SuccessFactorsAdapter, "_fetch_url", lambda self, url: (503, "")
    )
    a = SuccessFactorsAdapter(
        company="HKJC", company_slug="hkjc", sf_host="careers.hkjc.com",
    )
    assert a.fetch_jobs() == []


def test_transport_error_is_swallowed(monkeypatch):
    """One broken company must never stop the other 190-odd."""
    monkeypatch.setattr("hk_jobs.adapters.successfactors.time.sleep", lambda *a, **k: None)

    def _boom(self, url):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(SuccessFactorsAdapter, "_fetch_url", _boom)
    a = SuccessFactorsAdapter(
        company="HKJC", company_slug="hkjc", sf_host="careers.hkjc.com",
    )
    assert a.fetch_jobs() == []


def test_host_normalisation_strips_scheme():
    a = SuccessFactorsAdapter(
        company="HKJC", company_slug="hkjc", sf_host="https://careers.hkjc.com/",
    )
    assert a.sf_host == "careers.hkjc.com"
    assert a._listing_url(0).startswith("https://careers.hkjc.com/search/?q=")


def test_search_query_is_url_encoded():
    a = SuccessFactorsAdapter(
        company="HKJC", company_slug="hkjc", sf_host="careers.hkjc.com",
        search_query="Finance & Risk",
    )
    assert "Finance+%26+Risk" in a._listing_url(0)


# ── registry wiring ───────────────────────────────────────────────────────────

def test_adapter_is_registered():
    from hk_jobs.adapters import ADAPTERS

    assert ADAPTERS["successfactors"] is SuccessFactorsAdapter


def test_config_requires_sf_host():
    from hk_jobs.config import CompanyConfig, _validate

    bad = CompanyConfig(name="X", slug="x", adapter="successfactors", enabled=True, config={})
    with pytest.raises(ValueError, match="sf_host"):
        _validate(bad)
