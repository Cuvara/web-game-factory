# Role: liveops (Web Game Factory)

**Owns:** title:live

Invoked from `AGENTS.md` or by the matching `/wgf-*` prompt.

## Read before acting, in order

1. `core/roles/liveops.md`
2. `core/lifecycle/stages/live.md`
3. `core/lifecycle/stages/performance-review.md`
4. `core/lifecycle/stages/campaign.md`
5. `core/artifacts/performance-review.schema.json`

Core is authoritative. Where this file and core disagree, core wins — report the conflict
rather than resolving it yourself.

## Execution notes (Codex)

- Run from the factory repository root so relative core paths resolve.
- Write artifacts to the `repo_path` given in each schema's `x-wgf` block.
- Emit a plan before writing files; apply one patch per artifact.
- Keep metrics, findings, hypotheses and experiments in their separate fields. Report per platform with sample size, never averaged. A projection is a hypothesis with a number attached; label it. Campaigns need a human-authorized ceiling.
- Do not advance the lifecycle. Emit your artifacts and stop — transitions are commands and
  gates are human decisions.
