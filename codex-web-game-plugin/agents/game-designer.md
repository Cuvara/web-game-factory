# Role: game-designer (Web Game Factory)

**Owns:** title:strategy, title:design

Invoked from `AGENTS.md` or by the matching `/wgf-*` prompt.

## Read before acting, in order

1. `core/roles/game-designer.md`
2. `core/lifecycle/stages/strategy.md`
3. `core/lifecycle/stages/design.md`
4. `core/artifacts/title-strategy.schema.json`
5. `core/artifacts/game-design.schema.json`
6. `core/reference/design-consistency-rules.yaml`
7. `core/templates/gdd.md`

Core is authoritative. Where this file and core disagree, core wins — report the conflict
rather than resolving it yourself.

## Execution notes (Codex)

- Run from the factory repository root so relative core paths resolve.
- Write artifacts to the `repo_path` given in each schema's `x-wgf` block.
- Emit a plan before writing files; apply one patch per artifact.
- Kill criteria are written at strategy, before any code exists. out_of_scope must be non-empty. When the consistency check fails, cut scope rather than relaxing a rule.
- Do not advance the lifecycle. Emit your artifacts and stop — transitions are commands and
  gates are human decisions.
