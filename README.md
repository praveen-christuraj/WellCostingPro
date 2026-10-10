# WellCosting Pro

A tenant-aware foundation for a well-costing SaaS: login, workspace access management, and well-costing master reference data, with costing workflows next.

## Stack

React 19 · TypeScript · Material UI 7 · AG Grid Community · ECharts · FastAPI · SQLAlchemy 2 · Alembic · PostgreSQL 16. SQLite is available for local smoke tests when PostgreSQL is not installed.

## Run with PostgreSQL (recommended)

1. Copy `.env.example` to `.env`, and replace **both** secrets with strong random values (`openssl rand -hex 32` for `SECRET_KEY`).
2. `docker compose up --build` (web at http://localhost:8080, API docs at http://localhost:8080/docs).
3. Provision the first workspace and owner. This asks for the workspace, the administrator and a password you choose (12+ characters), and runs migrations first if they are pending:
   ```sh
   docker compose exec -it api python -m app.seed
   ```
   The API asks the same questions at startup when it has a terminal. For an unattended first boot set the `SEED_*` variables in `.env` instead — see [First-run administrator](#first-run-administrator).
4. Sign in with workspace ID `my-company`, owner email and the password you entered. Create users, roles, permissions, and assignments from the UI. No demo users or passwords are shipped.

Production deployments should terminate HTTPS at a trusted proxy and set `SECURE_COOKIES=true`.

## Run locally without Docker

```sh
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
cd backend
../.venv/bin/alembic upgrade head
../.venv/bin/python -m app.seed          # guided: workspace, owner and password; offers to migrate first
../.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
# in another terminal, from repository root:
cd frontend && npm ci && npm run dev
```

By default the API uses `backend/wellcosting.db` for this local-only path. For PostgreSQL outside Compose, set `DATABASE_URL=postgresql+psycopg://...` and `SECRET_KEY` in `backend/.env` before migrating. Frontend at http://localhost:5173 proxies `/api` to the API; OpenAPI at http://localhost:8000/docs. `make seed-admin` and `make check-admin` wrap the commands below.

## First-run administrator

A fresh clone has an empty database, so nobody can sign in. Rather than shipping demo credentials, the backend detects that state and asks for the first administrator:

- **At API startup** — when no owner account exists, the API logs what to run, and on an interactive terminal it asks directly: offer to run pending migrations, then the workspace ID, workspace name, administrator name, e-mail and a password entered twice and never echoed. Declining changes nothing.
- **From the CLI** — `python -m app.seed` runs that same flow. `python -m app.seed --check` only reports status for scripts and container entrypoints: exit `0` an administrator exists, `1` none exists, `2` the schema is not migrated, `3` provisioning failed.
- **Unattended** — set `SEED_ORG_SLUG`, `SEED_ORG_NAME`, `SEED_OWNER_NAME`, `SEED_ADMIN_EMAIL` and `SEED_ADMIN_PASSWORD`; the first start seeds from them (`python -m app.seed --from-env` does it explicitly). Clear the password again afterwards.
- **Explicit** — `python -m app.seed --slug my-company --name "My Company" --email owner@example.com --owner-name "Jane Smith"` prompts only for the password. Add `--attach-existing` to give a workspace whose owner was lost a new administrator.
- **In the UI** — `GET /api/health` returns `admin_seeded`, and the sign-in page explains what to run when it is `false`.

Seeding is idempotent (it never touches an existing owner), never creates tables behind Alembic, and is switched off entirely by `BOOTSTRAP_ADMIN_ON_STARTUP=false`. Non-interactive processes are never blocked waiting for input.

## API and policy

- `GET /api/health` reports liveness plus `admin_seeded`; `POST /api/v1/auth/login`, `/refresh`, `/logout`, `/change-password`; `GET /auth/me`.
- `GET /api/v1/overview`; list/create/update users, roles, permissions; assign roles to users and permissions to roles. See `/docs` for complete request schemas.
- Master Data Management covers UOM, Currency, Phases, Hole Sections, Activities, and a typed Services register. Services receive workspace-scoped auto-generated codes and carry a category (Drilling Services or Completion Services), provider type (In House Services or Third Party Services), optional vendor link, and description; third-party providers must reference a non-deleted vendor in the same workspace. Names are unique case-insensitively per workspace, and active service assignments protect vendors from soft deletion. The service register includes category/provider KPIs, quick and advanced filters, date-range filtering, import preview for xlsx/csv (including legacy Inhouse/3rd Party labels), and csv/xlsx/PDF export. Each organization gets isolated records, an overview dashboard, checkbox-based bulk actions, and a Deleted Entries view. Normal deletion is soft-only; restore or permanently delete from Deleted Entries. The `master-data:read`, `master-data:create`, `master-data:update`, `master-data:delete`, `master-data:restore`, `master-data:permanent-delete`, `master-data:import`, and `master-data:export` capabilities guard the API.
- Master Data Management also carries **Vendors** and **PO/SO Orders**. Add the vendor first (code, category, contact, e-mail, phone, website, country, tax/registration number, address, credit terms, and an active/inactive/blocked status); the category list includes Drilling and Completions alongside the other supply/service categories. Then file its purchase and service orders against it. Orders store **no prices or values**: the scanned PO/SO copy you attach is the reference. Each order number keeps an amendment chain — revision 0 is the original, later revisions are amendments raised with a mandatory reason, the newest revision is flagged as the one to quote, and files can be carried forward. Attachments support several files per revision (kind, label, note, SHA-256 duplicate check, uploader, preview/download), bulk attach by file name (`PO-2026-001_Rev1.pdf`), soft removal with restore, and audited downloads. Blocked vendors are refused new orders; vendors with active orders or active service assignments cannot be deleted. `master-data:document-upload`, `master-data:document-download` and `master-data:document-delete` gate file custody separately. Files are stored in the workspace database (capped by `DOCUMENT_MAX_SIZE_MB`, default 15 MB) because the deployed API filesystem is ephemeral.
- Workspace slug is required at sign-in. Resource IDs are checked against the authenticated organization, including assignment IDs. Owner role is provisioned once per organization and cannot be managed via ordinary RBAC endpoints. All other roles and capabilities are editable tenant data; platform capabilities are initially provisioned by `app.seed` and the master-data migration.
- Access JWTs expire after 15 minutes and are stored only in memory; refresh sessions rotate, are revocable, and live in an HttpOnly cookie. Password change revokes all sessions and invalidates existing access tokens. API evaluates grants from database on every request, not from stale JWT claims.
- A nonowner cannot grant a role or permission that exceeds their own grants. Permission keys follow `resource:action`.

## Quality and structure

`cd backend && ../.venv/bin/python -m pytest -q` · `cd frontend && npm run build` · `make graph`.

- `backend/app/api`, `models`, `schemas`, `core`, `services`, `seed.py`, `bootstrap.py` — API, persistence, validation, security, provisioning and the first-run administrator bootstrap.
- `backend/alembic/versions` — explicit database migrations.
- `frontend/src/pages`, `components`, `context`, `lib` — routed UI and typed API layer.
- `.agent/` and `AGENTS.md` — committed Graphify tool, architecture graph, durable AI memory and agent workflows; not in `.gitignore`.
- `docs/ci-template.yml` — backend test/migration and frontend build CI template; copy to `.github/workflows/ci.yml` when a GitHub connection with workflow permissions is available.

### Reference projects

Master Data workflows — including the legacy Services, Vendors/Suppliers and PO/SO Orders tabs — were reviewed from [Well-Costing](https://github.com/praveen-christuraj/Well-Costing), then re-designed for this application's tenant-scoped SQLAlchemy models, RBAC, API, MUI and AG Grid structure; the legacy tab UI and its single-attachment/value-based order model were not copied. Vendors and PO/SO Orders here add vendor lifecycle states, multi-revision amendment chains, and multi-file attachments stored per revision. Architecture and dashboard patterns were also reviewed from [fastapi-admin-v4](https://github.com/lijianqiao/fastapi-admin-v4), [full-stack-fastapi-template](https://github.com/fastapi/full-stack-fastapi-template), [react-admin-dashboard](https://github.com/kotenkodev/react-admin-dashboard), [Admin_Dashboard](https://github.com/tripathipawan/Admin_Dashboard) and [mui-admin-dashboard](https://github.com/JoelEmanuelNilsson/mui-admin-dashboard). This is an original implementation, not a copy of their code.

### Production follow-ups

This is a **foundation**, not a claim of complete production readiness: add invitations/password-reset delivery, MFA/SSO, audit history, distributed rate limiting, server-side pagination, backup/restore, observability, PostgreSQL integration tests, and costing domain workflows before a public SaaS launch. Use HTTPS, strong unique secrets, secure cookies and deployment-specific CORS; review RLS/tenant isolation strategy for multi-tenant compliance needs.
