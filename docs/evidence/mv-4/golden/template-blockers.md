# What stops the 2D golden run on Windows — and does not stop it on Linux

**The golden gate is not blocked.** On the Linux acceptance runner, at `origin/main`
`02bf577`, against the same pinned template `bca41a97665f…` (`v1.1.0`), both golden runs pass:

```
CATEGORY         RESULT   TESTS  PASS  FAIL  ERROR  SKIP
2D GOLDEN        PASS        10    10     0      0     0
3D GOLDEN        PASS        10    10     0      0     0
Core Acceptance Suite: OK (INCOMPLETE — 7 tests skipped in PASS categories; 639 tests)
```

Run 36520006818 (https://github.com/Cuvara/web-game-factory/actions/runs/36520006818),
Ubuntu 24.04, the workflow PR #10 added (`031ca0e`). The unit suite in the same run:
`OK (skipped=36)` over 1 603 tests. **That run is the evidence that the template pinned when
these measurements were taken passes the golden gate on POSIX.** Main has since released 2.3.0
and moved the pin to `v1.2.0`; its own acceptance run (36538299558, `adea9a3`) is green too.

What follows is therefore a record of two `web-game-template` defects that reproduce **on
Windows**, and of where the Windows golden run stops because of them. They are template
defects and they are recorded as such; they are **not MV-4 golden blockers**, and they are not
fixed here — this branch changes no game or template source, and the template work is a
separate track.

On Windows the run reaches `develop` with the checkout scaffolded, the assets placed and the
whole ported example game written into it — `pnpm install` and `prettier` both succeed inside
the replay developer — and fails on the game repository's **own** checks:

```
FAILED develop  checks failed - unit: pnpm run test: exit 1; smoke: pnpm run test:e2e: exit 1
```

## 1. `pnpm run test` — ten unit files never load, on Windows

```
$ cd web-game-template && pnpm exec vitest run --project unit          # Windows
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

Reproduced three times on Windows: the sibling `web-game-template` working copy at `v1.1.0`, the
golden run's generated game under `C:\tmp`, and the same working copy at template `main`
(`570815a`) — so it is present in the current template, not only in the pinned one.

**It does not happen on Linux.** The template's own CI at `570815a` reports
`Test Files 1 failed | 49 passed (50)`, `Tests 942 passed`, and the single failure is
unrelated (`tests/unit/pixi-assets.test.ts`, `ReferenceError: navigator is not defined`). The
ten files here are among the 49 that pass. The Factory's Linux acceptance run reaches the same
conclusion from the other side: the golden `develop` step runs this very suite inside the
generated game and both goldens pass 10/10.

## 2. `pnpm run test:e2e` — the smoke suite's insecure-request check, on Windows

```
2 failed
  [desktop] tests\e2e\smoke.spec.ts >> makes no insecure requests
  [mobile]  tests\e2e\smoke.spec.ts >> makes no insecure requests
Received: ["http://imasdk.googleapis.com/js/core/bridge3.791.0_en.html"]
```

The build targets Poki, so it loads the Poki SDK, which pulls Google's IMA bridge over `http`.
`tests/e2e/smoke.spec.ts` counts that as the game's own insecure request — at `v1.1.0` (the
pin), at `v1.2.0` and at template `main`:

```ts
if (url.startsWith("http://") && !url.startsWith("http://localhost")) insecure.push(url);
```

The same question was already answered for the *facts* collection and only there:
`5893fbd fix(verify): scope insecure_requests to the game's own resources` (template PR #5)
changed `tests/verify/facts.spec.ts` alone, and is contained in `v1.1.0`, `v1.2.0` and `main`.
The game in `../tower-merge-rush` carries a hand-applied version of that rule in its *own*
smoke spec (`chore(sync): scope insecure_requests to game resources`). So the correction exists
for one of the two specs, and **no upstream branch or PR carries it for the smoke spec**. The
two specs in one repository disagree about what "the game's own resources" means.

On Linux this never fires during a golden run for a different reason: the Factory's refusing
proxy stops the SDK script from loading at all, so there is no IMA bridge to request. That
proxy is set through the proxy environment variables, which Chromium reads on Linux and ignores
on Windows in favour of the system configuration — the Factory defect fixed in this branch as
far as it can be: the guard now reports `enforced: false` with the reason instead of reporting
zero refusals, which reads as isolation. Making the guard hold on Windows needs the proxy passed
to the browser at launch, which is the game repository's Playwright configuration, not the
Factory's.

## Consequence for MV-4

Steps `review`, `sdk`, `sdk-review`, `verify`, `prototype-review` and `release` are NOT_RUN **on
Windows**, so the Windows golden run contributes no evidence for them. The record of the run
that reaches this point is `golden-2d-windows.json` beside this file.

That is a statement about this machine, not about the gate. On Linux the same steps run and
both goldens pass 10/10 (run 36520006818, `02bf577`, pin `bca41a97665f…`), so:

- the golden gate is **not blocked**, and MV-4 does not claim it is;
- these two defects are **not MV-4 blockers**. They are `web-game-template` defects, recorded
  here because MV-4 found them, and they belong to the template's own track;
- no template change, template release or Factory pin change is part of MV-4. This branch
  touches `workspace/config/template.lock.json` not at all. The measurements here were taken
  against `bca41a97665f8a32d0f803d46a7bbd001ac94d41` / `v1.1.0`, the pin in force when they
  were made; Factory 2.3.0 has since moved the pin to `v1.2.0` (`b106261`) with its own green
  Linux run (36538299558, `adea9a3`);
- what MV-4's Windows runs do establish is narrower and still worth having: the pipeline
  reaches a scaffolded repository with the ported game written into it on a second operating
  system, after the two Factory defects this branch fixes, and stops there for reasons outside
  the Factory.
