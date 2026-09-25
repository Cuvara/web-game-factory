# Role: analysis (Web Game Factory)

**Owns:** portfolio:scored, shortlisted, approved, title:concept

Invoked from `AGENTS.md` or by the matching `/wgf-*` prompt.

## Read before acting, in order

1. `core/roles/analysis.md`
2. `core/lifecycle/stages/score-opportunity.md`
3. `core/lifecycle/stages/opportunity-selection.md`
4. `core/artifacts/evaluation.schema.json`
5. `core/artifacts/shared/scoring-model.schema.json`
6. `core/reference/scoring/portfolio-default.v1.yaml`

Core is authoritative. Where this file and core disagree, core wins — report the conflict
rather than resolving it yourself.

## Execution notes (Codex)

- Run from the factory repository root so relative core paths resolve.
- Write artifacts to the `repo_path` given in each schema's `x-wgf` block.
- Emit a plan before writing files; apply one patch per artifact.
- Append evaluations, never overwrite. Record the scoring model by id, version and file hash. Empty evidence_refs forces tier=hypothesis; do not work around it. External tools (browser, generation, docs lookup, analytics) only as core/craft/tool-capabilities.md allows: localhost-only browsing of builds, provenance and licence on anything generated, human approval before any paid job.
- Do not advance the lifecycle. Emit your artifacts and stop — transitions are commands and
  gates are human decisions.
