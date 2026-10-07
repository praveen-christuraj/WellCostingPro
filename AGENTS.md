# Agent working agreement

Read `.agent/README.md` and `.agent/memory/project.md` before making changes. Keep durable decisions in `.agent/memory/project.md` and regenerate the import graph with `make graph` after structural changes. Use `.agent/skills/` for focused workflows. Do not commit credentials, generated databases, virtual environments or build output. Test backend and build frontend before delivering. Do not silently change authorization semantics or tenant boundaries.
