# Changelog

Notable changes to the methodology. A change here can invalidate an artifact that already
exists, so each entry says what it would take to bring one forward.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). The Factory is
released as a whole (`v1.0.0` is Core v1, frozen); schemas still carry their own versions,
and `core/` is still the contract.

## [Unreleased]

The 2D asset pipeline: atlas packing, a runtime asset manifest game code loads through, and
validation of both. A change to the `assets` module (with one consumer line each in `develop`
and `verify`): `game-design` and `asset-manifest` move to 1.2.0 and `asset-policy` to 1.1.0,
all additive - every 1.1.0 design and manifest remains valid, and an existing design produces
the manifest it did plus `runtime_manifest`. No engine, workflow, lifecycle, gate or template
change. Details: [docs/assets-module.md](docs/assets-module.md).

### Added

- **Atlas groups.** A sprite, UI, icon or VFX requirement may name an `atlas`; each group is
  packed deterministically (stdlib PNG codec, shelf packing, extrusion, padding, power-of-two)
  into `public/assets/atlases/<group>.png` + `.json` (TexturePacker JSON Hash, read unchanged
  by PixiJS and Phaser). Members' own images go to `src/assets/`, so each pixel ships once;
  `texture-atlas` moves from `deferred` to `applied`.
- **The runtime asset manifest** `public/assets/assets.json`
  (`core/artifacts/shared/runtime-assets.schema.json`): every loadable asset by id, URLs
  relative to the manifest, atlas frames, sizes, `scale`, spritesheet frames and animations
  (fps, loop), tileset grids, file hashes. No timestamps or absolute paths; byte-identical for
  identical assets. The asset manifest records its path and hash.
- **Requirement fields** (`game-design` 1.2.0): `atlas`, `scale` (1-4), `animations`,
  `tile_width`/`tile_height` and the new `tileset` kind, `existing.atlas`.
- **Validation**: SVG safety, texture-edge limits, transparency expectations per kind,
  dimension and tileset checks, atlas descriptors against their images (frames in bounds,
  animations naming real frames, `meta.image`), duplicate paths; ten new issue codes. AVIF is
  recognised (it was sniffed as M4A).
- **`scripts/wgf-assets.py`**: `build`, `validate`, `pack`, `inspect`; JSON output and exit
  codes 0/1/2.
- **`assets.runtime-manifest`**, a verify check that validates the repository against its
  runtime manifest; the develop brief's `runtime_assets` and its loading rule.
- **`core/craft/2d-assets.md`**: how to ask for 2D assets and load them in PixiJS and Phaser;
  read by the asset agent and the `assets`, `pixijs` and `phaser` skills.
- **Pruning**: placeholders and pipeline-made atlases nothing references any more are removed
  (`prune: false` to keep them); nothing else is ever deleted.

### Fixed

- **The installed Claude plugin only worked from the factory repository.** Claude Code installs
  a plugin as a copy of its own directory, which held surfaces and nothing else: every command,
  agent and skill read `core/` relative to the working directory, and `/web-game-factory:new-game`
  stopped unless `core/workflows/new-game.workflow.yaml` was there. Run from a game project it
  could not find the Factory. The plugin now ships the runtime closure in
  `claude-web-game-plugin/runtime/` (`scripts/build-plugin-runtime.py`, run by
  `gen-adapters.sh`, drift-checked by `check-integrity.py`), and every Claude surface names
  Factory paths as `${CLAUDE_PLUGIN_ROOT}/runtime/...`. The engine now keeps two roots
  (`wgflib/paths.py`): the Factory (`ROOT`, beside `wgflib/`) and the project (`PROJECT`:
  instance data, run store, checkouts base). In a development checkout both are the
  repository, so nothing there changes; from an installed runtime the project is the working
  directory, or `WGF_PROJECT_DIR`. New: `wgf where [--json]`. `wgf test-core` refuses to run
  from an installed runtime. See `docs/plugin-runtime.md`. Regressions in
  `test_plugin_runtime` and `test_adapter_binding.ClaudeSurfacesReadThePluginRuntime`.
  *Migration:* none for a development checkout. A project using the installed plugin keeps its
  runs in `<project>/.factory/` and may add its own `workspace/config/factory.yaml`.
- A library spritesheet renamed to its asset id kept the library's `meta.image`, so a loader
  following the descriptor fetched a file that was not there. It is rewritten on copy, and an
  existing sheet whose descriptor names another image is `invalid-atlas`.
- An existing spritesheet was accepted without its atlas descriptor.

### Bringing an artifact forward

Nothing is required. To use the new fields, add them to a design's `asset_requirements` and
re-run `assets`; a game adopts the runtime manifest by loading through it
(`core/craft/2d-assets.md`).

## [2.4.0] - 2026-09-30

A minor version: one new adapter surface and the evidence and fixes MV-4 produced. No engine,
workflow, lifecycle, gate, schema or template-contract change, and no template pin change
(still `v1.2.0`). Release record: [docs/v2.4-release.md](docs/v2.4-release.md).

**`/new-game`** is the first *workflow entry point*: one Claude Code command (and its Codex
prompt) that runs `core/workflows/new-game.workflow.yaml` through the existing engine and stops
at every gate for a person. The `/wgf-*` transition commands are unchanged. The Claude plugin
is released with the Factory, so it moves to `2.4.0` with `VERSION`.

MV-4 (`docs/mv-4-report.md`): real-world evidence, and the five Factory defects that running
the existing suite on a second operating system exposed. Its Windows measurements were taken
against template `v1.1.0`, the pin in force when they were made; 2.3.0 moved the pin to
`v1.2.0`.

### Added

- **`/new-game`, a workflow entry point in the Claude Code plugin** (and `commands/new-game.md`
  in the Codex adapter): one command that starts, or with `resume <run-id>` continues, a run of
  `core/workflows/new-game.workflow.yaml` through the existing workflow engine
  (`bin/wgf new-game` / `bin/wgf resume`), in the background, and reports it from
  `bin/wgf status`. The engine and the workflow file stay the only orchestrator - step order,
  retries, loops, gates, decisions and resume - and the command restates none of it nor
  composes the `/wgf-*` commands. Gate decisions stay human-owned: it never runs `wgf decide`
  or `--decision` (from the session they would be recorded as a person's), refuses those
  arguments, and at every gate or develop handoff stops with the command the person types.
  It reports the configured autonomy without changing `factory.yaml`, and warns before a real
  run whose init creates a GitHub repository. `disable-model-invocation: true`.
  - A new binding surface kind, `workflow` (`workflows:` in
    `core/bindings/adapter-binding.yaml`, manifest 1.5.0), generated by `gen-adapters.sh`
    from its own table. `commands:` stays transitions only: the 13 `/wgf-*` commands are
    byte-identical after regeneration.
  - `check-integrity.py` checks each entry point against its workflow file (a `core/` path
    named `<id>.workflow.yaml`, whose id it is, with exactly the gates its checkpoints
    name). `scripts/tests/test_adapter_binding.py` ties the binding, the generator tables,
    the generated files and both `CONFORMANCE.md` files together by id, and holds the entry
    points to pointing at the engine and never answering a gate.
  - Claude plugin `2.4.0`, with `VERSION`: installed copies see the update and pick the new
    command up. Its full name in Claude Code is `/web-game-factory:new-game`.
- `scripts/mv4/`: the MV-4 evidence harness. `session.py` + `session.spec.ts` measure a built
  game in a real browser on the bytes that would ship (load, frame times, audio unlock,
  visibility, resize, heap across a restart, telemetry), labelling every measurement with the
  class of thing it was taken on; `device.py` records a real-device measurement or an explicit
  UNVERIFIED with the reason, and refuses a capture that does not carry the handset's identity;
  `playtest.py` computes the two player kill criteria and refuses to count a developer test or
  to report a share from fewer than five first-time participants; `packaging.py` audits what a
  release actually packaged; `g4.py` assembles the G4 record and refuses to let a weaker
  measurement class decide a criterion. Tests: `scripts/tests/test_mv4.py`.
- `docs/mv-4-plan.md`, `docs/mv-4-playtest-protocol.md`, `docs/mv-4-touch-sheet.md`,
  `docs/mv-4-report.md`, and the evidence under `docs/evidence/mv-4/`.

### Fixed

- **A reviewer's blocker could name a file outside the repository.** The guard on
  `blockers[].file` was written on `os.path.isabs`, which is the host's rule: on Windows with
  Python 3.13+ it accepted `/etc/passwd`, and on POSIX it accepted `C:\Windows\x` and
  `..\..\secrets.env`. `wgflib.paths.repo_relative` now judges the string - no leading
  separator of either kind, no drive, no `..` on either separator - so every host agrees.
  Regressions in `test_core_security.HostileIdentifiers`.
- **No child process could be started on Windows.** `CreateProcess` does not apply `PATHEXT`,
  so `procs.run(["pnpm", ...])` failed with `WinError 2` against an installed `pnpm.CMD` and the
  step reported the tool as not startable. `procs` now resolves `argv[0]` on the child's own
  `PATH` when it has no directory part, accepting only a file - a directory of the same name on
  `PATH` satisfies `shutil.which` and then fails as `WinError 267`. POSIX behaviour is
  unchanged. Regressions in `test_core_process.ResolvingTheProgram`.
- **An agent could not start a tool at all on Windows.** The agent environment is an allowlist
  and it held only the POSIX names; without `SystemRoot` no child starts there, so every golden
  run's developer refused with `NotADirectoryError: [WinError 267]`. The same basics are now
  allowlisted under the names Windows uses (`SystemRoot`, `windir`, `COMSPEC`, `PATHEXT`,
  `SystemDrive`, the Program Files and ProgramData locations, `USERPROFILE` / `APPDATA` /
  `LOCALAPPDATA`), and names are compared the way the platform compares them. No credential
  name was added and the secret-name filter is unchanged. Regressions in
  `test_core_security.AgentEnvironment`.
- **The refusing proxy reported isolation it did not have.** `wgflib.netguard` is set through
  the proxy environment variables, which Chromium reads on Linux and ignores elsewhere in favour
  of the system configuration. Its summary now carries `enforced` and, when false, the reason,
  so `refused_requests: 0` cannot be read as "nothing got out" on a platform where nothing was
  routed through it. The proxy itself is unchanged. Regression: `test_netguard.Enforcement`.
- **A finished run's report was lost to the console's encoding.** Anything the CLI prints can
  carry a character the console cannot encode; on cp1252 that raised `UnicodeEncodeError` after
  the work was done and printed nothing at all (a whole `test-core --json` run). The CLI's
  streams now escape what they cannot encode. Regression:
  `test_workflow_cli.ConsoleEncoding`.
- **The release tests could not reach their own fixture on Windows.** The suite shims `pnpm`
  as an extension-less script with a `#!` line, which Windows cannot execute; the real `pnpm`
  was found instead and the tests measured a repository with none of the fixture's scripts. The
  fixture writes a `pnpm.CMD` beside the shim there. No test changed what it asserts.
- **A golden run record differed by host**: `scripts/golden/live.py` wrote the config's path
  with the host's separator. It now uses `paths.display`.
- **The Claude plugin reported `0.4.0` through 2.3.0.** Claude Code detects a plugin update by
  `plugin.json`'s `version`, and it had not moved since 2.0.0, so an installed plugin never saw
  one. The plugin is released with the Factory: its version is now `VERSION` (`2.3.0`), and
  `check-integrity.py` fails when the two differ or when the marketplace entry sets a version
  of its own. Regressions in `test_check_integrity.PluginVersionTest`.

## [2.3.0] - 2026-09-29

Both engines gained ground. **Phaser is a second 2D engine** — `engine.type` accepts
`phaserjs` next to `pixijs` and `threejs`, the pinned template ships `@wgf/phaser-framework`
(web-game-template 1.2.0), and a Phaser title gets its own craft playbook and skill. **The
Three.js half of the pipeline gained the craft it never had**: three 3D playbooks, a physics
decision recorded at G3, and engine notes in the develop brief. And the acceptance gate that
could not run on a Windows host now runs on a Linux runner in CI, which is how both golden
runs were proved for this release.

**PixiJS remains the 2D default and is unchanged**: a design that records `dimension: 2d` and
no engine still selects `pixijs`, and no existing artifact, workflow, gate, role or platform
changed.

A minor Factory version with a **major template contract** (`CONTRACT_VERSION` 1.0.0 → 2.0.0):
`packages/phaser-framework/` and `src/rendering/phaserjs/` follow from the new engine id by
the template's naming convention, and they are required entries, so a repository generated
from a template older than 1.2.0 is now refused by init. That is the whole breaking surface.

**Upgrading from 2.2.x:** re-pin nothing by hand — `workspace/config/template.lock.json`
already names web-game-template `v1.2.0`. What you will see:
- A game repository created before the pin move is still built and verified as before; it is
  only `init` that refuses to *create* one from an older template.
- A design may now declare `engine.type: phaserjs`. Nothing selects it for you.
- A Phaser title's develop brief recommends the `web-game-factory:phaser` skill and, as a
  generic skill, the Phaser Game Agent — for reading API knowledge and reusable blocks, never
  for writing the checkout: that tooling owns its own cloud project layout, and here the
  template owns the layout and the build.

### Added

- **3D craft playbooks** (`core/craft/3d-scene-and-physics.md`,
  `core/craft/3d-assets-and-animation.md`, `core/craft/3d-diagnostics.md`). The template's
  Three.js binding is a renderer, one scene and one camera, so a 3D game writes its whole
  runtime; the Factory now says how. Parts adapted from
  `majidmanzarpour/threejs-game-skills` (MIT). The `threejs`, `web-performance`, `qa` and
  `gameplay-review` skills read them (adapter binding 1.3.0); no new surface id.
- **`tech-plan.architecture.physics`** — optional, additive, so every existing tech plan
  stays valid. The physics approach and its exact package are decided at G3
  (`with: {physics: custom|rapier|cannon-es}`), never inferred from the design and never at
  development time. The develop brief quotes the line and allows only the package it names;
  the reviewer treats an unplanned physics dependency as a blocker.
- **Engine notes in the development brief**, for `threejs` only (`brief.json`
  `engine_notes`; a 2D brief is unchanged): what the renderer binding already owns, the one
  update order, the model and clip checks after import, restart releasing everything, and a
  required `@boot` assertion that the canvas is neither blank nor a single flat colour, with
  the renderer's counters logged. No new gameplay aspect and no Factory-side probe: a 3D
  build that renders nothing otherwise passes every check it has.
- `docs/3d-benchmark.md` — the protocol for measuring the 3D developer capability. No
  results are recorded; the only measured baseline is the golden pair.

- **`phaserjs` in `core/artifacts/tech-plan.schema.json`** (`engine.type` and
  `repo_params.build.engine`), which is the one list `wgflib.template_contract.ENGINES` and
  `guards.supported_engines()` read. The renderer package and rendering directory follow from
  it by convention; the drift test holds both against the pinned template.
- **`core/craft/phaser.md`** and the generated `phaser` skill in both adapters (binding
  manifest 1.4.0): the loop game-core owns and Phaser does not, scenes and their shutdown,
  assets, input, tweens, arcade physics, tilemaps, cameras, audio, a debugging table and a QA
  pass. `pixijs` and `threejs` are untouched.
- **Phaser conformance in `develop`.** `phaser` and `phaser/*` are the engine's modules for a
  `phaserjs` game, importable only under `src/rendering/phaserjs/`; for any other game they
  are refused exactly as before. A `package.json` dependency on another template engine's
  library is now a finding too, not only a dependency on an engine the template does not
  carry — previously a dependency nothing imported yet went unnoticed.

### Changed

- **The pinned template is web-game-template 1.2.0.** It adds `@wgf/phaser-framework`, the
  third `createRenderer` branch, `pnpm build:engine <engine.type>`, and an engine-per-bundle
  build: `import.meta.env.WGF_ENGINE` is defined from `game.config.yaml`, so Rollup drops the
  engines a build does not use. A PixiJS build no longer carries the Three.js chunk, and
  carries no Phaser.
- `ENGINE_FOR_DIMENSION` is now the *default* engine per dimension, and `DIMENSION_FOR_ENGINE`
  is an explicit map (two engines are 2D, so it is no longer an inverse).

## [2.2.0] - 2026-09-28

Factory 2.2.0 (`docs/v2.2-release.md`): MV-3 of the post-production plan (PR #8) - a release
and verification that only claim what the build can ship - plus the root cause of the
long-standing process-liveness flake and a decidable template-contract versioning rule. A
minor version: it adds verification checks, a release refusal code, step metadata, a
liveness field and contract records, and breaks no consumer (the compatibility evidence is
in the release record). No schema, workflow, configuration or `CONTRACT_VERSION` change.

**Upgrading from 2.1.x:** nothing to configure. What you will see:
- A release draft holds only the package for the platform the build targets (game.config.yaml's
  first `required` platform, else its first); the other platforms are named as not packaged,
  and verification reports them `not-ready` (`platform.build-target:<id>`). They need
  per-platform builds (template contract 2).
- A game whose game.config.yaml has two `required` platforms now fails verification: one
  bundle cannot be both portals' build. The strategy module always writes one.
- The runtime facts' fps and time to interactive appear as `policy.device-performance`,
  evidence `PASS_MOCK`: a desktop proxy, not a device.

### Fixed

- **Release drafts shipped one bundle under every platform's name.** On the pinned
  template (contract 1.0.0) `pnpm build` makes one bundle, which boots one adapter, yet
  `release:package` zips it for every `platforms[]` entry: the 2.1.2 production run's
  `crazygames.zip` and `yandex.zip` were its Poki build, and would have loaded Poki's SDK on
  both portals. The release step now removes, between `release:package` and
  `release:manifest`, every archive for a platform the build does not target, and rewrites
  `packages.json` and `checksums.txt` in the template's formats; the step's message and
  metadata (`not_packaged`) name them; a foreign package that reaches the manifest anyway is
  refused (`package-not-built`).
- **Verification called those platforms ready.** Their profile assertions passed because the
  template's `platform_sdk` fact echoes the platform it is asked about. New check
  `platform.build-target:<id>`: PASS for the target, FAIL (with the reason) for every other
  platform - an optional one is `not-ready` without failing the verdict, a second required one
  fails it. The rule is `template_contract.build_target`, held against the pinned template by
  a drift test that will fail when per-platform builds arrive.
- **Proxy performance read as device evidence.** fps and time to interactive, measured in
  CPU-throttled desktop Chromium, sat inside `policy.runtime-facts`' PASS. They are now
  `policy.device-performance`, PASS with evidence `PASS_MOCK`, not required.
- **`wgf status` could call a healthy chatty child hung** - the root cause of the recurring
  `test_core_process.SilentChildInAStep.test_a_chatty_child_stays_running` failure. Captured
  under load on WSL2: the wall clock stepped 2.7 s forward in 0.1 s of monotonic time, and
  liveness judged output silence as `now - last_output_at`, which counts any clock step
  between the driver's stamp and the observer's `now` (NTP corrections, WSL resyncs, resumed
  laptops do this). Output-hung is now judged on `output_silence_seconds` =
  `last_heartbeat_at - last_output_at`: the silence the driver measured on its monotonic
  clock, in which a step cancels out. `output_idle_seconds` is still reported, never judged.
  The `on_hung: cancel` watchdog was never affected (it acts on the monotonic `idle_s`).
- **The template contract's versioning rule contradicted itself**, and 2.1.1's new
  `SOURCE_PATHS` entry (`src/game/boot-scene.ts`) was recorded nowhere. The rule now follows
  acceptance only (major: a repository accepted before can be refused; minor: an assumption is
  dropped; neither: an entry only recognized when present, or a rule the pinned contract
  already had). That entry is only recognized, so `CONTRACT_VERSION` stays 1.0.0 - by the
  rule, not by omission. `CONTRACT_LOG` records every change and `CONTRACT_DIGEST` (a sha256
  over the entries, never their descriptions) makes an unrecorded change fail the tests.

Regressions: `test_template_contract` (BuildTargetTest, the drift rule, the digest, the log,
descriptions are not entries), `test_verification.PlatformAndPolicy` (three),
`test_release_module.Drafting` (two, and the drafted-packages expectation),
`test_core_workflow.OutputLiveness` (the captured clock step, a real silence after a step,
output after the last heartbeat).

## [2.1.3] - 2026-09-28

A patch release (`docs/v2.1-release.md`, *2.1.3*): the first increment of the post-production
plan - G4 plumbing and G4 honesty - found by the 2.1.2 production run. No configuration,
schema or workflow change. **Upgrading:** nothing to configure. With lifecycle sync on, a
G4 `pass` over unmeasured kill criteria now logs the guard as UNKNOWN (it read GREEN); the run
proceeds on the person's decision as before.

### Fixed

- **The G4 `iterate` reason never reached the developer.** It was recorded (decision-record
  `rationale`, `DECISION_RECORDED`) but decision-record is not a develop input and the brief's
  "Why this is another iteration" read only visit budgets: the developer was told to "fix what
  sent it back" with nothing saying what that was, and the production run's next visit changed
  no game code. develop now quotes the newest decision of the route's source step when its
  choice is the route's (`brief.json` `loop.decision`), or says none was recorded.
- **"Development visits ... 1 of 9" was not the budget.** It was develop's `max_visits` loop
  guard, reset by every resume; 7 of 9 developer sessions were spent. The brief now states the
  developer budget - sessions used before this visit and left (`brief.json` `sessions`).
- **`kill_criteria_not_breached` read GREEN on a prototype nobody had played.** develop writes
  every strategy kill criterion as `measured: null, breached: false` until something measures
  it; the guard counted only `breached`. An unmeasured criterion now makes it UNKNOWN.
- **G4 showed only its choices.** `wgf status` and the output of `new-game`, `decide` and
  `resume` now print what the waiting checkpoint's inputs say - each kill criterion as
  breached / not breached / unmeasured with its value, a warning when any is unmeasured,
  playtest sessions by `player_context`, report verdicts and evidence status
  (`wgflib.gate_evidence`; `status --json` `pending.evidence`). It decides nothing.

Regressions: `test_develop_module` (five brief tests), `test_decisions.KillCriteriaGuard`,
`test_gate_evidence`, `test_workflow_cli.MockNewGame.test_g4_shows_the_evidence_it_is_decided_on`.

## [2.1.2] - 2026-09-28

A patch release (`docs/v2.1-release.md`, *2.1.2*): an ownership gap between the develop and
sdk steps, found by the live production validation of 2.1.1. No configuration, schema or
workflow change. **Upgrading:** nothing to configure; a game repository whose develop commits
changed one of the sdk step's files now blocks at sdk instead of losing that change - move
the work into the game's own files through develop.

### Fixed

- **The sdk step silently erased developer work in its own files.** It writes five files
  whole on every run - `src/platform/gameplay.ts`, `src/platform/game-integration.ts`,
  `src/platform/integration-plan.ts` and the two suites
  `tests/unit/platform/gameplay-integration.test.ts` and
  `tests/unit/platform/game-integration.test.ts` - but the brief named, and conformance
  checked, only the two seam files. In the 2.1.1 production run a developer fixing an
  sdk-review blocker added its regression test to the SDK-mock suite; the next sdk run
  rewrote the file, sdk-review blocked the deleted test, and the loop - invisible to the
  developer - used up the run's developer budget. Now `wgflib.gameseam.SDK_OWNED_PATHS` is the
  one list: the brief names the files (`sdk_owned`; own code and tests go in files of the
  game's own), develop's conformance refuses a change to any of them against the visit's
  baseline commit, and the sdk step BLOCKS rather than overwrite one whose last change is a
  commit its ledger does not record. A committed link at one of those paths therefore blocks
  the sdk step instead of being replaced (its target is still never written). Regressions:
  `test_develop_module.SdkOwnedFiles`, `test_sdk_integration.Commits`.

## [2.1.1] - 2026-09-28

A patch release (`docs/v2.1-release.md`, *2.1.1*): one false positive in the develop step,
found by the live production validation of 2.1.0. No configuration, schema or workflow
change; nothing to do to upgrade.

### Fixed

- **The develop conformance check refused a game-owned `BootScene`.** It refused any
  `src/main.ts` that contained the word `BootScene`, meaning to catch the template's scaffold
  scene still being started. The 2.1.0 production run's developer replaced that scene as the
  brief asks, with its own first scene - also named `BootScene`, in `src/scenes/boot-scene.ts`
  - and all three develop attempts were refused on the class name; the run failed at develop
  with a conformant build. The check now resolves each relative import in game source and
  refuses one that resolves to the template's scene module, `src/game/boot-scene.ts` (static,
  dynamic or re-exported; a re-export through another module was not caught before). The path
  is in the template contract's `SOURCE_PATHS`, so the pin is drift-tested for it. The rule
  is unchanged: a game does not start the template's `BootScene`. Regressions:
  `test_develop_module.Conformance` (a game-owned `BootScene` passes; the template's scene
  imported directly, without extension, dynamically or through another module is refused).

## [2.1.0] - 2026-09-27

Factory 2.1.0 (`docs/v2.1-release.md`): the fixes found by live-agent and production
validation of 2.0.0 (PR #4), against the unchanged template pin (v1.1.0, `bca41a9`). A minor
version: it adds the live build, two archetypes and two blocking design-consistency rules
(`design-consistency-rules.yaml` 1.2.0); no 2.0.0 default, schema or workflow definition
changed. **Upgrading from 2.0.0:** nothing to configure. A design made under 1.1.0 rules is
not re-evaluated; a run that redoes `design` meets the concept rules, and a strategy whose
concept no archetype carries now fails design rather than getting the nearest genre.

Found by the fresh live-agent validation of the v2.0.0 tag (`5b74e30`), which failed both
live tests with the documented argvs.

### Fixed

- **Live evidence is reproducible from the repository.** The 2.0.0 live runs used prompts
  kept only as `...` excerpts in `docs/claude-capabilities.md` (a custom developer prompt,
  and a reviewer `--append-system-prompt` that narrowed the review to one file); they could
  not be rerun. The live tests now read the developer and reviewer argvs from the commented
  examples in `workspace/config/factory.yaml`, verbatim (`golden.live.shipped_agent_examples`
  - the parser `ShippedConfig` checks them with), use the steps' own prompts, and record both
  argvs and the host's version in the run's evidence. `WGF_LIVE_DEVELOPER_ARGV` is no longer
  read; `WGF_LIVE_REVIEWER_ARGV` becomes an optional override.
- **A live run started without a run budget.** The post-2.0.0 production validation records
  every run under `develop.budget: {max_sessions: 6, max_cost: 120}`, but that was added to
  each configuration by hand: `live.py config` wrote none, so a run started from the
  repository alone had no run-level bound on paid developer sessions (only the host's
  per-session `--max-budget-usd`). `golden.live.build_live_config` now writes
  `LIVE_BUDGET` and records it in `live-agents.json`. Regression:
  `test_live_loop.LiveConfig.test_a_live_run_starts_under_the_documented_developer_budget`.
- **`WGF_LIVE_KEEP` with both live tests in one invocation** errored the second test: it
  copied its scratch over the first's, onto read-only git objects. Each test now keeps its
  evidence in `<dir>/<test id>` (`.2`, `.3` ... on a rerun), never over an earlier run's.
  Regression: `test_core_agents.LiveEvidence`.
- **`LiveReviewer` asserted what a competent reviewer must not do.** After the scripted fix it
  required no blocker on `src/game/score.ts`, but the fixture is a stub that does not implement
  the brief's design, and the reviewer - told to judge against the design - correctly keeps a
  blocker on it. It now asserts what the fixture can prove: the reviewer finds the planted
  bug, every verdict is trusted, the blocker reaches the developer's next brief, and the next
  review reads the fixing commit. The assertion was not weakened to pass: convergence moved to
  a scenario where it can legitimately happen (below).
- **`LiveDeveloperAndReviewer` removed**, for the same reason: on the stub, approval needed a
  review narrowed by a prompt the shipped reviewer does not have.

### Added

- **The live build** (`scripts/golden/live.py`, `test_live_loop`, AGENTS category, opt-in
  `WGF_LIVE_AGENT=1`, costs money): the golden 2D pipeline with the documented developer
  building the game from scratch from the Factory's brief and the documented reviewer judging
  it against the design, asserted to converge - completed, last development commit and sdk
  commit approved, every develop check green, only the developer's own files changed,
  isolation intact, no process left. `live.py config --human-gates` writes the same
  configuration for a run a person drives with `bin/wgf` and decides G2, G3 and G4.
  `GoldenRun.sandbox()` is the one seam it overrides (no refusing proxy: the hosts need their
  API).
- **"Which files are yours" in the development brief** (`wgf_develop.brief`): inside the
  writable paths, the template's own source (`TEMPLATE_SOURCE`: `src/core/`,
  `src/platform/bind.ts`, `src/rendering/create-renderer.ts`, `src/types/`) and the Factory's
  seam are not the developer's; a missing or broken one goes in `known_issues`, never into a
  patch, and review blockers are fixed only in the developer's own files. In the v2.0.0 live
  run a developer "fixed" a blocker about the seam's imports by writing `src/platform/bind.ts`
  and `src/core/config.ts`. Guidance only: conformance enforces what it did before.
  Regressions: `test_develop_module.FileOwnershipInTheBrief`, `TemplateSourceShipsInThePin`
  (every named path ships in the pinned template; every template file the seam imports is
  named).

### Fixed (found by the first clean production run and clean-machine gate after it)

- **G3 was answered blind to its own timebox predicate.** The tech plan reports an overrun
  only as a `STEP_LOG` warning ("plan exceeds the timebox; G3 decides"), which no console
  printed: the stopped 2026-09-26 run's G3 was approved over 18.0 estimated days against
  10.5 allowed. `wgf`'s console now prints warning- and error-level step logs with their
  facts. (The kernel still decides nothing with them: it may not import the lifecycle
  guards, and a checkpoint's inputs stay its gate's `required_artifacts`.)
- **A one-word strategy MVP item became a duplicate feature.** "Localization: en, ru"
  shares one significant word with the Localization feature and so never folded into it:
  two Localization features, two plan tasks. An item whose significant words a feature
  covers entirely is now folded. Regression: `test_design_module.StrategyMvpFolding`.
- **Clean-machine golden runs broke when the registry moved.** The 2D golden failed at
  develop from an empty HOME with `ERR_PNPM_NO_OFFLINE_META` for `earcut` after
  `pixi.js@8.21.0` was published: the warm-up's online install reused the template
  lockfile's `earcut@3.2.3` without fetching its metadata, and the replay's offline
  resolution needed it. `golden.harness.warm_store` now resolves online without the
  lockfile (metadata for the whole graph), then performs the replay's exact offline
  resolution once in a second copy, so a store that cannot serve it fails before the
  sandbox, naming the package.

### Changed (installation calibration)

- **`factory.techplan.estimates` is calibrated for this installation** in
  `workspace/config/factory.yaml`, by the portfolio owner's decision after G3 rejected a plan
  of 20.0 days against 10.5 allowed. The defaults put the drop-merge MVP at 87.5 h; the live
  build `new-game-20260927-044345-3c20a0` took 2.12 agent-hours for it (develop + review,
  from its event log). Rule fixed before the result: f = 4 x measured / heuristic = 0.097,
  rounded to 0.1, applied to every hour constant; `hours_per_day` unchanged. Any factor from
  about 1 to 40 would clear the allowance, so the outcome does not hinge on the choice.
  Workspace data, not core; the defaults in `wgf_techplan/devplan.py` are unchanged, and the
  golden and live configurations inherit the calibration. Derivation:
  [docs/handoff/2026-09-27-production-validation.md](docs/handoff/2026-09-27-production-validation.md).

### Fixed (found by the live builds on the corrected design)

- **The brief told the developer to break its own commit boundary.** It said "Run `pnpm
  format:write` before you finish"; that is `prettier --write .`, the pinned template is not
  prettier-clean (why the shipped checks leave `format` out), and a live developer's 61-minute
  build was refused for 20 reformatted template files. The brief now says to format only the
  files the developer created or changed. It also says scratch files go under `$TMPDIR`: a
  later live developer left `scratch-sim.mjs` in the repository root and was refused.
  And it names the two `src/main.ts` rules conformance enforces (no engine import, no
  template `BootScene`), which two independent live builds broke, a paid retry each.
- **sdk read the design's own placement id as the wrong moment.** A game calling
  `interstitial("interstitial-between")` - the design's touchpoint id, on leaving the result
  card - was classified by the id's words ("between" -> level-complete) and the required
  platform failed as `partial`. A design touchpoint id now takes that touchpoint's moment.
- **sdk planned two placements for one moment.** The design-derived entry
  (`rewarded-game-over`) stayed beside the game's own id at the same moment; the generated
  runtime resolves by kind and moment, so ad telemetry went out under the unused id (found by
  the live sdk-review). The game's own placement now supersedes it.

Validation record, runs and the two decisions left to a person:
[docs/handoff/2026-09-27-production-validation.md](docs/handoff/2026-09-27-production-validation.md).

### Fixed (design follows the strategy)

- **The design described a different game from the strategy it was built from, and passed
  its own checks.** Root cause: the design module chose its archetype by counting genre
  keywords over the whole strategy, and had one "merge" shape - a 7x7 swap-and-match level
  game - so the approved drop-merge strategy (drop numbered pieces onto a seven-column track;
  equal neighbours merge and cascade) got a swap design; the 3D strategy (steer between walls
  that rush toward the craft; a crash ends the run) likewise got a checkpoint time trial.
  Nothing compared the design with the strategy's concept. Fixed at three layers:
  - two archetypes for the games those concepts describe: `drop-merge` and `arena-dodge`
    (`wgf_design/archetypes.py`), with rules and numbers matching the pinned template's
    Tower Merge Rush and Neon Drift Arena;
  - selection reads each archetype's `signature` - the terms of its core mechanic - against
    the strategy's concept first, genre keywords second;
  - *Reason (core change, core/reference):* `design-consistency-rules.yaml` 1.2.0 adds two
    **blocking** rules, `concept_mechanics_carried` and `design_adds_no_foreign_mechanic`,
    over a `concept_terms` vocabulary: every core mechanic the strategy's concept names must
    be in the design's own text (core loop, the MVP mechanics it defines, the MVP controls -
    not text folded in from the strategy), and the design may add none the strategy does not
    name. A pinned archetype that is not the strategy's game is now refused. The old golden
    2D and 3D designs both fail them.
  The golden replay ports map the new MVP features, all `built`; the replay's known issue
  "the design is a swap-based level puzzle" is gone because it is no longer true.
  *Migration:* a design made under 1.1.0 rules is not re-evaluated (artifacts are
  immutable); a run that redoes `design` meets the new rules, and a strategy whose concept
  no archetype carries now fails design instead of getting the nearest genre.
  Regressions: `test_design_module.Choices` (one per golden concept, every archetype
  selected for its own game, a contradicting pin refused) and `ConceptFidelity`.

## [2.0.0] - 2026-09-26

Factory 2.0.0 (`docs/v2-release.md`): the release audit's fixes on top of everything since
1.1.0, validated with both golden runs against the unchanged template pin (v1.1.0,
`bca41a9`). A major version because defaults a 1.1.0 installation or script relied on
changed - each listed under **Breaking** with how to keep working. No schema's required
fields changed.

Since 1.1.0: the architectural audit that followed it - Wave 1 (P0 safety, template
contract, CLI, test honesty), Wave 2 and Wave 3 (M1-M13) - and the game production workflow:
the `core/craft/` playbooks, adapter binding 1.2.0 (Claude plugin 0.4.0) and the step-module
follow-ups F1-F7. Entries name their module (M*, F*); core changes are listed with their
reason, as docs/core-v1.md requires. What a 1.1.0 installation, script or run meets unchanged
is listed first, under **Breaking**, each with how to keep working; the entries below carry
the detail and the migration notes.

### Breaking

Every one fails closed and has a way back; none changes a schema's required fields.

| Change | Who notices | Keep working by |
|---|---|---|
| Developer and reviewer processes get an allowlisted environment, not the Factory's (M1) | A `command` developer or reviewer that authenticates from an environment variable (`ANTHROPIC_API_KEY`, ...) | Naming it in `factory.agents.env_passthrough` |
| Code run in the game repository gets the allowlist too (M1b) | A `pnpm install` / build that reads a registry token from the environment | `factory.agents.game_env_passthrough`, or the credential in `~/.npmrc` |
| The development commit holds only `writable_paths`; `package.json` may only gain dependencies; hidden paths and capitalised `*.md` are refused (M1). 1.1.0 committed `git add --all` | A developer that edits scripts, config or files outside `src/`, `tests/`, `public/`, `docs/development/`, `index.html` | `factory.develop.writable_paths`, `allowed_package_changes` |
| Release refuses a build no review approved (M7). The shipped `review.reviewer.kind: none` therefore refuses every release | Anyone releasing without a reviewer | Configuring a reviewer, or `factory.release.allow_unreviewed: true` (carried as UNREVIEWED) |
| `new-game` has G4 (`prototype-review`) and `sdk-review`; release requires G4 passed (M4, M7) | `wgf new-game --mock` now stops WAITING at G4 and exits 3; a run past sdk started under 1.1.0 is refused at release | `wgf decide <run-id> pass`; a custom workflow's release sets `required_gates: []` |
| `wgf status` exits as the run: 1 failed/blocked/cancelled, 3 waiting/paused (M11) | Scripts running `wgf status && ...` | Reading `wgf status --json` `status` instead of the exit code |
| Flag combinations that were silently ignored, and usage errors that exited 1, exit 2 (M11) | Scripts passing `--mock`/`--mock-plan`/`--hold-gates`/`--project` with `--resume`/`--run`, `--from` with `--run`, `--note` without `--decision`, `--decision` without `--resume` | Dropping the ignored flag |
| A relative `factory.storage.directory` resolves against the repository root, not the working directory (M11) | Runs made under 1.1.0 from another directory are not found | `--store <dir>` or an absolute `storage.directory` |
| Resuming a 1.1.0 run whose state claims `mock`, `mock_plan` or `auto_approve` is refused: its params were never recorded (M2) | Old mock or auto-approved runs | Starting a new run |
| A gated checkpoint waits until its gate's `required_artifacts` are in the run (M4) | Custom workflows | Listing those artifacts as the checkpoint's inputs |
| Release refusal code `commit-lineage-mismatch` is now `review-commit-mismatch`; reviewer evidence files are named `<step>-<visit>-<attempt>.*` (M7) | Scripts matching the code or hard-coded verdict paths | Matching the new names; `{verdict}` / `WGF_REVIEW_VERDICT` are unaffected |

### Upgrading from 1.1.0

1. Take the new `workspace/config/factory.yaml`, or merge it. Its top-level `checkouts: ..`
   now decides where game checkouts are; a legacy key you customised (`develop.checkouts`,
   `init.projects_dir`, ...) is still read, but set `checkouts` to that value.
2. Name the agent host's credential in `factory.agents.env_passthrough`, and any registry
   credential the game build reads from the environment in `game_env_passthrough`.
3. Configure a reviewer (`factory.review.reviewer`), or accept unreviewed releases with
   `factory.release.allow_unreviewed: true`.
4. Optionally bound developer spend with `factory.develop.budget`: develop may now be
   visited up to 9 times in a run (the loops are bounded per route, M13).
5. Finish or restart 1.1.0 runs: they resume under the new definition - `new-game` is now
   version 2, so the resume records `definition_version: 2` and says it continues under a
   newer definition - and one already past sdk must pass sdk-review and G4 before release.
6. Check scripts against the exit codes above (`wgf status`, exit 2 on refused flags,
   `new-game --mock` exiting 3 at G4).

### Added

#### Workflow engine and gates (M3, M4)
- **Timeout auto-approval (M4).** `factory.checkpoints.timeout_auto_approve: {G2: 48h}`
  lets a reversible gate approve itself once it has waited that long. *Reason (core
  change, wgflib/workflow):* gates.yaml's `auto_approve_after` was documented but never
  implemented. Conservative by construction: only listed gates; an irreversible or unknown
  gate listed refuses the run at start; the windows are snapshotted into the run's params
  (corroborated on resume, and a run started before has none); `waiting_since` is recorded
  per visit from the engine clock and corroborated by its `STEP_WAITING` event, and upstream
  work redone restarts it; the approval is recorded as `DECISION_RECORDED`
  (`decided_by: automation`, `mode: timeout`) and applied only by `wgf resume` - `wgf
  status` and `wgf runs --waiting` report eligibility and change nothing. *Migration:* none;
  the default is no window, as before.
- **A silent child reads `hung`, and can be stopped (M3, P0-13).** The step state keeps
  `last_output_at` (the child wrote something, or a lifecycle event) and
  `last_heartbeat_at` apart from `last_activity_at` (any event, heartbeats included), and
  `wgf status` reads `hung` with `hung_reason: output` when heartbeats show the driver alive
  but the child has written nothing for `factory.execution.hung_output_seconds` (default
  900: above the reviewer's 600 s and the developer's documented 900 s idle timeouts), or
  `hung_reason: driver` as before. The status text says which, and names `wgf cancel`.
  Opt-in watchdog `factory.execution.on_hung: cancel` (default `none`): the driving engine
  terminates such a child's tree through the cancel path, the step ends not retryably, and
  a `STEP_LOG` warning says why; the policy is snapshotted into the run's params and
  corroborated on resume. *Reason (core change, wgflib/procs + wgflib/workflow):* every
  heartbeat refreshed `last_activity_at`, so a live but stuck child always read `running`
  and nothing acted on `hung`. *Migration:* none; older `state.json` has neither new field
  and derives as before, and a run started with `on_hung: none` records no new params.
- **SIGKILL recovery (M3, P0-12).** Children of a step carry
  `WGF_PROC_RUN=<run-id>@<store digest>`; resuming - or cancelling - a run that is
  `RUNNING` with no live driver first terminates every process still naming that run
  (Linux `/proc`; elsewhere a warning that it cannot) and logs the pids. Nothing untagged,
  and nothing of another run or store, is touched. *Reason (core change, wgflib/procs +
  wgflib/workflow):* a SIGKILLed driver runs no cleanup, so its trees were orphaned and no
  later process knew their pids.

#### Contracts, template contract, CLI and test-core (M9-M12)
- `wgflib/template_contract.py` (CONTRACT_VERSION 1.0.0): every path, npm script, CLI and
  output the Factory assumes of a game repository, used by init, verification, sdk and
  release, with a drift test against the pinned template (M10, `docs/template-contract.md`).
- `wgf resume`, `wgf decide`, `wgf runs --waiting [--json]` (M11).
- `wgf test-core --strict` (exit 4 on a SKIP category; opt-in tests skipped inside a PASS category are listed, not failed); the summary never reads a bare OK when
  anything was skipped, and every skipped test is listed by reason (M12).
- `docs/env-vars.md`; `test_review_module.py`, `test_netguard.py`, `test_check_integrity.py`,
  `test_template_contract.py`.
- **`x-wgf.version` and one provenance builder (M9, P1-6).** Every top-level schema declares
  its contract version (semver) as `x-wgf.version`; check-integrity requires it.
  `scripts/wgflib/provenance.py` (`build`, `artifact_id`, `producer`, `pin`, `pin_inputs`,
  `seal`, `version_of`) replaces the provenance each step module and the mock steps
  assembled by hand; `schema_version` is read from the schema. `ArtifactContracts` refuses
  an artifact whose `provenance.schema_version` has another MAJOR than `x-wgf.version`.
  Versions, set to what the producing module already emitted: asset-manifest 1.1.0,
  game-design 1.1.0, qa-report 1.1.0, release-manifest 1.2.0, scaffold-record 1.1.0 (1.2.0 after M6),
  sdk-report 1.2.0, title-strategy 1.1.0, verification-report 1.1.0; decision-record,
  evaluation, opportunity, performance-review, platform-publication, prototype-report,
  research-report, review-report, state and tech-plan 1.0.0. *Core change, reason:* the
  version a producer claimed was a per-module constant nothing checked (sdk carried two,
  1.2.0 and 1.1.0). *Migration:* existing artifacts stay valid - only the major is compared,
  and every artifact written so far is major 1. Mock runs now write each schema's version
  instead of 1.0.0 for all, so new mock artifacts hash differently; real modules' output is
  unchanged apart from key order inside `provenance`, which the content hash ignores.
- **`x-wgf.run_path` (M9, P1-1).** Artifacts a workflow step produces name where an engine
  run stores them, `<storage>/workflows/<run-id>/artifacts/<id>/v<n>.json`, next to
  `repo_path`, their home in the methodology (workspace/ or the game repository), which the
  engine never writes (docs/artifact-contracts.md). *Migration:* none; `repo_path` keeps its
  meaning for adapters.

#### Game production workflow (craft layer, F4-F7)
- **The developer brief recommends the plugin's craft skills (F7).**
  - `brief.DEFAULT_SKILLS` names `web-game-factory:game-feel`, `core-loop`,
    `web-performance`, `audio` (area `craft`), `onboarding-ux` (`ui`), and the engine's
    `pixijs` / `threejs`, alongside the generic skills.
  - Configured areas are no longer silently dropped: every area except the other engine's
    reaches the brief. `[]` drops an area.
  - `develop.skills` is validated.

  *Migration:* none.

- **Opt-in developer self-playtest (F6).** The defaults are unchanged: developer `handoff`,
  `self_playtest: false`.
  - `developer.argv` gains a `{factory}` placeholder (the Factory root, substituted once).
  - New `workspace/config/mcp-playwright-localhost.json`: `@playwright/mcp@0.0.82`, headless,
    isolated, localhost origins only.
  - New `develop.self_playtest` setting, which adds a "Playtest your build" section to the
    brief.
  - A second commented developer block in `factory.yaml` (`--- opt-in: self-playtest`) adds
    `--mcp-config`, `--plugin-dir` and `Skill` / `mcp__playwright` to the verified argv,
    keeping `--strict-mcp-config` and every restriction.
  - `docs/claude-capabilities.md` records it as VERIFIED offline, UNVERIFIED live.

  *Migration:* none.

- **Shaped procedural audio (F5).** The procedural backend's sound effects were a bare sine
  tone. They now come from a deterministic jsfxr-style synthesiser (`encoders.synth`):
  waveform, envelope, pitch slide, vibrato and arpeggio. The preset (ui, coin, jump, hit,
  powerup, whoosh, lose, blip) is picked from the item's words and detuned by its id. Music
  is an 8 s bass-and-arpeggio loop (`encoders.music_loop`). The files remain placeholders,
  factory-generated and never production-ready, and each item's notes name its preset.
  *Migration:* none; `encoders.wav` is kept.

- **The `agent` design author (F4)**, `scripts/wgf_design/agent.py`. It is opt-in
  (`factory.design.author: agent`); the default stays `archetype`.
  - An agent host improves the archetype's draft from a request holding the strategy, the
    platform profiles and a starting draft.
  - The design module then applies exactly the checks it applies to any author:
    `finalize`, buildability, and the consistency rules including `descope`.
  - A malformed draft is refused before `finalize` (not retryable). A failing or silent
    host is retryable.
  - The design is attributed `actor: ai`.
  - The design step's brief now carries `config`, `run_dir`, `visit` and `attempt`.
  - `factory.yaml` has a commented read-only host example.

  *Migration:* none.

- **`core/craft/`: production craft playbooks.** What a *good* web game looks like inside
  the fields the artifacts already have: core loop and difficulty, game feel (a minimum
  feedback bar, distinct from polish), onboarding and portal UX, UI/HUD/mobile, audio, art
  direction, accessibility, web performance, playtesting (agent playthrough, stranger
  playtest and performance pass protocols), a gameplay-review checklist, competitive
  teardowns, and provider-neutral tool capability classes with their limits. Stage files
  `design`, `prototype`, `qa` and `tech-plan` point at them. `prototype.md` clarifies that
  the feedback bar is not the polish it warns against. *Migration:* none; no field, state
  or gate changed.
- **Adapter binding 1.2.0.** Eight new skills (`core-loop`, `game-feel`, `onboarding-ux`,
  `audio`, `art-direction`, `web-performance`, `gameplay-review`, `playtesting`). Existing
  skills and agent must-read lists are widened to the playbooks; `gameplay` and `ui` now
  read the game-design schema, and `asset` reads the asset policy. Skill entries list their
  `reads:`, which the integrity check verifies. Claude plugin 0.4.0; both adapters
  regenerated. *Migration:* none.
- `docs/production-craft-and-mcp.md`: skills and MCP tools by phase, what belongs in host
  configuration versus the repository, and Factory-module follow-ups found in the audit
  (F1-F7, since implemented: see the entries in this section and under Changed).

### Changed

#### Definition versions
- `new-game.workflow.yaml` is `version: 2` and `gates.yaml` `1.1.0`: the workflow gained
  sdk-review, G4 and per-route loop limits, and G3/G4 changed their required artifacts. A run
  keeps the version it started under; resuming a version-1 run records `definition_version`
  in `WORKFLOW_RESUMED`. *Migration:* none; `wgf status` shows `new-game (v2)`.

#### Gate semantics (M4)
- **G4 `prototype-review` is a real checkpoint** in `new-game`, after `verify` passes and
  before `release`, decided on the verified `qa-report`, `verification-report` and
  `prototype-report` against the kill criteria and design (`title-strategy`, `game-design`),
  with `pass` / `iterate` / `kill`. gates.yaml G4 `required_artifacts`, the title machine's
  prototype-review inputs, the stage procedure and every schema's `required_for_gates` agree
  on those five, and check-integrity now fails when a schema's `required_for_gates`
  disagrees with gates.yaml. *Reason (core change,
  core/workflows + wgflib/workflow):* the workflow went from verify straight to release, so
  the one gate the factory exists for - the kill gate - was never asked. `iterate` returns
  to develop (a success routed back; lineage kept) and G4 asks again; `kill` ends the run
  (BLOCKED routed to `$end`: `DECISION_RECORDED`, `exit.route: kill`, `wgf status` "Ended:
  kill at G4", exit 0) and the run cannot be continued. Only a person decides it.
  *Migration:* `wgf new-game --mock` now stops `WAITING` at G4 - answer it with
  `wgf decide <run-id> pass`; scripts that expected it to complete unattended must decide
  G4. A run started before this change resumes under the current definition; one whose
  cursor is already past verify (at release) is not sent back to G4 by a plain resume, but
  `--run release` in it is refused until G4 is passed.
- **A gate is passed only by a forward answer.** The engine refuses a later step past a
  gate whose last answer routed backwards (`iterate`, `rework`) or ended the run, not only
  past one never answered; `--run` in skip mode asks such a gate again. *Reason:* `iterate`
  is a SUCCESS and would otherwise have counted as passing G4. `context.gates_passed` lists
  the gates a run has passed (for steps that want to check). *Migration:* none for a run that
  answers its gates forward; a custom step that relied on passing a gate answered backwards
  now waits for it again.
- **A checkpoint is decided on its gate's `required_artifacts`** (gates.yaml): without them
  in the run, as the step's inputs, it waits for input and asks nobody. G2 and G3 now list
  them as inputs. gates.yaml: G3 no longer requires `asset-manifest` (assets are sourced
  after G3), G4 requires the verified evidence. Each schema's `x-wgf.required_for_gates`
  now agrees with gates.yaml, which check-integrity enforces: `research-report` no longer
  claims G1 (G1 is decided on `opportunity` and `evaluation`), `asset-manifest` no longer
  claims G3, and `qa-report` / `verification-report` gain G4. *Migration:* a custom workflow
  whose gated checkpoint does not list its gate's required artifacts as inputs now waits for
  input.
- **Reject and kill stop the run**; a run a decision ended at `$end` exits 0 and shows
  `Ended:` in `wgf status` (`ended_by` in `--json`), and `--run` refuses to continue it.
  *Migration:* scripts that treated a rejected run as failed read `ended_by` instead.
- **`design.on.descope: $fail`**, explicit: a blocking design-consistency breach ends the
  run with the design's own message (it already did, unrouted).

#### The shipped commit is reviewed, and release refuses what was not (M7)
- **`sdk-review`: the sdk commit is reviewed too** (P0-8). `new-game` gains a step after
  `sdk`, before `verify`: `type: review`, `stage: title:prototype`, `with: subject:
  sdk-report`, inputs `sdk-report`, `prototype-report`, `game-design`, `scaffold-record`.
  The review step reads a generic `with: subject` (`prototype-report`, the default, or
  `sdk-report`): the reviewed commit is that artifact's `build_ref.commit_sha`, which must
  be HEAD; for the sdk subject the brief's change is prototype commit..sdk commit. Its
  `request-changes` routes to `develop` - the developer fixes the game side, sdk integrates
  again, both reviews run again, `max_visits` bounds it; a requested change never reaches
  verify. Verdict files are now `<run>/review/<step>-<visit>-<attempt>.*`, so the two
  reviews never overwrite each other. `sdk-report`'s x-wgf consumers gain
  `title:prototype`. *Reason (core change, core/workflows + core/artifacts):* `review` read
  develop's commit, then sdk committed integration code on top of it, and that unreviewed
  sdk commit is what verify checked and release shipped.
- **Release refuses an unreviewed or mis-reviewed build** (P0-9). The newest review-report
  must approve exactly the commit being released (the sdk commit, HEAD), from a reviewer
  that ran (`reviewer.kind: command`), pinning the run's newest prototype-report and
  sdk-report. `skipped`/absent is `unreviewed` (FAILED, not retryable); an approval of
  another commit - develop's alone included - or of an older report is
  `review-commit-mismatch` (was `commit-lineage-mismatch`). New
  `factory.release.allow_unreviewed` (default `false`, read only from config, never a
  step's `with:`) drafts a skipped/absent review anyway, recorded as UNREVIEWED; it waives
  nothing else. *Reason:* release recorded "UNREVIEWED" and shipped, and with the shipped
  `review.reviewer.kind: none` every release was unreviewed.
- **Release checks G4 itself** (M4 follow-up). `evidence_refusals` takes the engine's
  `context.gates_passed` (a required keyword: no default) and refuses `g4-not-passed`
  (BLOCKED) unless every gate in the release step's `with: required_gates` (default `[G4]`,
  read only from the workflow, never from config) is passed and current. The step cannot
  see its workflow definition and no engine change was in scope, so the workflow declares
  what its release requires and the default fails closed; `test_workflow_definition` checks
  every shipped workflow's release requires each irreversible gate it checkpoints.
- `--mock`: the review mock approves the commit its subject names (`reviewer.kind: none`,
  so no real release could accept it); the review-report fixture is `approve`.
- *Migration:* **with the shipped `review.reviewer.kind: none`, every real release is now
  refused (`unreviewed`)** - configure `factory.review.reviewer` (see the commented Claude
  Code block in factory.yaml), or set `factory.release.allow_unreviewed: true` knowingly. A
  custom workflow with a `release` step and no G4 checkpoint must add `with:
  required_gates: []`; one that lists `review-report` as a release input should add a
  review of the commit it ships. A run in flight past `sdk` when this lands has no
  sdk-review: resume it `--from develop` (or `--from sdk-review` in a run whose sdk commit
  is HEAD) to get the approval release now requires. Existing drafts are unaffected.

#### Gates emit decision-records (M5)
- **Workflow gates emit decision-records (P1-1, P0-11).** The G2, G3 and G4 checkpoints emit
  a schema-valid `decision-record` on every decided outcome - a person's choice,
  auto-approval, timeout approval, reject and kill - whose subject and provenance pin exactly
  the evidence consumed. One table in `wgflib/workflow/decisions.py` maps workflow choices to
  the schema (`kill` -> `abandon`). check-integrity requires every step naming a gate to
  output a decision-record, and only such steps may. *Reason (core change):* CLAUDE.md said
  every gate emits one; workflow gates did not. *Migration:* runs gain one
  `decision-record-<step>` artifact per decided gate visit.
- **Lifecycle bridge.** `factory.lifecycle.sync` (default off, snapshotted per run) appends a
  run's decision-records to `workspace/titles/<id>/decisions/` and advances the title cursor
  through `wgf-state.py`'s own guards and gate rules; a refused move is a warning, never the
  run's outcome. Never for a `--mock` run.
- **Guards read run evidence.** `ci_green`, `verify_suite_green` and `playable_build` can
  answer from a run's qa-report and verification-report (`wgflib/guards.py` `RunEvidence`);
  `PASS_MOCK` never counts as a pass for `verify_suite_green` / `playable_build`.
- `test_decisions` joins the WORKFLOW category of the Core Acceptance Suite.

#### One checkout resolver (M6)
- **One checkout resolver (P0-14, P1-2, P1-3).** `wgflib/checkout.py`: every step that
  touches the game repository finds it by `with: repo_dir|game_repo` -> `WGF_GAME_REPO` ->
  scaffold-record `repository.local_path` -> `factory.checkouts` + name, relative paths
  resolved against the Factory root (docs/checkouts.md). *Migration:* `factory.checkouts`
  replaces `develop.checkouts`, `init.projects_dir`, `review.checkouts`, `sdk.games_dir`,
  `verification.checkouts` and `release.checkouts` (deprecated aliases, warned when they
  disagree), and the sdk step's `sdk.game_repo` (a checkout, honoured for sdk only, with a
  warning); `WGF_GAME_REPO` now applies to every step that reaches the game repository -
  init, assets, develop and review as well as sdk and verify. Unset it where only one step
  should see it.
- A per-checkout advisory lock (pid + start time) blocks a second live run from working in
  the same tree while a step runs (`checkout-in-use`).
- scaffold-record 1.2.0 adds an optional `repository.local_path`, written by init.
- Assets default into `<checkout>/public/assets/`, which develop commits; the develop brief
  lists every asset's repository-relative file paths. *Migration:* set `assets.root` to keep
  them elsewhere.
- Vendored platform profiles are verified by content hash in init, verify
  (`platform.profile:<id>`) and sdk (`wgf_init.profiles.verify_pins` / `pin_identity`).
- `wgf_develop` reads its template literals from `wgflib/template_contract.py`.

#### Loop and session budgets (M13)
- **Loops into one step are bounded per route (P1-7).** A workflow step may declare
  `max_visits_by_route: {<route>: n}`; entries through that route (the label or outcome
  that routed into the step) are counted in the step's new `route_visits` and bounded apart
  from each other, while `max_visits` still holds. A key is a route from any step or
  `<source>.<route>` from one step; entries are counted per `<source>.<route>`. new-game's
  develop takes `review.request-changes: 2`, `sdk-review.request-changes: 2`, `fail: 2`
  (verify) and `iterate: 2` (G4) over the run, with `max_visits: 9` on develop and on every
  later step of the loop. Route budgets last the run: resuming a run a route limit stopped
  refills that limit only; `--from` and `--run` (an explicit fresh start of a slice)
  refill all of them (M13 review: the two reviewers had
  shared one `request-changes` count, and every resume refilled every route, so G4's
  `iterate` - always decided by a resume - was never bounded).
  *Reason (core change, core/workflows + wgflib/workflow):* the four loops back into develop
  shared develop's one `max_visits` of 3, so a review loop could spend the passes a failing
  verification needed, and nothing said which loop had. The definition refuses a key that
  is no route into its step; the engine names no route.
- **Why a run stopped at a loop limit is data.** `state.blocked_reason = {kind: loop-limit,
  step, route, scope: step|route, limit, entered, from}` (also `WORKFLOW_BLOCKED`
  `data.blocked`), and resume's "one more pass" is decided from it instead of the message
  prefix (P1-8). *Reason (core change, wgflib/workflow):* string coupling. Integrity checks
  its shape and the route counters like `loop_base`.
- **A run-level budget for developer sessions that resume does not reset.**
  `factory.develop.budget: {max_sessions, max_cost, cost_from: {jsonl_key}}`, snapshotted
  into run params (`develop_budget`, corroborated like every param). The develop step counts
  command-developer sessions and their reported cost from the run's event log (STEP_LOG
  `data.budget`) and returns `BLOCKED` - no agent spawned - with `budget exhausted: N
  developer sessions used of N`, or on the cost limit. A session with no readable cost is
  counted and reported as unknown; the host's per-session flag stays that session's bound.
  *Reason (core change, wgflib/budget.py, wgflib/workflow/{config,api,integrity}.py):* every
  resume refilled the loop budget, so with a command developer nothing capped a run's
  sessions or spend.
- **Raising a budget is a person's act:** `wgf resume <run> --budget-sessions N |
  --budget-cost X` records a `BUDGET_RAISED` operator event (new generic
  `engine.resume(operator_events=...)`: refused for `decided_by: automation` and for the
  engine's own event names). Refused from inside a step's process tree. A raise counts only
  when the engine's `WORKFLOW_RESUMED` corroborates it by `resume_nonce`, and whatever
  another process writes to the run's event log during a step is taken out again (Security:
  the event log is sealed while a drive holds the run). Before the M13 review, any appended
  `BUDGET_RAISED` line naming a person was honoured. `develop_budget` is a guarded param.
- A step's context gains `entered_by` (`<source>.<route>` of this visit, e.g. `verify.fail`), `visit_budget` (what the
  visit leaves of its limits) and `read_events()` (the run's recorded events);
  `STEP_STARTED` carries `entered_by`. The develop brief says which loop brought the work
  back and how many passes it has left (`brief.json` `loop`); a first visit (`<step>.success`)
  has none.
- *Migration:* none required. A run started before this change has no `route_visits`,
  `blocked_reason` or `develop_budget` and resumes as before (a loop-limit stop recorded only
  in its message still gets its one more pass); it has no budget, since none was
  snapshotted. `factory.develop.budget` applies to runs started after it is set.
  `max_visits_by_route` counts only from this version: an old run's earlier loops are not
  charged to any route. `wgf new-game --mock --mock-plan '{"verify": [fail x4]}'` now
  blocks on develop's `fail` route (as before, after the third failed verification); a
  review that always requests changes still blocks on its third request, and a third G4
  `iterate` now stops for a person. develop may be visited up to 9 times instead of 3 when
  the loops mix - set `factory.develop.budget` to bound what a command developer may spend
  in the run.

#### CLI and test-core (M11, M12)
- `wgf status` exits with the run's code (1 failed/blocked/cancelled, 3 waiting/paused).
  Flags a command would silently ignore are refused (exit 2), and so are the usage errors
  1.1.0 reported with exit 1 (`--decision` without `--resume`, `--resume` with `--run`,
  `--force` without `--run`). An environment failure (a full disk, a read-only store) exits 1
  with one line, no traceback. pause/cancel import no step module. A relative
  `factory.storage.directory` resolves against the repository root, not the directory `wgf`
  is run from (M11). *Migration:* see Breaking; runs made from another directory are reached
  with `--store`.
- `wgf sdk-review` and `wgf prototype-review` run those steps on their own, like every step
  of the workflow (the commands are the workflow's step ids).
- Test opt-in flags mean exactly `=1`; `WGF_TEMPLATE_REPO` (a pin bypass) is removed, the
  real SDK suite runs on the pinned checkout with `WGF_TEMPLATE_SDK_TEST=1` (M12).

#### Game production workflow (F1-F3)
- **`docs/GDD.md` is rendered into the game repository (F3).** `game-design` declared
  `rendered_to: <game-repo>/docs/GDD.md`; nothing produced it. The develop step now writes
  it (`scripts/wgf_develop/gdd.py`) in `core/templates/gdd.md`'s section structure, pinned to
  the design's artifact id and content hash. It is written before the developer runs and again
  after, so a hand edit never survives, and it is committed with each visit. The development
  and review briefs point at it. The golden reviewer allows `docs/GDD.md`. The scaffolding
  procedure and the GDD template now say who renders it. M1's commit scope accepts exactly
  `docs/GDD.md` (`scope.FACTORY_RENDERED`, fixed): the step re-renders it after the developer,
  so the committed file is always the Factory's; any other capitalised `*.md` stays refused.
  *Migration:* none. `docs/tech-plan.md` is still not rendered; the tech plan reaches the
  developer through the brief (F1), and `core/templates/tech-plan.md` now says so.

- **The review brief adds a gameplay lens and a design-fidelity section (F2).** "Look for"
  was code-only. It now also covers what players feel: restart state, frame-rate
  independence, pause, double starts and taps, tuning as data, frame-loop allocation, flash
  rate, audio unlock, and tests that reach their aspect. The lens is condensed from
  `core/craft/gameplay-review.md`. When the committed development brief carries F1's
  `build_spec` / `dev_plan`, the brief lists the MVP feedback, the tutorial approach and each
  task's acceptance criteria to check against. *Migration:* none; the verdict contract is
  unchanged.
- **Golden reviewer: every blocker carries `file`** (null for a whole-build finding).
  `scripts/golden/reviewer.py` omitted the key. `wgf_review.verdict.parse` rightly
  discards such a verdict as malformed, which failed a golden run after a verify → develop
  loop.

- **The develop brief carries the design's `build_spec` and the approved plan's tasks (F1)**
  (core change: `core/workflows/new-game.workflow.yaml`). The design authored mechanics
  with rules and tuning, the difficulty curve, reward and failure feedback, tutorial steps
  and audio cues, and the tech plan authored tasks with acceptance criteria. None of it
  reached the developer, whose brief held only the design's summary strings. `develop` now
  takes `tech-plan` as an optional input. `brief.md` gains a "Build spec (MVP tier)" and a
  "Development plan" section, and `brief.json` gains `build_spec` and `dev_plan`.
  `sdk_touchpoints` stay with the sdk step and `assets` with the asset manifest. The
  prototype-report now pins the tech plan it was briefed from. *Migration:* none; a run
  without a tech plan, or a design without `build_spec`, briefs exactly as before. A run
  resumed at develop under this definition consumes its existing tech plan.

### Security
- **Developer boundary (M1).** develop's git runs hardened like the reviewer's
  (`wgflib/gitsafe`: pinned git dir and work tree, safe env, filter drivers neutralised
  unless `factory.develop.git.allow_filters`, signing programs off). `package.json`,
  `tsconfig.json` and `pnpm-lock.yaml` are protected: only dependency additions allowed by
  `factory.develop.allowed_package_changes` pass conformance, so a developer can no longer
  rewrite the `test`/`lint`/`test:e2e` scripts every later check runs. The Factory's guarded
  paths are fingerprinted and restored around the developer. The commit is scoped to
  `factory.develop.writable_paths`; hidden paths (`.claude/`, `.github/`, ...) and agent
  instruction files are refused. Developer and reviewer processes get a scrubbed
  environment (`wgflib/agentenv.py`; add names with `factory.agents.env_passthrough`).
  Reviewer isolation moved to `wgflib/isolation.py`. *Migration:* a live agent host that
  authenticates through an environment variable needs it in `env_passthrough`; a developer
  that edited package.json scripts or wrote outside the writable paths now fails develop.
- **Game code gets no Factory secrets (M1b).** The code the Factory runs inside a game
  repository - the develop checks, verify's commands, the sdk conformance suite and release
  packaging, all written or editable by the developer agent - ran with the Factory's whole
  environment. It now gets `wgflib/agentenv.game_code_env`: the agents' allowlist (plus
  `PLAYWRIGHT_*` and `COREPACK_*`, toolchain configuration) and the names in the new
  `factory.agents.game_env_passthrough` (default `[]`) - never the agents'
  `env_passthrough`. Core change (`wgflib/agentenv.py`): the allowlist is shared kernel
  code, and one definition keeps the agents' and game code's rules from drifting.
  *Migration:* an installation whose `pnpm install` (or build) reads a registry or other
  credential from an environment variable must name it in `game_env_passthrough`;
  credentials in `~/.npmrc` under HOME keep working.
- **Run params are corroborated (M2).** `WORKFLOW_STARTED` records the run's params and
  resume refuses a state.json whose params differ. *Migration:* a run started before this
  change whose state claims `mock`, `mock_plan` or `auto_approve` is refused on resume;
  start a new run.
- **`--from` cannot step over a gate (M2).** A fresh run started with an explicit `--from`
  past a gate in its scope is refused (`wgf new-game --from design` skipped G2). Fresh
  single-step runs (`wgf verify`) are unaffected.
- **The event log is sealed while a drive holds the run (M13 review, release audit).**
  Decisions and budget raises are corroborated from `events.jsonl`, and while a drive holds
  a run the engine is its only writer. After every step the engine compares the log with
  exactly what it wrote: anything another process appended, edited or truncated - a forged
  `BUDGET_RAISED` with the `WORKFLOW_RESUMED` that would corroborate it, a negative cost
  line, forgotten sessions - is put back (`EVENT_LOG_RESTORED`) and the step fails, not
  retried. That covers every step that runs a developer's or an agent's code, including the
  develop checks that run its tests, which an earlier session-only audit did not. A raise
  also needs its engine-written `resume_nonce`, and a cost that is not a non-negative finite
  number lowers nothing. *Core change (wgflib/workflow/{store,engine,events}.py), reason:*
  the only legitimate writer of a driven run's log is the engine, so anything else there
  can only be a forgery, from whichever step ran it. *Residual:* no hash chain or secret; a
  process that edits the run directory while no driver holds the run (one that escaped its
  step's process tree) is outside this.
- **The Factory never writes its files through links in the checkout (release audit).** The
  develop step's brief, `docs/GDD.md`, integration seam and `checks.json`, and the sdk
  step's integration files, were written with a plain open(): a symbolic or hard link the
  developer left in their place had the Factory write its text to a Factory file or the
  run's event log, where no guard comparison followed. They now go through
  `wgf_develop/safewrite.py` - no linked directory, and the file's directory entry replaced
  (temp file + rename), never written through - and the commit scope refuses a
  `docs/GDD.md` that is not a plain file. An unsafe directory fails the step, not retried,
  having written nothing. *Migration:* none.
- **The design agent host gets the allowlisted environment (F4).** Like the developer and
  the reviewer: `wgflib.agentenv.scrubbed` plus `factory.agents.env_passthrough`, never the
  Factory's own environment.
- **The self-playtest opt-in stays inside the boundary (F6 with M1).** The installation
  guards `claude-web-game-plugin` (`factory.review.guarded_paths`), whose skills that
  developer loads; the Playwright MCP writes its snapshots to `/tmp`, outside the checkout.

### Fixed
- **Pre-publish checks (release record: docs/v2-release.md).** A live reviewer's whole-build
  finding no longer fails the run. The verdict contract's example shows a finding with
  `file: null` and no `line`, and `line: null` reads as no line; a missing `file` stays
  malformed. The golden runs warm the pnpm store themselves, online, before their offline
  sandbox, so they pass on a clean machine: from an empty HOME they failed at develop with
  `ERR_PNPM_NO_OFFLINE_META`. The live developer-and-reviewer test expects sdk-review of the
  shipped commit (M7). *Migration:* none.
- Run lock identity is pid + process start time, so a recycled pid no longer holds a dead
  run; an empty lock tolerates mtime skew (M2).
- Atomic writes use unique temp names; concurrent `LATEST` writes no longer race (M2).
- A cancel is honoured while a step waits out its retry backoff; a crash between entering a
  step and moving the cursor no longer burns a visit (M2).
- Platform profiles are identified by id, version and content hash; init re-vendors a
  same-version profile with other content, and `wgf_init.profiles.verify_pins` checks it.
  check-integrity reads platform ids from the pinned template, never the sibling, and warns
  on template profiles that diverge under the same version (M8).
- **x-wgf agrees with the workflow (M9, P1-1).** check-integrity now fails when a workflow
  step outputs an artifact whose `x-wgf.producer` is not the step's `stage`, or takes an
  input whose `x-wgf.consumers` omit it. The 11 disagreements it found are fixed in
  `core/artifacts/`: `asset-manifest`'s producer is `title:prototype` (the `assets` step;
  `title:design` joins `updated_by`); consumers gained `title:scaffolding` (game-design),
  `title:prototype` (qa-report, prototype-report), `release:qa` (prototype-report,
  scaffold-record) and `release:draft` (qa-report, verification-report, sdk-report,
  prototype-report), plus `title:prototype-review` on qa-report and verification-report for
  the G4 checkpoint. *Core change, reason:* two statements of who produces and consumes an
  artifact had drifted with nothing comparing them. *Migration:* none for artifacts; a
  workflow that uses an artifact at a stage its schema does not name now fails the check.
- **One validator for the release manifest (M9, P1-6).** `scripts/wgf_release/schema.py`, a
  second, subset JSON Schema validator, is deleted; release validates the manifest it drafts
  and the game repository's `manifest.json` with `ArtifactContracts` (full schema through
  `jsonschema_lite`, provenance type, contract major, hash). A game manifest that only
  passed the subset (wrong `artifact_type`, an impossible date) is now refused as
  `invalid-manifest`. *Migration:* none for the template's make-manifest.mjs.
- **Recorded gameplay sessions are validated against their schema (M9, P1-6).**
  `wgf_verification/checks/gameplay.py` validates `build/verification/gameplay-session.json`
  with `jsonschema_lite` against `shared/gameplay-session.schema.json` (formats, unknown
  keys, browser entries) instead of a hand-written subset, and keeps the one rule the schema
  cannot state (the aspect is one the template contract knows). *Migration:* a session with
  keys the schema does not define is no longer used; verification falls back to the
  repository's Playwright suites, as for any unusable session.

## [1.1.0] - 2026-09-25

Factory v1, usable (`docs/v1-usable.md`). Core v1 against the latest **released**
web-game-template, v1.1.0 (`bca41a97665f8a32d0f803d46a7bbd001ac94d41`), running one complete
real workflow - research to a drafted release - with a real Claude developer and a real
read-only Claude reviewer. Core v1's architecture is unchanged; contract changes are additive.
Live portal behaviour, submission and publishing remain BLOCKED_EXTERNAL.

### Added

- **Platform profiles for Y8, GameDistribution and GameMonetize**
  (`core/reference/platforms/`). The shared profile schema gains `requirements.game_id`
  (`required | optional | none`), `game_id_pattern` and `hosting`. *Migration:* none; the
  fields are optional.
- **Portal registrations** - `workspace/titles/<title>/portals.yaml` - carried by the tech
  plan into `game_config.platforms[].game_id` (and `hosting` / `game_url`); a required Game
  ID that is missing blocks the tech plan. tech-plan schema: `game_id`, `hosting`,
  `game_url` on platform entries. *Migration:* none.
- **The integration seam module.** The develop step provides `src/game/integration.ts` and
  `src/platform/integration.ts` (`createGamePlatform`, `createGameIntegration`) before a
  game is built; the sdk step writes its integrated wiring over the latter as a whole file.
  *Migration:* a game built before 1.1.0 does not boot through the seam, and the sdk step
  now refuses it; rebuild it through develop.
- **`wgflib.netguard`** (moved from the golden harness): the develop smoke check and
  verify's browser commands run behind a refusing proxy, so no test contacts a portal.
- scaffold-record `template.generated_from_sha` and `template.pin_commit`.

### Changed

- **Pinned to web-game-template v1.1.0**, a release, instead of the development commit
  `22482b4`. The golden runs read their ports from a separately pinned fixture commit.
- The tech plan's `repo_params.template_ref` is always `<repository>@<pinned sha>`; init
  refuses a plan approved against another revision and brings a repository GitHub generated
  from another revision to the pin with one local commit. *Migration:* a tech plan naming
  `<template>@main` must be re-planned.
- init writes `game.id`/`game.name` itself for either source (bootstrap's own derivation).
- The sdk step never edits `src/main.ts`; it reads seam calls with the game's TypeScript
  compiler, resolves named placement ids and reports unresolvable ones.
- The develop brief states verification's evidence contract (aspect tags and the aspects
  this build must prove); a retry after a failed developer is told to continue its work.
- Shipped Claude developer example: `--max-turns 400`, `--max-budget-usd 40`.

### Fixed

- Reviewer isolation no longer reports pnpm-store hard links as reviewer writes.
- A reviewer's fenced verdict after quoted code is found.
- See `docs/v1-usable.md`, "What the real runs found and fixed".

## [1.0.0] - 2026-09-24

Core v1, frozen (`docs/core-v1.md`). The executable workflow core - engine, persistence,
contracts, process ownership, agent runtime, verify and release - protected by the Core
Acceptance Suite (`bin/wgf test-core`) and two real golden pipelines, Tower Merge Rush
(PixiJS) and Neon Drift Arena (Three.js). Validated against web-game-template
`22482b4eb81084a89ff8ecdeea9130f06ebb8026` (`workspace/config/template.lock.json`).
Everything below was added on the way there. Portal QA, publishing and real ad fill remain
BLOCKED_EXTERNAL.

### Added

- **Core v1 hardening (security pass).** `scaffold-record.repository.name` refuses `.` and
  `..` (schema pattern; consumers also resolve checkouts through
  `wgflib.paths.checkout_path`). `wgflib.procs.install_subreaper()` — installed by the `wgf`
  CLI — reparents orphans to the Factory, so a descendant that detaches and clears its
  environment is still ended with its step. *Migration:* a scaffold-record naming `.` or
  `..` was never usable; none exist.

- **Review module (`scripts/wgf_review`, step type `review`) and the `review-report`
  artifact.** An independent reviewer reads every development commit and approves it or
  requests changes with named blockers. The loop is data: `new-game` now runs
  `develop → review → sdk`, with `review` `on: {request-changes: develop}`, and
  `max_visits` bounds it. Request-changes is `FAILED` with a route and not retryable, so
  a workflow that forgot to route it fails closed. The reviewer is read-only and that is
  enforced: HEAD, refs, index, every tracked and untracked file, package/lock/test/config
  paths, `.git/config`/hooks and the Factory's `core/workflows` + `workspace/config` are
  fingerprinted before and after. Any change fails the review
  (`reviewer-isolation-violation`) and is undone. Verdicts are validated strictly
  (`malformed-verdict`). Timeouts and crashes are retryable and end the whole process tree
  through `wgflib.procs`. `kind: none` records `skipped`, never an approval. `develop`
  now takes `review-report` as an input: a request for changes to the commit it starts
  from puts the blockers first in the next brief (`review_blockers`). It also gains an
  optional `developer.idle_timeout_seconds`. Proved by
  `scripts/tests/test_core_agents.py`, the AGENTS category of the Core Acceptance Suite,
  with real subprocesses, real git and the real engine. See `docs/review-module.md`.
  *Existing artifacts:* none change. Existing runs of `new-game` resume into a workflow
  that has one more step. Installations must add `wgf_review` to `factory.steps.modules`
  (done in the shipped config) or run it with `--mock`.

- **Full schema validation inside the engine (`scripts/wgflib/jsonschema_lite.py`).** A
  standard-library JSON Schema draft 2020-12 validator covering every keyword
  `core/artifacts/**` uses (enumerated by the tests), with `$ref` across the shared schemas,
  asserted formats, ECMA-faithful patterns and JSON-pointer errors in a fixed order. It raises
  on any keyword it does not implement instead of ignoring it. `ArtifactContracts` now
  validates the whole schema, not only top-level keys, rejects content JSON cannot represent
  (NaN, non-string keys, Python-only values), and caps diagnostics at 20 while always keeping
  the provenance type and hash problems. New `check_lineage(content, consumed)` checks that
  `provenance.inputs` pins exactly the input versions a step consumed; the engine does not
  call it yet. Deliberately stricter than ajv-formats@2 in one place: a `date-time` must
  carry an RFC 3339 offset. **Bringing an artifact forward:** nothing to do if it already
  passed ajv; every workspace instance, reference file and module output under the test
  suite validates unchanged. See `docs/core-contracts.md`, which also audits every pipeline
  boundary. No schema changed.

- **Tech-plan module (`scripts/wgf_techplan`, step type `tech-plan`) and the G3 checkpoint.**
  `new-game` now runs design → `tech-plan` → `tech-plan-review` (G3, reversible, same shape
  as `strategy-review`) → init, as the title machine always said. The module is minimal and
  deterministic: the engine is the one the design declares (dimension or asset kinds only as
  a fallback for older designs), platforms are the strategy's pins resolved against
  `core/reference/platforms/`, the bundle budget is the tightest required limit, ad kinds
  come from the design's placements, and the dev plan's estimates are a stated heuristic
  reported against the timebox, never fitted to it. See `docs/techplan-module.md`.
  *Existing runs:* a run started before this change has no `tech-plan` step; resume it as
  before, or start a new run to get one.
- **Init writes `game.config.yaml` from the tech plan.** With a `tech-plan` in the run, init
  rewrites `engine`, `platforms` and `monetization` in place (comments and every other field
  kept, the result parsed back and checked), vendors the pinned profiles into
  `config/platforms/`, and makes one local commit carrying the idempotency key as a trailer.
  It never pushes. A 3D design now reaches the game repository as `engine.type: threejs`
  instead of the template default.
- **Init `factory.init.source: local`.** Makes the project from a local template checkout
  (`template_path`, pinned by `template_ref`) with `git archive` into a new repository with no
  remote: offline, for golden-regression runs. `github` stays the default and is unchanged.
- **`scaffold-record` fields (additive, schema 1.1.0):** `template.source` (`github` |
  `local`), `game_config.engine`, `game_config.commit_sha`, `game_config.pushed`. Existing
  records remain valid; an absent `template.source` means `github`.

- **Release module (`scripts/wgf_release`, step type `release`, stage `release:draft`).**
  The `release` step is real: `wgf new-game` no longer needs `--mock` for it. It drafts a
  release only when the newest qa-report in the run passed, pins the newest
  verification-report, prototype-report and sdk-report by hash, and names the same commit as
  each of them and as the checkout's HEAD; the checkout is clean and its bundle is the one
  verification digested. It then runs the game repository's own `release:package` and
  `release:manifest` (as owned process trees, `wgflib.procs`), checks every package's sha256
  against its file, refuses archives with sourcemaps, test files, env/secret files or
  secret-looking content or without `index.html` at their root, validates the manifest
  against the schema, and returns it in state `draft`. It never pushes, tags, publishes or
  contacts a portal. See `docs/release-module.md`. **Contract change:** the `release` step
  now declares `verification-report`, `sdk-report`, `prototype-report` and
  `scaffold-record` besides `qa-report`; `factory.release.checkouts` locates the game
  repository.
- **Evidence statuses.** `PASS`, `PASS_MOCK`, `BLOCKED_EXTERNAL`, `UNVERIFIED`, `FAIL`, in
  the new shared primitive `core/artifacts/shared/evidence.schema.json`, alongside (not
  instead of) the routing statuses. A check observed only against a stand-in — every SDK
  feature exercised against a mocked portal SDK — is `PASS_MOCK`, and so is every
  verification, qa-report, platform and release manifest resting on one; nothing promotes it
  to `PASS`. A platform's own portal QA is `BLOCKED_EXTERNAL` unless its SDK evidence says it
  was observed on the live portal (`NOT_APPLICABLE` for a profile whose review process is
  `none`).

  *Schema changes, all additive:* `verification-report` gains `evidence_status`,
  `workflow`, `checks[].evidence_status`, `platform_readiness[].evidence_status` and
  `portal_status`; `qa-report` gains `evidence_status`, `workflow` and
  `platform_checks[].evidence_status` / `portal_status`; `release-manifest` gains
  `workflow`, `template`, `evidence` (what the draft was cleared by: qa and verification
  reports, commit lineage, bundle hash, per-platform evidence, package audit,
  reproducibility) and `packages[].content_digest` / `files`. Reports the verify step writes
  now declare `schema_version` 1.1.0; drafted manifests 1.1.0.

  *Migration:* none for existing artifacts, which stay valid. A qa-report without
  `evidence_status` (1.0.x) is refused by the release step: re-run verify.

- **Assets module (`scripts/wgf_assets`, step type `assets`).** Turns a game design into an
  asset manifest and the files behind it: inspects `game_design.asset_requirements` (or
  derives a baseline), classifies each against the new `core/reference/asset-policy.yaml`,
  reuses a design's existing file or a licensed library asset, otherwise generates a
  placeholder — through an optional 2D asset MCP server when one is configured, always
  falling back to a standard-library procedural backend — then validates formats from the
  bytes, optimizes losslessly and records licence, origin and usage constraints per item.
  An asset whose licence is unknown or restricted, or that has no recorded origin, is never
  `production_ready`. Covers 2D (sprites, sheets, backgrounds, UI, icons, VFX, fonts, audio)
  and 3D (models, textures, materials, animations, environments). Registered in
  `factory.steps.modules`; see `docs/assets-module.md`.

  *Schema changes, all additive:* `asset-manifest` items gain `dimension`,
  `license_status`, `usage_constraints`, `origin`, `placeholder`, `production_ready`,
  `files`, `reference`, `optimization` and `issues`, the `type` enum gains `background`,
  `material` and `environment`, and the manifest gains `policy`, `issues` and `generation`
  (instances now declare `schema_version` 1.1.0). `game-design` gains optional
  `asset_requirements`. The `assets` step and `title:prototype` now also consume
  `scaffold-record` (for platform bundle limits), and `title:prototype` names
  `asset-manifest` among its outputs.

  *Migration:* none. Existing manifests and designs stay valid.

- **Development module.** `scripts/wgf_develop` implements the `develop` step and is
  registered in `workspace/config/factory.yaml`. It briefs the build from the game design
  (`docs/development/brief.md` in the game repository), hands it to a developer — a person
  (`handoff`) or a configured command — then checks template conformance, typecheck, lint,
  tests, build and the browser smoke suite, commits once per visit, and emits a
  `prototype-report` that records only what it measured. See
  `docs/development-module.md`. **Contract change:** `develop` now declares
  `scaffold-record` and `title-strategy` as inputs in `core/workflows/new-game.workflow.yaml`;
  existing runs resume unaffected, and a run without them is told what is missing.

- **SDK integration phase (`scripts/wgf_sdk`).** Before its conformance check, the `sdk`
  step now integrates web-game-template's existing platform SDK into a game's gameplay: it reads
  the SDK the game repository carries, compares what each target platform's adapter offers
  with what the game-design needs, writes a gameplay layer (`bootPlatform`,
  `PlatformGameplay`), a plan generated from the design's placements and an SDK-mock suite
  into the game repository, routes the template's boot through it, and reports per platform
  and feature, laid over the conformance result (the worse status wins). It implements no
  SDK and contacts no portal. Settings in `factory.sdk`; `--mock` runs are unaffected. See
  `docs/platform-architecture.md`.
- **The sdk module checked against each portal's current documentation** (Yandex, CrazyGames,
  Poki, GameVui; 2026-09-23). The gameplay layer now keeps one "playing" state with the
  adapter's own, mutes and pauses for every ad and for the portal's own pause (Yandex
  `game_api_pause`), hands late rewards to the game, says why a reward was not granted,
  hides offers when the portal SDK did not load, and gives Poki an ad opportunity before
  every continue (`factory.sdk.break_on_continue`) while keeping interstitials off
  CrazyGames' pause menu (`factory.sdk.interstitial_forbidden_moments`). The boot timeout is
  gone: every adapter bounds its own waits, and replacing one on a timer lost Yandex Game
  Ready and CrazyGames gameplay events. `python -m wgf_sdk.e2e` builds a PixiJS and a
  Three.js game per platform from a template revision and drives it in Chromium against the
  template's own SDK mocks. Platform limitations are listed in
  `docs/platform-architecture.md`. The step also wires the develop module's seam
  (`src/game/integration.ts`): it implements `GameIntegration` on the platform, maps the
  game's own placement ids to the design's moments, and swaps the developer's default
  implementation out of `main.ts`.
- **Workflow module contract.** `docs/workflow-module-contract.md` is what the discovery,
  strategy, design, init, assets, development, SDK and verification modules implement
  against; `scripts/tests/test_workflow_contracts.py` holds the gate — an external module
  plugged in through `factory.steps.modules` runs without engine changes. The engine now
  checks every produced artifact against its schema's top level and provenance before
  persisting it, records which input versions each step consumed, versions its events
  (`format: 1`), accepts dot-namespaced step types, and validates run ids, artifact ids and
  module names before they reach a path or an import. `--mock` auto-approves only the
  workflow's own reversible checkpoint gates. Pausing or cancelling a crashed run takes
  effect at once.
- **`scaffold-record` and `sdk-report` schemas**, named as outputs of `title:scaffolding` and
  `title:prototype`, replacing the workflow's `untyped_artifacts`. Additive: no existing
  artifact changes. The title machine keeps version 1.0.0 because only its declared outputs
  grew.
- **Executable workflow engine (`wgf`).** `core/workflows/new-game.workflow.yaml` defines the
  work from research to release preparation as data; `scripts/wgflib/workflow/` runs it —
  step registry, retry with backoff, failure routing (`verify` fail → `develop`), human
  checkpoints tied to gates, resume, idempotent re-entry, events and a file store in
  `.factory/`. `bin/wgf` exposes `new-game`, `research`, `plan`, `init`, `assets`, `develop`,
  `sdk`, `verify`, `release`, `status`, `logs`, `runs`, `pause` and `cancel`, all through
  one engine. Every step is a placeholder (`--mock`) that emits schema-valid artifacts;
  nothing is researched, built or published. `workspace/config/factory.yaml` configures it.
  `check-integrity.py` now validates workflow files. Existing artifacts are unaffected.

- **`tech_plan.repo_params.game_config.monetization`** — the ad kinds a title commits to,
  carried into the game repository. Platform profiles assert on `package.uses_banner_ads` and
  `package.uses_rewarded_ads`, and on GameVui the latter is blocking; but observing a run can
  only prove an ad *was* requested, never that one is never requested. Without a declaration
  reaching the game repository, those assertions could not be evaluated honestly. Derived from
  `game_design.monetization.placements[].kind` — not decided in the tech plan.

  *Migration:* optional. An existing tech plan stays valid; a game repository built from one
  without it measures both ad facts as `false`.

- **`scripts/wgf-org-setup.sh`** — creates and reconciles the organization's `WGF_*` Actions
  secrets and variables for the game pipelines. Idempotent, and the living inventory of what
  the organization should hold. It never rewrites an existing secret's value: GitHub cannot
  return one, so `gh secret set` on an existing name would replace a real credential with the
  sentinel.

### Changed

- **Agent-host capability audit (docs/claude-capabilities.md).**
  - `workspace/config/factory.yaml` `review.guarded_paths` is back to the module default,
    `[core, scripts, bin, workspace/config]`. It had narrowed it to
    `[core/workflows, workspace/config]`, which undid the widening from the security pass.
    A test now pins it.
  - The file gains commented, verified headless developer/reviewer argvs for the one host
    audited. The active defaults (`handoff` / `none`) are unchanged.
  - Adapter binding 1.1.0: `architect` produces `review-report` as the read-only reviewer
    in `title:prototype`. `gameplay` and `release` consume what their steps read. Both
    plugins are regenerated.
  - `test_core_agents` gains `LiveDeveloperAndReviewer` (opt-in). `LiveReviewer` could not
    pass against a competent live host and is fixed.
  - No existing artifact is affected.

- **Commit lineage: a real run can release.** The pipeline develop → review → sdk → verify →
  release now names one chain of commits, and every step that reads it applies one rule
  (docs/core-contracts.md §5, `scripts/wgf_verification/lineage.py`). The `sdk` step commits
  its integration once, locally, keyed by the idempotency key in a `Wgf-Sdk-Key` trailer
  (reusing develop's keyed-commit mechanism), and never pushes; it refuses (`BLOCKED`) a
  checkout whose HEAD is not the prototype-report's commit or this run's sdk commits on it,
  and uncommitted changes it did not make. `sdk-report.build_ref` gains `base_commit_sha` and
  `sdk_commits` (**sdk-report 1.2.0, additive**). verify's `source.upstream-commits` and
  release both require: sdk-report commit == verified commit == HEAD; prototype-report commit
  == sdk base; `git log base..sdk` holds only this run's sdk commits — otherwise
  `commit-lineage-mismatch`. release now takes `review-report` as an input (workflow
  `new-game`, and `release:draft` added to its consumers): an approval must be of exactly the
  prototype commit, a request for changes refuses (`review-not-approved`), and a skipped
  review is recorded as `evidence.review.status: skipped` — never as approved
  (**release-manifest 1.2.0, additive**: `evidence.review`). Placeholder commits are gone:
  develop returns `BLOCKED` instead of `"0"*40`, sdk `BLOCKED` instead of `"unknown"`, and
  release refuses either as `commit-unknown`. The engine now enforces artifact lineage: with
  a validator, an output declaring `provenance.inputs` must pin exactly the versions its step
  consumed (`contracts.check_lineage`, plus no pin of a declared input the step was not
  given), else a non-retryable `FAILED`. Proved by `scripts/tests/test_core_lineage.py`.
  *Existing artifacts:* sdk-reports and release-manifests from before still validate; an
  sdk-report without `base_commit_sha` is read as having made no commit, so it must name the
  prototype's commit. A prototype-report or sdk-report naming a placeholder commit can no
  longer be released from: re-run develop (and sdk) so they commit.

- **Verification no longer passes on stale or unowned evidence.** An sdk-report or
  prototype-report naming another commit than the one under test is now a required,
  `BLOCKED` `source.upstream-commits` check (was a non-blocking warning), and SDK checks
  built on such an sdk-report are `BLOCKED`. Runtime facts and assertion results left by an
  earlier run are deleted before the commands that write them, an assertion evaluator that
  exits non-zero without a blocking breach is `FAIL`, a Playwright run that exits non-zero
  with a green report is `FAIL`, a recorded scenario citing a screenshot that does not exist
  is not counted, and the Playwright report, assertion results, runtime facts, recorded
  session and screenshots are pinned by sha256 in the evidence.
- **`sdk-report` 1.1.0**, additive: optional `sdk`, per-platform `adapter`, per-feature
  `required_by`/`hooks`/`fallback`, feature status `unsupported`, and an `integration` block
  (files, placements, game hooks, tests). Existing 1.0.0 reports still validate.
- **The workflow's `sdk` step reads `game-design` and `scaffold-record`** as well as
  `prototype-report`: it integrates what the design placed into the repository init made.
  A run whose `sdk` step was already completed is unaffected.
- **`criteria-expression` now states which way `in` and `not_in` read.** Platform profiles use
  `{left: package.locales, op: in, right: [ru]}` to mean "the package ships Russian". Read as
  the conventional "left is a member of right", that assertion passes for a package with no
  locales at all — and locale assertions are blocking on three platforms. The operator
  description now fixes the semantics: an array measurement asks whether every element of
  `right` is present in it; a scalar measurement asks whether it appears in `right`.

  *Migration:* none to the data. Any evaluator written against the old reading must be
  corrected, and its locale results re-checked.

### Notes from implementing the template's pipelines

Findings that belong with the methodology even though the code lives in the sibling repository:

- A **gate needs a mechanism, not a name**. `environment: production` in a workflow is not a
  gate — GitHub creates an unconfigured environment implicitly, with no protection, the first
  time a job names one. G6 and G7 are enforced by *required reviewers* on that environment, and
  the workflows now verify that rather than assume it.
- **Required reviewers are unavailable on private repositories under a free plan.** A private
  game repository on a free organization cannot enforce G6 or G7 through environments at all.
  Worth deciding per title, since `repo_params.visibility` defaults to `private`.
- **Platform profiles must be vendored into the game repository** at the pinned version. A game
  repository has no access to `core/`, and `platform-validation.md` names validating against
  the current profile rather than the pinned one as a failure mode. They go to
  `config/platforms/` as byte-identical copies, so drift is a plain diff.
- **Only Poki has a headless upload path.** Yandex, CrazyGames and GameVui accept a ZIP through
  a console a person logs into. `publish.md` already says no portal APIs are integrated by
  design; this is the same conclusion arrived at from the other direction.

## 2026-09-22 — initial

- `core/`: four lifecycle machines, seven gates as data, thirteen artifact schemas with their
  contracts in `x-wgf`, five platform profiles, twelve role charters, adapter bindings.
- `claude-web-game-plugin/` and `codex-web-game-plugin/`, generated from `gen-adapters.sh`.
- `workspace/`: a complete worked example from a market claim to a kill decision at G4.
- `scripts/check-integrity.py` for referential integrity across machines, schemas, roles and
  bindings.
