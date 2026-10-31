# WellCostIQ security audit and IT handover — 31 October 2026

This is the controlling security document for the current codebase. It replaces the
earlier `SECURITY_REVIEW_2026-10-31.md`, whose "verified findings" section described
controls that were **not present in the code** at the time of handover (see
§3). Every statement below was checked against the source in this repository and,
where practical, against an executed test.

It is a source-level audit plus automated abuse-case testing. It is **not** a
penetration test, a DAST scan, a PostgreSQL concurrency proof, or a statement that
the application is vulnerability-free. §9 lists what IT must still do before
production.

---

## 1. Scope

| Area | Reviewed |
|---|---|
| Backend | FastAPI application (`backend/app`), configuration, authentication, session handling, password lifecycle, RBAC, audit, recovery workflows, backup/restore, document handling, CSV/report export, database browser, migrations |
| Frontend | `frontend/src` (token handling, session recovery, password screens, export/import), `nginx.conf`, `vercel.json`, Dockerfiles |
| Deployment | `docker-compose.yml`, `render.yaml`, `.env.example` files, GitHub Actions workflow |
| Dependencies | `requirements.txt` / `requirements.lock`, `package.json` / `package-lock.json` |
| Data model | Alembic history up to the new revision `b7c1d9e4f2a8` |

Not reviewed here: infrastructure outside the repository, the identity provider (there
is none), production logs and data, TLS termination, network segmentation, container
image CVEs and the planned PostgreSQL deployment.

---

## 2. Executive summary

The application already had a good structural baseline: tenant-scoped queries, an
immutable owner role, server-side permission checks, Argon2 password hashing,
short-lived access tokens, HttpOnly refresh cookies, hash-only reset codes, an audit
trail and a two-person backup restore.

The audit found **27 defects**, of which seven were High. The most serious were not
missing features but **missing enforcement**: controls described in the previous
handover document had never been implemented, and the repository's own
`tests/test_security_hardening.py` proved it — 12 of its 22 cases failed on the
untouched code.

All 26 are remediated in this branch. The evidence, the exact behaviour that changed,
and the residual risks are below.

---

## 3. The central finding: documentation asserted controls that did not exist

At the start of the review the hardening suite was executed against the untouched
branch:

```
$ cd backend && ../.venv/bin/python -m pytest tests/test_security_hardening.py -q
12 failed, 10 passed, 9 warnings in 26.51s
```

The failures were not cosmetic. Each corresponds to a claimed control that the code
did not implement:

| Test that failed | What was actually true |
|---|---|
| `test_jwt_requires_expiry_and_access_type` | `jwt.decode` verified signatures but never **required** `exp`, `sub`, `org`, `type` or `ver`; a signed token without expiry was accepted |
| `test_origin_guard_and_no_store` | No `Cache-Control: no-store`; no Origin check on cookie-bearing auth writes; `/api/health` returned `admin_seeded` |
| `test_public_throttle_cannot_be_bypassed_with_forwarding_headers` | `api/security.py` and `services/audit.py` read `X-Forwarded-For` directly, so rotating the header reset the recovery budget and forged audit addresses |
| `test_reset_verification_is_throttled` | Reset-code verification had no attempt budget |
| `test_validation_does_not_echo_secrets` | FastAPI's default 422 body echoed the rejected password in `detail[0].input` |
| `test_cors_rejects_non_origins[...]` (5 cases) | `CORS_ORIGINS=*` was accepted with `allow_credentials=True` |
| `test_production_fails_closed` | `ENVIRONMENT` did not exist; a placeholder `SECRET_KEY` with SQLite was accepted as "production"; secure cookies were optional |
| `test_database_integrity_errors_are_generic_conflicts` | No `IntegrityError` handler existed (`app.main.integrity_error` was an ImportError) |

The same was true outside that file:

* `frontend/package.json` still shipped `xlsx@0.18.5` (known prototype-pollution and
  ReDoS advisories) and `export.ts` performed **no** formula neutralisation, while the
  handover claimed both were replaced;
* `app/core/spreadsheets.py` contained a correct `safe_csv_cell()` that **nothing
  imported** — the tests tested the helper, not the export path;
* `backend/Dockerfile` ran as root; `frontend/nginx.conf` sent no security headers and
  proxied `/docs` and `/openapi.json` publicly;
* backup archives still contained `users` (password hashes), `password_history`,
  reset requests and the RBAC tables.

**Practical consequence for IT:** do not accept a prior security document as evidence.
Run the commands in §8 against the artefact you deploy.

---

## 4. Findings and remediation

Severity is an engineering assessment of exploitability and impact in this
application, not a measured CVSS score.

| ID | Severity | Finding and evidence | Remediation |
|---|---|---|---|
| **F-01** | High | Recovery throttling and audit IPs trusted `X-Forwarded-For` (`api/security.py:49`, `services/audit.py:16`). One attacker could rotate the header to reset the 5-per-15-minute budget and poison the audit trail. | `core/request_security.py` is the only source of client identity. Headers are believed only when the connecting peer is inside `TRUSTED_PROXY_IPS`, and then the rightmost non-proxy hop is used. Audit and both recovery endpoints call it. |
| **F-02** | High | Archives exported `users` (Argon2 hashes), `password_history`, `password_reset_requests`, `password_reset_attempts`, `roles`, `permissions` and their link tables (`services/backup.py:76`). A restore would also roll credentials and grants back to the archive's state. | `CREDENTIAL_TABLES` is excluded from the plan and preserved during restore. Archives are business-data copies, never credential copies. Old archives cannot overwrite accounts. |
| **F-03** | High | CORS accepted any string including `*` with credentials, and production had no fail-closed checks (`core/config.py:18`, `main.py:39`). | CORS entries are parsed as exact `scheme://host[:port]`; wildcards, paths, credentials and `null` are rejected at startup. Production requires HTTPS origins, `SECURE_COOKIES=true` and a non-placeholder `SECRET_KEY` of ≥32 characters, regardless of database type. |
| **F-04** | High | Uploaded PO/SO documents were served with the **client-supplied** `Content-Type` and could be shown inline (`api/vendor_master.py`). A `.pdf` containing HTML with `Content-Type: text/html` executed script on the API origin. | MIME is derived from file signatures; only verified PDF/JPEG/PNG/GIF may render inline; everything else is `application/octet-stream` as an attachment with `CSP: default-src 'none'; sandbox`. |
| **F-05** | High | Login had no per-client budget, so unknown accounts bypassed account lockout entirely; reset-code verification and password changes had no attempt limit. | One shared `throttle()` ledger applied to login (30/15 min), forgot-password (5), reset-code verification (10) and change-password (10). Account lockout remains at 5 failures / 15 minutes and is configurable. |
| **F-06** | High | `xlsx@0.18.5` remained in `package.json` and `doMPurify` (via jsPDF) matched critical advisories — both contradicted the handover. | `xlsx` removed; `read-excel-file`, `write-excel-file` and Papa Parse used instead; DOMPurify updated. `npm audit --audit-level=low` now reports 0. |
| **F-07** | Medium | JWT claims were optional; the API accepted a correctly signed token with no `exp`. | `decode_access_token()` requires `exp, iat, nbf, sub, org, type, ver, iss`, verifies `iss`, enforces `type=access`, and rejects `alg` other than HS256. Tokens are 15 minutes by default. |
| **F-08** | Medium | Rotation deleted the old refresh row, so replaying a stolen token was indistinguishable from an unknown token and did not alert. | Rotation writes `revoked_at` + `replaced_by_hash`. Presenting a revoked token revokes **all** sessions for that account, bumps `token_version` and audits `refresh_reuse`. |
| **F-09** | Medium | 422 responses echoed the rejected value — for login and password fields, the password itself. | `validation_error` strips `input` and `url` and stringifies non-scalar `ctx` before responding. |
| **F-10** | Medium | No Origin/Referer check on cookie-bearing writes; `SameSite=Lax` was the only barrier. | `origin_guard` rejects cross-site `Sec-Fetch-Site`, a mismatched `Origin`, and a mismatched `Referer` on `POST/PUT/PATCH/DELETE /api/v1/auth/*`. Requests with neither header (CLI/integration) keep working; bearer-token writes are unaffected because browsers do not attach the token automatically. |
| **F-11** | Medium | CSV formula injection was live in server-generated report CSVs (`services/report_engine.py`) and the database browser's local `_csv_cell` missed `-`, spaces and control prefixes. | Both exporters call one `safe_csv_cell()`; the browser keeps typed numbers numeric. Frontend CSV/XLSX exports neutralise headers and cells and write XLSX cells as explicit strings. Tests cover both sides. |
| **F-12** | Medium | Uploaded documents were read fully into memory **before** the size check (`_read_upload`). | Reads are bounded to `limit + 1`; oversized files are refused without being buffered. |
| **F-13** | Medium | No password maximum age for any account, including Owner; "force change" set a flag but did not invalidate the current credential or drive the login screen. | `PASSWORD_MAX_AGE_DAYS` (default 90) applies to every account with no owner exemption. `users.password_expires_at` is stored on each change, derived for legacy rows. An expired password blocks the workspace exactly like a forced change and notifies the account holder once. |
| **F-14** | Medium | Backup path resolution followed symlinks (`ensure_within_root`). | Symlinks are rejected; the resolved path must remain under the root and be a regular file. Archive directories are `0700`, files `0600`. |
| **F-15** | Medium | `IntegrityError` became a 500 with no explanation; concurrent creation races surfaced as server errors. | A typed handler answers 409 with a generic message and logs the path only — never SQL, parameters or values. |
| **F-16** | Medium | No response hardening on API responses, and the SPA host sent none. | API middleware sets `nosniff`, `DENY`, `no-referrer`, Permissions-Policy, CSP, COOP/CORP and `Cache-Control: no-store`, with HSTS when secure cookies are on. nginx and Vercel ship equivalent policies; the SPA CSP allows `'unsafe-inline'` styles only (MUI/emotion), never scripts. |
| **F-17** | Medium | `/api/health` disclosed whether the deployment had an administrator; Swagger/ReDoc/OpenAPI were public. | Health returns `status` and `api_version` only. API documentation is disabled when `ENVIRONMENT=production` and the nginx/Vercel routes return 404. |
| **F-18** | Low | Any authenticated user could read workspace account/role/permission counts from `GET /api/v1/overview`; the UI route was unguarded. | The endpoint requires one of `users:read`, `roles:read`, `permissions:read`; the dashboard route uses the same guard. `/security/overview` is likewise permission-gated. |
| **F-19** | Low | Settings objects rendered `SECRET_KEY`, the seed password and the database URL in `repr`/logs. | `repr`/`str`/`safe_summary()` mask all four; startup logs the masked summary. |
| **F-20** | Low | No log redaction; audit free-text could contain control characters that break CSV/UI rendering. | A redaction filter masks password/token/cookie/secret keys and bearer values in every configured logger; SQLAlchemy engine logging is pinned to WARNING; audit fields are stripped of control characters and length-capped. |
| **F-21** | Low | Containers ran as root; no health checks; compose had no capability or filesystem hardening. | API image runs as an unprivileged `app` user with a health check. Compose uses `read_only`, `tmpfs`, `no-new-privileges`, `cap_drop: ALL`, health checks, a private network and a fixed subnet for trusted-proxy configuration. |
| **F-22** | Low | Naive/aware datetime handling used `.replace(tzinfo=UTC)`, which relabels an aware non-UTC value instead of converting it. | `core/time.as_utc()` is the single conversion; lockout, session expiry, reset expiry and password age use it. |
| **F-23** | Low | A created account kept the administrator-chosen password indefinitely. | `force_password_change_on_create` defaults to **true in production**, so a new account must choose its own password at first sign-in; `require_password_change` can force it per account anywhere. |
| **F-24** | Low | `PasswordChange` accepted an unbounded `current_password`, allowing a large-body hashing DoS; `LoginInput` was unbounded. | Both are bounded (1–128 characters); JSON bodies are capped at 10 MB before parsing; the login throttle runs before any hashing. |
| **F-25** | Low | The validation/error surface differed between endpoints, leaking framework wording. | One validation handler, one HTTP handler, one 500 handler with a reference code; the browser turns field errors into plain sentences. |
| **F-26** | Low | Unused credential-adjacent helpers and dead code (`safe_csv_cell` imported nowhere) gave a false impression of coverage. | Exporters import the helper; the security suite asserts the **wiring**, not just the helper. |
| **F-27** | High | **Privilege escalation through the security centre.** Only `lock` refused to act on an Owner (`api/security.py`). A delegated holder of `security:password-reset` could therefore issue itself a reset code **for the Owner account**, force a password change on it, or revoke its sessions — then sign in as the Owner and leave its own role behind. The bulk endpoint had the same hole for every action except `lock`. | One `ensure_can_act_on()` guard is applied to reset-code issue, force-change, session revocation, lock, unlock and every bulk action: an Owner account may only be touched by an Owner. Regression tests drive all six paths as a delegated administrator and assert that the same administrator can still serve a normal account. |

---

## 5. Disposition of your 24-item checklist

| # | Original item | Result in WellCostIQ |
|---|---|---|
| 1 | CORS misconfiguration | **Fixed.** Exact origins, no wildcard with credentials, HTTPS-only in production, fail-closed at startup (F-03). |
| 2 | Hardcoded admin username backdoor | **Not present.** No username/e-mail switch exists; the Owner role is a persisted, immutable tenant role; provisioning requires a policy-compliant password. `SEED_*` is environment-only and must be cleared after first boot. |
| 3 | JWT type confusion / session configuration | **Fixed.** Required claims, explicit `type=access`, 15-minute TTL, strict HS256, issuer check, refresh replay detection (F-07, F-08). |
| 4 | Logout does not revoke refresh token | **Verified as correct, then strengthened.** Logout deletes the session and clears the cookie; `logout-all` revokes everything and bumps `token_version`; rotation detects replay. Access tokens remain valid for their short lifetime by design — use revocation for incidents. |
| 5 | Missing rate limiting on 2FA verification | **No 2FA exists in this product.** Every credential-verification endpoint (login, reset code, change-password) now has a shared per-client budget plus account lockout (F-05). Native TOTP/WebAuthn remains a product gap (§9). |
| 6 | Missing password policy on create/update | **Fixed.** One policy function (12–128, three character classes, no e-mail/account name, no known defaults or keyboard walks, product name refused), reuse of the last five, configurable lifetime. User update cannot set a password; administrators use reset codes or force-change. |
| 7 | Missing location scope enforcement | **Not applicable.** The entitlement model is workspace tenancy (`organization_id`) plus RBAC. Cross-tenant access is covered by existing regression tests; there is no site/location dimension to enforce. |
| 8 | Path traversal in backup paths | **Fixed/verified.** Resolve-then-contain, symlink refusal, regular-file check, restrictive permissions (F-14). |
| 9 | Sensitive information in logs | **Reduced in code.** Redaction filter, no request body logging, sanitised audit text, SQL parameters hidden, forwarded headers no longer trusted (F-01, F-20). Platform log retention and SIEM redaction remain IT work. |
| 10 | Missing value/range validation on calibration rows | **No calibration module exists.** Typed decimals and module-level validation are present; a business range catalogue is a domain requirement, not a security fix. |
| 11 | Insecure token storage in `localStorage` | **Verified.** Access token lives in memory only; the refresh token is an HttpOnly, Path-scoped cookie; local storage holds theme, navigation and scope preferences only. |
| 12 | Database credentials via command-line arguments | **Not present.** No `pg_dump`/CLI credential path; SQLAlchemy uses `DATABASE_URL`. Compose passes the password as an environment variable, which is standard but still requires secret-manager handling in production. |
| 13 | CSV formula injection in exports | **Fixed.** Server reports, database browser, client CSV and XLSX templates; headers included; typed numbers preserved (F-11). |
| 14 | SQL built with f-strings | **No executable SQL found.** Bandit B608 matches are user-facing error messages; the only raw `text()` is the parameterless `SELECT version_num FROM alembic_version`. Reports and the database browser use reflected, allow-listed identifiers and bound parameters. |
| 15 | HTML injection | **No raw HTML sink** (`dangerouslySetInnerHTML`, `innerHTML`, `eval`, `new Function` absent). The realistic XSS path — an uploaded document served with a client MIME — is closed (F-04), and CSP is applied at both tiers. |
| 16 | Naive datetime comparison in lockout | **Fixed.** Aware conversions everywhere, with tests (F-22). |
| 17 | Hardcoded API base URL with insecure fallback | **Fixed.** The SPA calls relative `/api/v1`; nginx proxies same-origin. The Vercel template no longer proxies `/docs`/`/openapi.json`, and its SPA fallback cannot swallow `/api/*` into HTML. The API origin in `vercel.json` must be reviewed per environment (§9). |
| 18 | Unsanitised error display | **Fixed.** Structured validation errors without input echo, generic 409, 500 with a reference code, readable 401/403/404/405 messages (F-09, F-15, F-25). |
| 19 | IntegrityError race on concurrent creation | **Handled.** Database uniqueness remains the final guard; conflicts answer 409 without leaking SQL (F-15). True concurrency must still be proven on PostgreSQL (§9). |
| 20 | RBAC diagnostics information disclosure | **Fixed.** `/api/v1/overview` and `/api/v1/security/overview` require the capabilities they summarise, and the UI route is guarded as well (F-18). |
| 21 | Administrator password set to never expire | **Fixed.** Maximum age applies to every account, Owner included, with a warning window and a forced change on expiry (F-13). Expiry is configurable and can be disabled only deliberately. |
| 22 | Weak key derivation (fast hash) | **Password hashing is Argon2** via `pwdlib`. SHA-256 is used only to index high-entropy random refresh/reset tokens, where a fast hash is appropriate. No custom encryption KDF exists. |
| 23 | Missing security headers | **Fixed** at the API, the nginx tier and the Vercel template, including CSP, HSTS (secure cookies), COOP/CORP and `no-store` for API payloads (F-16). Verify HSTS at your TLS edge. |
| 24 | Unauthenticated diagnostic endpoint disclosure | **Fixed.** `/api/health` exposes liveness and API version only; documentation routes are disabled in production (F-17). |

---

## 6. Password lifecycle as implemented

This is the section IT should test in UAT. Every rule below is server-side; the UI
only reflects it.

### 6.1 Creation and first sign-in

* Accounts are created by an administrator (`POST /api/v1/users`, `users:create`).
  The initial password must satisfy the policy below and cannot be assigned to
  another person's account silently: `force_password_change_on_create` defaults to
  **true in production**, so the first successful sign-in is replaced by the password
  screen, and only `/auth/me`, `/auth/change-password`, `/auth/logout`,
  `/auth/logout-all` and `/auth/refresh` are reachable until a new password is saved.
* The first workspace Owner is created by `python -m app.seed` or the `SEED_*`
  variables. `SEED_ADMIN_PASSWORD` must be removed after the first successful boot;
  the API logs a warning if bootstrap is enabled in production.

### 6.2 Composition policy (single implementation, `core/security.py`)

- 12–128 characters (`PASSWORD_MIN_LENGTH` can raise the minimum, never lower it below 12).
- At least three of: lowercase, uppercase, digit, symbol.
- Must not contain the account's e-mail address, and must not contain an account
  handle of 8 characters or more.
- Known defaults (`password`, `changeme`, `welcome`, `admin`, product names, common
  variants) and keyboard/number walks (`qwerty…`, `1234…`, `abcd…`) are refused.
- No leading or trailing whitespace, no single-character repetition.
- The last `PASSWORD_HISTORY_LIMIT` (default 5) passwords cannot be reused. History
  stores Argon2 verifiers only, never the password.

### 6.3 Lifetime and expiry

- `PASSWORD_MAX_AGE_DAYS` defaults to **90** and applies to every account, including
  Owner. `0` disables age expiry and should only be used with an external identity
  provider.
- `users.password_expires_at` is written on every change; legacy rows derive it from
  `password_changed_at` (falling back to `created_at`), so a dormant account cannot
  keep an old password forever.
- **At sign-in:** an expired password still authenticates (the user is proven), but the
  session is contained — `must_change_password` is set, the response carries
  `password_expired: true`, the account holder receives one notification, and every
  other endpoint answers 403 until the change is complete.
- **While signed in:** `/auth/me` reports `password_expired`,
  `password_expires_at` and `password_days_remaining`; the UI gate applies on the next
  request even if the password expires mid-session.
- The Security Centre lists expiry state and exposes filters for *Password expired*
  and *expires within 14 days*.

### 6.4 User-initiated change

`POST /api/v1/auth/change-password` requires the current password, enforces policy and
history, writes a new expiry, bumps `token_version`, deletes **all** refresh sessions
and clears the cookie. Every device must sign in again.

### 6.5 Forgot-password (administrator-approved recovery)

1. `POST /auth/forgot-password` is enumeration-safe (same 202 and same body for known
   and unknown accounts), rate-limited to 5 requests per 15 minutes per client, and
   creates one pending request plus a high-priority task for `security:password-reset`.
2. An authorised reviewer approves or rejects it (`/security/password-reset-requests/{id}/approve|reject`),
   recording a reason.
3. Approval returns a **one-time code** (32 random bytes). Only its SHA-256 hash is
   stored; it expires after `PASSWORD_RESET_MINUTES` (30) and is invalidated on use.
4. `POST /auth/reset-password` is rate-limited to 10 attempts per 15 minutes, enforces
   the same policy **and reuse history**, clears the lockout, revokes every session and
   notifies the account holder.
5. Identity verification and secure delivery of the code are operational controls, not
   code. The application cannot prove who answered the phone.

### 6.6 Administrator actions (Security Centre)

| Action | Effect | Permission |
|---|---|---|
| Issue one-time reset code, no request needed | Pending request created, code returned once, account holder notified | `security:password-reset` |
| Force password change | `must_change_password` set **and** password expired immediately, all sessions revoked, notification sent | `security:password-reset` |
| Revoke sessions | Deletes refresh sessions, bumps `token_version` | `security:password-reset` |
| Lock account | Blocks sign-in until an authorised unlock (no timed release), sessions revoked | `security:unlock` |
| Unlock account | Clears lock and failure counter | `security:unlock` |
| Bulk actions | One audited decision across a selection; skips self, and skips every Owner target unless the actor is an Owner | as above |

**Owner protection (F-27).** No delegated capability is sufficient to act on an
Owner account. Reset-code issue, force-change, revocation, lock and unlock all run
the same `ensure_can_act_on()` check, and the bulk path applies the same rule per
target instead of only for `lock`. Without it, `security:password-reset` was a
route to full workspace ownership.

Every action writes a typed row in the same transaction as an audit entry with actor,
reason, timestamp, client address and user agent. Owner accounts cannot be deleted,
deactivated, demoted or (for non-owners) edited or locked.

### 6.7 Lockout and session rules

- 5 failed passwords lock the account for 15 minutes (`MAX_FAILED_LOGINS`,
  `LOCKOUT_MINUTES`); lock state is computed with timezone-aware comparisons.
- Unknown accounts perform a dummy Argon2 verification to reduce timing-based
  enumeration, and are throttled per client address.
- Refresh tokens rotate on every use; a replayed token revokes the whole account's
  sessions. At most `MAX_ACTIVE_SESSIONS` (10) live sessions are kept.
- Sign-in while an account is locked is refused *and audited* (`login_blocked`).

---

## 7. Control catalogue (what IT is receiving)

**Identity and session**
- Argon2id password hashing (`pwdlib` recommended settings), no password ever stored,
  logged or returned.
- 15-minute HS256 access tokens with required claims, issuer check and token version;
  opaque 256-bit refresh tokens stored as SHA-256 hashes, HttpOnly/SameSite=Lax cookie
  scoped to `/api/v1/auth`, rotated with replay detection.
- Immediate invalidation on password change, reset, force-change, lock and logout-all.

**Authorisation**
- Tenant-scoped queries (`organization_id`) and server-side capability checks on every
  business and administrative route; permissions are data, not hard-coded names.
- Separation of duties for backup restore (request → approve → validate → execute),
  and for password resets (requester ≠ approver is a documented process control).
- Immutable Owner role; privilege escalation through role/permission assignment is
  blocked when the actor lacks the capability.

**Data protection**
- No JSON/JSONB business payload columns; typed relational columns only.
- Credential tables excluded from archives and preserved across restore.
- Uploaded documents stored in the database with signature-derived MIME types.
- Exports neutralise spreadsheet formulas; API payloads are `no-store`.

**Operational**
- Structured audit trail (actor snapshot, action, entity, summary, IP, user agent,
  timestamp) surviving restores; no audit delete endpoint.
- Health/liveness without setup-state disclosure; API docs off in production.
- Config fail-closed for production; secrets masked in logs and representations.
- Container and compose hardening; nginx security headers, rate limits and body caps.

---

## 8. Executed verification

Environment: Python 3.11.2 sandbox, SQLite databases on temporary paths, Node 22.22.3,
npm 10.9.8. CI uses Python 3.12; PostgreSQL is not exercised here.

| Check | Command | Result |
|---|---|---|
| Hardening suite, before changes | `pytest tests/test_security_hardening.py -q` | **12 failed, 10 passed** |
| Hardening suite, after changes | same | **22 passed** |
| Account lifecycle suite (new) | `pytest tests/test_account_lifecycle.py -q` | **18 passed** |
| Full backend suite, final code | `pytest -q` | **326 passed, 0 failed** (12m40s) |
| Migration round trip | `alembic upgrade head`, `alembic downgrade -1`, `alembic upgrade head` | head `b7c1d9e4f2a8`, `schema_status() == ready` |
| Frontend security tests | `npm run test:security` | passed (formula neutralisation in CSV and XLSX, quoting, import limits, ZIP preflight, XLSX text round trip) |
| Frontend build | `npm run build` | passed (TypeScript + Vite) |
| Dependency audit (backend) | `pip-audit -r backend/requirements.lock` | 0 known advisories |
| Dependency audit (frontend) | `npm audit --audit-level=low` | 0 known advisories |
| Static analysis | `bandit -r backend/app -ll` | 0 High, 7 Medium (B608 — user-facing messages, triaged), 13 Low |
| Lint (undefined names) | `ruff check backend/app --select F821,F811` | no executable defect (remaining F821 are SQLAlchemy forward references) |

The new lifecycle tests cover: password expiry gate and reopening, refresh replay
revocation, logout-all, weak-password rejection, trusted-proxy identity,
credential-free archives, symlink/escape refusal, end-to-end report CSV neutralisation,
secret masking and production documentation shutdown.

---

## 9. Residual risks and pre-production gates

These are **not** mitigated by this branch and must be handled by IT or accepted
explicitly.

1. **No MFA/SSO.** There is no TOTP, WebAuthn, SAML, OIDC or SCIM. Password-only
   authentication is the largest remaining risk. Put identity-aware access in front of
   the application now; plan native MFA as a separate tested release.
2. **Edge rate limiting.** The database ledger is shared but count-then-insert is not
   atomic under high concurrency, and per-IP budgets do not stop distributed
   credential stuffing. Apply atomic limits at the load balancer/WAF for
   `/auth/login`, `/auth/refresh`, `/auth/forgot-password`, `/auth/reset-password` and
   `/auth/change-password`.
3. **Proxy trust must be configured correctly.** `TRUSTED_PROXY_IPS` decides whether
   forwarded headers are believed. Set it to the private proxy range only (compose
   does). If the API is directly reachable, leave it empty. Never use `*`.
4. **TLS and HSTS.** Terminate TLS at the approved edge, redirect HTTP, and enable
   HSTS there. The application only adds HSTS when `SECURE_COOKIES=true`.
5. **Same-site cookie constraint.** The refresh cookie is `SameSite=Lax` and scoped to
   `/api/v1/auth`. Serve the SPA and API from the same site (nginx template does). If
   they must be on different sites, the refresh flow will fail by design; do not
   weaken it without a CSRF-token design.
6. **PostgreSQL concurrency and migrations.** Run the full suite against a disposable
   PostgreSQL instance, including parallel refresh rotation, reset consumption, user
   creation and asset creation, and time the migration under multiple workers. Never
   point the tests at production: fixtures drop tables.
7. **Deployed DAST and independent penetration test**, plus real-browser CSP/UAT
   across charts, PDF previews, downloads and both hosting templates.
8. **Malware scanning / content disarm** for uploaded documents. MIME sniffing is not
   antivirus.
9. **Secrets management.** `SECRET_KEY`, database credentials and seed values must live
   in the platform secret manager. Removing `SEED_ADMIN_PASSWORD` after first boot is
   mandatory. Rotating `SECRET_KEY` invalidates access tokens and changes throttle
   hashes; coordinate it.
10. **Central logging and alerting.** Redaction is implemented in-process, but SIEM
    parsing, retention and access control are platform responsibilities. Alert on
    `login_failed`, `login_blocked`, `refresh_reuse`, `password_expired`,
    `password_change_failed`, reset approvals, lock/unlock, role and permission changes,
    restore execution and unusually large exports.
11. **Backup handling.** Archives now contain business data only. Encrypt them in
    transit and at rest, restrict filesystem access, test restore on PostgreSQL, and
    expire them under retention policy. Treat older archives (which may contain
    credential hashes) as sensitive: quarantine, restrict and consider a credential
    reset if one was exposed.
12. **Container and OS supply chain.** The Dockerfiles no longer run as root and pin a
    lock file, but image CVEs, digest pinning and registry policy still require a
    scanning pipeline.
13. **Vercel API origin.** `frontend/vercel.json` still names the deployed API host.
    Confirm it is the approved HTTPS origin for that environment and that
    `CORS_ORIGINS` matches it exactly. Prefer the nginx template (same-origin, no
    hard-coded third-party host).

---

## 10. Deployment checklist

1. `ENVIRONMENT=production`.
2. `SECRET_KEY` = `openssl rand -hex 32` (≥32 characters, unique per environment,
   stored in the secret manager).
3. `SECURE_COOKIES=true`; TLS terminated at the edge with HTTP→HTTPS redirect.
4. `CORS_ORIGINS` = exact HTTPS front-end origin(s); no wildcard.
5. `TRUSTED_PROXY_IPS` = the private proxy CIDR only (compose default
   `172.28.0.0/16`); empty if directly reachable.
6. Run `alembic upgrade head` — the current head is **`b7c1d9e4f2a8`** (password expiry
   and refresh rotation). Back up first.
7. Set the password policy: `PASSWORD_MAX_AGE_DAYS` (90), `PASSWORD_HISTORY_LIMIT` (5),
   `MAX_FAILED_LOGINS` (5), `LOCKOUT_MINUTES` (15),
   `FORCE_PASSWORD_CHANGE_ON_CREATE=true`.
8. Complete first-boot seeding, then **delete** `SEED_ADMIN_PASSWORD` and, if
   appropriate, set `BOOTSTRAP_ADMIN_ON_STARTUP=false`.
9. Confirm `/docs`, `/redoc` and `/openapi.json` return 404 and `/api/health` contains
   only `status` and `api_version`.
10. Confirm the backup root is on an encrypted private volume with restrictive
    ownership, and that an archive's table list contains no `users`,
    `password_history`, `password_reset_*` or `refresh_sessions`.
11. Point monitoring at the events in §9.10 and run the UAT script in
    `SECURITY_MANUAL.md` (including the expired-password and replay cases).
12. Keep `docs/SECURITY_VALIDATION.md` with the release evidence; re-run §8 for every
    build.

---

## 11. Change inventory (this branch)

**Backend**
`core/config.py`, `core/security.py`, `core/request_security.py`, `core/time.py`,
`core/logging.py`, `core/spreadsheets.py`, `main.py`, `api/deps.py`, `api/auth.py`,
`api/security.py` (including the Owner-target guard), `api/rbac.py`, `api/vendor_master.py`, `api/backup.py`,
`models/entities.py`, `services/password_policy.py`, `services/audit.py`,
`services/backup.py`, `services/database_browser.py`, `services/report_engine.py`,
`services/provisioning.py`, `schemas/rbac.py`, `schemas/security.py`,
`alembic/versions/b7c1d9e4f2a8_password_expiry_and_refresh_rotation.py`.

**Frontend**
`src/lib/export.ts`, `src/lib/types.ts`, `src/lib/workflowTypes.ts`,
`src/context/AuthContext.tsx`, `src/components/PasswordChangeGate.tsx`,
`src/components/ImportDialog.tsx`, `src/pages/Login.tsx`, `src/pages/SecurityCenter.tsx`,
`src/App.tsx`, `package.json` / `package-lock.json`, `nginx.conf`,
`proxy_params_wcp.conf`, `vercel.json`, `tests/security.mjs`, `Dockerfile`.

**Deployment and tests**
`docker-compose.yml`, `backend/Dockerfile`, `render.yaml`, `.env.example`,
`backend/.env.example`, `backend/tests/test_security_hardening.py` (now passing),
`backend/tests/test_account_lifecycle.py` (new, 18 cases), `backend/tests/test_bootstrap.py`
(health contract), `docs/SECURITY_MANUAL.md`, `docs/SECURITY_VALIDATION.md`,
`Makefile`.

---

## 12. Statement of limitations

This audit was performed by reading the entire backend application, the security-
relevant frontend modules, the deployment templates and the test suite, then executing
the backend and frontend security tests, dependency audits, static analysis and a
migration round trip. It did not include a deployed environment, real users, real
production data, PostgreSQL, TLS configuration, a WAF or an independent attacker.

Controls that depend on infrastructure (TLS, HSTS, rate limiting at the edge, log
retention, malware scanning, secret storage, PostgreSQL concurrency) are specified here
and in `SECURITY_MANUAL.md` but must be verified by IT before go-live. A clean result in
the commands above means "the checks we ran passed", not "the system is secure".
