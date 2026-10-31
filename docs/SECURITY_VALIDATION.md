# Executed security validation — 2026-10-31

## Results

| Check | Executed result |
|---|---|
| Backend full-suite run (SQLite, intermediate patch) | **305 passed, 4 failed**, 278 warnings, 18m39s. The failures were three readable-validation-message regressions and one numeric CSV formatting regression introduced during hardening. |
| Updated focused authentication/backup/vendor/validation run | **56 passed**, 42 warnings. |
| Final affected-path retest, including every full-run failure | **68 passed**, 53 warnings, 4m00s. Covers security-hardening, complete backup and database-browser suites, the two affected daily-cost cases and affected mud-cost case. |
| Backend test inventory | **313 collected cases** after added regressions. The full run covered 309 cases; the affected-path retests cover the four subsequently added cases too. No unresolved test failure remains from these runs. A fresh single-pass full-suite run after the final fixes was **not** performed; CI is configured to run it. |
| `npm run test:security --prefix frontend` | Passed. Formula prefixes/whitespace, CSV quotes/multiline cells, import limits, actual XLSX string-cell round trip, absence of formula XML, ZIP directory size budget/invalid archives. |
| `npm run build --prefix frontend` | Passed TypeScript and Vite production build. Existing >500 kB chunk-size warnings remain (performance, not a security scan failure). |
| `npm audit --prefix frontend --audit-level=low` | **0 known advisories**, after replacing SheetJS and updating the affected PDF transitive dependency. |
| `pip-audit -r backend/requirements.lock` | **0 known advisories** in 43 resolved dependencies. The unpinned input requirements were also audited before creating the release lock. |
| `.venv/bin/pip check` | No broken requirements. |
| Bandit (`backend/app`) | **0 high, 7 medium, 10 low** static flags; manually triaged in the review. Medium f-string flags are error messages rather than SQL execution. The scan is not being represented as clean/zero-findings. |
| Secret configuration checks | Placeholder production signing keys rejected; settings representations and validation exception text do not expose supplied signing/seed/database secrets. |
| `git diff --check` / `make graph` | Passed; architecture graph regenerated. |

The final targeted tests exercise real database transactions and test-client HTTP requests,
not only mocks. Backend tests were run on disposable SQLite databases on Python 3.11;
the production/CI template uses Python 3.12 and PostgreSQL still requires IT verification.
No production credentials or data were used, and no live vulnerability exploitation was
performed against a deployed service.

## Regression coverage added

- JWT expiry/tenant/type/version requirements, including rejection of refresh-type JWTs.
- Browser Origin checks on refresh and no-store/security headers on authenticated data.
- Forwarded-header spoofing cannot reset the recovery-request IP budget.
- Reset-code verification and login request budgets.
- Validation does not echo passwords; database uniqueness errors return generic 409.
- Exact-origin CORS and production fail-closed configuration.
- CSV text neutralization without corrupting typed negative numbers.
- Archives exclude credentials/access control, reject forged tenant IDs/FK targets,
  reject oversized inflation, and use unique filenames even with shared workspace folders.
- Spreadsheet replacement output/import behavior and ZIP preflight.

## Not tested here — mandatory external release gates

- PostgreSQL integration, parallel refresh/reset/account/asset mutation races, migration
  timing under multiple production workers, and large-data restore performance.
- Actual TLS certificates, HSTS, reverse-proxy trust, origin/host routing, atomic distributed
  edge throttling, body limits before multipart parsing, and infrastructure network policies.
- Container/OS CVEs, image signing/digest pinning, encrypted disaster-recovery backup and restore.
- Real-browser CSP/UAT across charts, dialogs, attachments, PDF and XLSX exports.
- Malware scanning/content disarm, SSO/MFA, secrets manager, SIEM and external audit retention.
- Deployed authenticated DAST and independent penetration testing.

Use `SECURITY_REVIEW_2026-10-31.md` as the IT handover and release checklist. These results
are evidence of the executed checks, **not a statement that the application is vulnerability-free**.
