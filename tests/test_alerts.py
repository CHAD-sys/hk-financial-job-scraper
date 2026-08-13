"""Behavior contract for the weekly Alerts job (alerts.py)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import job_read
import seekers_store
from alert_unsubscribe import AlertUnsubscribeToken
from alerts import MAX_ROLES_PER_EMAIL, run_weekly_alerts
from sender import RecordingSender

from .support import enrichment, job, make_jobs_db

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
TOKENS = AlertUnsubscribeToken("test-secret")


def _jobs_database(tmp_path, jobs, enrichments):
    path = tmp_path / "jobs.db"
    make_jobs_db(path, jobs=jobs, enrichments=enrichments)
    connection = sqlite3.connect(path)
    job_read.prepare(connection)
    return connection


def _store(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEKERS_DB_PATH", str(tmp_path / "seekers.db"))
    seekers_store.reset_store()
    return seekers_store.get_store()


def _matching_setup(tmp_path, monkeypatch, *, n_candidates: int = 1, companies: list[str] | None = None):
    """A verified, opted-in, due Seeker with one saved Role establishing a
    "credit risk" signal, and `n_candidates` fresh Roles that genuinely match it."""
    store = _store(tmp_path, monkeypatch)
    seeker_id = store.create_seeker("jane@example.com", email_verified=True)
    store.set_alert_opt_in(seeker_id, True)
    store.save_role(seeker_id, "workday", "SAVED", now=NOW - timedelta(days=1))

    companies = companies or [f"Company {i}" for i in range(n_candidates)]
    jobs = [
        job(source="workday", source_id="SAVED", company="HSBC", title="Credit Risk Analyst"),
    ]
    enrichments = [
        enrichment(source="workday", source_id="SAVED", required_skills='["credit risk"]'),
    ]
    for i in range(n_candidates):
        jobs.append(
            job(
                source="workday",
                source_id=f"MATCH-{i}",
                company=companies[i],
                title=f"Credit Risk Manager {i}",
                url=f"https://example.test/match-{i}",
            )
        )
        enrichments.append(
            enrichment(
                source="workday", source_id=f"MATCH-{i}", required_skills='["credit risk"]'
            )
        )
    jobs_conn = _jobs_database(tmp_path, jobs, enrichments)
    return store, seeker_id, jobs_conn


def test_a_due_opted_in_seeker_with_a_genuine_match_gets_emailed(tmp_path, monkeypatch):
    store, seeker_id, jobs_conn = _matching_setup(tmp_path, monkeypatch)
    sender = RecordingSender()

    outcomes = run_weekly_alerts(
        jobs_conn, sender, TOKENS, public_base_url="https://finexcareers.test", now=NOW
    )

    assert [o.seeker_id for o in outcomes] == [seeker_id]
    assert outcomes[0].sent is True
    assert outcomes[0].role_count == 1
    assert sender.recipients == ["jane@example.com"]
    assert "Credit Risk Manager 0" in sender.sent[0].body
    assert "https://example.test/match-0" in sender.sent[0].body
    assert store.list_alerted_role_ids(seeker_id) == {("workday", "MATCH-0")}
    # last_sent_at advanced to NOW: a same-instant re-run's own cutoff
    # (moment - 7 days) must not consider this Seeker due again.
    assert store.seekers_due_for_alert(cutoff=NOW - timedelta(days=7)) == []


def test_never_an_empty_digest(tmp_path, monkeypatch):
    """Opted in, due, has signal, but zero candidates: no email at all."""
    store, seeker_id, jobs_conn = _matching_setup(tmp_path, monkeypatch, n_candidates=0)
    sender = RecordingSender()

    outcomes = run_weekly_alerts(
        jobs_conn, sender, TOKENS, public_base_url="https://finexcareers.test", now=NOW
    )

    assert outcomes == []
    assert sender.sent == []
    # Not marked sent — a Seeker with nothing to say this week is still due
    # again once real signal or new supply shows up, not punished with a wait.
    assert store.seekers_due_for_alert(cutoff=NOW) == [seeker_id]


def test_cold_start_seeker_is_silent_even_when_due(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    seeker_id = store.create_seeker("cold@example.com", email_verified=True)
    store.set_alert_opt_in(seeker_id, True)
    jobs_conn = _jobs_database(
        tmp_path,
        [job(source="workday", source_id="X", title="Analyst")],
        [enrichment(source="workday", source_id="X")],
    )
    sender = RecordingSender()

    outcomes = run_weekly_alerts(
        jobs_conn, sender, TOKENS, public_base_url="https://finexcareers.test", now=NOW
    )

    assert outcomes == []
    assert sender.sent == []


def test_freshness_only_matches_do_not_count(tmp_path, monkeypatch):
    """A Seeker with real signal, but candidates that share nothing with it,
    must not be emailed — a role that only cleared the freshness floor is not
    a match."""
    store = _store(tmp_path, monkeypatch)
    seeker_id = store.create_seeker("jane@example.com", email_verified=True)
    store.set_alert_opt_in(seeker_id, True)
    store.save_role(seeker_id, "workday", "SAVED", now=NOW - timedelta(days=1))

    jobs_conn = _jobs_database(
        tmp_path,
        [
            job(source="workday", source_id="SAVED", company="HSBC", title="Credit Risk Analyst"),
            job(
                source="eightfold",
                source_id="UNRELATED",
                company="AIA",
                title="Actuarial Manager",
            ),
        ],
        [
            enrichment(source="workday", source_id="SAVED", required_skills='["credit risk"]'),
            enrichment(source="eightfold", source_id="UNRELATED"),
        ],
    )
    sender = RecordingSender()

    outcomes = run_weekly_alerts(
        jobs_conn, sender, TOKENS, public_base_url="https://finexcareers.test", now=NOW
    )

    assert outcomes == []
    assert sender.sent == []


def test_not_opted_in_is_never_considered(tmp_path, monkeypatch):
    store, seeker_id, jobs_conn = _matching_setup(tmp_path, monkeypatch)
    store.set_alert_opt_in(seeker_id, False)
    sender = RecordingSender()

    outcomes = run_weekly_alerts(
        jobs_conn, sender, TOKENS, public_base_url="https://finexcareers.test", now=NOW
    )

    assert outcomes == []
    assert sender.sent == []


def test_unverified_email_is_never_mailed(tmp_path, monkeypatch):
    store, seeker_id, jobs_conn = _matching_setup(tmp_path, monkeypatch)
    store.set_email_verified(seeker_id, False)
    sender = RecordingSender()

    outcomes = run_weekly_alerts(
        jobs_conn, sender, TOKENS, public_base_url="https://finexcareers.test", now=NOW
    )

    assert outcomes == []
    assert sender.sent == []


def test_not_due_yet_is_skipped(tmp_path, monkeypatch):
    store, seeker_id, jobs_conn = _matching_setup(tmp_path, monkeypatch)
    store.mark_alert_sent(seeker_id, now=NOW - timedelta(days=2))  # 2 days ago, not 7
    sender = RecordingSender()

    outcomes = run_weekly_alerts(
        jobs_conn, sender, TOKENS, public_base_url="https://finexcareers.test", now=NOW
    )

    assert outcomes == []
    assert sender.sent == []


def test_already_alerted_roles_never_recur(tmp_path, monkeypatch):
    store, seeker_id, jobs_conn = _matching_setup(tmp_path, monkeypatch)
    store.record_alerted_roles(seeker_id, [("workday", "MATCH-0")], now=NOW - timedelta(days=10))
    sender = RecordingSender()

    outcomes = run_weekly_alerts(
        jobs_conn, sender, TOKENS, public_base_url="https://finexcareers.test", now=NOW
    )

    assert outcomes == []
    assert sender.sent == []


def test_selection_is_capped_at_max_roles_per_email(tmp_path, monkeypatch):
    store, seeker_id, jobs_conn = _matching_setup(tmp_path, monkeypatch, n_candidates=12)
    sender = RecordingSender()

    outcomes = run_weekly_alerts(
        jobs_conn, sender, TOKENS, public_base_url="https://finexcareers.test", now=NOW
    )

    assert outcomes[0].role_count == MAX_ROLES_PER_EMAIL
    assert len(store.list_alerted_role_ids(seeker_id)) == MAX_ROLES_PER_EMAIL


def test_a_failed_send_does_not_advance_cadence_or_dedup(tmp_path, monkeypatch):
    """Mail is best-effort (sender.py's contract): a failure must not burn the
    Seeker's dedup list or push their next eligible date out by 7 days for
    nothing — they stay due and are retried on the next run."""
    store, seeker_id, jobs_conn = _matching_setup(tmp_path, monkeypatch)
    sender = RecordingSender(delivers=False)

    outcomes = run_weekly_alerts(
        jobs_conn, sender, TOKENS, public_base_url="https://finexcareers.test", now=NOW
    )

    assert outcomes[0].sent is False
    assert store.list_alerted_role_ids(seeker_id) == set()
    assert store.seekers_due_for_alert(cutoff=NOW) == [seeker_id]


def test_unsubscribe_link_resolves_to_the_seeker(tmp_path, monkeypatch):
    store, seeker_id, jobs_conn = _matching_setup(tmp_path, monkeypatch)
    sender = RecordingSender()

    run_weekly_alerts(jobs_conn, sender, TOKENS, public_base_url="https://finexcareers.test", now=NOW)

    body = sender.sent[0].body
    assert "https://finexcareers.test/unsubscribe?token=" in body
    token = body.split("token=")[1].split("\n")[0].strip()
    assert TOKENS.resolve(token) == seeker_id


def test_only_due_seekers_among_several_get_emailed(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    due = store.create_seeker("due@example.com", email_verified=True)
    not_due = store.create_seeker("not-due@example.com", email_verified=True)
    for seeker_id in (due, not_due):
        store.set_alert_opt_in(seeker_id, True)
        store.save_role(seeker_id, "workday", "SAVED", now=NOW - timedelta(days=1))
    store.mark_alert_sent(not_due, now=NOW - timedelta(days=1))

    jobs_conn = _jobs_database(
        tmp_path,
        [
            job(source="workday", source_id="SAVED", company="HSBC", title="Credit Risk Analyst"),
            job(source="workday", source_id="MATCH", company="Hang Seng", title="Credit Risk Manager"),
        ],
        [
            enrichment(source="workday", source_id="SAVED", required_skills='["credit risk"]'),
            enrichment(source="workday", source_id="MATCH", required_skills='["credit risk"]'),
        ],
    )
    sender = RecordingSender()

    outcomes = run_weekly_alerts(
        jobs_conn, sender, TOKENS, public_base_url="https://finexcareers.test", now=NOW
    )

    assert [o.seeker_id for o in outcomes] == [due]
