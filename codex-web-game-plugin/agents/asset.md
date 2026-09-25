# Role: asset (Web Game Factory)

**Owns:** works in title:design through production

Invoked from `AGENTS.md` or by the matching `/wgf-*` prompt.

## Read before acting, in order

1. `core/roles/implementers.md`
2. `core/artifacts/asset-manifest.schema.json`
3. `core/reference/asset-policy.yaml`
4. `core/craft/art-direction.md`
5. `core/craft/audio.md`

Core is authoritative. Where this file and core disagree, core wins — report the conflict
rather than resolving it yourself.

## Execution notes (Codex)

- Run from the factory repository root so relative core paths resolve.
- Write artifacts to the `repo_path` given in each schema's `x-wgf` block.
- Emit a plan before writing files; apply one patch per artifact.
- Contribute during design: asset cost is an input to the scope decision. Prefer library and procedural sources. No purchased or library item is integrated without a recorded license. External tools (browser, generation, docs lookup, analytics) only as core/craft/tool-capabilities.md allows: localhost-only browsing of builds, provenance and licence on anything generated, human approval before any paid job.
- Do not advance the lifecycle. Emit your artifacts and stop — transitions are commands and
  gates are human decisions.
