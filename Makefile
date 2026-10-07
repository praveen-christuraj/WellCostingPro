.PHONY: test build graph up

test:
	cd backend && ../.venv/bin/python -m pytest -q
build:
	cd frontend && npm run build
graph:
	python3 .agent/tools/graphify.py
up:
	docker compose up --build
