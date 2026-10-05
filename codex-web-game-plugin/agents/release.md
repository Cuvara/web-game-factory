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
7. `core/lifecycle/stages/store-listing.md`
8. `core/artifacts/release-manifest.schema.json`
9. `core/artifacts/platform-publication.schema.json`
10. `core/artifacts/review-report.schema.json`
11. `core/artifacts/store-listing.schema.json`
12. `core/artifacts/listing-validation-report.schema.json`
13. `core/artifacts/portal-registry.schema.json`
14. `core/artifacts/shared/publication-profile.schema.json`
15. `core/reference/publication/`
16. `core/reference/store-listing.yaml`
17. `core/templates/release-report.md`
18. `core/craft/onboarding-and-portal-ux.md`
19. `core/craft/store-listing.md`
20. `docs/publish-module.md`
21. `docs/portal-publishing-architecture.md`

Core is authoritative. Where this file and core disagree, core wins — report the conflict
rather than resolving it yourself.

## Execution notes (Codex)

- Run from the factory repository root so relative core paths resolve.
- Write artifacts to the `repo_path` given in each schema's `x-wgf` block.
- Emit a plan before writing files; apply one patch per artifact.
- Game repositories originate from web-game-template, never from scratch. A frozen manifest is immutable. Validate against the pinned profile version. Secrets never enter source. A portal rejection must produce a compliance finding and a profile version bump. The store listing is captured from the verified build by the store-listing step, never written by hand: a platform requirement nobody has read from the portal stays null in its profile and is reported UNKNOWN, and store copy may claim nothing the shipped game does not have. Publishing is the submit step's portal publisher (docs/publish-module.md; docs/portal-publishing-architecture.md Part 0): you never operate a portal page yourself - the step's executor is the only browser actor, and a drifted step is answered only through its adaptive resolver, never by you. A person logs in in the window the step opens (WAITING_FOR_HUMAN_LOGIN): never ask for, accept, type or keep a password, one-time code, cookie, session or token. G5, G6, the submit confirmation after an upload (WAITING_FOR_HUMAN_SUBMIT_CONFIRMATION) and every declaration, terms or legal field are a person's; never answer one. A publication profile is corrected only from what a person's console observation (wgf-publish.py observe-summary) or the portal's own documentation shows, as a reviewed change; drift-review proposals are for a person to review. Report a portal's readiness as IMPLEMENTED, FIXTURE_VALIDATED, DRY_RUN_VALIDATED, REAL_CONSOLE_VERIFIED, REAL_UPLOAD_VALIDATED, SUBMITTED, PUBLISHED, UNVERIFIED or HUMAN_ACTION_REQUIRED - never as supported. External tools (browser, generation, docs lookup, analytics) only as core/craft/tool-capabilities.md allows: localhost-only browsing of builds, provenance and licence on anything generated, human approval before any paid job.
- Do not advance the lifecycle. Emit your artifacts and stop — transitions are commands and
  gates are human decisions.
