from __future__ import annotations

from collections.abc import Mapping

import identity_protocol as protocol
import pytest


class FakeTransport:
    def __init__(self, *, token: dict | None = None, identity: dict | None = None) -> None:
        self.token = token or {}
        self.identity = identity or {}
        self.calls: list[tuple] = []

    def post_form(self, url: str, data: Mapping[str, str]) -> dict:
        self.calls.append(("post", url, dict(data)))
        return self.token

    def get_json(
        self,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict:
        self.calls.append(("get", url, dict(params or {}), dict(headers or {})))
        return self.identity


def credentials(provider: protocol.Provider) -> protocol.ClientCredentials:
    return protocol.ClientCredentials(f"{provider}-client", f"{provider}-secret")


def callback(**changes) -> protocol.Callback:
    values = {"code": "code", "state": "state", "cookie_state": "state", "error": None}
    values.update(changes)
    return protocol.Callback(**values)


def test_begin_builds_provider_authorization_requests_without_exposing_secret():
    identity = protocol.IdentityProtocol(FakeTransport(), credentials)

    google = identity.begin("google", "https://finex.test/api/auth/google/callback")
    linkedin = identity.begin("linkedin", "https://finex.test/api/auth/linkedin/callback")

    assert google.url.startswith(protocol.GOOGLE_AUTH_URL)
    assert "scope=openid+email+profile" in google.url
    assert "prompt=select_account" in google.url
    assert linkedin.url.startswith(protocol.LINKEDIN_AUTH_URL)
    assert "scope=openid+profile+email" in linkedin.url
    assert "secret" not in google.url + linkedin.url
    assert google.state and linkedin.state and google.state != linkedin.state


@pytest.mark.parametrize(
    "bad_callback",
    [
        callback(code=None),
        callback(state=None),
        callback(cookie_state=None),
        callback(state="attacker"),
        callback(error="access_denied"),
    ],
)
def test_complete_rejects_bad_callbacks_before_contacting_provider(bad_callback):
    transport = FakeTransport()
    identity = protocol.IdentityProtocol(transport, credentials)

    with pytest.raises(protocol.IdentityProtocolError):
        identity.complete("google", "https://finex.test/callback", bad_callback)

    assert transport.calls == []


def test_unconfigured_provider_is_unavailable_at_start_and_callback():
    identity = protocol.IdentityProtocol(FakeTransport(), lambda _provider: None)

    with pytest.raises(protocol.ProviderUnavailable):
        identity.begin("google", "https://finex.test/callback")
    with pytest.raises(protocol.ProviderUnavailable):
        identity.complete("linkedin", "https://finex.test/callback", callback())


def test_google_exchange_checks_audience_and_returns_verified_claim():
    transport = FakeTransport(
        token={"id_token": "signed-token"},
        identity={
            "aud": "google-client",
            "sub": "google-123",
            "email": "seeker@example.com",
            "email_verified": "true",
            "name": "FinEx Seeker",
        },
    )
    identity = protocol.IdentityProtocol(transport, credentials)

    claim = identity.complete("google", "https://finex.test/callback", callback())

    assert claim.provider == "google"
    assert claim.subject == "google-123"
    assert claim.email == "seeker@example.com"
    assert claim.email_verified is True
    assert transport.calls[0][2]["client_secret"] == "google-secret"
    assert transport.calls[1][2] == {"id_token": "signed-token"}


def test_google_rejects_token_for_another_client():
    identity = protocol.IdentityProtocol(
        FakeTransport(token={"id_token": "token"}, identity={"aud": "other", "sub": "123"}),
        credentials,
    )

    with pytest.raises(protocol.IdentityProtocolError, match="audience mismatch"):
        identity.complete("google", "https://finex.test/callback", callback())


@pytest.mark.parametrize(
    ("token", "identity", "message"),
    [
        ({}, {}, "no id_token"),
        ({"id_token": "token"}, {"aud": "google-client"}, "no subject"),
    ],
)
def test_google_requires_exchange_evidence(token, identity, message):
    service = protocol.IdentityProtocol(
        FakeTransport(token=token, identity=identity), credentials
    )

    with pytest.raises(protocol.IdentityProtocolError, match=message):
        service.complete("google", "https://finex.test/callback", callback())


@pytest.mark.parametrize(
    ("provider_value", "expected"),
    [
        (True, True),
        ("true", True),
        ("TRUE", True),
        (False, False),
        ("false", False),
        (1, False),
        (None, False),
    ],
)
def test_linkedin_accepts_only_explicit_verified_email(provider_value, expected):
    transport = FakeTransport(
        token={"access_token": "access"},
        identity={
            "sub": "linkedin-123",
            "email": "seeker@example.com",
            "email_verified": provider_value,
        },
    )
    identity = protocol.IdentityProtocol(transport, credentials)

    claim = identity.complete("linkedin", "https://finex.test/callback", callback())

    assert claim.email_verified is expected
    assert transport.calls[1][3] == {"Authorization": "Bearer access"}


def test_claim_can_omit_email_without_inventing_identity_evidence():
    identity = protocol.IdentityProtocol(
        FakeTransport(
            token={"access_token": "access"},
            identity={"sub": "linkedin-123", "name": "No Email"},
        ),
        credentials,
    )

    claim = identity.complete("linkedin", "https://finex.test/callback", callback())

    assert claim.email is None
    assert claim.email_verified is False


def test_linkedin_requires_access_token_and_subject():
    without_token = protocol.IdentityProtocol(FakeTransport(), credentials)
    with pytest.raises(protocol.IdentityProtocolError, match="no access_token"):
        without_token.complete("linkedin", "https://finex.test/callback", callback())

    without_subject = protocol.IdentityProtocol(
        FakeTransport(token={"access_token": "access"}, identity={}), credentials
    )
    with pytest.raises(protocol.IdentityProtocolError, match="no subject"):
        without_subject.complete("linkedin", "https://finex.test/callback", callback())
