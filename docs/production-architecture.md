# Production architecture: from a playable greybox to a finished game

Status: the target the 2.6 work implements; workflow 5 (below) is executable in
`core/workflows/new-game.workflow.yaml`, and release refuses a build the production gates did
not pass (docs/release-module.md). Each section names its owner workstream and the
contract (schema, reference file, step) it builds against. A contract here changes only by
editing this file and the schema together.

## The failure this prevents

A generated game can pass every check and still be a developer prototype: the player is a
cube, threats are spheres, the UI is browser-default buttons, and every asset the manifest
lists is a hash-coloured placeholder that the game never loads. Workflow 4 proves the loop
(greybox, then playability) but nothing yet proves the **presentation**. Production quality
is checked, never assumed:

| Claim | Proven by |
|---|---|
| Production assets exist | `asset-manifest` items with `placeholder: false`, `quality.verdict: pass` |
| They are used | the play probe names the asset drawing each entity; the bot sees the files fetched |
| No accidental primitives | probe `entities[].render` + GLB inspection (`quality.primitive_only`) |
| UI is coherent | DOM measurement (targets, overlap, contrast, size) + the visual QA judge |
| It looks finished | `visual-qa` - a vision judge reading runtime frames against a rubric |

## Greybox vs production

| | greybox | production |
|---|---|---|
| Steps | `greybox`, `greybox-playability` | `assets`, `develop` (phase production), `playability`, `production-quality`, `visual-qa` |
| Primitives | allowed | refused for readable roles unless `art_direction.primitive_style: true` |
| Placeholder assets | allowed | refused (release refuses too) |
| UI | functional | styled from `build_spec.ui_style`, measured |

`art_direction.primitive_style: true` is the one explicit escape: a game whose art direction
*is* geometric (a neon abstract runner). It must be stated at design time with a reason, and
visual QA still judges the result.

## Target workflow (5)

```
init -> greybox -> greybox-playability -> assets -> develop -> playability
     -> production-quality -> visual-qa -> review -> sdk -> sdk-review -> verify -> G4 -> release
```

Routing:
- `greybox-playability` fail -> `greybox`
- `playability` fail -> `develop`
- `production-quality` route `assets` -> `assets` (an asset is missing, a placeholder, or
  fails its quality check); route `develop` -> `develop` (an asset is not loaded or used, an
  entity is drawn with primitives, UI measurements fail)
- `visual-qa` route `assets` / `develop` the same way, by the category of each finding
- `assets` re-entered reads the failing report and rebuilds only the items it names
- `release` refuses unless the newest `production-quality-report` and `visual-qa-report`
  passed for the released commit's ancestor develop commit

## Contracts

### game-design 1.6.0 (owner: design/UI)

`build_spec.assets[]` gains:
- `role`: player | threat | goal | target | projectile | collectible | hazard | environment |
  background | prop | ui | vfx | icon | font - the same vocabulary as the play probe's
  entity roles, plus the non-entity ones
- `readability`: what a first-time player must recognise in it ("a goalkeeper in gloves,
  readable at 60 px tall from the camera")
- `dimension`: 2d | 3d

As the schema landed, the look lives in `build_spec.visual_identity` (no separate
`art_direction`/`ui_style` blocks): the existing `palette` (token, hex, role) and
`typography`, plus `primitive_style` (an object with a `reason`; absent means false) and
`ui`: `font_px` (body, hud, heading), `min_target_px`, `button` (`fill` and `text` palette
tokens, `radius_px`, `style`) and `surface` (a palette token).

The design step checks it after the experience contract (`scripts/wgf_design/presentation.py`,
bars in `core/reference/experience-rules.yaml` `production_art` and `ui`): every MVP drawn
asset states `role` and `dimension`; every entity-role asset a `readability` line; every
readable role the design's own mechanics and win/lose conditions name (`role_cues`) has an
asset of that role with a readability line, unless `primitive_style`; a 3D design's
player and threat assets are models in 3D; the typography ships as an MVP `font` asset, and
every face can set every locale in `scope.locales` (`core/reference/asset-quality.yaml`
`fonts`: a listed family must be published with one of the locale's subsets, any other
family's font asset states its subsets) - the archetype author swaps a kit face that cannot
for its covering alternate (`identity.ALTERNATES`: Bungee -> Rubik Mono One for `ru`); and
`ui` names palette tokens, button text on its fill at 4.5:1 or better, targets >= 44 px and
body/HUD text >= 14 px. Every built-in archetype states all of it (no archetype claims
`primitive_style`); an agent author is told the fields and shown the problems to repair.

### asset-manifest 1.4.0 (owner: assets 2D/3D)

Each item gains:
- `role` (as above), `dimension`
- `quality`: `{verdict: pass|fail|skipped, checks: [{id, status, summary}],
  primitive_only: bool|null, parts: int|null, triangles: int|null, colors: int|null}`
- `placeholder` keeps its meaning and becomes a release blocker for mvp items

Sources (the assets step's backends), by preference:
1. `library`: imported from a configured library directory with a licence record
   (`factory.assets.libraries`) - also how golden fixtures supply real art
2. `author`: an agent author writes SVG (2D) or a model spec (3D, built by the pinned
   Blender) for each requirement, from its `description`, `readability`, `role` and the
   palette; validated, rejected and re-asked like the design author
3. `placeholder`: today's procedural stand-ins, always `placeholder: true`

2D production files are SVG (sprites, backgrounds, icons) rendered by the browser, plus PNG
atlases where the engine needs them. 3D production files are GLB with normals, materials
and at least the part count the spec states.

### play-probe (owner: production gate)

- `entities[].asset`: the runtime asset id (`public/assets/assets.json`) that draws it, or
  null
- `entities[].render`: `asset` | `primitive` | `text` | `composite`
- `assets_loaded`: runtime asset ids the game has loaded

### production-quality-report (owner: production gate)

Per check `{id, status, required, summary, measured, expected, route}`; `route` is
`assets` or `develop`. Checks (bars in `core/reference/production-quality.yaml`):
- `assets.present` - every mvp requirement has a manifest item, not placeholder, quality pass
- `assets.loaded` - every mvp runtime asset was fetched by the page during play
- `assets.used` - every readable-role entity names an asset, `render: asset|composite`
- `scene.no_primitives` - no readable-role entity `render: primitive` (unless primitive_style)
- `ui.targets` - interactive elements >= min target px on mobile
- `ui.overlap` - no interactive element overlaps another or the HUD
- `ui.text` - text contrast >= 4.5:1, font >= min px
- `ui.styled` - buttons are not browser-default (computed style differs from UA default)
- `ui.states` - win/lose/retry screens exist and were seen

### visual-qa-report (owner: visual QA)

A vision judge (agent command, like the reviewer) reads the frames of every state on both
viewports with `core/reference/visual-qa-rubric.yaml` and the design's art direction, and
returns findings `{id, severity, category: assets|ui|composition|debug|readability,
frame, summary, route}` and a verdict. Never a first-time-player measure
(`measurement_class: automation-agent`).

## Golden runs

The golden ports must pass the production gates: their art arrives as a `library` fixture
in the template's golden branch (SVG tiles and background for Tower Merge Rush; GLB craft,
walls and arena for Neon Drift Arena, built from model specs by the pinned Blender), loaded
through `assets.json`, and their probes report `asset` and `render`.
