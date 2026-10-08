.PHONY: test build graph up seed-admin check-admin

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
