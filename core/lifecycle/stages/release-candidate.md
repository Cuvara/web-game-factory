# Release candidate

**Machine** release · **State** `rc` · **Kind** deterministic CI · **Role** release
**Contributors** qa · **Gate** G5
**Inputs** `qa-report`, `release-manifest` · **Outputs** `release-manifest` (frozen)

Freeze the candidate and decide whether it ships.

## Freezing

At this point the release manifest becomes **immutable**: a fixed commit, a fixed build,
checksums for every package, and a `frozen_at` timestamp. Any change from here produces a
new release, never an edit to this one.

This is not ceremony. Rollback is defined as re-publishing a previous manifest, which only
works if manifests are retained, complete, and trustworthy. A mutable manifest makes
rollback a rebuild, and a rebuild under pressure is how a bad situation becomes worse.

## The verify suite

`verify_suite_green` is a distinct, heavier guard from `ci_green`, and it runs here and
only here:

- smoke tests against the **built artifacts**, not the dev server
- performance benchmarks against `tech_plan.perf_budgets`
- mobile compatibility checks

CI ran on every commit through production. This runs once, on the thing that would actually
ship.

## Release artifacts

```
release/<release-id>/
  manifest.json      — the immutable record
  <platform>.zip     — one package per targeted platform
  checksums.txt
  report.md          — rendered from the manifest and QA report
```

## Gate G5

Guards: `verify_suite_green`, `candidate_frozen`. Present blocking defect count (zero) and
the accepted defects being taken on, performance per device class against budget, and the
changelog.

Reversible — a rejected candidate is cancelled and another is built — so auto-approval is
permitted (default 24h).

## Exit

- `approve` → `approved`
- `cancel` → `cancelled`

Note that approving the build is **not** authorizing publication. That is G6, deliberately
separate: an approved build can sit indefinitely at no cost, and the decision that makes it
public is the irreversible one.
