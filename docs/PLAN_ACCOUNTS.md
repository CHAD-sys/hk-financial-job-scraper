# PLAN — Seeker accounts (v1)

**Status:** built, not yet shipped — `ACCOUNTS_LIVE = false`
**Date:** 2026-07-30 (plan) · 2026-08-04 (status)

Everything in §8's build order exists: `webapp/backend/auth.py`,
`webapp/backend/seekers_store.py`, and the Sign in / Register / Forgot password /
Account pages. What remains is the *ship* step — decision 17's
`ACCOUNTS_LIVE` flag in `PrivacyNotice.tsx` is still `false`, so the privacy
copy does not yet describe accounts. Flip it when the feature goes public.
**Supersedes:** the 27 July accounts plan, deleted in full. No decision from it carries
over; every decision below was re-derived from scratch.

---

## 1. What we are building, and what it is for

A **Seeker** account: sign in with Google or email + password, keep Saved Roles on the
server instead of in the browser, delete your account when you want to.

That is a deliberately small feature, and the reason matters. **v1 is not built because
Seekers are asking for it.** At the time, nothing on the board was gated (ADR 0002,
later superseded by ADR 0018's public Research Scope) and there are no
alerts, so the account's entire benefit is that Saved Roles survive the browser and stop
going stale. Expect very few signups.

**v1 exists as the identity foundation for future paid personalisation** — CV matching
and personalised roles, built by another team member — which cannot exist without a
Seeker to attach a CV to. Two implications run through everything below:

- Keep the surface minimal. Do not build conversion pressure for features that do not
  exist yet.
- Get identity right the first time. Migrating a *paying* user base later is far more
  expensive than migrating a free one.

---

## 2. Decision log

Every line was a deliberate choice. Do not silently reverse one.

| # | Decision | Where |
|---|----------|-------|
| 1 | Seekers only. Employers are a separate aggregate later, **not a `role` column** | ADR 0001 |
| 2 | Carrot = durable Saved Roles. Alerts, application tracking, CV matching all deferred | ADR 0001 |
| 3 | **Public without an account.** Superseded: research remains anonymous, while catalogue enumeration is closed | ADR 0018 |
| 4 | Google + email/password. LinkedIn is a fast-follow, not v1 — **shipped 2026-08-07**, once a Company Page + Developer app existed | ADR 0003 |
| 5 | Auth assembled from Python libraries inside the existing FastAPI service | ADR 0004 |
| 6 | **FastAPI serves the React bundle** — one origin, one service | ADR 0005 |
| 7 | Seeker data in its own `/data/seekers.db`, `ATTACH`-joined to `jobs.db` | ADR 0006 |
| 8 | Railway scheduled volume backups, enabled before launch | ADR 0006 |
| 9 | ~~Resend, sending from `mail.finexclub.org`~~ → **send as `amine@finexclub.org` over the existing SMTP host; no Resend, no new subdomain** | ~~ADR 0008~~ **ADR 0009** |
| 10 | Unverified Seekers get full access; verification gates *sending*, not the account | §4 |
| 11 | Sessions: opaque tokens, SHA-256 hashed at rest, **90 days rolling**, no "remember me" | §4 |
| 12 | An alert would be a *saved search* reusing the existing filter params — when built | §6 |
| 13 | CV component contract deferred. Only commitment: **`seeker_id` is a stable opaque UUID** | ADR 0006 |
| 14 | First sign-in **union-merges** `localStorage` saves, then clears the local key | §4 |
| 15 | Abuse: rate limit per email **and** per IP, honeypot on signup, non-enumerable responses. No CAPTCHA | §5 |
| 16 | Self-serve account deletion that **really deletes**. Access requests handled manually | ADR 0007 |
| 17 | `ACCOUNTS_LIVE = false` **now**; account clauses rewritten at ship | §7 |
| 18 | No admin UI. `sqlite3` over `railway ssh` | §5 |
| 19 | First-party server-side event counts. No third-party analytics | §5 |
| 20 | **Single-origin change ships alone, first**, before any auth code | §8 |

---

## 3. Facts established — do not re-derive

- **`up.railway.app` is on the Public Suffix List** (line 15360). `finex-careers.up.railway.app`
  and `backend-production-08b4e.up.railway.app` are therefore **different sites**. No cookie
  can be scoped across them, `SameSite=Lax` is never sent cross-site, and `SameSite=None`
  is blocked by Safari's ITP and partitioned by Firefox. This is why decision 6 exists.
- **`get_db()` sets `PRAGMA query_only=ON`** (`main.py:90`) — the API cannot write to `jobs.db`.
- **`mailer.send_mail()` cannot email a Seeker.** It uses a fixed
  `SUBMISSION_RECIPIENT` for recruiter Role submissions, by design.
- **`_rate_limited(key)` already exists** (`main.py:881`): in-memory sliding window, 3/hour,
  `SUBMIT_RATE_LIMIT`. Its own comment notes it resets on deploy and does not survive replicas.
- **The Role-submission honeypot** is already implemented on `/api/post-role`.
- **`useSavedJobs.ts` stores whole `Job` objects** under `finex_saved_jobs:v1` — so a Saved Role
  today is a frozen snapshot and a soft-deleted role still shows as live. Server-side saves
  storing only `(source, source_id)` and joining at read time fix this for free.
- **`webapp/frontend/.env.local` already supports one origin**: `VITE_API_URL=` makes the
  frontend call relative `/api`.
- **A Role has no URL.** `selectedJob` is React state (`JobBoardPage.tsx:62`); the query string
  carries filters/sort/page only. No `JobPosting` structured data, no `robots.txt`, no sitemap.
- **`backup.py` covers `data/jobs.db` locally only**, and defaults to `retention_days=0` —
  every snapshot kept forever. The README's "30-day rolling" is stale.
- **`AboutPage.tsx:290`** — "free to browse and needs no account, no paywall on any listing"
  **stays true** under decision 3 and needs no change.
- **LinkedIn OIDC returns only** `sub`, `name`, `given_name`, `family_name`, `picture`,
  `locale`, and *optionally* `email` / `email_verified`. No work history, no skills, no
  headline. LinkedIn states it "does not verify user identities."

---

## 4. Behaviour

**Sign-up / sign-in.** Google or email + password. A session is issued immediately;
Saved Roles work from the first click. Google sign-ins arrive verified.

**Verification** exists to confirm the address so password reset works, and to stop the
platform becoming a mail cannon aimed at an address its owner never entered. It gates
*outbound mail*, not access. With alerts deferred, nothing else depends on it yet.

**Sessions.** Opaque random tokens, stored as SHA-256 hashes so a leaked `seekers.db`
does not hand over live sessions. 90-day rolling expiry refreshed on use. No
"remember me" checkbox — it pushes a decision onto the Seeker when the answer is known.
`httpOnly`, `Secure`, `SameSite=Lax`, which works because of decision 6.

**Account linking rule, absolute:** never auto-link an OAuth identity to an existing
account unless the provider asserts the email is verified. Otherwise anyone who can
create a provider account on your email address takes over your account.

**Saved Roles.** Server stores `(seeker_id, source, source_id)` only. Job fields are
joined from `jobs.db` at read time. On first sign-in, `localStorage` saves are
union-merged into the account and the local key is cleared: signed out means browser,
signed in means account, first sign-in moves them up. A Role that has been Closed a
fortnight stops being listed — still saved, still reachable by reference, just no
longer in the way (ADR 0011). Signed-out saves are unaffected, because a frozen copy
in `localStorage` cannot learn that a Role closed; not going stale is what the account
is for.

**Deletion.** Real deletion, sessions revoked, event logged. See ADR 0007.

---

## 5. Defences and visibility

| Concern | Measure |
|---|---|
| Inbox bombing a third party via `/register` | Rate limit **per target email**, not only per IP — the target is the constant, the IP is not |
| Brute force / credential stuffing | Rate limit per email and per IP on login |
| Bot signups | Honeypot field, mirroring the two existing endpoints |
| Account enumeration | Register on an existing address behaves like success and mails "someone tried to register"; forgot-password always returns 200 |
| Password storage | Argon2id via `argon2-cffi`. **Resolve the version at install time — a guessed pin broke a build once** |
| Visibility | First-party server-side events: signup started/completed, verification clicked, login, save, delete. No cookies, no JS, no vendor — so `PrivacyNotice.tsx:99`'s "no third-party trackers" claim stays true |
| Admin | None. `sqlite3 /data/seekers.db` over `railway ssh` |

**Knowingly accepted gap:** the rate limiter is in-memory and resets on restart. Acceptable
for a foundation release with few Seekers. It wants to be persistent before paid features.

---

## 6. Deferred, with the shape already decided

Not in v1, but the design is settled so it is not re-litigated later:

- **Alerts** — a weekly digest, Monday 09:00 HKT, riding the cadence
  `hk_jobs/reports/weekly.py` already uses. **An alert is a saved search**: store the
  existing filter params (`filtersToSearchParams`), so alerts inherit every filter added
  later for free. ~800 emails/month at 200 Seekers, well inside the existing mail
  host's limits (ADR 0009 replaced the Resend plan); daily
  would be ~6,000 and outside it. **Blocked on the open item in §9.**
- **Application tracking** — Seeker-owned status on roles already saved. Needs no email,
  no scheduled job, no fresh `jobs.db`. The cheapest way to give the account a visible
  purpose if signups disappoint.
- ~~**LinkedIn sign-in** — third provider against the same Seeker record, configured
  through a generic OIDC slot. Brand value, not data value.~~ **Shipped 2026-08-07**:
  `webapp/backend/main.py`'s `linkedin_start`/`linkedin_callback`, `LinkedInButton`
  (`AuthShell.tsx`), on `/signin` and `/register`. Needs `LINKEDIN_CLIENT_ID` /
  `LINKEDIN_CLIENT_SECRET` in the environment (docs/adr/0003's prerequisite) before
  it does anything but redirect to `?error=linkedin_unavailable` — same posture
  Google sign-in shipped with before its own credentials existed.
- **Employer accounts and billing** — a different aggregate, gated on paid inventory
  existing (`docs/PLAN_FRONT_PAGE.md` decision 20).

---

## 7. Copy that must change

1. **`PrivacyNotice.tsx:22` — set `ACCOUNTS_LIVE = false` today.** It is committed and
   live, and currently tells visitors the platform holds their name, email and a
   password hash. None of that exists yet.
2. **At ship, rewrite the account clauses** to match v1 exactly: remove "application
   status" (deferred), and add two disclosures it lacks — the **mail host** processing Seeker
   email addresses in the US (a cross-border transfer) and **Google** receiving data on
   Google sign-in. Then set the flag back to `true`.
3. **`CLAUDE.md`** needs the soft-delete carve-out from ADR 0007 written into it.
4. **`AboutPage.tsx`** — no change. Decision 3 keeps it true.

---

## 8. Build order

| Phase | Work | Verifiable outcome |
|---|---|---|
| **0** | Single origin (FastAPI serves the bundle, catch-all route) · Railway volume backups on · `ACCOUNTS_LIVE=false` | **Board works unchanged at one origin. No auth code involved** |
| 1 | `seekers.db` schema + migrations + writable connection · hashing · session issue/verify/revoke | Unit tests pass, no HTTP yet |
| 2 | register / login / logout / me · rate limits · honeypot · non-enumerable responses | A session obtainable with curl |
| 3 | SMTP (ADR 0009) · verification · password reset | Round trip to a real inbox |
| 4 | Google OAuth | Both paths reach one Seeker record |
| 5 | Server-side Saved Roles (`ATTACH` join) · `localStorage` migration | Existing saves survive first sign-in |
| 6 | AuthProvider · sign-in / register pages · Nav slot · dual-mode `useSavedJobs` | Full flow in a browser |
| 7 | Delete-account · event logging · privacy notice rewrite | Site internally consistent again |

**Phase 0 ships alone, deliberately.** It is the riskiest infrastructure change here —
it retires a Railway service, needs a catch-all route or every client-side route 404s on
refresh, and rewrites `/rail-it`. Shipping it with auth means debugging topology and
cookies simultaneously.

**Start phase 3's DNS records now, in parallel.** SPF/DKIM/DMARC verification and
propagation is waiting, not coding.

---

## 9. Open items

- [ ] **How does the `jobs.db` on the Railway volume get refreshed?** The pipeline runs
      locally against your Mac's copy; `_seed_db_if_missing()` only downloads when the file
      is *absent*; no script uploads it. Does not block v1 — **blocks alerts**, which need
      to know which Roles are new.
- [ ] **Can CNAME/TXT records be added to `finexclub.org` DNS?** It is a Wix site. Blocks
      phase 3 entirely; nothing else.
- [ ] Google Cloud project + OAuth consent screen + redirect URIs — owner task with lead time.
- [ ] `/rail-it` rewrite for the single-service topology.
- [ ] A custom domain is still wanted for the brand — decision 6 fixes cookies but leaves the
      public URL reading `backend-production-08b4e.up.railway.app`. No longer urgent.

---

## 10. Non-goals for v1

Stated as refusals, not omissions: **no gating · no alerts · no application tracking ·
no CV upload or matching · no employer accounts · no billing · no admin UI ·
no CAPTCHA · no self-serve data export.** (LinkedIn sign-in was on this list for v1;
see §6 — it shipped as the fast-follow it was always scheduled to be.)

---

## 11. Testing

- **`tests/test_auth.py`** — password never appears in any response; session cookie is
  `httpOnly`+`Secure`+`SameSite`; forgot-password returns identical responses for known and
  unknown addresses; register on an existing address is indistinguishable from success;
  expired and reused tokens rejected; rate limit trips per email *and* per IP; OAuth
  callback rejects a bad or replayed `state`; an OAuth identity with `email_verified: false`
  never auto-links to an existing account.
- **`tests/test_saved_roles.py`** — `ATTACH` join returns live job fields, not stored copies;
  a soft-deleted role shows as closed rather than live; first-sign-in migration is a union
  and is idempotent on a second run.
- **`tests/test_account_deletion.py`** — rows actually gone, sessions revoked, event logged.
- Never send real email in a test — patch the sender, as the existing submit-endpoint tests do.
