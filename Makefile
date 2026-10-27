.PHONY: test build graph up seed-admin check-admin ui-check ui-rollback daily-cost-check daily-cost-scope-check mud-cost-reconciliation-check mud-cost-kpi-check lih-worksheet-check fuel-cost-check usage-reports-check

test:
	cd backend && ../.venv/bin/python -m pytest -q
build:
	cd frontend && npm run build
graph:
	python3 .agent/tools/graphify.py
up:
	docker compose up --build
seed-admin:
	cd backend && ../.venv/bin/python -m app.seed
check-admin:
	cd backend && ../.venv/bin/python -m app.seed --check
# Render the real theme and shared components in a DOM and assert the design rules
# (light + dark). jsdom is installed with --no-save: application dependencies stay unchanged.
ui-check:
	cd frontend && npm install --no-save jsdom && \
		NODE_PATH="$$PWD/node_modules" ./node_modules/.bin/esbuild ../.agent/tools/ui-check.jsx \
		--bundle --platform=node --format=esm --jsx=automatic \
		--outfile=node_modules/.cache/ui-check.mjs --loader:.jsx=jsx --log-level=error \
		--external:jsdom && node node_modules/.cache/ui-check.mjs
# Restore the pre-design-layer interface. Use it if the enhanced UI is rejected.
ui-rollback:
	bash scripts/ui-rollback.sh

# Full daily/well printing and list-only register regressions (jsdom is a dev-only install).
daily-cost-check:
	cd frontend && npm install --no-save jsdom && \
		NODE_PATH="$$PWD/node_modules" ./node_modules/.bin/esbuild ../.agent/tools/daily-cost-check.jsx \
		--bundle --platform=node --format=esm --jsx=automatic \
		--outfile=node_modules/.cache/daily-cost-check.mjs --external:jsdom && \
		node node_modules/.cache/daily-cost-check.mjs

# Daily Cost register shortcuts: the current rig and well load as defaults and
# every related register opens already scoped to them (still changeable).
daily-cost-scope-check:
	cd frontend && npm install --no-save jsdom && \
		NODE_PATH="$$PWD/node_modules" ./node_modules/.bin/esbuild ../.agent/tools/daily-cost-scope-check.jsx \
		--bundle --platform=node --format=esm --jsx=automatic --log-level=error \
		--outfile=node_modules/.cache/daily-cost-scope-check.mjs --external:jsdom && \
		node node_modules/.cache/daily-cost-scope-check.mjs

# Mud type / Cost/BBL configuration dialog rules (section-scoped reconciliation).
mud-cost-reconciliation-check:
	cd frontend && npm install --no-save jsdom && \
		NODE_PATH="$$PWD/node_modules" ./node_modules/.bin/esbuild ../.agent/tools/mud-cost-reconciliation-check.jsx \
		--bundle --platform=node --format=esm --jsx=automatic \
		--outfile=node_modules/.cache/mud-cost-reconciliation-check.mjs --external:jsdom && \
		node node_modules/.cache/mud-cost-reconciliation-check.mjs

# Mud Cost Analysis: section KPI balances, grouped latest stock/rates and refresh.
mud-cost-kpi-check:
	cd frontend && npm install --no-save jsdom && \
		NODE_PATH="$$PWD/node_modules" ./node_modules/.bin/esbuild ../.agent/tools/mud-cost-kpi-check.jsx \
		--bundle --platform=node --format=esm --jsx=automatic --log-level=error \
		--outfile=node_modules/.cache/mud-cost-kpi-check.mjs --external:jsdom && \
		node node_modules/.cache/mud-cost-kpi-check.mjs

# LIH worksheet: multi-row entry, duplicate, paste, shortcuts and the one-save payload.
lih-worksheet-check:
	cd frontend && npm install --no-save jsdom && \
		NODE_PATH="$$PWD/node_modules" ./node_modules/.bin/esbuild ../.agent/tools/lih-worksheet-check.jsx \
		--bundle --platform=node --format=esm --jsx=automatic --log-level=error \
		--outfile=node_modules/.cache/lih-worksheet-check.mjs --external:jsdom && \
		node node_modules/.cache/lih-worksheet-check.mjs

# Fuel Cost Register: daily AGO/gas entry, company classification and material balance.
fuel-cost-check:
	cd frontend && npm install --no-save jsdom && \
		NODE_PATH="$$PWD/node_modules" ./node_modules/.bin/esbuild ../.agent/tools/fuel-cost-check.jsx \
		--bundle --platform=node --format=esm --jsx=automatic --log-level=error \
		--outfile=node_modules/.cache/fuel-cost-check.mjs --external:jsdom && \
		node node_modules/.cache/fuel-cost-check.mjs

# Reports module: usage/cost matrix, NPT/UPA matrix and the shared filter panel.
usage-reports-check:
	cd frontend && npm install --no-save jsdom && \
		NODE_PATH="$$PWD/node_modules" ./node_modules/.bin/esbuild ../.agent/tools/usage-reports-check.jsx \
		--bundle --platform=node --format=esm --jsx=automatic \
		--outfile=node_modules/.cache/usage-reports-check.mjs --loader:.jsx=jsx --log-level=error \
		--external:jsdom && node node_modules/.cache/usage-reports-check.mjs
