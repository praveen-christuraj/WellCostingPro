# WellCostIQ Security Manual

This guide explains the controls built into WellCostIQ and the deployment work that remains the responsibility of the customer’s IT team. It is written in two levels: the first section is for ordinary users and workspace administrators; the second is for IT, security and deployment personnel.

## Part 1 — Everyday security for non-IT users

### Signing in safely

- Sign in only through your organisation’s approved WellCostIQ address. Never follow an unexpected reset link or disclose a password in chat or email.
- The workspace ID and work email identify your account. A wrong workspace, unknown email and wrong password all produce the same public error so an outsider cannot discover registered accounts.
- Five failed password attempts temporarily lock the account for 15 minutes. An authorised administrator can unlock it from the Security Centre after verifying the person.
- Sessions use a short-lived access token and a rotating, browser-only refresh cookie. Signing out invalidates the current refresh session. A password change or password reset invalidates every session for that user.

### Password rules

Passwords must be 12–128 characters and use at least three of these four groups: lowercase letters, uppercase letters, numbers and symbols. The password must not contain the user’s email address and common default passwords are rejected. The last five passwords an account has used cannot be chosen again. Use a company-approved password manager and a unique password.

### When an administrator controls your password

The Security Centre can act **without a request from you**, because a lost laptop, a suspected leak or a leaver cannot wait for a support ticket. Three things can happen, and each one tells you what occurred:

- **A one-time reset code is issued.** You receive a notification. Redeeming the code sets a new password and signs out every session.
- **A new password is required.** You receive a notification and every session ends. After signing in, the only screen available is the password screen; the workspace reopens as soon as a compliant password is saved.
- **Sessions are revoked or the account is locked.** Revocation signs you out everywhere but keeps the password. A lock blocks sign-in completely until an authorised administrator releases it.

If you receive any of these notices and did not expect it, contact your workspace administrator or IT security immediately — the audit trail records who acted, when and why.

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
- The **Notification centre** adds filters (read state, severity, type, text, date range), 20/50/100 paging, mark read/unread, dismissal and CSV/Excel/PDF export of the view you are looking at.
- Announcements are addressed to every active user, to chosen roles, or to chosen people. Each broadcast keeps one typed header row, so an authorised sender can see how many recipients read it and can **recall** it — recalling withdraws only the copies nobody has opened.
- The Task Manager shows only tasks the user created, is assigned, is permitted to act on, or—if authorised—all workspace tasks.
- The task queue supports status, priority, type, assignee and due-date filters (including overdue and due-today), 20/50/100 paging, bulk claim/complete/reopen/cancel/reassign, a per-task history with comments, and CSV/Excel/PDF export.
- Existing AFE transitions remain the source of truth. Submitting an AFE creates a review task; completing review creates an approval task. Acting on the task does not bypass the AFE permission or status checks.
- Announcements sent by authorised users appear in the addressed inboxes. Do not place passwords, reset codes, personal data or secrets in announcements or task descriptions.

### Roles and audit trail

Access is tenant-scoped and permission-based. Give users the smallest role they need. Owner access is powerful and should be limited. Sign-in, failed sign-in, password recovery decisions, user administration, notification sending, task changes and business changes are recorded in the read-only audit trail with actor, time and request details.

Report a lost device, suspicious notification, unexpected password reset, or unexplained audit entry immediately. IT should deactivate the user or force a password reset and review the audit trail.

### Error messages

When an action fails, the application shows one pop-up with the server’s readable explanation: a missing permission, a record that changed, a validation problem or a missing endpoint. A “Not found” answer always names what was missing and what to do next; if it names an API route, the browser tab and the deployed API are different versions and a reload after deployment resolves it. Messages that carry no information are replaced with a plain sentence rather than passed through.

Three rules keep the messages usable:

1. **A permission answer names the capability**, for example *“Permission denied. This action needs security:read.”* The user can then ask an administrator for exactly that capability instead of guessing.
2. **A rejected form is translated into plain language.** The API describes validation failures in developer terms (*“String should match pattern '^(low|normal|high|critical)$'”*); the browser rewrites them as *“Priority must be one of: low, normal, high, critical.”* No technical field path or regex is ever shown.
3. **An address the application does not serve is a page, not a silent redirect.** Reloading a bookmark that no longer exists shows the requested address, the reason it usually fails (an older page bundle than the deployed build) and buttons back to the dashboard. An unmatched API route is logged on the server with method, path and API version so the operator can see which call a browser is making.

## Part 2 — IT and deployment security

### Security architecture

- **Tenant isolation:** application queries and mutable records are scoped by `organization_id`; RBAC checks run server-side.
- **Authentication:** Argon2 password hashing through `pwdlib`; signed HS256 access JWTs default to 15 minutes; refresh tokens are opaque random values stored only as SHA-256 hashes and rotated on use.
- **Revocation:** user `token_version` invalidates outstanding access tokens after a credential reset; all stored refresh sessions are deleted.
- **Recovery:** enumeration-safe request response, per-IP request throttling, administrator permission gate, short-lived one-time code, hash-only persistence and complete audit history.
- **Administrator password control:** one-time codes without a user request, forced password change (`users.must_change_password`), session revocation (`token_version` plus refresh-session deletion), and account lock. Each action writes a typed request/notification row and an audit entry with the administrator’s reason.
- **Password history:** `password_history` stores one-way hashes of the previous five passwords per account, so reuse is refused on every path (sign-in change, reset code, administrator action). No plaintext password is ever stored or logged.
- **Containment:** while `must_change_password` is set, only `GET /auth/me`, `POST /auth/change-password`, `POST /auth/logout` and `POST /auth/refresh` are reachable; every other endpoint answers 403 with an instruction to set a new password.
- **Browser controls:** HttpOnly/SameSite refresh cookie, optional Secure flag, strict CORS allow-list, clickjacking/content-sniffing/referrer/permissions/CSP response headers, and HSTS when secure cookies are enabled.
- **Persistence:** security workflow, notifications and task history use ordinary typed relational columns. Reset secrets and raw refresh tokens are never stored. There are no JSON/JSONB business payload columns.
- **Data browser:** authentication secrets and other protected fields remain excluded from the application database browser.

### New permission keys

| Permission | Purpose |
|---|---|
| `security:read` | View the account register, the recovery queue and the security summary |
| `security:password-reset` | Open the Security Centre, approve/reject requests, issue one-time reset codes on demand, force a password change and revoke sessions (the account register itself still needs `security:read`) |
| `security:unlock` | Lock or unlock an account |
| `notifications:manage` | Send workspace-wide announcements |
| `tasks:read` | Read permitted workflow tasks |
| `tasks:create` | Create manual tasks |
| `tasks:manage` | Manage all workspace tasks |

The migration grants these permissions to existing Owner roles. For separation of duties, create a dedicated security-administrator role and avoid routine use of Owner accounts.

### Production deployment checklist

1. Set a unique, randomly generated `SECRET_KEY` of at least 32 bytes. Never reuse development or test values. Store it in the platform secret manager, not source control.
2. Use PostgreSQL with a dedicated least-privilege database role. Restrict database network access to the API service and authorised backup/operations systems.
3. Run `cd backend && alembic upgrade head` before starting the updated application. Back up the database first and confirm the migration reaches revision `d1f4b8c27e93` (password controls, password history, announcement headers).
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
- **Suspected compromise:** deactivate the account, revoke every session, force a password change (or issue a one-time code), preserve logs, inspect audit and session activity, rotate affected infrastructure secrets, and follow the organisation’s incident-response plan.
- **Administrator-initiated reset:** issue the code from Security centre → Accounts, record the reason, deliver it through an approved channel, and confirm the account holder completes the change. A forced change is preferable when the old password may be known to somebody else.
- **Reset-code handling:** verify identity, approve just before use, disclose once through an approved channel, and never record the plain code in a ticket or audit note. Reject stale or suspicious requests.
- **Periodic review:** quarterly (or more often) review Owner accounts, privileged permission assignments, inactive users, open reset requests, open/overdue tasks, CORS origins, TLS posture, backups and audit alerts.

### Validation after deployment

Use a non-production workspace to confirm that an unknown account and a known account receive the same forgot-password response; the sixth request within 15 minutes is throttled; an unapproved, expired or reused code fails; a valid reset signs out every session; an administrator-issued code works without a prior request; a forced change closes the workspace until the new password is saved; a reused password is refused; locking blocks sign-in and unlocking restores it; recalling an announcement removes unread copies only; users cannot see cross-tenant records; non-authorised users receive HTTP 403; and AFE review/approval tasks do not bypass existing transitions.

### Current boundaries and recommended next phase

WellCostIQ currently provides password authentication and tenant-aware RBAC; it does not yet claim MFA, SAML/OIDC single sign-on, SCIM provisioning, breached-password intelligence, tamper-evident external audit storage or whole-platform SIEM integration. Organisations requiring those controls should place identity-aware access at the edge now and plan native MFA/SSO as a separately tested security release. Do not describe those controls as implemented until UAT and security review are complete.
