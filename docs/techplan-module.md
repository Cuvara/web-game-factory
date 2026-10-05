# Tech-Plan Module

`tech-plan` in `core/workflows/new-game.workflow.yaml`, serving `title:tech-plan`, followed
by the `tech-plan-review` checkpoint (gate G3). Written against
[workflow-module-contract.md](workflow-module-contract.md); it changes nothing in the engine.

```
game-design ──► engine (as the design declares it) ─┐
title-strategy ─► pinned platforms, budgets ─────────┼─► repo_params.game_config ─► tech-plan
                                                     └─► dev_plan (milestones, tasks)
```

**This is a minimal, honest planner, not a research-grade one.** It maps what the design and
the strategy already decided onto the tech-plan contract, and estimates with a heuristic
that is written down below. It does not evaluate engines, invent architecture, or know
anything about a genre. What it guarantees is that the plan G3 reviews is complete,
schema-valid and traceable to its inputs, and that the engine and platforms init writes
into the game repository are the ones that were reviewed.

| File | Holds |
|---|---|
| `scripts/wgf_techplan/selection.py` | Engine selection and platform pinning. Pure. |
| `scripts/wgf_techplan/devplan.py` | Milestones, tasks and the estimate heuristic. Pure. |
| `scripts/wgf_techplan/step.py` | `TechPlanStep`, `factory.techplan` settings, the artifact |
| `scripts/tests/test_techplan_module.py` | Unit, engine-contract (G3), failure-path and schema tests |

## Engine: the design's decision

`game_design.engine.type` is taken as declared — including `phaserjs`, the second 2D engine.
The module's only engine knowledge is the template's mapping from dimensionality to a
**default** engine id — `2d → pixijs`, `3d → threejs`, from the tech-plan schema's enum — and
the template's package name for each, used in the architecture text. There is no PixiJS-,
Phaser- or Three.js-specific logic anywhere else.

Both 2D engines map back to `2d`, so nothing about dimension changes; what a design cannot do
is get Phaser without asking for it. `dimension: 2d` alone still selects `pixijs`, which is
what every title planned before Phaser existed recorded.

| The design says | Result | `metadata.engine_source` |
|---|---|---|
| `engine.type` | that engine | `design.engine.type` |
| only `engine.dimension` | the template's default engine for it (`2d` → `pixijs`) | `design.engine.dimension` |
| neither, but its asset lists use 3D-only kinds (`model`, `environment`…) | `threejs` | `design assets` |
| neither, and its assets are all 2D kinds | `pixijs` | `design assets` |
| `engine.type` and `engine.dimension` disagree | `FAILED`, not retryable | — |
| nothing either way | `FAILED`, not retryable: guessing a renderer is what G3 stops | — |

Asset kinds and their dimension come from `core/reference/asset-policy.yaml`. The fallback
exists for designs written before `engine` was recorded (the asset fixtures are such
designs); its rationale says the engine was inferred and asks for a superseding design.

## Physics: this plan's decision, and only this plan's

`architecture.physics` records how the game detects and resolves collisions, and the exact
package if it needs one. Nothing is inferred from the design — the same rule as the engine,
one rung lower. The default for both engines is `custom`: collision and overlap tests in
`src/game/`, engine-free, unit-testable, no dependency.

A simulation library is a dependency, a payload against `max_bundle_mb` and a source of
non-determinism, so it is an architect's decision at G3, taken with the step's `with:` block:

```yaml
- id: tech-plan
  with: {physics: rapier}      # custom (default) | rapier | cannon-es
```

| Choice | Package written into the plan | |
|---|---|---|
| `custom` | none | The default. `pixijs` and `threejs` |
| `rapier` | `@dimforge/rapier2d-compat` / `@dimforge/rapier3d-compat` | Per engine |
| `cannon-es` | `cannon-es` | `threejs` only |

Anything else, and any choice with no build for the selected engine, is `FAILED`, not
retryable. The ladder and the reasons for each rung are `core/craft/3d-scene-and-physics.md`.

The develop brief quotes this line and allows the developer to add **only** the package it
names ([development-module.md](development-module.md)); the reviewer treats an unplanned
physics dependency as a blocker (`core/craft/gameplay-review.md`). Adding one later is a
superseding tech-plan through G3, not a development decision.

## Platforms: the strategy's pins

Each `title_strategy.platform_set[]` entry must resolve to
`core/reference/platforms/<id>.yaml` at the pinned `profile_version`, and becomes the
template's `game.config.yaml` entry `{id, profile: <id>@<version>, role}`. Required
platforms come first because the template's `primaryPlatform()` is the first required
entry. A missing profile, or one whose version moved since the strategy pinned it, is
`BLOCKED`: re-pin in a superseding strategy. Nothing here knows what any portal is.

A profile is not enough: the pinned template must carry the platform's SDK adapter, or the
build throws at boot. The adapter list is `workspace/config/template.lock.json`
`platform_adapters` (the pinned registry's `KNOWN_PLATFORM_IDS`, held equal by
`check-integrity.py`), and a platform outside it is `BLOCKED` with "<Name> needs a template
release carrying its SDK adapter (HUMAN_ACTION_REQUIRED: release and pin)" (`selection.py`
`require_adapters`). Strategy refuses the same platforms earlier. GamePix is the case today
(`docs/platform-targets-2026-10.md`).

From the profiles:

- `perf_budgets.max_bundle_mb` — the tightest `requirements.max_bundle_mb` across required
  platforms (all platforms, if none is required).
- `release_requirements` — every blocking assertion of every target, as `<pin>: <id>`.
- one hardening task per platform, whose acceptance criteria are its blocking assertions.

`repo_params.game_config.monetization.ad_kinds` is the design's placement kinds,
deduplicated, `iap` separately — derived, never decided here, so release validation can
check a declaration rather than a run.

## The development plan

| Milestone | Phase | Tasks |
|---|---|---|
| `M1` Playable core loop | prototype | `CORE-001` (boot on the template with the engine) + one `GAME-nnn` per `mvp` feature + one `CONTENT-nnn` per batch of MVP content units |
| `M2` Production scope (at `release`: "Release scope, built before G4") | production | one `GAME-nnn` per `post-mvp` feature + - when the run's tier builds the post-mvp tier - one `CONTENT-nnn` per batch of post-mvp content units; omitted if none |
| `M3` Platform integration and hardening | hardening | one `SDK-nnn` per target platform + `QA-001` (verify suite green) |

A feature task's acceptance criteria are the feature's own. `optional` features get no task,
and neither does a feature whose evaluation (game-design 1.10.0) is `later` or `cut`.
A design with no `features` (an older schema) falls back to `scope.tiers.mvp` and
`scope.tiers.production`; those carry no criteria, and the generated criterion says so —
which is what the reviewer at G3 should see.

**What the run builds before G4: the quality tier** (tech-plan 1.1.0 `dev_plan.build_scope`).
The run's quality tier is the design's `build_spec.content.quality_tier`, else the strategy's
`concept.content_model.quality_tier`, else `mvp` (a strategy before title-strategy 1.5.0
states none, and is planned as it always was). What a tier builds is data,
`core/reference/quality-benchmark.yaml` `tiers[].builds`: at `mvp` the `mvp` design tier and
the prototype phase (M1); at `release` the `mvp` and `post-mvp` design tiers and the prototype
and production phases (M1 and M2). In `new-game` the step after G4 is the store listing and
then release - nothing is built after G4 - so at `release` every feature the design includes
and every unit the release ships is planned **and built** before G4: the developer's brief
carries M1 and M2 (`docs/development-module.md`). Before WS-3 the plan kept only `tier: mvp`
units, and `M2` was planned but never built in `new-game`, so a release was the MVP by
construction (`docs/quality-gap-audit-2026-10.md`, finding 1). The tier and what it builds are read
through `scripts/wgflib/build_scope.py`, the same reading the judging steps use without a
tech plan among their inputs (playability's design units, content-sufficiency's owed units,
verification's content conformance), so a unit the plan built is never an unknown unit to
the bot that plays it.

**Content tasks.** The design's content units of the tiers the run builds
(`build_spec.content.units`, game-design 1.9.0) are planned as work, not left implicit in the
feature tasks: one `CONTENT-nnn` per batch of `implementation.task_batch` units (3, from
`core/reference/genre-models.yaml`) - MVP units batched into M1, a release's post-mvp units
into M2, so a batch never mixes them - in the design's index order — the order *is* the difficulty curve. Each task carries every unit's
own `acceptance` lines plus two generated ones per unit: that the unit is in
`public/content/units.json` with the design's difficulty values, and that it is reachable from
the unit before it in play (or, for the first, that it is where play starts); where the unit
states them (game-design 1.12.0), the first also names its `group`, `structure`, `elements` and
`objective_kind`, which the develop checks compare. Its tests are
`tests/unit/content.test.ts`, and it depends on `CORE-001` and on the `GAME-nnn` tasks of the
mechanics its units ask for — a level cannot be built before the verb it is made of. Estimated
at `implementation.content_unit_hours` (1.5) per unit, so the content is in the timebox total
that `plan_fits_timebox` is asked about. A design whose `generation.mode` is not `authored`
gets **no** content task: a parametric or procedural design generates its units from
parameters, and there is no list to build one against (`devplan.content_units`).

**Estimates**, in hours, all overridable under `factory.techplan.estimates`:

| Key | Default | Applies to |
|---|---|---|
| `core_hours` | 3 | `CORE-001` |
| `feature_base_hours` + `per_criterion_hours` × criteria (min 1) | 2 + 1.5 × n, capped at `feature_max_hours` 12 | each feature task |
| `platform_base_hours` + `per_assertion_hours` × blocking assertions | 3 + 0.5 × n | each platform task |
| `qa_hours` | 4 | `QA-001` |
| `hours_per_day` | 6 | milestone `est_days` = hours ÷ this, rounded **up** to a half day |

This installation calibrates the estimates in `workspace/config/factory.yaml`
(`factory.techplan.estimates`, from measured live-build agent time; derivation in
`docs/handoff/2026-09-27-production-validation.md`). The defaults above are the uncalibrated
heuristic every other installation starts from.

The total is compared with `title_strategy.timebox_days × overrun_tolerance`
(`workspace/config/portfolio.yaml`) and reported — `metadata.fits_timebox`, and a `high`
technical risk when it overruns — but **never adjusted to fit**. `plan_fits_timebox` is
G3's question; estimates that sum neatly to the budget were fitted
(`core/lifecycle/stages/tech-plan.md`).

## The develop budget: derived from the plan

The plan derives the developer-session budget its own tasks need (`dev_plan.develop_budget`,
tech-plan 1.1.0, `scripts/wgf_techplan/budget.py`), from `core/reference/quality-benchmark.yaml`
`develop` - values with their calibration basis, never a number in code:

| | |
|---|---|
| build hours | the `est_hours` of every task in a phase the tier builds (CORE, GAME, CONTENT; a CONTENT task is `content_unit_hours` per unit) |
| sessions | `ceil(build hours / session_task_hours) + rework_sessions` (8 h a session, 6 sessions of greybox pass and routed returns; both `proposed`) |
| cost | `sessions x session_cost` (3.5, `measured-2`: the two validation runs' US$62.86 / 18 and US$29.25 / 9) |

The record carries its `basis` (the hours, the task ids, the content tasks and hours, the
values and their calibration, the formula and the benchmark version), so G3 sees why the number
is what it is. A 32-unit release design with a handful of features derives about 23 sessions,
where the 2D validation run was given a fixed 14 and needed a person to raise it to 18 mid-run.

**The installation caps it lower, never substitutes for it.** `factory.develop.budget` is the
installation's consent to spend: the run's snapshot of it (and any raise a person recorded) is
read when the plan is made and recorded as `develop_budget.cap`. Where the cap is below the
plan's need, `develop_budget.shortfall` says by how much, the plan carries a `high` technical
risk beginning "Planned shortfall", `metadata.budget_shortfall` is set, the step's message ends
`PLANNED SHORTFALL: ...` and a warning is logged - all before G3, so the shortfall is decided at
G3 (raise the budget, cut scope in a superseding design, or reject), not discovered as a
`BUDGET_RAISED` in the middle of the build. The develop step enforces the lower of the two from
the first session (`docs/development-module.md#budget`). With no cap at all the plan still
records the need, and no command developer starts.

## G3

`tech-plan-review` is a `human-checkpoint` with `gate: G3`. G3 is reversible, so an
installation may list it under `factory.checkpoints.auto_approve`; otherwise the run waits
for `--decision approve`. A rejection is unrouted and blocks the run for a person.
`wgf plan` runs strategy → G2 → design → tech-plan → G3.

What G3 sees of the budget: `dev_plan.develop_budget` with its basis and the cap, and - when the
cap is below the need - the planned-shortfall risk. An installation that auto-approves G3 (the
autonomous profile does) records the risk without a person reading it; the run then stops
`BLOCKED` when the cap is spent, never reporting the tier achieved.

What G3 sees of the content, beside the plan: the design's `consistency.rule_results`
include the `content.*` rules and `consistency.content_model` names the genre model by id and
version, and `wgflib.gate_evidence` prints both — how many content rules ran, which breached,
and against which model — so the reviewer can tell a design that was checked from one that was
not.

Known gap: the title machine's G3 also requires an `asset-manifest` (guard
`asset_manifest_present`), but in `new-game` the `assets` step runs after `init`, because it
writes into the repository init creates. A G3 decided inside a workflow run therefore sees
no asset manifest; the lifecycle transition through `wgf-state.py` still evaluates the guard.

## Outcomes

| Situation | Result |
|---|---|
| No `game-design` or no `title-strategy` in the run | `WAITING_FOR_INPUT` |
| An input's schema major version is not 1 | `FAILED`, not retryable |
| Design and strategy for different titles, or not this run's project | `FAILED`, not retryable |
| Design `consistency.status` is not `pass` | `FAILED`, not retryable |
| No engine can be established, or the design contradicts itself | `FAILED`, not retryable |
| Pinned profile missing or moved | `BLOCKED` |
| `factory.techplan` invalid | `BLOCKED` |
| `quality-benchmark.yaml` states no `tiers[].builds` or `develop` basis for the run's tier | `BLOCKED` |
| Otherwise — including a plan that overruns the timebox, and a planned budget shortfall | `SUCCESS` |

No side effect outside the run: the same inputs, settings and clock give the same content
hash.

## Portal registrations

Some portals issue a per-title Game ID the build must carry (`game.config.yaml`
`platforms[].game_id`, read by the template's `platformOptions()`). It exists only once the
title is registered on the portal, so it is instance data beside the title:

```yaml
# workspace/titles/<title-id>/portals.yaml
gamedistribution: {game_id: 0123456789abcdef0123456789abcdef}
gamemonetize: {game_id: my-title-0001}
# gamedistribution: {game_id: ..., hosting: self-hosted, game_url: "https://..."}
```

The platform's profile decides (`requirements.game_id`, `game_id_pattern`, `hosting`):

| Profile says | No registration | Registration |
|---|---|---|
| `required` (GameDistribution) | `BLOCKED`, naming the file to fill in | written into the entry, if it matches `game_id_pattern` |
| `optional` (GameMonetize) | entry without `game_id`; the build may take it from its environment | written into the entry |
| `none` / absent (every other portal) | — | `BLOCKED`: the template would reject it |

A `hosting` other than the profile's first (default) mode is written with its `game_url`
(https, required for `self-hosted`). init writes every one of these keys into
`game.config.yaml` and reads them back (`docs/init-module.md`).

## Configuration

`factory.techplan` in `workspace/config/factory.yaml`, every key optional:

| Key | Default |
|---|---|
| `template_ref` | the pin: `<repository>@<commit>` from `workspace/config/template.lock.json`. Anything else is `BLOCKED`: the plan approved at G3 names the exact revision init creates the game from |
| `overrun_tolerance` | `overrun_tolerance` in `workspace/config/portfolio.yaml`, else 1.5 |
| `estimates` | the table above |
| `device_classes` | `mobile-mid` and `desktop` at 60 fps; `max_time_to_interactive_s` defaults to the design's `session.time_to_first_play_s` |
| `build` | `{command: pnpm build, output: dist}` — the template's |

## Running it

```bash
python -m unittest scripts/tests/test_techplan_module.py
WGF_AJV=1 python -m unittest scripts.tests.test_techplan_module.Schema   # + ajv
```
