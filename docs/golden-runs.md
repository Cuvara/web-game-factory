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
research -> strategy -> G2 -> design -> tech-plan -> G3 -> init -> assets
         -> develop -> review -> sdk -> sdk-review -> verify -> G4 -> release
```

G2 and G3 are auto-approved (reversible; configured below). G4 is irreversible, so the run
stops there `WAITING`; the harness answers it `pass` through the API `wgf decide` uses,
with `decided_by` left to `default_decider()` - `human`, because the person running the
golden run is outside every step's process tree - and resumes. Its note says it is the
harness operator's pass of a known-good port (`harness.G4_NOTE`). `games.EXPECTED_STEPS`
lists all 15 steps, `prototype-review` and `sdk-review` included. The golden reviewer
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

Needs: `git`, `node` + `pnpm` with a warm store (installs run `--offline` /
`--prefer-offline`), Playwright's Chromium installed, and a git checkout of
`web-game-template` (`WGF_TEMPLATE_DIR`, default `/mnt/e/GameWeb/web-game-template`, else
the sibling `../web-game-template`). The work directory defaults to a fresh
`mkdtemp(prefix="wgf-golden-")` under `$WGF_GOLDEN_DIR` or `/tmp` — keep it on a fast local
file system, not a Windows mount.

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
are test fixtures, so the lock names them separately (`golden_ports`: template main
`ea466d7`, which is v1.1.0 plus the ports), and the replay developer reads them from a
checkout of that commit (`--ports`, `wgflib.template.golden_ports_checkout()`). The game
repository itself is still created from the pinned release, exactly.

| Template path | What |
|---|---|
| `examples/tower-merge-rush/wgf-golden/` | the 2D port: `src/main.ts`, `src/game/app.ts`, UI, input, the PixiJS view wrapper, `index.html`, `en`/`ru` locales, the tagged browser spec |
| `examples/neon-drift-arena/wgf-golden/` | the 3D port: the same set for the Three.js game |
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
   the repository root (their READMEs and the old default integration excepted): `main.ts`,
   the scene calling the brief's `GameIntegration` seam instead of `platform.showRewarded` /
   `withAdBreak`, UI and pause screens, a small audio service, `en`/`ru` locales,
   `index.html`, and a browser spec tagged `@boot @loading @start @input @core-loop
   @progression @game-over @restart @pause-resume @responsive`;
4. moves that `main.ts` onto the seam the develop step already wrote, as the brief asks any
   developer to: `await createGamePlatform()` for the platform, `createGameIntegration(game,
   platform)` for the seam, no `createPlatform` (`SEAM_REWRITES`: each line must be found
   exactly once, or the replay refuses). `src/game/integration.ts` is the develop step's;
5. adds the engine package the example pins (`pixi.js`, or `three` + `@types/three`) and
   updates the lockfile offline;
6. points the template smoke's `data-scene` assertion at the game's scene (the template
   boot scene file stays: `main.ts` no longer starts it, and the template's SDK matrix
   harness imports it);
7. writes `docs/development/report.json` honestly: a design MVP item the example does not
   cover is `partial` or `cut` and becomes a scope delta (the 2D design is a swap-based
   level puzzle; the replayed game is drop-and-merge, so "Swap and resolve" is `partial`,
   "Level goal" `cut`), every asset is `placeholder`, and `known_issues[0]` says the build is
   a replay.

The develop step then runs its real checks — install, conformance, typecheck, lint, unit,
build, smoke — and commits.

Every file written into a game carries a `GOLDEN-RUN REPLAY` header. The Factory keeps
only data about the replay — `fixtures/<game>/port.json` (copy and replace rules, overlays,
MVP notes, placements, known issues) and the seam rewrites — and no game source: the
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
- **the GitHub path.** `init.source: local`; creating a repository with `gh` is outward-facing
  and is not exercised.

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
