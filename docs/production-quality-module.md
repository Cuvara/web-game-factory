# The production-quality module

`scripts/wgf_production/` implements the `production-quality` step type: the gate between a
playable build and a finished one. It is the "production gate" of
[production-architecture.md](production-architecture.md), which owns the target workflow and
the contracts; this page is how the step works.

```
... -> develop -> playability -> production-quality -> visual-qa -> review -> ...
          ▲   ▲                        │ route develop
          │   └────────────────────────┤
       assets ◄────────────────────────┘ route assets
```

In `new-game` (workflow 5) it runs after `playability` and before `visual-qa`; route
`assets` goes to `assets` (budget `production-quality.assets: 2`), route `develop` to
`develop` (`production-quality.develop: 2`), and `release` refuses unless the newest report
is PASS for the development commit it ships (docs/release-module.md).

## Why it exists

A build can pass playability and every code check and still be a developer prototype: the
player is a cube, threats are spheres, the buttons are the browser's grey defaults, and the
assets the manifest lists are placeholders the game never loads. Playability proves the loop
can be played and seen; nothing proved the presentation. This step does, from evidence the
playability bot already recorded.

## Inputs, output, outcomes

| | |
|---|---|
| inputs | `playability-report` (its `commit` and `records_dir`, playability-report 1.1.0), `asset-manifest` (items, `placeholder`, `quality`, `files`), `game-design` (`build_spec.assets`, `visual_identity`, `experience`), `scaffold-record` (the title) |
| output | `production-quality-report` (`core/artifacts/production-quality-report.schema.json`): every check with `route`, the asset ids it concerns, what was measured and the bar; `failed`, `routes`, the verdict |
| SUCCESS | every required check passed |
| FAILED, route `assets` | a required check failed and at least one failed check routes to `assets`: an asset must be made again (missing, a placeholder, failing its own quality checks). Not retryable |
| FAILED, route `develop` | every failed check routes to `develop`: the game's use of assets or its UI must change. Not retryable |
| BLOCKED | nothing to judge: the playability report was blocked, names no `records_dir`, the records are not on disk, or they come from a bot that did not record asset requests |

The step never plays the game and never touches the checkout. It reads what the
playability bot recorded in the same run (`<run_dir>/<records_dir>/<project>/*.json` and
`frames/`), so both steps judge the same play of the same commit.

## The checks

Bars: [`core/reference/production-quality.yaml`](../core/reference/production-quality.yaml).
`project` is set on per-viewport checks; the asset checks are global.

| Check | Route | Passes when |
|---|---|---|
| `assets.present` | assets | every required-tier (`mvp`) asset - each design requirement and each manifest item of that tier, `cut` excepted - has a delivered manifest item with `placeholder: false` and `quality.verdict: pass` |
| `assets.loaded` | develop | every such item with a file (store presentation types excepted) was fetched by the page during play with a 2xx/3xx: its runtime-manifest `url`/`data` or its atlas's, as `assets.json` was fetched; else its `files` under `public/assets/`. No request under `/assets/` failed |
| `assets.runtime` | assets if any asset breaks at `exists`, else develop | the asset runtime chain holds for every required asset, link by link, stopping at the first that breaks: **exists** (a delivered manifest item, not a placeholder, with files) -> **referenced** (in the runtime manifest `assets.json` the page fetched) -> **loaded** (its file fetched during play) -> **rendered** (an entity the probe reported names it, `render` `asset`/`composite`) -> **visible** (an entity drawn with it is on screen, visible and at least `visible.min_area_fraction` of the viewport in the per-frame samples, and in a state frame at least `min_changed_share` of the pixels in its box differ from the frame's dominant colour by `min_pixel_delta`). `rendered` and `visible` apply to entity-role assets (`entities.asset_roles`); `referenced`/`loaded` skip store presentation types. `measured` holds each asset's chain and `failed_at` |
| `assets.used` | develop | every entity of a readable role (player, threat, goal, target, projectile) the probe reported names an `asset` that is in the runtime manifest, with `render` `asset` or `composite` |
| `scene.no_primitives` | develop | no readable entity is `render: primitive`, and every one reports `render` (one that does not cannot be shown not to be a primitive) |
| `ui.targets` | develop | mobile only: every interactive DOM element and every probe `ui` entity is at least `min_target_px` (44, raised by the design's `visual_identity.ui.min_target_px` or `responsive.min_touch_target_px`) on both sides |
| `ui.overlap` | develop | no two controls, and no control and text, share `min_overlap_px` or more |
| `ui.text` | develop | every DOM text (controls' and others') is at least `min_font_px`, with WCAG contrast ≥ 4.5:1, or ≥ 3:1 for large text (≥ 24 px, or ≥ 18.66 px bold). The background is the DOM's when an opaque one is behind the text; otherwise the dominant colour of the state's frame inside the text's box (text over the canvas) |
| `ui.styled` | develop | no control's computed style equals the user-agent default for its tag |
| `ui.states` | develop | the `lost` and `retry` screens were seen on the viewport, and `won` when the experience contract has a win |

A check with nothing to measure (no DOM control, no DOM text) is a `WARNING`, not required:
a canvas-drawn UI is visual QA's to judge.

### `primitive_style`

When the design's `build_spec.visual_identity.primitive_style` is present (its `reason`
stating that the art direction itself is geometric), `scene.no_primitives` is not required;
it still reports what it found, with `measured.exempt: true` and the reason, and its summary
begins `exempt`. `assets.used` then accepts an entity drawn only as a primitive with no asset,
and lists it under `measured.exempt_primitive_style`. Every other check stands.

## Routing

The step's route is the first of `routes`, assets before develop: when an asset itself is
wrong, the game's use of it cannot be judged until it is made again. The report keeps every
failed check, so `develop`, re-entered after `assets`, still sees its own.

## What it does not claim

`measurement_class: automation-bot`. It proves the art is delivered and used and the DOM UI
meets measurable bars; whether the result *looks* finished is visual QA's, and whether
players understand it is measured from people.

## Running it outside a run

`checks.judge(records, manifest, design, rules, frames_dirs)` is pure; its tests synthesise
records the way the bot writes them (`scripts/tests/test_production_quality.py`). The mock
step (`--mock`) answers `fail` with route `develop` and `fail-assets` with route `assets`.
