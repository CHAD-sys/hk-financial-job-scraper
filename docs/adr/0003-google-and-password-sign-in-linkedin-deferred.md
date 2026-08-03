# Google and email/password sign-in; LinkedIn deferred

**Status:** accepted (2026-07-30)

A Seeker signs in with Google or with an email address and password. LinkedIn is a
deliberate fast-follow rather than a v1 provider, added against the same Seeker
record once a LinkedIn Developer app and verified Company Page exist.

**Why LinkedIn was wanted, and why it waited.** A LinkedIn button on a finance
careers board is a real trust signal. But "Sign In with LinkedIn using OpenID
Connect" returns only `sub`, `name`, `given_name`, `family_name`, `picture`,
`locale` and — *optionally* — `email` / `email_verified`. There is no work history,
no positions, no skills, and no headline; those need partner-only APIs. LinkedIn also
states the product "does not verify user identities and should not be marketed as
such." So its value here is brand, not data, and it is strictly weaker than Google as
an identity source because the email may be absent entirely. Not worth blocking v1 on
LinkedIn's review queue.

**Why not magic-link-only**, which was recommended and rejected: it would have deleted
password hashing, the reset flow, the account-existence oracle and the whole
credential-storage liability, and email verification would have been structural rather
than a separate flow. The owner chose conventional sign-in for familiarity and for not
making email delivery the login critical path.

**Consequences accepted:** we store credentials, so we own password hashing, a reset
flow, enumeration defences on both register and forgot-password, and rate limiting per
email *and* per IP. Multiple providers on one email introduce account linking, whose
rule is absolute: **never auto-link an OAuth identity to an existing account unless the
provider asserts the email is verified.**
