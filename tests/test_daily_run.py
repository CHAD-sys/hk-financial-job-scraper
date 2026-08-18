"""The Daily Run module's external interface is its test surface."""

import gzip
import sqlite3
import subprocess
from datetime import datetime, timezone

import httpx

from hk_jobs.daily_run import (
    CommandPhaseExecutor,
    DailyRunRecord,
    PhaseOutput,
    PhaseStatus,
    RunStatus,
    RuntimePaths,
    profile_for,
    render_markdown,
    run_daily,
    run_reporters,
)


def test_profiles_share_one_phase_vocabulary_without_forcing_identical_work():
    hosted = profile_for("hosted")
    local = profile_for("local")

    assert [phase.key for phase in hosted.phases] == [
        "restore",
        "scrape",
        "descriptions",
        "deepseek",
        "salary_audit",
        "linkedin_promote",
        "publish",
    ]
    assert [phase.key for phase in local.phases] == [
        "scrape",
        "descriptions",
        "deepseek",
        "salary_audit",
        "pocketbase",
        "linkedin_fetch",
        "linkedin_discovery",
        "linkedin_promote",
        "backup",
    ]
    assert hosted.phase("scrape") == local.phase("scrape")


def test_enrich_only_is_the_smallest_profile_that_changes_production():
    """Enrichment has to run inside GitHub Actions (the DeepSeek key is a secret
    there), and the only route to it used to be a full `hosted` run — so clearing
    an enrichment backlog cost a scrape of all 213 sources. restore and publish
    are required, not decoration: without them the phase would enrich a database
    nobody reads."""
    assert [phase.key for phase in profile_for("enrich_only").phases] == [
        "restore",
        "deepseek",
        "publish",
    ]


def test_enrich_only_reuses_the_shared_phase_definitions():
    """A profile selects phases; it never redefines them. Otherwise 'deepseek'
    could come to mean something different depending on how it was reached."""
    hosted, enrich = profile_for("hosted"), profile_for("enrich_only")
    for key in ("restore", "deepseek", "publish"):
        assert hosted.phase(key) == enrich.phase(key)


def test_required_failure_aborts_catalogue_work_but_record_remains_complete():
    record = DailyRunRecord.start(
        "run-1",
        profile_for("hosted"),
        started_at="2026-08-11T00:00:00+00:00",
    )
    record.begin_phase("restore", at="2026-08-11T00:00:01+00:00")
    record.finish_phase("restore", PhaseStatus.SUCCESS, duration_seconds=2)
    record.begin_phase("scrape")
    record.finish_phase("scrape", PhaseStatus.FAILED, detail="source failure")

    assert record.finalize(at="2026-08-11T00:05:00+00:00") is RunStatus.FAILED
    assert record.phase("publish").status is PhaseStatus.SKIPPED
    assert record.phase("publish").required is True


def test_optional_failure_allows_success_with_warning():
    record = DailyRunRecord.start("run-2", profile_for("hosted"))
    for phase in record.phases:
        record.begin_phase(phase.key)
        status = PhaseStatus.FAILED if phase.key == "salary_audit" else PhaseStatus.SUCCESS
        record.finish_phase(phase.key, status)

    assert record.finalize() is RunStatus.WARNING
    assert record.phase("publish").status is PhaseStatus.SUCCESS


def test_reporting_failure_does_not_reclassify_published_catalogue_as_failed():
    record = DailyRunRecord.start("run-3", profile_for("hosted"))
    for phase in record.phases:
        record.begin_phase(phase.key)
        record.finish_phase(phase.key, PhaseStatus.SUCCESS)
    record.add_reporting_result("email", PhaseStatus.FAILED, "SMTP unavailable")

    assert record.finalize() is RunStatus.WARNING
    assert record.phase("publish").status is PhaseStatus.SUCCESS


def test_record_round_trips_through_versioned_atomic_json(tmp_path):
    path = tmp_path / "records" / "run.json"
    record = DailyRunRecord.start(
        "run-4",
        profile_for("local"),
        source_run_url="file:///logs/daily_runs.log",
    )
    record.begin_phase("scrape")
    record.finish_phase("scrape", PhaseStatus.FAILED, detail="boom")
    record.diagnostics.append("traceback: logs/daily_runs.log")
    record.finalize()

    assert record.write(path) == path
    loaded = DailyRunRecord.read(path)
    assert loaded.to_dict() == record.to_dict()


def test_unknown_profile_and_phase_fail_loudly():
    try:
        profile_for("desktop")
    except ValueError as exc:
        assert "choose enrich_only, hosted, local" in str(exc)
    else:
        raise AssertionError("unknown profile should fail")

    record = DailyRunRecord.start("run-5", profile_for("hosted"))
    try:
        record.begin_phase("pocketbase")
    except KeyError:
        pass
    else:
        raise AssertionError("phase outside the selected profile should fail")


def test_runner_executes_the_selected_profile_in_registry_order(tmp_path):
    executed: list[str] = []

    def execute(phase, _record):
        executed.append(phase.key)
        return PhaseOutput(detail=f"completed {phase.label}")

    record = run_daily("local", "local-1", execute, record_path=tmp_path / "record.json")

    assert executed == [phase.key for phase in profile_for("local").phases]
    assert record.status is RunStatus.SUCCESS
    assert DailyRunRecord.read(tmp_path / "record.json").status is RunStatus.SUCCESS


def test_runner_stops_after_required_failure_and_never_reaches_publish():
    executed: list[str] = []

    def execute(phase, _record):
        executed.append(phase.key)
        if phase.key == "descriptions":
            raise RuntimeError("description source unavailable")
        return None

    record = run_daily("hosted", "hosted-1", execute)

    assert executed == ["restore", "scrape", "descriptions"]
    assert record.status is RunStatus.FAILED
    assert record.phase("publish").status is PhaseStatus.SKIPPED
    assert "RuntimeError" in record.diagnostics[0]


def test_runner_records_optional_failure_as_warning_and_continues_to_publish():
    executed: list[str] = []

    def execute(phase, _record):
        executed.append(phase.key)
        if phase.key == "salary_audit":
            raise RuntimeError("budget endpoint timed out")
        if phase.key == "restore":
            return PhaseOutput(facts={"restore_source": "railway", "restore_sha256": "a" * 64})
        if phase.key == "publish":
            return PhaseOutput(
                facts={"published_sha256": "b" * 64, "published_at": "2026-08-11T02:00:00Z"}
            )
        return None

    record = run_daily("hosted", "hosted-2", execute)

    assert executed[-1] == "publish"
    assert record.status is RunStatus.WARNING
    assert record.phase("salary_audit").status is PhaseStatus.WARNING
    assert record.restore_source == "railway"
    assert record.published_sha256 == "b" * 64


def test_runner_rejects_unowned_facts_as_a_phase_failure():
    def execute(phase, _record):
        if phase.key == "restore":
            return PhaseOutput(facts={"secret": "must not leak into the record"})
        return None

    record = run_daily("hosted", "hosted-3", execute)
    assert record.status is RunStatus.FAILED
    assert record.phase("restore").status is PhaseStatus.FAILED


def test_optional_phase_can_report_an_expected_skip():
    def execute(phase, _record):
        if phase.key == "linkedin_discovery":
            return PhaseOutput(status=PhaseStatus.SKIPPED, detail="Runs on Mondays in Hong Kong")
        return None

    record = run_daily("local", "local-skip", execute)

    assert record.status is RunStatus.SUCCESS
    assert record.phase("linkedin_discovery").status is PhaseStatus.SKIPPED
    assert record.phase("linkedin_discovery").detail == "Runs on Mondays in Hong Kong"


def test_reporting_adapters_are_isolated_and_reclassify_to_warning(tmp_path):
    calls: list[str] = []

    class Reporter:
        def __init__(self, key, fails=False):
            self.key = key
            self.fails = fails

        def __call__(self, _record):
            calls.append(self.key)
            if self.fails:
                raise OSError("temporarily unavailable")
            return "done"

    record = run_daily("local", "reporting-1", lambda *_: None)
    record_path = tmp_path / "daily-run.json"
    run_reporters(
        record,
        [Reporter("railway", fails=True), Reporter("github")],
        record_path=record_path,
    )

    assert calls == ["railway", "github"]
    assert record.status is RunStatus.WARNING
    assert [result.status for result in record.reporting] == [
        PhaseStatus.FAILED,
        PhaseStatus.SUCCESS,
    ]
    assert DailyRunRecord.read(record_path).status is RunStatus.WARNING


def test_railway_record_reporter_posts_a_json_body():
    captured = {}

    def post(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return httpx.Response(
            200,
            json={"ok": True},
            request=httpx.Request("POST", url),
        )

    from hk_jobs.daily_run.reporting import RailwayRecordReporter

    record = run_daily("hosted", "railway-report-1", lambda *_: None)
    reporter = RailwayRecordReporter(
        "https://railway.test/operations",
        "token",
        post=post,
    )

    assert reporter(record) == "HTTP 200"
    assert captured["url"] == "https://railway.test/operations"
    assert captured["kwargs"]["headers"]["X-Pipeline-Sync-Token"] == "token"
    assert captured["kwargs"]["json"] == record.to_dict()
    assert "content" not in captured["kwargs"]


def test_github_summary_is_rendered_from_the_record():
    record = DailyRunRecord.start(
        "summary-1",
        profile_for("hosted"),
        started_at="2026-08-10T18:00:00+00:00",
    )
    record.begin_phase("restore")
    record.finish_phase(
        "restore",
        PhaseStatus.SUCCESS,
        detail="Source: railway",
        duration_seconds=8,
    )
    record.finalize()

    summary = render_markdown(record)

    assert "Daily Run · 2026-08-11" in summary
    assert "| Restore | required | success | 8s | Source: railway |" in summary
    assert "| Railway publish | required | skipped |" in summary


def test_local_command_adapter_uses_the_profile_without_owning_phase_order(tmp_path):
    commands: list[list[str]] = []

    def run_command(command, **_kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="")

    paths = RuntimePaths(
        tmp_path,
        tmp_path / "data/jobs.db",
        tmp_path / "data/jobs.jsonl",
    )
    executor = CommandPhaseExecutor(
        paths,
        environ={"DEEPSEEK_API_KEY": "configured", "DEEPSEEK_DAILY_ENRICH_LIMIT": "12"},
        run_command=run_command,
        now=lambda: datetime(2026, 8, 11, tzinfo=timezone.utc),  # Tuesday in Hong Kong
    )

    record = run_daily("local", "commands-1", executor)

    assert record.status is RunStatus.SUCCESS
    assert record.phase("linkedin_discovery").status is PhaseStatus.SKIPPED
    flattened = [" ".join(command) for command in commands]
    assert any("--enrich-limit 12" in command for command in flattened)
    assert any("hk_jobs.sync_pocketbase" in command for command in flattened)
    assert any("--fetch-posts" in command for command in flattened)
    assert not any("--posts-discovery" in command for command in flattened)
    assert any("--backup" in command for command in flattened)


def test_hosted_adapter_restores_and_publishes_the_same_database(tmp_path):
    source = tmp_path / "source.db"
    with sqlite3.connect(source) as conn:
        conn.execute("CREATE TABLE marker (value TEXT)")
        conn.execute("INSERT INTO marker VALUES ('enriched')")
    restored_body = gzip.compress(source.read_bytes())
    published = {}

    def get(_url, **_kwargs):
        return httpx.Response(
            200,
            content=restored_body,
            request=httpx.Request("GET", "https://railway.test/database"),
        )

    def post(_url, **kwargs):
        published["headers"] = kwargs["headers"]
        published["body"] = kwargs["files"]["snapshot"][1].read()
        return httpx.Response(
            200,
            json={"published": True},
            request=httpx.Request("POST", "https://railway.test/database"),
        )

    paths = RuntimePaths(
        tmp_path,
        tmp_path / "data/jobs.db",
        tmp_path / "data/jobs.jsonl",
    )
    executor = CommandPhaseExecutor(
        paths,
        environ={
            "DEEPSEEK_API_KEY": "configured",
            "PIPELINE_SYNC_TOKEN": "token",
            "PIPELINE_DATABASE_SYNC_URL": "https://railway.test/database",
        },
        run_command=lambda command, **_kwargs: subprocess.CompletedProcess(command, 0),
        http_get=get,
        http_post=post,
        now=lambda: datetime(2026, 8, 11, tzinfo=timezone.utc),
    )

    record = run_daily("hosted", "hosted-transport", executor)

    assert record.status is RunStatus.SUCCESS
    assert record.restore_source == "railway"
    assert record.restore_sha256 == record.published_sha256
    assert published["headers"]["X-Pipeline-Run-Id"] == "hosted-transport"
    assert gzip.decompress(published["body"]) == paths.database.read_bytes()


def test_repair_is_the_smallest_profile_that_changes_production_without_a_model_call():
    """A clamp change only affects estimates written after it, so rows already
    published keep whatever the old clamp allowed. This is how a deterministic
    repair reaches them: restore pulls the live database down, the repair recomputes
    the affected rows in Python, publish hands it back. No scrape, no DeepSeek."""
    assert [phase.key for phase in profile_for("repair").phases] == [
        "restore",
        "salary_repair",
        "publish",
    ]


def test_repair_is_not_part_of_the_nightly_run():
    """Once the clamp is in place no new bad rows are written, which makes the
    repair a backfill rather than a nightly chore. Adding it to hosted would run a
    full table scan every night to change nothing."""
    assert "salary_repair" not in [phase.key for phase in profile_for("hosted").phases]


def test_repair_reuses_the_shared_phase_definitions():
    hosted, repair = profile_for("hosted"), profile_for("repair")
    for key in ("restore", "publish"):
        assert hosted.phase(key) == repair.phase(key)
