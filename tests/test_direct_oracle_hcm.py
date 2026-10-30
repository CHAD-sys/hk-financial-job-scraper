"""Oracle HCM Candidate Experience fetchers (JPMorgan, Chubb, Schroders HK), offline.

Fixtures are trimmed real responses recorded 30 Oct 2026."""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from hk_jobs.adapters import direct_oracle_hcm as m

FIXTURES = Path(__file__).parent / "fixtures" / "direct_sites"


def _load(slug, kind):
    return json.loads((FIXTURES / f"{slug}_{kind}.json").read_text())


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(m, "REQUEST_DELAY", 0)


def _client(slug, rows=None, details=None, total=None, log=None, fail_detail=()):
    listing = _load(slug, "list")
    rows = listing["requisitionList"] if rows is None else rows
    details = _load(slug, "details") if details is None else details

    def handler(request: httpx.Request) -> httpx.Response:
        if log is not None:
            log.append(request.url)
        finder = request.url.params["finder"]
        if request.url.path.endswith("recruitingCEJobRequisitions"):
            offset = int(re.search(r"offset=(\d+)", finder).group(1))
            limit = int(re.search(r"limit=(\d+)", finder).group(1))
            item = {
                "TotalJobsCount": len(rows) if total is None else total,
                "requisitionList": rows[offset : offset + limit],
            }
            return httpx.Response(200, json={"items": [item]})
        req_id = re.search(r'Id="(\d+)"', finder).group(1)
        if req_id in fail_detail:
            return httpx.Response(500)
        found = details.get(req_id)
        return httpx.Response(200, json={"items": [found] if found else []})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_registered_slugs():
    assert set(m.SITE_FETCHERS) == {"jpmorgan", "chubb", "schroders-hk"}


@pytest.mark.parametrize(
    "slug,company,host,site,count",
    [
        ("jpmorgan", "JPMorgan", "jpmc.fa.oraclecloud.com", "CX_1001", 4),
        ("chubb", "Chubb", "fa-ewgu-saasfaprod1.fa.ocs.oraclecloud.com", "CX_2001", 3),
        ("schroders-hk", "Schroders", "ekbq.fa.em2.oraclecloud.com", "CX_2", 3),
    ],
)
def test_field_mapping(slug, company, host, site, count):
    jobs = m.SITE_FETCHERS[slug](_client(slug), company, slug)
    assert len(jobs) == count
    for j in jobs:
        assert j.source == "direct_site" and j.company == company
        assert j.company_slug == slug and j.scraped_under_slug == slug
        assert j.source_id == f"{slug}:{j.url.rsplit('/', 1)[1]}"
        assert j.url == f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{j.source_id.split(':')[1]}"
        assert j.title == j.title.strip() and "  " not in j.title
        assert j.posted_at is not None and j.posted_at.tzinfo is not None
        assert "<" in j.description_raw and "<" not in j.description_clean
        assert len(j.description_clean) > 100
        assert j.department


def test_real_posted_timestamp_comes_from_detail():
    jobs = m.fetch_schroders(_client("schroders-hk"), "Schroders", "schroders-hk")
    by_id = {j.source_id: j for j in jobs}
    assert by_id["schroders-hk:1709"].posted_at == datetime(
        2026, 10, 24, 12, 17, 16, tzinfo=timezone.utc
    )
    assert by_id["schroders-hk:1709"].department == "Product & Solutions"


def test_posted_date_falls_back_to_list_date_when_detail_missing():
    jobs = m.fetch_chubb(_client("chubb", details={}), "Chubb", "chubb")
    assert jobs and all(j.posted_at is not None for j in jobs)
    assert jobs[0].posted_at == datetime(2026, 10, 30, tzinfo=timezone.utc)
    jp = m.fetch_jpmorgan(_client("jpmorgan", details={}), "JPMorgan", "jpmorgan")
    assert all(j.description_clean for j in jp)  # list ShortDescriptionStr


def test_detail_http_error_falls_back_to_list_text():
    jobs = m.fetch_chubb(_client("chubb", fail_detail={"38113"}), "Chubb", "chubb")
    assert len(jobs) == 3
    first = next(j for j in jobs if j.source_id == "chubb:38113")
    assert first.posted_at == datetime(2026, 10, 30, tzinfo=timezone.utc)
    other = next(j for j in jobs if j.source_id == "chubb:37200")
    assert other.description_clean and other.posted_at.hour != 0


def test_hong_kong_filter_by_country_and_secondary_location():
    rows = _load("jpmorgan", "list")["requisitionList"]
    sg_with_hk = next(r for r in rows if r["PrimaryLocationCountry"] == "SG")
    assert m.is_hong_kong(sg_with_hk)
    only_sg = {**sg_with_hk, "Id": "999", "secondaryLocations": []}
    other = {**rows[1], "Id": "998", "PrimaryLocationCountry": "SG", "secondaryLocations": []}
    assert not m.is_hong_kong(only_sg) and not m.is_hong_kong(other)

    details = {**_load("jpmorgan", "details")}
    jobs = m.fetch_jpmorgan(
        _client("jpmorgan", rows=[only_sg, other] + rows[:2], details=details),
        "JPMorgan",
        "jpmorgan",
    )
    ids = {j.source_id for j in jobs}
    assert "jpmorgan:999" not in ids and "jpmorgan:998" not in ids
    assert "jpmorgan:210756183" in ids  # SG primary, HK secondary
    sg_job = next(j for j in jobs if j.source_id == "jpmorgan:210756183")
    assert sg_job.locations == ["Singapore, Singapore", "Hong Kong"]


def test_request_uses_facet_and_site_number():
    log = []
    m.fetch_chubb(_client("chubb", log=log), "Chubb", "chubb")
    finder = log[0].params["finder"]
    assert "siteNumber=CX_2001" in finder and "locationId=300000000467173" in finder
    assert "keyword" not in str(log[0])
    log2 = []
    m.fetch_jpmorgan(_client("jpmorgan", log=log2), "JPMorgan", "jpmorgan")
    assert "selectedLocationsFacet=300000000289330" in log2[0].params["finder"]


def test_pagination_walks_all_pages_and_stops(monkeypatch):
    monkeypatch.setattr(m, "PAGE_SIZE", 2)
    log = []
    jobs = m.fetch_schroders(_client("schroders-hk", log=log), "Schroders", "schroders-hk")
    lists = [u for u in log if u.path.endswith("recruitingCEJobRequisitions")]
    assert len(jobs) == 3 and len(lists) == 2  # 2 + 1 rows, then offset >= total
    assert "offset=2" in lists[1].params["finder"]


def test_empty_result():
    client = _client("chubb", rows=[], details={})
    assert m.fetch_chubb(client, "Chubb", "chubb") == []


def test_duplicate_ids_collapse(monkeypatch):
    rows = _load("schroders-hk", "list")["requisitionList"]
    dup = [rows[0], rows[1], dict(rows[0]), rows[2]]
    jobs = m.fetch_schroders(
        _client("schroders-hk", rows=dup, total=4), "Schroders", "schroders-hk"
    )
    ids = [j.source_id for j in jobs]
    assert len(ids) == len(set(ids)) == 3


def test_repeating_page_stops_instead_of_looping(monkeypatch):
    monkeypatch.setattr(m, "PAGE_SIZE", 3)
    rows = _load("schroders-hk", "list")["requisitionList"]
    # claims 50 rows but every page returns the same three
    def handler(request):
        item = {"TotalJobsCount": 50, "requisitionList": rows}
        return httpx.Response(200, json={"items": [item]})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert len(m.list_requisitions(client, "h", "CX_2", "selectedLocationsFacet", "1")) == 3


def test_inconsistent_listing_raises():
    with pytest.raises(ValueError):  # total says 5 but first page is empty
        m.fetch_chubb(_client("chubb", rows=[], total=5), "Chubb", "chubb")
    broken = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"items": [{}]}))
    )
    with pytest.raises(ValueError):  # unknown site: 200 without TotalJobsCount
        m.fetch_chubb(broken, "Chubb", "chubb")
    gone = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"items": []}))
    )
    with pytest.raises(ValueError):
        m.fetch_chubb(gone, "Chubb", "chubb")


def test_entity_escaped_description_unescaped_once_but_real_html_untouched():
    assert m._unescape_once("&lt;p&gt;a &amp;amp; b&lt;/p&gt;") == "<p>a &amp; b</p>"
    assert m._unescape_once("<p>a &amp; b</p>") == "<p>a &amp; b</p>"


def test_http_error_on_listing_propagates():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403)))
    with pytest.raises(httpx.HTTPStatusError):
        m.fetch_jpmorgan(client, "JPMorgan", "jpmorgan")
