# One Identity Protocol owns provider exchange

**Status:** accepted (2026-08-11)

`webapp/backend/identity_protocol.py` owns the complete external identity
protocol for Google and LinkedIn. Its two outcome-oriented operations begin an
authorization round trip and complete one into a Verified Identity Claim. The
module hides provider URLs and scopes, nonce generation and constant-time state
validation, dynamic credential lookup, token exchange, provider claim lookup,
Google audience validation, required-subject checks and strict interpretation
of email-verification evidence.

## Account policy stays separate

The protocol ends when it produces `auth.IdentityClaim`. It does not create,
link or recognise an account, issue a session, set a cookie or choose a browser
redirect. `auth.link_or_create_seeker` and `auth.link_or_create_employer` remain
separate policies. In particular, Google may create a new Seeker while it may
only recognise or link an Employer that already exists. This preserves ADR
0001's separate aggregates instead of hiding them behind a generic “user” flow.

## The external seam

Provider HTTP is a true-external dependency behind the narrow
`OAuthTransport` adapter. Production uses `HttpxOAuthTransport`; tests supply a
deterministic in-memory transport and exercise successful exchange, malformed
evidence and failure paths without Google or LinkedIn credentials. Credential
lookup remains dynamic so rotated environment values apply without rebuilding
the FastAPI app and existing hermetic endpoint tests can vary configuration.

Cryptographic work is still delegated as ADR 0004 requires: providers verify
their tokens, Python's `secrets` creates the nonce, and `hmac.compare_digest`
checks it. The module owns the security-sensitive glue and makes it one test
surface rather than repeating it in each route.

## Consequences

- A provider validation fix applies to Seeker Google, Seeker LinkedIn and
  Employer Google together.
- A non-empty string such as LinkedIn's `"false"` is no longer accidentally
  treated as verified email evidence.
- FastAPI routes own only browser transport and the relevant account policy.
- Adding another account flow for an existing provider reuses the same protocol
  without merging account aggregates.
- Removing this module would spread state, exchange and claim-validation rules
  back across every provider callback, so the module earns depth.
