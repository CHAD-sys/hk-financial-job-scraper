"""Greenhouse adapter, run against trimmed real boards recorded 28 Oct 2026."""

import json
from pathlib import Path

import httpx
import pytest

from hk_jobs.adapters import greenhouse
from hk_jobs.adapters.greenhouse import GreenhouseAdapter, is_hong_kong

FIXTURES = Path(__file__).parent / "fixtures" / "greenhouse"


def _board(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def _adapter(monkeypatch, board: dict, token: str = "x") -> GreenhouseAdapter:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "boards-api.greenhouse.io"
        assert request.url.params["content"] == "true"
        return httpx.Response(200, json=board)

    adapter = GreenhouseAdapter("Acme", "acme", board_token=token)
    monkeypatch.setattr(
        GreenhouseAdapter,
        "_client",
        lambda self, timeout=20.0: httpx.Client(transport=httpx.MockTransport(handle)),
    )
    return adapter


@pytest.mark.parametrize("name,hk,total", [("flowtraders", 4, 6), ("hrt", 3, 5), ("squarepoint", 4, 6)])
def test_only_hong_kong_roles_are_returned(monkeypatch, name, hk, total):
    board = _board(name)
    assert len(board["jobs"]) == total
    jobs = _adapter(monkeypatch, board).fetch_jobs()
    assert len(jobs) == hk
    assert all(j.locations == ["Hong Kong"] and j.source == "greenhouse" for j in jobs)


def test_a_role_listed_under_another_city_is_found_through_its_offices():
    """HRT's headline location says Singapore; only `offices` says Hong Kong."""
    board = _board("hrt")
    mismatched = [
        j for j in board["jobs"]
        if "hong kong" not in j["location"]["name"].lower() and is_hong_kong(j)
    ]
    assert mismatched, "fixture must contain a location/offices mismatch"


def test_a_role_with_no_hong_kong_signal_is_dropped():
    assert not is_hong_kong({"location": {"name": "London"}, "offices": [{"name": "London"}]})
    assert not is_hong_kong({"location": None, "offices": None})


def test_office_location_field_counts_too():
    """Flow Traders names the office 'Hong Kong office'; its location is 'Hong Kong'."""
    assert is_hong_kong({"location": {"name": "Amsterdam"}, "offices": [{"name": "HK", "location": "Hong Kong"}]})


def test_fields_map_to_the_canonical_job(monkeypatch):
    job = _adapter(monkeypatch, _board("squarepoint"), "squarepointcapital").fetch_jobs()[0]
    assert job.source_id.isdigit()
    assert job.url.startswith("http")
    assert job.title == job.title.strip() and job.title
    assert job.posted_at is not None
    assert "&lt;" not in job.description_raw  # unescaped once
    assert job.description_clean  # fixture text is cut mid-tag, so only check it is non-empty


def test_duplicate_ids_collapse(monkeypatch):
    board = _board("flowtraders")
    board["jobs"] = board["jobs"] + board["jobs"]
    assert len(_adapter(monkeypatch, board).fetch_jobs()) == 4


def test_null_first_published_falls_back_to_updated_at(monkeypatch):
    board = _board("hrt")
    for j in board["jobs"]:
        j["first_published"] = None
    jobs = _adapter(monkeypatch, board).fetch_jobs()
    assert all(j.posted_at is not None for j in jobs)


def test_empty_board_is_an_empty_list_not_an_error(monkeypatch):
    assert _adapter(monkeypatch, {"jobs": []}).fetch_jobs() == []


def test_http_failure_is_isolated(monkeypatch):
    adapter = GreenhouseAdapter("Acme", "acme", board_token="x")
    monkeypatch.setattr(greenhouse, "with_retry", lambda fn: (_ for _ in ()).throw(httpx.ConnectError("down")))
    assert adapter.fetch_jobs() == []

