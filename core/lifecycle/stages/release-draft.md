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

## Exit

`ci_green` → `qa`.

## Note

The manifest is mutable in `draft` and frozen at `rc`. After freezing, any correction
produces a **new release**, never an edit. That immutability is what makes rollback an
operation rather than a rebuild.
