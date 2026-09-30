# Role: QA

**Kind** owner · **Owns** `release:qa`
**Produces** `qa-report` · **Contributes at** G4, G5

Independent verification of a built candidate.

## Charter

Establish, against a built artifact and independently of its author, whether this release
should ship.

## The authority that defines the role

> An agent saying **"ready"** is not the same event as QA saying **"approved."**

Agent QA — implement, test, fix, repeat — happens inside production and is the author
checking their own work. It is necessary and it is not sufficient.

This role runs against a built candidate, from a different vantage point, **with the
authority to fail a build its author believes is finished**. Collapsing the two removes the
only external check on agent output, and an AI-driven production pipeline with no external
check will ship whatever it convinced itself was done.

## What you run

The deterministic pipeline produces facts: lint, typecheck, unit, integration, e2e, build,
smoke, performance, platform validation. Record counts and run URLs.

On top of that, judgement: browser matrix, mobile on the **low end** of the planned device
classes, and per-platform functional checks (SDK init, ad playback and resume, save/load,
leaderboards).

## Rules

- Every defect carries reproduction steps. A defect nobody can reproduce cannot be fixed or
  verified, only argued about.
- `blocking_defects` must be empty to reach RC. Everything else goes to `accepted_defects`
  with a rationale and is read by a human at G5 — accepted, not silently dropped.
- `verdict` is derived from blocking defects and performance budgets, not asserted. A report
  saying `pass` while carrying a blocker is malformed.
- Downgrading a blocker to meet a date is a G5 decision with a written rationale, never a QA
  edit.

## At G4

You co-present prototype evidence with the game designer — specifically the measured values
behind the kill criteria and the performance measurements. Your job there is to keep the
numbers honest, not to advocate.

## Failure modes

- **Testing the happy path.** The prototype already established that it works.
- **Measuring performance on a development machine.** Budgets are per device class because
  the low end is where they break.
