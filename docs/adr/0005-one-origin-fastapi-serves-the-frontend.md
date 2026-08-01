# One origin: FastAPI serves the React bundle

**Status:** accepted (2026-07-30)

The built React app is served as static files by the existing FastAPI service, so the
UI and the API share a single origin. The separate Railway frontend service becomes
redundant.

**Why this was forced.** `up.railway.app` is on the Public Suffix List (line 15360:
*"Railway Corporation … up.railway.app"*). That makes
`finex-careers.up.railway.app` and `backend-production-08b4e.up.railway.app`
**different sites**, not sibling subdomains. Browsers reject a `Domain` cookie whose
value is a public suffix, so there is no shared parent to scope a session to, and every
cookie the API sets is a third-party cookie from the UI's perspective. `SameSite=Lax`
cookies are never sent on cross-site fetches, and `SameSite=None; Secure` is blocked
outright by Safari's ITP and partitioned by Firefox. A cookie session across those two
URLs cannot work, and would have failed only in production.

The alternative — `careers.finexclub.org` + `api.finexclub.org`, giving both a real
shared parent — was recommended and rejected in favour of collapsing to one service.

**Consequences:**

- CORS middleware becomes unnecessary; the frontend calls relative `/api` paths, which
  `webapp/frontend/.env.local` already supports (`VITE_API_URL=`).
- Frontend and backend now deploy together. `/rail-it` deploys two services and needs
  rewriting.
- FastAPI needs a catch-all route returning `index.html` for non-`/api` paths, or
  client-side routes (`/jobs`, `/saved`, …) 404 on hard refresh.
- **The public URL becomes the backend service's**, which reads
  `backend-production-08b4e.up.railway.app`. Cookies are fixed; the brand URL is not.
  A custom domain is still wanted, just no longer urgent.
