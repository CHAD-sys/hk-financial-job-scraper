"""Publishing GitHub's completed jobs database into Railway's live catalogue."""

from __future__ import annotations

import gzip
import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from .support import make_app, make_bundle

TOKEN = "pipeline-sync-secret"
HK = ZoneInfo("Asia/Hong_Kong")


def _migrated(path: Path, jobs: list[tuple[str, str, str, int]]) -> Path:
    from hk_jobs.migrations import migrate

    migrate(str(path))
    today = datetime.now(HK).date().isoformat()
    with sqlite3.connect(path) as conn:
        for source, source_id, title, active in jobs:
            conn.execute(
                """
                INSERT INTO jobs (
                    source, source_id, company, company_slug, url, dedup_hash,
                    title, description_clean, locations, fetched_at, is_active,
                    is_primary
                ) VALUES (?, ?, 'HSBC', 'hsbc', ?, ?, ?, ?, '["Hong Kong"]', ?, ?, 1)
                """,
                (
                    source,
                    source_id,
                    f"https://example.test/{source_id}",
                    f"hash-{source_id}",
                    title,
                    f"Description for {title}",
                    f"{today}T00:00:00+08:00",
                    active,
                ),
            )
        conn.execute(
            """
            INSERT INTO job_history (
                company_id, company_name, job_count, scraped_date,
                trend_direction, trend_percent, jobs_added, jobs_removed
            ) VALUES ('hsbc', 'HSBC', ?, ?, 'stable', 0, 0, 0)
            """,
            (sum(active for *_, active in jobs), today),
        )
    return path


def _gzip_snapshot(path: Path) -> tuple[bytes, str]:
    raw = path.read_bytes()
    return gzip.compress(raw, compresslevel=1), hashlib.sha256(raw).hexdigest()


def _post(client: TestClient, snapshot: Path, *, token: str = TOKEN, run_id: str = "12345"):
    body, digest = _gzip_snapshot(snapshot)
    return client.post(
        "/api/admin/pipeline/database",
        files={"snapshot": ("jobs.db.gz", body, "application/gzip")},
        headers={
            "X-Pipeline-Sync-Token": token,
            "X-Pipeline-Run-Id": run_id,
            "X-Pipeline-Snapshot-SHA256": digest,
            "X-Pipeline-Source-Url": f"https://github.test/actions/runs/{run_id}",
        },
    )


@pytest.fixture()
def publish_client(tmp_path, monkeypatch):
    import seekers_store

    live = _migrated(
        tmp_path / "live.db",
        [
            ("workday", "W1", "Pipeline-owned old title", 1),
            ("direct", "D1", "Approved direct Role", 1),
        ],
    )
    with sqlite3.connect(live) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute(
            """INSERT INTO pipeline_operations (
                   run_id, scraped_date, status, phases_json, recorded_at
               ) VALUES ('railway-current', '2026-08-11', 'success', '[]',
                         '2026-08-11T02:00:00+08:00')"""
        )
        conn.execute(
            """
            INSERT INTO job_enrichments (
                source, source_id, seniority, salary_estimated_min,
                salary_estimated_max
            ) VALUES ('workday', 'W1', 'mid', 40000, 60000)
            """
        )

        import job_edit

        job_edit.apply_edit(
            conn,
            "workday",
            "W1",
            "ultimate-admin-id",
            job_changes={"title": "Human-corrected title"},
            enrichment_changes={"salary_estimated_max": 88000},
        )

    monkeypatch.setenv("SEEKERS_DB_PATH", str(tmp_path / "seekers.db"))
    monkeypatch.setenv("EMPLOYERS_DB_PATH", str(tmp_path / "employers.db"))
    seekers_store.reset_store()
    dist = tmp_path / "dist"
    make_bundle(dist)
    client = TestClient(
        make_app(
            live,
            dist,
            tmp_path,
            cookie_secure=False,
            pipeline_sync_token=TOKEN,
        )
    )
    return client, live


def test_catalog_publish_requires_the_machine_secret(publish_client, tmp_path):
    client, live = publish_client
    incoming = _migrated(tmp_path / "incoming.db", [("workday", "W2", "New Role", 1)])

    assert _post(client, incoming, token="wrong").status_code == 401
    with sqlite3.connect(live) as conn:
        assert conn.execute("SELECT title FROM jobs WHERE source_id='W1'").fetchone()[0] == (
            "Human-corrected title"
        )


def test_catalog_restore_snapshot_is_protected_and_excludes_railway_owned_rows(
    publish_client, tmp_path
):
    client, _live = publish_client

    assert client.get("/api/admin/pipeline/database").status_code == 401
    response = client.get(
        "/api/admin/pipeline/database",
        headers={"X-Pipeline-Sync-Token": TOKEN},
    )

    assert response.status_code == 200, response.text
    raw = gzip.decompress(response.content)
    assert hashlib.sha256(raw).hexdigest() == response.headers[
        "X-Pipeline-Snapshot-SHA256"
    ]
    restored = tmp_path / "restored.db"
    restored.write_bytes(raw)
    with sqlite3.connect(restored) as conn:
        assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT COUNT(*) FROM jobs WHERE source='direct'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM admin_edits").fetchone()[0] == 0
        sync_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='pipeline_catalog_sync'"
        ).fetchone()
        if sync_table:
            assert conn.execute("SELECT COUNT(*) FROM pipeline_catalog_sync").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM pipeline_operations").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM jobs_fts").fetchone()[0] == 1


def test_catalog_publish_rejects_corrupt_or_tampered_uploads(publish_client):
    client, live = publish_client
    before = live.read_bytes()

    corrupt = client.post(
        "/api/admin/pipeline/database",
        files={"snapshot": ("jobs.db.gz", b"not a gzip", "application/gzip")},
        headers={
            "X-Pipeline-Sync-Token": TOKEN,
            "X-Pipeline-Run-Id": "bad",
            "X-Pipeline-Snapshot-SHA256": "0" * 64,
        },
    )

    assert corrupt.status_code == 400
    assert live.read_bytes() == before


def test_catalog_publish_rejects_a_catastrophic_empty_board(publish_client, tmp_path):
    client, live = publish_client
    incoming = _migrated(tmp_path / "empty.db", [("workday", "W2", "Closed Role", 0)])

    response = _post(client, incoming)

    assert response.status_code == 400
    with sqlite3.connect(live) as conn:
        assert conn.execute("SELECT COUNT(*) FROM jobs WHERE is_active=1").fetchone()[0] == 2


def test_catalog_publish_is_atomic_and_preserves_railway_owned_data(publish_client, tmp_path):
    client, live = publish_client
    incoming = _migrated(
        tmp_path / "incoming.db",
        [
            ("workday", "W1", "Fresh pipeline title", 1),
            ("jobsdb", "J2", "Brand new pipeline Role", 1),
        ],
    )
    with sqlite3.connect(incoming) as conn:
        conn.execute(
            """
            INSERT INTO job_enrichments (
                source, source_id, seniority, salary_estimated_min,
                salary_estimated_max
            ) VALUES ('workday', 'W1', 'senior', 50000, 70000)
            """
        )

    response = _post(client, incoming, run_id="777")

    assert response.status_code == 200, response.text
    assert response.json()["source_run_id"] == "777"
    assert response.json()["active_jobs"] == 3  # two pipeline + one preserved direct

    with sqlite3.connect(live) as conn:
        conn.row_factory = sqlite3.Row
        rows = {
            (r["source"], r["source_id"]): r["title"]
            for r in conn.execute("SELECT source, source_id, title FROM jobs")
        }
        assert rows == {
            ("workday", "W1"): "Human-corrected title",
            ("jobsdb", "J2"): "Brand new pipeline Role",
            ("direct", "D1"): "Approved direct Role",
        }
        enrichment = conn.execute(
            "SELECT salary_estimated_max, manually_edited_at FROM job_enrichments "
            "WHERE source='workday' AND source_id='W1'"
        ).fetchone()
        assert enrichment[0] == 88000
        assert enrichment[1]
        assert conn.execute("SELECT COUNT(*) FROM admin_edits").fetchone()[0] == 2
        assert conn.execute(
            "SELECT run_id FROM pipeline_operations"
        ).fetchone()[0] == "railway-current"
        assert (
            conn.execute("SELECT source_run_id FROM pipeline_catalog_sync").fetchone()[0] == "777"
        )
        assert conn.execute("SELECT COUNT(*) FROM jobs_fts").fetchone()[0] == 3

    backups = list((live.parent / "catalog-backups").glob("jobs-before-777-*.db.gz"))
    assert len(backups) == 1


def test_catalog_publish_can_be_retried_idempotently(publish_client, tmp_path):
    client, _live = publish_client
    incoming = _migrated(tmp_path / "incoming.db", [("workday", "W1", "Fresh", 1)])

    first = _post(client, incoming, run_id="888")
    second = _post(client, incoming, run_id="888")

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["already_published"] is True


def test_catalog_publish_adds_the_allowlisted_closed_at_migration(
    publish_client, tmp_path
):
    client, live = publish_client
    with sqlite3.connect(live) as conn:
        conn.execute("ALTER TABLE jobs DROP COLUMN closed_at")
    incoming = _migrated(tmp_path / "incoming.db", [("workday", "W1", "Fresh", 1)])

    response = _post(client, incoming, run_id="legacy-volume")

    assert response.status_code == 200, response.text
    with sqlite3.connect(live) as conn:
        assert "closed_at" in {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
