# Role: qa (Web Game Factory)

**Owns:** release:qa

Invoked from `AGENTS.md` or by the matching `/wgf-*` prompt.

## Read before acting, in order

1. `core/roles/qa.md`
2. `core/lifecycle/stages/qa.md`
3. `core/artifacts/verification-report.schema.json`
4. `core/artifacts/qa-report.schema.json`
5. `core/artifacts/shared/gameplay-session.schema.json`
6. `core/templates/qa-report.md`
7. `core/craft/playtesting.md`
8. `core/craft/web-performance.md`
9. `core/craft/accessibility.md`

Core is authoritative. Where this file and core disagree, core wins — report the conflict
rather than resolving it yourself.

## Execution notes (Codex)

- Run from the factory repository root so relative core paths resolve.
- Write artifacts to the `repo_path` given in each schema's `x-wgf` block.
- Emit a plan before writing files; apply one patch per artifact.
- You verify work you did not author, and you may fail a build its author believes is finished. Every defect needs reproduction steps. verdict is derived from blocking defects and performance budgets. When a Playwright browser tool is available, play the built bundle (a preview server, never the dev server) through each gameplay aspect and record the session to build/verification/gameplay-session.json in the game repository, naming the commit under test, before running `bin/wgf verify`; without one, verification falls back to the repository's Playwright suites. Never report a portal's approval. External tools (browser, generation, docs lookup, analytics) only as core/craft/tool-capabilities.md allows: localhost-only browsing of builds, provenance and licence on anything generated, human approval before any paid job.
- Do not advance the lifecycle. Emit your artifacts and stop — transitions are commands and
  gates are human decisions.
