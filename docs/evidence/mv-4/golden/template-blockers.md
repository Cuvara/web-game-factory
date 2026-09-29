# What stops the 2D golden run on Windows, after the Factory's own two defects were fixed

The run now reaches `develop` with the checkout scaffolded, the assets placed and the whole
ported example game written into it — `pnpm install` and `prettier` both succeed inside the
replay developer — and fails on the game repository's **own** checks:

```
FAILED develop  checks failed - unit: pnpm run test: exit 1; smoke: pnpm run test:e2e: exit 1
```

Both causes are in `web-game-template`, not in the Factory, and both reproduce outside any
golden run. This branch changes no game or template source, so neither is fixed here.

## 1. `pnpm run test` — ten unit files never load

```
$ cd web-game-template && pnpm exec vitest run --project unit
 FAIL |unit| tests/unit/assertions-pin.test.ts
 FAIL |unit| tests/unit/assertions.test.mjs
 FAIL |unit| tests/unit/crazygames-audit.test.mjs
 FAIL |unit| tests/unit/facts.test.ts
 FAIL |unit| tests/unit/gamedistribution-release.test.ts
 FAIL |unit| tests/unit/poki-audit.test.mjs
 FAIL |unit| tests/unit/release-manifest.test.ts
 FAIL |unit| tests/unit/release-package.test.ts
 FAIL |unit| tests/unit/sdk-integration.test.ts
 FAIL |unit| tests/unit/platform/check-integration.test.mjs
 Test Files  10 failed | 40 passed (50)
      Tests  823 passed (823)
```

Every one fails to parse, not to assert:

```
SyntaxError: Invalid or unexpected token
 ❯ tests/unit/poki-audit.test.mjs:2:31
```

All ten, and only these ten, import a CLI under `scripts/` that begins with a shebang:

| Test file | Imports |
|---|---|
| `assertions-pin.test.ts`, `assertions.test.mjs` | `scripts/verify/evaluate-assertions.mjs` |
| `crazygames-audit.test.mjs` | `scripts/crazygames-audit.mjs` |
| `facts.test.ts` | `scripts/verify/collect-facts.mjs` |
| `gamedistribution-release.test.ts` | `scripts/release/gamedistribution-wrapper.mjs` |
| `poki-audit.test.mjs` | `scripts/verify/poki-audit.mjs` |
| `release-manifest.test.ts` | `scripts/release/make-manifest.mjs` |
| `release-package.test.ts` | `scripts/release/package.mjs` |
| `sdk-integration.test.ts` | `scripts/sdk/prepare-integration.mjs` |
| `platform/check-integration.test.mjs` | `scripts/sdk/check-integration.mjs` |

Node itself is content with them — `node -e "import('./scripts/verify/poki-audit.mjs')"`
resolves and exports normally — so this is the vitest/vite transform on this platform, not the
module. 823 tests pass; these ten files contribute none, because they never load.

Reproduced twice, in two repositories: the sibling `web-game-template` working copy at its own
path, and the golden run's generated game under `C:\tmp`.

## 2. `pnpm run test:e2e` — the smoke suite's insecure-request check

```
2 failed
  [desktop] tests\e2e\smoke.spec.ts >> makes no insecure requests
  [mobile]  tests\e2e\smoke.spec.ts >> makes no insecure requests
Received: ["http://imasdk.googleapis.com/js/core/bridge3.791.0_en.html"]
```

The build targets Poki, so it loads the Poki SDK, which pulls Google's IMA bridge over `http`.
The pinned template `v1.1.0`'s `tests/e2e/smoke.spec.ts` counts that as the game's own insecure
request. The game generated on 2026-09-23 in `../tower-merge-rush` carries a later template
commit whose smoke spec excludes the ad-SDK hosts explicitly
(`chore(sync): scope insecure_requests to game resources (web-game-template@fix/facts-scope)`),
so the correction exists on a template branch and is **not in the pinned release**.

On Linux this never fires during a golden run for a different reason: the Factory's refusing
proxy stops the SDK script from loading at all, so there is no IMA bridge to request. That
proxy is set through the proxy environment variables, which Chromium reads on Linux and ignores
on Windows in favour of the system configuration — the Factory defect fixed in this branch as
far as it can be: the guard now reports `enforced: false` with the reason instead of reporting
zero refusals, which reads as isolation. Making the guard hold on Windows needs the proxy passed
to the browser at launch, which is the game repository's Playwright configuration, not the
Factory's.

## Consequence for MV-4

Steps `review`, `sdk`, `sdk-review`, `verify`, `prototype-review` and `release` are NOT_RUN on
this platform, so the golden run contributes no evidence for them here. The record of the run
that reaches this point is `golden-2d-windows.json` beside this file.
