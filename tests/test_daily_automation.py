"""Guardrails around the two daily pipeline entry points."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_local_daily_summary_email_is_opt_in():
    script = (ROOT / "scripts" / "daily_run.sh").read_text(encoding="utf-8")

    guard = 'if [[ "${PIPELINE_DAILY_EMAIL:-0}" == "1" ]]; then'
    notify = "python -m hk_jobs.pipeline --notify-summary"

    assert guard in script
    assert notify in script
    assert script.index(guard) < script.index(notify) < script.index("\nfi", script.index(notify))


def test_github_daily_workflow_emails_both_recipients_only_for_scheduled_runs():
    workflow = (ROOT / ".github" / "workflows" / "daily.yml").read_text(encoding="utf-8")

    assert "needs: scrape" in workflow
    assert "github.event_name == 'schedule'" in workflow
    assert "amine@finexclub.org,mohamedaminechahid@gmail.com" in workflow
    assert "secrets.SMTP_USER" in workflow
    assert "secrets.SMTP_PASS" in workflow
    assert "send_daily_summary" in workflow
    assert "send_failure_alert" in workflow


def test_github_daily_workflow_always_publishes_operations_telemetry():
    workflow = (ROOT / ".github" / "workflows" / "daily.yml").read_text(encoding="utf-8")

    assert "- name: Publish pipeline operations telemetry" in workflow
    assert "if: always()" in workflow
    assert "/api/admin/pipeline/operations" in workflow
    for phase_id in (
        "id: restore", "id: scrape", "id: descriptions", "id: deepseek",
        "id: salary_audit", "id: linkedin", "id: publish_catalogue",
    ):
        assert phase_id in workflow
