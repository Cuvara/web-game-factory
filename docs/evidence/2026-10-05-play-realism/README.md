# Play-realism calibration, 2026-10-05

The evidence behind the bars of `core/reference/play-realism.yaml` 1.0.0
([playability-module.md](../../playability-module.md#play-realism)). `calibration.json` holds
every number quoted there; this file says where each came from. The validation runs it reads
are read-only evidence outside this repository (`wgf-runs/val-2d`, `wgf-runs/val-3d`); the
builds are the accepted r1 releases and the defective builds of the later runs
(factory-learning-ledger L11, L13, L14).

| Builds | r1 (accepted at G4) | head (defective) |
|---|---|---|
| 2D brick breaker | 96f5cea, run `new-game-20261003-081154-4e5e0a` | 68a12b7, run `new-game-20261005-002926-318384` |
| 3D marble | 64ff4c6, run `new-game-20261003-082542-0de9b5` | 1c6b099, run `new-game-20261005-002923-597b5e` |

## What was run

- **Physics** (`physics.undrawn_collision`): `realism.judge` over the win test's per-frame
  samples of every playability visit of both 2D runs, desktop and mobile - records the bot
  wrote during those runs. Neither probe reports a `playfield` or a `collider`. r1: 34
  viewports, 0 FAIL. Head: 20 viewports, 8 FAIL, each a turn moving up 220-248 px short of
  the drawn bar above it (the undrawn ceiling).
- **Naive play**: the bot's own `naive` test (this commit's `bot.spec.ts`) run in WSL against
  each build's `dist/`, served by `python3 -m http.server`, Playwright 1.63 with
  chromium-1243, desktop only. The builds predate the realism fields, so the calibration copy
  of the bot read each build's `falls` metric as `setbacks` and its `par` / `par-time` metric
  as `content.par_s`; nothing else differed. The 3D head build was played twice: on the
  default sample (the opening unit, then the middle and last authored units) and on the units
  with its tight bends (meadow-circuit, gem-garden).
- **Level geometry**: `realism.judge_layouts` over head's `public/content/layouts.json`
  (1c6b099). r1 declares its courses in code (`src/game/courses.ts`); their radii, widths,
  lengths and pars were transcribed for the YAML's notes and are not a layout file the lint
  read.

## What it does not cover

- `naive.drift`, `naive.alignment` and `physics.collider_size` measured nothing: no build
  reports `track`, `view` or `collider`. Their bars are reasoned, not calibrated, and the YAML
  says so.
- Two builds per dimension and a few minutes of naive play each: the setbacks bar in
  particular rests on 2 falls against 0.
- No run of the full playability step played these builds with the new bot: the naive test
  and the judging were run separately, as above.
