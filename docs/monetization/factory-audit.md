# Factory audit: the end-to-end workflow (2026-10-21)

What each stage of WebGameFactory actually does, traced through code and through the record of
the two validation games, Brick Breaker Worlds (BBW, 2D) and Sky Marble (SM, 3D). This document
keeps a documented intention apart from a working capability. It is the evidence base of
[implementation-roadmap.md](implementation-roadmap.md).

Labels:
- **[C]** confirmed by reading the code or the record.
- **[I]** inferred without running anything.
- **[U]** unknown.

Sources:
- this repository at `main` 6d458a2 (Factory 2.8.2);
- the pinned template v1.2.1 `4b74b08` (paths marked `template:`);
- the run notes and game repositories under `C:/Users/duycu/wgf-runs/` (paths marked `runs:`);
- [docs/benchmark/2026-10-baseline.md](../benchmark/2026-10-baseline.md);
- [docs/quality-gap-audit-2026-10.md](../quality-gap-audit-2026-10.md).

No test or run was executed for this audit.

## 1. Summary

The Factory's **machinery is mature**:
- every stage has a module, schema-checked artifacts, data-driven rules and unit tests;
- CI runs 129 test files (about 4,900 tests) in about 55 minutes.

Its **inputs and its outputs are not**:

1. **Research does not choose what gets built.** The teardown corpus is empty, the snapshots are
   one date old, G1 is not in the workflow, and both validation games came from hand-written
   briefs.
2. **People made the games commercially presentable.** Content, level design and polish were
   added outside the workflow:
   - BBW went from 12 to 32 levels;
   - SM went from 6 corridors to 12 authored courses.
   A later automated loop "made gates pass and games worse", catching 0 of 11 human findings.
3. **Content depth is far below what portals reward.** All of BBW's designed content is 854 s of
   play, and SM's is 345 s. CrazyGames publishes 10+ minutes average playtime as what successful
   titles often see: a benchmark, not a threshold. Poki's final review targets 5+ minutes. The
   Factory's release bar is 300 s. Designed content is not measured playtime; only portal data
   shows what players actually do.
4. **What shipped bypassed the release gates.** Both games were packaged and submitted by hand,
   outside G4/G5/G6 and the quality gate. The Y8 builds requested no ads at all.
5. **Nothing measures a game after launch, and most spend is unmetered.** Post-launch maturity is
   0. Only developer sessions record cost.

## 2. Stage matrix

Maturity scale:
- **0**: documented only.
- **1**: code exists, unproven on a real game.
- **2**: runs on real games, but misses real defects or wastes money.
- **3**: reliable.

"Code" and "evidence" maturity are scored separately: a stage can be well engineered and still
run on empty data.

| # | Stage | Module (key symbols) | Artifacts and gates | Code | Evidence | Main weakness | Business consequence |
|---|---|---|---|---|---|---|---|
| 1 | Market research | `scripts/wgf_discovery/` (`ResearchStep.execute` step.py:211; `analyse_market` market.py:52; generators opportunities.py:682-990) | research-report, opportunity; claim tiers enforced (`ClaimBook.rests_on_observation` analysis.py:308) | 3 | **0** | 0 teardowns (`workspace/research/games/` absent); 22 snapshots, all `observed_at` 2026-09-23 (stale ~2026-11-07 at `evidence_ttl_days` 45); `LiveCollector` off (step.py:159), no `probes.yaml` [C] | Concepts are chosen by people, not by market evidence |
| 2 | Opportunity selection (G1) | scoring `core/reference/scoring/portfolio-default.v1.yaml`; agent procedure `/wgf-score` | evaluation; G1 `gates.yaml:44-61` | 1 | 0 | **G1 is not in `new-game`** (`new-game.workflow.yaml:205-216`); no step writes an evaluation; opp-001 promoted at coverage 0.246 below the 0.60 floor (`docs/research-v2.md:315-320`); weights "a starting point, not a finding" [C] | No evidence-based go/no-go before spend |
| 3 | Strategy (G2) | `scripts/wgf_strategy/planner.py` (`plan_strategy` :1492) | title-strategy; G2 `kill_criteria_defined` (non-empty only) | 3 | 1 | Kill and success criteria are fixed templates (planner.py:1243-1280); `why_this_opportunity` is a string template (:1379); no differentiation field [C] | Kill gate cannot kill on evidence |
| 4 | Design (G3) | `scripts/wgf_design/` (authors.py; consistency, content.py:84-150, experience.py, depth.py) | game-design (rich `build_spec`), ~14 blocking + ~13 warning rules; knowledge-contract | 3 | 1 | Default author = 6 archetype templates; the agent author (opt-in, ~$8/round, 3 repairs) is needed for release tier (`workspace/config/factory.yaml:868-876`); no USP field; no fun critic; blocking breach routes `descope`, which ends the run [C] | Designs are structurally valid and commercially generic |
| 5 | Level design and content | `core/reference/genre-models.yaml` (8 families); `scripts/wgf_sufficiency/audit.py` (16 checks); `scripts/wgf_leveldesign/` | content-sufficiency; level critic | 2 | 1 | Solvability proven only for units 1..`min_units_traversed` (3-4) (`wgf_playability/analysis.py:499-545`); reachability = "entered" via `?wgf-unit=` (audit.py:727-745); level critic `judge.kind: none`, advisory (`factory.yaml:776-783`); no generator; bars rest on 2 own games (`quality-benchmark.yaml`) [C] | Content quality was supplied by people |
| 6 | Assets, art, audio | `scripts/wgf_assets/` (pipeline.py); Blender 4.5 model specs; synthesized audio | asset-manifest; `asset-quality.yaml` heuristics | 2 | 2 | No paid generation (agent-drawn SVG, $6/session; model spec $3; audio synthesized) [C]; craft judge off (`profiles/autonomous.yaml:240-246`); silhouette rule turned a marble into a drum, then a placeholder; re-entry renamed model nodes and broke boot (runs:LEAD-STATE.md:35,39) [C] | Low cost, low ceiling; a person still rejects art |
| 7 | Implementation | `scripts/wgf_develop/` (developers.py:43-150; brief.py 2,247 lines; guard step.py:36-47) | development commits; review-report | 2 | 2 | `claude -p --model sonnet --max-budget-usd 40`, 400 turns; develop visits up to 71, triage 128 (`new-game.workflow.yaml:388,445`); wasted iterations (section 4) [C] | Budget overruns; every real run needed a raise |
| 8 | QA: playability, production, visual, verify | `wgf_playability` (6.8k lines), `wgf_production`, `wgf_visualqa`, `wgf_verification` (`browser-qa.yaml`, 31 checks) | playability / production / visual-qa / verification reports | 2 | 1 | No landscape phone viewport (`browser-qa.yaml:47-51`); clipping = viewport edge only (:288-293); no fault injection or throttling (`browser_qa.spec.ts:394`); bot never exercises ads; absolute VQA rubric cannot see regressions; evidence PASS_MOCK [C] | Defects found by portals and people (section 3) |
| 9 | Quality gate (G4 input) | `scripts/wgf_quality/` | quality-report | 2 | 1 | Aggregates reports faithfully, but K6: "0 of 11 human findings caught" (runs:TEAM-STATUS.md:241-243); not run for the shipped builds [C] | High confidence, low validity |
| 10 | Monetization integration | `scripts/wgf_sdk/` (integration.py `_cover_targets` :250); template `packages/platform-sdk` | sdk-report; `checks/platform.py` `_declared_ads` :69 | 2 | 1 | Y8 builds made zero `showAd` calls; the check derives required kinds from the same placements, so it was circular [C]; pause-inside-callbacks not ported; GamePix builds same defect (section 7) | No ad revenue possible from the shipped Y8 builds |
| 11 | Packaging and compliance | `scripts/wgf_release/package.py`; platform-validate guards | release-manifest; platform-publication | 1 | 1 | Real packages built by hand scripts (`runs:release-prep-2026-10-18/build_platforms.py`, `package_platforms.py`) [C] | Gate evidence not attached to what shipped |
| 12 | Store listing, submission | `scripts/wgf_listing/` (5.2k lines); `scripts/wgf_publish/` (adapters 1,894 lines) | store-listing; G5/G6 | 1 | 1 | Every publication profile `unverified`; every adapter FIXTURE_VALIDATED (`wgf_publish/adapters/y8.py:5-7`); real submission by a CDP Playwright session plus the owner (runs:release-prep-2026-10-18/portal-records.md:1-5); store assets made by hand; SM submitted to Y8 by an unknown actor [C] | Unreproducible releases; one unattributed submission |
| 13 | Post-launch and learning | `title:live`, `performance-review.schema.json`, guards (`wgflib/guards.py:557-600`); `scripts/wgf_knowledge/` | performance-review; lessons | 0 (live) / 3 (lessons code) | 0 | No `wgf_live` step, no portal-report import [C]; 29 hand-written lessons, `workspace/lessons/candidates.yaml` empty [C]; nothing feeds research or scoring | The factory cannot learn which games earn |

## 3. Defect escapes

Every one of these passed every gate that ran on its build.

| Defect | Found by | Gate that should have caught it | Why it escaped | Label |
|---|---|---|---|---|
| Y8 Builds 001/002 made zero `showAd` calls; Y8 rejected one game as "missing ads" | Y8 admin | sdk / verify platform | `_declared_ads` reads the same placements that omitted y8 | [C] |
| GamePix builds have no ad calls | GamePix toolkit | none: GamePix was never a Factory target | same placement filter | [C] |
| Pause and mute around the request instead of inside `beforeAd`/`afterAd` | fix agent | sdk-review | no per-portal callback contract test | [C] |
| Spent rewarded button stays visible after a dismissed ad (all portals) | new e2e test | playability / verify | the bot never exercises ads | [C] |
| D1: SOUND label clipped at 844x390 and 640x360 | manual QA | verify `browser.clipping` | no landscape phone viewport; clipping measured at the viewport edge only | [C] |
| D2: one failed asset request leaves boot dead, with an English message | manual QA | verify `loads` | no transient-failure injection | [C] |
| r1 ball drawn ~42 px over a 22 px collider; passed G4 | person | production / playability | no render-vs-physics check at the time (since added, WS-2) | [C] |
| Invisible walls, fake ceilings (gate-gaming) | person | review | no gaming precheck at the time (now `wgf_review/gaming.py`) | [C] |
| Iterated builds worse than the accepted r1 | person (K6) | quality gate / VQA | absolute floors only; pairwise baseline judge advisory (#77) | [C] |
| "A demo, not a game": 12 levels, one brick type (BBW); straight corridors (SM) | person audit | content-sufficiency / level critic | bars and critic did not exist or were advisory | [C] |

## 4. Where money and iterations are wasted

Evidence: `runs:LEAD-STATE.md`, `runs:TEAM-STATUS.md`, `runs:budget-ledger.md`, lessons L5-L13.

1. **False-positive gates driving paid repairs.**
   - Units-reachable timing (L5).
   - Host stalls (L7).
   - `depth.ramp` judge noise of 14 vs 15 actions, whose "repair" broke progression (LEAD-STATE:152-160).
2. **Gate-gaming by specialists.** Undrawn ceilings; enlarged sprites over small hitboxes (L10).
3. **Factory defects found mid-run, then resumed.** About 33 in one day (LEAD-STATE:16-50).
4. **Rework of accepted builds.**
   - Fresh runs changed 21 files (+5903/-3850) against the accepted build (runs:release-prep-2026-10-18/progress-log.md:24).
   - Greybox re-entry deleted 12,168 lines of shipped content in 2D (LEAD-STATE:136).
5. **Design wording loops.** Pacing and lexicon rules failed the design repeatedly (TEAM-STATUS:91,128).
6. **Environment and template faults paid for by developer sessions.** A stale template test, port collisions, refused shell commands (LEAD-STATE:26-33).

## 5. Cost visibility

| Item | Value | Label |
|---|---|---|
| Developer spend, first runs | BBW 18 sessions **US$62.86**; SM 9 sessions **US$29.25** | [C] baseline §6 |
| Developer spend, Oct 5 loop | BBW US$64.01; SM US$64.60 | [C] budget-ledger:31-35 |
| Estimated all-in per game through the Oct 5 loop | ~US$250-320 | [I] budget-ledger:37-41 |
| Metering | only `developer-session` / `developer-cost` (`wgf_develop/budget.py:26-37`); design, review, asset, VQA and copy sessions run `--output-format text` and record nothing | [C] |
| Agent processes per game | 139 (BBW), 224 (SM), mostly assets | [C] baseline §6 |
| Human hours | not recorded | [U] |
| A paid comparison run | ~US$300 | [C] runs:k7-decision-report-2026-10-12.md:45 |

Detail and scenarios: [portfolio-economics.md](portfolio-economics.md).

## 6. CI and test reality

- `.github/workflows/acceptance.yml` runs these jobs, about 55 min wall clock in parallel [C]:
  - checks;
  - units (4 shards);
  - core;
  - golden 2D/3D (150 min each);
  - an opt-in golden loop.
- **Goldens cost $0 and use no AI** [C]:
  - a replay developer ports the template examples (`scripts/golden/replay_developer.py`);
  - a pixel-baseline judge replaces visual QA.

  So CI never regression-tests a real agent, a real prompt or a real portal.
- Goldens cannot run on Windows (pnpm `.cmd` shim), and there is a standing Windows environment
  failure baseline of 78-79 tests [C].

Detail: [qa-and-ci-improvements.md](qa-and-ci-improvements.md).

## 7. The monetization path

The rest of this document is the monetization audit made earlier on 2026-10-21. It traces the ad
path from design to portal, and records the reported Y8 RPM and why it is not yet a signal.

Each finding below is classed as one of:
- **defect**: an implementation defect;
- **data**: missing data;
- **design**: weak game design;
- **distribution**;
- **platform**: a commercial or policy limit of a portal.

### 7.1 The reported numbers

| Item | Finding | Label | Class |
|---|---|---|---|
| Source | The user reports RPM of ~$0.02 and ~$0.38 over 30 days, read from the **Y8** developer dashboard, for two games. Raw rows (plays, impressions, revenue, geo, dates) were not available. | [C] user statement; rows [U] | data |
| The games | Brick Breaker Worlds (Y8 Game ID 288357) and Sky Marble (Y8 Game ID 288371). Source: `runs:release-prep-2026-10-18/portal-records.md` | [C] | - |
| Portal state | As of 2026-10-21, **neither game is approved or live on any portal**. Y8: both "In review", Build 003 resubmitted 2026-10-21. CrazyGames: BBW "Awaiting review"; SM blocked by CrazyGames's one-game-in-review rule. Yandex: "Submissions for new games are temporarily paused". GamePix: records created, not submitted. | [C] | distribution |
| Ads during review | Y8 serves Google test creatives while a game is in review (`core/reference/platforms/y8.yaml`, `review.process` comment; docs.y8.com/sdk/advertising). A Y8 staff reply says there is no revenue until ads are live (forum.y8.com/t/how-developers-earn-money-with-id-net/3449). | [C] docs; serving [U] | platform |
| Metric definition | Y8 does not publish what its Revenue Report's metrics divide by. The denominator - plays, page views or impressions - is unknown. | [U] | data |
| Sample | The Y8 records were created 2026-10-18/19, so a "30-day" window holds at most ~3 days of the games' existence, with no public catalogue traffic. | [I] | data |

**Conclusion.** The two figures are not yet evidence about the games' monetization. They are
consistent with three causes:
- no in-game ad requests at all in the builds under review (§7.2);
- test creatives during review;
- a tiny, non-public sample.

A real RPM exists only after approval, with Build 003, over a window of public traffic.

### 7.2 The ad path, traced

The path runs:
1. design `monetization.placements`;
2. the `sdk` step writes `src/platform/integration-plan.ts`;
3. `PlatformGameplay` (game) asks the plan for a placement at a moment;
4. the template adapter calls the portal SDK;
5. build and package per platform;
6. portal.

#### Defects in the shipped games

| # | Finding | Evidence | Label | Class | Impact |
|---|---|---|---|---|---|
| G1 | **Y8 Builds 001/002 of both games made zero `showAd` calls.** `integration-plan.ts` limited both placements (`rewarded-continue`, `interstitial-between`) to `["crazygames","yandex","poki"]`; `PlatformGameplay.#placement` filters by target, so on Y8 `canOfferReward` was false and `naturalBreak("level-complete")` did nothing. Y8's admin rejected one game as "missing ads". | `runs:fixes/bbw-y8ads-REPORT.md`, `runs:fixes/sm-y8ads-REPORT.md` | [C] | defect | No ad revenue possible on Y8 from those builds; a rejection. |
| G2 | Fixed locally: BBW 185aae6, SM d8c8c3a add `y8` to both placements and pause only inside `beforeAd`..`afterAd`. Uploaded as Build 003, review requested 2026-10-21. Nothing pushed or merged. Verified against the repo's Y8 SDK mock only. | same reports; `portal-records.md` last section | [C] mock; live [U] | defect (fixed, unverified live) | Revenue on Y8 depends on approval and real fill. |
| G3 | **The GamePix builds have the same defect.** `runs:fixes/bbw-gp/src/platform/integration-plan.ts:14,21` lists `["crazygames","yandex","poki"]` for both placements; the GamePix record holds a "Build ready" package from that branch. The real GamePix Testing Toolkit showed `interstitialAd` and `rewardAd` red (not called). | file; `portal-records.md` "Update 2026-10-21 GamePix" | [C] | defect | A GamePix submission today would earn nothing from in-game ads. |
| G4 | After a rewarded ad that gave no reward, the Extra Ball button stayed visible and did nothing until the screen changed. Affects every platform. Fixed in BBW 185aae6. | bbw-y8ads-REPORT, item 3 | [C] | defect | CrazyGames lists "rewarded buttons without effect" as a rejection cause (`template:packages/platform-sdk/src/types.ts:56-59`). |
| G5 | The integration plans were hand-edited after generation; the game repos and the Factory have diverged. | both reports | [C] | defect (process) | A regeneration loses or re-breaks fixes (F2). |

#### Factory

| # | Finding | Evidence | Label | Class |
|---|---|---|---|---|
| F1 | `_cover_targets` gives a placement every later-added target whose profile offers its kind, so the G1 class is closed for **new** plans. | `scripts/wgf_sdk/integration.py:250-285` | [C] | defect (fixed for new runs) |
| F2 | The Factory's gameplay layer has no pause-inside-ad-callbacks mode (`breakOnContinue` exists, `pauseOnAdStart` does not). A regenerated Y8 build would pause and mute around the request again. | `scripts/wgf_sdk/game/src/platform/gameplay.ts:64,271,320,359`; `integration.py:182-187` | [C] | defect |
| F3 | **No check verifies that each packaged target can reach an ad.** `_declared_ads` reads the design's own kinds. | `scripts/wgf_verification/checks/platform.py:36,69` | [C] | defect (gate gap) |
| F4 | No runtime check counts ads per session or measures cadence. `quality-floor.yaml`, `check-tiers.yaml` and `quality-benchmark.yaml` have no ad dimension. WS-11 platform behaviour checks are not implemented. | `docs/quality-gap-audit-2026-10.md:180,238` | [C] | defect (gate gap) |
| F5 | Design captures monetization well: placements with player value, `monetization_touchpoints` (cooldown, when unavailable), `sdk_touchpoints`, and blocking rules (`rewarded_ads_need_reward_moments`, `interstitial_interval_fits_session`, `monetization_supported_by_platform`). | `core/artifacts/game-design.schema.json:208-235,959-999`; `core/reference/design-consistency-rules.yaml:51-106` | [C] | - |
| F6 | Rule prose mentions an "eCPM assumption", but nothing computes ad opportunities per session. | `design-consistency-rules.yaml:60,80` | [C] | design |
| F7 | Profiles carry ad formats and one cadence number. They carry no pause scope, rewarded cap, preroll policy, launch-stage gating, revenue share, payout or metric definition. Revenue terms exist only as prose in `core/reference/publication/*.yaml`. | `core/reference/platforms/*.yaml` | [C] | data |
| F8 | Post-launch is specified, not implemented: `title:live`, `performance-review.schema.json` (free-form metrics), and the guards exist; there is no `wgf_live` step and no report import. | `core/lifecycle/title.machine.yaml:300-339`; `scripts/wgflib/guards.py:557-600` | [C] | data |
| F9 | Discovery never estimates revenue, so `revenue_potential` is always a hypothesis. | `scripts/wgf_discovery/analysis.py:17,853` | [C] | data |
| F10 | Analytics is "not required" wherever the adapter reports `platform-provided`. The develop seam wires a `NullSink`. | `scripts/wgf_sdk/integration.py:480`; `scripts/wgf_develop/seam/src/platform/integration.ts:11-13,62` | [C] | data (by design) |
| F11 | Game code outside `src/platform/` may not call ad methods directly, which is a good structural guard. | `scripts/wgf_develop/checks.py:430` | [C] | - |
| F12 | No title besides the worked example `neon-drift` is in `workspace/titles/`. The validation games' manual submissions have no Factory records. | `workspace/titles/` | [C] | data |

#### Template v1.2.1

| # | Finding | Evidence | Label | Class |
|---|---|---|---|---|
| T1 | One `Platform` interface. No ad call rejects, one ad plays at a time, and a missing SDK degrades to plain web. | `template:packages/platform-sdk/src/types.ts:124-221` | [C] | - |
| T2 | Adapters: yandex, poki, crazygames, y8, gamedistribution, gamemonetize, generic-web, gamevui. **No GamePix adapter at v1.2.1** (it is in v1.2.2, not pinned). | `registry.ts:27-36` | [C] | platform |
| T3 | Rewarded grants exactly once per request, with `ad:late-reward` on Yandex, CrazyGames, GameDistribution and Y8. Poki drops a reward after its 60 s deadline. | adapters | [C] | - |
| T4 | Yandex: no maximum duration after `onOpen`. A lost close callback freezes the game. | `adapters/yandex.ts:449`; `src/platform/bind.ts:219` | [I] | defect |
| T5 | CrazyGames: `sdk.init()` has no timeout (black boot screen if it hangs). | `crazygames/platform.ts:220` | [I] | defect |
| T6 | Local caps: Yandex 60 s, CrazyGames 180 s. Y8, Poki and GameDistribution rely on the SDK. | adapters | [C] | - |
| T7 | No banner support; no leaderboard, achievement or IAP calls, although capability flags exist. | `types.ts:28-31` | [C] | platform |
| T8 | `packages/analytics-sdk` is wired to nothing. Runtime counters exist in `window.__wgf__.usage()` (`adsRequested` / `adsShown`). | `src/core/probe.ts` | [C] | data |
| T9 | `usage.gameplayStart/StopCalls` stays 0 on Yandex and Poki. | `poki.ts:458-464`; `yandex.ts:357-372` | [C] | defect (measurement) |
| T10 | Example games hard-code `generic-web`. Tower Merge Rush's "Double score" can be repeated without limit, and no example checks `adAvailability`. | `examples/tower-merge-rush/src/main.ts:20`, `app.ts:140-153` | [C] | defect (reference quality) |
| T11 | No daily rewards, achievements, leaderboards, shop or unlock systems. | grep | [C] | design |
| T12 | `test:sdk:matrix` and the example e2e suites run in no workflow. | `.github/workflows/*.yml` | [C] | defect (coverage) |

### 7.3 Retention and session evidence for the two games

| Item | Finding | Label |
|---|---|---|
| Placements | Interstitial only on a result-card click, from the second clear or run, at most once per 180 s, never during play. Rewarded only from an optional button on the fail card. No preroll, banner or timer ad. | [C] |
| Structure | BBW: worlds of levels with a content file (`units.json`). SM: courses with par timers and gems. Both save progress. | [C] commit logs; depth [U] |
| Session length, D1, conversion | Never measured on real players. | [U] |
| QA defects before submission | D1 (SOUND label cut off on landscape phones, 2D) and D2 (one failed asset request left both games on an English "boot failed" message with no retry), both fixed (9374549, 39e7ad5). | [C] |
| Ad fix test evidence | The Y8 fixes added 25 unit + 3 e2e tests (BBW) and 26 unit + 4 e2e tests (SM), all against the repo's Y8 SDK mock. | [C] reports |
| Package size and load | BBW ~6.4 MB zipped (10.5 MB unpacked); SM ~1.8 MB zipped. CrazyGames's QA tool showed slow load because the machine was at 100% CPU, so its load figure is not evidence. | [C] sizes; load time [U] |

### 7.4 Distribution state

| Item | Finding | Label | Class |
|---|---|---|---|
| CrazyGames | Ads disabled in Basic Launch; Full Launch follows playtime, conversion and retention. | [C] docs | platform |
| CrazyGames | One game in review per account; SM waits for BBW. | [C] | distribution |
| Yandex | New-game submissions paused by the portal. | [C] | distribution |
| Y8 | Resubmission cooldowns 6 h to 5 days; Media tab locks during review. | [C] | distribution |
| GamePix | Description must not be AI-written (dashboard wording). | [C] | distribution |

### 7.5 Unknowns and their next step

| Unknown | Next step | Owner |
|---|---|---|
| Y8 report denominator, impressions, geo, dates | Export the report; ask developers@y8.com | person |
| Whether Build 003 fills real ads | After approval, observe `showAd` on the live page | person |
| CrazyGames launch outcome for BBW | Read the dashboard after review | person |
| Real session length, D1, conversion | Portal dashboards after public traffic | person |
| Yandex pause end | Watch the console banner | person |
| GamePix share and RPM base | Read the agreement; ask GamePix | person |
| Cost per game | Meter every agent (roadmap P0-05) | engineer |
