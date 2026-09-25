# Factory v1 — usable (1.1.0)

Core v1 (1.0.0) froze the workflow core. 1.1.0 is the release where that core, against the
**latest released web-game-template**, runs one complete real workflow — research to a
drafted release — with a real Claude developer and a real, read-only Claude reviewer. This
page is the acceptance record: what was run, on what, what it proved, and what it did not.

Core v1's architecture is unchanged: the same workflow definition, engine, state machines,
gates and contracts. Every change below is a fix in the module that owned the defect, each
with a regression test, plus additive contract fields (no existing contract was weakened).

## The template

| | |
|---|---|
| Repository | `Cuvara/web-game-template` |
| Release | `v1.1.0` (latest GitHub release, 2026-09-24) |
| Commit | `bca41a97665f8a32d0f803d46a7bbd001ac94d41` (the tag's target) |
| Lock | `workspace/config/template.lock.json` (`commit`, `ref: v1.1.0`) |
| Golden-run ports | not in the release; pinned separately as test fixtures (`golden_ports`: template main `ea466d7` = v1.1.0 + the ports) and read by the replay developer only. A game is never created from them. |

Before 1.1.0 the Factory was pinned to `22482b4`, a development branch that is in no template
release.

## Factory ↔ template compatibility (the P0 work)

| Item | Before | Now |
|---|---|---|
| init honours the exact template revision | github: the template's default-branch HEAD; local: the checkout's HEAD; the tech plan recorded `<template>@main` | the tech plan records `<repo>@<pinned sha>`, init refuses a plan approved against anything else; github: root→pin applied as one local keyed commit (anything else differing fails loudly); local: the pin or refuse |
| SDK integration through a real seam | regex patches of `src/main.ts` keyed to the template's boot lines — v1.1.0 changed them, every patch "skipped", the step succeeded with an SDK nothing called; `bootPlatform` passed only `{namespace}` | a Factory-owned seam module (`src/platform/integration.ts`: `createGamePlatform()`, `createGameIntegration()`) built on the template's own API (`createPlatform` with `platformOptions(entry)` + `virtual:platform-config`); develop provides the default, sdk writes the integrated one as a whole file; main.ts is never edited; a build that does not boot through the seam fails, non-retryably. Seam calls are read by the game's own TypeScript compiler |
| Y8, GameDistribution, GameMonetize | no core profile: no strategy could target them, init could not vendor them | `core/reference/platforms/{y8,gamedistribution,gamemonetize}.yaml`; the profile schema gains `requirements.game_id`, `game_id_pattern`, `hosting` |
| `game_id` through plan → init → build | the tech-plan schema had no place for it; init's writer dropped every platform key but id/profile/role; the SDK's boot dropped `platformOptions` | `workspace/titles/<title>/portals.yaml` → tech plan (blocks when a required one is missing) → `game.config.yaml` platforms[] (written and read back) → the template's `platformOptions()` → the adapter |

## The acceptance run

Run `new-game-20260925-002051-0fecbd`, from a fresh clone of Factory commit `118e2ab`
(1.1.0's code; the release commit adds only this page, the changelog and the version), with
`workspace/config/factory.yaml` as shipped except: the commented Claude developer and
reviewer examples uncommented, every path outside the checkout, and `init.adopt_existing:
true` (the repository had been created by an earlier diagnostic run of the same title).

```
research → strategy → G2 → design → tech-plan → G3 → init → assets → develop → review → sdk → verify → release
   ✓          ✓       ✓      ✓          ✓        ✓     ✓       ✓         ✓        ✓       ✓      ✓        ✓
```

| Step | Result |
|---|---|
| research, strategy | real modules; title `block-grid-puzzle`; poki required, crazygames and yandex optional |
| G2, G3 | human checkpoints, approved by the operating session on the user's instruction (G3 noted the 19-day estimate against a 7-day timebox) |
| tech-plan | pixijs; `repo_params.template_ref` = `Cuvara/web-game-template@bca41a9…` |
| init | `Cuvara/block-grid-puzzle` (private, from the template; GitHub generated it from template main); pin commit `91e06d1` makes the tree byte-identical to v1.1.0; identity `block-grid-puzzle`; config commit `9620743`; nothing pushed |
| develop | **real Claude developer** (`claude -p`, sonnet, host-restricted tools), 39 min, one attempt; install, conformance (incl. the seam), typecheck, lint, unit, build and the network-guarded Playwright smoke all passed; keyed commit `87c57bf` |
| review | **real read-only Claude reviewer** (`--safe-mode`, Read/Glob/Grep/read-only git): approve, 0 blockers, reviewed commit `87c57bf`, isolation intact, no process left |
| sdk | integration commit `bc12f06` on `87c57bf`; poki, crazygames, yandex **working** (mock conformance + the integration's own suite and typecheck); the game's own placements `extra-moves`, `result-card` integrated; seam calls read by TypeScript 5.9.3 |
| verify | PASS, evidence `PASS_MOCK`: 41 PASS, 4 WARNING, no required check failing, at `bc12f06` |
| release | `r1` draft, 0.1.0, commit `bc12f06`, `poki.zip` / `crazygames.zip` / `yandex.zip` + `manifest.json` + `checksums.txt` (checksums verify); every run artifact validates against its schema with ajv |

End state: the game checkout clean at `bc12f06` (release files in the template's ignored
`release/`), the Factory clone clean, nothing pushed to the game repository, no process left.

### The request-changes loop

In the acceptance run the reviewer approved the first build, so no change was requested.
The loop was exercised live by the diagnostic run of the same title
(`new-game-20260924-165109-777475`): the reviewer requested changes (a real session-bookkeeping
bug), develop fixed it, review approved; that run also went verify FAIL → develop → review →
sdk → verify PASS → release. The routing (`review.on.request-changes: develop`,
`verify.on.fail: develop`) is data in the workflow file and did not change after it.

## What the real runs found and fixed

Each was found by a real run, fixed in its owning module with a regression test, and the whole
workflow was then run again from a clean checkout.

| Found | Owning module | Fix |
|---|---|---|
| bootstrap.yml cannot mint its token in a new game repository, and the game kept `example-game` | wgf_init | init writes bootstrap's own identity derivation; bootstrap's identical commit rebases away |
| review BLOCKED on 10716 "modified" node_modules files — pnpm store hard links whose ctime other installs move | wgf_review | hard-linked files are judged by inode, size and mtime |
| a valid request-changes verdict read as "no verdict" after quoted code | wgf_review | code fences paired line by line |
| named placement ids (`const X = "id"`) invisible, so no ad would have run | wgf_sdk | names resolved; a computed id reported, never dropped |
| seam calls through a context object invisible; a doc comment read as a call | wgf_sdk | seam calls read by the TypeScript compiler |
| a retry after the developer hit its turn limit did not know the work was half done | wgf_develop | the failure goes into the next attempt's brief |
| `--max-turns 200` ended builds long before the 90-minute timeout | config example | 400 turns / US$40 (measured: ~200 turns, 26–44 min, US$10–15 per build) |
| the smoke check (and verify's browser runs) loaded Poki's real SDK, whose http:// ad bridge failed "no insecure requests" | wgf_develop, wgf_verification | browser checks run behind `wgflib.netguard`'s refusing proxy, as the golden runs always had |
| every first verification failed "no evidence for progression / game-over / pause-resume" | wgf_develop | the brief states verification's tag contract and required aspects, computed by verification's own function |

## Status

| Capability | Status |
|---|---|
| Core workflow, persistence, resume, retry, gates G2/G3 | PASS (acceptance run + Core Acceptance Suite) |
| Real Claude developer | PASS (live, acceptance run) |
| Real read-only Claude reviewer | PASS (live, acceptance run) |
| Request-changes loop | PASS (live, diagnostic run; routing unchanged since) |
| init from the pinned template release, via GitHub | PASS (live) |
| SDK integration | PASS_MOCK — real integration against the template's mocked portal SDKs |
| Verification | PASS_MOCK — real build, real browser, portal SDKs refused |
| Release draft | PASS (draft artifacts; publishing is behind G5/G6) |
| Live portal SDK behaviour, ads, rewards | BLOCKED_EXTERNAL (portal accounts; template issues #1–#15) |
| Portal submission, QA, publishing | BLOCKED_EXTERNAL (G6, human, portal accounts) |
| Template bootstrap in a new game repository | BLOCKED_EXTERNAL — the organization's bot credentials are not available to new repositories, so bootstrap.yml fails there (repository variables and gate environments are not created); init no longer depends on it |
| GameDistribution / GameMonetize / Y8 in a live run | UNVERIFIED — covered by unit tests and the SDK browser e2e (mocks); no acceptance run targeted them |

## Known limitations

- **One build for every platform.** Template v1.1.0 builds once, for the primary platform,
  and packages that build per platform: in the acceptance release the three zips are
  byte-identical, so the optional platforms' packages carry the Poki build. Release
  validation (G5) would reject them; per-platform builds need a template release.
- **CrazyGames sequencing.** The template's own SDK browser suite (not part of the
  workflow's default checks) showed the diagnostic run's game reporting `gameplayStart`
  before `loadingStop` on CrazyGames (optional there).
- **Reviewer judgement varies.** Two reviews of one commit in the diagnostic run disagreed
  (one found a regression, the rerun approved). The Factory enforces the verdict contract and
  isolation, not the reviewer's thoroughness.
- **The template's SDK browser suite is template-scoped** (`factory.sdk.browser`): it builds
  both engines and asserts the template's boot scene, so it does not fit a developed game and
  stays off.

## Tests

| Suite | Before the acceptance run (`118e2ab`) | After (release commit) |
|---|---|---|
| `python -m unittest discover scripts/tests` | 1023 OK, 35 opt-in skips | see the release notes |
| `WGF_GOLDEN=1 bin/wgf test-core` | 395 tests, 9/9 categories PASS (2D and 3D golden 10/10) | see the release notes |
| `check-integrity.py`, `wgf-hash.py --check` | OK | see the release notes |
| SDK browser e2e (`python -m wgf_sdk.e2e`), 7 platforms × 2 engines | PASS (during the work) | see the release notes |
| web-game-template v1.1.0 `pnpm test` | — | see the release notes |
