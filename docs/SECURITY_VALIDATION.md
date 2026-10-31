# Executed security validation — 2026-10-31

This page records what was **actually run** against the code in this branch. The
controlling handover document is [`SECURITY_AUDIT_FINAL.md`](SECURITY_AUDIT_FINAL.md);
the superseded claims are listed in
[`SECURITY_REVIEW_2026-10-31.md`](SECURITY_REVIEW_2026-10-31.md).

## Results

| Check | Executed result |
|---|---|
| Backend full-suite run, final code | **326 passed, 0 failed**, 282 warnings, 12m40s. Python 3.11.2, disposable SQLite databases. |
| `pytest tests/test_security_hardening.py -q` — before any change | **12 failed, 10 passed.** The repository's own hardening suite contradicted the previous handover: required JWT claims, Origin/cookie-write guard, `no-store`, XFF-proof throttling, reset verification budget, 422 input echo, CORS wildcard, production fail-closed and the `IntegrityError` handler were all absent. |
| `pytest tests/test_security_hardening.py -q` — final code | **22 passed.** |
| `pytest tests/test_account_lifecycle.py -q` (new) | **18 passed.** Expiry gate and reopening, refresh replay revocation, logout-all, weak password refusal, trusted-proxy identity, credential-free archives, symlink/escape refusal, report CSV neutralisation end to end, secret masking, documentation shutdown, forced change on account creation, and the Owner-target escalation guard (all six account actions plus bulk). |
| Focused authentication/RBAC/backup/vendor run | **64 passed** (account lifecycle, hardening, security workflows, RBAC, vendor master), re-run after the Owner-target guard. |
| Migration round trip | `alembic upgrade head` → `downgrade -1` → `upgrade head` succeeded on SQLite; `current_revision` = `head_revision` = **`b7c1d9e4f2a8`**; `schema_status()` = `ready`. |
| Frontend TypeScript | `npx tsc -b` — 0 errors. |
| `npm run build` | Passed TypeScript + Vite production build. Chunk-size warnings >500 kB remain (performance, not a security failure). |
| `npm run test:security` | Passed: formula neutralisation for CSV and XLSX, quoting/multiline cells, import size/row/column limits, real XLSX string-key round trip with no `<f>` element, ZIP central-directory budget and malformed-archive refusal. |
| `npm audit --audit-level=low` | **0 known advisories** (DOMPurify ≥3.4.17 via jsPDF; SheetJS removed). |
| `pip-audit -r backend/requirements.lock` | **0 known advisories** across 43 resolved dependencies. |
| `pip check` | No broken requirements in `.venv`. |
| Bandit (`backend/app`, `-ll`) | **0 High, 7 Medium, 13 Low.** All seven medium flags are B608 matches on user-facing error strings built with f-strings (`"Select an active {label} from this workspace's Master Data"` etc.); no dynamic SQL is constructed. Complements, not a substitute for, the manual SQL trace below. |
| Ruff (`F821`, `F811`, `F401`) | Undefined-name and redefinition findings cleared; remaining F821 hits are SQLAlchemy `Mapped["X"]` string forward references. Unused imports removed. |
| Manual SQL trace | Every `text(...)` occurrence and every f-string reaching `execute()` was read: the only raw SQL is the parameterless `SELECT version_num FROM alembic_version`; reports and the database browser use reflected, allow-listed identifiers with bound parameters. |
| Secret configuration checks | Production refuses placeholder signing keys, `SECRET_KEY` <32 characters, non-HTTPS CORS origins and `SECURE_COOKIES=false`. `Settings` `repr`/`str`/`safe_summary()` mask the signing key, seed password, database URL and CORS-free secrets; the validation-error handler strips `input`/`url`. |
| `git diff --check` | No whitespace errors. |

The suite exercises real database transactions and real HTTP requests through the test
client, not mocks. CI (`.github/workflows/security.yml`) runs pip-audit, bandit,
pytest, `npm audit`, `npm run test:security` and `npm run build` on Python 3.12 / Node 22.

## Deliberate limits of this evidence

- SQLite only. **PostgreSQL concurrency is not proven** (parallel refresh rotation,
  reset consumption, account and asset creation, migration timing under multiple
  workers).
- No deployed environment: TLS/HSTS termination, reverse-proxy trust, WAF/edge
  throttling, body limits before multipart parsing and network policies are
  configuration to verify, not code paths exercised here.
- No container/OS CVE scanning, image signing or registry policy.
- No real-browser CSP/UAT across charts, dialogs, attachments, PDF and XLSX exports.
- No malware scanning of uploads, no MFA/SSO, no SIEM, no external penetration test.
- No live exploitation of a deployed service and no production data or credentials.

A green run means "the checks performed passed", not "the application is
vulnerability-free". Residual risks and the deployment checklist are in
[`SECURITY_AUDIT_FINAL.md`](SECURITY_AUDIT_FINAL.md) §9–§10.
