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
| `assets.runtime` | assets if any asset breaks at `exists`, else develop | the asset runtime chain holds for every required asset, link by link, stopping at the first that breaks: **exists** (a delivered manifest item, not a placeholder, with files) -> **referenced** (in the runtime manifest `assets.json` the page fetched) -> **loaded** (its file fetched during play) -> **rendered** (an entity the probe reported names it, `render` `asset`/`composite`) -> **visible** (an entity drawn with it is on screen, visible and at least `visible.min_area_fraction` of the viewport in the per-frame samples, and in a state frame at least `min_changed_share` of the pixels in its box differ from the frame's dominant colour by `min_pixel_delta`). `rendered` and `visible` apply to entity-role assets (`entities.asset_roles`); `referenced`/`loaded` skip store presentation types. `measured` holds each asset's chain and `failed_at`. A state the game staged through its probe's optional showcase (the bot's `showcase-<id>` screens, [playability-module.md](playability-module.md)) counts for `rendered` and `visible` like any state frame, but only for an entity whose box in that frame passes the same `min_changed_share` pixel test: an asset the probe names there and the frame does not draw is not credited. An asset credited from one carries `showcase: true`. A box in a state frame is the one the entity swept while the screenshot was taken; when the bot recorded the entity's drawn size (`own: [w, h]`), the pixel test takes the best window of that size slid along the box in half-size steps, and the area fraction uses that size - so a small fast mover is not diluted by the path it swept |
| `assets.used` | develop | every entity of a readable role (player, threat, goal, target, projectile) the probe reported names an `asset` that is in the runtime manifest, with `render` `asset` or `composite` |
| `scene.contrast` | develop | each readable role stands out from its surround in the state frames: for every readable entity's box (at least `contrast.min_box_px` on both sides), the WCAG contrast of the box's pixels against the median luminance of a ring around it (`ring_fraction` of the box's shorter side), taken at `percentile` (0.9: the entity's most distinct tenth, since a box also holds background), and the role's best box reaches `min_ratio` (3:1, WCAG 2.1 SC 1.4.11 for graphical objects). No box large enough to judge is a `WARNING` |
| `scene.no_primitives` | develop | no readable entity is `render: primitive`, and every one reports `render` (one that does not cannot be shown not to be a primitive) |
| `ui.targets` | develop | mobile only: every interactive DOM element and every probe `ui` entity is at least `min_target_px` (44, raised by the design's `visual_identity.ui.min_target_px` or `responsive.min_touch_target_px`) on both sides |
| `ui.overlap` | develop | no two controls, and no control and text, share `min_overlap_px` or more |
| `ui.text` | develop | every DOM text (controls' and others') is at least `min_font_px`, with WCAG contrast ≥ 4.5:1, or ≥ 3:1 for large text (≥ 24 px, or ≥ 18.66 px bold). The background is the DOM's when an opaque one is behind the text and nothing else paints there; otherwise (undetermined) the dominant colour of the state's frame inside the text's box. The DOM background is undetermined when the text's element or an ancestor up to that opaque background paints a background image, a border-image (a nine-slice panel), a mask or a ::before/::after with an image or a fill, or when, at the text's centre, another element that paints (a canvas, an image, a sibling tile) lies between the text and it. A control's colour, font and background are those of the element that draws its text (a face `<span>` inside a transparent `<button>`). Every text is also read on the frame, whatever the DOM says (**busy backdrop**): inside its glyph box (`glyph_box`, the rectangle of its own text; a control is read only there, never on its border box), more than `ui.max_backdrop_clutter` (0.3) of the pixels explained by neither the background, the text's colour, its own text-shadow or stroke colours (`paint`), nor a blend of two of them within `ui.backdrop_delta` (40 per channel; each pixel judged with its two horizontal neighbours, so subpixel-antialiasing fringes are not art) fails, and so does a horizontal line of the text's own colour longer than `ui.max_ink_run_em` (2.0 em) through it - a tile's or panel's edge, never a glyph stroke (an underlined text is exempt). A text whose frame cannot be read is counted in `measured.backdrop.unread`, never passed on it. A control named only by its `aria-label` (an icon button) draws no text and is not measured (`text_drawn: false` in the bot's record) |
| `ui.styled` | develop | no control's computed style equals the user-agent default for its tag |
| `ui.states` | develop | the `lost` and `retry` screens were seen on the viewport, and `won` when the experience contract has a win |
| `audio.plays` | develop; assets when the music was never delivered | only when the design has music (`build_spec.audio` type `music` of a required tier): during play at least one probe sample has `audio.playing` with the measured `audio.level` at or above `audio.min_level` (0.005 RMS, about -46 dBFS), the probe names the track, the music's file was fetched (its runtime-manifest url), and with the page unfocused (a window blur - the platform mute) the level is at most `audio.max_muted_level` (0.001). A probe with no `audio` field fails it |

A check with nothing to measure (no DOM control, no DOM text) is a `WARNING`, not required:
a canvas-drawn UI is visual QA's to judge.

`scene.contrast` was proven on real frames (2026-10-01): the 3D reference Neon Drift Arena's
gate records (`/tmp/wgf-g3d-ndrift/int/gate2/playability/1-1/out`) pass - player 11.13:1 and
threat 15.18:1 on desktop, 8.70:1 and 14.28:1 on mobile; the 3D asset agent's first, dark
build (`/tmp/mk/evidence/{desktop,mobile}-play-1.png`, no probe records, so the barrier and
craft boxes were located on the frames by hand) fails on the barriers - 2.58:1 desktop,
2.53:1 mobile - while its craft passes (6.6:1, 6.9:1); the 2D golden build passes (target
14.5:1).

The busy backdrop was calibrated on real frames (2026-10-05, production-quality.yaml 1.3.0).
At sky-marble `a61a9d7` the card was a nine-slice `border-image` of the whole UI-kit sheet
over a sand `background-color`: production-quality passed `ui.text` (the DOM measured ink on
sand), and visual QA then found the pause, win and loss cards overprinted by other screens'
PLAY/GO, NEXT and chip art. Read on the playability frames of that commit
(`val-3d/.../playability/5-1/out`), every card fails, on both viewports: clutter 0.48
('Par 24.0 s · Gold 19.2 s', won) and 0.60-0.64 ('60.0 s / 60.0 s', lost), and ink lines of
4.3-4.9 em ('Course clear'), 2.3-2.5 em ('5.3 s'), 3.6-3.7 em ('Time is up') and 2.8-2.9 em
('Paused'). At the fixed commit `3f394e2` (`6-1`, `7-1`) every text measures clutter 0.00
and at most 1.1 em ('Time is up': the T's bar); the 2D brick-breaker-worlds run's texts
(`val-2d/.../playability/{1..10}-1/out`) at most 0.04 and 0.5 em. Records from a bot before
`glyph_box` have no glyph box for controls; their controls are not read for the backdrop
(`unread`).

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

## What a failure sends back

Every failed check keeps `summary`, `expected`, `measured`, the `assets` it concerns and the
`frames` it measured (frame ids of the play, resolved through the playability-report it
judged to absolute paths under the run directory).

- **Route `assets`**: the assets step remakes the checks' `assets` (else the ids and role
  words their summary names) and hands each author the check, what was expected and
  measured, and the frames ([assets-module.md](assets-module.md#re-entry)). When no
  configured author can remake them, the assets step blocks instead of reusing every file.
- **Route `develop`**: the develop brief's "Fix first: what the production gate measured"
  lists every failed required check with its route, assets, expected, measured (cut at 600
  characters) and the absolute paths of its frames, which the developer is told to open.

## What it does not claim

`measurement_class: automation-bot`. It proves the art is delivered and used and the DOM UI
meets measurable bars; whether the result *looks* finished is visual QA's, and whether
players understand it is measured from people.

## Running it outside a run

`checks.judge(records, manifest, design, rules, frames_dirs)` is pure; its tests synthesise
records the way the bot writes them (`scripts/tests/test_production_quality.py`). The mock
step (`--mock`) answers `fail` with route `develop` and `fail-assets` with route `assets`.
