# P0 execution plan (reviewed 2026-10-21)

The concrete plan for milestone M1, initiatives P0-01 to P0-07 of
[implementation-roadmap.md](implementation-roadmap.md). Each finding was re-checked against the
code on `main` 6d458a2 before this plan was written. **Nothing here is implemented. Each item
waits for explicit approval.**

Rules for every item:
- Core v1 is frozen ([docs/core-v1.md](../core-v1.md)). Change one module at a time.
- Validate each change with the module's tests, the contract tests, `bin/wgf test-core` and both
  goldens (`WGF_GOLDEN=1 bin/wgf test-core --strict`) on Linux CI.
- No gate or test is weakened to make a change pass.
- No paid session, upload, submission, merge or release is part of this plan.

## Status update (2026-10-21, later)

P0-03 is implemented by **PR #84** (`fix/ads-per-target-platform`, "per-target ad coverage
gates"). It is open and was being completed in a separate session when this plan was resumed.
It contains:
- the profile field `ads.required_by_portal` (y8 1.4.0);
- one shared coverage rule, `scripts/wgflib/ad_coverage.py`;
- the verify Hard Gate `platform.ads-integrated:<id>`;
- the platform-validate guard `ads_integrated`;
- lesson L30 and `scripts/tests/test_ad_coverage.py`.

Its first CI run failed for two reasons:
- test fixtures pin `y8@1.3.0` against the new 1.4.0 profile;
- `test_core_security.Coupling` forbids portal names in `wgflib/ad_coverage.py`.

That session is fixing both. P0-04 changes the same files (`core/reference/platforms/y8.yaml`,
`scripts/wgf_sdk/integration.py`), so it is sequenced **after PR #84 merges**, never in
parallel with it.

## Findings re-checked

| # | Finding | Status | Evidence checked |
|---|---|---|---|
| 1 | Y8 Builds 001/002 make zero ad calls | **Confirmed** (game repos, reports) | `runs:fixes/bbw-y8ads-REPORT.md`, `sm-y8ads-REPORT.md`; the pre-fix placement list is still visible on the GamePix branch (`runs:fixes/bbw-gp/src/platform/integration-plan.ts:14,21`) |
| 2 | GamePix builds have no ad placement for `gamepix` | **Confirmed** (file + real toolkit) | `integration-plan.ts:14,21` lists `["crazygames","yandex","poki"]`; the GamePix toolkit showed `interstitialAd`/`rewardAd` red (`portal-records.md`) |
| 3 | Release gates bypassed in the manual submission | **Confirmed** (record) | `runs:release-prep-2026-10-18/portal-records.md` header: "G4/G5/G6 and the quality gate were NOT run (user chose manual submission)" |
| 4 | The ad check reads the same source as the implementation | **Confirmed** (code) | `scripts/wgf_verification/checks/platform.py:69-77`: `_declared_ads` = `game.config.yaml` `ad_kinds` plus the design's placements filtered by `platforms`; the profile's `capabilities.ads` is not consulted |
| 5 | Content and progression too thin for portal benchmarks | **Confirmed for designed content** (854 s / 345 s, baseline §5). **Not established for player behaviour**: CrazyGames' 10+ min is a published benchmark of successful titles, not a threshold (re-read 2026-10-21); real playtime needs portal data | `docs/benchmark/2026-10-baseline.md`; https://docs.crazygames.com/resources/basic-launch-metrics/ |
| 6 | Automated QA misses human-found defects | **Confirmed** for D1 (no landscape phone viewport, `core/reference/browser-qa.yaml:46-51`) and for the ad defects (no ad exercise in the bot). D2 confirmed by the QA report; fault injection absent per audit, **to reproduce** against the pre-fix commit | browser-qa.yaml; `runs:release-prep-2026-10-18/qa/report.md` |
| 7a | No per-agent cost tracking | **Confirmed** | `workspace/config/profiles/autonomous.yaml`: design `--output-format text` (:79-80), review `text` (:147-148); develop `stream-json` with `cost_from.jsonl_key: total_cost_usd` (:109-124); no cost read in `scripts/wgf_review`, `wgf_visualqa`, `wgf_leveldesign`, `wgf_assets` |
| 7b | No post-launch revenue import | **Confirmed** | no `scripts/wgf_live/`; no revenue/impression code outside discovery |
| 8 | Research and opportunity selection not enforced | **Confirmed** | `core/workflows/new-game.workflow.yaml:205-216`: `research` then `strategy`; the first gate is G2 at :225 |

## Ad evidence states

The roadmap defines seven states, A1 Declared to A7 Monetized
([implementation-roadmap.md](implementation-roadmap.md#ad-evidence-states)). P0 aims at A2 and A3
for every target build, which the Factory can prove. A4-A6 are a person's observations; A7 is a
portal report. A config entry (A1) is never taken as evidence of the others.

## The plan, per initiative

### P0-01 Y8 report, metric definitions, live ad check

| Field | Plan |
|---|---|
| Files | none in the repo; workspace claims only after the data exists |
| Current | Y8 RPM figures with no known denominator; Build 003 verified only against the mock (A3) |
| Change | Owner exports Revenue Report rows; asks developers@y8.com what RPM divides by; after approval, observes `showAd` `next`/`reward` and `breakStatus` on each live page |
| Acceptance | denominator, window, stage, sample recorded; A6 shown for both games (at least one `viewed` interstitial and one `viewed` rewarded) |
| Tests | none (manual protocol) |
| Platform validation | Y8 live page under the real SDK |
| Dependencies | Y8 approval of Build 003; owner login |
| Rollback | n/a |
| Automatable | no |
| Human approval | **yes**: live login, email to Y8 |
| Status | **blocked externally** |

### P0-02 GamePix builds get ad placements

| Field | Plan |
|---|---|
| Files | game repos, branches `gamepix/bbw-fixed` and `gamepix/sm-fixed`: `src/platform/integration-plan.ts`, `src/platform/gameplay.ts` (if GamePix needs a pause scope), new `tests/unit/gamepix-ads.test.ts`, `tests/gamepix/ads.spec.ts`, Playwright config |
| Current | both placements exclude `gamepix`; toolkit red (A2 and A4 fail) |
| Change | add `gamepix` to both placements, mirroring 185aae6 / d8c8c3a; check GamePix's "pause audio during ads" against the template v1.2.2 adapter; rebuild and repackage |
| Acceptance | unit + e2e against a GamePix mock pass; the zip holds only the GamePix SDK; real Testing Toolkit shows `interstitialAd` and `rewardAd` green (A4) |
| Tests | typecheck, lint, unit, e2e, CrazyGames audit unchanged |
| Platform validation | GamePix Testing Toolkit (24 h test URL) |
| Dependencies | none for the code; toolkit run and upload need the owner |
| Rollback | keep r5 package hashes; revert the branch commit |
| Automatable | code and tests yes; toolkit run no |
| Human approval | **yes** for upload, toolkit and submission; code change needs approval to touch game repos |
| Status | **local work possible now** (game repos) |

### P0-03 Per-target ad hard gate (profile-derived)

| Field | Plan |
|---|---|
| Files | `scripts/wgf_verification/checks/platform.py` (new check beside `_declared_ads`), `core/reference/check-tiers.yaml`, `core/reference/lessons.yaml` (new lesson, `guarded_by`), `docs/verification-module.md`, `scripts/tests/test_verification_*.py` |
| Current | `_declared_ads` (:69-77) derives required kinds from the design's placements, so a placement that omits a target makes nothing required |
| Change | (a) for each target whose **profile** `capabilities.ads` is non-empty, require at least one placement of an offered kind listing the target in the **built** plan (A2), unless the design explicitly and recordedly excludes it; (b) later, with P2-03, require `adsRequested > 0` from a bot session on that target's build (A3) |
| Acceptance | fails on a fixture reproducing the Y8 plan; passes on the fixed plan; explicit exclusion passes with a recorded reason; `check-integrity.py` green |
| Tests | new unit tests with both fixtures; `bin/wgf test-core --only VERIFY`; both goldens on Linux CI. The goldens' replay games must still pass; if a golden fixture lacks a placement for a target, fix the fixture's design, never the check |
| Platform validation | none (deterministic) |
| Dependencies | none for part (a); part (b) needs P2-03 |
| Rollback | remove the check-tiers entry; revert the module commit |
| Automatable | yes |
| Human approval | PR review (core change; stated reason: a revenue-zero defect passed every gate) |
| Status | **local work possible now** |

### P0-04 Pause scope as profile data

| Field | Plan |
|---|---|
| Files | `core/reference/platforms/y8.yaml` (and a default on the others), `scripts/check-integrity.py`, `scripts/wgf_sdk/integration.py` (plan writer at :182-187), `scripts/wgf_sdk/game/src/platform/gameplay.ts` (+ its unit tests), `scripts/wgf_sdk/e2e/smoke.spec.ts`, `scripts/tests/test_sdk_integration.py` |
| Current | `gameplay.ts` pauses and mutes around the request; only `breakOnContinue` is plan data |
| Change | profile field `ads.pause_scope: request | inside-callbacks` (default `request`, y8 `inside-callbacks`, version bump); plan field `pauseInsideAdCallbacks`; port d8c8c3a's `#break` logic; add the spent-rewarded-offer scenario |
| Acceptance | game-side tests cover capped, viewed and silent breaks on Y8; other targets unchanged; regenerating BBW's plan reproduces the hand edit |
| Tests | `python -m unittest scripts/tests/test_sdk_integration.py`; game-side vitest; test-core; both goldens |
| Platform validation | Y8 mock (A3) |
| Dependencies | none |
| Rollback | revert; the field defaults to `request` |
| Automatable | yes |
| Human approval | PR review (core change) |
| Status | **local work possible now** |

### P0-05 Meter every agent session

| Field | Plan |
|---|---|
| Files | `workspace/config/profiles/autonomous.yaml`, `workspace/config/factory.yaml` (commented argv), a shared transcript reader in `scripts/wgflib/` (new; core change), call sites in `scripts/wgf_design/agent.py`, `scripts/wgf_review/step.py`, `scripts/wgf_visualqa/judge.py`, `scripts/wgf_leveldesign/judge.py`, `scripts/wgf_assets/model_judge.py`, `scripts/wgf_listing/` |
| Current | only develop is metered (`scripts/wgf_develop/budget.py`, `scripts/wgflib/budget.py`); design and review run `--output-format text` |
| Constraint found | review and judges use `verdict_from: stdout` ("the last JSON object printed", `factory.yaml:651`). Switching them to a JSON output format wraps their text in a `result` field, so a naive switch breaks verdict parsing |
| Change | one reader that accepts text, json and stream-json, returns (text, cost); verdict extraction reads the text; each step emits a `STEP_LOG` cost event; `wgf status --json` sums cost per run; text output stays supported (cost recorded as unknown) |
| Acceptance | recorded transcripts in each format give the same verdict as today and the right cost; a fixture run reports cost for every agent step |
| Tests | unit tests with recorded transcripts per format; `test_review_module.py`, `test_visual_qa.py`, `test_core_agents.py`, `test_autonomous_profile.py` unchanged in intent; test-core AGENTS; goldens |
| Platform validation | none |
| Dependencies | none |
| Rollback | revert the profile argv to `text`; the reader keeps working |
| Automatable | yes (no paid call is needed to test: recorded transcripts) |
| Human approval | PR review (core change; stated reason: cost per game is unknown) |
| Status | **local work possible now** |

### P0-06 Submissions only from the release path

| Field | Plan |
|---|---|
| Files | `scripts/wgf_release/`, `bin/wgf` subcommand surface (`wgf release --platform <id>` without a run), `workspace/titles/<id>/portals.json` handling (`scripts/wgf-publish.py registry`), `docs/release-module.md` |
| Current | packages built by hand scripts (`runs:release-prep-2026-10-18/build_platforms.py`, `package_platforms.py`) that import Factory internals |
| Change | a supported per-platform release from a named commit: build, package, audit, release-manifest, registry entry with the package hash |
| Acceptance | re-producing Y8 Build 003 from 185aae6 gives the recorded hash d0979a27...e9c2, or the difference is explained (build reproducibility); registry lists every live build |
| Tests | release unit tests; test-core RELEASE; goldens |
| Platform validation | per-platform audit scripts already in the game repos |
| Dependencies | P1-09 (one release line per game) for the real games; the Factory side can be built first |
| Rollback | revert; hand packaging still possible |
| Automatable | yes for the code; recording live builds needs the owner's confirmation of what is live |
| Human approval | PR review; the owner keeps submitting in a live login |
| Status | **local work possible now** (Factory side) |

### P0-07 Template ad and boot hangs; GamePix at the pin

| Field | Plan |
|---|---|
| Files | web-game-template: `packages/platform-sdk/src/adapters/yandex.ts` (after `onOpen`, :449), `adapters/crazygames/platform.ts` (`sdk.init()`, :220), their unit tests; Factory: `workspace/config/template.lock.json` |
| Current | Yandex has no max duration after `onOpen` [I]; CrazyGames `init()` has no timeout [I]; GamePix adapter only in v1.2.2 |
| Change | add a max-duration timer (mirror GameDistribution's 90 s) and an init timeout that degrades to plain web; release template 1.2.3+; move the pin with both goldens in one commit |
| Acceptance | new adapter tests for a lost close callback and a hung init; goldens pass at the new pin (`WGF_TEMPLATE_COMMIT=<sha>` first) |
| Tests | template CI; Factory `WGF_GOLDEN=1 bin/wgf test-core --strict` on Linux |
| Platform validation | template SDK mocks |
| Dependencies | template release and tag |
| Rollback | revert the lock commit |
| Automatable | code yes; release no |
| Human approval | **yes**: template push and tag |
| Status | code local; **release blocked on approval** |

## What can start now, and what waits

| Can be done locally now (after approval to start) | Blocked externally |
|---|---|
| P0-03 part (a), P0-04, P0-05, P0-06 (Factory side): Factory repo, Linux CI validates | P0-01: Y8 approval, owner login, email |
| P0-02 code and tests: game repos | P0-02 upload and toolkit: owner |
| P0-07 template code | P0-07 template release and pin move: approval |

## Recommended first batch

**Batch 1: stop the zero-ads defect class.** Ship it as two PRs, one module each.

1. **P0-04, pause scope as profile data.** It makes the Factory's regenerated games match the
   game fixes, and P0-02 and P1-09 depend on it.
2. **P0-03 part (a), the per-target ad hard gate.** It makes the Y8 and GamePix defects
   impossible to ship again.

Acceptance criteria for batch 1:
- A fixture plan with a target missing from both placements fails verify with the new Hard Gate.
  The fixed plan passes.
- A Y8 capped break does not pause or mute. A viewed break pauses at `beforeAd` and resumes at
  `afterAd`. A silent SDK leaves the game running. Other targets are unchanged.
- Regenerating Brick Breaker Worlds' plan from its design reproduces the hand-edited Y8 fields.
- `python scripts/check-integrity.py` is OK, and `python -m unittest discover scripts/tests`
  passes (Windows-only environment failures listed separately).
- `bin/wgf test-core` and both goldens pass on Linux CI, with no SKIP category.
- No golden fixture, test or gate is loosened.

**Batch 2** (in parallel or next): P0-05 metering. **Batch 3:** P0-06. P0-02 runs in the game
repositories when the owner is ready to upload to GamePix. P0-07 runs when a template release is
approved.
