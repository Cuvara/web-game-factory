# The template contract

A game repository is generated from `web-game-template`, pinned by commit in
`workspace/config/template.lock.json`. Every Factory step that reads from a game repository, or
runs something in one, relies on names the template chose: file paths, npm scripts, node CLIs
and their flags, files a suite writes, keys in `game.config.yaml`, and Playwright and Vitest
projects. Those names are the **template contract**.

`scripts/wgflib/template_contract.py` is the one list of them. Step modules import a name from
it instead of retyping the literal. `CONTRACT_VERSION` changes whenever an entry is added,
removed or renamed:

- **major**: the Factory stops accepting a repository it accepted before (an entry added or
  renamed);
- **minor**: the Factory only stops assuming something (an entry removed or made optional).

Like all of `wgflib`, the module names no renderer or portal (`test_core_security.Coupling`).
The engines are the `engine.type` enum of `core/artifacts/tech-plan.schema.json` (the list
`guards.supported_engines()` also reads). The engine-specific paths are derived from the engines
by the template's naming convention: `packages/<engine without "js">-framework/` and
`src/rendering/<engine>/`. The drift test holds that convention against the pinned template.

## What it lists

| Kind | Names | Read by |
|---|---|---|
| Required paths (`INFRASTRUCTURE`) | root config, `packages/*`, `config/platforms/`, `scripts/{verify,release,publish}/`, `tests/{unit,integration,e2e,verify}/`, `.github/workflows/*` | init's `missing_infrastructure` |
| Template source (`SOURCE_PATHS`) | `src/main.ts`, `src/rendering/*`, `src/platform/`, `tests/e2e/smoke.spec.ts`, platform-sdk `types.ts`/`registry.ts` | develop brief and checks, SDK inspector |
| Package manager | `pnpm`, `pnpm-lock.yaml` | verify, sdk, release |
| npm scripts (`NPM_SCRIPTS`) | `build`, `typecheck`, `lint`, `format`, `format:write`, `test`, `test:unit`, `test:integration`, `test:e2e`, `test:verify`, `sdk:conformance`, `test:sdk:browser`, `release:package`, `release:manifest` | verify, develop, sdk, release |
| Forwarded flags (`SCRIPT_FLAGS`) | `release:package --release`; `release:manifest --release --version --kind --state` | release |
| `pnpm exec` tools (`EXEC_TOOLS`) | `vitest`, `tsc` | sdk |
| Node CLIs (`NODE_CLIS`) | `scripts/verify/collect-facts.mjs --platform --out`; `scripts/verify/evaluate-assertions.mjs --platform --facts --out` | verify (policy) |
| Outputs (`OUTPUTS`) | template-named: `build/runtime-facts.json`, `build/sdk-conformance.json`, `build/facts/<platform>.json`, `release/<id>/{packages.json,checksums.txt,manifest.json}`. Factory-named: `build/assertions/<platform>.json`, `build/verification/gameplay-session.json`, `build/verification/playwright-e2e.json` | verify, sdk, release |
| `game.config.yaml` | `game.id`, `game.version`, `engine.type` ∈ `ENGINES`, `platforms[]` `{id, profile, role}`, `monetization.ad_kinds`, `build.command`, `build.output` (default `dist`), `verification.mobile_test` | init, verify, release, develop |
| Test projects | Playwright `desktop`, `mobile`, `verify`; Vitest `unit`, `integration`, `sdk` | verify (gameplay, runtime facts), sdk |
| `@aspect` tags (`ASPECTS`) | `boot`, `loading`, `start`, `input`, `core-loop`, `progression`, `game-over`, `restart`, `pause-resume`, `responsive` | verify (gameplay), the developer brief |

## How drift is caught

`scripts/tests/test_template_contract.py` holds every entry against a checkout of the pinned
commit (`wgflib.template.checkout()`, never the sibling working copy). It checks that:

- every required path and every template source path exists;
- every npm script is in `package.json`;
- every node CLI exists and its usage text mentions the flags the Factory passes;
- the CLIs behind the forwarded scripts mention their flags;
- every template-written output is named by the code that writes it;
- the `game.config.yaml` keys are present;
- the Playwright and Vitest projects are declared.

The test skips, with the reason, only when the pinned checkout cannot be obtained. It also
fails when a module that has moved to the contract still carries a raw copy of a contract
path, output or namespaced script name.

Moving the template pin therefore runs the contract as well: a template release that renames
`test:verify` fails this test before any golden run starts.

## Not yet covered

- `scripts/wgf_develop/` still carries its own copies of the paths, scripts and engines it
  uses. It moves to the contract in a later module; until then, the drift test checks those
  entries in the template, but not the develop module's copies.
- The template does not yet publish its side of the contract. The intended follow-up is a
  machine-readable `wgf-interface.json` in the template (its version, scripts and paths), which
  init and verify would compare against `CONTRACT_VERSION` and these lists. It is a template
  issue, not a Factory one.
