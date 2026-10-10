# Golden Runs

Two canonical, repeatable, **real** regression runs of the one shared `new-game` workflow:

| Run | Game | Engine | Replays |
|---|---|---|---|
| 2D | Tower Merge Rush (`tower-merge-rush`) | PixiJS | `web-game-template/examples/tower-merge-rush` |
| 3D | Neon Drift Arena (`neon-drift-arena`) | Three.js | `web-game-template/examples/neon-drift-arena` |

Both go through the same workflow file, the same engine and the same modules — no `--mock`,
no engine branching. The only differences are data in `scripts/golden/games.py`, the
fixtures under `scripts/golden/fixtures/<2d|3d>/` (a catalog and the port mapping) and the
port each game's template example carries. That is the point: the pair proves the
Factory is renderer-agnostic.

```
research -> strategy -> G2 -> design -> tech-plan -> G3 -> init -> greybox
         -> greybox-playability -> assets -> develop -> playability -> production-quality
         -> visual-qa -> content-sufficiency -> review -> sdk -> sdk-review -> verify
         -> quality-gate -> G4 -> store-listing -> listing-validation -> release
```

G2 and G3 are auto-approved (reversible; configured below). G4 is irreversible, so the run
stops there `WAITING`; the harness answers it `pass` through the API `wgf decide` uses,
with `decided_by` left to `default_decider()` - `human`, because the person running the
golden run is outside every step's process tree - and resumes. Its note says it is the
harness operator's pass of a known-good port (`harness.G4_NOTE`). `games.EXPECTED_STEPS`
lists all 24 steps, `greybox`, both playability steps, `production-quality`, `visual-qa`,
`content-sufficiency`, `quality-gate`, `prototype-review` and `sdk-review` included. A golden
run is an `mvp` run of endless (parametric) ports, so `content-sufficiency` counts no unit
list: its unit checks are SKIPPED with that reason and it passes
([content-sufficiency-module.md](content-sufficiency-module.md)). At `mvp` the quality gate
holds the universal floor's mvp blockers and decides `development`, never release
([quality-gate-module.md](quality-gate-module.md)); release drafts it and records it as such
(`evidence.quality_report`). The replay developer ports the whole game in
the greybox phase - with no assets yet, each port draws its fallback primitives - and
develop's production visit commits the assets step's files, imported from the port's art
library, on an unchanged game that now draws them (see *The production gates*, below). Each playability step plays each port from outside through its play probe
(`examples/*/wgf-golden/src/game/play-probe.ts` at the lock's `golden_ports` commit) and
holds it to the design's experience contract ([playability-module.md](playability-module.md)):
a port that cannot be played from outside fails the golden run. The golden reviewer
reviews both commits - develop's (`review`) and the sdk integration commit on top of it
(`sdk-review`), which is the one verified and released - and the golden configuration never
sets `release.allow_unreviewed`: a golden run releases only a commit the reviewer approved
(`test_a_golden_release_is_never_unreviewed`).

## Running them

```bash
python3 scripts/golden/run.py --game 2d            # temp workdir, removed afterwards
python3 scripts/golden/run.py --game 3d --keep     # keep the workdir and its evidence
python3 scripts/golden/run.py --game 2d --workdir /tmp/g2d --json
python3 scripts/golden/run.py --game 2d --workdir /tmp/g2d --resume <run-id> --from verify

WGF_GOLDEN=1 python3 -m unittest scripts.tests.test_golden_2d   # the 2D GOLDEN category
WGF_GOLDEN=1 python3 -m unittest scripts.tests.test_golden_3d   # the 3D GOLDEN category
WGF_GOLDEN=1 bin/wgf test-core --only "2D GOLDEN" --only "3D GOLDEN"
python3 -m unittest scripts.tests.test_golden_fast              # always-on harness checks
```

Needs: `git`, `node` + `pnpm`, network access to the npm registry before the run (each
golden run first warms the pnpm store itself - `harness.warm_store`: the pinned template's
dependencies, and a full online resolution of the engine package the replay adds - then runs
offline, `--offline` / `--prefer-offline`), Playwright's Chromium installed (the build the
pinned template's Playwright version expects), and the pinned template commit.
`scripts/wgflib/template.py` finds it in this order: `WGF_TEMPLATE_DIR` (refused unless it
is at the pinned commit), the cache `~/.cache/wgf/templates/<sha>`, then a clone from the
sibling `../web-game-template` when it holds the commit, else from GitHub (the lock's URL;
the machine's git credentials). The work directory defaults to a fresh `mkdtemp(prefix="wgf-
golden-")` under `$WGF_GOLDEN_DIR` or `/tmp` — keep it on a fast local file system, not a
Windows mount.

**Run them one at a time.** The template's Playwright config serves on the fixed port 4173
with `reuseExistingServer: false`; two runs at once collide there.

Without `WGF_GOLDEN=1` the 2D/3D GOLDEN categories are **SKIP**, and a skip is never a pass.
`test_golden_fast.py` (config, fixtures, research -> G3 steering, the replay mapping, port
conformance, the reviewer) always runs, in about 20 s, and needs no node.

## Where the evidence lands

```
<workdir>/
  factory-store/workflows/<run-id>/        state.json, events.jsonl, artifacts/ (every version)
  games/<title-id>/                         the game repository (local git, no remote)
    release/<release-id>/                   <platform>.zip, packages.json, checksums.txt, manifest.json
  evidence/
    golden-<2d|3d>.json                     the summary (below)
    factory-config-<2d|3d>.json             the exact factory configuration the run used
    browser-<2d|3d>/browser-evidence.json   the independent browser evidence
    browser-<2d|3d>/suites.json             Playwright JSON report of the game's own suites
    browser-<2d|3d>/probe/<viewport>/       the harness probe: probe.json + screenshots
    playability/reports/                    every playability-report version, as the store holds it
    playability/<step>/<visit>-<attempt>/   the bot's settings.json and <project>/first-session.json,
                                            act.json, ... (no frames, no logs), pass or fail
    golden-loop-2d.json                     with --defect: the loop's before/after record (below)
    golden-loop/v<n>-<commit>/<project>/    with --defect: the frames the first and last report cite
```

The summary holds: `run_id`; every step's status, expected outcome, route, duration,
visits; every artifact `id@vN` with its content hash and checksum; the repository's commits
and whether it is clean; the engine as recorded by the design, the tech plan, the scaffold
record, `game.config.yaml` at HEAD and the browser's `window.__wgf__` probe; the release
manifest path, and each zip's recorded and recomputed sha256 and content digest; the
evidence statuses exactly as the modules wrote them; the browser evidence; and any process
still alive in the work directory. `passed` is true only if every step reached its expected
outcome, release drafted a manifest whose zip hashes reproduce, and the engine is the same
everywhere. `browser_passed` is reported beside it; the CLI and the tests require both.

## The template is pinned — the ports are pinned beside it

A golden run creates its game from web-game-template at the one commit the Factory pins,
`workspace/config/template.lock.json`, through `scripts/wgflib/template.py` — never at
whatever the sibling checkout's HEAD is. The regression baseline therefore moves only when
someone moves it: adopting a newer template means running both golden runs with
`WGF_TEMPLATE_COMMIT=<sha>` (`WGF_GOLDEN_TEMPLATE_REF` is the older spelling), making them
pass, and changing the lock in the same commit. The summary records `template_ref`.

The Factory holds no game source, so the hand-made part of each replay lives in the template,
beside the example it adapts. The pinned **release** (v1.1.0) does not ship those ports: they
are test fixtures, so the lock names them separately (`golden_ports`: the local template
branch `wgf-golden-content`, `db7b140` - `wgf-golden-production` (the play-probe ports
`1c5afcb` with both reference ports' production art merged in, `8f49d28` and `7c132ef`) plus
the content the production gate's `font.coverage` and `variants` checks require: towers 9
and 10 in the 2D library, Latin + Cyrillic faces in both, both baselines re-captured), and
the replay developer reads them from a
checkout of that commit (`--ports`, `wgflib.template.golden_ports_checkout()`). The game
repository itself is still created from the pinned release, exactly.

| Template path | What |
|---|---|
| `examples/tower-merge-rush/wgf-golden/` | the 2D port: `src/main.ts`, `src/game/app.ts`, UI, input, the PixiJS view wrapper, `index.html`, `en`/`ru` locales, the tagged browser spec |
| `examples/neon-drift-arena/wgf-golden/` | the 3D port: the same set for the Three.js game |
| `examples/<example>/wgf-golden/library/` | the port's production art, a library the golden run's assets step imports (`factory.assets.libraries`): SVG pieces, board, icons, UI kit and OFL fonts (2D); Blender-built GLB craft, walls, track and skyline, fonts and icons (3D). Never copied into the game |
| `examples/<example>/wgf-golden/baseline/` | the approved frames of the finished port, `<viewport>/<name>.png`, that visual QA's baseline judge compares the run's frames with (`states.json` names a frame's rubric state where its file name does not). Never copied into the game |
| `examples/wgf-golden-shared/` | shared by both: the audio service (its default `GameIntegration` implementation is no longer copied: the develop step provides the seam's wiring) |

Each has a README saying what it is. They sit in the template's layout (`src/...` relative to
the directory), are laid onto a game repository's root by the replay developer, and only
typecheck there: the template's root `tsconfig.json` excludes `examples/wgf-golden-shared`,
and its `examples/*/src` / `examples/*/tests` globs do not reach `examples/*/wgf-golden/`, so
the template's own lint, typecheck and tests still pass. A ports commit that does not ship
them makes the replay refuse (exit 3) and the fast tests fail.

The ports were adapted to template 1f5dee2 (a real GameVui adapter; `GenericWebPlatform`
takes its capabilities through its constructor) with one change: the template's own SDK
matrix harness (`tests/sdk-matrix/main.ts`) now imports `src/game/boot-scene.ts`, so the
replay no longer deletes that file — `main.ts` just does not start it.

## How a run is isolated and steered

The harness (`scripts/golden/harness.py`) reads `workspace/config/factory.yaml` and never
writes it, and passes an in-memory configuration to `WorkflowAPI` — the same assembly
`wgf` uses. The overrides:

| Setting | Golden value | Why it is legitimate |
|---|---|---|
| `init.source` | `local`, `template_path` = the template checkout | no GitHub; `git archive` of the template's HEAD becomes the repo's initial commit ([init-module.md](init-module.md)) |
| `checkouts` | `<workdir>/games` | every step finds the same repository ([checkouts.md](checkouts.md)); no deprecated per-module key is set |
| `assets.root` | the game repository | the manifest's files land in the repo verify checks |
| `discovery` | frozen snapshots (`fixtures/research`), a one-archetype catalog, no backlog, `as_of` fixed | the step's documented settings; the scan still screens and can refuse |
| `develop.developer` | `command`: the replay developer | see below |
| `review.reviewer` | `command`: the golden reviewer | see below |
| `develop.author`, `sdk.commit_author` | `wgf-golden` | the machine may have no git identity; nothing is pushed |
| `checkpoints.auto_approve` | `[G2, G3]` | both reversible; the engine refuses G4/G6/G7 whatever is listed |
| G4 decision | `pass`, by the person running the harness (`decided_by: human`) | G4 is irreversible and cannot be configured; the harness decides it as `wgf decide` would, and a harness running inside a step's tree would be `automation` and refused |

The engine is **steered through inputs, never forced**: the catalog's archetype wording
("merge", "puzzle" / "3d", "arena", "drive") leads the design module's own archetype
selection to a 2D grid puzzle or a 3D arena, so the design declares `pixijs` or `threejs`
itself, the tech plan pins it and init writes it into `game.config.yaml`. The workflow YAML
and every module are unchanged. `test_golden_fast` runs research -> G3 for real and asserts
the engine.

**Phaser has no golden run**, and that is deliberate. A golden replays a whole example game
the template ships (`examples/<name>/` plus its `wgf-golden` overlay); the template ships no
Phaser one, and writing a third game to get a third golden is a large amount of game content
for a renderer that the pipeline does not branch on — which is exactly what this pair already
proves. `phaserjs` is proved where the engine-specific behaviour actually is:

| Claim | Proved by |
|---|---|
| The template builds and boots it, the canvas appears, the loop steps, pause and resume work | `pnpm build:engine phaserjs` then the template's own `tests/e2e/` (smoke and lifecycle), run for every engine by `verify.yml` |
| Phaser's own loop is stopped, `render()` steps it once, `destroy()` runs the deferred teardown, a re-init works | `packages/phaser-framework/tests/renderer.test.ts` |
| The Factory plans, creates and develops a Phaser title | `test_techplan_module` (selection), `test_init_module` (the engine reaches `game.config.yaml`), `test_develop_module.Conformance` (the engine's modules, and the other 2D engine refused) |

A Phaser golden becomes worth adding the day the template ships a Phaser example game.

### Never contacting a portal

A build for a portal loads that portal's SDK from its CDN, so every browser test in the
pipeline would fetch it. On a machine with network, the template's own smoke test
*"makes no insecure requests"* then fails on a Poki build — Poki's SDK pulls an `http://`
ad bridge (observed). The harness therefore runs the whole workflow with HTTP(S) proxy
variables pointing at a closed local port, `no_proxy` = localhost (`SANDBOX_ENV`); Chromium,
git and pnpm honour them. The replayed specs and the browser probe additionally abort every
non-localhost request. This is a guard, not a sandbox: a process that ignores proxy
variables is not stopped by it.

## The replay developer — not an AI developer

`scripts/golden/replay_developer.py` runs through the real `command` developer kind and
`wgflib.procs`, where an agent host would. It does **not** write a game from the brief. It
ports a known-good example into the layout the brief requires:

1. refuses a brief whose engine is not the replayed game's;
2. copies the portable example files **from the repository's own `examples/`** (rules or
   simulation, the engine view, input, unit tests) with import paths adapted and a
   provenance header (the mapping: `fixtures/<game>/port.json`);
3. copies the hand-made adaptation **from the ports checkout** (`--ports`) — port.json's
   `overlays`, `examples/wgf-golden-shared/` then `examples/<example>/wgf-golden/`, laid onto
   the repository root (their READMEs, `library/`, `baseline/`, `release-1/` and the old
   default integration excepted): the game's entry `src/game/index.ts` (`createGame(context)`,
   the template's contract 2), the scene calling the brief's `GameIntegration` seam instead
   of `platform.showRewarded` / `withAdBreak`, UI and pause screens, a small audio service,
   `en`/`ru` locales, `index.html`, and a browser spec tagged `@boot @loading @start @input
   @core-loop @progression @game-over @restart @pause-resume @responsive`;
4. boots that entry through the seam the develop step already wrote, as the brief asks any
   developer to: `await createGamePlatform()` for the platform, `createGameIntegration(game,
   platform)` for the seam, no `createPlatform`. The ports carry no `main.ts`. **Temporary
   release-1 bridge:** the pinned release (`v1.2.0`) is still contract 1 - its `main.ts`
   starts the template boot scene and there is no `src/game/context.ts` - so on such a
   repository (detected, never assumed: no `src/game/context.ts`, or only the bridge's own from
   an earlier visit, which carries the replay header) the replay writes the
   template-owned bridge port.json names under `boot_bridge`
   (`examples/wgf-golden-shared/release-1/` of the ports checkout): a `src/main.ts` that is
   the release's boot order with the seam lines, calling `createGame` with the `GameContext`
   it builds, and that type as `src/game/context.ts`. The report's `replay.boot_bridge`
   records it. On a contract-2 repository the template's own `main.ts` calls `createGame` and
   nothing is bridged; the bridge goes away when the lock's release moves to a contract-2
   template. (A legacy port that still carries `main.ts` is moved onto the seam by
   `SEAM_REWRITES`: each line must be found exactly once, or the replay refuses.)
   `src/game/integration.ts` is the develop step's;
5. adds the engine package the example pins (`pixi.js`, or `three` + `@types/three`) and
   updates the lockfile offline;
6. points the template smoke's `data-scene` assertion at the game's scene (the template
   boot scene file stays: `main.ts` no longer starts it, and the template's SDK matrix
   harness imports it);
7. writes `docs/development/report.json` honestly: a design MVP item the example does not
   cover is `partial` or `cut` and becomes a scope delta (since the concept-fidelity fix the
   golden designs are the replayed games - `drop-merge` for Tower Merge Rush, `arena-dodge`
   for Neon Drift Arena - so every mechanic is `built`; telemetry stays `partial`), every
   asset is `placeholder`, and `known_issues[0]` says the build is a replay.

The develop step then runs its real checks — install, conformance, typecheck, lint, unit,
build, smoke — and commits.

Every file written into a game carries a `GOLDEN-RUN REPLAY` header. The Factory keeps
only data about the replay — `fixtures/<game>/port.json` (copy and replace rules, overlays,
MVP notes, placements, known issues, the boot bridge's path) and the seam rewrites — and no
game source (the release-1 bridge too is template code): the
adaptation itself is template code, versioned with the template and pinned in the lock.

## The golden reviewer — not an AI reviewer

`scripts/golden/reviewer.py` runs through the real review step, whose fingerprint isolation
applies to it. It reads git objects only (never `git status`, which may rewrite the index)
and requests changes on any of: the commit is not HEAD; the commit changes a
template-owned path, or one outside `src/ tests/ public/ index.html docs/development/
package.json pnpm-lock.yaml`; `package.json` adds a dependency other than the engine's; a
portal SDK identifier or URL in `src/`; an ad call outside `src/platform/`; no unit test or
no browser test tagged for boot, start, game over and restart; no committed development
report for the design's engine. It judges nothing about quality or fun.

## The production gates in a golden run

The goldens fail if the art regresses to primitives or placeholders. `harness.build_config`
points `factory.assets.libraries` at the port's `library/` in the golden ports checkout, so
the real assets step delivers every MVP requirement from it (`placeholder: false`, quality
`pass`); the real `production-quality` step judges what playability recorded of the
production build (assets present, loaded, rendered, visible; no readable entity a primitive;
the DOM UI's targets, overlap, text and styling); and visual QA runs the `baseline` judge
(docs/visual-qa-module.md) on the port's `baseline/` - no agent, no mock. The summary's
`production` block holds both verdicts, and `passed` requires production-quality PASS and
visual-qa PASS by the baseline judge (`test_the_production_gates_passed_the_port_art`). A
port with no `library/` gets no library and one with no `baseline/` gets `judge.kind: none`,
which blocks visual QA: never an unjudged pass.

`python3 scripts/golden/run.py --game 2d --no-library --keep` is the calibration run: no art
library, so assets are placeholders, and the run must fail. It fails at develop - the port's
own art-guard browser test refuses placeholder art - before the production gates; the
baseline judge's numbers for that placeholder build are in docs/visual-qa-module.md.

Validated on 2026-10-01 (Factory branch `dyCuong03/wgf-p05-finish`, golden ports `5fb737d`):
2D `Ran 11 tests ... OK` twice and 3D `Ran 11 tests ... OK`; each run COMPLETED through all
20 steps with production-quality 16 of 16 checks (assets present, loaded, rendered and
visible; no primitives; UI targets, overlap, text, styling, states on both viewports) and
visual-qa PASS on 26 frames (2D 0.766-0.990, 3D 0.805-0.991 against the approved frames),
review approved, a drafted release, no leftover process. The calibration numbers are in
docs/visual-qa-module.md (*The baseline judge*). Getting there took three fixes in the ports
that only a real run exposes: the 2D greybox drew paper on paper (mean luminance 227, over
the playability ceiling of 225); the 2D asset loader sat in `src/assets/`, which verification
reads as asset files (`assets.formats`); and the 3D port refused to boot without its runtime
manifest, so the greybox phase - before any asset exists - failed every browser test. And
one in the Factory: the playability bot measured a pause card mid fade-in (text at 0.75
alpha, 3.93:1), so it now waits for finite CSS animations before measuring a screen.

Validated again on 2026-10-02 (golden ports `db7b140`), after `font.coverage` and the
`variants` checks made both runs fail `assets.present` on their own art: 2D and 3D `Ran 11
tests ... OK`, one run at a time; each COMPLETED all 20 steps with production-quality 18 of
18 checks and visual-qa PASS on 26 frames (2D 0.769-0.990, 3D 0.756-0.987 against the
re-captured frames); the 2D `pieces` ten drawings with `variants.distinct` pass, every
delivered face `font.coverage` pass for `en` and `ru`.

## The independent browser evidence

After the workflow, `scripts/golden/browser.py` clones the game repository at HEAD into
the evidence directory (the repository is not touched), installs offline, and — when release
drafted one — unpacks the **released primary-platform zip** as `dist/`, after checking its
sha256 against the manifest, so the bytes played are the bytes that would ship. Then:

- the game's own Playwright suites, desktop + mobile, JSON reporter (the template's smoke and
  the ported example spec);
- the harness's own probe (`scripts/golden/browser/probe.spec.ts`), per viewport: boot, the
  engine / platform / game id reported by the template's `window.__wgf__` probe, a real click
  to start, frames rendering, game over, restart; screenshots hashed; console errors, page
  errors and aborted external requests recorded.

The unmodified example specs are not run against the port: they assert the examples' own DOM
(`#ui[data-ready]`, `body[data-ready]`), which the template layout replaces with
`#hud[data-ready]`. The ported spec is the example's spec adapted to that contract.

## What the golden runs prove, and what they do not

They prove that one workflow, one engine and the real modules take a market scan to a
drafted release for a PixiJS game and a Three.js game alike; that the artifacts chain by hash
and validate; that the repository the Factory creates builds and passes the template's
browser tests on desktop and mobile; that the release packages the verified bundle; and that
no process outlives the run.

They do **not** prove:

- **that an AI developer can build a game.** The developer is a replay of a known-good port.
  An agent developer must be validated separately (`docs/development-module.md`).
- **that a reviewer finds real defects.** The reviewer is a rule check.
- **anything about a portal.** No portal is contacted. SDK features are exercised against the
  template's mocked portal SDKs, so their evidence is `PASS_MOCK`; each portal's own QA is
  `BLOCKED_EXTERNAL` and `external_approval` is `not-claimed`. The summary copies these
  statuses; it never upgrades them. `PASS_MOCK` is not `PASS`.
- **design quality.** The design module's archetypes do not include a drop-and-merge game;
  the 2D report lists the deltas.
- **the content contract on an authored game.** Both golden designs are **parametric arcade**:
  the fixture catalogs pin `design_archetype` (`drop-merge`, `arena-dodge`) and
  `genre_model: arcade`, and the archetypes state `genre.ending: endless` with
  `build_spec.content.generation.mode: parametric` — the units they list are the representative
  run-segments the design commits to, not a sequence the build traverses. So the goldens do
  exercise the design step's content rules, the brief's content table, the tech plan without
  `CONTENT-nnn` tasks (a generated design gets none) and the generated-content playability
  path, and they do **not** exercise the authored path: no `public/content/units.json` is owed,
  `content.units_reachable`, `content.objective_shown` and `content.win_lose_per_unit` are
  `SKIPPED` with the reason "content is generated (parametric)", and `progression.persists` and
  `depth.session_length` are warnings rather than failures because the generation mode is not
  `authored`. `difficulty.axes_progress`, `content.variety` and `depth.ramp` are measured from
  the endless windows and the in-run content schedule. A level game — the authored path, a data
  file compared unit for unit — has no golden run and needs its own port before it has one.
- **the release tier.** A golden run sets `factory.strategy.quality_tier: mvp`
  (`scripts/golden/harness.py`): it is a pipeline regression of a known-good port at MVP
  tier. At `release` the design step holds the design to the quality benchmark's content bars
  (`content.tier_*`, game-design 1.12.0), which the built-in design authors the golden runs
  use do not write to - a true finding at that tier, not a fixture to loosen. So the goldens
  do not exercise a release-tier design, the content budget or the tier rules; the unit tests
  do (`scripts/tests/test_design_content.py`, `TheQualityTier`).
- **the GitHub path.** `init.source: local`; creating a repository with `gh` is outward-facing
  and is not exercised.
- **that the art suits every locale.** The ports' bundled display and body fonts are subset
  Latin builds with no Cyrillic: the `ru` locale both ports ship falls back to a system font
  for its text. A known limit of the fixtures, not hidden by any check: production-quality
  measures the DOM text it sees, which the golden runs play in `en`.
- **that the art is good.** The baseline judge proves the run's frames look like frames a
  person approved, not that the approved look is good; an agent judge (`kind: command`) is
  what reads a new game's frames against the rubric.

## The golden loop

A golden run proves the pipeline carries a known-good game to a release. It does not prove
the Factory's loop: that a real build failing a real check is routed back, rebuilt, and the
**same check re-played and passed on a newer commit** - through the production workflow, not
a fixture world. The golden loop does, with no LLM: the 2D golden with a defect planted by
the replay developer.

```
greybox (visit 1)       replay plants `restart-dead`             -> commit A
greybox-playability     clones A, builds, plays in Chromium:     FAIL  restart.works
                        the bot clicks the result screen's          (desktop + mobile,
                        restart, the run stays lost                 frames end-lost, retry-dead)
  route fail -> greybox (visit 2), brief.json playability_failures names restart.works
greybox (visit 2)       replay reads the brief, leaves it out    -> commit B (descends from A)
greybox-playability     clones B, builds, re-plays:              PASS  restart.works (measured)
assets -> ... -> release                                          the normal golden outcome
```

**The defect.** `replay_developer.DEFECTS["restart-dead"]` (2D only, greybox phase only):
in the port's `src/game/index.ts` the result screen's `restart` UI action keeps `click();`
and drops `void app.restart();`. Typecheck, lint, the unit tests and the port's own browser
tests (which restart through the `window.__game.restart()` hook) all pass; only a player's
click on the button - the bot's, at the coordinates the play probe lists - finds it dead.
`restart.works` is a hard check and a universal-floor blocker. The rewrite is an exact-once
string replacement in the style of `SEAM_REWRITES`: an anchor not found exactly once refuses
the replay (exit 3) before anything is written, on a repairing visit too.

**Plant and repair are read from the brief, nothing else.** `defect_decision`: a greybox
brief whose `playability_failures` name no `restart.works` failure gets the defect
(`planted`); one that names it - the develop step hands a visit the failed checks of the
report that played the commit it starts from - lays the port's own line (`repaired`); a
production visit lays the port as it is (`not-applied`). Each visit records what it did in
`docs/development/report.json` `replay.defect`, labelled `GOLDEN-LOOP DEFECT: a scripted
rewrite ... a replay, not an agent's fix`. The repair proves the routing and the re-play,
not a developer's ability to fix anything - that is the live loop's question.

**Evidence.** The playability bot captures `retry-dead` - the screen a retry that never
returned to play leaves - and `restart.works` cites the lose recording's `end-<reached>`,
`retry-dead` and `state-retry` frames. `scripts/golden/loop.py` reads the run store and the
game's history and writes `evidence/golden-loop-2d.json`: every greybox-playability report
(commit, verdict, `restart.works` per project with its viewport, summary, measurement and
frames - path, existence, sha256), the developer record at each commit, the visits, how the
run ended, a `before` / `after` pair, and `closed` with the `reasons` it is not. The first and
the last report's frames are copied to `evidence/golden-loop/v<n>-<commit>/<project>/`.
`closed` requires: v1 FAIL with `restart.works` FAIL on desktop and mobile, citing frames that
exist, on a commit recorded `planted`; the last report PASS with `restart.works` PASS on both
(UNMEASURED, SKIPPED, BLOCKED or absent never count) on a commit recorded `repaired`; that
commit different from and descending from A; greybox visited at least twice.

**The negative control.** `--defect restart-dead --no-repair` plants it on every greybox
visit whatever the brief says. The loop must not close: greybox is entered once and then
`max_visits_by_route: {greybox-playability.fail: 2}` more times, every report FAILs
`restart.works`, and the engine stops the run `BLOCKED` (`blocked_reason.kind: loop-limit`,
step greybox) - nothing after greybox runs, nothing is released, and `closed` is false.

```bash
python3 scripts/golden/run.py --game 2d --defect restart-dead --keep        # exit 0: closed
python3 scripts/golden/run.py --game 2d --defect restart-dead --no-repair   # exit 0: not closed
python3 scripts/golden/run.py --game 2d --defect restart-dead --defect-stage develop --keep
python3 scripts/golden/run.py --game 2d --defect restart-dead --defect-stage develop --no-repair
WGF_GOLDEN_LOOP=1 bin/wgf test-core --only "GOLDEN LOOP" --strict           # all four, asserted
```

Measured 2026-10-09 on Windows 11 (k6/golden-loop): the repaired run planted the defect at
commit A `700ec25`; greybox-playability failed exactly `restart.works`, on desktop (1280x720)
and mobile (393x851) - "retry (input:restart) returned to play in None ms; score did not
reset", `retry-dead` showing the game-over screen 15 s after the press; greybox's second visit
(source diff: the one restored line) built B `38244e9`, re-played `restart.works` PASS (568 /
604 ms) and the run completed every step to the drafted release (61.6 min). The negative
control failed `restart.works` on all three greybox builds and stopped BLOCKED at the loop
limit after 39 min. Eleven of the twelve GOLDEN LOOP tests passed; the twelfth is the
template's own `makes no insecure requests` smoke in the independent browser evidence, the
known Windows environment failure every Windows golden shows (Chromium on win32 ignores the
refusing proxy), not the loop.

### The develop stage: through triage and the finding ledger

The greybox loop never reaches the Factory's own Diagnose -> Repair -> Verify bookkeeping:
greybox-playability's `fail` goes straight back to greybox, so no triage runs and the run's
finding ledger stays empty. `--defect-stage develop` plants the same defect in the first
**production** develop visit instead (the greybox stays clean), where a playability failure
goes through triage:

```
greybox -> greybox-playability PASS -> assets -> triage (nothing to route)
develop (visit 1)       replay plants `restart-dead`                -> commit A
playability             FAIL restart.works (desktop + mobile, frames)
  route fail -> triage  normalizes playability-report:restart.works@desktop / @mobile,
                        classifies them (specialist-routing: restart.works -> ui -> ui),
                        assigns them and routes `ui`
develop (visit 2)       entered as triage.ui: briefed as the UI specialist with the two
                        findings (brief.json specialist.findings); the replay reads them and
                        leaves the defect out                        -> commit B
playability             PASS restart.works, measured
production-quality -> visual-qa -> content-sufficiency -> review -> sdk -> sdk-review ->
verify -> quality-gate  advances the ledger: implemented (B) -> verified (playability on B)
                        -> closed (every gate measured B)
G4 (the harness passes it, as in every golden) -> store-listing -> listing-validation -> release
```

**The decision** (`replay_developer.defect_decision(..., stage="develop", prior=...)`): a
production visit whose brief names no `restart.works` failure plants it; one whose
`specialist.findings` include a `playability-report` finding of `restart.works` - or whose
`playability_failures` name it - leaves it out (`repaired`); a later visit that names
nothing keeps it out (`kept-repaired`), read from the replay's own record in the checkout the
visit starts from. The record (`replay.defect`) adds `stage`, `specialist`, `findings_named`
and `triage_report`; it is still a replay, never an agent's fix. Without `--defect-stage`
nothing changes.

**Closed** (`loop.record(stage="develop")`, `evidence/golden-loop-2d-develop.json`): the
greybox-stage conditions over playability's reports - `after` is the report of the visit
that repaired it - and, for each project's finding, the run's own ledger: a triage-report
detected and assigned it; develop was entered for its owner (`triage.<owner>`); the newest
ledger (the quality-report's) holds it verified or closed, through `implemented`, with
`fix.commit` = B; `verification.verdict: passed`, `before` = A's FAIL and `after` = B's PASS
of the same scenario id `restart.works@<project>`, `comparison.same_scenario` true, every
frame either side cites on disk with its sha256; and the quality-report's `open` does not
list it. The record copies the ledger records in (`ledger.triage`, `ledger.quality`,
`ledger.final` with `frames_on_disk`) and the quality-report's assessment lines
(`assessment`).

**Its negative control** (`--defect-stage develop --no-repair`): every develop visit plants
it, briefed or not. Playability fails it on each build, triage reopens the finding
(`still-failing`) and routes it to the UI specialist again, and on the third failure
triage's `max_visits_by_route: {playability.fail: 2}` stops the run `BLOCKED`
(`blocked_reason.kind: loop-limit`, step triage). The ledger never verifies the finding and
`closed` is false.

Measured 2026-10-09 on Windows 11 (k6/develop-loop), run `new-game-20261009-115717-1f2d20`,
64.9 min: greybox `5d5298e` PASS; develop planted the defect at A `76d9556`; playability
FAILED exactly `restart.works` on desktop (1280x720) and mobile (393x851) - "retry
(input:restart) returned to play in None ms; score did not reset", frames `end-lost`,
`retry-dead`; triage routed "2 finding(s) to UI (route `ui`)"; the UI visit's commit B
`c6fb256` restored the one line (`void app.restart();`); playability re-played
`restart.works` PASS (635 / 738 ms). Every later step passed (verify 148 pass, 0 fail), G4
was passed by the harness and release r1 was drafted at the sdk commit `62b1366`. The
quality-report's ledger holds both findings **closed**: detected (playability-report 01, A,
seq 15) -> classified (specialist-routing 1.6.0, ui) -> assigned (triage-report 02) ->
implemented (prototype-report 02, B, seq 17) -> verified (playability-report 02, B, seq 18,
"the same scenario, bot and settings measured the failure and the pass") -> closed
(quality-report 01: every gate measured B); `open: []`; one sample. The assessment: design
validity, runtime correctness and player-facing quality all **INCONCLUSIVE** - runtime
correctness holds `playability:restart.works` PASS and nothing FAILED, but 10 of its 60 held
checks measured nothing (browser QA's `browser.win`, `.lose`, `.restart`, the audio and
context-menu checks report WARNING on this port: the design states no win, bad play does not
lose within 90 s), and no person had judged the build when the quality gate ran. The
GOLDEN LOOP assertions do not require a runtime PASS for that reason.

The negative control, measured 2026-10-10 (run `new-game-20261010-062926-0102fe`, 53.9 min;
an earlier attempt was interrupted by a host restart and is not counted): develop planted
the defect on all three visits (`7ebb60b`; then `1d0142a` and `31c64a7`, each briefed as the
UI specialist with both findings and planting it anyway), playability FAILED `restart.works`
on desktop and mobile each time, and the run stopped `BLOCKED` at triage (`loop-limit`,
`playability.fail`, limit 2). The ledger took each finding detected -> classified ->
assigned -> implemented -> classified (`still-failing`: reopened) -> assigned and never
verified it; no quality-report was produced; `closed` false; `control_held` true. The run.py
exit status of a negative control now needs that too (`loop.control_held`: versions, every
one FAIL on every project, every developer record `planted`): a record that could not be
read is also `closed: false`, and used to pass the control vacuously.
Asserted on the two kept runs (`WGF_GOLDEN_LOOP_DIR`): `GoldenLoopDevelop2D` 9 of 10 - the tenth
is the same `makes no insecure requests` browser smoke, the known Windows environment
failure - and `GoldenLoopDevelopNoRepair2D` 5 of 5.

`scripts/tests/test_golden_loop.py` is the **GOLDEN LOOP** category, gated by
`WGF_GOLDEN_LOOP=1` (SKIP otherwise; a skip is never a pass). It is **opt-in**
(`core_suite.OPT_IN`): a plain `wgf test-core` - the release gate included - leaves it out and
says so under the table, unless the variable is `1` or the category is named with `--only`.
It asserts everything above from the run store, `git show <commit>:` and the files on disk,
plus the run's normal golden outcome for the repaired runs: four classes, `GoldenLoop2D`,
`GoldenLoopNoRepair2D`, `GoldenLoopDevelop2D` and `GoldenLoopDevelopNoRepair2D`, four golden
runs. `WGF_GOLDEN_LOOP_DIR=<dir>` runs each class in `<dir>/<key>` (`greybox`,
`greybox-no-repair`, `develop`, `develop-no-repair`); a class whose directory already holds a
finished run's summary is asserted on that kept run instead of running again. CI runs it in
its own job (`golden-loop` in `.github/workflows/acceptance.yml`, 360 min), never in the
acceptance job: on a manual
run with `golden_loop` ticked, or on a pull request labelled `golden-loop` (the
label takes effect on the next push or re-run), and uploads `golden-loop-evidence`. The
always-on part - the anchors against the pinned port, the decision, the refusals, the argv,
`loop.record` over a synthetic store and a real git history - is `GoldenLoopFast` in
`test_golden_fast.py`.

## The live loop

`scripts/golden/live.py` (`test_live_loop.LiveBuildConverges`, opt-in: `WGF_LIVE_AGENT=1`,
costs money) asks what a golden run cannot: does a real developer -> reviewer loop
**converge** on a game the developer builds from the Factory's own brief? It is the 2D golden
pipeline - the frozen research inputs, so strategy, design and tech plan come out the same
every run; the pinned template; the real develop checks, sdk, verify, G4 and release - with:

- the developer and the reviewer `workspace/config/factory.yaml` documents, **verbatim**,
  from develop visit 1, with the steps' own prompts: the developer builds the game from
  scratch from the brief, the reviewer judges it against the design. No replay, no planted
  defect, no prompt written for the test;
- no refusing proxy: the hosts need their API, and the developer runs pnpm online.

It passes only on convergence: the run COMPLETED, the last development commit approved by
review and the sdk commit by sdk-review, every develop check green on it, only the
developer's own files changed, every verdict trusted, no process left. It does not require a
first review to request changes. A run keeps both argvs, where they came from and the host's
version in `evidence/live-agents.json`.

`python3 scripts/golden/live.py config --workdir DIR --human-gates` writes the same
configuration as `DIR/factory.yaml`, with no gate auto-approved, for a run a person drives
with `bin/wgf new-game --config ... --store ...` and decides G2, G3 and G4 with `wgf decide`.
Both the live build and that configuration run under a developer budget,
`golden.live.LIVE_BUDGET` (`factory.develop.budget`: 6 sessions, US$120 by the host's
`total_cost_usd`), snapshotted when the run starts and recorded in `live-agents.json`; the
host's own `--max-budget-usd` bounds only one session.

**Why not the replay.** The post-2.0.0 live validation first planted a defect in the golden
replay and let a live reviewer find it. The reviewer rejected the build on six design-fidelity blockers
and never reached the defect, correctly: the golden 2D design was then the design module's
`merge-puzzle` archetype - a 7x7 swap-and-match game with levels, goal colours and a move
limit - while the strategy and the replay are Tower Merge Rush, a drop-and-merge game. That
mismatch is fixed at its root (the design now follows the strategy's concept, and two
blocking consistency rules refuse a design that drops or adds a core mechanic; see
CHANGELOG), but the live build still builds from scratch: a replay is not an agent's work.

## Repeatability

Given the same template commit, fixtures and Factory code, two runs agree on everything but
what is inherently per-run. `scripts/golden/compare.py a.json b.json` checks it.

Measured 2026-09-24 (WSL2, warm pnpm store, Chromium 1243): each run 220-350 s wall
clock; the time is `develop` (checks incl. the e2e smoke, 30-180 s) and `verify`
(45-170 s). Every other step is under 10 s. Two consecutive runs of each game compared
`REPEATABLE`: identical step outcomes, engine records, research/opportunity hashes, files per
commit, package content digests, evidence statuses (`PASS_MOCK` overall; poki portal
`BLOCKED_EXTERNAL`), verification counts and browser results.

Legitimately different between two runs:

- run ids, timestamps (`produced_at`, `created_at`, event times, `checked_at`), durations;
- every artifact content hash that embeds a timestamp or the run id — which, through
  provenance chaining, is every artifact from `strategy` on (research is pinned by `as_of`);
- commit SHAs (commit dates differ), and so the idempotency keys and trailers;
- zip `checksum`s: web-game-template's `package.mjs` stamps entries with file mtimes
  (`evidence.reproducibility.archive_bytes: timestamp-dependent`, see
  [release-module.md](release-module.md));
- screenshot hashes (the loop runs on wall-clock frames).

Must be identical: the step outcomes and routes; the research report and opportunity content
hashes; the engine everywhere; the set of files each commit touches; the release's package
`content_digest`s (entry names and bytes); the test counts and results.

## How module work is validated against them

Core v1 is frozen ([core-v1.md](core-v1.md)). A change to any module in the pipeline is
validated by its own tests, the contract tests, `wgf test-core`, **and both golden runs**:

```bash
WGF_GOLDEN=1 bin/wgf test-core
```

A golden run that stops at a step names the step and the module's own message in the
summary (`steps[].message`). Fix the module, not the harness: the harness may only change
what it feeds the pipeline through documented settings. If a module legitimately changes
what a run produces (a new required check, a new artifact field), update `games.py`
(`EXPECTED_STEPS`) or `testing.py` in the same change and say why in the commit.
