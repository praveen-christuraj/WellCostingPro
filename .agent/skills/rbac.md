# Skill: change RBAC safely

1. Define the capability in the provisioned baseline only if it guards an actual API feature; custom business capabilities are created via API.
2. Add the API policy with `Depends(require("resource:action"))`. Scope every record lookup to `current_user.organization_id`; reject foreign IDs in assignments.
3. Never trust permission keys or organization IDs from clients as proof of authority. Do not allow nonowners to grant capabilities they do not possess.
4. Protect the owner from deletion, deactivation, assignment, and role edits. Check JWT version and active flag for every protected call.
5. Fetch data from the API and gate UI actions with `can()`, but remember the API is the security boundary.
6. Add negative tests for forbidden actions and cross-tenant IDs, run pytest, and update durable memory.
