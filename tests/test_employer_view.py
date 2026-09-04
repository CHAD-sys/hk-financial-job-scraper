"""
Tests for the Employer's perspective — webapp/backend/employer_view.py and the
`/api/admin/employers/{id}/activity` route over it.

What these pin, and why each one is here rather than assumed:

  1. The gate. Ultimate Admin only, like the account directory it is reached
     from — an ordinary admin gets 403, not a partial answer.
  2. Attribution is EVIDENCE, not a guess. /api/post-role stores no employer_id
     (main.py's RoleIn), so a submission is matched by contact_email or by
     company name and every row says which. A test that only checked "the right
     submissions came back" would pass just as happily against a module that
     merged both and asserted more than we know.
  3. `standing` explains why a Role is off the board. The interesting case is
     `capped`: a Role that is open, primary, visible and freshly posted, and
     still not browsable because ADR 0035 allows 60 per employer. That is the
     answer an admin could not give an Employer before this existed, and it is
     the one state derived as a residual, so it is the one most able to rot.
  4. `board_roles` is the board's own answer. Seeded here as a Role a visitor
     genuinely cannot open (capped out) alongside ones they can, so a panel
     that queried `is_active = 1` by hand would go red.
  5. No password hash reaches the wire. `get_employer` is a `SELECT *`.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from .support import days_ago, job, make_app, make_bundle, make_jobs_db

ADMIN = {"email": "admin@example.com", "password": "correct-horse-battery", "display_name": "Root"}
PLAIN_ADMIN = {"email": "plain@example.com", "password": "correct-horse-battery", "display_name": "Des"}
EMPLOYER = {
    "email": "hr@acmecapital.com",
    "password": "correct-horse-battery",
    "company_name": "Acme Capital",
    "contact_name": "Jamie Lee",
}

#: ADR 0035's per-employer cap. Seeding one more than this is what makes the
#: `capped` standing observable at all.
CAP = 60


@pytest.fixture()
def db(tmp_path):
    """Acme with 62 open Roles — 61 fresh, 1 aged out — plus a rival employer.

    61 fresh is deliberate: the cap is 60, so exactly one fresh, open, primary,
    visible Role must fall off the board and be reported as `capped`. The rival
    exists so a matching bug that ignored the company filter would show up as a
    count, not just as a missing assertion.
    """
    path = tmp_path / "jobs.db"
    rows = [
        job(
            source="direct",
            source_id=f"A{i}",
            company="Acme Capital",
            title=f"Credit Analyst {i}",
            # Descending freshness, so which Role the cap drops is deterministic:
            # A0 is newest, A60 the oldest of the fresh ones.
            posted_at=days_ago(i % 25),
        )
        for i in range(CAP + 1)
    ]
    rows.append(
        job(source="direct", source_id="OLD", company="Acme Capital",
            title="Ancient Role", posted_at=days_ago(200))
    )
    rows.append(
        job(source="direct", source_id="SHUT", company="Acme Capital",
            title="Closed Role", is_active=0)
    )
    rows.append(
        job(source="direct", source_id="DUPE", company="Acme Capital",
            title="Cross-posted copy", is_primary=0, cross_posted=1)
    )
    rows.append(
        job(source="direct", source_id="HIDE", company="Acme Capital",
            title="Hidden Role", admin_hidden=1)
    )
    rows.append(
        job(source="workday", source_id="R1", company="Rival Bank", title="Rival Role")
    )
    make_jobs_db(path, jobs=rows)
    return path


@pytest.fixture()
def dist(tmp_path):
    d = tmp_path / "dist"
    make_bundle(d)
    return d


@pytest.fixture()
def _stores_env(tmp_path, monkeypatch):
    import employers_store
    import seekers_store

    monkeypatch.setenv("SEEKERS_DB_PATH", str(tmp_path / "seekers.db"))
    monkeypatch.setenv("EMPLOYERS_DB_PATH", str(tmp_path / "employers.db"))
    seekers_store.reset_store()
    employers_store.reset_store()


def _submission(**over):
    base = {
        "contact_name": "Jamie Lee", "contact_email": "hr@acmecapital.com",
        "company": "Acme Capital", "title": "Credit Analyst",
        "location": "Central, Hong Kong", "employment_type": "Full-time",
        "salary_range": "", "description": "Analyse credit risk.",
        "apply_url": "https://example.test/apply",
        "received_at": "2026-08-05T09:00:00+00:00", "status": "pending",
    }
    base.update(over)
    return base


@pytest.fixture()
def queue(tmp_path):
    """The moderation queue, written before any client reads it."""
    def write(rows):
        path = tmp_path / "submitted_roles.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        return path
    return write


def _promote(email: str, *, ultimate: bool) -> None:
    import seekers_store

    store = seekers_store.get_store()
    row = store.get_seeker_by_email(email)
    store.set_admin(row["id"], True)
    if ultimate:
        store.set_super_admin(row["id"], True)


@pytest.fixture()
def employer_id(db, dist, tmp_path, _stores_env):
    """A registered Employer, created through the real endpoint."""
    c = TestClient(make_app(db, dist, tmp_path, cookie_secure=False))
    return c.post("/api/employer/register", json=EMPLOYER).json()["id"]


@pytest.fixture()
def ultimate(db, dist, tmp_path, _stores_env):
    c = TestClient(make_app(db, dist, tmp_path, cookie_secure=False))
    c.post("/api/auth/register", json=ADMIN)
    _promote(ADMIN["email"], ultimate=True)
    return c


@pytest.fixture()
def ordinary_admin(db, dist, tmp_path, _stores_env):
    c = TestClient(make_app(db, dist, tmp_path, cookie_secure=False))
    c.post("/api/auth/register", json=PLAIN_ADMIN)
    _promote(PLAIN_ADMIN["email"], ultimate=False)
    return c


def _activity(client, employer_id, **params):
    return client.get(f"/api/admin/employers/{employer_id}/activity", params=params)


# ── The gate ──────────────────────────────────────────────────────────────────


def test_an_ordinary_admin_cannot_read_an_employers_perspective(ordinary_admin, employer_id):
    """Same posture as the account directory this is reached from — the ADR 0019
    widening covered Role correction, not another account's personal data."""
    assert _activity(ordinary_admin, employer_id).status_code == 403


def test_an_unknown_employer_is_404(ultimate):
    assert _activity(ultimate, "no-such-employer").status_code == 404


def test_the_password_hash_never_reaches_the_wire(ultimate, employer_id):
    """`employers_store.get_employer` is a SELECT * — this asserts the read
    model's whitelist, not the store's discretion."""
    r = _activity(ultimate, employer_id)
    assert r.status_code == 200
    assert "password_hash" not in r.text
    assert "password" not in r.json()["employer"]


# ── Attribution ───────────────────────────────────────────────────────────────


def test_a_submission_from_the_accounts_own_address_is_matched_by_email(
    ultimate, employer_id, queue
):
    queue([_submission(title="From the account")])
    rows = _activity(ultimate, employer_id).json()["submissions"]
    assert [r["title"] for r in rows] == ["From the account"]
    assert rows[0]["matched_by"] == "email"


def test_a_colleagues_submission_is_matched_by_company_and_says_so(
    ultimate, employer_id, queue
):
    """The weaker claim. It is still shown — a colleague posting under the same
    company is the common case — but never as the same kind of fact as an
    address match, because two real employers can share a name."""
    queue([_submission(title="From a colleague", contact_email="colleague@acmecapital.com")])
    rows = _activity(ultimate, employer_id).json()["submissions"]
    assert [r["title"] for r in rows] == ["From a colleague"]
    assert rows[0]["matched_by"] == "company"


def test_another_employers_submission_is_not_attributed(ultimate, employer_id, queue):
    queue([_submission(title="Not theirs", company="Rival Bank",
                       contact_email="hr@rivalbank.com")])
    assert _activity(ultimate, employer_id).json()["submissions"] == []


def test_matching_on_both_reports_the_stronger_claim(ultimate, employer_id, queue):
    """Both the address and the company match. `email` wins, so an admin reading
    the panel never has to reason about precedence."""
    queue([_submission(title="Both")])
    assert _activity(ultimate, employer_id).json()["submissions"][0]["matched_by"] == "email"


def test_email_matching_ignores_case(ultimate, employer_id, queue):
    queue([_submission(title="Shouty", contact_email="HR@ACMECAPITAL.COM")])
    rows = _activity(ultimate, employer_id).json()["submissions"]
    assert rows[0]["matched_by"] == "email"


def test_submissions_come_back_newest_first(ultimate, employer_id, queue):
    queue([
        _submission(title="Older", received_at="2026-08-01T09:00:00+00:00"),
        _submission(title="Newer", received_at="2026-08-09T09:00:00+00:00"),
    ])
    rows = _activity(ultimate, employer_id).json()["submissions"]
    assert [r["title"] for r in rows] == ["Newer", "Older"]


def test_a_rejected_submission_carries_its_reason(ultimate, employer_id, queue):
    """The whole point of the panel: an admin can answer "what happened to my
    role?" without opening the JSONL file."""
    queue([_submission(title="No", status="rejected", rejected_reason="Not a HK role")])
    row = _activity(ultimate, employer_id).json()["submissions"][0]
    assert row["status"] == "rejected"
    assert row["rejected_reason"] == "Not a HK role"


# ── Standing: why a Role is, or is not, on the board ──────────────────────────


def test_the_per_employer_cap_is_reported_as_capped_not_as_missing(ultimate, employer_id):
    """ADR 0035 allows 60 Roles per employer on the board. The 61st is open,
    primary, not hidden and freshly posted — everything an Employer would call
    live — and a visitor still cannot browse to it. Before this view there was
    no way to say that; a bug that dropped the row entirely would leave the
    counts silently short, so both halves are asserted."""
    standing = _activity(ultimate, employer_id).json()["standing"]
    assert standing["on_board"] == CAP
    assert standing["capped"] == 1


def test_every_off_board_reason_is_named(ultimate, employer_id):
    standing = _activity(ultimate, employer_id).json()["standing"]
    assert standing["aged_out"] == 1
    assert standing["closed"] == 1
    assert standing["duplicate"] == 1
    assert standing["hidden"] == 1


def test_the_standings_account_for_every_role_and_only_this_employers(
    ultimate, employer_id, db
):
    """Nothing lost, nothing borrowed: the states must partition this Employer's
    rows exactly, and the rival's Role must not appear in any of them."""
    import sqlite3

    conn = sqlite3.connect(db)
    mine = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE company = 'Acme Capital'"
    ).fetchone()[0]
    conn.close()

    standing = _activity(ultimate, employer_id).json()["standing"]
    assert sum(standing.values()) == mine


def test_an_employer_with_nothing_on_the_board_gets_a_full_zeroed_shape(
    ultimate, db, dist, tmp_path, _stores_env
):
    """Every state present and zero, so the panel cannot render "no data" where
    the honest answer is "none in that state"."""
    c = TestClient(make_app(db, dist, tmp_path, cookie_secure=False))
    new_id = c.post(
        "/api/employer/register",
        json={**EMPLOYER, "email": "hr@nowhere.com", "company_name": "Nowhere Ltd"},
    ).json()["id"]

    body = _activity(ultimate, new_id).json()
    assert body["standing"] == {
        "on_board": 0, "capped": 0, "aged_out": 0,
        "undated": 0, "hidden": 0, "duplicate": 0, "closed": 0,
    }
    assert body["board_roles"] == []


# ── The board list ────────────────────────────────────────────────────────────


def test_board_roles_are_the_boards_own_answer(ultimate, employer_id):
    """Read through job_read.list_jobs at BOARD visibility, so a Role that is
    open but capped, aged out, hidden or a cross-post copy cannot appear here."""
    body = _activity(ultimate, employer_id).json()
    titles = {role["title"] for role in body["board_roles"]}
    assert len(body["board_roles"]) == body["board_sample_size"]
    assert "Ancient Role" not in titles
    assert "Closed Role" not in titles
    assert "Hidden Role" not in titles
    assert "Cross-posted copy" not in titles


def test_another_employers_roles_never_appear(ultimate, employer_id):
    body = _activity(ultimate, employer_id).json()
    assert all(role["company"] == "Acme Capital" for role in body["board_roles"])


# ── The lens ──────────────────────────────────────────────────────────────────


def test_the_lens_reports_which_spellings_were_matched(ultimate, employer_id):
    lens = _activity(ultimate, employer_id).json()["lens"]
    assert lens["company"] == "Acme Capital"
    assert lens["matched_spellings"] == ["Acme Capital"]
    assert lens["overridden"] is False


def test_the_company_override_repoints_the_lens(ultimate, employer_id):
    """The escape hatch for an account whose registered name is not how the
    board spells the employer. Matching is deliberately exact, so without this
    such an account would show zero Roles with no way to check."""
    body = _activity(ultimate, employer_id, company="Rival Bank").json()
    assert body["lens"]["overridden"] is True
    assert body["lens"]["matched_spellings"] == ["Rival Bank"]
    assert [r["company"] for r in body["board_roles"]] == ["Rival Bank"]
    # The account itself is unchanged — this is a read, not an edit.
    assert body["employer"]["company_name"] == "Acme Capital"


def test_an_override_that_matches_nothing_is_an_empty_answer_not_an_error(
    ultimate, employer_id
):
    body = _activity(ultimate, employer_id, company="No Such Employer").json()
    assert body["lens"]["matched_spellings"] == []
    assert body["board_roles"] == []
    assert body["standing"]["on_board"] == 0
