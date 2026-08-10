import sqlite3

from hk_jobs.ai_usage import estimate_cost_usd, record, usage_from_payload


def test_usage_payload_and_v4_flash_cost_are_persisted(tmp_path):
    db = tmp_path / "jobs.db"
    totals = usage_from_payload({
        "usage": {
            "prompt_tokens": 1500,
            "prompt_cache_hit_tokens": 1000,
            "prompt_cache_miss_tokens": 500,
            "completion_tokens": 250,
        }
    })
    record(
        str(db), phase="deepseek_enrichment", model="deepseek-v4-flash",
        totals=totals, roles_processed=1, source_run_id="run-1",
    )
    row = sqlite3.connect(db).execute(
        "SELECT calls, roles_processed, prompt_cache_hit_tokens, "
        "prompt_cache_miss_tokens, completion_tokens, estimated_cost_usd FROM ai_usage"
    ).fetchone()
    assert row[:5] == (1, 1, 1000, 500, 250)
    assert row[5] == estimate_cost_usd(cache_hit=1000, cache_miss=500, completion=250)


def test_incrementing_usage_keeps_every_linkedin_call(tmp_path):
    db = tmp_path / "jobs.db"
    for _ in range(2):
        record(
            str(db), phase="linkedin_promotion", model="deepseek-v4-flash",
            totals={"calls": 1, "cache_hit": 0, "cache_miss": 100, "completion": 20},
            roles_processed=1, source_run_id="run-2", increment=True,
        )
    row = sqlite3.connect(db).execute(
        "SELECT calls, roles_processed, prompt_cache_miss_tokens, completion_tokens "
        "FROM ai_usage"
    ).fetchone()
    assert row == (2, 2, 200, 40)
