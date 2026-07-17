# Deploying the demo to Railway

A temporary, public investor demo of the FinEx Careers job board. Frozen data
snapshot, free `*.up.railway.app` URLs, no logins.

**Architecture:** two Railway services from this one repo
(`CHAD-sys/hk-financial-job-scraper`):

| Service   | Root directory      | What it runs                                   |
|-----------|---------------------|------------------------------------------------|
| backend   | `webapp/backend`    | FastAPI (uvicorn on `0.0.0.0:$PORT`) reading `jobs.db` |
| frontend  | `webapp/frontend`   | Vite build of the React app, served with `vite preview` |

The database is **never in git**. It ships to the backend service separately —
via a Railway **Volume** (recommended) or an on-boot download (`DB_SEED_URL`).

---

## What the code already does (done for you)

- **Backend start command** — `webapp/backend/Procfile`: `uvicorn main:app --host 0.0.0.0 --port $PORT`.
- **Pinned deps** — `webapp/backend/requirements.txt` (fastapi, uvicorn[standard], pydantic).
- **DB path is configurable** — backend reads `JOBS_DB_PATH` (defaults to the local `data/jobs.db`).
- **Optional DB auto-seed** — if `JOBS_DB_PATH` is missing and `DB_SEED_URL` is set, the backend downloads the DB once on first boot.
- **CORS is configurable** — backend reads `CORS_ORIGINS` (comma-separated, or `*`).
- **Frontend API URL is configurable** — reads `VITE_API_URL` at build time (no hardcoded localhost).
- **Frontend serve command** — `npm start` → `vite preview` (SPA fallback, binds `0.0.0.0`, allows the railway host).

The prepared DB snapshot to upload is **`data/jobs_demo.db`** (~34 MB, gitignored).

---

## Manual steps in Railway (you do these — I can't use your login/payment)

### 0. Create the project
1. Go to <https://railway.app> and sign in with GitHub (**your** login).
2. **New Project → Deploy from GitHub repo** → authorize Railway for
   `CHAD-sys/hk-financial-job-scraper` → select it.
3. If Railway prompts for a payment card to enable deployments, add one
   yourself — the free trial credit covers a short demo.

### 1. Backend service
1. In the project: **New → GitHub Repo → same repo** (or use the first service).
2. Open the service → **Settings → Root Directory** = `webapp/backend`.
3. Railway auto-detects Python + the `Procfile`. Confirm the start command is
   `uvicorn main:app --host 0.0.0.0 --port $PORT`.
4. **Variables** tab, add:
   - `JOBS_DB_PATH` = `/data/jobs.db`
   - `CORS_ORIGINS` = `*`  *(tighten to the frontend URL after step 2 if you like)*
5. **Add a Volume:** service → **Settings → Volumes → New Volume**, mount path
   `/data`.
6. **Upload the DB to the volume** (pick one):
   - **A — Volume upload (recommended):** in the service's **Volume** panel use
     *Upload* (or the service **Shell/SSH**) to put `data/jobs_demo.db` onto the
     volume as `/data/jobs.db`.
   - **B — Auto-seed (easiest):** upload `data/jobs_demo.db` somewhere public and
     downloadable (e.g. a **GitHub Release asset** on your repo — a release asset
     is *not* the git tree, so the DB still isn't committed). Then add variable
     `DB_SEED_URL` = that download URL. The backend fetches it on first boot.
7. Once it deploys, open the backend's public URL and check
   `https://<backend>.up.railway.app/api/stats` returns real numbers.

### 2. Frontend service
1. **New → GitHub Repo → same repo** again (second service).
2. **Settings → Root Directory** = `webapp/frontend`.
3. Railway auto-detects Node, runs `npm install` + `npm run build`, then `npm start`.
4. **Variables** tab, add:
   - `VITE_API_URL` = `https://<backend>.up.railway.app`  *(the backend URL from step 1; no trailing slash)*
5. Redeploy so the build bakes in `VITE_API_URL`. Open the frontend URL — the
   board should load real jobs.

### 3. (Optional) Lock CORS down
Back in the **backend** service, set `CORS_ORIGINS` to the exact frontend URL
(`https://<frontend>.up.railway.app`) and redeploy.

### 4. Share
Send your boss the **frontend** URL. No login required.

---

## Local sanity check before deploying
```bash
# backend
cd webapp/backend && JOBS_DB_PATH=../../data/jobs.db CORS_ORIGINS='*' \
  uvicorn main:app --host 0.0.0.0 --port 8000
# frontend (separate shell)
cd webapp/frontend && VITE_API_URL=http://localhost:8000 npm run build && npm start
```

## Notes
- This is a **read-only** demo — no scraper/enrichment runs on Railway, no
  `DEEPSEEK_API_KEY` needed there. Never put API keys in this public repo.
- To refresh the demo data later, regenerate the snapshot locally
  (`sqlite3 data/jobs.db "VACUUM INTO 'data/jobs_demo.db'"`) and re-upload it.
