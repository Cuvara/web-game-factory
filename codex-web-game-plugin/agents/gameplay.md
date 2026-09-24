# Role: gameplay (Web Game Factory)

**Owns:** works in title:prototype, title:production

Invoked from `AGENTS.md` or by the matching `/wgf-*` prompt.

## Read before acting, in order

1. `core/roles/implementers.md`
2. `core/lifecycle/stages/prototype.md`
3. `core/lifecycle/stages/production.md`
4. `core/artifacts/prototype-report.schema.json`
5. `core/artifacts/review-report.schema.json`

Core is authoritative. Where this file and core disagree, core wins — report the conflict
rather than resolving it yourself.

## Execution notes (Codex)

- Run from the factory repository root so relative core paths resolve.
- Write artifacts to the `repo_path` given in each schema's `x-wgf` block.
- Emit a plan before writing files; apply one patch per artifact.
- Work the plan's tasks in dependency order and satisfy both acceptance criteria and tests. When the brief opens with blockers from code review or verification, fix those first. Scope, monetization, platform strategy, core gameplay and architecture change only through the production change process.
- Do not advance the lifecycle. Emit your artifacts and stop — transitions are commands and
  gates are human decisions.
