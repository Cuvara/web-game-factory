# Implementation roadmap

Sequenced initiatives to improve both the games the Factory produces and its ability to produce
commercially successful games repeatedly. Every initiative cites evidence in this package. This
is a plan: **nothing here is implemented, and nothing may be built, merged, uploaded, submitted
or paid for until a person approves it.**

## Horizons

- **P0**: visibility and confirmed blockers.
- **P1**: high-impact game and production improvements.
- **P2**: reusable factory capabilities.
- **P3**: advanced optimization.

## Tags

- **EX**: improves an existing game.
- **FU**: improves future games.
- **SH**: shared infrastructure.
- **GE**: genre-specific.
- **PL**: platform-specific.
- **RS**: research task.

## Scoring

Effort is in engineer-days, with uncertainty low (L), medium (M) or high (H). The priority score
follows [portfolio-economics.md](portfolio-economics.md) §5.

**Core changes.** `scripts/wgflib/`, `core/` and step modules are under the Core v1 freeze
([docs/core-v1.md](../core-v1.md)). Each is one module at a time, with module tests, contract
tests, `bin/wgf test-core` and both goldens (`WGF_GOLDEN=1`, Linux CI), and a stated reason.

## Overview

| ID | Title | Tags | Effort | Impact / conf. | Owner type |
|---|---|---|---|---|---|
| P0-01 | Y8 report, metric definitions, live ad check | EX PL RS | 1 d, L | high / high | person |
| P0-02 | GamePix builds get ad placements | EX PL | 1 d, L | high / high | engineer + owner |
| P0-03 | Per-target ad hard gate (profile-derived) | FU SH | 3 d, M | high / high | engineer |
| P0-04 | Pause scope as profile data | FU SH PL | 2 d, L | medium / high | engineer |
| P0-05 | Meter every agent session | FU SH | 2 d, L | high / high | engineer |
| P0-06 | Submissions only from the release path | EX FU SH | 3 d, M | high / high | engineer + owner |
| P0-07 | Template ad and boot hangs; GamePix at the pin | FU SH PL | 3 d, M | medium / medium | engineer |
| P1-01 | Content depth and mastery layer for BBW and SM | EX GE | 5-8 d, H | high / medium | engineer + person |
| P1-02 | CrazyGames Full Launch readiness | EX PL | 3 d, H | high / medium | engineer + owner |
| P1-03 | Yandex readiness while paused | EX PL | 1 d, L | medium / medium | owner |
| P1-04 | Browser QA: landscape, text-fit, fault injection, throttling | FU SH | 3 d, L | high / high | engineer |
| P1-05 | Teardown corpus for the next concept | FU RS | 3-5 d (people), M | high / medium | person |
| P1-06 | G1 inside the workflow | FU SH | 2 d, M | medium / high | engineer |
| P1-07 | Measured kill metrics at G4 (stranger playtest) | EX FU | 2 d + people, M | high / high | engineer + person |
| P1-08 | Differentiation field and rule | FU SH | 2 d, L | medium / medium | engineer |
| P1-09 | Reconcile game repos with the Factory | EX | 2 d, M | medium / high | engineer + owner |
| P1-10 | Store presentation pass | EX PL | 1 d, M | medium / medium | owner |
| P2-01 | Portal-derived content bars | FU SH | 3 d, M | high / medium | engineer |
| P2-02 | Solvability for every unit | FU SH | 3 d, M | high / high | engineer |
| P2-03 | Bot-exercised ads per target | FU SH | 3 d, M | high / high | engineer |
| P2-04 | Portal-report artifact and import | FU SH | 3 d, M | high / high | engineer |
| P2-05 | `wgf_live` performance-review step | FU SH | 5 d, H | high / medium | engineer |
| P2-06 | Accepted-baseline regression gate | EX FU SH | 3 d, M | high / medium | engineer |
| P2-07 | Confirm-before-routing for findings | FU SH | 2 d, M | medium / high | engineer |
| P2-08 | Level critic baseline at release tier; naive-play bot | FU SH GE | 4 d, M | medium / medium | engineer |
| P2-09 | Parametric level generators per family | FU GE | 5 d per family, H | high / medium | engineer + person |
| P2-10 | Calibrated budget model | FU SH | 2 d, M | medium / medium | engineer |
| P2-11 | Agent canary golden | FU SH | 3 d + spend, M | medium / medium | engineer + approval |
| P2-12 | Profile monetization fields and revenue terms as data | FU SH PL | 3 d, L | medium / high | engineer |
| P2-13 | Playgama evaluation | FU PL RS | 2 d, M | medium / low | person + engineer |
| P2-14 | Ad opportunity estimate in design | FU SH | 2 d, M | medium / medium | engineer |
| P2-15 | Reference example fixes in the template | FU SH | 1 d, L | low / high | engineer |
| P2-16 | Genre matrix as reference data (late) | FU GE | 2 d, H | low / low | engineer |
| P3-01 | Controlled experiments E1-E5 | EX | 3 d per test, M | medium / low | engineer + owner |
| P3-02 | Scoring model v2/v3 calibrated on outcomes | FU SH | 3 d, H | medium / low | engineer |
| P3-03 | Portfolio ledger and net contribution report | SH | 2 d, L | medium / medium | engineer |
| P3-04 | Automated post-release diagnosis | FU SH | 5 d, H | medium / low | engineer |
| P3-05 | Channel diversification (GameDistribution, Coolmath) | EX PL | 3 d per portal, M | medium / low | engineer + owner |

---

## Ad evidence states

An ad entry in a configuration file does not show that a build can earn. Each state below needs
its own evidence, and no state implies the next one.

| State | Meaning | Independent evidence | Produced by |
|---|---|---|---|
| A1 Declared | the profile offers the kind; `game.config.yaml` `ad_kinds` lists it | profile and config | data |
| A2 Placed | the shipped integration plan holds a placement of that kind for this target | the built `integration-plan` in the package | P0-03 |
| A3 Invoked (mock) | a bot on **this target's packaged build** reaches a beat and the portal SDK call is made, with the right type, pause scope and reward on completion | `window.__wgf__.usage()` `adsRequested` / `adsShown` plus the SDK mock's call log | P2-03 (P0-03 part b) |
| A4 Invoked (real SDK) | the same build, under the portal's real SDK or test tool, makes the calls | the portal QA tool (Y8 QA tab, CrazyGames QA tool, GamePix Testing Toolkit) | a person |
| A5 Approved | the portal approved the game for public play, out of review or Basic Launch | the portal console state | the portal |
| A6 Served live | real creatives (not test or house ads) appear on the public page | a person's observation, with `breakStatus` | P0-01 |
| A7 Monetized | the portal report shows impressions and revenue for the build's window | a portal-report record | P2-04 |

Today:
- BBW and SM on Y8 (Build 003) reach A3 against the mock. A4-A7 are not established.
- On GamePix, the builds fail A2 (`runs:fixes/bbw-gp/src/platform/integration-plan.ts:14,21`) and
  A4 (the toolkit shows the ad calls red).

## P0: visibility and confirmed blockers

### P0-01 Y8 report, metric definitions and live ad check

- **Problem.** The reported Y8 RPM ($0.02 / $0.38) has no known denominator, window or sample.
  Both games have been in review the whole time. Builds 001/002 made no ad calls. Build 003's ads
  were checked only against a mock ([factory-audit.md](factory-audit.md) §7).
- **Objective.** Know whether the number means anything, and confirm that real ads serve.
- **Files.** None (data); the record goes into the workspace as `observed` claims.
- **Dependencies.** Y8 approval of Build 003 for the live check.
- **Approach.**
  1. A person exports Y8 Revenue Report rows per game: plays, impressions, revenue, geo, dates.
  2. A person asks developers@y8.com what RPM divides by.
  3. After approval, a person plays each live page to a beat and to a fail, and records
     `showAd` `next` and `reward` with their `breakStatus`.
- **Acceptance.**
  - Denominator, window, stage and sample are recorded for both figures.
  - At least one `viewed` interstitial and one `viewed` rewarded per game on the live page.
- **Tests and CI.** None (manual protocol).
- **Risks and rollback.** If fill is empty, ask Y8; no game change.
- **Metrics.** Y8 impressions per play once live.
- **Authorization.** Live login; emailing Y8.

### P0-02 GamePix builds get ad placements

- **Problem.** `runs:fixes/bbw-gp/src/platform/integration-plan.ts:14,21` (and SM) omit
  `gamepix`. The real GamePix toolkit showed no ad calls.
- **Objective.** A GamePix submission can earn and avoids a "missing ads" rejection.
- **Files.** Game repos on the `gamepix/*` branches: `src/platform/integration-plan.ts`, new
  tests.
- **Dependencies.** None.
- **Approach.**
  - Mirror 185aae6 / d8c8c3a: add `gamepix` to both placements.
  - Check GamePix's audio-pause rule against the v1.2.2 adapter.
  - Add unit and e2e tests against a GamePix mock.
  - Rebuild, then re-run the GamePix toolkit.
- **Acceptance.** The toolkit shows `interstitialAd` and `rewardAd` green. Tests pass. Only the
  GamePix SDK is in the zip.
- **Tests and CI.** typecheck, lint, unit, e2e, the CrazyGames audit unchanged.
- **Risks and rollback.** Keep the previous package hash.
- **Metrics.** GamePix impressions after approval.
- **Authorization.** Re-upload and submit by the owner, with a human-written description.

### P0-03 Per-target ad hard gate

- **Problem.** `_declared_ads` (`scripts/wgf_verification/checks/platform.py:69`) derives the
  required kinds from the same placements that omitted y8. The check was circular, and the defect
  passed every gate.
- **Objective.** No build reaches a portal without a reachable ad.
- **Files.**
  - `scripts/wgf_verification/checks/platform.py`
  - `core/reference/check-tiers.yaml`
  - `core/reference/lessons.yaml` (a new lesson with `guarded_by`)
  - `docs/verification-module.md`
- **Dependencies.** Per-target builds in verify. P2-03 extends the gate with bot evidence.
- **Approach.**
  1. For each target whose **profile** `capabilities.ads` is non-empty, require a placement of an
     offered kind listing the target in the built plan.
  2. A design may exclude a target only by an explicit, recorded `placements[].platforms`
     choice.
  3. Register the check as a Hard Gate.
- **Acceptance.**
  - Fails on a fixture reproducing the Y8 plan.
  - Passes on the fixed plans.
  - `check-integrity.py` stays green.
- **Tests and CI.** Unit tests with both fixtures; `test-core --only VERIFY`; both goldens.
- **Risks and rollback.** Could block a deliberate exclusion; the explicit-exclusion path covers
  it. Revert = remove the tier entry.
- **Metrics.** Target builds with zero ad opportunities caught at verify.

### P0-04 Pause scope as profile data

> **As built (PR #88):** configuration, not a profile field - `factory.sdk.pause_inside_ad_callbacks:
> [y8]`, beside `break_on_continue`. See [p0-execution-plan.md](p0-execution-plan.md#execution-status-2026-10-22).

- **Problem.** `scripts/wgf_sdk/game/src/platform/gameplay.ts` pauses around the request. Y8
  requires the pause inside `beforeAd`/`afterAd`. A regeneration would undo the game fixes.
- **Objective.** Generated games follow each portal's pause rule.
- **Files.**
  - `core/reference/platforms/y8.yaml` and the other profiles
  - `scripts/check-integrity.py`
  - `scripts/wgf_sdk/integration.py`
  - `scripts/wgf_sdk/game/src/platform/gameplay.ts` and its tests
  - `scripts/wgf_sdk/e2e/smoke.spec.ts`
- **Dependencies.** None.
- **Approach.**
  - Add `ads.pause_scope: request | inside-callbacks` (default `request`; y8 `inside-callbacks`).
  - The plan writer emits `pauseInsideAdCallbacks`.
  - Port the d8c8c3a logic.
  - Add an e2e scenario where a spent rewarded offer hides.
- **Acceptance.**
  - Game-side tests cover capped, viewed and silent breaks.
  - Regenerating BBW's plan reproduces the hand edit.
- **Tests and CI.** `python -m unittest scripts/tests/test_sdk_integration.py`, game vitest,
  test-core, goldens.
- **Risks and rollback.** Other targets keep `request`.
- **Metrics.** None beyond tests.

### P0-05 Meter every agent session

- **Problem.** Only developer sessions record cost. Design, review, assets, visual QA and copy
  use text output (`workspace/config/profiles/autonomous.yaml:78-80,146-148`). Cost per game is
  an estimate.
- **Objective.** A real cost per stage and per game, which every portfolio decision needs.
- **Files.**
  - `workspace/config/profiles/autonomous.yaml`
  - the agent invocation sites in `scripts/wgf_design/agent.py`, `scripts/wgf_review/`,
    `scripts/wgf_assets/`, `scripts/wgf_visualqa/`, `scripts/wgf_listing/`
  - the `scripts/wgf_develop/budget.py` reader pattern
- **Dependencies.** None.
- **Approach.**
  - Switch each agent to `stream-json` output.
  - Read `total_cost_usd` as develop does.
  - Emit `STEP_LOG` cost events per step.
  - `wgf status --json` sums them per run.
- **Acceptance.** A fixture run reports cost for every agent step. A live run's sum is within 5%
  of the host's own total.
- **Tests and CI.** Unit tests with recorded stream-json transcripts.
- **Risks and rollback.** Output parsing differs per step; keep text parsing as a fallback.
- **Metrics.** Cost per stage per game.

### P0-06 Submissions only from the release path

> **As built (PR #87):** no standalone release command (it would skip G4/G5/G6). `registry show`
> reports a portal build that no release-manifest pins as UNGATED. See
> [p0-execution-plan.md](p0-execution-plan.md#execution-status-2026-10-22).

- **Problem.** What shipped was built by hand scripts and submitted outside G4/G5/G6 and the
  quality gate (`runs:release-prep-2026-10-18/`). One submission was by an unknown actor.
- **Objective.** Every upload is traceable to a gated release manifest.
- **Files.**
  - `scripts/wgf_release/`
  - a new `wgf release --platform <id>` path without a full run
  - `workspace/titles/<id>/portals.json`
  - `docs/release-module.md`
- **Dependencies.** P1-09 (one release line per game).
- **Approach.**
  - Package per platform from a named commit.
  - Write a release manifest.
  - Record the package hash in the title's portal registry.
  - G6 pins it.
- **Acceptance.** Re-producing the current Y8 Build 003 zip gives the same hash. The registry
  lists every live build.
- **Tests and CI.** Release tests; test-core RELEASE.
- **Risks and rollback.** The owner's manual submission stays possible; the record is the point.
- **Metrics.** Share of live builds with a manifest (target 100%).
- **Authorization.** The owner keeps submitting by hand in a live login.

### P0-07 Template ad and boot hangs; GamePix at the pin

> **As found:** both fixes are already on template `main` (`3bdd83d`, `231e50a`) but in no release.
> What remains is a template release and the pin move, which need approval. See
> [p0-execution-plan.md](p0-execution-plan.md#execution-status-2026-10-22).

- **Problem.** Three gaps in the template:
  - Yandex has no max duration after `onOpen`;
  - CrazyGames `sdk.init()` has no timeout;
  - GamePix has no adapter at v1.2.1.
- **Objective.** No frozen game or black boot screen; GamePix built from the pinned template.
- **Files.**
  - web-game-template `packages/platform-sdk/src/adapters/{yandex.ts,crazygames/platform.ts}`
  - Factory `workspace/config/template.lock.json`
- **Dependencies.** A template release.
- **Approach.**
  - Add the timers.
  - Release template 1.2.3 or later.
  - Move the pin with both goldens in one commit.
- **Acceptance.** New adapter tests for a lost close and a hung init. Goldens pass at the new pin.
- **Tests and CI.** Template CI; `WGF_GOLDEN=1 bin/wgf test-core --strict` on Linux.
- **Risks and rollback.** A pin move affects every run; follow the pin procedure.
- **Authorization.** Template push and tag.

## P1: high-impact game and production improvements

### P1-01 Content depth and mastery layer for BBW and SM

- **Problem.** All designed content is 854 s (BBW) and 345 s (SM). The CrazyGames benchmark is
  10+ min average playtime. Comparables have far more levels plus mastery or meta layers
  ([level-design-improvements.md](level-design-improvements.md) §2).
- **Objective.** Raise playtime per player toward the benchmark before CrazyGames' Basic Launch
  judgement.
- **Files.** Game repos: `public/content/units.json`, level data, save schema, result screens. The
  designs, through the Factory's design re-entry.
- **Dependencies.** P1-09 first (one release line), and P2-02 ideally (solvability).
- **Approach.**
  1. Stars (BBW) and par medals (SM) per unit, using existing saves.
  2. More units per group, through the content contract, toward 50+ (BBW) and 30+ (SM). Each
     unit is accepted by a person.
  3. Distinct climax art (G-01).
  4. No currency or shop.
- **Acceptance.**
  - Designed play time at least 2x the benchmark, as a hypothesis.
  - Every unit won by the bot.
  - Similarity checks pass.
  - A person accepts each new group.
- **Tests and CI.** Game unit and e2e; content sufficiency; playability.
- **Risks and rollback.** A resubmission resets review queues; time it with the portal states.
  Keep the previous build hash.
- **Metrics.** CrazyGames average playtime and conversion; Yandex playtime and D1 later.

### P1-02 CrazyGames Full Launch readiness

- **Problem.** Basic Launch has ads off. Full Launch depends on playtime, conversion past 1 minute
  and D1 against comparables. The load must stay under 10 s.
- **Objective.** BBW, then SM, reach Full Launch.
- **Files.** Game repos (first-minute flow, `happytime`, loading); store assets.
- **Dependencies.** BBW's review result; P1-01.
- **Approach.**
  - Measure time to first input locally and trim it to 5 s or less.
  - Call `happytime` only on world or course clear.
  - Check `gameplayStart/Stop` brackets.
  - Finish the Details assets.
- **Acceptance.** The QA tool detects all SDK events. Local first input is 5 s or less. Basic
  Launch metrics are recorded through P2-04.
- **Tests and CI.** Game e2e; CrazyGames audit.
- **Risks.** The thresholds are relative and unpublished.
- **Metrics.** Conversion, average playtime, D1, stage reached.
- **Authorization.** Owner uploads and attestations.

### P1-03 Yandex readiness while paused

- **Problem.** New-game submissions are paused. The drafts lack RU screenshots. Yandex ranking
  uses card completeness, and "Popular" needs RU+EN and promo materials.
- **Approach.** Complete RU screenshots, promo images, hero image and maskable icon; keep the
  drafts on the fixed builds; watch for reopening.
- **Acceptance.** Card complete per the console.
- **Effort.** 1 d, L.
- **Authorization.** Owner.

### P1-04 Browser QA additions

- **Problem.** D1 (landscape phone clipping) and D2 (one failed asset kills boot) escaped.
- **Files.** `core/reference/browser-qa.yaml`, `scripts/wgf_verification/` browser spec,
  [docs/verification-module.md](../verification-module.md).
- **Approach.** Add 844x390 and 640x360 viewports, a text-fits-control check, same-origin fault
  injection with recovery expected, and throttled load.
- **Acceptance.** Reproduces D1 and D2 on the pre-fix commits (9374549^ / 39e7ad5^); passes after.
- **Tests and CI.** Unit fixtures; test-core VERIFY; goldens.
- **Metrics.** Post-release UI defects per title.

### P1-05 Teardown corpus for the next concept

- **Problem.** 0 teardowns. Snapshots are 28 days old.
- **Approach.**
  - Refresh snapshots.
  - Tear down at least 10 games in each of 3 candidate families, with `scripts/wgf-corpus.py`.
  - Validate with `wgf-corpus.py validate`.
- **Acceptance.** `bin/wgf research` produces opportunities with convention prevalence above the
  bar, from observed claims.
- **Effort.** People's time, no paid calls.
- **Metrics.** Evidence coverage of the next opportunity, at least 0.60.

### P1-06 G1 inside the workflow

- **Problem.** G1 is defined but absent from `new-game`. opp-001 was promoted below its coverage
  floor.
- **Files.**
  - `core/workflows/new-game.workflow.yaml`
  - a scoring step module or a checkpoint emitting `evaluation` and `decision-record`
  - `scripts/wgflib/workflow/decisions.py`
- **Approach.** Add a checkpoint after research that scores with the model and refuses promotion
  below coverage or on a veto.
- **Acceptance.**
  - A fixture opportunity at 0.246 coverage is refused.
  - A valid one passes.
  - `check-integrity.py` stays green.
- **Tests and CI.** Workflow tests; test-core WORKFLOW; goldens.
- **Risks.** An extra human checkpoint; G1 may auto-approve on timeout by design.

### P1-07 Measured kill metrics at G4

- **Problem.** Kill metrics are "NOT MEASURED" (`scripts/wgf_develop/report.py:181-188`).
- **Approach.**
  - Run the stranger playtest ([docs/mv-4-playtest-protocol.md](../mv-4-playtest-protocol.md)) at
    G4, with at least 5 players.
  - Record `first_time_understood_share`, `unprompted_retry_share` and median session into the
    prototype report.
  - A G4 pass without them needs a recorded override.
- **Acceptance.** The G4 decision record cites measured values.
- **Effort.** 2 d engineering plus people's time.
- **Metrics.** Correlation of G4 metrics with later portal playtime (after 5 titles).

### P1-08 Differentiation field and rule

- **Problem.** There is no USP field. Y8 and Poki reject unoriginal and reskinned games.
- **Files.** `core/artifacts/title-strategy.schema.json`, `scripts/wgf_strategy/planner.py`,
  `core/reference/design-consistency-rules.yaml`.
- **Approach.** Add `differentiation {axis, versus[], evidence}`. A blocking rule requires that a
  design mechanic realizes the axis. A `reskin_risk` warning compares with earlier own titles.
- **Acceptance.** Fixture tests; ajv validation of the worked example.

### P1-09 Reconcile the game repositories with the Factory

- **Problem.** Fixes sit on several local branches (`y8-ads`, `gamepix/*`, `release-prep/*`).
  The plans are hand-edited, and the workspace has no record of the releases.
- **Approach.**
  - After P0-04, re-run the sdk step on each design; it must reproduce the edits.
  - Merge into one release line per game.
  - Record `portals.json`.
- **Acceptance.** The diff against the hand-edited plan is empty apart from the header. Every live
  hash maps to a commit.
- **Authorization.** Pushing game repos.

### P1-10 Store presentation pass

- **Problem.** Y8 picks one standard screenshot as the thumbnail at approval. GamePix's dashboard
  requires a human-written description. The thumbnail drives clicks on every portal (Poki's Web
  Fit Test scores CTR).
- **Approach.**
  - Order screenshots so the strongest gameplay frame comes first. Y8 locks media during review,
    so do it before the next upload.
  - The owner writes the GamePix description.
  - Check covers against each profile's `store_listing` block ([docs/store-listing-module.md](../store-listing-module.md)).
- **Acceptance.** Listing validation shows no FAIL; UNKNOWN items are named.
- **Authorization.** Owner.

## P2: reusable factory capabilities

| ID | Problem and evidence | Approach | Files | Acceptance | Tests |
|---|---|---|---|---|---|
| P2-01 | Release bar of 300 s is from own games; CrazyGames publishes 10+ min average as its successful-title benchmark | Content bar as a function of the strictest target profile (designed play time at least 2x the benchmark, hypothesis); profile field for benchmarks | `core/reference/quality-benchmark.yaml`, profiles, `scripts/wgf_design/content.py`, `scripts/wgf_sufficiency/audit.py` | Fixture designs below the bar warn at design and fail at release tier | unit, test-core QUALITY, goldens |
| P2-02 | Solvability proven for 3-4 units only (`wgf_playability/analysis.py:499-545`) | Bot must win every unit through the survey link, within a time bound; authored solution traces where the bot cannot play | `scripts/wgf_playability/`, `scripts/wgf_sufficiency/` | An unwinnable fixture unit blocks; the goldens' units all pass | unit, goldens |
| P2-03 | Ads never exercised by the bot | One interstitial and one rewarded per target build against the mock; assert beat, pause scope, reward on completion, spent offer hidden | `scripts/wgf_playability/`, SDK mocks in the template | Reproduces the four ad defects on fixtures | unit, browser fixtures |
| P2-04 | Nothing imports portal data | `core/artifacts/portal-report.schema.json` (`x-wgf`), `core/reference/monetization-metrics.yaml`, stdlib `scripts/wgf-portal-report.py import|summary` | as named; `adapter-binding.yaml`; regenerate adapters | Recorded export reproduces totals; ajv validates | unit with fixture exports |
| P2-05 | `title:live` is paper only | `wgf_live` step module drafts day 1/7/30 reviews from portal-report records; proposes a decision; never decides G7 | new `scripts/wgf_live/`, `workspace/config/factory.yaml` modules | Fixture reports produce a valid review; `below_sunset_floor` reads it | unit, test-core WORKFLOW |
| P2-06 | Gates pass while games get worse (K6) | Compare candidate against the accepted build: content counts, course lengths, pairwise visual judgement (promote #77 at release tier) | `scripts/wgf_quality/`, baseline comparison | The K6 regression fixture is caught | unit, golden loop |
| P2-07 | False positives drive paid repairs (L5, L7) | A finding routes only after a second independent measurement; timing checks report intervals | `scripts/wgf_triage/`, playability analysis | Noise fixtures no longer route | unit |
| P2-08 | Level critic off; perfect-play bot only | Critic `baseline` mode as Quality Gate at release tier; second bot policy with human-like error for a fail curve | `workspace/config/factory.yaml`, `core/reference/check-tiers.yaml`, `scripts/wgf_leveldesign/`, `scripts/wgf_playability/` | Spike and trivial-unit fixtures flagged | unit |
| P2-09 | Content was added by people | Parametric generators per family in the game repo, checked by existing rules plus P2-02; human acceptance per group | template genre modules; design `generation.mode: parametric` | Generated units pass similarity, pacing, solvability; a person accepts | game tests, sufficiency |
| P2-10 | Budget model a guess; both runs exceeded it | Fit `session_task_hours` and `rework_sessions` from metered runs (needs P0-05) | `core/reference/quality-benchmark.yaml`, `scripts/wgf_techplan/budget.py` | Predicted versus actual within 25% on the next 2 runs | unit |
| P2-11 | CI never tests real prompts | Opt-in, capped, weekly agent canary on a fixed tiny concept | `.github/workflows/` (manual dispatch), `scripts/golden/` | Canary result compared with the previous canary | the canary itself |
| P2-12 | Profiles lack pause scope, launch-stage gating and revenue terms | `ads.{pause_scope, launch_stage_ads, rewarded_cap_s, preroll}` and `revenue_terms {share, basis, payout, metric, source, read_on}` | `core/reference/platforms/*.yaml`, `core/reference/publication/*.yaml`, `scripts/check-integrity.py` | Integrity validates every field with source and date | integrity |
| P2-13 | Playgama could multiply reach (MSN, YouTube Playables) | Read terms and the Bridge SDK; decide whether a template adapter is worth it | research note; possible template adapter | A recorded go/no-go | - |
| P2-14 | Rule prose mentions an "eCPM assumption" but nothing computes ad opportunities | Derived `ad_opportunities_per_session` from `session.target_seconds`, `build_spec.session_flow` beats and the tightest profile interval; warn below 1 on any target; never a revenue projection | `scripts/wgf_design/consistency.py`, `core/reference/design-consistency-rules.yaml` | Fixture designs produce the expected estimate | unit |
| P2-15 | Template examples hard-code `generic-web`; Tower Merge Rush "Double score" is repeatable; no `adAvailability` check; example e2e and `test:sdk:matrix` not in CI | Read the platform from `game.config.yaml`; once-per-run reward; availability check; add suites to CI | web-game-template `examples/*`, `.github/workflows/` | Example tests cover a granted reward | template CI |
| P2-16 | The genre format matrix is judgement, not data | Move [monetization-and-distribution.md](monetization-and-distribution.md) C2 into `core/reference/genre-monetization.yaml`, read by design as defaults, only after P3-01 validates the arcade and platformer rows | `core/reference/`, `scripts/wgf_design/` | Integrity validates; design reads defaults | unit |

Each P2 item:
- **Dependencies.** P2-03 needs P0-03; P2-05 needs P2-04; P2-10 needs P0-05; P2-09 needs P2-02.
- **Risks.** Core changes follow the Core v1 process; revert by module.
- **Metrics.**
  - defect escapes per title;
  - paid sessions per title;
  - designed play time against the benchmark;
  - cost per title.

## P3: advanced optimization

| ID | What | Depends on | Acceptance | Metric |
|---|---|---|---|---|
| P3-01 | Experiments E1-E5 ([analytics-and-feedback-loops.md](analytics-and-feedback-loops.md)): near-win rewarded offer, later first interstitial, shorter onboarding, stars, a second rewarded use | P2-04, titles in Full Launch | protocol followed; a decision recorded with guardrails | impressions per play, conversion, D1 |
| P3-02 | Scoring v2 (new file) with portal-benchmark feasibility, content cost per minute, reskin veto; v3 calibrated on outcomes | P1-05, at least 5 titles with outcomes | weights justified by data or left unchanged | rank correlation of score with playtime |
| P3-03 | Portfolio ledger: cost per title (metered) and net revenue per portal | P0-05, P2-04 | a monthly report | net contribution per title |
| P3-04 | Post-release diagnosis: portal status polling (`wgf publish --track`), rejection reasons as findings, error reports where permitted | P2-04, P2-05 | a rejection reason becomes a routed finding | time from rejection to fix |
| P3-05 | GameDistribution, then Coolmath for a logic title | titles in Full Launch elsewhere | approval on each | revenue share by portal |

## Critical path

```
P0-01 ─────────────────────────────────────────────┐ (data)
P0-02 ──> GamePix submission                       │
P0-04 ──> P1-09 ──> P0-06                          │
P0-03 ──> P2-03                                    │
P0-05 ──> P2-10, P3-03                             │
P1-09 ──> P1-01 ──> P1-02 (CrazyGames Full Launch) ┴──> P2-04 ──> P2-05 ──> P3-01, P3-02
P1-05 ──> P1-06 ──> next concept (only after P1-02 has a result)
```

## Increments

| Milestone | Contents | Exit criterion |
|---|---|---|
| **M1: see and stop the bleeding** | P0-01 .. P0-07 | Real ads observed on Y8; GamePix packages carry placements; the per-target ad gate and pause scope merged; every agent metered; live builds traceable to manifests |
| **M2: make the two games worth distributing** | P1-01, P1-02, P1-03, P1-04, P1-09 | BBW through CrazyGames Basic Launch with measured playtime; SM queued; Yandex cards complete |
| **M3: choose the next game on evidence** | P1-05, P1-06, P1-07, P1-08 | A concept chosen at G1 from at least 30 teardowns, with a differentiation axis and measured kill metrics at G4 |
| **M4: a factory that meets portal bars** | P2-01 .. P2-12 | The next title meets the content bar, solvability, bot-exercised ads and the accepted-baseline gate, with metered cost |
| **M5: learn and optimize** | P2-13, P3-* | Portal data drives performance reviews, experiments and scoring calibration |

**First milestone dependencies (M1):**
- the owner's portal logins (P0-01, P0-02);
- Y8's approval of Build 003;
- a template release for P0-07;
- Core v1 module validation for P0-03, P0-04, P0-05 and P0-06.

## Do not build yet

| Item | Reason | Revisit when |
|---|---|---|
| Shops, soft currencies, IAP | cost and balance; no evidence our genres need them | a title in Full Launch shows long sessions and returning players |
| Login rewards, streaks | pressure patterns; no D1 data | Yandex D1 data exists |
| Leaderboards, achievements | no template interface; low value without traffic | a title has steady traffic |
| In-game third-party analytics | banned on GamePix and GameDistribution | never inside portal builds |
| Telegram, Discord, Facebook Instant | weak fit | evidence of ad-funded casual success there |
| Poki | exclusive; deferred by the user | a deliberate exclusive title |
| More titles in parallel | cost unmetered; no title has cleared Full Launch | M2 and M1 are done |
| An AI "fun" judge | no predictive evidence; adds spend | never as sole evidence |
| A rewrite of the Platform interface | it works; gaps are targeted | - |

## What needs a person's authorization

| Action | Initiatives |
|---|---|
| Logging in to a portal; exporting reports; live ad checks | P0-01, P1-02, P1-03 |
| Emailing a portal | P0-01 |
| Uploading, submitting, attesting, writing store copy | P0-02, P0-06, P1-01, P1-02, P1-03, P1-10, P3-01, P3-05 |
| Pushing game repositories or the template; tagging a release | P0-07, P1-09, P2-15 |
| Core changes (Core v1 frozen; one module at a time) | P0-03, P0-04, P0-05, P0-06, P1-04, P1-06, P1-07, P1-08, P2-01 .. P2-14, P2-16 |
| Paid agent spend | P2-11 (canary); P1-01 if done through Factory runs |
| Stranger playtests (people's time) | P1-07 |
