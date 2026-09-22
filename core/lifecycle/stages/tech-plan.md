# Technical plan

**Machine** title · **State** `tech-plan` · **Kind** AI-assisted · **Role** architect
**Contributors** asset, sdk, gameplay · **Gate** G3
**Inputs** `game-design`, `title-strategy`, `asset-manifest` · **Outputs** `tech-plan`

Engine, architecture, performance budgets, repository parameters, and the development plan
the coding agent works from.

## Engine selection

PixiJS for 2D, Three.js for 3D. No other engine is supported by the template and none
should be introduced. The choice is driven by the game, and the rationale must be about
cost and constraint — load budget, asset pipeline, mobile performance — not preference.

Engine selection lives in this state rather than one of its own because `engine.type` is a
repository-creation parameter. Decide the engine, then create the repo. That ordering is
load-bearing, and it is why the old lifecycle's separate `ENGINE SELECTION` stage was
removable without losing anything.

## The development plan is the important part

A coding agent handed only a GDD will invent scope — it has to, because a GDD does not say
what to build first, what "done" means, or how to prove it. The plan supplies:

- **Milestones** with exit criteria and day estimates
- **Tasks** with ids, dependencies, **acceptance criteria**, and **tests**
- Asset references per task, so art and code do not block each other invisibly

Acceptance criteria and tests are required by the schema. A task without them cannot be
verified and will be reported complete when it is not.

A task should look like:

```yaml
id: GAME-023
title: Implement enemy spawning
milestone: M2
dependencies: [GAME-010, GAME-018]
acceptance_criteria:
  - Enemies spawn at configured intervals from configured points
  - Spawn rate is data-driven, not hard-coded
  - No runtime errors across a five-minute session
tests:
  - unit/enemy-spawn.spec.ts
```

## Also produced here

- **Performance budgets** per device class, checked by the verify suite at release.
  Budgets set after measuring are not budgets. `max_bundle_mb` must respect the tightest
  limit across required platform profiles.
- **Ownership split** — what is generic (template), game-specific, platform-specific,
  agent responsibility, CI responsibility. This is the section that prevents the most
  common scaffolding mistake: reimplementing in the game what the template already provides.
- **`repo_params`**, including the complete `game.config.yaml` content to be written at
  scaffolding, with platforms pinned as `<platform-id>@<profile-version>`.

## Gate G3

Guards: `engine_selected`, `asset_manifest_present`, `plan_fits_timebox`. Design and plan
are approved together deliberately — splitting them adds a gate to a cycle that already
has too many, and they are not independently actionable. Approving a design whose plan
does not fit the timebox decides nothing.

Present the consistency result including rules that nearly failed, milestone estimates
against the timebox, and how much asset cost is not yet sourced.

## Failure modes

- **Plan that restates the GDD.** If a task says "implement the core loop", the plan has
  not been written.
- **Estimates summing neatly to the timebox.** Estimates that exactly fit were fitted.
- **3D by default.** Three.js costs load time, asset pipeline complexity and mobile
  performance. It needs a reason.
