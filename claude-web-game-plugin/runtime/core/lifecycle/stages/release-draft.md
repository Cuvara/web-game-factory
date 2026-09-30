# Release draft

**Machine** release · **State** `draft` · **Kind** AI-assisted · **Role** release
**Inputs** `tech-plan`, `game-design` · **Outputs** `release-manifest`

Assemble what is shipping.

## Procedure

1. **Allocate a release id** — `r1`, `r2`, … sequential per title. A title returns here for
   every shipment including hotfixes.
2. **Set the version** and the `kind` (`initial`, `content`, `hotfix`, `rollback`).
3. **Write the target platform list with roles.** This is per-release policy, not a title
   property: `r1` may ship Yandex-only and `r2` may add CrazyGames. Each entry pins the
   platform profile version the build will be validated against.
4. **Write the changelog** — what changed, in terms a player or a portal reviewer would
   recognize.
5. **Assemble store metadata per platform**: title, descriptions per required locale,
   screenshots, icon, age rating. Completeness here is the guard on G6, and a missing
   required locale is the classic late failure.
6. **Name the rollback target** — the previous known-good release manifest. Named now,
   calmly, rather than found later under pressure.

## Drafting from a verified commit

When a workflow drafts the release after its verification (the `release` step of
`core/workflows/new-game.workflow.yaml`), the draft is made only from evidence, and it also
consumes `qa-report`, `verification-report`, `sdk-report`, `prototype-report` and
`scaffold-record`:

- the newest qa-report passed, and it pins the newest verification, development and SDK
  reports — a qa-report older than later work is stale;
- every one of them names the same commit, and it is the checkout's HEAD, with a clean tree
  and the verified bundle on disk;
- the packages come from the game repository's own packaging, each recorded by checksum and
  free of sourcemaps, tests and secrets, with `index.html` at the archive root;
- evidence strength is carried per platform as observed: `PASS_MOCK` stays `PASS_MOCK`, and a
  portal's own QA stays `BLOCKED_EXTERNAL` until someone has evidence from the portal.

Otherwise there is no draft. Nothing here is published or submitted.

## Exit

`ci_green` → `qa`.

## Note

The manifest is mutable in `draft` and frozen at `rc`. After freezing, any correction
produces a **new release**, never an edit. That immutability is what makes rollback an
operation rather than a rebuild.
