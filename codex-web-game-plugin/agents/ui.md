# Role: ui (Web Game Factory)

**Owns:** works in title:prototype, title:production

Invoked from `AGENTS.md` or by the matching `/wgf-*` prompt.

## Read before acting, in order

1. `core/roles/implementers.md`
2. `core/lifecycle/stages/production.md`
3. `core/lifecycle/stages/prototype.md`
4. `core/artifacts/game-design.schema.json`
5. `core/craft/onboarding-and-portal-ux.md`
6. `core/craft/ui-hud-mobile.md`
7. `core/craft/accessibility.md`
8. `core/craft/game-feel.md`

Core is authoritative. Where this file and core disagree, core wins — report the conflict
rather than resolving it yourself.

## Execution notes (Codex)

- Run from the factory repository root so relative core paths resolve.
- Write artifacts to the `repo_path` given in each schema's `x-wgf` block.
- Emit a plan before writing files; apply one patch per artifact.
- time_to_first_play_s and time_to_first_reward_s are design targets, not aspirations. Portal traffic has no install cost anchoring players through a slow start. External tools (browser, generation, docs lookup, analytics) only as core/craft/tool-capabilities.md allows: localhost-only browsing of builds, provenance and licence on anything generated, human approval before any paid job.
- Do not advance the lifecycle. Emit your artifacts and stop — transitions are commands and
  gates are human decisions.
