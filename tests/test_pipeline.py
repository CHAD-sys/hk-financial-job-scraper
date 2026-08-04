"""
Tests for hk_jobs/pipeline.py — pipeline orchestrator.

Two things these tests have to imitate about production, both of which they
previously did not:

  - `main()` runs the migrations before it ever calls `run()`, and `run()`
    records a daily snapshot into `job_history`. A bare database has no such
    table, so every test that called `run()` died on
    `sqlite3.OperationalError: no such table: job_history`.
  - `run()` calls `load_companies` TWICE — once for the config, once for
    `companies_longtail.yaml` — so a mock that ignores its path argument
    returns the same companies both times and silently doubles the list.

`_db()` and `_load_companies` below are those two facts, stated once.
"""

import argparse
from datetime import UTC, datetime
from pathlib import Path

from hk_jobs.config import CompanyConfig
from hk_jobs.migrations import migrate_to_phase_11
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


def _db(tmp_path: Path) -> str:
    """
    A database path with the analytics tables in place.

    `run()` records a snapshot into `job_history` / `company_metrics` at the end
    of every non-dry run, and production creates those tables by running 16
    migrations in `main()` long before `run()` is reached. Doing the same here is
    what makes these tests exercise the production path rather than a shape the
    application never sees.
    """
    path = str(tmp_path / "jobs.db")
    migrate_to_phase_11(path)
    return path


def _load_companies(cfgs: list[CompanyConfig]):
    """
    A stand-in for `load_companies` that respects which file it was asked for.

    `run()` calls it twice: once for the main config, once for
    `companies_longtail.yaml`. A mock that ignores the path returns `cfgs` both
    times, so the list doubles and `--company` filtering appears to return two
    matches for one slug. Only the main-config call yields the test's companies;
    the longtail call yields nothing, which is what an empty longtail track
    looks like.
    """
    def fake(path=None):
        return [] if path is not None and "longtail" in str(path) else cfgs
    return fake


def _args(
    db: str,
    export: str | None = None,
    company: str | None = None,
    dry_run: bool = False,
    verbose: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(
        db=db,
        export=export,
        company=company,
        dry_run=dry_run,
        verbose=verbose,
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
    monkeypatch.setattr("hk_jobs.pipeline.load_companies", _load_companies([cfg]))
    monkeypatch.setattr(CompanyConfig, "build_adapter", lambda self: _MockAdapter(jobs))

    results = run(_args(_db(tmp_path)))

    assert len(results) == 1
    assert results[0].total_fetched == 2
    assert results[0].inserted == 2
    assert results[0].updated == 0
    assert results[0].ok


def test_run_updates_on_re_run(tmp_path: Path, monkeypatch):
    jobs = [_job("J-001")]
    cfg = _cfg()
    monkeypatch.setattr("hk_jobs.pipeline.load_companies", _load_companies([cfg]))
    monkeypatch.setattr(CompanyConfig, "build_adapter", lambda self: _MockAdapter(jobs))

    db = _db(tmp_path)
    run(_args(db))
    results = run(_args(db))

    assert results[0].inserted == 0
    assert results[0].updated == 1


def test_run_flags_zero_jobs_company(tmp_path: Path, monkeypatch, caplog):
    import logging
    cfg = _cfg()
    monkeypatch.setattr("hk_jobs.pipeline.load_companies", _load_companies([cfg]))
    monkeypatch.setattr(CompanyConfig, "build_adapter", lambda self: _MockAdapter([]))

    with caplog.at_level(logging.WARNING):
        results = run(_args(_db(tmp_path)))

    assert results[0].total_fetched == 0
    assert results[0].ok  # no error — just 0 jobs
    assert any("0 jobs" in m for m in caplog.messages)


def test_run_handles_adapter_exception(tmp_path: Path, monkeypatch):
    class _BrokenAdapter:
        def fetch_jobs(self):
            raise RuntimeError("network down")

    cfg = _cfg()
    monkeypatch.setattr("hk_jobs.pipeline.load_companies", _load_companies([cfg]))
    monkeypatch.setattr(CompanyConfig, "build_adapter", lambda self: _BrokenAdapter())

    results = run(_args(_db(tmp_path)))

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

    monkeypatch.setattr("hk_jobs.pipeline.load_companies", _load_companies(cfgs))
    monkeypatch.setattr(
        CompanyConfig,
        "build_adapter",
        lambda self: _TrackingAdapter(self.slug),
    )

    results = run(_args(_db(tmp_path), company="aia-hk"))

    assert len(results) == 1
    assert results[0].slug == "aia-hk"
    assert calls == ["aia-hk"]


# ── export ────────────────────────────────────────────────────────────────────

def test_run_exports_jsonl(tmp_path: Path, monkeypatch):
    jobs = [_job("J-001"), _job("J-002")]
    cfg = _cfg()
    monkeypatch.setattr("hk_jobs.pipeline.load_companies", _load_companies([cfg]))
    monkeypatch.setattr(CompanyConfig, "build_adapter", lambda self: _MockAdapter(jobs))

    export_path = str(tmp_path / "out" / "jobs.jsonl")
    run(_args(_db(tmp_path), export=export_path))

    lines = Path(export_path).read_text().strip().splitlines()
    assert len(lines) == 2


def test_export_only_active_jobs(tmp_path: Path, monkeypatch):
    """
    Jobs soft-deleted by mark_inactive_for_run should not appear in the export.

    The second run returns FEWER jobs, not zero. Zero would prove nothing: a
    scrape that comes back empty is far more likely to be a Cloudflare block
    than a company that closed every vacancy overnight, so
    `JobStore.mark_inactive_for_run` deliberately refuses to deactivate anything
    on a 0-job result. This test used to assert the opposite and only ever
    "passed" because it died earlier, on a missing job_history table.
    """
    cfg = _cfg()
    monkeypatch.setattr("hk_jobs.pipeline.load_companies", _load_companies([cfg]))
    monkeypatch.setattr(
        CompanyConfig, "build_adapter",
        lambda self: _MockAdapter([_job("J-001"), _job("J-002")]),
    )

    db_path = _db(tmp_path)
    export_path = str(tmp_path / "jobs.jsonl")

    run(_args(db_path))
    monkeypatch.setattr(
        CompanyConfig, "build_adapter", lambda self: _MockAdapter([_job("J-001")]),
    )
    run(_args(db_path, export=export_path))

    lines = [ln for ln in Path(export_path).read_text().strip().splitlines() if ln]
    assert len(lines) == 1, "the deactivated job must not be exported"
    assert '"source_id":"J-001"' in lines[0]


# ── soft-delete integration ───────────────────────────────────────────────────

def test_mark_inactive_called_after_run(tmp_path: Path, monkeypatch):
    """Jobs not returned in the second run should be marked inactive."""
    cfg = _cfg()

    # First run: insert J-001 and J-002
    monkeypatch.setattr("hk_jobs.pipeline.load_companies", _load_companies([cfg]))
    monkeypatch.setattr(
        CompanyConfig, "build_adapter",
        lambda self: _MockAdapter([_job("J-001"), _job("J-002")]),
    )
    db_path = _db(tmp_path)
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


# ── --dry-run ─────────────────────────────────────────────────────────────────

def test_dry_run_does_not_write_to_disk(tmp_path: Path, monkeypatch):
    """--dry-run must leave the real DB file untouched."""
    jobs = [_job("J-001"), _job("J-002")]
    cfg = _cfg()
    monkeypatch.setattr("hk_jobs.pipeline.load_companies", _load_companies([cfg]))
    monkeypatch.setattr(CompanyConfig, "build_adapter", lambda self: _MockAdapter(jobs))

    # Deliberately NOT _db(): running the migrations would create the very file
    # this test asserts is never created. A dry run skips the snapshot too, so it
    # never reaches job_history.
    db_path = str(tmp_path / "jobs.db")
    run(_args(db_path, dry_run=True))

    assert not Path(db_path).exists(), "dry-run must not create the database file"


def test_dry_run_reports_would_be_inserted_count(tmp_path: Path, monkeypatch):
    jobs = [_job("J-001"), _job("J-002"), _job("J-003")]
    cfg = _cfg()
    monkeypatch.setattr("hk_jobs.pipeline.load_companies", _load_companies([cfg]))
    monkeypatch.setattr(CompanyConfig, "build_adapter", lambda self: _MockAdapter(jobs))

    results = run(_args(_db(tmp_path), dry_run=True))

    assert results[0].total_fetched == 3
    assert results[0].inserted == 3   # would-be inserts
    assert results[0].updated == 0
    assert results[0].deactivated == 0


def test_dry_run_does_not_call_mark_inactive(tmp_path: Path, monkeypatch):
    """Running dry-run twice should not accumulate deactivated counts."""
    jobs = [_job("J-001")]
    cfg = _cfg()
    monkeypatch.setattr("hk_jobs.pipeline.load_companies", _load_companies([cfg]))
    monkeypatch.setattr(CompanyConfig, "build_adapter", lambda self: _MockAdapter(jobs))

    db = _db(tmp_path)
    run(_args(db, dry_run=True))
    results = run(_args(db, dry_run=True))

    assert results[0].deactivated == 0


# ── --only / --verbose ────────────────────────────────────────────────────────

def test_only_flag_accepted_by_parse_args():
    from hk_jobs.pipeline import _parse_args

    args = _parse_args(["--only", "aia-hk", "--db", "data/jobs.db"])
    assert args.company == ["aia-hk"]  # action='append' returns a list


def test_only_flag_accepts_multiple_slugs():
    from hk_jobs.pipeline import _parse_args

    args = _parse_args(["--only", "aia-hk", "--only", "blackrock-hk", "--db", "data/jobs.db"])
    assert set(args.company) == {"aia-hk", "blackrock-hk"}


def test_company_flag_still_accepted_by_parse_args():
    from hk_jobs.pipeline import _parse_args

    args = _parse_args(["--company", "aia-hk", "--db", "data/jobs.db"])
    assert args.company == ["aia-hk"]


def test_verbose_flag_parsed():
    from hk_jobs.pipeline import _parse_args

    args = _parse_args(["-v", "--db", "data/jobs.db"])
    assert args.verbose is True

    args2 = _parse_args(["--verbose", "--db", "data/jobs.db"])
    assert args2.verbose is True


def test_verbose_logs_job_titles(tmp_path: Path, monkeypatch, caplog):
    import logging

    jobs = [_job("J-001"), _job("J-002")]
    cfg = _cfg()
    monkeypatch.setattr("hk_jobs.pipeline.load_companies", _load_companies([cfg]))
    monkeypatch.setattr(CompanyConfig, "build_adapter", lambda self: _MockAdapter(jobs))

    with caplog.at_level(logging.DEBUG):
        run(_args(_db(tmp_path), verbose=True))

    # Each job's source_id should appear in a DEBUG log line
    debug_msgs = " ".join(caplog.messages)
    assert "J-001" in debug_msgs
    assert "J-002" in debug_msgs


# ── constants ─────────────────────────────────────────────────────────────────

def test_company_timeout_is_positive():
    assert COMPANY_TIMEOUT_SECS > 0
