"""
Seeker authentication core — passwords, sessions, single-use email tokens,
provider-identity linking.

There is no web framework in this file. Nothing here knows about FastAPI,
cookies, requests or responses; every function takes a SeekerStore and plain
values. That is deliberate: the security-critical decisions (how long a session
lives, whether a token has already been spent, whether a Google identity may
attach to an existing account) are testable without spinning up an app, and the
route layer above is left with nothing but plumbing.

What is delegated and what is ours (ADR 0004): hashing is `argon2-cffi`, token
generation is `secrets`, digests are `hashlib`, constant-time comparison is
`hmac`. Nothing cryptographic is hand-rolled. What we wrote is the glue — and
the glue is where the interesting mistakes live, hence the density of comment
below.

Three rules run through the whole file:

  1. **A raw token is never stored.** Session tokens and email tokens are written
     as SHA-256 digests. The raw value exists exactly once — in the return value
     of the issue_* function, on its way into a cookie or an email — and is
     unrecoverable afterwards. A leaked seekers.db hands over no live session and
     no working reset link.

  2. **Sessions roll.** 90 days, pushed forward on use (decision 11). No "remember
     me": it asks the Seeker a question whose answer we already know.

  3. **Never auto-link an OAuth identity to an existing account unless the
     provider asserts the email is verified.** Absolute, per §4 of the plan. This
     is the rule that stops someone who can create a Google account on your
     address from taking over your Seeker account.

Deliberately NOT here, with the seams left clean:
  - **Sending email.** issue_email_token() returns the raw token; the caller
    puts it in a link and hands that to the mailer (phase 3). This module never
    imports mailer.
  - **The Google OAuth dance.** Exchanging a code for an id_token, validating
    `state`, checking the issuer and audience — all of that is phase 4 and
    belongs in the route layer. Its *output* is an IdentityClaim, which is where
    this module picks the story up.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from seekers_store import (
    EmailAlreadyRegistered,
    SeekerStore,
    from_iso,
    normalise_email,
    utcnow,
)

logger = logging.getLogger(__name__)

# ── Policy constants ──────────────────────────────────────────────────────────

#: Sessions live 90 days from last use (decision 11).
SESSION_TTL = timedelta(days=90)

#: How stale a session's expiry must get before a successful verification writes
#: a new one. Rolling expiry taken literally would mean a database write on
#: EVERY authenticated request — on a network-backed Railway volume, against the
#: backend's only writable database, for no benefit: a session refreshed 23 hours
#: ago is not meaningfully closer to expiring than one refreshed now. So we
#: refresh at most once a day and accept that the window is "90 days, ±1 day".
SESSION_REFRESH_INTERVAL = timedelta(days=1)

#: Verify and reset links are short-lived: they arrive by email, an inherently
#: forwardable and long-lived medium. One hour is the plan's ceiling.
EMAIL_TOKEN_TTL = timedelta(hours=1)

#: 32 bytes of `secrets` randomness, urlsafe-base64 → 43 characters. Far beyond
#: guessable, and the token is opaque: it carries no claims, so there is nothing
#: to forge. All authority lives in the row it points at.
_TOKEN_BYTES = 32

TokenPurpose = Literal["verify", "reset"]

# argon2-cffi's own defaults: Argon2**id**, m=64 MiB, t=3, p=4 — the RFC 9106
# recommended profile. Left at the library's defaults on purpose (ADR 0004: we
# delegate crypto rather than tune it). One consequence worth knowing before the
# container is sized: each concurrent hash allocates 64 MiB, so a burst of
# simultaneous logins is a memory event, not a CPU one. The parameters are
# encoded inside every stored hash, so raising them later needs no migration —
# needs_rehash() below detects old hashes at the next successful login.
_hasher = PasswordHasher()

# A real Argon2 hash of a value nobody will ever submit. Used to spend roughly
# the same time verifying a password for an account that does not exist (or that
# has no password because it is Google-only) as for one that does. Without it,
# login response time answers "does this address have an account?" — undoing the
# non-enumerable responses decision 15 buys at the HTTP layer.
#
# Computed on first use, not at import. At import it cost a full Argon2id hash —
# 64 MiB and ~100 ms — on every process start, and on every test that
# re-imported this module, which the old app-less test setup did per fixture.
_dummy_hash: str | None = None


def _dummy() -> str:
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = _hasher.hash("finex-careers-dummy-password-for-constant-time-login")
    return _dummy_hash


class AuthError(Exception):
    """Base class for refusals this module raises."""


class IdentityLinkRefused(AuthError):
    """
    Raised when a provider identity may not be attached to an existing Seeker.

    The one case that matters: the provider gave us an address that already has
    an account, but did NOT assert that it verified the address. Silently
    linking would mean anyone able to create a provider account on someone
    else's address inherits their Seeker account.
    """


# ── Passwords ─────────────────────────────────────────────────────────────────


def hash_password(password: str) -> str:
    """
    Hash a plaintext password with Argon2id.

    The returned string is self-describing — it contains the algorithm, version,
    parameters and salt as well as the digest — which is why no separate salt or
    params column exists in the schema.
    """
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """
    Check a password against a stored hash. Never raises; returns a bool.

    `password_hash` is None for a Seeker who signed up with Google and has never
    set a password. That case still performs a dummy verification before
    returning False, so it costs the same wall-clock time as a real wrong
    password — see _dummy().

    Callers should pass None (rather than skipping the call) when the address has
    no account at all, for the same timing reason.
    """
    if password_hash is None:
        _safe_verify(_dummy(), password)  # burn the same time, then refuse
        return False
    return _safe_verify(password_hash, password)


def _safe_verify(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False
    except (VerificationError, InvalidHashError):
        # A corrupted or foreign-format hash. Treated as a failed login rather
        # than a 500: an unreadable hash must never authenticate anyone, and
        # crashing the endpoint would tell an attacker they had found one.
        logger.warning("Unverifiable password hash encountered; treating as a failed login")
        return False


def password_needs_rehash(password_hash: str) -> bool:
    """
    True when a stored hash was produced with weaker parameters than current.

    Call this after a SUCCESSFUL login — it is the only moment the plaintext is
    available to re-hash with — and store the new hash if it returns True. That
    is how the whole Seeker base migrates to stronger parameters without a
    forced reset.
    """
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


# ── Token plumbing ────────────────────────────────────────────────────────────


def generate_token() -> str:
    """A fresh opaque token. The only place raw token material is created."""
    return secrets.token_urlsafe(_TOKEN_BYTES)


def hash_token(raw_token: str) -> str:
    """
    SHA-256 hex digest of a token — the form that is stored.

    Plain SHA-256 rather than Argon2, deliberately. A password is low-entropy and
    guessable, so its hash must be slow. A token is 256 bits of `secrets`
    randomness: there is no dictionary to run against it, and making the digest
    slow would only make every authenticated request slow. This is the standard
    treatment for high-entropy bearer tokens.
    """
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _matches(stored_hash: str, candidate_hash: str) -> bool:
    """
    Constant-time comparison of two digests.

    Strictly speaking the row was already found by an equality match on the
    primary key, so this second comparison cannot fail. It is kept because it
    costs nothing, documents that token comparison is never a plain `==`, and
    keeps the code correct if a future lookup ever stops being a primary-key hit.
    """
    return hmac.compare_digest(stored_hash, candidate_hash)


# ── Sessions ──────────────────────────────────────────────────────────────────


def issue_session(
    store: SeekerStore,
    seeker_id: str,
    *,
    user_agent: str | None = None,
    now: datetime | None = None,
) -> str:
    """
    Create a session and return the RAW token — the only time it exists.

    The caller puts it in an httpOnly, Secure, SameSite=Lax cookie (which works
    because the frontend and API share one origin, decision 6) and then forgets
    it. Do not log it, do not return it in a JSON body, do not store it.
    """
    moment = now or utcnow()
    raw_token = generate_token()
    store.insert_session(
        hash_token(raw_token),
        seeker_id,
        expires_at=moment + SESSION_TTL,
        user_agent=user_agent,
        now=moment,
    )
    return raw_token


def verify_session(
    store: SeekerStore, raw_token: str | None, *, now: datetime | None = None
) -> str | None:
    """
    Resolve a session token to a seeker_id, or None if it is not a live session.

    None covers every failure identically — unknown token, expired token, token
    belonging to a deleted Seeker. The caller cannot tell them apart and should
    not try to; they all mean "not signed in".

    On success the session's expiry rolls forward (at most once per
    SESSION_REFRESH_INTERVAL, see the constant). Expiry is enforced HERE, on
    read, not by a cleanup job: purge_expired_sessions() only reclaims space, so
    a cleanup task that never ran could not leave a stale session usable.
    """
    if not raw_token:
        return None

    moment = now or utcnow()
    candidate_hash = hash_token(raw_token)
    session = store.get_session(candidate_hash)
    if session is None:
        return None
    if not _matches(session["token_hash"], candidate_hash):
        return None

    if from_iso(session["expires_at"]) <= moment:
        # Expired. Drop the row on the way past — it can never be valid again,
        # and removing it here means an abandoned session cleans itself up on the
        # one request that would have used it.
        store.delete_session(candidate_hash)
        return None

    fresh_expiry = moment + SESSION_TTL
    if fresh_expiry - from_iso(session["expires_at"]) >= SESSION_REFRESH_INTERVAL:
        store.extend_session(candidate_hash, fresh_expiry)

    return str(session["seeker_id"])


def revoke_session(store: SeekerStore, raw_token: str | None) -> bool:
    """Sign out one session (logout). Returns whether there was one to revoke."""
    if not raw_token:
        return False
    return store.delete_session(hash_token(raw_token))


def revoke_all_sessions(store: SeekerStore, seeker_id: str) -> int:
    """
    Sign out everywhere. Returns how many sessions were revoked.

    Call this on password reset and password change: a reset exists because
    someone may have lost control of the account, so leaving the attacker's
    session alive defeats the point of the reset.
    """
    return store.delete_sessions_for_seeker(seeker_id)


# ── Single-use email tokens (verify / reset) ──────────────────────────────────


def issue_email_token(
    store: SeekerStore,
    seeker_id: str,
    purpose: TokenPurpose,
    *,
    now: datetime | None = None,
    invalidate_previous: bool = True,
) -> str:
    """
    Mint a single-use token for a verification or password-reset link, and return
    the RAW value for the caller to embed in a URL.

    By default any outstanding token of the same purpose is deleted first, so
    requesting a new reset link immediately kills the old one. That is the
    behaviour a Seeker expects ("I clicked it twice, the first mail is dead") and
    it shrinks the window in which an intercepted older email is useful.

    Sending is not this module's job. The caller builds the link and hands it to
    the mailer (phase 3); nothing here imports it.
    """
    if purpose not in ("verify", "reset"):
        raise ValueError(f"unknown token purpose {purpose!r}")

    moment = now or utcnow()
    if invalidate_previous:
        store.delete_email_tokens(seeker_id, purpose)

    raw_token = generate_token()
    store.insert_email_token(
        hash_token(raw_token),
        seeker_id,
        purpose,
        expires_at=moment + EMAIL_TOKEN_TTL,
        now=moment,
    )
    return raw_token


def consume_email_token(
    store: SeekerStore, raw_token: str | None, purpose: TokenPurpose, *, now: datetime | None = None
) -> str | None:
    """
    Spend a token and return the seeker_id it belonged to, or None.

    None means: no such token, wrong purpose, already used, or expired. All four
    are the same answer to the Seeker — "this link is no longer valid" — and the
    caller must not distinguish them in its response.

    The `purpose` check is not ceremony. Without it a verification token (which a
    Seeker receives by simply signing up) would be redeemable as a password-reset
    token, and one email would become a password change.

    Single-use is enforced by the store's conditional UPDATE, so two simultaneous
    clicks on the same link cannot both succeed.
    """
    if not raw_token:
        return None

    moment = now or utcnow()
    candidate_hash = hash_token(raw_token)
    token = store.get_email_token(candidate_hash)
    if token is None:
        return None
    if not _matches(token["token_hash"], candidate_hash):
        return None
    if token["purpose"] != purpose:
        return None
    if token["used_at"] is not None:
        return None
    if from_iso(token["expires_at"]) <= moment:
        return None

    # Everything above is a pre-flight check; THIS is the step that decides,
    # because it is the only one that is atomic.
    if not store.claim_email_token(candidate_hash, now=moment):
        return None

    return str(token["seeker_id"])


# ── Provider identities (Google now, LinkedIn later) ──────────────────────────


@dataclass(frozen=True)
class IdentityClaim:
    """
    What an identity provider told us about a person, after the OAuth/OIDC
    exchange has been completed and validated by the route layer.

    `subject` is the provider's immutable id for the account (OIDC `sub`) and is
    the only field safe to use as a key: email addresses get reassigned by domain
    owners, `sub` does not.

    `email_verified` is the load-bearing field. Google sets it truthfully.
    LinkedIn's OIDC response includes `email`/`email_verified` only optionally
    (see §3 of the plan), and LinkedIn states it does not verify user identities
    — so when the claim is absent it must arrive here as False, never as an
    assumed True.
    """

    provider: str
    subject: str
    email: str | None = None
    email_verified: bool = False
    display_name: str | None = None


@dataclass(frozen=True)
class LinkResult:
    """Which of the three things happened, so the caller can log the right event."""

    seeker_id: str
    #: 'recognised' — the identity was already linked; nothing changed.
    #: 'linked'     — attached to an existing Seeker found by verified email.
    #: 'created'    — a brand-new Seeker was created for this identity.
    outcome: Literal["recognised", "linked", "created"]


def link_or_create_seeker(
    store: SeekerStore,
    claim: IdentityClaim,
    *,
    now: datetime | None = None,
    create_if_missing: bool = True,
) -> LinkResult:
    """
    Turn a provider identity into a Seeker, enforcing the absolute linking rule.

    The order of the three cases is the whole security argument:

      1. **The identity is already linked.** Return that Seeker. `sub` is the key,
         so this keeps working if the person changed their Google address — and
         it deliberately does NOT consult the email at all.

      2. **An account already exists on the claimed email.** Attach the identity
         to it ONLY if the provider asserted `email_verified`. Otherwise refuse
         with IdentityLinkRefused. This is the takeover case: a provider that
         will hand out an account on `victim@example.com` without checking is,
         if we auto-link, handing out that Seeker's account.

      3. **Nobody holds that email.** Create a Seeker. `email_verified` is copied
         from the claim, so an unverified provider email produces an unverified
         Seeker who must still verify before we will mail them (decision 10).

    A claim with no email at all is only usable in case 1 or 3 — there is nothing
    to match on — and case 3 needs an address for the UNIQUE column, so a claim
    with neither an existing identity nor an email is refused.

    Note the deliberate gap this leaves open, so it is not mistaken for an
    oversight: case 3 lets an unverified provider email occupy an address that
    its real owner has not yet registered. That is *squatting*, not takeover —
    the squatter gains nothing the owner had — and closing it costs a
    verification round-trip in the middle of a "Sign in with Google" click. If
    v1's only provider is Google, whose assertions are trustworthy, the case is
    unreachable in practice; revisit it when the generic OIDC slot opens for
    LinkedIn.
    """
    moment = now or utcnow()

    existing_identity = store.get_identity(claim.provider, claim.subject)
    if existing_identity is not None:
        return LinkResult(seeker_id=str(existing_identity["seeker_id"]), outcome="recognised")

    email = normalise_email(claim.email) if claim.email else None
    if email:
        existing_seeker = store.get_seeker_by_email(email)
        if existing_seeker is not None:
            if not claim.email_verified:
                logger.warning(
                    "Refused to auto-link %s identity to existing Seeker: provider did not "
                    "assert email_verified",
                    claim.provider,
                )
                raise IdentityLinkRefused(
                    f"{claim.provider} did not assert that the email address is verified; "
                    "refusing to link it to an existing account"
                )
            store.link_identity(
                str(existing_seeker["id"]), claim.provider, claim.subject, now=moment
            )
            return LinkResult(seeker_id=str(existing_seeker["id"]), outcome="linked")

    if not create_if_missing:
        raise IdentityLinkRefused("no Seeker matches this identity and creation was not permitted")
    if not email:
        raise IdentityLinkRefused(
            f"{claim.provider} returned no email address and this identity is unknown; "
            "cannot create a Seeker without one"
        )

    try:
        seeker_id = store.create_seeker(
            email,
            password_hash=None,  # Google-only Seeker: no password exists, as opposed to a blank one
            display_name=claim.display_name,
            email_verified=claim.email_verified,
            now=moment,
        )
    except EmailAlreadyRegistered:
        # Lost a race against a concurrent registration on the same address
        # between the SELECT above and this INSERT. Refuse rather than retry into
        # the link branch: the safe answer to "who owns this address?" under a
        # race is "ask again", never "assume it is you".
        raise IdentityLinkRefused(
            "that address was registered concurrently; retry sign-in"
        ) from None

    store.link_identity(seeker_id, claim.provider, claim.subject, now=moment)
    return LinkResult(seeker_id=seeker_id, outcome="created")
