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
- `audio` (optional): the music playing, whether it is audible, and the master output's
  measured RMS - read from an `AnalyserNode` after every gain, so a muted game reports ~0

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

### game-design 1.7.0 (owner: design)

`build_spec.depth`: `meta_loop` (statement, tier, `persists[]` of `{kind, what, tier}`),
`goal_ladder[]` (`horizon` short | mid | long), `content_schedule[]` (`kind`, `at_s` /
`after_runs`, `rule`), `first_session` (`target_s` = `session.first_session_seconds`,
`ends_on`), `return_hooks[]`; every entry tiered, with `delivered_by` naming what builds it.
The design step checks it after the consistency rules (`scripts/wgf_design/depth.py`, bars
in `core/reference/design-depth.yaml`); craft in `core/craft/retention-and-progression.md`.

After depth comes the **content contract** (game-design 1.9.0): `genre`,
`build_spec.content.units[]`, `build_spec.difficulty.axes` and `build_spec.mastery`, held to
the genre family's entry in `core/reference/genre-models.yaml` by
`scripts/wgf_design/content.py` (22 `content.*` rules). That is what gives the checks below
something to measure a build against: a unit list, the axes difficulty moves on, and a stated
win. Craft: `core/craft/content-and-level-design.md`.

## Design depth (implemented)

**Status: implemented.** The playability step runs them
([playability-module.md](playability-module.md)), as three extra bot tests per viewport
(traverse, persist, session) and eight checks:
`content.units_reachable`, `content.objective_shown`, `content.win_lose_per_unit`,
`content.variety`, `difficulty.axes_progress`, `progression.persists`,
`depth.session_length` and `depth.ramp`. Every bar is data — `core/reference/design-depth.yaml`
`playability:` (added in 1.1.0: the time budget, the traverse and objective bars, the
difficulty rise share and relief dip, the variety share, the session share and the ramp
multipliers) merged with the genre family's `qa:` block in `core/reference/genre-models.yaml`,
read through `wgflib/genre_models.py` `qa_of()`. No multiplier is in code.

Two things differ from the proposal below. There is no `depth.return_hook` check: the result
card's hook is not measured. And `depth.persists` is `progression.persists`, which also holds
the content unit reached, not only the depth metrics. A check whose claim the design does not
make is `SKIPPED` — never a pass, always listed in the report's `skipped_checks` with its
reason — and a claim the probe cannot show is a FAIL. `verify` carries all of it into the
verification and the qa-report's `gameplay-quality` suite rather than measuring it again
([verification-module.md](verification-module.md)), and G4 is shown it
(`wgflib.gate_evidence`).

The rest of this section is the contract as it was specified, kept because it is what the
implementation was written against. Each check measures from outside, through real input and
the play probe
(`shared/play-probe.schema.json`), against the design's `build_spec.depth`. Like every
playability measure they are `measurement_class: automation-agent`: a bot's numbers, never a
first-time player's.

A check only holds what the build claims. It reads only the **MVP** entries of
`build_spec.depth`, because post-mvp and optional depth are stated and not built. A
prototype is never failed for a stage map it was not asked to build. A production build
(after G4) is held to the post-mvp entries as well, once the step knows which phase it is
judging.

Probe additions the checks need. They are additive to the play probe, and a game without
them reports `skipped` with the reason, never `pass`:

- `metrics` carries every metric a depth entry's `measure` names, under the metric ids the
  design uses. The prototype has at least `best`. A production build adds the persisted
  progression metrics: `coins`, `stage` (highest stage cleared), `stars`, `missions_done`,
  `achievements`, `unlocked` (a count) and `streak`.
- `entities[].role` and `entities[].kind`. `kind` is optional and new: the
  content-schedule kind (`special-piece`, `pickup`, `hazard`, ...) or the content item id,
  so the bot can tell a bomb from a level-3 piece without reading pixels.
- `oracle` (with `wgf-probe=1`) as now: the input that succeeds. "Fixed bad play" means
  every input the oracle does not recommend, chosen with a fixed seed.

| Check | Measures | Passes when | Route |
|---|---|---|---|
| `depth.session_length` | The oracle bot plays good runs back to back for up to 1.5 × `depth.first_session.target_s`. It retries at once after each loss and stops at the design's `first_session.ends_on` beat (a new best, a stage cleared) or at the cap. The bot runs 3 sessions and takes the median. | The median session length is ≥ 0.5 × `depth.first_session.target_s`. A loop that ends far sooner under good play has nothing to keep a first session going. | `develop` |
| `depth.ramp` | Fixed bad play (a seeded non-oracle input stream), 10 runs, measuring time to loss in each. Inside one long oracle-assisted run, the bot also measures the interval between oracle-required inputs. | Bad-play runs end (time to loss < 3 × the archetype's run length). Under oracle play, the required-input rate rises from the first third of the run to the last. Any relief beat the curve states shows as a dip of ≥ 2 s. Flat or falling pressure fails. | `develop` |
| `depth.persists` | Play until every MVP `meta_loop.persists[]` metric changes (`best` at least), reload the page, and read the probe again before any input. | Every persisted MVP metric reads its pre-reload value after the reload. A production build also covers `coins`, `stage`, `unlocked`, ... | `develop` |
| `depth.variety` | Across the first `max_first_in_run_s` + 120 s of oracle play, record the set of `entities[].kind` (or role + asset) seen per 30 s window. | The first new kind arrives by the design's earliest MVP `content_schedule[].at_s` + 15 s. At least `min_mvp_items` new kinds appear over the window, and the MVP items whose `at_s` falls inside the window are each seen. | `develop` |
| `depth.return_hook` | The last result card of the session-length run: its visible text and screen elements. | The card shows the session's mid goal (the gap to best, or the next stage's goal), and at least one MVP `return_hooks[]` is visible as text or an element. | `develop` |

Numbers in the checks come from `core/reference/design-depth.yaml` and the design. The
multipliers (0.5 ×, 3 ×, + 15 s, 2 s) are in that file's `playability` block, never in code.

What the checks cannot tell: whether players come back (D1 is a live metric read at
`title:live`, and a strategy success criterion) and whether the meta is fun. Stranger
playtests (`core/craft/playtesting.md`) and G4 answer those.

## Golden runs

The golden ports must pass the production gates: their art arrives as a `library` fixture
in the template's golden branch (SVG tiles and background for Tower Merge Rush; GLB craft,
walls and arena for Neon Drift Arena, built from model specs by the pinned Blender), loaded
through `assets.json`, and their probes report `asset` and `render`.

The golden designs (archetypes `drop-merge` and `arena-dodge`) are **parametric arcade**
games: the fixtures pin `design_archetype` and `genre_model: arcade`, and their content is
generated from parameters rather than authored unit by unit, so the authored-content checks
SKIP or warn rather than failing art that is correct
([golden-runs.md](golden-runs.md)). They state their depth honestly
for what the ports build. The MVP depth is a persisted best score, the in-run drop ramp or
speed tiers, and the short and mid goals the ports already have. Stages, special pieces,
power-ups, coins, zones, pickups, the garage and missions are `post-mvp` and rest on post-mvp
features. The dev brief and the golden replay read only the MVP, so these entries add no MVP
item the ports lack, and nothing in the golden runs judges post-mvp depth. The feature specs
those entries come from are [reference-games/tower-merge-rush.md](reference-games/tower-merge-rush.md)
and [reference-games/neon-drift-arena.md](reference-games/neon-drift-arena.md).
