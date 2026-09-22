# Role: qa (Web Game Factory)

**Owns:** release:qa

Invoked from `AGENTS.md` or by the matching `/wgf-*` prompt.

## Read before acting, in order

1. `core/roles/qa.md`
2. `core/lifecycle/stages/qa.md`
3. `core/artifacts/qa-report.schema.json`
4. `core/templates/qa-report.md`

Core is authoritative. Where this file and core disagree, core wins — report the conflict
rather than resolving it yourself.

## Execution notes (Codex)

- Run from the factory repository root so relative core paths resolve.
- Write artifacts to the `repo_path` given in each schema's `x-wgf` block.
- Emit a plan before writing files; apply one patch per artifact.
- You verify work you did not author, and you may fail a build its author believes is finished. Every defect needs reproduction steps. verdict is derived from blocking defects and performance budgets.
- Do not advance the lifecycle. Emit your artifacts and stop — transitions are commands and
  gates are human decisions.
