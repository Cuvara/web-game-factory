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

`game_design.engine.type` is taken as declared. The module's only engine knowledge is the
template's mapping from dimensionality to engine id — `2d → pixijs`, `3d → threejs`, the
tech-plan schema's enum — and the template's package name for each, used in the
architecture text. There is no PixiJS- or Three.js-specific logic anywhere else.

| The design says | Result | `metadata.engine_source` |
|---|---|---|
| `engine.type` | that engine | `design.engine.type` |
| only `engine.dimension` | the template's engine for it | `design.engine.dimension` |
| neither, but its asset lists use 3D-only kinds (`model`, `environment`…) | `threejs` | `design assets` |
| neither, and its assets are all 2D kinds | `pixijs` | `design assets` |
| `engine.type` and `engine.dimension` disagree | `FAILED`, not retryable | — |
| nothing either way | `FAILED`, not retryable: guessing a renderer is what G3 stops | — |

Asset kinds and their dimension come from `core/reference/asset-policy.yaml`. The fallback
exists for designs written before `engine` was recorded (the asset fixtures are such
designs); its rationale says the engine was inferred and asks for a superseding design.

## Platforms: the strategy's pins

Each `title_strategy.platform_set[]` entry must resolve to
`core/reference/platforms/<id>.yaml` at the pinned `profile_version`, and becomes the
template's `game.config.yaml` entry `{id, profile: <id>@<version>, role}`. Required
platforms come first because the template's `primaryPlatform()` is the first required
entry. A missing profile, or one whose version moved since the strategy pinned it, is
`BLOCKED`: re-pin in a superseding strategy. Nothing here knows what any portal is.

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
| `M1` Playable core loop | prototype | `CORE-001` (boot on the template with the engine) + one `GAME-nnn` per `mvp` feature |
| `M2` Production scope | production | one `GAME-nnn` per `post-mvp` feature; omitted if none |
| `M3` Platform integration and hardening | hardening | one `SDK-nnn` per target platform + `QA-001` (verify suite green) |

A feature task's acceptance criteria are the feature's own. `optional` features get no task.
A design with no `features` (an older schema) falls back to `scope.tiers.mvp` and
`scope.tiers.production`; those carry no criteria, and the generated criterion says so —
which is what the reviewer at G3 should see.

**Estimates**, in hours, all overridable under `factory.techplan.estimates`:

| Key | Default | Applies to |
|---|---|---|
| `core_hours` | 3 | `CORE-001` |
| `feature_base_hours` + `per_criterion_hours` × criteria (min 1) | 2 + 1.5 × n, capped at `feature_max_hours` 12 | each feature task |
| `platform_base_hours` + `per_assertion_hours` × blocking assertions | 3 + 0.5 × n | each platform task |
| `qa_hours` | 4 | `QA-001` |
| `hours_per_day` | 6 | milestone `est_days` = hours ÷ this, rounded **up** to a half day |

The total is compared with `title_strategy.timebox_days × overrun_tolerance`
(`workspace/config/portfolio.yaml`) and reported — `metadata.fits_timebox`, and a `high`
technical risk when it overruns — but **never adjusted to fit**. `plan_fits_timebox` is
G3's question; estimates that sum neatly to the budget were fitted
(`core/lifecycle/stages/tech-plan.md`).

## G3

`tech-plan-review` is a `human-checkpoint` with `gate: G3`. G3 is reversible, so an
installation may list it under `factory.checkpoints.auto_approve`; otherwise the run waits
for `--decision approve`. A rejection is unrouted and blocks the run for a person.
`wgf plan` runs strategy → G2 → design → tech-plan → G3.

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
| Otherwise — including a plan that overruns the timebox | `SUCCESS` |

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
