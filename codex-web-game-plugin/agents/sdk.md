# Role: sdk (Web Game Factory)

**Owns:** works in title:prototype, production, release:validating

Invoked from `AGENTS.md` or by the matching `/wgf-*` prompt.

## Read before acting, in order

1. `core/roles/implementers.md`
2. `core/reference/platforms/`
3. `core/artifacts/shared/platform-profile.schema.json`
4. `core/craft/onboarding-and-portal-ux.md`

Core is authoritative. Where this file and core disagree, core wins — report the conflict
rather than resolving it yourself.

## Execution notes (Codex)

- Run from the factory repository root so relative core paths resolve.
- Write artifacts to the `repo_path` given in each schema's `x-wgf` block.
- Emit a plan before writing files; apply one patch per artifact.
- Game code never calls a portal SDK directly; it calls the abstraction. Integrate during prototype, not production, so monetization is proven in context. External tools (browser, generation, docs lookup, analytics) only as core/craft/tool-capabilities.md allows: localhost-only browsing of builds, provenance and licence on anything generated, human approval before any paid job.
- Do not advance the lifecycle. Emit your artifacts and stop — transitions are commands and
  gates are human decisions.
