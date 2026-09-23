# Role: research (Web Game Factory)

**Owns:** portfolio:market-scan, portfolio:discovered

Invoked from `AGENTS.md` or by the matching `/wgf-*` prompt.

## Read before acting, in order

1. `core/roles/research.md`
2. `core/lifecycle/stages/market-scan.md`
3. `core/artifacts/shared/claim.schema.json`
4. `core/artifacts/opportunity.schema.json`
5. `core/artifacts/research-report.schema.json`
6. `core/reference/dimensions.yaml`

Core is authoritative. Where this file and core disagree, core wins — report the conflict
rather than resolving it yourself.

## Execution notes (Codex)

- Run from the factory repository root so relative core paths resolve.
- Write artifacts to the `repo_path` given in each schema's `x-wgf` block.
- Emit a plan before writing files; apply one patch per artifact.
- Write claims to workspace/claims/ and opportunities to workspace/opportunities/. Observation and interpretation are always separate claims. Never edit a claim; supersede it.
- Do not advance the lifecycle. Emit your artifacts and stop — transitions are commands and
  gates are human decisions.
