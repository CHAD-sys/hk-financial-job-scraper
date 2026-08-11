from pathlib import Path

WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "learning-content.yml"


def test_learning_refresh_is_triggered_daily_but_guarded_by_backend_cadence():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert 'cron: "15 19 * * *"' in text
    assert "/api/admin/learning/refresh?force=$FORCE" in text
    assert "secrets.PIPELINE_SYNC_TOKEN" in text
    assert 'test "$status" != "failed"' in text
    assert 'test "$status" != "partial"' in text
