# QA

**Machine** release · **State** `qa` · **Kind** AI-assisted + deterministic CI · **Role** qa
**Contributors** gameplay, sdk
**Inputs** `release-manifest`, `game-design`, `tech-plan`, `scaffold-record`, `asset-manifest`, `sdk-report`
**Outputs** `verification-report`, `qa-report`

Independent verification of a built candidate.

## Two kinds of QA, deliberately separated

**Agent QA** happens during production: implement → test → fix → repeat. It is the author
checking their own work, and it is necessary.

**Independent QA** is this stage. A different role, against a built artifact, with the
authority to fail a build its author believes is finished.

> "Ready" ≠ "Approved."

Collapsing these removes the only external check on agent output. The distinction is
structural, not procedural politeness.

## The deterministic pipeline

Run by CI, not by judgement:

```
Lint → Typecheck → Unit → Integration → E2E → Build → Smoke → Performance → Platform validation
```

These produce facts. They go in `suites[]` with pass/fail counts and a run URL.

## Evidence, check by check

Every fact behind the verdict is recorded in the `verification-report`: one entry per check —
build, code, gameplay, platform, assets, policy — each `PASS`, `FAIL`, `BLOCKED` or `WARNING`,
each with the command run, the file read or the behaviour observed. The `qa-report` is
computed from it, never written beside it, so the two cannot disagree.

- `BLOCKED` is about the verification, not the build: no checkout, a missing tool, a check
  whose prerequisite did not pass. It stops the verdict, because an unverified requirement
  is not a met one.
- Gameplay — boot, loading, start, input, core loop, progression, game over, restart,
  pause/resume, mobile viewport — is observed in a browser against the built bundle. An
  interactive session recorded against the commit under test
  (`shared/gameplay-session.schema.json`) is preferred; the repository's own browser suites
  are the fallback, so verification never depends on an interactive browser tool. An aspect
  the design implies and nothing exercised is a failure, not a pass.
- Platform readiness is local and deterministic: SDK evidence per platform and the pinned
  profile's assertions. It never claims a portal's approval.

## Human and agent judgement

On top of the pipeline:

- **Browser matrix** — the target browsers on the target platforms.
- **Mobile** — on the low end of the planned device classes, not on a development machine.
- **Platform checks** per platform: SDK init, ad playback and resume, save/load,
  leaderboards. Distinct from the assertions at `release:validating`, which check the
  package rather than the behaviour.
- **Defects**, each with reproduction steps. A defect nobody can reproduce cannot be fixed
  or verified, only argued about.

## Blocking vs accepted

`blocking_defects` must be empty to reach RC. Everything else goes in `accepted_defects`
with an `accepted_rationale`, and gets read at G5. The point is that non-blocking defects
are **accepted by a human**, not silently dropped.

## Exit

- `no_blocking_defects` and `perf_budgets_met` → `rc`
- otherwise → back to the parent title's `production`

`verdict` is derived from those two conditions, not asserted. A report that says `pass`
while carrying a blocker is malformed.

## Failure modes

- **Testing the happy path.** The prototype already proved the happy path works.
- **Measuring performance on the wrong hardware.** Budgets exist per device class because
  the low end is where they break.
- **Downgrading a blocker to meet a date.** That is a G5 decision with a rationale, not a
  QA edit.
