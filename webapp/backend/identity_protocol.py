"""Verified external identity claims from Google and LinkedIn.

This module owns the OAuth/OIDC protocol boundary: authorization requests,
CSRF state validation, code exchange, provider claim retrieval, and the checks
required before provider data becomes an :class:`auth.IdentityClaim`.

It deliberately does *not* decide what a claim may do. Seeker creation/linking
and Employer recognition/linking remain separate policies in ``auth.py``.
HTTP redirects, cookies, and sessions remain web concerns in ``main.py``.
"""

from __future__ import annotations

import hmac
import os
import secrets
from dataclasses import dataclass
from typing import Callable, Literal, Mapping, Protocol
from urllib.parse import urlencode

import auth
import httpx

Provider = Literal["google", "linkedin"]


@dataclass(frozen=True)
class ClientCredentials:
    client_id: str
    client_secret: str


@dataclass(frozen=True)
class AuthorizationRequest:
    url: str
    state: str


@dataclass(frozen=True)
class Callback:
    code: str | None
    state: str | None
    cookie_state: str | None
    error: str | None = None


class IdentityProtocolError(Exception):
    """A callback could not safely produce a verified identity claim."""


class ProviderUnavailable(IdentityProtocolError):
    """The selected provider has no complete client configuration."""


class TransportFailure(IdentityProtocolError):
    """The external provider exchange failed or returned an invalid payload."""


class OAuthTransport(Protocol):
    """The true-external HTTP seam used by the identity protocol."""

    def post_form(self, url: str, data: Mapping[str, str]) -> dict: ...

    def get_json(
        self,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict: ...


class HttpxOAuthTransport:
    """Production adapter for provider HTTP calls."""

    def __init__(self, timeout_seconds: float = 10) -> None:
        self._timeout_seconds = timeout_seconds

    def post_form(self, url: str, data: Mapping[str, str]) -> dict:
        try:
            with httpx.Client(timeout=self._timeout_seconds) as client:
                response = client.post(url, data=dict(data))
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise TransportFailure("provider token exchange failed") from exc
        if not isinstance(payload, dict):
            raise TransportFailure("provider token response was not an object")
        return payload

    def get_json(
        self,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict:
        try:
            with httpx.Client(timeout=self._timeout_seconds) as client:
                response = client.get(
                    url,
                    params=dict(params) if params else None,
                    headers=dict(headers) if headers else None,
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise TransportFailure("provider identity lookup failed") from exc
        if not isinstance(payload, dict):
            raise TransportFailure("provider identity response was not an object")
        return payload


GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"
LINKEDIN_AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
LINKEDIN_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
LINKEDIN_USERINFO_URL = "https://api.linkedin.com/v2/userinfo"


def credentials_from_env(provider: Provider) -> ClientCredentials | None:
    prefix = provider.upper()
    client_id = os.environ.get(f"{prefix}_CLIENT_ID", "").strip()
    client_secret = os.environ.get(f"{prefix}_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        return None
    return ClientCredentials(client_id, client_secret)


class IdentityProtocol:
    """Turn one provider round trip into one checked identity claim."""

    def __init__(
        self,
        transport: OAuthTransport | None = None,
        credential_source: Callable[[Provider], ClientCredentials | None] = credentials_from_env,
    ) -> None:
        self._transport = transport or HttpxOAuthTransport()
        self._credentials = credential_source

    def begin(self, provider: Provider, redirect_uri: str) -> AuthorizationRequest:
        credentials = self._require_credentials(provider)
        state = secrets.token_urlsafe(24)
        params = {
            "client_id": credentials.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile" if provider == "google" else "openid profile email",
            "state": state,
        }
        if provider == "google":
            params["prompt"] = "select_account"
        auth_url = GOOGLE_AUTH_URL if provider == "google" else LINKEDIN_AUTH_URL
        return AuthorizationRequest(f"{auth_url}?{urlencode(params)}", state)

    def complete(
        self,
        provider: Provider,
        redirect_uri: str,
        callback: Callback,
    ) -> auth.IdentityClaim:
        if callback.error:
            raise IdentityProtocolError(f"provider returned error={callback.error}")
        if (
            not callback.code
            or not callback.state
            or not callback.cookie_state
            or not hmac.compare_digest(callback.state, callback.cookie_state)
        ):
            raise IdentityProtocolError("missing or mismatched state (possible CSRF)")

        credentials = self._require_credentials(provider)
        if provider == "google":
            return self._complete_google(credentials, redirect_uri, callback.code)
        return self._complete_linkedin(credentials, redirect_uri, callback.code)

    def _require_credentials(self, provider: Provider) -> ClientCredentials:
        credentials = self._credentials(provider)
        if credentials is None:
            raise ProviderUnavailable(f"{provider} client is not configured")
        return credentials

    def _complete_google(
        self, credentials: ClientCredentials, redirect_uri: str, code: str
    ) -> auth.IdentityClaim:
        token = self._transport.post_form(
            GOOGLE_TOKEN_URL,
            {
                "code": code,
                "client_id": credentials.client_id,
                "client_secret": credentials.client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        id_token = _required_string(token, "id_token", "token response carried no id_token")
        info = self._transport.get_json(GOOGLE_TOKENINFO_URL, params={"id_token": id_token})
        if info.get("aud") != credentials.client_id:
            raise IdentityProtocolError("id_token audience mismatch")
        return _claim("google", info, "id_token carried no subject")

    def _complete_linkedin(
        self, credentials: ClientCredentials, redirect_uri: str, code: str
    ) -> auth.IdentityClaim:
        token = self._transport.post_form(
            LINKEDIN_TOKEN_URL,
            {
                "code": code,
                "client_id": credentials.client_id,
                "client_secret": credentials.client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        access_token = _required_string(
            token, "access_token", "token response carried no access_token"
        )
        info = self._transport.get_json(
            LINKEDIN_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        return _claim("linkedin", info, "userinfo carried no subject")


def _required_string(payload: Mapping[str, object], key: str, message: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise IdentityProtocolError(message)
    return value


def _verified(value: object) -> bool:
    """Accept only explicit true, never a merely truthy provider value."""
    return value is True or (isinstance(value, str) and value.lower() == "true")


def _claim(
    provider: Provider, info: Mapping[str, object], missing_subject: str
) -> auth.IdentityClaim:
    subject = _required_string(info, "sub", missing_subject)
    email = info.get("email")
    display_name = info.get("name")
    return auth.IdentityClaim(
        provider=provider,
        subject=subject,
        email=email if isinstance(email, str) else None,
        email_verified=_verified(info.get("email_verified")),
        display_name=display_name if isinstance(display_name, str) else None,
    )
