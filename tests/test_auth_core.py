"""
Tests for the authentication core — hashing, sessions, single-use email tokens,
provider-identity linking.

These are the tests that would have to fail before an account can be stolen, so
they are written as claims about attacks rather than as coverage: the stored hash
is not the password, the stored session is not the token, an expired or replayed
link does nothing, and an OAuth identity the provider would not vouch for never
inherits an existing account.

No HTTP, no network, no email — auth.py has no web framework in it and these
tests need none either. Each test gets its own seekers.db under tmp_path, and
time is passed in explicitly (`now=`) rather than slept for.
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import timedelta
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent / "webapp" / "backend"
sys.path.insert(0, str(BACKEND))

import auth  # noqa: E402 — path must be set up first
from auth import (  # noqa: E402
    EMAIL_TOKEN_TTL,
    SESSION_REFRESH_INTERVAL,
    SESSION_TTL,
    IdentityClaim,
    IdentityLinkRefused,
    consume_email_token,
    hash_password,
    hash_token,
    issue_email_token,
    issue_session,
    link_or_create_employer,
    link_or_create_seeker,
    password_needs_rehash,
    revoke_all_sessions,
    revoke_session,
    verify_password,
    verify_session,
)
from employers_store import EmployerStore  # noqa: E402
from seekers_store import SeekerStore, from_iso, utcnow  # noqa: E402

PASSWORD = "correct horse battery staple"


@pytest.fixture()
def store(tmp_path) -> SeekerStore:
    return SeekerStore(tmp_path / "seekers.db")


@pytest.fixture()
def seeker_id(store) -> str:
    return store.create_seeker("alice@example.com", password_hash=hash_password(PASSWORD))


@pytest.fixture()
def employer_store(tmp_path) -> EmployerStore:
    return EmployerStore(tmp_path / "employers.db")


@pytest.fixture()
def employer_id(employer_store) -> str:
    return employer_store.create_employer(
        "hr@acme.example", password_hash=hash_password(PASSWORD), company_name="Acme"
    )


# ── Passwords ─────────────────────────────────────────────────────────────────


def test_password_round_trips(store, seeker_id):
    stored = store.get_seeker(seeker_id)["password_hash"]
    assert verify_password(stored, PASSWORD) is True


def test_wrong_password_fails(store, seeker_id):
    stored = store.get_seeker(seeker_id)["password_hash"]
    assert verify_password(stored, "not the password") is False
    assert verify_password(stored, PASSWORD.upper()) is False
    assert verify_password(stored, "") is False


def test_the_hash_is_not_the_password(store, seeker_id):
    stored = store.get_seeker(seeker_id)["password_hash"]
    assert PASSWORD not in stored
    assert stored.startswith("$argon2id$")  # Argon2id specifically, not argon2i/d

    # And the plaintext appears nowhere in the database file itself.
    raw_bytes = Path(store.db_path).read_bytes()
    assert PASSWORD.encode() not in raw_bytes


def test_the_same_password_hashes_differently_each_time(store):
    """Per-hash salt — two Seekers with the same password must not look alike."""
    assert hash_password(PASSWORD) != hash_password(PASSWORD)


def test_missing_hash_is_a_failed_login_not_a_crash(store):
    """A Google-only Seeker has no password. Verifying against None must simply fail."""
    google_only = store.create_seeker("bob@example.com", email_verified=True)
    assert store.get_seeker(google_only)["password_hash"] is None
    assert verify_password(None, PASSWORD) is False


def test_corrupt_hash_never_authenticates(store):
    assert verify_password("not-an-argon2-hash", PASSWORD) is False
    assert verify_password("", PASSWORD) is False


def test_needs_rehash_is_false_for_a_fresh_hash(store):
    assert password_needs_rehash(hash_password(PASSWORD)) is False
    assert password_needs_rehash("garbage") is True


# ── Sessions ──────────────────────────────────────────────────────────────────


def test_session_verifies(store, seeker_id):
    token = issue_session(store, seeker_id, user_agent="pytest")
    assert verify_session(store, token) == seeker_id


def test_raw_session_token_is_never_stored(store, seeker_id):
    """Decision 11: a leaked seekers.db must hand over no live session."""
    token = issue_session(store, seeker_id)

    conn = sqlite3.connect(store.db_path)
    try:
        rows = conn.execute("SELECT token_hash FROM sessions").fetchall()
    finally:
        conn.close()
    assert [row[0] for row in rows] == [hash_token(token)]
    assert token not in [row[0] for row in rows]

    # Not anywhere else in the file either — WAL pages included.
    for path in (store.db_path, Path(str(store.db_path) + "-wal")):
        if Path(path).exists():
            assert token.encode() not in Path(path).read_bytes()


def test_unknown_and_empty_tokens_are_rejected(store, seeker_id):
    issue_session(store, seeker_id)
    assert verify_session(store, "totally-made-up-token") is None
    assert verify_session(store, "") is None
    assert verify_session(store, None) is None


def test_session_expires(store, seeker_id):
    """
    Note each case gets its OWN token: a successful verification rolls the expiry
    forward, so checking "still valid at day 89" and "dead at day 90" against a
    single session would test the rolling window instead of the expiry.
    """
    start = utcnow()
    just_alive = issue_session(store, seeker_id, now=start)
    on_the_boundary = issue_session(store, seeker_id, now=start)
    long_gone = issue_session(store, seeker_id, now=start)

    assert verify_session(store, just_alive, now=start + SESSION_TTL - timedelta(minutes=1)) == (
        seeker_id
    )
    assert verify_session(store, on_the_boundary, now=start + SESSION_TTL) is None
    assert verify_session(store, long_gone, now=start + SESSION_TTL + timedelta(days=1)) is None


def test_expired_session_row_is_dropped_on_the_way_past(store, seeker_id):
    start = utcnow()
    token = issue_session(store, seeker_id, now=start)
    verify_session(store, token, now=start + SESSION_TTL + timedelta(seconds=1))
    assert store.get_session(hash_token(token)) is None


def test_rolling_expiry_extends_on_use(store, seeker_id):
    """The 90-day window is measured from last use, not from sign-in."""
    start = utcnow()
    token = issue_session(store, seeker_id, now=start)
    original_expiry = from_iso(store.get_session(hash_token(token))["expires_at"])

    later = start + timedelta(days=30)
    assert verify_session(store, token, now=later) == seeker_id

    extended_expiry = from_iso(store.get_session(hash_token(token))["expires_at"])
    assert extended_expiry > original_expiry
    assert extended_expiry == later + SESSION_TTL

    # And the session is still alive past the point the ORIGINAL expiry would have
    # killed it — which is the whole point of rolling.
    assert verify_session(store, token, now=original_expiry + timedelta(days=1)) == seeker_id


def test_refresh_is_rate_limited_to_avoid_a_write_per_request(store, seeker_id):
    """Rolling, but not one DB write per authenticated request. See SESSION_REFRESH_INTERVAL."""
    start = utcnow()
    token = issue_session(store, seeker_id, now=start)
    first = store.get_session(hash_token(token))["expires_at"]

    verify_session(store, token, now=start + SESSION_REFRESH_INTERVAL - timedelta(minutes=1))
    assert store.get_session(hash_token(token))["expires_at"] == first  # not rewritten

    verify_session(store, token, now=start + SESSION_REFRESH_INTERVAL)
    assert store.get_session(hash_token(token))["expires_at"] != first  # rewritten


def test_session_revokes(store, seeker_id):
    token = issue_session(store, seeker_id)
    assert revoke_session(store, token) is True
    assert verify_session(store, token) is None
    assert revoke_session(store, token) is False  # already gone


def test_revoke_all_sessions_signs_out_every_device(store, seeker_id):
    other = store.create_seeker("bob@example.com", password_hash=hash_password(PASSWORD))
    tokens = [issue_session(store, seeker_id) for _ in range(3)]
    bystander = issue_session(store, other)

    assert revoke_all_sessions(store, seeker_id) == 3
    assert all(verify_session(store, token) is None for token in tokens)
    assert verify_session(store, bystander) == other  # another Seeker is untouched


def test_two_sessions_are_independent(store, seeker_id):
    laptop = issue_session(store, seeker_id, user_agent="laptop")
    phone = issue_session(store, seeker_id, user_agent="phone")
    assert laptop != phone

    revoke_session(store, laptop)
    assert verify_session(store, laptop) is None
    assert verify_session(store, phone) == seeker_id


def test_deleting_the_seeker_kills_the_session(store, seeker_id):
    token = issue_session(store, seeker_id)
    store.delete_seeker(seeker_id)
    assert verify_session(store, token) is None


# ── Single-use email tokens ───────────────────────────────────────────────────


@pytest.mark.parametrize("purpose", ["verify", "reset"])
def test_email_token_round_trips(store, seeker_id, purpose):
    token = issue_email_token(store, seeker_id, purpose)
    assert consume_email_token(store, token, purpose) == seeker_id


def test_raw_email_token_is_never_stored(store, seeker_id):
    token = issue_email_token(store, seeker_id, "reset")
    conn = sqlite3.connect(store.db_path)
    try:
        stored = [row[0] for row in conn.execute("SELECT token_hash FROM email_tokens")]
    finally:
        conn.close()
    assert stored == [hash_token(token)]
    assert token not in stored


def test_email_token_is_single_use(store, seeker_id):
    token = issue_email_token(store, seeker_id, "reset")
    assert consume_email_token(store, token, "reset") == seeker_id
    assert consume_email_token(store, token, "reset") is None  # replay refused


def test_email_token_expires(store, seeker_id):
    start = utcnow()
    token = issue_email_token(store, seeker_id, "verify", now=start)

    assert consume_email_token(
        store, token, "verify", now=start + EMAIL_TOKEN_TTL - timedelta(seconds=1)
    ) == seeker_id

    replacement = issue_email_token(store, seeker_id, "verify", now=start)
    assert consume_email_token(store, replacement, "verify", now=start + EMAIL_TOKEN_TTL) is None


def test_email_token_ttl_is_at_most_an_hour(store):
    assert EMAIL_TOKEN_TTL <= timedelta(hours=1)


def test_a_verify_token_cannot_be_spent_as_a_reset_token(store, seeker_id):
    """Otherwise signing up would hand out a password-change capability."""
    token = issue_email_token(store, seeker_id, "verify")
    assert consume_email_token(store, token, "reset") is None
    assert consume_email_token(store, token, "verify") == seeker_id  # still unspent


def test_issuing_a_new_token_kills_the_previous_one(store, seeker_id):
    first = issue_email_token(store, seeker_id, "reset")
    second = issue_email_token(store, seeker_id, "reset")

    assert consume_email_token(store, first, "reset") is None
    assert consume_email_token(store, second, "reset") == seeker_id


def test_issuing_can_keep_the_previous_token_when_asked(store, seeker_id):
    first = issue_email_token(store, seeker_id, "verify")
    issue_email_token(store, seeker_id, "verify", invalidate_previous=False)
    assert consume_email_token(store, first, "verify") == seeker_id


def test_unknown_email_token_is_rejected(store, seeker_id):
    issue_email_token(store, seeker_id, "verify")
    assert consume_email_token(store, "made-up", "verify") is None
    assert consume_email_token(store, None, "verify") is None


def test_unknown_purpose_is_refused_at_issue_time(store, seeker_id):
    with pytest.raises(ValueError):
        issue_email_token(store, seeker_id, "login")  # type: ignore[arg-type]


def test_tokens_are_not_guessable_and_are_unique(store, seeker_id):
    tokens = {
        issue_email_token(store, seeker_id, "verify", invalidate_previous=False)
        for _ in range(50)
    }
    assert len(tokens) == 50
    assert all(len(token) >= 40 for token in tokens)


def test_constant_time_comparison_is_used(monkeypatch, store, seeker_id):
    """Token comparison must never become a plain `==` in a later refactor."""
    calls: list[tuple[str, str]] = []
    real = auth.hmac.compare_digest

    def spy(a, b):
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(auth.hmac, "compare_digest", spy)
    token = issue_session(store, seeker_id)
    assert verify_session(store, token) == seeker_id
    assert calls, "verify_session should compare digests with hmac.compare_digest"


# ── Provider identities ───────────────────────────────────────────────────────


def _claim(**overrides) -> IdentityClaim:
    base = dict(
        provider="google",
        subject="google-sub-1",
        email="alice@example.com",
        email_verified=True,
        display_name="Alice",
    )
    base.update(overrides)
    return IdentityClaim(**base)  # type: ignore[arg-type]


def test_unverified_provider_email_does_not_auto_link(store, seeker_id):
    """
    The absolute rule from §4. If this test ever goes green by returning a
    LinkResult instead of raising, anyone who can create a provider account on
    someone's address owns their Seeker account.
    """
    with pytest.raises(IdentityLinkRefused):
        link_or_create_seeker(store, _claim(email_verified=False))

    # Nothing was linked, and the existing account is untouched.
    assert store.get_identity("google", "google-sub-1") is None
    assert store.list_identities(seeker_id) == []
    assert store.get_seeker(seeker_id)["password_hash"] is not None


def test_verified_provider_email_links_to_the_existing_seeker(store, seeker_id):
    result = link_or_create_seeker(store, _claim(email_verified=True))
    assert result.outcome == "linked"
    assert result.seeker_id == seeker_id
    assert store.get_identity("google", "google-sub-1")["seeker_id"] == seeker_id


def test_a_known_identity_is_recognised_without_consulting_the_email(store, seeker_id):
    """`sub` is the key — a Seeker who changed their Google address still signs in."""
    link_or_create_seeker(store, _claim(email_verified=True))

    result = link_or_create_seeker(
        store, _claim(email="alice-new@example.com", email_verified=False)
    )
    assert result.outcome == "recognised"
    assert result.seeker_id == seeker_id
    assert store.get_seeker(seeker_id)["email"] == "alice@example.com"  # unchanged


def test_a_new_identity_creates_a_seeker(store):
    result = link_or_create_seeker(store, _claim(subject="sub-new", email="new@example.com"))
    assert result.outcome == "created"

    created = store.get_seeker(result.seeker_id)
    assert created["email"] == "new@example.com"
    assert created["email_verified"] == 1  # the provider vouched for it
    assert created["password_hash"] is None
    assert created["display_name"] == "Alice"


def test_an_unverified_new_identity_creates_an_unverified_seeker(store):
    """No existing account to steal, so creation is allowed — but nothing is assumed proven."""
    result = link_or_create_seeker(
        store, _claim(subject="sub-new", email="new@example.com", email_verified=False)
    )
    assert result.outcome == "created"
    assert store.get_seeker(result.seeker_id)["email_verified"] == 0


def test_creation_can_be_refused(store):
    with pytest.raises(IdentityLinkRefused):
        link_or_create_seeker(store, _claim(subject="sub-new", email="new@example.com"),
                              create_if_missing=False)


def test_a_claim_with_no_email_and_no_known_identity_is_refused(store):
    """LinkedIn's OIDC response may omit the address entirely (plan §3)."""
    with pytest.raises(IdentityLinkRefused):
        link_or_create_seeker(store, _claim(subject="sub-anon", email=None, email_verified=False))


def test_two_providers_reach_one_seeker(store, seeker_id):
    """Both sign-in paths must land on the same Seeker record, never on two."""
    google = link_or_create_seeker(store, _claim(provider="google", subject="g-1"))
    linkedin = link_or_create_seeker(store, _claim(provider="linkedin", subject="l-1"))
    assert google.seeker_id == linkedin.seeker_id == seeker_id
    assert len(store.list_identities(seeker_id)) == 2


def test_the_same_sub_from_a_different_provider_is_a_different_identity(store, seeker_id):
    link_or_create_seeker(store, _claim(provider="google", subject="shared-sub"))
    assert store.get_identity("linkedin", "shared-sub") is None


# ── Employer provider identities ─────────────────────────────────────────────
#
# link_or_create_employer's cases 1 and 2 mirror link_or_create_seeker's exactly
# (same _claim() helper, same email used in the employer_id fixture below), so
# these tests pin the same two claims. Case 3 is where it genuinely differs:
# there is no "creates" outcome to test, only a refusal — see the function's
# docstring for why company_name makes that impossible rather than just unbuilt.


def _employer_claim(**overrides) -> IdentityClaim:
    base = dict(
        provider="google",
        subject="google-sub-1",
        email="hr@acme.example",
        email_verified=True,
        display_name="Jamie",
    )
    base.update(overrides)
    return IdentityClaim(**base)  # type: ignore[arg-type]


def test_employer_unverified_provider_email_does_not_auto_link(employer_store, employer_id):
    """Same takeover defence as the Seeker version — see that test's docstring."""
    with pytest.raises(IdentityLinkRefused):
        link_or_create_employer(employer_store, _employer_claim(email_verified=False))

    assert employer_store.get_identity("google", "google-sub-1") is None
    assert employer_store.get_employer(employer_id)["password_hash"] is not None


def test_employer_verified_provider_email_links_to_the_existing_employer(
    employer_store, employer_id,
):
    result = link_or_create_employer(employer_store, _employer_claim(email_verified=True))
    assert result.outcome == "linked"
    assert result.employer_id == employer_id
    assert employer_store.get_identity("google", "google-sub-1")["employer_id"] == employer_id


def test_employer_known_identity_is_recognised_without_consulting_the_email(
    employer_store, employer_id,
):
    link_or_create_employer(employer_store, _employer_claim(email_verified=True))

    result = link_or_create_employer(
        employer_store, _employer_claim(email="hr-new@acme.example", email_verified=False)
    )
    assert result.outcome == "recognised"
    assert result.employer_id == employer_id
    assert employer_store.get_employer(employer_id)["email"] == "hr@acme.example"  # unchanged


def test_employer_no_match_is_always_refused_never_created(employer_store):
    """
    The load-bearing difference from the Seeker version: there is no
    create_if_missing=True escape hatch, because there is no company_name to
    create the row with. This must raise, not return a LinkResult with a
    'created' outcome — that outcome does not exist on EmployerLinkResult at
    all (see its Literal type), so a caller mistakenly expecting one would
    fail statically before this test could even catch it at runtime.
    """
    with pytest.raises(IdentityLinkRefused):
        link_or_create_employer(
            employer_store, _employer_claim(subject="sub-new", email="new@acme.example")
        )


def test_employer_claim_with_no_email_and_no_known_identity_is_refused(employer_store):
    with pytest.raises(IdentityLinkRefused):
        link_or_create_employer(
            employer_store, _employer_claim(subject="sub-anon", email=None, email_verified=False)
        )


def test_employer_two_providers_reach_one_employer(employer_store, employer_id):
    link_or_create_employer(employer_store, _employer_claim(provider="google", subject="g-1"))
    google_again = link_or_create_employer(
        employer_store, _employer_claim(provider="google", subject="g-1")
    )
    assert google_again.outcome == "recognised"
    assert google_again.employer_id == employer_id
