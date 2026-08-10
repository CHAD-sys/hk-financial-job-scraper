"""
Tests for the seekers.db storage layer.

The theme is that this file holds the only copy of the account data there is
(ADR 0006) and that its delete really deletes (ADR 0007), so the tests are about
the guarantees rather than the CRUD: the path never resolves to jobs.db,
migrations are safe to re-run, uniqueness is enforced by the database, deletion
leaves nothing behind but the event, and none of it needs a network or a server.

Every test gets its own file under tmp_path — no shared state, no cleanup.
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import timedelta
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent / "webapp" / "backend"
sys.path.insert(0, str(BACKEND))

from seekers_store import (  # noqa: E402 — path must be set up first
    EmailAlreadyRegistered,
    SeekerStore,
    from_iso,
    normalise_email,
    resolve_seekers_db_path,
    utcnow,
)


@pytest.fixture()
def store(tmp_path) -> SeekerStore:
    return SeekerStore(tmp_path / "seekers.db")


# ── Where the file lives ──────────────────────────────────────────────────────


def test_path_defaults_next_to_the_jobs_db_volume(tmp_path, monkeypatch):
    """On Railway JOBS_DB_PATH=/data/jobs.db, so seekers.db must land on /data too."""
    monkeypatch.delenv("SEEKERS_DB_PATH", raising=False)
    monkeypatch.setenv("JOBS_DB_PATH", str(tmp_path / "volume" / "jobs.db"))
    assert resolve_seekers_db_path() == (tmp_path / "volume" / "seekers.db").resolve()


def test_explicit_env_override_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEKERS_DB_PATH", str(tmp_path / "elsewhere.db"))
    assert resolve_seekers_db_path() == (tmp_path / "elsewhere.db").resolve()


def test_refuses_to_be_jobs_db(tmp_path, monkeypatch):
    """The invariant from ADR 0006, enforced rather than merely documented."""
    monkeypatch.setenv("SEEKERS_DB_PATH", str(tmp_path / "jobs.db"))
    with pytest.raises(ValueError, match="jobs.db"):
        resolve_seekers_db_path()
    with pytest.raises(ValueError, match="jobs.db"):
        SeekerStore(tmp_path / "jobs.db")


# ── Migrations ────────────────────────────────────────────────────────────────


def _schema(db_path: Path) -> set[tuple[str, str]]:
    conn = sqlite3.connect(db_path)
    try:
        return {
            (row[0], row[1])
            for row in conn.execute(
                "SELECT type, name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
    finally:
        conn.close()


def test_migrations_create_every_table(store):
    names = {name for kind, name in _schema(store.db_path) if kind == "table"}
    assert {
        "seekers",
        "seeker_identities",
        "sessions",
        "email_tokens",
        "saved_roles",
        "seeker_discovery_events",
        "recommendation_impressions",
        "recommendation_feedback",
        "recommendation_settings",
        "recommendation_hidden_employers",
        "seeker_resumes",
        "events",
    } <= names


def test_migrations_are_idempotent(tmp_path):
    """Run twice — second run must be a no-op, not an error, and not a schema change."""
    db_path = tmp_path / "seekers.db"
    first = SeekerStore(db_path)
    seeker_id = first.create_seeker("alice@example.com")
    before = _schema(db_path)

    first.migrate()  # explicit re-run
    second = SeekerStore(db_path)  # and a fresh store, which migrates in __init__

    assert _schema(db_path) == before
    assert second.get_seeker(seeker_id) is not None  # data survived


def test_wal_mode_is_on(store):
    conn = sqlite3.connect(store.db_path)
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    finally:
        conn.close()


# ── Seekers ───────────────────────────────────────────────────────────────────


def test_create_and_fetch(store):
    seeker_id = store.create_seeker(
        "Alice@Example.COM ", password_hash="not-a-real-hash", display_name="Alice"
    )
    assert len(seeker_id) == 36 and seeker_id.count("-") == 4  # uuid4 shape

    seeker = store.get_seeker(seeker_id)
    assert seeker["email"] == "alice@example.com"  # normalised on the way in
    assert seeker["display_name"] == "Alice"
    assert seeker["email_verified"] == 0
    assert seeker["last_login_at"] is None
    assert store.get_seeker_by_email("ALICE@example.com")["id"] == seeker_id


def test_seeker_id_is_not_the_email(store):
    """ADR 0006: the identifier is opaque. Email is mutable and must never key anything."""
    seeker_id = store.create_seeker("alice@example.com")
    assert "alice" not in seeker_id
    assert "@" not in seeker_id


def test_duplicate_email_is_refused_by_the_database(store):
    store.create_seeker("alice@example.com")
    with pytest.raises(EmailAlreadyRegistered):
        store.create_seeker("ALICE@EXAMPLE.COM")  # same address, different casing


def test_password_hash_is_nullable_for_oauth_only_seekers(store):
    seeker_id = store.create_seeker("bob@example.com", email_verified=True)
    assert store.get_seeker(seeker_id)["password_hash"] is None
    assert store.get_seeker(seeker_id)["email_verified"] == 1


# ── Admin Mode (is_admin, username) ───────────────────────────────────────────


def test_new_seekers_are_not_admin_by_default(store):
    seeker_id = store.create_seeker("alice@example.com")
    assert store.get_seeker(seeker_id)["is_admin"] == 0


def test_set_admin_toggles_is_admin(store):
    seeker_id = store.create_seeker("alice@example.com")
    store.set_admin(seeker_id, True)
    assert store.get_seeker(seeker_id)["is_admin"] == 1
    store.set_admin(seeker_id, False)
    assert store.get_seeker(seeker_id)["is_admin"] == 0


def test_username_starts_unset(store):
    seeker_id = store.create_seeker("alice@example.com")
    assert store.get_seeker(seeker_id)["username"] is None
    assert store.get_seeker_by_username("alice") is None


def test_set_username_and_look_it_up(store):
    seeker_id = store.create_seeker("kenson@finexclub.org")
    store.set_username(seeker_id, "kenson")
    assert store.get_seeker_by_username("kenson")["id"] == seeker_id


def test_username_lookup_is_case_and_whitespace_insensitive(store):
    seeker_id = store.create_seeker("kenson@finexclub.org")
    store.set_username(seeker_id, "Kenson")
    assert store.get_seeker(seeker_id)["username"] == "kenson"  # stored normalised
    assert store.get_seeker_by_username(" KENSON ")["id"] == seeker_id


def test_duplicate_username_is_refused_by_the_database(store):
    a = store.create_seeker("a@example.com")
    b = store.create_seeker("b@example.com")
    store.set_username(a, "kenson")
    with pytest.raises(sqlite3.IntegrityError):
        store.set_username(b, "KENSON")  # same handle, different casing


def test_seekers_with_no_username_never_collide(store):
    """SQLite's UNIQUE index treats every NULL as distinct — the near-totality
    of Seekers, who never set a username, must not be limited to one account."""
    store.create_seeker("a@example.com")
    store.create_seeker("b@example.com")  # neither call raises


def test_clearing_a_username_frees_it_for_reuse(store):
    a = store.create_seeker("a@example.com")
    b = store.create_seeker("b@example.com")
    store.set_username(a, "kenson")
    store.set_username(a, None)
    store.set_username(b, "kenson")  # does not raise: a's claim was released
    assert store.get_seeker_by_username("kenson")["id"] == b


def test_set_password_and_verification_and_login(store):
    seeker_id = store.create_seeker("carol@example.com")
    store.set_password_hash(seeker_id, "hash-v2")
    store.set_email_verified(seeker_id)
    store.touch_last_login(seeker_id)

    seeker = store.get_seeker(seeker_id)
    assert seeker["password_hash"] == "hash-v2"
    assert seeker["email_verified"] == 1
    assert from_iso(seeker["last_login_at"]) <= utcnow()


def test_normalise_email_does_not_mangle_the_local_part(store):
    """Gmail dot/plus rules are deliberately NOT applied — merging two people is worse."""
    assert normalise_email(" A.Lice+jobs@Example.com ") == "a.lice+jobs@example.com"


# ── Identities ────────────────────────────────────────────────────────────────


def test_identity_link_is_idempotent(store):
    seeker_id = store.create_seeker("dana@example.com", email_verified=True)
    store.link_identity(seeker_id, "google", "sub-123")
    store.link_identity(seeker_id, "google", "sub-123")

    assert store.get_identity("google", "sub-123")["seeker_id"] == seeker_id
    assert len(store.list_identities(seeker_id)) == 1
    assert store.get_identity("google", "unknown-sub") is None


def test_one_seeker_can_hold_several_providers(store):
    seeker_id = store.create_seeker("dana@example.com", email_verified=True)
    store.link_identity(seeker_id, "google", "sub-123")
    store.link_identity(seeker_id, "linkedin", "sub-456")
    assert len(store.list_identities(seeker_id)) == 2


# ── Sessions ──────────────────────────────────────────────────────────────────


def test_session_round_trip_and_revocation(store):
    seeker_id = store.create_seeker("erin@example.com")
    expires = utcnow() + timedelta(days=90)
    store.insert_session("hash-a", seeker_id, expires, user_agent="pytest")

    session = store.get_session("hash-a")
    assert session["seeker_id"] == seeker_id
    assert session["user_agent"] == "pytest"

    assert store.delete_session("hash-a") is True
    assert store.get_session("hash-a") is None
    assert store.delete_session("hash-a") is False


def test_revoking_all_sessions(store):
    seeker_id = store.create_seeker("erin@example.com")
    other_id = store.create_seeker("frank@example.com")
    expires = utcnow() + timedelta(days=90)
    for token_hash in ("h1", "h2", "h3"):
        store.insert_session(token_hash, seeker_id, expires)
    store.insert_session("h4", other_id, expires)

    assert store.delete_sessions_for_seeker(seeker_id) == 3
    assert store.count_sessions(seeker_id) == 0
    assert store.count_sessions(other_id) == 1  # untouched


def test_purge_expired_sessions_leaves_live_ones(store):
    seeker_id = store.create_seeker("erin@example.com")
    now = utcnow()
    store.insert_session("live", seeker_id, now + timedelta(days=90))
    store.insert_session("dead", seeker_id, now - timedelta(seconds=1))

    assert store.purge_expired_sessions(now=now) == 1
    assert store.get_session("live") is not None
    assert store.get_session("dead") is None


# ── Email tokens ──────────────────────────────────────────────────────────────


def test_email_token_claim_is_single_use(store):
    seeker_id = store.create_seeker("gita@example.com")
    store.insert_email_token("tok-hash", seeker_id, "verify", utcnow() + timedelta(hours=1))

    assert store.claim_email_token("tok-hash") is True
    assert store.claim_email_token("tok-hash") is False  # the second click loses
    assert store.get_email_token("tok-hash")["used_at"] is not None


def test_email_token_purpose_is_constrained(store):
    seeker_id = store.create_seeker("gita@example.com")
    with pytest.raises(ValueError):
        store.insert_email_token("x", seeker_id, "login", utcnow() + timedelta(hours=1))


def test_deleting_tokens_by_purpose(store):
    seeker_id = store.create_seeker("gita@example.com")
    expires = utcnow() + timedelta(hours=1)
    store.insert_email_token("v1", seeker_id, "verify", expires)
    store.insert_email_token("r1", seeker_id, "reset", expires)

    assert store.delete_email_tokens(seeker_id, "reset") == 1
    assert store.get_email_token("v1") is not None
    assert store.get_email_token("r1") is None


# ── Saved roles ───────────────────────────────────────────────────────────────


def test_saving_a_role_is_idempotent(store):
    seeker_id = store.create_seeker("hana@example.com")
    store.save_role(seeker_id, "jobsdb", "job-1")
    store.save_role(seeker_id, "jobsdb", "job-1")

    saved = store.list_saved_roles(seeker_id)
    assert len(saved) == 1
    assert (saved[0]["source"], saved[0]["source_id"]) == ("jobsdb", "job-1")


def test_saved_role_stores_a_reference_not_a_copy(store):
    """CONTEXT.md: a Saved Role is a reference to a Role, never a snapshot of one."""
    seeker_id = store.create_seeker("hana@example.com")
    store.save_role(seeker_id, "workday", "job-2")
    columns = set(store.list_saved_roles(seeker_id)[0])
    assert columns == {"seeker_id", "source", "source_id", "saved_at"}
    assert not columns & {"title", "company", "url", "description"}


def test_unsave(store):
    seeker_id = store.create_seeker("hana@example.com")
    store.save_role(seeker_id, "jobsdb", "job-1")
    assert store.unsave_role(seeker_id, "jobsdb", "job-1") is True
    assert store.unsave_role(seeker_id, "jobsdb", "job-1") is False
    assert store.list_saved_roles(seeker_id) == []


def test_merge_is_a_union_and_idempotent(store):
    """Decision 14: first sign-in lifts localStorage saves in without losing either set."""
    seeker_id = store.create_seeker("hana@example.com")
    store.save_role(seeker_id, "jobsdb", "already-here")

    added = store.merge_saved_roles(seeker_id, [("jobsdb", "already-here"), ("indeed", "new-one")])
    assert added == 1
    assert len(store.list_saved_roles(seeker_id)) == 2

    again = store.merge_saved_roles(seeker_id, [("jobsdb", "already-here"), ("indeed", "new-one")])
    assert again == 0
    assert len(store.list_saved_roles(seeker_id)) == 2


# ── Recommendation signals ───────────────────────────────────────────────────


def test_discovery_events_persist_search_filters_and_result_count(store):
    seeker_id = store.create_seeker("hana@example.com")
    now = utcnow()

    created = store.record_discovery(
        seeker_id,
        search_query=" Credit Risk ",
        filters={"sectors": ["Banking"], "seniority": ["mid"]},
        result_count=42,
        now=now,
    )

    assert created is True
    assert store.list_discovery_events(seeker_id) == [
        {
            "id": 1,
            "seeker_id": seeker_id,
            "search_query": "credit risk",
            "filters_json": '{"sectors":["Banking"],"seniority":["mid"]}',
            "result_count": 42,
            "created_at": now.isoformat(),
        }
    ]


def test_discovery_events_suppress_refresh_duplicates_but_keep_changed_intent(store):
    seeker_id = store.create_seeker("hana@example.com")
    now = utcnow()
    kwargs = {
        "search_query": "risk",
        "filters": {"sectors": ["Banking"]},
        "result_count": 10,
    }

    assert store.record_discovery(seeker_id, **kwargs, now=now) is True
    assert store.record_discovery(
        seeker_id, **kwargs, now=now + timedelta(minutes=2)
    ) is False
    assert store.record_discovery(
        seeker_id,
        search_query="risk",
        filters={"sectors": ["Insurance"]},
        result_count=3,
        now=now + timedelta(minutes=2),
    ) is True
    assert len(store.list_discovery_events(seeker_id)) == 2


def test_recommendation_impressions_and_click_are_auditable(store):
    seeker_id = store.create_seeker("hana@example.com")
    now = utcnow()
    batch_id = store.record_recommendation_impressions(
        seeker_id,
        [
            {
                "source": "workday",
                "source_id": "job-1",
                "score": 12.5,
                "reasons": ["Matches your Banking searches", "Uses credit risk"],
                "position": 1,
            }
        ],
        model_version="signals-v1",
        now=now,
    )

    impressions = store.list_recommendation_impressions(seeker_id)
    assert len(impressions) == 1
    assert impressions[0]["batch_id"] == batch_id
    assert impressions[0]["reasons_json"] == (
        '["Matches your Banking searches","Uses credit risk"]'
    )
    assert impressions[0]["clicked_at"] is None

    assert store.mark_recommendation_clicked(
        seeker_id, "workday", "job-1", now=now + timedelta(seconds=5)
    ) is True
    assert store.list_recommendation_impressions(seeker_id)[0]["clicked_at"] == (
        now + timedelta(seconds=5)
    ).isoformat()


def test_recommendation_feedback_settings_and_hidden_employers_round_trip(store):
    seeker_id = store.create_seeker("feedback@example.com")

    assert store.get_recommendation_settings(seeker_id) == {
        "personalization_enabled": True,
        "use_saved_roles": True,
        "use_discovery": True,
        "use_clicks": True,
    }
    store.update_recommendation_settings(
        seeker_id,
        personalization_enabled=False,
        use_clicks=False,
    )
    assert store.get_recommendation_settings(seeker_id) == {
        "personalization_enabled": False,
        "use_saved_roles": True,
        "use_discovery": True,
        "use_clicks": False,
    }

    store.record_recommendation_feedback(
        seeker_id, "workday", "job-1", action="more_like"
    )
    # The two intent actions are mutually exclusive: changing your mind should
    # replace the old choice rather than leave contradictory training labels.
    store.record_recommendation_feedback(
        seeker_id, "workday", "job-1", action="not_interested"
    )
    store.record_recommendation_feedback(
        seeker_id,
        "workday",
        "job-2",
        action="wrong_reason",
        detail="Matches your Banking searches",
    )
    feedback = store.list_recommendation_feedback(seeker_id)
    assert {(row["source_id"], row["action"]) for row in feedback} == {
        ("job-1", "not_interested"),
        ("job-2", "wrong_reason"),
    }

    store.hide_recommendation_employer(seeker_id, "hsbc", "HSBC")
    assert store.list_hidden_recommendation_employers(seeker_id) == [
        {"employer_key": "hsbc", "employer_name": "HSBC"}
    ]
    assert store.unhide_recommendation_employer(seeker_id, "hsbc") is True
    assert store.list_hidden_recommendation_employers(seeker_id) == []


def test_opened_recommendations_are_exposed_as_deduplicated_learning_refs(store):
    seeker_id = store.create_seeker("clicks@example.com")
    now = utcnow()
    for offset in range(2):
        store.record_recommendation_impressions(
            seeker_id,
            [{
                "source": "workday",
                "source_id": "job-1",
                "score": 5.0,
                "reasons": ["Recently listed"],
                "position": 1,
            }],
            model_version="signals-v2",
            now=now + timedelta(minutes=offset),
        )
        store.mark_recommendation_clicked(
            seeker_id,
            "workday",
            "job-1",
            now=now + timedelta(minutes=offset, seconds=2),
        )

    assert store.list_clicked_recommendation_refs(seeker_id) == [
        {"source": "workday", "source_id": "job-1"}
    ]


def test_reset_recommendation_profile_keeps_saved_roles_and_account(store):
    seeker_id = store.create_seeker("reset@example.com")
    store.save_role(seeker_id, "workday", "saved")
    store.record_discovery(
        seeker_id, search_query="risk", filters={}, result_count=3
    )
    store.record_recommendation_feedback(
        seeker_id, "workday", "job-1", action="more_like"
    )
    store.hide_recommendation_employer(seeker_id, "hsbc", "HSBC")
    store.update_recommendation_settings(seeker_id, use_discovery=False)

    store.reset_recommendation_profile(seeker_id)

    assert store.get_seeker(seeker_id) is not None
    assert len(store.list_saved_roles(seeker_id)) == 1
    assert store.list_discovery_events(seeker_id) == []
    assert store.list_recommendation_feedback(seeker_id) == []
    assert store.list_hidden_recommendation_employers(seeker_id) == []
    assert store.get_recommendation_settings(seeker_id)["use_discovery"] is True

# ── Events ────────────────────────────────────────────────────────────────────


def test_events_are_counted_by_name(store):
    seeker_id = store.create_seeker("iris@example.com")
    store.log_event("signup.completed", seeker_id)
    store.log_event("login.succeeded", seeker_id)
    store.log_event("login.succeeded")  # anonymous events are allowed

    assert store.count_events("login.succeeded") == 2
    assert store.count_events("login.succeeded", seeker_id=seeker_id) == 1
    assert store.count_events() == 3


def test_events_hold_nothing_but_name_seeker_and_time(store):
    """Decision 19: first-party counts, not a properties blob that becomes a data store."""
    store.log_event("login.succeeded")
    conn = sqlite3.connect(store.db_path)
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(events)")}
    finally:
        conn.close()
    assert columns == {"id", "name", "seeker_id", "created_at"}


# ── Private resume ───────────────────────────────────────────────────────────


def test_resume_replacement_is_atomic_and_keeps_exactly_one_document(store):
    seeker_id = store.create_seeker("resume@example.com")
    first = b"first resume"
    second = b"second resume"

    assert store.replace_resume(
        seeker_id,
        filename="first.pdf",
        media_type="application/pdf",
        size_bytes=len(first),
        content_sha256="a" * 64,
        file_content=first,
        text_content="First extracted resume text with enough useful evidence.",
    ) is False
    assert store.replace_resume(
        seeker_id,
        filename="second.pdf",
        media_type="application/pdf",
        size_bytes=len(second),
        content_sha256="b" * 64,
        file_content=second,
        text_content="Second extracted resume text with updated useful evidence.",
        analysis={"skills": ["credit risk"]},
    ) is True

    stored = store.get_resume(seeker_id, include_document=True)
    assert stored is not None
    assert stored["filename"] == "second.pdf"
    assert stored["file_content"] == second
    assert stored["analysis"] == {"skills": ["credit risk"]}
    assert store._conn().execute(
        "SELECT COUNT(*) FROM seeker_resumes WHERE seeker_id = ?", (seeker_id,)
    ).fetchone()[0] == 1


def test_resume_can_be_deleted_without_deleting_the_account(store):
    seeker_id = store.create_seeker("resume-delete@example.com")
    content = b"resume"
    store.replace_resume(
        seeker_id,
        filename="resume.pdf",
        media_type="application/pdf",
        size_bytes=len(content),
        content_sha256="c" * 64,
        file_content=content,
        text_content="A resume with enough extracted text to store safely.",
    )

    assert store.delete_resume(seeker_id) is True
    assert store.delete_resume(seeker_id) is False
    assert store.get_resume(seeker_id) is None
    assert store.get_seeker(seeker_id) is not None


# ── Deletion (ADR 0007) ───────────────────────────────────────────────────────


def test_deletion_really_deletes(store):
    seeker_id = store.create_seeker("jane@example.com", password_hash="hash")
    store.link_identity(seeker_id, "google", "sub-jane")
    store.insert_session("sess-jane", seeker_id, utcnow() + timedelta(days=90))
    store.insert_email_token("tok-jane", seeker_id, "verify", utcnow() + timedelta(hours=1))
    store.save_role(seeker_id, "jobsdb", "job-1")
    store.record_discovery(
        seeker_id,
        search_query="risk",
        filters={"sectors": ["Banking"]},
        result_count=1,
    )
    store.record_recommendation_impressions(
        seeker_id,
        [{
            "source": "jobsdb",
            "source_id": "job-1",
            "score": 1.0,
            "reasons": ["Matches Banking"],
            "position": 1,
        }],
        model_version="signals-v1",
    )
    store.record_recommendation_feedback(
        seeker_id, "jobsdb", "job-1", action="not_interested"
    )
    store.hide_recommendation_employer(seeker_id, "hsbc", "HSBC")
    store.update_recommendation_settings(seeker_id, use_clicks=False)
    resume_content = b"private resume"
    store.replace_resume(
        seeker_id,
        filename="resume.pdf",
        media_type="application/pdf",
        size_bytes=len(resume_content),
        content_sha256="d" * 64,
        file_content=resume_content,
        text_content="Private extracted resume text that must be deleted with the account.",
    )
    store.log_event("login.succeeded", seeker_id)

    assert store.delete_seeker(seeker_id) is True

    assert store.get_seeker(seeker_id) is None
    assert store.get_seeker_by_email("jane@example.com") is None
    assert store.get_session("sess-jane") is None
    assert store.count_sessions(seeker_id) == 0
    assert store.get_email_token("tok-jane") is None
    assert store.list_saved_roles(seeker_id) == []
    assert store.list_discovery_events(seeker_id) == []
    assert store.list_recommendation_impressions(seeker_id) == []
    assert store.list_recommendation_feedback(seeker_id) == []
    assert store.list_hidden_recommendation_employers(seeker_id) == []
    assert store.get_resume(seeker_id) is None
    assert store.get_identity("google", "sub-jane") is None
    assert store.list_identities(seeker_id) == []


def test_deletion_logs_an_event_that_survives(store):
    """ADR 0007: you cannot forward a deletion you have no record of."""
    seeker_id = store.create_seeker("jane@example.com")
    store.delete_seeker(seeker_id)

    assert store.count_events("seeker.deleted", seeker_id=seeker_id) == 1
    surviving = store.list_events(seeker_id)
    assert [event["name"] for event in surviving] == ["seeker.deleted"]


def test_deleting_an_unknown_seeker_is_false_not_an_error(store):
    assert store.delete_seeker("00000000-0000-4000-8000-000000000000") is False


def test_deletion_frees_the_email_for_reuse(store):
    """Real deletion means the address is genuinely available again — a flag would not."""
    first = store.create_seeker("jane@example.com")
    store.delete_seeker(first)
    second = store.create_seeker("jane@example.com")
    assert second != first


def test_deletion_leaves_other_seekers_alone(store):
    victim = store.create_seeker("jane@example.com")
    bystander = store.create_seeker("kim@example.com")
    store.insert_session("sess-kim", bystander, utcnow() + timedelta(days=90))
    store.save_role(bystander, "jobsdb", "job-1")

    store.delete_seeker(victim)

    assert store.get_seeker(bystander) is not None
    assert store.get_session("sess-kim") is not None
    assert len(store.list_saved_roles(bystander)) == 1
