"""Tests for hk_jobs/adapters/base.py."""

import pytest

from hk_jobs.adapters import ADAPTERS, BaseAdapter
from hk_jobs.schema import Job

# ── Minimal concrete subclass used throughout these tests ─────────────────────

class _EchoAdapter(BaseAdapter):
    source_name = "echo"

    def fetch_jobs(self) -> list[Job]:
        return [
            Job(
                source=self.source_name,
                source_id="TEST-1",
                company=self.company,
                company_slug=self.company_slug,
                url="https://example.com/jobs/1",
                title="Test Role",
                locations=["Hong Kong"],
            )
        ]


class _BrokenAdapter(BaseAdapter):
    source_name = "broken"

    def fetch_jobs(self) -> list[Job]:
        raise RuntimeError("network down")


# ── Instantiation ─────────────────────────────────────────────────────────────

def test_cannot_instantiate_base_directly():
    with pytest.raises(TypeError):
        BaseAdapter(company="HSBC", company_slug="hsbc")  # type: ignore[abstract]


def test_concrete_subclass_stores_fields():
    adapter = _EchoAdapter(company="HSBC", company_slug="hsbc")
    assert adapter.company == "HSBC"
    assert adapter.company_slug == "hsbc"
    assert adapter.config == {}


def test_kwargs_stored_in_config():
    adapter = _EchoAdapter(company="HSBC", company_slug="hsbc", tenant="hsbc", site="External")
    assert adapter.config == {"tenant": "hsbc", "site": "External"}


# ── fetch_jobs ────────────────────────────────────────────────────────────────

def test_fetch_jobs_returns_job_objects():
    adapter = _EchoAdapter(company="HSBC", company_slug="hsbc")
    jobs = adapter.fetch_jobs()
    assert len(jobs) == 1
    assert isinstance(jobs[0], Job)
    assert jobs[0].company == "HSBC"
    assert jobs[0].title == "Test Role"


# ── _safe_fetch ───────────────────────────────────────────────────────────────

def test_safe_fetch_returns_result_on_success():
    adapter = _EchoAdapter(company="HSBC", company_slug="hsbc")
    jobs = adapter._safe_fetch(adapter.fetch_jobs)
    assert len(jobs) == 1


def test_safe_fetch_swallows_exception_and_returns_empty():
    adapter = _BrokenAdapter(company="BrokenCo", company_slug="broken-co")
    result = adapter._safe_fetch(adapter.fetch_jobs)
    assert result == []


def test_safe_fetch_swallows_arbitrary_callable():
    adapter = _EchoAdapter(company="HSBC", company_slug="hsbc")

    def explode():
        raise ValueError("boom")

    assert adapter._safe_fetch(explode) == []


# ── _client ───────────────────────────────────────────────────────────────────

def test_client_has_browser_user_agent():
    adapter = _EchoAdapter(company="HSBC", company_slug="hsbc")
    with adapter._client() as client:
        ua = client.headers["user-agent"]
    assert "Mozilla" in ua


def test_client_includes_zh_hk_accept_language():
    adapter = _EchoAdapter(company="HSBC", company_slug="hsbc")
    with adapter._client() as client:
        lang = client.headers["accept-language"]
    assert "zh-HK" in lang


# ── Registry ──────────────────────────────────────────────────────────────────

def test_adapters_registry_is_dict():
    assert isinstance(ADAPTERS, dict)


def test_adapters_registry_values_are_base_adapter_subclasses():
    for name, cls in ADAPTERS.items():
        assert isinstance(name, str)
        assert issubclass(cls, BaseAdapter)
