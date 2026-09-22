# Platform validation

**Machine** release · **State** `validating` · **Kind** deterministic CI · **Role** release
**Contributors** sdk
**Inputs** `release-manifest` · **Outputs** `platform-publication` (one per platform)

Run each targeted platform profile's assertions against the actual built package.

## What this stage is not

It is **not** where platform requirements are discovered. Every assertion here corresponds
to a requirement the design was already bound to at `strategy` and `design`, when the
platform profiles were read as binding constraints and recorded in
`game_design.platform_constraints_applied`.

By the time you reach this stage you are **re-checking a known constraint**. If validation
surprises you, the design drifted — and the fix is a design conversation, not a packaging
tweak.

This is the correction to the most expensive defect in the original workflow, where
`PLATFORM VALIDATION` sat after the build and was the first point at which anyone
discovered that Yandex requires Russian localization.

## Procedure

Per targeted platform:

1. Resolve the profile at the **pinned version** from the release manifest. Not the current
   version — the build was made against the pinned rules and must be judged by them.
2. Shape the package to the profile: bundle limits, orientation, SDK wiring, entry point.
3. Run the profile's `assertions[]`. Record every result, including passes, in
   `assertion_results`.
4. Blocking failure → `validation-failed`, carrying the failing assertion ids. This is what
   lets remediation target a named rule rather than "platform validation failed".

## Exit

- every targeted platform `validated` → `submitting`
- any required platform failed → back to the parent title's `production`, carrying the
  assertion ids

## Failure modes

- **Validating against the latest profile instead of the pinned one.** That makes builds
  non-reproducible and produces failures that did not exist when the work was approved.
- **Treating a failure as a packaging problem.** Sometimes it is. Often it means the design
  absorbed a constraint incorrectly, and patching the package hides that.
