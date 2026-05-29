"""Tests for hk_jobs/pipeline.py — pipeline orchestrator."""

import argparse
from datetime import UTC, datetime
from pathlib import Path

from hk_jobs.config import CompanyConfig
from hk_jobs.pipeline import COMPANY_TIMEOUT_SECS, run
from hk_jobs.schema import Job
from hk_jobs.storage import JobStore

# ── helpers ───────────────────────────────────────────────────────────────────

def _job(source_id: str = "J-001", company_slug: str = "aia-hk") -> Job:
    return Job(
        source="workday",
        source_id=source_id,
        company="AIA Hong Kong",
        company_slug=company_slug,
        url=f"https://example.com/{source_id}",
        title="Analyst",
        locations=["Hong Kong"],
        fetched_at=datetime.now(UTC),
    )


def _cfg(slug: str = "aia-hk", adapter: str = "workday") -> CompanyConfig:
    return CompanyConfig(
        name="AIA Hong Kong",
        slug=slug,
        adapter=adapter,
        enabled=True,
        config={"tenant": "aia", "site": "External"},
    )


def _args(db: str, export: str | None = None, company: str | None = None) -> argparse.Namespace:
    return argparse.Namespace(
        db=db,
        export=export,
        company=company,
        no_enrich=True,   # skip enrichment so tests don't depend on enrich logic
        config=None,
        log_level="WARNING",
    )


class _MockAdapter:
    """Minimal adapter stub — returns pre-set jobs without any network calls."""

    def __init__(self, jobs: list[Job]):
        self._jobs = jobs

    def fetch_jobs(self) -> list[Job]:
        return self._jobs


# ── basic run ─────────────────────────────────────────────────────────────────

def test_run_inserts_jobs(tmp_path: Path, monkeypatch):
    jobs = [_job("J-001"), _job("J-002")]
    cfg = _cfg()
    monkeypatch.setattr("hk_jobs.pipeline.load_companies", lambda path=None: [cfg])
    monkeypatch.setattr(CompanyConfig, "build_adapter", lambda self: _MockAdapter(jobs))

    results = run(_args(str(tmp_path / "jobs.db")))

    assert len(results) == 1
    assert results[0].total_fetched == 2
    assert results[0].inserted == 2
    assert results[0].updated == 0
    assert results[0].ok


def test_run_updates_on_re_run(tmp_path: Path, monkeypatch):
    jobs = [_job("J-001")]
    cfg = _cfg()
    monkeypatch.setattr("hk_jobs.pipeline.load_companies", lambda path=None: [cfg])
    monkeypatch.setattr(CompanyConfig, "build_adapter", lambda self: _MockAdapter(jobs))

    db = str(tmp_path / "jobs.db")
    run(_args(db))
    results = run(_args(db))

    assert results[0].inserted == 0
    assert results[0].updated == 1


def test_run_flags_zero_jobs_company(tmp_path: Path, monkeypatch, caplog):
    import logging
    cfg = _cfg()
    monkeypatch.setattr("hk_jobs.pipeline.load_companies", lambda path=None: [cfg])
    monkeypatch.setattr(CompanyConfig, "build_adapter", lambda self: _MockAdapter([]))

    with caplog.at_level(logging.WARNING):
        results = run(_args(str(tmp_path / "jobs.db")))

    assert results[0].total_fetched == 0
    assert results[0].ok  # no error — just 0 jobs
    assert any("0 jobs" in m for m in caplog.messages)


def test_run_handles_adapter_exception(tmp_path: Path, monkeypatch):
    class _BrokenAdapter:
        def fetch_jobs(self):
            raise RuntimeError("network down")

    cfg = _cfg()
    monkeypatch.setattr("hk_jobs.pipeline.load_companies", lambda path=None: [cfg])
    monkeypatch.setattr(CompanyConfig, "build_adapter", lambda self: _BrokenAdapter())

    results = run(_args(str(tmp_path / "jobs.db")))

    assert len(results) == 1
    assert not results[0].ok
    assert "RuntimeError" in results[0].error


def test_run_company_filter(tmp_path: Path, monkeypatch):
    """--company slug should skip all other companies."""
    cfgs = [_cfg("aia-hk"), _cfg("hsbc-hk")]
    calls = []

    class _TrackingAdapter:
        def __init__(self, slug):
            self.slug = slug

        def fetch_jobs(self):
            calls.append(self.slug)
            return [_job(company_slug=self.slug)]

    monkeypatch.setattr("hk_jobs.pipeline.load_companies", lambda path=None: cfgs)
    monkeypatch.setattr(
        CompanyConfig,
        "build_adapter",
        lambda self: _TrackingAdapter(self.slug),
    )

    results = run(_args(str(tmp_path / "jobs.db"), company="aia-hk"))

    assert len(results) == 1
    assert results[0].slug == "aia-hk"
    assert calls == ["aia-hk"]


# ── export ────────────────────────────────────────────────────────────────────

def test_run_exports_jsonl(tmp_path: Path, monkeypatch):
    jobs = [_job("J-001"), _job("J-002")]
    cfg = _cfg()
    monkeypatch.setattr("hk_jobs.pipeline.load_companies", lambda path=None: [cfg])
    monkeypatch.setattr(CompanyConfig, "build_adapter", lambda self: _MockAdapter(jobs))

    export_path = str(tmp_path / "out" / "jobs.jsonl")
    run(_args(str(tmp_path / "jobs.db"), export=export_path))

    lines = Path(export_path).read_text().strip().splitlines()
    assert len(lines) == 2


def test_export_only_active_jobs(tmp_path: Path, monkeypatch):
    """Jobs soft-deleted by mark_inactive_for_run should not appear in the export."""
    jobs = [_job("J-001"), _job("J-002")]
    cfg = _cfg()
    monkeypatch.setattr("hk_jobs.pipeline.load_companies", lambda path=None: [cfg])
    monkeypatch.setattr(CompanyConfig, "build_adapter", lambda self: _MockAdapter(jobs))

    db_path = str(tmp_path / "jobs.db")
    export_path = str(tmp_path / "jobs.jsonl")

    # First run inserts both; second run (empty adapter) soft-deletes both
    run(_args(db_path))
    monkeypatch.setattr(CompanyConfig, "build_adapter", lambda self: _MockAdapter([]))
    run(_args(db_path, export=export_path))

    lines = Path(export_path).read_text().strip().splitlines()
    assert lines == [] or lines == [""]  # all deactivated


# ── soft-delete integration ───────────────────────────────────────────────────

def test_mark_inactive_called_after_run(tmp_path: Path, monkeypatch):
    """Jobs not returned in the second run should be marked inactive."""
    cfg = _cfg()

    # First run: insert J-001 and J-002
    monkeypatch.setattr("hk_jobs.pipeline.load_companies", lambda path=None: [cfg])
    monkeypatch.setattr(
        CompanyConfig, "build_adapter",
        lambda self: _MockAdapter([_job("J-001"), _job("J-002")]),
    )
    db_path = str(tmp_path / "jobs.db")
    run(_args(db_path))

    # Second run: only J-001 returned — J-002 should be deactivated
    monkeypatch.setattr(
        CompanyConfig, "build_adapter",
        lambda self: _MockAdapter([_job("J-001")]),
    )
    results = run(_args(db_path))

    assert results[0].deactivated == 1
    with JobStore(db_path) as store:
        stats = store.stats()
    assert stats["active"] == 1
    assert stats["total"] == 2


# ── constants ─────────────────────────────────────────────────────────────────

def test_company_timeout_is_positive():
    assert COMPANY_TIMEOUT_SECS > 0
