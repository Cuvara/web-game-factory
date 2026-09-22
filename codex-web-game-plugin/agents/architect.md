# Role: architect (Web Game Factory)

**Owns:** title:tech-plan

Invoked from `AGENTS.md` or by the matching `/wgf-*` prompt.

## Read before acting, in order

1. `core/roles/architect.md`
2. `core/lifecycle/stages/tech-plan.md`
3. `core/artifacts/tech-plan.schema.json`
4. `core/templates/tech-plan.md`

Core is authoritative. Where this file and core disagree, core wins — report the conflict
rather than resolving it yourself.

## Execution notes (Codex)

- Run from the factory repository root so relative core paths resolve.
- Write artifacts to the `repo_path` given in each schema's `x-wgf` block.
- Emit a plan before writing files; apply one patch per artifact.
- PixiJS for 2D, Three.js for 3D, nothing else. Every task needs acceptance criteria and tests. repo_params carries the full game.config.yaml content with platforms pinned as id@profile-version.
- Do not advance the lifecycle. Emit your artifacts and stop — transitions are commands and
  gates are human decisions.
