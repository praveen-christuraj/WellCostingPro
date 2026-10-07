# WellCosting Pro

A tenant-aware foundation for a well-costing SaaS: login and workspace access management first, well-costing features next.

## Stack

React 19 · TypeScript · Material UI 7 · AG Grid Community · ECharts · FastAPI · SQLAlchemy 2 · Alembic · PostgreSQL 16. SQLite is available for local smoke tests when PostgreSQL is not installed.

## Run with PostgreSQL (recommended)

1. Copy `.env.example` to `.env`, and replace **both** secrets with strong random values (`openssl rand -hex 32` for `SECRET_KEY`).
2. `docker compose up --build` (web at http://localhost:8080, API docs at http://localhost:8080/docs).
3. Provision the first workspace and owner, using a password you choose (12+ characters):
   ```sh
   docker compose exec api python -m app.seed --slug my-company --name "My Company" --email owner@example.com --owner-name "Jane Smith"
   ```
4. Sign in with workspace ID `my-company`, owner email and the password you entered. Create users, roles, permissions, and assignments from the UI. No demo users or passwords are shipped.

Production deployments should terminate HTTPS at a trusted proxy and set `SECURE_COOKIES=true`.

## Run locally without Docker

```sh
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
cd backend
../.venv/bin/alembic upgrade head
../.venv/bin/python -m app.seed --slug my-company --name "My Company" --email owner@example.com --owner-name "Jane Smith"
../.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
# in another terminal, from repository root:
cd frontend && npm ci && npm run dev
```

By default the API uses `backend/wellcosting.db` for this local-only path. For PostgreSQL outside Compose, set `DATABASE_URL=postgresql+psycopg://...` and `SECRET_KEY` in `backend/.env` before migrating. Frontend at http://localhost:5173 proxies `/api` to the API; OpenAPI at http://localhost:8000/docs.

## API and policy

- `POST /api/v1/auth/login`, `/refresh`, `/logout`, `/change-password`; `GET /auth/me`.
- `GET /api/v1/overview`; list/create/update users, roles, permissions; assign roles to users and permissions to roles. See `/docs` for complete request schemas.
- Workspace slug is required at sign-in. Resource IDs are checked against the authenticated organization, including assignment IDs. Owner role is provisioned once per organization and cannot be managed via ordinary RBAC endpoints. All other roles and capabilities are editable tenant data; platform capabilities are initially provisioned by `app.seed`.
- Access JWTs expire after 15 minutes and are stored only in memory; refresh sessions rotate, are revocable, and live in an HttpOnly cookie. Password change revokes all sessions and invalidates existing access tokens. API evaluates grants from database on every request, not from stale JWT claims.
- A nonowner cannot grant a role or permission that exceeds their own grants. Permission keys follow `resource:action`.

## Quality and structure

`cd backend && ../.venv/bin/python -m pytest -q` · `cd frontend && npm run build` · `make graph`.

- `backend/app/api`, `models`, `schemas`, `core`, `seed.py` — API, persistence, validation, security, provisioning.
- `backend/alembic/versions` — explicit database migrations.
- `frontend/src/pages`, `components`, `context`, `lib` — routed UI and typed API layer.
- `.agent/` and `AGENTS.md` — committed Graphify tool, architecture graph, durable AI memory and agent workflows; not in `.gitignore`.
- `docs/ci-template.yml` — backend test/migration and frontend build CI template; copy to `.github/workflows/ci.yml` when a GitHub connection with workflow permissions is available.

### Reference projects

Architecture and dashboard patterns were reviewed from [fastapi-admin-v4](https://github.com/lijianqiao/fastapi-admin-v4), [full-stack-fastapi-template](https://github.com/fastapi/full-stack-fastapi-template), [react-admin-dashboard](https://github.com/kotenkodev/react-admin-dashboard), [Admin_Dashboard](https://github.com/tripathipawan/Admin_Dashboard) and [mui-admin-dashboard](https://github.com/JoelEmanuelNilsson/mui-admin-dashboard). This is an original implementation, not a copy of their code.

### Production follow-ups

This is a **foundation**, not a claim of complete production readiness: add invitations/password-reset delivery, MFA/SSO, audit history, distributed rate limiting, server-side pagination, backup/restore, observability, PostgreSQL integration tests, and costing domain workflows before a public SaaS launch. Use HTTPS, strong unique secrets, secure cookies and deployment-specific CORS; review RLS/tenant isolation strategy for multi-tenant compliance needs.
