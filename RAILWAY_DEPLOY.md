# Railway deployment — Bloomberg Terminal + AURORA Intelligence Layer

This guide walks through a clean Railway deployment of all five services
(backend, frontend, TimescaleDB, Redis, Meilisearch). It assumes you've
already pushed the repository to GitHub and have a Railway account.

Total time: ~25 minutes the first time, ~5 minutes for re-deploys.

---

## 0. Prerequisites

- Railway account with a payment method on file (the free trial doesn't
  cover background workers / WebSockets after the first month).
- GitHub access to https://github.com/wpf002/bloomberg.git
- API keys for the integrations you want enabled. Anything missing
  degrades gracefully — the relevant panel just shows "not configured":
    - Alpaca paper trading (re-use Syntrackr's keys)
    - Anthropic (Claude) — for the AI advisor
    - FRED — macro panel
    - Finnhub + FMP — fundamentals fallback
    - GitHub OAuth — user accounts (Phase 6)
    - FINRA TRACE — corporate-bond panel (optional)
- A long random string for `SECRET_KEY` and `MEILI_MASTER_KEY`. Generate
  each independently:
    ```
    openssl rand -hex 48
    ```

---

## 1. Create the Railway project

1. Go to https://railway.app/new
2. Click **Deploy from GitHub repo** and pick `wpf002/bloomberg`.
3. Railway auto-detects two deployable services from the repo
   (`backend/Dockerfile`, `frontend/Dockerfile`). For now, **cancel** the
   auto-deploy — we'll add services manually so the order is correct.
4. Name the project something like `bloomberg-terminal-prod`.

---

## 2. Add the Postgres plugin (TimescaleDB)

1. In the project canvas → **+ New** → **Database** → **Add PostgreSQL**.
2. Wait ~30 seconds for the plugin to provision.
3. Click the Postgres service → **Data** tab → open the **Query** runner
   and run:
    ```sql
    CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
    ```
   Railway's Postgres image bundles the TimescaleDB extension; this just
   activates it for the database. (The backend re-runs the same statement
   on every boot, so a future region move or DB reset auto-heals.)
4. Open **Variables** on the Postgres service. Confirm `DATABASE_URL` is
   set — you'll reference this from the backend in step 5.

---

## 3. Add the Redis plugin

1. Project canvas → **+ New** → **Database** → **Add Redis**.
2. Wait for it to provision. `REDIS_URL` becomes available on the Redis
   service's Variables tab.

---

## 4. Add the Meilisearch service (Docker image)

1. Project canvas → **+ New** → **Empty Service**.
2. On the new service: **Settings** → **Source** → **Image** →
   `getmeili/meilisearch:v1.7`.
3. Rename the service to `meilisearch` (the backend builds the internal
   URL from this name).
4. **Variables** tab → add:
    ```
    MEILI_MASTER_KEY=<paste long random string from step 0>
    MEILI_NO_ANALYTICS=true
    MEILI_ENV=production
    ```
5. **Settings** → **Networking** → **Generate Domain** is *not* needed —
   we'll only access Meili over Railway's private network.
6. **Settings** → **Custom Start Command**:
    ```
    meilisearch --master-key $MEILI_MASTER_KEY --no-analytics --http-addr 0.0.0.0:$PORT
    ```
7. Click **Deploy**.

---

## 5. Deploy the backend service

1. Project canvas → **+ New** → **GitHub Repo** → pick `wpf002/bloomberg`.
2. Rename the service to `backend`.
3. **Settings** → **Source**:
    - **Root Directory**: `/` (the repo root — leave empty if Railway
      shows it as default)
    - **Dockerfile Path**: `backend/Dockerfile`
4. **Settings** → **Networking** → **Generate Domain**. Railway returns
   something like `https://backend-production-xxxx.up.railway.app`.
   Copy this URL — you'll plug it into the frontend in step 6.
5. **Settings** → **Custom Start Command**:
    ```
    python -m uvicorn backend.main:app --host 0.0.0.0 --port $PORT
    ```
6. **Settings** → **Healthcheck**:
    - **Path**: `/healthz`
    - **Timeout**: 30s
7. **Variables** tab — add the following. Copy verbatim from
   `.env.railway.example` and fill in real values; Railway accepts the
   `${{ Service.VARIABLE }}` reference syntax for plugins:
    ```
    APP_ENV=production
    DEBUG=false

    # Plugin references — copy as-is, Railway resolves at deploy time:
    DATABASE_URL=${{ Postgres.DATABASE_URL }}
    REDIS_URL=${{ Redis.REDIS_URL }}

    # Internal Meilisearch URL — service name from step 4:
    MEILISEARCH_URL=http://meilisearch.railway.internal:7700
    MEILISEARCH_KEY=<same value you set as MEILI_MASTER_KEY>

    # Frontend URL (you'll get this in step 6 — for now leave blank, fill
    # it in after the frontend gets a domain, then redeploy this service):
    FRONTEND_URL=

    # JWT signing — the second random string from step 0:
    SECRET_KEY=<long random string>

    # Integrations:
    ALPACA_API_KEY=<from Alpaca dashboard>
    ALPACA_API_SECRET=<from Alpaca dashboard>
    ALPACA_BASE_URL=https://paper-api.alpaca.markets
    ANTHROPIC_API_KEY=<from console.anthropic.com>
    ANTHROPIC_MODEL=claude-sonnet-4-6
    FRED_API_KEY=<from fred.stlouisfed.org>
    FINNHUB_API_KEY=<from finnhub.io>
    FMP_API_KEY=<from financialmodelingprep.com>
    SEC_USER_AGENT=bloomberg-terminal you@example.com

    # GitHub OAuth — set after registering the app (step 7):
    GITHUB_CLIENT_ID=
    GITHUB_CLIENT_SECRET=

    # Optional:
    FINRA_API_KEY=
    FINRA_API_SECRET=
    ```
8. Click **Deploy**. Watch the build logs — first build takes ~3 minutes
   (compiling numpy, scipy, asyncpg). Subsequent builds use the cache and
   take ~30s.
9. Once green, hit `https://<backend-url>/healthz` in a browser. You
   should see something like:
    ```json
    {
      "status": "ok",
      "db": "ok",
      "redis": "ok",
      "meilisearch": "ok",
      "version": "9.2.0"
    }
    ```

---

## 6. Deploy the frontend service

1. Project canvas → **+ New** → **GitHub Repo** → pick `wpf002/bloomberg`
   again. Yes, the same repo — Railway will create a second service.
2. Rename the service to `frontend`.
3. **Settings** → **Source**:
    - **Root Directory**: `/` (repo root)
    - **Dockerfile Path**: `frontend/Dockerfile`
4. **Settings** → **Networking** → **Generate Domain**. Copy the URL.
5. **Settings** → **Custom Start Command**:
    ```
    npm run start
    ```
6. **Settings** → **Healthcheck**:
    - **Path**: `/`
    - **Timeout**: 30s
7. **Variables** tab — add the backend public URL:
    ```
    VITE_API_URL=https://<backend-railway-url-from-step-5>
    NODE_ENV=production
    ```
   Note: `VITE_API_URL` is baked into the bundle at build time, so any
   change requires a redeploy.
8. Click **Deploy**.

---

## 7. Wire FRONTEND_URL on the backend

1. Open the backend service → **Variables**.
2. Set `FRONTEND_URL=https://<frontend-railway-url-from-step-6>`.
3. Backend redeploys automatically when you save. The new value:
    - Adds the frontend origin to the CORS allow-list.
    - Switches session cookies to `SameSite=None; Secure` so cross-origin
      XHRs from the SPA carry them.
    - Becomes the post-login redirect destination for GitHub OAuth.

---

## 8. (Optional) GitHub OAuth setup

Skip this section if you don't need the Phase 6 user-account features
(per-user watchlists, layouts, alert rules). The terminal still works as
a single-tenant app without OAuth — the login button is hidden when
`GITHUB_CLIENT_ID` is unset.

1. https://github.com/settings/developers → **OAuth Apps** → **New OAuth App**.
2. Fill in:
    - **Application name**: Bloomberg Terminal (Production)
    - **Homepage URL**: `https://<frontend-railway-url>`
    - **Authorization callback URL**:
      `https://<backend-railway-url>/api/auth/github/callback`
3. Click **Register application** → copy the Client ID, generate a Client
   Secret, copy that too.
4. On the backend service → **Variables**:
    ```
    GITHUB_CLIENT_ID=<paste>
    GITHUB_CLIENT_SECRET=<paste>
    ```
5. Redeploy. The login button appears in the frontend launchpad.

---

## 9. First-time verification

1. Open the frontend URL in a browser.
2. Hit each panel in turn — the most data-heavy ones to spot-check:
    - **MKT** (Market Overview) — should populate from Alpaca.
    - **NEWS** — should stream via WebSocket. Open the browser devtools
      Network → WS tab and confirm a `wss://<backend>/api/ws/news`
      connection in `101 Switching Protocols`. You should see ping
      frames every 30s.
    - **MAC** (Macro) — should show FRED series.
    - **SRCH** (Filings search) — Meilisearch-backed; should return
      results once the daily indexer runs (or click the panel's
      "Re-index" button to force a refresh).
3. Check `/healthz` again — every dependency should report `"ok"`.
4. (If OAuth is enabled) Click **Login with GitHub** in the frontend
   launchpad → complete the consent → land back on the frontend with
   your avatar showing in the header.

---

## 10. Troubleshooting cheatsheet

| Symptom | Likely cause |
|---|---|
| `/healthz` reports `"db": "degraded"` | TimescaleDB extension didn't install. Re-run `CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;` in the Postgres query runner. |
| `/healthz` reports `"meilisearch": "degraded"` | `MEILISEARCH_KEY` on backend ≠ `MEILI_MASTER_KEY` on the meilisearch service. Match them and redeploy backend. |
| Frontend loads but every API call returns CORS errors | `FRONTEND_URL` is unset on the backend, or doesn't match the actual frontend domain. Check both, redeploy backend. |
| WebSocket connects then closes after ~90s | You're missing the `useStream` pong handler — confirm `frontend/src/hooks/useStream.js` is on the deployed branch. |
| GitHub login → "redirect URI mismatch" | The OAuth app's callback URL doesn't match the backend's actual domain. Update the OAuth app settings, no redeploy needed. |
| Backend crashes at boot with `asyncpg.InvalidPasswordError` | `DATABASE_URL` was set as a literal string instead of a Railway reference. Replace with `${{ Postgres.DATABASE_URL }}`. |

---

## 11. Updating the deployment

1. Push to `main` on https://github.com/wpf002/bloomberg.git.
2. Railway auto-deploys both backend and frontend (each service watches
   the same branch).
3. The backend's startup migration is idempotent, so DDL changes get
   applied automatically. No manual DB step.
4. Frontend changes that depend on a new env var require setting the var
   in the Railway dashboard *before* the first deploy that reads it
   (Vite bakes env vars at build time).
