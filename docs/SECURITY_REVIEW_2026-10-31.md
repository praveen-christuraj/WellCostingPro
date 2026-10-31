# Security review register (WCP-01 … WCP-16) — 31 October 2026

> **Status: verified register, superseded as the handover document.**
> Use [`SECURITY_AUDIT_FINAL.md`](SECURITY_AUDIT_FINAL.md) for the IT handover,
> the 24-item disposition and the password lifecycle. This page keeps the WCP
> identifiers and is retained as the audit trail.
>
> **Important correction.** Several items below were written as if the mitigation
> were already in the code. When the repository's own hardening suite was run on
> the untouched branch, **12 of its 22 cases failed** — required JWT claims, the
> Origin guard, `Cache-Control: no-store`, forwarded-header-proof throttling, the
> reset-verification budget, 422 input stripping, exact-origin CORS, production
> fail-closed validation and the `IntegrityError` handler were absent. So were:
> removal of `xlsx@0.18.5`, formula neutralisation in `frontend/src/lib/export.ts`,
> exclusion of credential tables from archives, the non-root API image, the nginx
> and Vercel header sets, the `/overview` capability guard, and any password-age
> expiry. Those gaps are now implemented and covered by tests; see
> `SECURITY_VALIDATION.md` for the executed evidence. Treat this register as
> "what was intended and is now true", not as the earlier state of the code.

## Scope and assurance

Source review of the FastAPI/SQLAlchemy backend, React frontend, authentication/RBAC,
public endpoints, relational reporting/database-browser paths, backup/import/restore,
file handling, configuration and deployment templates. Dependency checks used `npm audit`
and `pip-audit`; static Python checks used Bandit. Existing business/tenant tests and
new abuse-case tests supplement manual inspection. OWASP ASVS and the OWASP Top 10
were used as review guides, **not as a certification claim**.

This is not a complete penetration test or a guarantee of absence of vulnerabilities.
Production infrastructure, external identity systems, network controls, real production
logs/data, PostgreSQL concurrency, container image CVEs, browser end-to-end interaction,
and a deployed DAST assessment have not been verified here. Do not mark deployment
approved until IT completes the release gates below.

## Verified findings and changes

Severity is a source-review assessment, not a measured CVSS score. Dependency advisory
severity does not establish that every vulnerable library feature was reachable here.

| ID | Severity | Evidence and mitigation |
|---|---|---|
| WCP-01 | Medium | `api/deps.py` verified JWT signatures/type but did not require `exp`; a correctly signed token without expiry was accepted. Require expiry, subject, tenant, token type and version claims. Algorithm remains explicitly HS256. This is defense-in-depth: exploiting it requires an otherwise valid signed non-expiring token; it is not an unsigned-token or signing bypass. |
| WCP-02 | High | `api/security.py` and `services/audit.py` trusted arbitrary `X-Forwarded-For`; rotating that header bypassed recovery throttling and forged audit addresses. Use ASGI connection identity; trusted proxy processing belongs in Uvicorn/edge configuration. |
| WCP-03 | High | `services/backup.py` exported all columns including password hashes/history and restored users/roles/permissions from uploaded data. Exclude and preserve account, credential and RBAC tables. Existing archives cannot overwrite them. Authentication recovery is now an IT-managed procedure, not a business-archive restore. |
| WCP-04 | High | Archive validation trusted the workspace in the manifest; row organization IDs and cross-workspace FK targets were not independently checked. Reject foreign-tenant rows/references during transactional application; preserve current accounts and permissions. |
| WCP-05 | High | Installed `xlsx` 0.18.5 had prototype-pollution and ReDoS advisories without an npm fix. Replace it with `read-excel-file`, `write-excel-file`, and Papa Parse. Update DOMPurify (PDF transitive dependency), which had critical/high advisory matches. See advisory links below. |
| WCP-06 | Medium | Login lacked a client-wide budget (unknown accounts bypassed account lockout); reset-code checks and password changes lacked attempt limits. Add database-backed per-client/action budgets, retaining account lockouts and the existing recovery-request limit. Strict concurrent limits still require edge rate limiting. |
| WCP-07 | Medium | CSV exports in `report_engine.py` and frontend `lib/export.ts` emitted formula-like text without neutralization; database export missed `-` and whitespace prefixes. Centralize backend text protection and protect frontend CSV cells/headers/templates. XLSX output uses explicit string cells. |
| WCP-08 | Medium | Gzip archives were bounded only by compressed size; unbounded readline/iteration permitted inflation/resource exhaustion. Bound expanded content to 512 MiB and individual records to 16 MiB; validate manifest/record/trailer shapes and counts. Limits also apply during transactional restore. |
| WCP-09 | Medium | Credentialed CORS configuration accepted arbitrary strings, and SQLite could use a public default JWT secret. Validate exact HTTP(S) origins, reject wildcards/paths/userinfo; production requires HTTPS, secure cookies and an explicit strong-length key regardless of database. Unconfigured SQLite development uses an ephemeral random key. |
| WCP-10 | Medium | No explicit Origin validation on cookie-bearing auth writes (SameSite alone is not a complete same-site/subdomain CSRF defense). Reject unexpected browser Origins on authentication writes. Non-browser requests without Origin remain supported. |
| WCP-11 | Medium | Uploaded document MIME was client-controlled, inline viewing was unrestricted, and file size was checked after an unbounded read. Bound reads to limit+1; determine preview MIME from PDF/PNG/JPEG signatures, otherwise force octet-stream attachment. This is not antivirus/content-disarm scanning. |
| WCP-12 | Medium | Exception/SQL logs could include bound values; backup errors stored raw exception strings; default validation errors echoed rejected input. Hide SQL parameters; avoid full exception formatting in application fallback/backup handlers; store generic unexpected backup errors; strip input/context from validation responses. IT must also configure framework/proxy log redaction. |
| WCP-13 | Low | Public health revealed whether the first administrator existed. Remove setup-state disclosure, keep minimal liveness/version contract. Production disables Swagger/ReDoc/OpenAPI routes. |
| WCP-14 | Low | Concurrent database conflicts could become unhandled 500s. Map otherwise unhandled IntegrityError to a generic HTTP 409 without SQL details. Existing scoped conflict handlers remain. |
| WCP-15 | Low | API headers did not protect the separately served SPA, and sensitive responses could be cached. Add SPA headers/CSP in Nginx and Vercel, add API no-store, run API container as a non-root user, create new backup directories/files with restrictive permissions. |

| WCP-17 | High | The Security Centre guarded Owner accounts only for `lock`. A delegated `security:password-reset` holder could issue a reset code for, force a change on, or revoke the sessions of an Owner — then sign in as that Owner. The bulk endpoint repeated the hole for every action but `lock`. Mitigated with a single `ensure_can_act_on()` guard across all six single-account actions and per target in bulk. |
| WCP-16 | Medium | Administrators could configure the same archive folder across workspaces; workspace-local backup numbers and second-resolution filenames could collide and overwrite another archive. Include the globally unique job ID in generated/imported filenames; preserve existing registered paths. |

### Dependency advisory references

- SheetJS: https://github.com/advisories/GHSA-4r6h-8v6p-xvw6 and https://github.com/advisories/GHSA-5pgg-2g8v-p4x9
- DOMPurify: https://github.com/advisories/GHSA-cg2g-xh64-v4q7, https://github.com/advisories/GHSA-mrv2-3pqr-j5jr and https://github.com/advisories/GHSA-c6gr-qvv4-5v3f

The initial frontend audit matched two packages (one critical, one high). Final npm audit
reported zero known advisories. `pip-audit -r backend/requirements.txt` reported zero
known advisories in its 43-package resolution. `backend/requirements.lock` records that
resolution and is used by the API Dockerfile and Render build; npm's lockfile is updated.
Rerun both audits for each release; zero known advisories does not imply safe dependencies.

Bandit findings were manually triaged: its medium SQL-injection matches in rig/well,
AFE, catalogue and daily-cost services were f-string **error messages**, not executed
SQL. Other matches were the literal token-type label `bearer`, consistency/invariant
asserts and exception-handling branches. These were not treated as verified SQL injection
or hardcoded-password findings. SQL queries reviewed use SQLAlchemy expressions and
reflected, allow-listed identifiers; this does not establish exhaustive query safety.

## Disposition of your previous 24-item checklist

| Previous item | Result in this application |
|---|---|
| 1 CORS misconfiguration | Configuration validation and production fail-closed checks added (WCP-09). |
| 2 Hardcoded admin backdoor | No username/email bypass found in reviewed auth, bootstrap or provisioning; owner is a persisted protected role, not a special username. |
| 3 JWT type/session confusion | Access type was already checked; required claims and refresh single-use concurrency protection added. |
| 4 Logout refresh revocation | Already deletes the stored refresh session and cookie. Access JWTs intentionally remain valid for their short lifetime; use security-centre revoke/lock for incident containment. |
| 5 Missing 2FA throttling | No native MFA/2FA feature exists. Password/recovery endpoint budgets improved; MFA remains a deployment/product requirement. |
| 6 Password policy | Shared strength validation and password history already exist; login/current-password input lengths now bounded. |
| 7 Location scope | This application uses workspace tenants, not a location entitlement model. Existing RBAC/tenant regressions plus backup row/FK validation cover tested boundaries. A new location model requires explicit product requirements. |
| 8 Backup traversal | Root-resolved path containment already exists. Retained it; added file permissions and hostile archive checks. Symlink-safe OS storage/access controls remain IT's responsibility. |
| 9 Sensitive logs | WCP-12; database, ASGI, proxy and central logging need operational redaction review too. |
| 10 Calibration ranges | No calibration module. Typed decimal/quantity models and existing module validation tests are present; this is not a proof of every business range. |
| 11 Browser localStorage tokens | Access token already memory-only; refresh token already HttpOnly cookie. LocalStorage contains theme/navigation/scope preferences, not credentials. |
| 12 DB passwords in CLI args | No database-dump subprocess/CLI credential path found; database access uses SQLAlchemy URL from environment. Environment secrets still need platform protection. |
| 13 Formula injection | WCP-07. |
| 14 SQL f-strings | Reviewed static flags were validation messages, not SQL execution. No arbitrary SQL console exists. |
| 15 HTML injection | React text rendering used in reviewed frontend; no raw HTML sinks found. Document MIME/inline boundary hardened (WCP-11). |
| 16 Naive lockout datetime | Existing lockout/recovery code normalizes database timestamps to UTC; retained and exercised via auth/security tests. |
| 17 API insecure fallback | Browser already uses relative `/api/v1`; no browser localhost fallback. Vercel still uses a deployment-specific HTTPS backend rewrite: IT must replace it for its environment. |
| 18 Unsanitized errors | WCP-12; errors render as text, rejected secret input is not echoed. |
| 19 Integrity race | WCP-14. Database uniqueness remains the final guard. PostgreSQL load/concurrency test is a release gate. |
| 20 RBAC diagnostics | **Fixed.** `GET /api/v1/overview` previously returned account, role and permission counts to any signed-in user, and the SPA dashboard route was unguarded. The endpoint now requires one of `users:read`, `roles:read`, `permissions:read`, the UI route uses the same guard, and `/security/overview` stays capability-gated. |
| 21 Never-expiring admin password | **Fixed.** There was no password age at all. `PASSWORD_MAX_AGE_DAYS` (default 90, `0` disables deliberately) now applies to every account, including Owner; `users.password_expires_at` is written on change and derived for legacy rows. An expired password authenticates once, then confines the session to `/auth/me`, `/auth/change-password`, `/auth/logout`, `/auth/logout-all` and `/auth/refresh` until a compliant replacement is saved, and notifies the account holder once. Security Centre shows expiry state and filters. |
| 22 Fast hash KDF | Passwords use Argon2. SHA-256 is used for high-entropy random refresh/reset-token lookup, not human-password derivation; it is appropriate for those tokens. No custom encryption KDF found. |
| 23 Headers | WCP-15; TLS/HSTS also needs verification at the public edge. |
| 24 Public diagnostics | WCP-13. Minimal health remains intentionally public. |

## Deployment gates — required before production

1. **Back up using IT tooling**, encrypt backups and test recovery on PostgreSQL. Application
   archives now preserve users, roles, permissions, password history and recovery state.
   They are **business-data recovery**, not a full disaster-recovery replacement. Quarantine
   old archives (they may contain credential hashes), restrict their access and expire them
   under retention policy. Assess credential-reset needs if any old archive was exposed.
2. Use `ENVIRONMENT=production`, a randomly generated `SECRET_KEY` (at least 32 characters,
   preferably `openssl rand -hex 32`), `SECURE_COOKIES=true`, and exact HTTPS `CORS_ORIGINS`.
   The default Compose configuration remains for local HTTP development, not production.
   Changing SECRET_KEY invalidates JWTs and changes rate-limit hashes; coordinate rotation.
3. Run database migrations to the current head (`alembic upgrade head`). The head is now
   **`b7c1d9e4f2a8`** (password expiry and refresh-token replay detection); the previously
   documented `f9a2c7d4e611` is the parent revision. Back up first. Remove
   `SEED_ADMIN_PASSWORD` after first boot; restrict initial Owner access.
4. Terminate TLS and redirect HTTP at your approved edge. Enforce HSTS there. Overwrite
   forwarded headers there as well (`frontend/proxy_params_wcp.conf` does this for the
   bundled nginx), keep direct API access closed, and set `TRUSTED_PROXY_IPS` to the
   private proxy CIDR only — never `*`. Audit addresses and throttle keys come from
   `core/request_security.py`, which believes a forwarded header only when the connecting
   peer is in that list. If the proxy is not listed, every user shares one budget; if the
   list is too wide, spoofing returns.
5. Apply atomic distributed edge rate limits to login, refresh, forgot/reset-password and
   password change. The DB-backed app budgets are shared across workers but count+insert
   is not strictly atomic, and IP-only limits do not stop distributed credential stuffing.
   Size limits for multipart requests must be set before parsing at the edge. Nginx defaults
   to 20 MiB here; approve a separate authenticated backup-upload limit if needed (archives
   are capped at 512 MiB expanded/16 MiB per record). Existing larger archives can be refused.
6. Place database/backup storage on private networks/volumes. Apply least-privilege DB roles,
   TLS on DB connections, volume encryption, restricted filesystem ownership, malware scanning
   for attachments and centralized log redaction/retention. Container hardening added here
   is not a complete container security assessment; scan OS images and pin approved digests.
7. Review every privileged capability. Database-browser, report-builder and backup access
   are broad workspace-data privileges even if a user lacks ordinary module read rights.
   Do not grant them as convenience roles. Owner is tenant administrator. There is no native
   MFA/SSO/SCIM, breached-password service or tamper-evident external audit archive.
8. Frontend parser supports **.xlsx and .csv, not legacy .xls**. Test imports, date/number
   formats, quotes, multiline cells, formula text, downloads and PDFs with real IT fixtures.
   Import limits are 10 MiB/10,000 rows/200 columns after decoding; a malicious compressed
   XLSX is preflight-checked against a 50 MiB ZIP directory expansion budget (2,000 entries,
   no ZIP64/encryption). Hostile archives can lie about sizes; isolated web workers/timeouts
   and further decoder-level limits remain advisable. Do not open untrusted workbooks.
9. Verify CSP in real browsers against charts, PDF/download flows, document previews and
   both hosting templates. Styles currently require `unsafe-inline` for MUI/grid styling;
   scripts do not. Do not weaken script CSP to resolve unrelated deployment errors.
10. Run full tests against a disposable **PostgreSQL** instance (`TEST_DATABASE_URL`),
    concurrency tests (refresh rotation, reset consumption, account/asset creation), an
    authenticated cross-tenant IDOR test, proxy-spoofing tests, DAST and an independent
    penetration test. Never run these tests against production: fixtures drop all tables.
11. Add the checks below to the deployment pipeline and schedule dependency/container scans.

## Reproducible verification commands

```sh
python -m venv .venv
.venv/bin/pip install -r backend/requirements.lock
(cd backend && ../.venv/bin/pytest -q)
npm ci --prefix frontend
npm run test:security --prefix frontend
npm run build --prefix frontend
npm audit --prefix frontend --audit-level=low
# Install scanners in a separate tools environment in CI:
pip-audit -r backend/requirements.lock
bandit -r backend/app
```

See `SECURITY_VALIDATION.md` for the final executed results and remaining untested areas.
