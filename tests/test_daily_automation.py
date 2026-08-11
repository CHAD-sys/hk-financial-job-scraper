"""Guardrails around the two daily pipeline entry points."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_local_daily_summary_email_is_opt_in():
    script = (ROOT / "scripts" / "daily_run.sh").read_text(encoding="utf-8")

    guard = 'if [[ "${PIPELINE_DAILY_EMAIL:-0}" == "1" ]]; then'
    notify = "ARGS+=(--email)"

    assert guard in script
    assert notify in script
    assert script.index(guard) < script.index(notify) < script.index("\nfi", script.index(notify))
    assert 'python -m hk_jobs.daily_run "${ARGS[@]}"' in script


def test_github_daily_workflow_emails_both_recipients_only_for_scheduled_runs():
    workflow = (ROOT / ".github" / "workflows" / "daily.yml").read_text(encoding="utf-8")

    assert "github.event_name == 'schedule'" in workflow
    assert "amine@finexclub.org,mohamedaminechahid@gmail.com" in workflow
    assert "secrets.SMTP_USER" in workflow
    assert "secrets.SMTP_PASS" in workflow
    assert "ARGS+=(--email)" in workflow
    assert "python -m hk_jobs.daily_run" in workflow


def test_github_daily_workflow_uses_one_canonical_run_and_always_keeps_its_record():
    workflow = (ROOT / ".github" / "workflows" / "daily.yml").read_text(encoding="utf-8")

    assert workflow.count("python -m hk_jobs.daily_run") == 1
    assert "- name: Upload authoritative Daily Run Record" in workflow
    assert "retention-days: 90" in workflow
    assert "/api/admin/pipeline/operations" in workflow
    assert "python - <<'PY'" not in workflow
    assert "curl --fail" not in workflow
