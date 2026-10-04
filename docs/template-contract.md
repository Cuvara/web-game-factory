# The template contract

A game repository is generated from `web-game-template`, pinned by commit in
`workspace/config/template.lock.json`. Every Factory step that reads from a game repository, or
runs something in one, relies on names the template chose: file paths, npm scripts, node CLIs
and their flags, files a suite writes, keys in `game.config.yaml`, and Playwright and Vitest
projects. Those names are the **template contract**.

`scripts/wgflib/template_contract.py` is the one list of them. Step modules import a name from
it instead of retyping the literal. `CONTRACT_VERSION` versions what the Factory requires of a
repository, and follows acceptance:

- **major**: the Factory can refuse a repository it accepted before (a required entry added
  or renamed);
- **minor**: the Factory only stops assuming something (an entry removed or made optional);
- **unchanged**: an entry the Factory only recognizes when present (it refuses nothing
  without it), or a rule the pinned contract already had that the Factory now encodes.

Every change to the entries is recorded, versioned or not: `CONTRACT_LOG` says what changed,
in which Factory release, and why; `CONTRACT_DIGEST` is a sha256 over the entries (names,
flags, owners - never their descriptions), and `test_template_contract` fails when the
entries change without the digest and the log being updated. Contract 1.0.0's log: written
in 2.0.0 (M10); 2.1.1 added `src/game/boot-scene.ts` (recognized, never required); 2.2.0
encodes `build_target`, the build-target rule contract 1.0.0 always had. **Contract 2.0.0**
(Factory 2.3.0): `phaserjs` joined the `engine.type` enum, so `packages/phaser-framework/`
and `src/rendering/phaserjs/` became required entries — a repository generated from a
template that predates them is now refused, which is exactly what a major means. Factory
2.8.0 encodes, unversioned, what the pinned contract already offered for per-platform builds:
the `WGF_GAME_CONFIG` override (`vite.config.ts`, `scripts/_shared.mjs` `readGameConfig`) and
`release:package --platform`, the `build/platforms/<id>/` layout, and - recognized only when
present - contract 2's `build:platforms` and its `package.json` `wgf.template.contract`
marker.
template that predates them is now refused, which is exactly what a major means.
**Contract 2.1.0** (Factory 2.8.0): CI never publishes a game to a portal - publication is the
Factory's `publish` group, behind a person's G6 (`docs/publish-module.md`) - so
`.github/workflows/publish.yml` and `scripts/publish/` are no longer required. A repository
without them is accepted; the pinned template (v1.2.0) still ships both, and the drift test
still passes against it because removing an assumption never breaks it. Also unversioned:
`PLATFORM_REGISTRY` names the adapter registry `SOURCE_PATHS` already required, because its
`KNOWN_PLATFORM_IDS` are now read - `workspace/config/template.lock.json` `platform_adapters`
records them for the pin, `check-integrity.py` and `test_core_template` hold the two equal,
and strategy and tech-plan refuse a platform outside the list (`docs/techplan-module.md`).

Like all of `wgflib`, the module names no renderer or portal (`test_core_security.Coupling`).
The engines are the `engine.type` enum of `core/artifacts/tech-plan.schema.json` (the list
`guards.supported_engines()` also reads). The engine-specific paths are derived from the engines
by the template's naming convention: `packages/<engine without "js">-framework/` and
`src/rendering/<engine>/`. The drift test holds that convention against the pinned template.

## What it lists

| Kind | Names | Read by |
|---|---|---|
| Required paths (`INFRASTRUCTURE`) | root config, `packages/*`, `config/platforms/`, `scripts/{verify,release}/`, `tests/{unit,integration,e2e,verify}/`, `.github/workflows/*` | init's `missing_infrastructure` |
| Template source (`SOURCE_PATHS`) | `src/main.ts`, `src/rendering/*`, `src/game/boot-scene.ts`, `src/platform/`, `tests/e2e/smoke.spec.ts`, platform-sdk `types.ts`/`registry.ts` (`PLATFORM_REGISTRY`) | develop brief and checks, SDK inspector, the lock's `platform_adapters` |
| Package manager | `pnpm`, `pnpm-lock.yaml` | verify, sdk, release |
| npm scripts (`NPM_SCRIPTS`) | `build`, `typecheck`, `lint`, `format`, `format:write`, `test`, `test:unit`, `test:integration`, `test:e2e`, `test:verify`, `sdk:conformance`, `test:sdk:browser`, `release:package`, `release:manifest` | verify, develop, sdk, release |
| Forwarded flags (`SCRIPT_FLAGS`) | `release:package --release --platform`; `release:manifest --release --version --kind --state` | release |
| `pnpm exec` tools (`EXEC_TOOLS`) | `vitest`, `tsc` | sdk |
| Node CLIs (`NODE_CLIS`) | `scripts/verify/collect-facts.mjs --platform --out`; `scripts/verify/evaluate-assertions.mjs --platform --facts --out` | verify (policy) |
| Build target (`build_target`) | one bundle per build; it boots game.config.yaml's first `required` platform, else its first (`src/core/config.ts` `primaryPlatform`, `scripts/build/game-config-plugin.ts`); no `build:platforms` | verify (`platform.build-target:<id>`, and which platform is built last), release (one bundle: packages only the target) |
| Per-platform builds (`GAME_CONFIG_ENV`, `PLATFORM_BUILDS_DIR`, `platform_dist_dir`, `platform_build_config`, `platform_build_record`, `PLATFORM_BUILDS_INDEX`) | `WGF_GAME_CONFIG=<path>` makes `vite build`, `collect-facts`, `release:package` and `release:manifest` read that config instead of game.config.yaml; the Factory writes `build/platforms/<id>/{game.config.json,dist/,build.json}` and `build/platforms/index.json` under the git-ignored `/build/` | verify (one build per platform, facts per bundle), release (`release:package --platform <id>` per bundle) |
| Contract 2 (`CONTRACT_MARKER`, `template_contract_of`, `SCRIPT_BUILD_PLATFORMS`, `builds_per_platform`) | `package.json` `wgf.template.contract` (absent: 1) and a `build:platforms` script: the repository builds its platforms itself into the same layout. Recognized when present, required nowhere | verify, release |
| Outputs (`OUTPUTS`) | template-named: `build/runtime-facts.json`, `build/sdk-conformance.json`, `build/facts/<platform>.json`, `release/<id>/{packages.json,checksums.txt,manifest.json}`. Factory-named: `build/assertions/<platform>.json`, `build/verification/gameplay-session.json`, `build/verification/playwright-e2e.json` | verify, sdk, release |
| `game.config.yaml` | `game.id`, `game.version`, `engine.type` ∈ `ENGINES`, `platforms[]` `{id, profile, role}`, `monetization.ad_kinds`, `build.command`, `build.output` (default `dist`), `verification.mobile_test` | init, verify, release, develop |
| Test projects | Playwright `desktop`, `mobile`, `verify`; Vitest `unit`, `integration`, `sdk` | verify (gameplay, runtime facts), sdk |
| `@aspect` tags (`ASPECTS`) | `boot`, `loading`, `start`, `input`, `core-loop`, `progression`, `game-over`, `restart`, `pause-resume`, `responsive` | verify (gameplay), the developer brief |

## The play probe showcase

The play probe (`window.__wgf__.play`, `core/artifacts/shared/play-probe.schema.json`) is
the game's code, not the template's, so it is not an entry of `template_contract.py` and
not in `CONTRACT_DIGEST`. One part of it is optional and backwards compatible: a game may
declare a **showcase**, only when the page URL carries `wgf-probe=1`:

```ts
window.__wgf__.play.showcase = {
  targets(): string[];                              // runtime asset ids it can stage
  show(assetId: string): boolean | Promise<boolean>; // stage it; false when it cannot
};
```

- `targets()` lists runtime asset ids (`public/assets/assets.json`) of readable entities
  the build can stage: typically the ones that first appear after the opening unit, which a
  bot starting on a fresh save never reaches.
- `show(assetId)` puts the running game into a real state of play in which an entity drawn
  from that asset is on screen - the unit it first appears in, its encounter - through the
  game's own loading and rendering, and resolves `true`; `false` when it cannot. Afterwards
  `snapshot()` reports `state: "playing"` and the entity with `asset` (or one of its
  variants) and its drawn box.

The playability bot uses it only in its last test, after its fresh-save play, and keeps a
frame of each staged state (`docs/playability-module.md`); production-quality's
`assets.runtime` credits an asset there only where that frame shows it
(`docs/production-quality-module.md`). A game without a showcase is played and judged
exactly as before; no Factory step requires one.

## The play probe unit link and entity kinds

Two more parts of the probe serve the content-sufficiency step
([content-sufficiency-module.md](content-sufficiency-module.md)), both only with
`wgf-probe=1`, and both stated in the probe schema:

- **The unit link.** A page URL that also carries `wgf-unit=<unit id>` (a
  `build_spec.content.units` id) starts play in that unit, as a level select would. The
  playability bot's survey enters every unit this way, so units past the first few the
  traverse reaches are measured. A build that cannot enter a unit starts as it otherwise
  would, and the survey records the unit as not entered; for a game that authors its units,
  that is a `content.units_reachable` failure.
- **Entity kinds.** While a content unit is in play (`content.unit_id` is a string), every
  entity of a content role - threat, goal, target, projectile, collectible, hazard - carries
  its `kind`, in the game's own vocabulary. The schema requires it (`probe.valid` reads it),
  and the content audit counts elements on the build by it.

## How drift is caught

`scripts/tests/test_template_contract.py` holds every entry against a checkout of the pinned
commit (`wgflib.template.checkout()`, never the sibling working copy). It checks that:

- every required path and every template source path exists;
- every npm script is in `package.json`;
- every node CLI exists and its usage text mentions the flags the Factory passes;
- the CLIs behind the forwarded scripts mention their flags;
- every template-written output is named by the code that writes it;
- the `game.config.yaml` keys are present;
- `WGF_GAME_CONFIG` is honoured where the per-platform builds rely on it (`vite.config.ts`,
  `readGameConfig` in `scripts/_shared.mjs`), and `release:package` and `collect-facts` read
  their config through `readGameConfig`;
- the Playwright and Vitest projects are declared.

The test skips, with the reason, only when the pinned checkout cannot be obtained. It also
fails when a module that has moved to the contract still carries a raw copy of a contract
path, output or namespaced script name.

Moving the template pin therefore runs the contract as well: a template release that renames
`test:verify` fails this test before any golden run starts.

## Not yet covered

- `scripts/wgf_develop/` reads the engines, the rendering directories, the renderer
  packages, the npm script names, the package manager, the engine selector and entry point,
  `dist`, and `package.json` / `pnpm-lock.yaml` / `game.config.yaml` / `config/platforms` /
  the Playwright and Vitest configs from the contract (test_checkout.DevelopLiterals). Still
  literal there: the rest of `PROTECTED_PATHS` (`packages`, `.github`, `scripts`,
  `vite.config.ts`, `eslint.config.js`, `tsconfig*.json`, `pnpm-workspace.yaml`) and the
  upstream renderer library names (`pixi.js`, `three`), which are not template names.
- The template does not yet publish its side of the contract. The intended follow-up is a
  machine-readable `wgf-interface.json` in the template (its version, scripts and paths), which
  init and verify would compare against `CONTRACT_VERSION` and these lists. It is a template
  issue, not a Factory one.
