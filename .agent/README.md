# Repository-resident agent toolkit

These are **committed**, not ignored: a dependency graph generator (`tools/graphify.py`), durable project memory (`memory/project.md` and generated `memory/architecture.dot`), and focused agent skills (`skills/`). They work without an external agent service, account, or proprietary tool. `make graph` updates the Graphviz DOT source; an optional local `dot` binary can render it. The graph is intentionally source-only and must not include secrets or production data.

Agent workflow: read memory → inspect graph → choose skill → implement → run tests/build → update memory and graph. This is an aid to human/AI contributors, not runtime application logic.
