# Skill: interface design work (critique → deslop → polish)

Use this for any UI change, new page or visual review. Read `.agent/memory/design-system.md`
first and follow the Standing product conventions in `.agent/memory/project.md`.

**Critique before changing anything.** Name the screen, the user's task and the three weakest
things about it (hierarchy, density, feedback, discoverability). Do not restyle what already
works: if a page uses `PageHeading`, `DataTable`, `FormDialog` and `Tag`, it is already on the
design system and only its content is in scope.

**Deslop.** Delete before adding: duplicated labels, a heading that repeats the nav, decorative
icons, chips that restate the column they sit in, empty wrappers, unused tokens and components
nobody renders. Every element must earn its space or go.

**Polish with tokens only.** Colours, radii, shadows, spacing, type and motion come from
`frontend/src/designSystem.ts` (and its `--wcp-*` mirror in `styles.css`) — never from a literal
in a page. Add a token if one is missing, in both layers, and use it.

**Pre-ship checklist.** Both themes; keyboard focus ring on every control; labels on every
field; `aria-expanded`/`aria-haspopup` on disclosures; `role="alert"` on errors; 44px hit areas
under `@media (pointer: coarse)`; no page-level horizontal scroll at 1440/1024/768; no
information by colour alone; motion only for state feedback and disabled by
`prefers-reduced-motion`; dialogs still close only via Cancel (and pass `danger` for
irreversible actions).

**Verify.** `cd frontend && npm run build`; the design-layer check
`.agent/tools/ui-check.jsx` (run command in its header); `cd backend && ../.venv/bin/python -m
pytest -q`; then look at the running app in light and dark.

**Never diminish functionality for looks.** No route, permission, filter, pagination option,
import/export path or dialog rule may change as a side effect of a visual change. If a visual
idea requires removing behaviour, stop and say so.

**Rollback.** The current UI layer is reversible: `make ui-rollback` restores the pre-design-layer
interface from tag `ui-pre-design-layer`. If the user rejects the enhanced UI, run it, re-run the
checks above, and remove the design-layer notes from `.agent/memory/project.md`.
