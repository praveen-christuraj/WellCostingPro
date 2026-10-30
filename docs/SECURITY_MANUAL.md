# WellCostIQ Security Manual

This guide explains the controls built into WellCostIQ and the deployment work that remains the responsibility of the customer’s IT team. It is written in two levels: the first section is for ordinary users and workspace administrators; the second is for IT, security and deployment personnel.

## Part 1 — Everyday security for non-IT users

### Signing in safely

- Sign in only through your organisation’s approved WellCostIQ address. Never follow an unexpected reset link or disclose a password in chat or email.
- The workspace ID and work email identify your account. A wrong workspace, unknown email and wrong password all produce the same public error so an outsider cannot discover registered accounts.
- Five failed password attempts temporarily lock the account for 15 minutes. An authorised administrator can unlock it from the Security Centre after verifying the person.
- Sessions use a short-lived access token and a rotating, browser-only refresh cookie. Signing out invalidates the current refresh session. A password change or password reset invalidates every session for that user.

### Password rules

Passwords must be 12–128 characters and use at least three of these four groups: lowercase letters, uppercase letters, numbers and symbols. The password must not contain the user’s email address and common default passwords are rejected. Use a company-approved password manager and a unique password.

### Forgotten password process

1. On the sign-in page choose **Forgot password?**.
2. Enter the workspace ID, work email and an optional reason. The confirmation is deliberately generic.
3. A user with **Review password reset requests** sees a high-priority task and notification.
4. The administrator verifies the requester outside WellCostIQ, approves or rejects the request, and if approved receives a single-use code. The plain code is shown only once; WellCostIQ stores only its SHA-256 hash.
5. The administrator gives the code to the verified user through the organisation’s approved secure channel—not an open group, ticket comment or unverified caller.
6. The user opens **I already have an approved reset code** on the sign-in page, supplies the code and a new password. Codes expire after 30 minutes by default and cannot be reused.

Never approve your own unexpected request without verifying why it was raised. Repeated or suspicious requests should be escalated to IT/security.

### Notifications and tasks

- The bell shows personal notifications. Notifications are stored as one typed row per recipient; recipients cannot see another user’s inbox.
- The Task Manager shows only tasks the user created, is assigned, is permitted to act on, or—if authorised—all workspace tasks.
- Existing AFE transitions remain the source of truth. Submitting an AFE creates a review task; completing review creates an approval task. Acting on the task does not bypass the AFE permission or status checks.
- Announcements sent by authorised users appear in every active user’s notification inbox. Do not place passwords, reset codes, personal data or secrets in announcements or task descriptions.

### Roles and audit trail

Access is tenant-scoped and permission-based. Give users the smallest role they need. Owner access is powerful and should be limited. Sign-in, failed sign-in, password recovery decisions, user administration, notification sending, task changes and business changes are recorded in the read-only audit trail with actor, time and request details.

Report a lost device, suspicious notification, unexpected password reset, or unexplained audit entry immediately. IT should deactivate the user or force a password reset and review the audit trail.

## Part 2 — IT and deployment security

### Security architecture

- **Tenant isolation:** application queries and mutable records are scoped by `organization_id`; RBAC checks run server-side.
- **Authentication:** Argon2 password hashing through `pwdlib`; signed HS256 access JWTs default to 15 minutes; refresh tokens are opaque random values stored only as SHA-256 hashes and rotated on use.
- **Revocation:** user `token_version` invalidates outstanding access tokens after a credential reset; all stored refresh sessions are deleted.
- **Recovery:** enumeration-safe request response, per-IP request throttling, administrator permission gate, short-lived one-time code, hash-only persistence and complete audit history.
- **Browser controls:** HttpOnly/SameSite refresh cookie, optional Secure flag, strict CORS allow-list, clickjacking/content-sniffing/referrer/permissions/CSP response headers, and HSTS when secure cookies are enabled.
- **Persistence:** security workflow, notifications and task history use ordinary typed relational columns. Reset secrets and raw refresh tokens are never stored. There are no JSON/JSONB business payload columns.
- **Data browser:** authentication secrets and other protected fields remain excluded from the application database browser.

### New permission keys

| Permission | Purpose |
|---|---|
| `security:read` | View the Security Centre and recovery queue |
| `security:password-reset` | Approve/reject requests and issue one-time reset codes |
| `security:unlock` | Clear an account lockout |
| `notifications:manage` | Send workspace-wide announcements |
| `tasks:read` | Read permitted workflow tasks |
| `tasks:create` | Create manual tasks |
| `tasks:manage` | Manage all workspace tasks |

The migration grants these permissions to existing Owner roles. For separation of duties, create a dedicated security-administrator role and avoid routine use of Owner accounts.

### Production deployment checklist

1. Set a unique, randomly generated `SECRET_KEY` of at least 32 bytes. Never reuse development or test values. Store it in the platform secret manager, not source control.
2. Use PostgreSQL with a dedicated least-privilege database role. Restrict database network access to the API service and authorised backup/operations systems.
3. Run `cd backend && alembic upgrade head` before starting the updated application. Back up the database first and confirm the migration reaches revision `c3d7e9f1a204`.
4. Terminate TLS at the approved reverse proxy/load balancer, redirect HTTP to HTTPS, set `SECURE_COOKIES=true`, and ensure proxy forwarding headers are overwritten—not appended from untrusted clients.
5. Set `CORS_ORIGINS` to exact approved HTTPS frontend origins. Do not use `*` with credentialed requests.
6. Keep the API and database on private networks where possible. Allow public ingress only to the reverse proxy; restrict administrative consoles by VPN or identity-aware access.
7. Configure central log collection and alert on repeated `login_failed`, password reset requests, account unlocks, role/permission changes, owner changes and unusual export volume. Application logs must not collect passwords, reset codes, JWTs or cookies.
8. Back up the database encrypted in transit and at rest. Test restoration regularly. Define retention for business, notification, task and audit data according to company policy and law.
9. Apply operating-system, container, Python and Node security updates through a tested release pipeline. Scan dependencies and container images before deployment.
10. Test light/dark UI, login, lockout, forgot/reset, session revocation, RBAC denial, AFE task generation, notifications, audit visibility, backup and restore in UAT.

### Reverse proxy requirements

Preserve the original client address only from trusted proxies. Strip inbound `X-Forwarded-For` at the public boundary and set it from the connection address. Limit request/body sizes and apply edge rate limits to `/api/v1/auth/login`, `/api/v1/auth/forgot-password`, `/api/v1/auth/reset-password` and refresh endpoints. Use a web application firewall where required by policy.

### Operational procedures

- **Joiner:** create the account with minimum roles and transmit the initial password separately. Require immediate password change under organisational policy.
- **Mover:** review and remove obsolete roles before adding new ones.
- **Leaver:** deactivate the user immediately; this blocks token use. Review assigned open tasks and transfer them.
- **Suspected compromise:** deactivate the account, revoke/reset credentials, preserve logs, inspect audit and session activity, rotate affected infrastructure secrets, and follow the organisation’s incident-response plan.
- **Reset-code handling:** verify identity, approve just before use, disclose once through an approved channel, and never record the plain code in a ticket or audit note. Reject stale or suspicious requests.
- **Periodic review:** quarterly (or more often) review Owner accounts, privileged permission assignments, inactive users, open reset requests, open/overdue tasks, CORS origins, TLS posture, backups and audit alerts.

### Validation after deployment

Use a non-production workspace to confirm that an unknown account and a known account receive the same forgot-password response; the sixth request within 15 minutes is throttled; an unapproved, expired or reused code fails; a valid reset signs out every session; users cannot see cross-tenant records; non-authorised users receive HTTP 403; and AFE review/approval tasks do not bypass existing transitions.

### Current boundaries and recommended next phase

WellCostIQ currently provides password authentication and tenant-aware RBAC; it does not yet claim MFA, SAML/OIDC single sign-on, SCIM provisioning, breached-password intelligence, tamper-evident external audit storage or whole-platform SIEM integration. Organisations requiring those controls should place identity-aware access at the edge now and plan native MFA/SSO as a separately tested security release. Do not describe those controls as implemented until UAT and security review are complete.
