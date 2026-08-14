# Deploying FinEx Careers to Railway

This file used to describe a temporary, read-only investor demo across two
GitHub-connected Railway services with no logins and a frozen data snapshot.
None of that is true anymore — it hasn't been since the 2026-08-05
single-origin cutover, and this file went stale in place instead of getting
fixed. This is the corrected version.

**The authoritative, step-by-step deploy runbook is the `/rail-it` Claude Code
skill** (deploy → verify → report, with every landmine documented). This file
is the human-readable summary; if the two ever disagree, trust the skill and
fix this file.

---

## Current architecture

**One Railway service**, not two. It serves the built React bundle *and* the
FastAPI backend from a single origin — a static frontend host was tried
first and abandoned because `up.railway.app` sits on the Public Suffix List,
which made the frontend and backend different *sites* and broke session
cookies for Seeker/Employer login entirely (see `docs/adr/0005`).

| | |
|---|---|
| Railway project | `finex-jobs-demo` |
| Service | `backend` (one service, despite the project's leftover name) |
| Deploy method | **CLI upload only** (`railway up`) — **not** connected to GitHub. Pushing to git deploys nothing. |
| Live accounts | Real — Seeker and Employer accounts, sessions, saved roles, resumes. This is not a demo dataset. |
| Database | SQLite on a Railway **Volume** at `/data`: `jobs.db` (catalogue), `seekers.db`, `employers.db` — never in git, never touched by a deploy. |

## Domains

| Domain | Points to | Notes |
|---|---|---|
| `finex-careers.up.railway.app` | Railway-provided | The original address. Still live and working — kept so nothing bookmarked or shared breaks. |
| `www.finexcareers.com` | same Railway service, via CNAME | The company's own domain (bought on Bluehost, DNS delegated to Bluehost's nameservers). Added 2026-08-14. |
| `finexcareers.com` (bare) | Bluehost, 301 → `https://www.finexcareers.com` | Bluehost still serves the bare domain itself, purely to issue that one redirect — it's not proxying to Railway. |

`PUBLIC_BASE_URL` and `LINKEDIN_REDIRECT_URI` (Railway env vars) determine
which of these the backend builds into its own links — password-reset
emails, verify-email links, and both OAuth redirect flows. Google/LinkedIn's
own developer consoles also need the matching authorized-redirect URL added
before sign-in works on a given domain.

## Deploying

Use the `/rail-it` skill. Summary of what it does:

1. Build the frontend locally (`tsc --noEmit && npm run build`), copy
   `webapp/frontend/dist` → `webapp/backend/frontend_dist` (untracked, but
   must exist on disk — it ships because it's present, not because it's
   committed; never add it to `.gitignore`, that silently drops it from the
   upload with no error).
2. Run the backend test suite.
3. `railway up --service backend --ci` from **inside** `webapp/backend`
   specifically — `railway up` uploads whatever directory is linked to the
   Railway project, resolved by walking up from cwd, not a `[PATH]` argument.
4. Poll until the deployment settles, then verify the live bundle hash
   actually changed and `/health`, `/api/stats`, and a client-side SPA route
   all return real data — a Railway `SUCCESS` only means the container built
   and started, not that the right thing is being served.

## Config surface (Railway env vars, current)

Beyond the standard `JOBS_DB_PATH`, `CORS_ORIGINS`, `FRONTEND_DIST`,
`PUBLIC_BASE_URL`, and OAuth client credentials, two dormant-by-default
kill-switches exist and are documented in `webapp/backend/settings.py`:

- `ALERTS_ENABLED` — weekly Seeker digest email.
- `DISK_ALERTS_ENABLED` / `DISK_ALERT_THRESHOLD_PCT` (default `80`) — daily
  email when the Railway volume crosses the threshold, checked from inside
  the always-on backend process (the GitHub Actions pipeline runner never
  touches this filesystem). See `webapp/backend/disk_alerts.py`.

Both require `SMTP_USER`/`SMTP_PASS` to actually send anything — as of this
writing those are **not set on production**, so submissions, weekly alerts,
and the disk alert are all silently queued/logged but never emailed until
someone sets them.

## Rollback

```bash
railway deployment list --service backend     # find the last SUCCESS
railway redeploy --service backend             # redeploys it
```

A failed deploy needs no rollback — the previous deployment keeps serving,
Railway only cuts over once a build actually succeeds.
