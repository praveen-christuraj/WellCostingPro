#!/usr/bin/env bash
# Roll the UI back to the state it had before the design-token layer (the "UI design layer"
# described in .agent/memory/project.md). Use it when the enhanced interface is rejected:
# it restores every application UI file from the pre-design-layer baseline and removes the
# files the layer added, leaving behaviour, routes, permissions and data untouched.
#
#   make ui-rollback        (or: bash scripts/ui-rollback.sh)
#
# It only touches the working tree — nothing is committed — so `git checkout .` /
# `git restore .` undoes the rollback itself if it was run by mistake.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Baseline commit: the tag created when the design layer landed, with the SHA as a fallback
# in case the tag was never pushed to this clone.
BASELINE_REF="ui-pre-design-layer"
BASELINE_SHA="82f952c495f07174d7897e98aeaab51281b0e53b"
if ! git rev-parse --verify --quiet "$BASELINE_REF" >/dev/null; then
  BASELINE_REF="$BASELINE_SHA"
fi
if ! git rev-parse --verify --quiet "$BASELINE_REF" >/dev/null; then
  echo "error: neither the tag ui-pre-design-layer nor $BASELINE_SHA exists in this clone." >&2
  echo "       Fetch the branch history (git fetch --tags origin) and run again." >&2
  exit 1
fi

# Files the design layer changed. Everything else in the repository is left alone.
RESTORED=(
  frontend/index.html
  frontend/package.json
  frontend/package-lock.json
  frontend/src/main.tsx
  frontend/src/theme.ts
  frontend/src/styles.css
  frontend/src/lib/api.ts
  frontend/src/components/Brand.tsx
  frontend/src/components/Common.tsx
  frontend/src/components/DataTable.tsx
  frontend/src/components/ImportDialog.tsx
  frontend/src/components/Layout.tsx
  frontend/src/components/OrderDocumentsDialog.tsx
  frontend/src/components/afe/AfeDeletedTab.tsx
  frontend/src/pages/CatalogueLists.tsx
  frontend/src/pages/DailyCostManagement.tsx
  frontend/src/pages/DeletedMasterData.tsx
  frontend/src/pages/Login.tsx
  frontend/src/pages/Permissions.tsx
  frontend/src/pages/RigWellDeleted.tsx
  frontend/src/pages/Roles.tsx
)

# Files the design layer added; they have no baseline version, so they are deleted.
ADDED=(
  frontend/src/designSystem.ts
  .agent/memory/design-system.md
  .agent/skills/ui-design.md
  .agent/tools/ui-check.jsx
)

echo "Rolling the UI back to $(git rev-parse --short "$BASELINE_REF") ($BASELINE_REF)"

missing=()
for file in "${RESTORED[@]}"; do
  if git cat-file -e "$BASELINE_REF:$file" 2>/dev/null; then
    git checkout "$BASELINE_REF" -- "$file"
    echo "  restored  $file"
  else
    missing+=("$file")
  fi
done

for file in "${ADDED[@]}"; do
  if [ -e "$file" ]; then
    rm -f "$file"
    echo "  removed   $file"
  fi
done

if [ "${#missing[@]}" -gt 0 ]; then
  echo "warning: not present in the baseline (left as-is): ${missing[*]}" >&2
fi

cat <<'NEXT'

Rollback applied to the working tree (nothing committed). Next:
  cd frontend && npm run build          # the pre-layer UI must still build
  cd backend && ../.venv/bin/python -m pytest -q
Then review `git diff` and commit when you are happy, for example:
  git add -A && git commit -m "revert(ui): roll back the design-token layer"

If the rollback is permanent, also drop the now-dead references to the design layer:
the "UI design layer" section in .agent/memory/project.md, the design-system sentences in
AGENTS.md and README.md, and the ui-check/ui-rollback targets in the Makefile.
NEXT
