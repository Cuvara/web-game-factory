# QA

**Machine** release · **State** `qa` · **Kind** AI-assisted + deterministic CI · **Role** qa
**Contributors** gameplay, sdk
**Inputs** `release-manifest`, `game-design`, `tech-plan` · **Outputs** `qa-report`

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
