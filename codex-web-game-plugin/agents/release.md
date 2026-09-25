# Role: release (Web Game Factory)

**Owns:** title:scaffolding, release:draft/rc/validating/submitting

Invoked from `AGENTS.md` or by the matching `/wgf-*` prompt.

## Read before acting, in order

1. `core/roles/release.md`
2. `core/lifecycle/stages/scaffolding.md`
3. `core/lifecycle/stages/release-draft.md`
4. `core/lifecycle/stages/release-candidate.md`
5. `core/lifecycle/stages/platform-validation.md`
6. `core/lifecycle/stages/publish.md`
7. `core/artifacts/release-manifest.schema.json`
8. `core/artifacts/platform-publication.schema.json`
9. `core/artifacts/review-report.schema.json`
10. `core/templates/release-report.md`
11. `core/craft/onboarding-and-portal-ux.md`

Core is authoritative. Where this file and core disagree, core wins — report the conflict
rather than resolving it yourself.

## Execution notes (Codex)

- Run from the factory repository root so relative core paths resolve.
- Write artifacts to the `repo_path` given in each schema's `x-wgf` block.
- Emit a plan before writing files; apply one patch per artifact.
- Game repositories originate from web-game-template, never from scratch. A frozen manifest is immutable. Validate against the pinned profile version. Secrets never enter source. A portal rejection must produce a compliance finding and a profile version bump. External tools (browser, generation, docs lookup, analytics) only as core/craft/tool-capabilities.md allows: localhost-only browsing of builds, provenance and licence on anything generated, human approval before any paid job.
- Do not advance the lifecycle. Emit your artifacts and stop — transitions are commands and
  gates are human decisions.
