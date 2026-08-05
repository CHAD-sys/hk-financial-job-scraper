# Auth is assembled from Python libraries inside the existing FastAPI service

**Status:** accepted (2026-07-30)

Authentication lives in the FastAPI backend we already deploy, built from focused
libraries — `argon2-cffi` for password hashing, `httpx-oauth`/`Authlib` for the Google
exchange, `itsdangerous` for signed single-use tokens — with the session layer,
endpoints and flows written by us. No new deployed service, no ORM, no vendor.

**Rejected alternatives, all of which were viable:**

- **A second, dedicated PocketBase as an auth server.** PocketBase has a genuinely
  complete auth system: 32 OAuth2 providers, three generic OIDC slots (which is how
  LinkedIn would be configured), password auth, OTP, MFA, verification, reset, and a
  user admin UI — self-hosted and free. It was the recommendation. Rejected to avoid
  operating a third Railway service, a second volume to back up, a shared HS256 secret
  between two services, and the confusion of running two unrelated PocketBase
  instances. *Note: reusing the existing PocketBase mirror was never an option —
  `sync_pocketbase.py` writes its SQLite file directly on disk and refuses to run while
  PocketBase is serving, so it cannot also be a live auth database.*
- **Clerk or Supabase Auth.** Free to 50,000 users and 3–5 days faster, with account
  linking and provider integrations already solved. Rejected because it places Seeker
  identities with a US vendor — a PDPO cross-border-transfer disclosure on a site whose
  privacy notice currently sells restraint — and because never holding the password
  hashes makes migrating off require a forced reset for every Seeker.
- **FastAPI-Users.** The batteries-included Python answer, but SQLAlchemy-based; this
  codebase deliberately uses stdlib `sqlite3` with hand-written SQL and phased
  migrations. Adding an ORM for one feature is the wrong trade.

**Consequence:** we own the security surface permanently. The mitigation is that
nothing cryptographic is hand-rolled — hashing, OAuth token exchange and token signing
are all delegated. What we write is glue.

**Implementation note (2026-08-05):** the specific libraries named above were the
plan, not what shipped. `requirements.txt` installs `argon2-cffi` (as decided) and
`httpx` (the repo's decided HTTP client, CLAUDE.md — not a new auth-specific
dependency) for auth; `httpx-oauth`, `Authlib` and `itsdangerous` were never added.
The Google exchange calls `https://oauth2.googleapis.com/token` and
`.../tokeninfo` directly with a plain `httpx.Client` rather than an OAuth client
library. Single-use tokens — email verification, password reset, sessions — are
hand-rolled from stdlib instead of `itsdangerous`: `secrets.token_urlsafe(32)`
generates them, `hashlib.sha256` is what gets stored (never the raw token),
`hmac.compare_digest` does the constant-time comparisons (`webapp/backend/auth.py`).
The decision this ADR records — delegate the *cryptography*, own the *glue* — held;
two of the three named packages did not ship. Recorded here rather than left
silent, because a reader trusting the list above would misjudge what is actually
installed.
