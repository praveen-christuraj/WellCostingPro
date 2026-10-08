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

Supabase's [Postgres connection guide](https://supabase.com/docs/guides/database/connecting-to-postgres)
explains the available connection modes; choose **Session pooler** for this
long-running Render API.

1. Sign up at [Supabase](https://supabase.com) and create a **New project**.
   Choose a strong database password and a region close to Render (and your
   users). Save the database password in a password manager; it is not your
   Supabase account password.
2. Wait for the database to finish provisioning. Supabase creates the database;
   the first Render deploy runs this application's Alembic migrations to create
   its tables.
3. In the Supabase project, click **Connect** and select **Session pooler**.
   Copy its URI. Use the session pooler for Render: it is reachable over IPv4
   and supports persistent backend connections. Do not use the **Transaction
   pooler** for this SQLAlchemy application.
4. Convert the copied URI to the SQLAlchemy/psycopg form Render needs:

   ```text
   postgresql+psycopg://<POOLER_USER>:<URL_ENCODED_PASSWORD>@<POOLER_HOST>:5432/postgres?sslmode=require
   ```

   Keep the actual username, host, port, and database name from Supabase's
   copied Session pooler URI. Usually its username includes the project ref
   (for example, `postgres.<PROJECT_REF>`); do not replace it with `postgres`
   unless Supabase shows that exact username. Change only the URI scheme from
   `postgresql://` to `postgresql+psycopg://`, and add `?sslmode=require` (or
   `&sslmode=require` if the URI already has query parameters).

   URL-encode reserved characters in the database password (`@`, `#`, `%`, `/`,
   `?`, `&`, spaces, etc.). For example, `@` becomes `%40`. Do not include the
   angle brackets or placeholder text in the final value.

   A **Direct connection** is also valid if the Render service can reach the
   Supabase direct endpoint (typically IPv6, or IPv4 with Supabase's IPv4
   add-on). The Session pooler is the simpler choice when direct connections
   fail with DNS, IPv6, or network errors. The Transaction pooler (usually
   port `6543`) is intended for short-lived/serverless connections and is not
   the fallback recommended here.

**Supabase notes**

- Check Supabase's current plan limits and pause policy in the dashboard; the
  database must be available when the API starts and handles requests.
- The app enforces tenant isolation in the API layer, not via Row Level
  Security. Only the Render service should know `DATABASE_URL` — never expose it
  to the browser (this deployment keeps it server-side only).
- Optional hardening: **Project Settings → Database → Network Restrictions** to
  allow only Render's outbound IPs (paid Render plans have static IPs; free-tier
  IPs are dynamic, so skip this on the free plan).

---

## 2. Render — FastAPI backend

These settings follow Render's [web service deployment
guide](https://render.com/docs/web-services).

The dashboard method below is the easiest way to get a first deploy working.
The repository's Blueprint is an alternative if you want Render to create the
service from `render.yaml`.

### Option A: Create the service in the dashboard

1. Push the application code to GitHub and make sure the branch you want to
   deploy contains `backend/requirements.txt`, `backend/alembic.ini`,
   `backend/alembic/`, and `backend/app/`.
2. Sign in at [Render](https://render.com). Choose **New → Web Service**, connect
   GitHub if asked, and select the `praveen-christuraj/WellCostingPro`
   repository. Select the branch you intend to deploy (commonly `main`).
3. Set these fields in the service form. The root directory is important: it
   makes all commands run from `backend/`.

   | Setting | Value |
   |---|---|
   | Name | `wellcosting-api` (or another available name; copy the actual URL Render assigns) |
   | Region | Same region as the Supabase project, or the nearest available region |
   | Environment | **Python 3** |
   | Root Directory | `backend` |
   | Build Command | `pip install -r requirements.txt` |
   | Start Command (Free plan) | `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
   | Health Check Path | `/api/health` |
   | Instance plan | Free for testing (sleeps when idle); choose a paid instance for an always-on service |

   Render provides `PORT`; bind Uvicorn to `0.0.0.0` and that port. On a Free
   instance use the combined start command above so migrations run before the
   API process. **Do not put `alembic upgrade head` in both commands.** A paid
   service can instead set **Pre-Deploy Command** to `alembic upgrade head` and
   use `uvicorn app.main:app --host 0.0.0.0 --port $PORT` as its Start Command.
   Pre-deploy migrations are preferable for paid services because they run
   before the new application version starts.
4. In the service form's **Advanced** section, add the environment variables
   from the next section before creating the service. In particular, set the
   `DATABASE_URL` from §1, a `SECRET_KEY`, and `CORS_ORIGINS` to the production
   Vercel origin you plan to use. If you have not created the Vercel project
   yet, use the expected `https://<project>.vercel.app` origin and correct it
   after the first Vercel deployment.
5. Click **Create Web Service**. Watch **Events** and **Logs** in the Render
   dashboard until the deploy is live. Record the actual `https://...onrender.com`
   URL shown for the service; the service name may not be available as typed.

### Option B: Create it from the Blueprint

1. Push the latest repository changes to GitHub. In Render choose **New →
   Blueprint**, connect this repository and branch, and confirm that Render
   found `render.yaml` in the repository root.
2. Review the proposed `wellcosting-api` service and click **Deploy Blueprint**.
   The Blueprint uses the Free-compatible migration/start command described
   above.
3. During initial Blueprint creation, enter the `sync: false` values when
   prompted. For `CORS_ORIGINS`, use the expected production Vercel origin and
   correct it after Vercel's first deployment if needed. Render prompts only on
   the first Blueprint creation; for later changes, edit the service's
   **Environment** page directly.
4. Follow the deploy in the service's Events and Logs. If you already created a
   separate dashboard-managed Render service, do not apply the Blueprint too:
   choose one management method to avoid creating a duplicate service.

### Environment variables for the API

| Variable | Required | Value / how to generate |
|---|---|---|
| `DATABASE_URL` | **Yes** | The Session pooler URI from §1, with the `postgresql+psycopg://` driver prefix and `sslmode=require` |
| `SECRET_KEY` | **Yes** | Generate a unique key with `openssl rand -hex 32`; on Windows PowerShell, `py -c "import secrets; print(secrets.token_hex(32))"` also works. Use at least 32 characters per environment; the app rejects a missing, short, or default key with PostgreSQL. |
| `SECURE_COOKIES` | **Yes** | `true` — Vercel serves HTTPS, and the refresh cookie is set with the `Secure` flag |
| `CORS_ORIGINS` | **Yes** | Exact Vercel origin(s), comma-separated, e.g. `https://wellcosting-pro.vercel.app`. Add custom domains too. No paths or trailing slash. |
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
- **Free-tier cold starts:** Render spins down a Free web service after 15
  minutes without inbound traffic; waking it can take about a minute. The API
  filesystem is ephemeral, so keep the database on Supabase, not local SQLite.
- Verify the deploy at `https://<actual-service-url>.onrender.com/api/health`.
  A successful database-backed check should include `"status":"ok"` and
  `"admin_seeded":false` before provisioning or `true` afterwards. This endpoint
  is a liveness check: if it reports `false`, inspect Render logs as well,
  because an unavailable database can also prevent the owner check.
- Verify migrations in the Render deploy/runtime logs: they should complete
  before Uvicorn starts. If the log says `alembic: command not found`, check
  that `pip install -r requirements.txt` succeeded and that the root directory
  is exactly `backend`.

---

## 3. Vercel — React frontend

1. Sign up at [Vercel](https://vercel.com), choose **Add New → Project**, and
   import the `praveen-christuraj/WellCostingPro` repository. Select the same
   production branch you selected for Render.
2. Configure the project:

   | Setting | Value |
   |---|---|
   | Framework Preset | **Vite** |
   | Root Directory | `frontend` |
   | Build Command | `npm run build` (default) |
   | Output Directory | `dist` (default) |
   | Install Command | `npm ci` (recommended; `package-lock.json` is committed) |
   | Production Branch | The branch you deploy (commonly `main`) |

3. **Environment variables: none are required.** The frontend has no build-time
   configuration — it calls the API with relative `/api` paths.
4. **Point Vercel's proxy at the live Render service.** Edit
   `frontend/vercel.json` in the repository. Replace every
   `YOUR-RENDER-SERVICE.onrender.com` with the actual Render hostname from §2
   (hostname only, no trailing slash), for example:

   ```json
   {
     "rewrites": [
       { "source": "/api/:path*", "destination": "https://wellcosting-api.onrender.com/api/:path*" },
       { "source": "/docs", "destination": "https://wellcosting-api.onrender.com/docs" },
       { "source": "/openapi.json", "destination": "https://wellcosting-api.onrender.com/openapi.json" }
     ]
   }
   ```

   Keep all three rewrites: `/api/...` for the application, `/docs` for API
   documentation, and `/openapi.json` for the schema. Vercel reads this file
   from the project root directory (`frontend/`). See
   [Vercel project configuration](https://vercel.com/docs/project-configuration)
   for details about `vercel.json`.
5. Commit and push this `vercel.json` change to the production branch. Vercel
   auto-deploys when that branch receives a push. A deployment made before this
   change will still contain the placeholder and its API routes will not work.
6. In Vercel, open the project's **Deployments** page and wait for the latest
   deployment to finish. Open the assigned production domain (not a preview
   deployment URL) and record its origin, e.g.
   `https://wellcosting-pro.vercel.app`.
7. Return to Render → service → **Environment**. Set `CORS_ORIGINS` to that
   exact origin (scheme + hostname, with no path/trailing slash); include any
   custom domain as another comma-separated origin. Save and redeploy. No
   `VITE_*` variables are needed in Vercel.
8. Open `https://<your-vercel-domain>/api/health`. It should return the Render
   health response through Vercel's rewrite. Also check
   `https://<your-vercel-domain>/docs` to confirm the API docs rewrite works.

**Custom domain (optional):** *Project → Settings → Domains*, add and verify
your domain. Add its exact HTTPS origin to Render's `CORS_ORIGINS` (comma
separated) and redeploy the API. The `vercel.json` rewrite still targets the
Render service; do not point the browser directly at Render.

---

## 4. First-run administrator (seeding)

A fresh database has no users, so nobody can sign in. Pick one option:

**Option A — `SEED_*` environment variables in Render (recommended for a first
deploy, including Free):** before the first API start, set all five variables:
`SEED_ORG_SLUG`, `SEED_ORG_NAME`, `SEED_OWNER_NAME`, `SEED_ADMIN_EMAIL` and
`SEED_ADMIN_PASSWORD` (§2). Use a workspace slug such as `my-company`, a valid
owner email, and a unique password of at least 12 characters. The API applies
Alembic migrations first, then creates the initial workspace and owner from
these values. Wait for Render logs to report `Seeded administrator ...`, then
**remove `SEED_ADMIN_PASSWORD`** from Render's Environment page and redeploy.
Removing the other four seed values is also recommended. Verify the health
response shows `"admin_seeded":true`.

**Option B — from your computer against Supabase:** use the same Session pooler
`DATABASE_URL` as Render and run the seeding CLI from `backend/`. This requires
Python dependencies installed locally and network access to Supabase. The CLI
asks for the workspace, administrator and password. Do not commit connection
strings or passwords to Git. `python -m app.seed --check` reports status
without changing anything (`0` = administrator present).

**Option C — Render Shell:** if your Render plan provides a Shell, open it for
the API service and run `python -m app.seed`. Shell availability depends on the
service plan; use Option A or B if the Shell tab is unavailable.

Then sign in at your Vercel URL with the **workspace slug**, the administrator
e-mail and the password you chose.

---

## 5. Post-deploy checklist

- [ ] `SECRET_KEY` is a unique random value (≥32 chars), never committed.
- [ ] `SECURE_COOKIES=true` on Render; the app is HTTPS-only end to end.
- [ ] `CORS_ORIGINS` lists the exact Vercel origin(s) — no `*`, since cookies are allowed.
- [ ] `SEED_ADMIN_PASSWORD` deleted from Render after the first boot.
- [ ] Sign-in works and the Overview page loads data through the proxy.
- [ ] `GET /api/health` through both Render and Vercel returns
      `{"status":"ok","admin_seeded":true}`.
- [ ] Auto-deploy is enabled on both Render and Vercel for the selected production branch.
- [ ] Consider a paid Render instance to avoid idle spin-down and review
      Supabase plan limits, network restrictions, and custom-domain needs.

## 6. Troubleshooting

| Symptom | Likely cause |
|---|---|
| Render build says `requirements.txt` is missing | Set Render Root Directory to `backend` (commands are relative to it) |
| API routes return Vercel 404/405 or do not reach Render | Replace the `YOUR-RENDER-SERVICE` placeholder in `frontend/vercel.json`, commit, push, and wait for a fresh Vercel deploy |
| Login page shows a seeding hint | No admin has been provisioned yet; check the Render logs and complete §4 |
| Health response says `admin_seeded:false` | This may mean no owner exists or the database check failed; inspect Render logs and confirm migrations/database connectivity |
| Render logs show `could not translate host name`, timeout, or IPv6/network errors | Use the Supabase Session pooler URI (host/user/port copied from **Connect → Session pooler**) rather than the Direct endpoint; do not use Transaction pooler |
| Render logs show `password authentication failed for user "postgres"` on port `6543` | Render is using the Transaction pooler endpoint and/or a username that does not match the copied pooler URI. In Supabase **Connect → Session pooler**, copy the full connection URI; preserve its generated username (usually `postgres.<PROJECT_REF>`), host, and port `5432`. In Render → service → **Environment**, replace `DATABASE_URL` with that URI using the `postgresql+psycopg://` scheme and `sslmode=require`. URL-encode reserved password characters, save with **Save, rebuild, and deploy**, then inspect the new logs. Do not merely change `6543` to `5432` while keeping the old username or guessed host. |
| Render logs show password authentication failed with another user/port | Re-copy the full connection URI from Supabase **Connect** and use its matching host, port, and username. Confirm the database password is current and reserved characters are URL-encoded. Update `DATABASE_URL` in Render's Environment page and redeploy. |
| Render logs show missing tables / Alembic revision errors | Confirm the start command runs `alembic upgrade head` before Uvicorn, or on a paid instance configure it as Pre-Deploy Command; verify the Render root directory is `backend` |
| Browser reports a CORS error | `CORS_ORIGINS` must contain the exact Vercel origin (scheme + host, no trailing slash); save and redeploy Render |
| Login succeeds but the next call is 401 | `SECURE_COOKIES` mismatch, or the cookie was set on the wrong domain — confirm you're browsing the Vercel URL, not calling Render directly |
| Render deploy fails: `SECRET_KEY` error | Missing/short/default `SECRET_KEY` when using PostgreSQL |
| First load very slow | The Free Render service may be waking from idle; this is expected for that plan |

## 7. Alternative: calling the API cross-origin (not recommended)

The frontend could instead call Render directly (`VITE_API_URL=https://...onrender.com`)
with the API's CORS enabled. That requires a small code change in
`frontend/src/lib/api.ts` (read `import.meta.env.VITE_API_URL` as the base URL) and
`credentials: 'include'` across origins. The rewrite approach above avoids code
changes and keeps the refresh cookie same-origin, so it is the recommended path.
