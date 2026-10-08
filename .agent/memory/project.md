# Durable project memory

## Product scope
WellCosting Pro is a tenant-aware SaaS foundation. This first increment covers authentication, user/role/permission CRUD, assignments, and a live overview. Well costing domain entities are **not implemented yet**.

## Architecture decisions
- React 19 + MUI 7 + AG Grid 35 + ECharts 6 + Vite, routed in `frontend/src/App.tsx`.
- FastAPI + SQLAlchemy 2 + Alembic; PostgreSQL for Compose/deployment, SQLite only for lightweight local development and tests.
- Organization IDs scope all RBAC records; never accept an organization ID in a management request. Authentication uses workspace slug + email + password.
- Access JWT stays in browser memory; rotating opaque refresh tokens are hashed in DB and sent as HttpOnly SameSite cookies. A password change revokes sessions and increments token version.
- API is the authorization authority. Client-side `can()` only hides controls. Owner role is immutable and assigned only by provisioning to prevent lockout. Nonowners cannot grant access they don't have.
- Capability keys use `resource:action`; baseline API capabilities are provisioned per organization, and custom capabilities are tenant data.
- Migrations are explicit Alembic revisions. Do not use `create_all` in the app runtime.
- The owner account is the platform administrator. On a new device the database is empty, so at startup the API detects the missing owner and asks the operator to create one (`app/bootstrap.py` + prompts in `app/services/console.py`, provisioning in `app/services/provisioning.py`, schema state in `app/core/migrations.py`). It never invents credentials, never writes to an existing tenant, never creates tables behind Alembic and never blocks a non-interactive process; `SEED_*` variables cover unattended first boots and `BOOTSTRAP_ADMIN_ON_STARTUP=false` disables the check. `python -m app.seed` is the same flow as a CLI, `--check` exits 0 admin present / 1 missing / 2 unmigrated / 3 failed.

## Deployment (Vercel + Render + Supabase)
- Production topology: Vercel serves the static frontend; `frontend/vercel.json` rewrites `/api/*` (plus `/docs`, `/openapi.json`) to the Render-hosted FastAPI service, so the SPA keeps relative `/api` calls and the HttpOnly refresh cookie stays same-origin. No `VITE_*` variables are needed.
- Render runs the API (Python runtime, rootDir `backend`) with `DATABASE_URL` pointing at Supabase Postgres (prefer the shared session pooler on port 5432 for IPv4-compatible persistent connections; use the host and username copied from Supabase, `postgresql+psycopg://` + `sslmode=require`), a unique `SECRET_KEY` (>=32 chars), `SECURE_COOKIES=true`, and `CORS_ORIGINS` set to the exact Vercel origin(s). The Free Blueprint runs Alembic migrations in its single-process start command; paid services can use a pre-deploy migration command (see `render.yaml` and `docs/deployment.md`).
- First boot seeds the owner from `SEED_*` env vars (password removed after seeding) or via `python -m app.seed` run against the Supabase URL.
- Guide: `docs/deployment.md`; blueprint: `render.yaml`.

## Next engineering priorities
Well/project/cost domain model, invitation and password reset email flow, SSO/MFA, structured audit trail, paginated server-side grids, stronger distributed rate limiting, background jobs, billing and tenant lifecycle automation, observability, PostgreSQL integration tests and deployment hardening. Do not represent these as shipped.

## Verification
`cd backend && ../.venv/bin/python -m pytest -q`; `cd frontend && npm run build`; `make graph`.
