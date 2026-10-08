# Deploying WellCosting Pro: Vercel + Render + Supabase

This guide deploys the three parts of the application to three managed services:

```
Browser ──HTTPS──▶ Vercel   (React SPA, static files)
                     │  /api/*, /docs, /openapi.json  (rewrites proxy — same-origin)
                     ▼
                  Render   (FastAPI + uvicorn, Python web service)
                     │  DATABASE_URL
                     ▼
                  Supabase (PostgreSQL)
```

**Why this split works without code changes:** the frontend calls the API with
relative URLs (`/api/v1/...`), and the refresh token is an HttpOnly cookie scoped
to `/api/v1/auth`. Vercel's `rewrites` (see `frontend/vercel.json`) proxy those
paths to Render, so from the browser's perspective everything is same-origin and
the cookie keeps working. No `VITE_*` build-time variables are required.

Estimated setup time: ~30 minutes.

---

## 1. Supabase — PostgreSQL database

1. Sign up at [supabase.com](https://supabase.com) and create a **New Project**
   (choose a strong database password — you will need it for the connection string —
   and a region near your users).
2. Wait for the project to finish provisioning (~2 minutes).
3. Go to **Project Settings → Database → Connection string** and copy the
   **URI** (or assemble it from the connection parameters shown below).
4. Build the value for the app's `DATABASE_URL` (note the `+psycopg` driver prefix
   and the `sslmode=require` parameter — the app uses SQLAlchemy with psycopg):

   ```
   postgresql+psycopg://postgres:<DB_PASSWORD>@db.<PROJECT_REF>.supabase.co:5432/postgres?sslmode=require
   ```

   - `<DB_PASSWORD>`: the project database password. **URL-encode** it if it
     contains special characters (`@`, `#`, `%`, `/`, ...). In the Supabase
     dashboard use *Connection string → URI* with the password inserted, or
     encode manually (e.g. `@` → `%40`).
   - `<PROJECT_REF>`: the project reference, e.g. `abcdefghijklmnopqrst`.
   - Use the **direct connection** (port `5432`), not the Supabase connection
     pooler (port `6543`). The pooler runs in transaction mode, which conflicts
     with SQLAlchemy's connection handling. If direct connections fail from
     your network (some Supabase projects are IPv6-only), switch the host to the
     pooler host `aws-0-<region>.pooler.supabase.com:6543` instead.

**Supabase notes**

- The free tier pauses the database after ~1 week of inactivity; the first
  request after a pause is slow while it resumes. Paid tier ($25/mo) stays on.
- The app enforces tenant isolation in the API layer, not via Row Level
  Security. Only the Render service should know `DATABASE_URL` — never expose it
  to the browser (this deployment keeps it server-side only).
- Optional hardening: **Project Settings → Database → Network Restrictions** to
  allow only Render's outbound IPs (paid Render plans have static IPs; free-tier
  IPs are dynamic, so skip this on the free plan).

---

## 2. Render — FastAPI backend

You can configure Render either from the **dashboard** (recommended for a first
deployment) or from the included **`render.yaml`** blueprint (one-click, then
fill in the secrets in the dashboard).

### Option A: Dashboard

1. Sign up at [render.com](https://render.com) and click **New → Web Service**,
   then connect your GitHub account and select the `praveen-christuraj/WellCostingPro`
   repository.
2. Configure the service:

   | Setting | Value |
   |---|---|
   | Name | `wellcosting-api` (your choice; becomes `https://wellcosting-api.onrender.com`) |
   | Region | Same region as your Supabase project |
   | Environment | **Python 3** |
   | Root Directory | `backend` |
   | Build Command | `pip install -r requirements.txt` |
   | Start Command | `uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}` |
   | Health Check Path | `/api/health` |
   | Plan | Free (sleeps after 15 min idle → ~30–60 s cold start) or **Starter ($7/mo)** for always-on |

   - Render sets the `PORT` environment variable, so the start command must use
     it (the `8000` fallback only matters outside Render).
   - To also run migrations automatically before each deploy, add a
     **Pre-Deploy Command**: `alembic upgrade head`. (Alternatively put
     `alembic upgrade head &&` at the front of the Start Command.)
3. Add the **environment variables** (table below) under *Environment*.
4. Click **Create Web Service** and wait for the first deploy.

### Option B: Blueprint (`render.yaml`)

1. In the Render dashboard: **New → Blueprint**, connect the repository.
2. Render detects `render.yaml` at the repo root. Click **Apply**.
3. Fill in the `sync: false` secrets in the dashboard when prompted
   (`DATABASE_URL`, `SECRET_KEY`, `CORS_ORIGINS`, and the `SEED_*` values).

### Environment variables for the API

| Variable | Required | Value / how to generate |
|---|---|---|
| `DATABASE_URL` | **Yes** | Supabase connection string from §1: `postgresql+psycopg://postgres:<password>@db.<ref>.supabase.co:5432/postgres?sslmode=require` |
| `SECRET_KEY` | **Yes** | `openssl rand -hex 32` (at least 32 characters, unique per environment; the app refuses to start with PostgreSQL if it is missing/short/default) |
| `SECURE_COOKIES` | **Yes** | `true` — Vercel serves HTTPS, and the refresh cookie is set with the `Secure` flag |
| `CORS_ORIGINS` | **Yes** | The exact Vercel origin(s), comma-separated, e.g. `https://wellcosting-pro.vercel.app`. Add your custom domain too if you attach one. No wildcards (the API sends credentialed CORS). |
| `BOOTSTRAP_ADMIN_ON_STARTUP` | No | `true` (default). Set `false` only if you seed manually. |
| `SEED_ORG_SLUG` | First boot | Workspace ID, e.g. `my-company` |
| `SEED_ORG_NAME` | First boot | Display name, e.g. `My Company` |
| `SEED_OWNER_NAME` | First boot | Administrator's name, e.g. `Jane Smith` |
| `SEED_ADMIN_EMAIL` | First boot | Administrator e-mail, e.g. `owner@example.com` |
| `SEED_ADMIN_PASSWORD` | First boot | Password, **12+ characters**. **Delete this variable after the first successful boot** (see §4). |
| `ACCESS_TOKEN_MINUTES` | No | Default `15` |
| `REFRESH_TOKEN_DAYS` | No | Default `7` |
| `APP_NAME` | No | Default `WellCosting Pro` |

Notes:

- Never commit these to Git. Render's dashboard/blueprint stores them encrypted;
  the repo's `.gitignore` already excludes `.env`.
- **Free-tier cold starts:** after 15 minutes idle the service sleeps and the
  first request takes ~30–60 s. For a demo that's fine; for real use, pick the
  Starter plan so the API (and its Supabase database) stay warm.
- Verify the deploy: open `https://<service>.onrender.com/api/health` — you
  should get `{"status":"ok","admin_seeded":false}` before seeding, and
  `"admin_seeded":true` after.

---

## 3. Vercel — React frontend

1. Sign up at [vercel.com](https://vercel.com), click **Add New → Project**, and
   import the `praveen-christuraj/WellCostingPro` repository.
2. Configure the project:

   | Setting | Value |
   |---|---|
   | Framework Preset | **Vite** |
   | Root Directory | `frontend` |
   | Build Command | `npm run build` (default) |
   | Output Directory | `dist` (default) |
   | Install Command | `npm ci` (recommended; `package-lock.json` is committed) |
   | Production Branch | `main` |

3. **Environment variables: none are required.** The frontend has no build-time
   configuration — it calls the API with relative `/api` paths.
4. **Point the proxy at your Render service.** Edit `frontend/vercel.json` and
   replace `YOUR-RENDER-SERVICE` with your actual Render service name, then
   commit:

   ```json
   {
     "rewrites": [
       { "source": "/api/:path*", "destination": "https://wellcosting-api.onrender.com/api/:path*" },
       { "source": "/docs", "destination": "https://wellcosting-api.onrender.com/docs" },
       { "source": "/openapi.json", "destination": "https://wellcosting-api.onrender.com/openapi.json" }
     ]
   }
   ```

   Vercel reads `vercel.json` from the **Root Directory** (`frontend/`). The
   rewrite makes `/api/...` requests same-origin from the browser, so the HttpOnly
   refresh cookie (path `/api/v1/auth`, `SameSite=Lax`) works unchanged.
5. Click **Deploy**. Vercel auto-deploys on every push to `main`.
6. Open the deployment URL and sign in (after seeding, §4).

**Custom domain (optional):** *Project → Settings → Domains*, add your domain, and
then add it to the API's `CORS_ORIGINS` on Render (comma-separated). Redeploy the API
after changing environment variables.

---

## 4. First-run administrator (seeding)

A fresh database has no users, so nobody can sign in. Pick one option:

**Option A — `SEED_*` env vars on Render (unattended, works on the free tier):**
set `SEED_ORG_SLUG`, `SEED_ORG_NAME`, `SEED_OWNER_NAME`, `SEED_ADMIN_EMAIL` and
`SEED_ADMIN_PASSWORD` (§2), deploy, and wait for the first boot to log
`Seeded administrator ...`. Then **delete `SEED_ADMIN_PASSWORD`** in the Render
dashboard (Environment → edit) and trigger a redeploy. Verify with
`https://<service>.onrender.com/api/health` → `"admin_seeded":true`.

**Option B — from your laptop against Supabase:**

```sh
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
cd backend
DATABASE_URL='postgresql+psycopg://postgres:<password>@db.<ref>.supabase.co:5432/postgres?sslmode=require' \
SECRET_KEY='<same-as-render>' \
../.venv/bin/alembic upgrade head
DATABASE_URL='...' SECRET_KEY='...' ../.venv/bin/python -m app.seed
```

`python -m app.seed` asks for the workspace, administrator and a password
(12+ characters). `python -m app.seed --check` reports status without changing
anything (exit `0` = admin exists).

**Option C — Render Shell (paid plans):** open the service's **Shell** tab and run
`python -m app.seed`.

Then sign in at your Vercel URL with the **workspace slug**, the administrator
e-mail and the password you chose.

---

## 5. Post-deploy checklist

- [ ] `SECRET_KEY` is a unique random value (≥32 chars), never committed.
- [ ] `SECURE_COOKIES=true` on Render; the app is HTTPS-only end to end.
- [ ] `CORS_ORIGINS` lists the exact Vercel origin(s) — no `*`, since cookies are allowed.
- [ ] `SEED_ADMIN_PASSWORD` deleted from Render after the first boot.
- [ ] Sign-in works and the Overview page loads data through the proxy.
- [ ] `GET /api/health` on Render returns `{"status":"ok","admin_seeded":true}`.
- [ ] Auto-deploy is enabled on both Render and Vercel for branch `main`.
- [ ] Consider: Starter plan on Render (no cold starts), paid Supabase tier
      (no pause), Supabase network restrictions, and a custom domain.

## 6. Troubleshooting

| Symptom | Likely cause |
|---|---|
| Login page shows a seeding hint | No admin yet — run §4; check `admin_seeded` in `/api/health` |
| API calls fail with CORS errors | `CORS_ORIGINS` doesn't exactly match the Vercel origin (scheme + host) |
| Login succeeds but the next call is 401 | `SECURE_COOKIES` mismatch, or the cookie was set on the wrong domain — confirm you're browsing the Vercel URL, not calling Render directly |
| Render deploy fails: `SECRET_KEY` error | Missing/short/default `SECRET_KEY` when using PostgreSQL |
| Database connection errors | Wrong password (URL-encoding!), wrong project ref, or IPv6-only project — see §1 |
| First load very slow | Render free-tier cold start after sleep; expected |
| `405`/`404` on `/api/...` | `frontend/vercel.json` still has the `YOUR-RENDER-SERVICE` placeholder |

## 7. Alternative: calling the API cross-origin (not recommended)

The frontend could instead call Render directly (`VITE_API_URL=https://...onrender.com`)
with the API's CORS enabled. That requires a small code change in
`frontend/src/lib/api.ts` (read `import.meta.env.VITE_API_URL` as the base URL) and
`credentials: 'include'` across origins. The rewrite approach above avoids code
changes and keeps the refresh cookie same-origin, so it is the recommended path.
