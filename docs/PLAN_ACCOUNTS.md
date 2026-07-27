# PLAN — User accounts, sign-in, and gated listings

**Status:** approved, not started
**Date:** 2026-07-27
**Costed at:** 5d on the August build plan. Realistic estimate below is **7–9d** —
see §11. This is the largest single item in August and it unblocks three others.

---

## 1. What we're building

The platform has never had accounts. This adds them, and simultaneously changes
the board from fully public to **partially gated**: anyone can see that a role
exists, but the description, salary and apply link require an account.

Three things become possible once this lands:

- **Auto-tracking** (4d, separate item) — application status held per user on the
  server instead of per device.
- **Saved roles across devices** — today they live in `localStorage` and die with
  the browser profile.
- **Stage 2 employer accounts** — the paid-listing product is gated on this.

---

## 2. Decisions (locked)

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | Auth is **FastAPI-native**, not PocketBase | PocketBase is a reviewer mirror, is not deployed, and must be *stopped* during the daily sync — see §3 |
| 2 | Users live in their **own SQLite file**, never `jobs.db` | The pipeline rewrites `jobs.db` daily and `backup.py` copies it wholesale; credentials must not be in the scraper's blast radius or in every nightly backup |
| 3 | **Full listings require an account** | Owner decision. Consequences are handled as work in §8, not treated as blockers |
| 4 | **Both** Google sign-in **and** email + password | Owner decision. Costs more than either alone; reflected in the estimate |
| 5 | Gating is enforced **server-side** | A UI-only gate is not a gate — see §7.1 |
| 6 | Sessions are **httpOnly cookies**, not localStorage tokens | A token in localStorage is readable by any XSS; an httpOnly cookie is not |

---

## 3. Why not PocketBase (the build plan's assumption)

The August plan says *"Our database (PocketBase) ships authentication built in,
which is why this is days not weeks."* That premise does not hold:

- **It is not the platform's database.** `data/jobs.db` is, read by FastAPI.
  `hk_jobs/sync_pocketbase.py` states it directly: *"PocketBase is NOT part of the
  live app; it is a browsable, shareable copy used to hand the data to a reviewer."*
- **It is not deployed.** `webapp/backend/railway.json` starts `uvicorn main:app`
  and nothing else. No PB service exists in any deploy config.
- **It must be offline during the daily sync.** `daily_run.sh` phase 4 refuses to
  run while PB serves on :8090, because the sync writes PB's SQLite file directly.
  If PB were the auth server, **every sign-in would fail during the nightly run.**

Making PocketBase viable would mean rewriting the sync to go through PB's HTTP API
and deploying a second service. That is more work than writing the auth, and it
buys a dependency rather than removing one.

---

## 4. Facts established (do not re-derive)

- Backend is FastAPI, `webapp/backend/main.py`, now with two POST endpoints
  (`/api/contact`, `/api/post-role`) and `mailer.py` for outbound email.
- CORS is `["GET", "POST"]`. Cookie auth needs `allow_credentials=True` **and**
  an explicit origin list — `allow_origins=["*"]` is invalid with credentials
  and browsers will reject it.
- `useSavedJobs` (`src/hooks/useSavedJobs.ts`) is `localStorage`-only, keyed
  `finex_saved_jobs:v1`, with a legacy-key migration path already in place.
- The board's list endpoint currently returns the apply link (`url`) and both
  salary fields on **every** row, and `/api/jobs/{source}/{source_id}` adds
  `description_clean` + `description_summary`.
- Live shape: 3,612 active primary roles — 3,266 mainstream, 149 Exclusive,
  197 Recruiter Posts.
- `PrivacyNotice.tsx` already describes accounts, gated behind `ACCOUNTS_LIVE`
  (currently `true`). Shipping this makes that notice accurate.
- Nav already reserves the right-hand slot for a Sign in control.

---

## 5. Data model — `data/users.db`

A separate SQLite file, created and migrated by the backend on boot.

```sql
CREATE TABLE users (
    id              TEXT PRIMARY KEY,        -- uuid4
    email           TEXT NOT NULL UNIQUE,    -- stored lowercased
    password_hash   TEXT,                    -- NULL for Google-only accounts
    google_sub      TEXT UNIQUE,             -- Google's stable subject id, NULL if none
    display_name    TEXT NOT NULL DEFAULT '',
    email_verified  INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    last_login_at   TEXT,
    is_active       INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE sessions (
    token_hash   TEXT PRIMARY KEY,           -- sha256 of the cookie value, never the value
    user_id      TEXT NOT NULL REFERENCES users(id),
    created_at   TEXT NOT NULL,
    expires_at   TEXT NOT NULL,
    user_agent   TEXT
);

CREATE TABLE email_tokens (
    token_hash  TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(id),
    purpose     TEXT NOT NULL,               -- 'verify' | 'reset'
    expires_at  TEXT NOT NULL,
    used_at     TEXT
);

CREATE TABLE saved_jobs (
    user_id    TEXT NOT NULL REFERENCES users(id),
    source     TEXT NOT NULL,
    source_id  TEXT NOT NULL,
    saved_at   TEXT NOT NULL,
    PRIMARY KEY (user_id, source, source_id)
);
```

**Why token *hashes* and not tokens:** if `users.db` leaks, stored session tokens
would be immediately usable to impersonate every logged-in user. Hashes are not.
Same reasoning as password hashing, and it costs one line.

`saved_jobs` stores only the key, not a copy of the job — the job lives in
`jobs.db` and is joined at read time, so a saved role never goes stale.

---

## 6. Backend — `webapp/backend/auth.py` (new) + routes in `main.py`

```
POST /api/auth/register       email, password        -> 201, sends verification
POST /api/auth/login          email, password        -> 200 + session cookie
POST /api/auth/logout                                -> 204, clears cookie
GET  /api/auth/me                                    -> current user or 401
POST /api/auth/verify         token                  -> marks email_verified
POST /api/auth/forgot         email                  -> always 200 (see below)
POST /api/auth/reset          token, new password    -> 200
GET  /api/auth/google         -> redirect to Google
GET  /api/auth/google/callback -> exchanges code, upserts user, sets cookie
GET  /api/me/saved            -> saved roles (joined against jobs.db)
POST /api/me/saved            source, source_id
DELETE /api/me/saved/{source}/{source_id}
```

Non-negotiables, each for a specific reason:

| Requirement | Why |
|---|---|
| **Argon2id** password hashing (pin the lib version at install; do not guess) | bcrypt is acceptable, plain sha256 is not |
| `/api/auth/forgot` always returns 200, even for unknown emails | Different responses turn it into an account-existence oracle |
| Login rate-limited per email **and** per IP | Per-IP alone lets a botnet spray one account; per-email alone lets one IP spray many |
| Session cookie: `httpOnly`, `Secure`, `SameSite=Lax`, expiry set | Lax still allows the Google OAuth redirect to land while blocking cross-site POSTs |
| Google OAuth **state** parameter, single-use | Without it the callback is CSRF-able |
| Verification and reset tokens: single-use, ≤1h expiry, stored hashed | A leaked mailbox otherwise grants permanent access |
| Constant-time comparison for all token checks | Timing side channel is cheap to avoid |
| `allow_credentials=True` + explicit origin list in CORS | Wildcard origins are rejected by browsers when credentials are sent |
| Email enumeration: register on an existing address behaves like success and sends a "someone tried to register" mail | Same oracle problem as forgot-password |

New dependencies for `requirements.txt` (**resolve real versions at install time —
a guessed pin already broke a build once this week**): `argon2-cffi`,
`authlib` (Google OAuth), `itsdangerous` or `pyjwt` for signed tokens.

---

## 7. The gate

### 7.1 Server-side, not UI-side

The gate lives in the **API response builder**, not the React components. If
`/api/jobs` keeps returning descriptions and apply links and the UI merely hides
them, anyone can read the JSON directly and the gate is decorative.

Anonymous responses omit the fields entirely rather than blanking them, so a
client cannot tell a gated field from an empty one:

| Field | Anonymous | Signed in |
|---|:--:|:--:|
| title, company, sector, locations, seniority, posted_at, source_tier | ✅ | ✅ |
| `description_excerpt` (first ~200 chars) | ✅ | ✅ |
| `description_clean`, `description_summary` | ❌ | ✅ |
| `salary_estimated_*`, `salary_hkd_*` | ❌ | ✅ |
| `url`, `apply_url` | ❌ | ✅ |
| `required_skills`, `board_signals` | ❌ | ✅ |

Implement as one `serialise_job(row, *, authed: bool)` used by **both** the list
and detail endpoints. A second code path is how these gates leak.

### 7.2 Search still works on gated fields

Filtering and full-text search must keep querying the full row server-side —
otherwise an anonymous visitor searching "Murex" gets nothing and concludes the
board is empty. They see *that* matching roles exist and how many; they just
cannot read them. That is the entire persuasion mechanism for signing up.

---

## 8. Consequences of gating — required work, not optional

These follow directly from decision 3 and must ship **with** it, not after.

1. **`AboutPage.tsx` currently says "no paywall on any listing".** That becomes
   false the moment this ships. It must be rewritten in the same release.
2. **`PrivacyNotice.tsx`** — clause 2's "Browsing the job index requires none of
   this. You can read every listing without giving us anything." becomes false.
   Same release.
3. **The portal's Careers door** says "Every finance role in Hong Kong" with a
   live count; it should say what is visible without an account.
4. **SEO / Google for Jobs — read this before implementing.** Google's structured
   data policy prohibits **cloaking**: serving Googlebot content that a user
   arriving from that search result cannot see. If we emit `JobPosting`
   structured data with full descriptions while gating those descriptions from
   users, that is a violation and risks removal from Google Jobs entirely.
   Three lawful options, pick one deliberately:
   - **(a)** Do not emit `JobPosting` structured data at all. Simplest, forfeits
     Google Jobs traffic.
   - **(b)** Keep the *description* public and gate only salary, apply link and
     skills. Compliant, keeps indexing, still a strong signup reason.
   - **(c)** First-click-free: visitors arriving from Google see the full role;
     the gate applies to onward browsing. More logic, keeps traffic.
   Recommendation: **(b)** — it preserves the acquisition channel the board
   depends on while still making the account worth having.
5. **`robots.txt` / `sitemap.xml`** — neither exists yet. Whatever stays public
   should be indexable on purpose rather than by accident.

---

## 9. Frontend

| File | Change |
|---|---|
| `src/auth/AuthProvider.tsx` | NEW — context: `user`, `loading`, `login`, `logout`, `register`. Calls `/api/auth/me` once on mount |
| `src/pages/SignInPage.tsx` | NEW — `/signin`, email+password form, "Continue with Google", link to register |
| `src/pages/RegisterPage.tsx` | NEW — `/register` |
| `src/pages/VerifyEmailPage.tsx` | NEW — `/verify` landing for the emailed link |
| `src/pages/ResetPasswordPage.tsx` | NEW — `/reset` |
| `src/components/Nav.tsx` | Fill the reserved slot: Sign in → user menu when authed |
| `src/components/JobCard.tsx` | Locked-state treatment for gated fields |
| `src/components/JobDetailModal.tsx` | Gate description/salary/apply behind a sign-in prompt that explains *why* |
| `src/hooks/useSavedJobs.ts` | Dual mode: `localStorage` when anonymous, API when authed. **On first sign-in, migrate existing local saves to the account** — silently losing them is the kind of thing users never forgive |
| `src/api/client.ts` | `credentials: 'include'` on every request; 401 handling |

`fetch` must send `credentials: 'include'` or the session cookie is never
attached — the single most common way this feature "works locally and not in
production".

---

## 10. Build order

| Phase | Work | Verifiable outcome |
|---|---|---|
| 1 | `users.db` schema + `auth.py`: hashing, sessions, cookie handling | Unit tests pass; no HTTP yet |
| 2 | register / login / logout / me + rate limiting | Can create a session with curl |
| 3 | Email verification + password reset via `mailer.py` | Round trip works end to end |
| 4 | Google OAuth (needs a GCP project + redirect URIs per environment) | Both sign-in paths reach one user record |
| 5 | `serialise_job(authed=…)` + gate on both endpoints | Anonymous JSON provably lacks the fields |
| 6 | AuthProvider, sign-in/register pages, Nav slot | Full flow in the browser |
| 7 | Saved-jobs migration local → server | Existing saves survive first sign-in |
| 8 | About + privacy rewrite, SEO decision from §8.4, robots/sitemap | Site is internally consistent again |

Phases 1–3 are the risky ones and are independently testable. Phase 4 has an
external dependency (Google Cloud console) that should be started early because
it involves waiting on a consent screen, not coding.

---

## 11. Estimate

The plan's 5 days assumed PocketBase supplied auth, verification, reset and an
admin UI. Writing it ourselves, with **two** sign-in methods and a server-side
gate:

| | |
|---|---|
| Phases 1–3 (core auth, email flows) | 3d |
| Phase 4 (Google OAuth) | 1–1.5d |
| Phase 5 (gating, both endpoints, tests) | 1d |
| Phases 6–7 (frontend, saved-jobs migration) | 2d |
| Phase 8 (copy, SEO, robots/sitemap) | 0.5–1d |
| **Total** | **7.5–8.5d** |

August has 21 working days and was already at 19.5 committed before the contact
endpoint, `/post-a-role`, and the About/privacy work were added. **This item
alone exceeds the remaining slack.** Something else in August moves, or this
does — that is a scheduling decision, not an engineering one.

---

## 12. Testing

- **Security-focused, in `tests/test_auth.py`:** password never returned in any
  response; session cookie is httpOnly+Secure+SameSite; forgot-password returns
  identical responses for known and unknown emails; login rate limit trips per
  email and per IP; expired and reused tokens rejected; OAuth callback rejects a
  bad or replayed `state`.
- **Gate tests, in `tests/test_job_gating.py`:** anonymous `/api/jobs` and
  `/api/jobs/{source}/{id}` responses contain none of the gated keys; the same
  requests with a session contain all of them; search on a gated field still
  returns correct counts anonymously.
- Never send real email in a test — patch `mailer.send_mail` as the existing
  submit-endpoint tests do.

---

## 13. Open items

- [ ] SEO approach from §8.4 — (a), (b) or (c). **Blocks phase 5**; recommend (b)
- [ ] Google Cloud project + OAuth consent screen + redirect URIs (owner task, has lead time)
- [ ] Move transactional email off the personal Gmail before it carries verification and reset links
- [ ] Session lifetime, and whether "remember me" is offered
- [ ] What happens to the 197 Recruiter Posts under gating — recruiter attribution is arguably the most sensitive data on the board
- [ ] Whether Stage 2 employer accounts share this `users` table or get their own role column (cheap to decide now, expensive later)
