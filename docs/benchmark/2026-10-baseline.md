# Old-Factory baseline: the two validation games (2026-10)

**Status: OBSERVED BASELINE.** This file records what the old Factory produced and recorded
for the two games of the 2026-10-03 validation. It is evidence about the old Factory. It is
**not** a list of findings the new Factory is expected to reproduce, and a new run is not wrong
because it differs from it.

| | |
|---|---|
| Baseline taken against `main` | `8daeec8` (Merge branch 'dyCuong03/ws10-assets-reentry', 2026-10-04 21:16 +0700) |
| Measured | 2026-10-04, read-only, from the run records and the game repositories |
| Machine-readable | [`2026-10-baseline.json`](2026-10-baseline.json) |
| Script | [`baseline.py`](baseline.py): `python docs/benchmark/baseline.py --out docs/benchmark/2026-10-baseline.json` |

The script reads `state.json`, `events.jsonl` and `artifacts/` of each run. It reads game
sources at the release commit with `git show`, never from the working tree, and it reads the
Factory worktrees' reflogs. It writes nothing outside its `--out` file, and two runs give
byte-identical output. The 3D course table is TypeScript, so Node (>= 22, type stripping)
evaluates it from stdin. Every number below comes from that JSON unless a row names another
source.

| Key | 2D | 3D |
|---|---|---|
| Game | Brick Breaker Worlds (PixiJS) | Sky Marble (three.js) |
| Run | `new-game-20261003-081154-4e5e0a` | `new-game-20261003-082542-0de9b5` |
| Project | `C:/Users/duycu/wgf-runs/val-2d/project` | `C:/Users/duycu/wgf-runs/val-3d/project` |
| Repository | `C:/Users/duycu/wgf-runs/val-2d/games/brick-breaker-worlds` | `C:/Users/duycu/wgf-runs/val-3d/games/sky-marble` |
| Workflow | `new-game` v7 | `new-game` v7 |
| Run state | WAITING at `publish-review` (G6) | WAITING at `publish-review` (G6) |

Earlier 3D attempts `new-game-20261003-081107-470090` and `new-game-20261003-081332-f7bb0b`
are in the same project. They are not part of this baseline.

## 1. Factory commit each run used

Each run read the Factory from its own worktree (`val-2d/factory`, branch `work/val-2d`;
`val-3d/factory`, branch `work/val-3d`). The worktree moved while the run was paused. The
table gives the commit in force at each point, from the worktree reflog. Both worktrees are
clean.

| Point | 2D | 3D |
|---|---|---|
| Run start | `cc9e2ff` (on `main`, PR #24) | `cc9e2ff` (on `main`, PR #24) |
| Last develop, playability, visual-qa, verify | `2a114ab` = tree of `main` `096f9d7` (PR #42) | `aa5b333` = tree of `main` `f228557` |
| Release and platform-validate | `1c78dc6` = tree of `main` `d67b24b` (listing showcase) | `cbb7e14` = tree of `main` `5a8adf4` |
| Head moves during the run | 12 | 15 |

`work/val-*` merge commits are not on `main`. The script checks that each one's tree is
identical to the `main` parent it merged. The run start predates `genre-models.yaml` and the
content contract. The 3D design was made on `cc9e2ff` and never re-entered, so it has no
`build_spec.content`. The 2D design was re-entered (design visit 4) and has one.

## 2. Release

| | 2D | 3D |
|---|---|---|
| Release commit | `96f5ceaa7abf165594b06cfb8c69eec9f0612ec1` ("feat(game): development iteration 17") | `64ff4c69f05cc259fa9bfda72305fd988ff94d0e` ("feat(game): development iteration 13") |
| Manifest | `artifacts/release-manifest/v1.json` | `artifacts/release-manifest/v3.json` |
| Manifest id | `wgf:release-manifest:brick-breaker-worlds:20261004-01` | `wgf:release-manifest:sky-marble:20261004-01` |
| Manifest content hash | `sha256:946e455a79f86d3fab6dbb618378a9fbc70049eba7fb479fa5780fc6572e2cb0` | `sha256:1fbabf0e3fcb025f5736428033010608cdfd461c25cf76a41ee1f552f8c7a4ca` |
| Release / version / state | r1 / 0.1.0 / draft | r1 / 0.1.0 / draft |
| Package | `poki.zip`, 6.077 MB, 78 files | `poki.zip`, 1.716 MB, 52 files |
| Package checksum | `sha256:697622cafe6fd5f7c46971e8c1857496d2fb50ab04ff0c47602fab836cef9dd7` | `sha256:e301327464b7944e015c5df022fc4776cf5127a77046dea52b5b4c82169348c2` |
| Package content digest | `sha256:1c470233b4997360a34a50fcb41d844c0e5f7251dbf3dab0dc25f6a62eb686b8` | `sha256:d7ca844cb60eebb37594e5f4d5dee84947b5619d9c482ce6b8c88524ad1293c9` |
| `release/r1/poki.zip` on disk matches the checksum | yes | yes |
| Dist digest (verification `build_artifact`) | `sha256:a165ecada7849c0489c5d73ed115f62d2404ea6812d8ab2063a82e40d82074d3`, 97 files, 10 707 557 bytes | `sha256:27f7f3f78f4f9bb53acee73526644a9f27b04a4d0e74103478e62284a7566f1b`, 56 files, 6 338 806 bytes |
| Targets | poki required; crazygames, yandex optional (profiles 1.1.0) | poki required; yandex, crazygames optional (profiles 1.1.0) |
| Template | `Cuvara/web-game-template` 1.2.0 `b106261` | same |
| Evidence status | PASS_MOCK | PASS_MOCK |

Only the Poki package exists for each game. The optional platforms have listing renditions
but no package.

## 3. Gate results

Each row is the artifact the step's last execution produced (`state.json` `steps.<id>.outputs`).
The file version (`vN`) is the run's own counter. The artifact id carries the Factory's
sequence, which differs from it.

### 3.1 Final results

| Step | 2D | 3D |
|---|---|---|
| greybox-playability | v15 PASS: 42 checks (38 PASS, 4 WARNING) on `312b7c4` | v2 PASS: 24 checks, all PASS, on `5d4be2d` |
| assets | asset-manifest v5: 34 items, 0 placeholders, 1 issue, `complete: false` | asset-manifest v4: 26 items, 0 placeholders, 0 issues, `complete: false` |
| playability (schema 1.2.0) | v23 PASS: 42 checks (38 PASS, 4 WARNING), automation-bot | v15 PASS: 40 checks (28 PASS, 8 SKIPPED, 4 WARNING), automation-bot |
| production-quality (schema 1.0.0) | v16 PASS: 19 checks, 2 WARNING (`scene.no_primitives` exempt by design, desktop and mobile) | v13 PASS: 19 checks, all PASS |
| visual-qa (rubric 1.2.0, bar 3, judge `claude`/sonnet) | v5 PASS, 52 frames, 2 judge runs, 1 repair | v10 PASS, 35 frames, 1 judge run, 0 repairs |
| review | review-report v8 approve, 0 blockers (iteration 5, 12.7 s) | review-report v11 approve, 0 blockers (iteration 8, 18.2 s) |
| sdk | sdk-report v4: poki, crazygames, yandex "working" (12 features working, 1 not required, each) | sdk-report v4: same shape for poki, yandex, crazygames |
| sdk-review | review-report v9 approve, 0 blockers (40.1 s) | review-report v12 approve, 0 blockers (39.9 s) |
| verify | verification-report v3 PASS, **PASS_MOCK**: 59 checks, 51 PASS, 2 FAIL, 6 WARNING | verification-report v4 PASS, **PASS_MOCK**: 59 checks, 47 PASS, 2 FAIL, 10 WARNING |
| verify (qa-report) | qa-report v3 pass, PASS_MOCK; e2e 40/0; platform-validation 17/2; perf proxy 13 fps (not a device) | qa-report v4 pass, PASS_MOCK; e2e 18/0; platform-validation 17/2; perf proxy 11 fps (not a device) |
| store-listing | store-listing v4 complete: 5 screenshots, 3 renditions; trailer webm only | store-listing v8 complete: 5 screenshots, 3 renditions; trailer webm only |
| listing-validation | v4 PASS: 60 checks, 20 UNKNOWN, 3 warnings (`metadata.ru.*`) | v7 PASS: 60 checks, 20 UNKNOWN, 0 warnings |
| platform-validate | platform-publication-poki v1: validated, **HUMAN_REQUIRED**, 5/5 guards GREEN | platform-publication-poki v3: validated, **HUMAN_REQUIRED**, 5/5 guards GREEN |

Both verify FAILs are `platform.build-target` for the two optional platforms (no package).

Verification warnings:
- 2D: `quality.content:variety`, `quality.depth:session-length`,
  `policy.assertions:{crazygames,yandex}`, `assets.manifest`, `assets.loading`.
- 3D: `quality.content:{objective-shown,units-reachable,variety,win-lose-per-unit}`,
  `quality.difficulty:axes-progress`, `quality.progression:persists`,
  `policy.assertions:{yandex,crazygames}`, `assets.manifest`, `assets.loading`.

Playability results that are not PASS:
- 2D: `content.variety` WARNING ("the probe reports no `entities[].kind`") and
  `depth.session_length` WARNING (the bot's window was cut to 220 000 ms). Each is reported
  on desktop and mobile.
- 3D: `content.units_reachable`, `content.objective_shown`, `content.win_lose_per_unit` and
  `difficulty.axes_progress` are SKIPPED, because the design states no content units or
  axes. `content.variety` and `progression.persists` ("the probe reports none of what the
  design says persists") are WARNING. Each is reported on desktop and mobile.

### 3.2 Visual-qa scores and findings

| Dimension | 2D v5 | 3D v10 |
|---|---|---|
| art_completeness | 4 | 4 |
| character_readability | 4 | 4 |
| environment | 4 | 4 |
| ui_polish | 4 | 4 |
| typography | 4 | 4 |
| composition | 3 | 4 |
| consistency | 5 | 5 |
| no_debug | 5 | 5 |
| mean / min | 4.125 / 3 | 4.25 / 4 |
| look verdict | finished-game | finished-game |

The final findings are all minor:

| Game | Finding | Category | Route | Frame |
|---|---|---|---|---|
| 2D | `desktop-board-narrow-column`: the board is a narrow portrait column on desktop and the hint card floats detached | composition | develop | - |
| 2D | `end-won-card-clipped`: Level Clear card clipped mid-entrance at 720 px | composition | develop | desktop/end-won |
| 2D | `hint-covers-ember`: the onboarding hint hides the falling ember | readability | develop | mobile/state-showcase-embers |
| 2D | `world1-backdrop-faint`: the cyan alley backdrop is low-contrast and sparse | composition | assets | desktop/first-session-1s |
| 3D | `wordmark-faded-low-contrast`: the wordmark is semi-transparent and no call to action is in the frame | readability | develop | desktop/persist-after-reload |
| 3D | `intro-card-covers-course`: the course intro card hides the gate and gems at the start | composition | develop | desktop/first-session-1s |
| 3D | `marble-colour-dull`: the marble reads dark brick-red, not bright coral | readability | assets | - |

### 3.3 How each gate got there (every version)

| Gate | 2D | 3D |
|---|---|---|
| playability | 23 versions: FAIL v1-v3, v11, v14; else PASS | 15 versions: FAIL v1; else PASS |
| production-quality | 16 versions: FAIL v1-v6, v9-v12, v15; PASS v7, v8, v13, v14, v16 | 13 versions: FAIL v1-v3; PASS v4-v13 |
| visual-qa mean score | v1 3.75, v2 4.0, v3 4.125, v4 4.0, v5 4.125 (all PASS) | v1 3.875 FAIL, v2 3.875, v3 3.375 FAIL, v4 3.875, v5 4.0, v6 4.375, v7-v9 4.125, v10 4.25 |
| review | 9 versions: v2 no-verdict; v3 request-changes (2 blockers, 1 major, 1 minor); else approve | 12 versions: v3 request-changes (1 blocker); v8-v10 request-changes (2 blockers, 1-2 majors); else approve |
| verification | v1 FAIL, v2 PASS, v3 PASS | v1 FAIL, v2 PASS, v3 FAIL, v4 PASS |
| store-listing / listing-validation | listing incomplete v1-v3, complete v4; validation FAIL v1-v3, PASS v4 | listing incomplete v1-v3 and v7; validation FAIL v1-v3, BLOCKED v6, PASS v4, v5, v7 |

The review blockers, from the JSON's `gates.history.review-report`:
- 2D v3 (`55ab02d`):
  - `out-of-scope-armored-hazards-bosses` (blocker): the commit added content the brief
    listed as "not now";
  - `star-gates-and-level-count-changed` (blocker);
  - `tests-assert-changed-rules` (major);
  - `level-query-bypasses-unlocks` (minor).

  This commit is the person-directed content expansion. The design was revised to v3 to
  match it afterwards.
- 3D v3 (`7e2f23b`): `css-fibre-datauri-unresolved-ref` (blocker).
- 3D v8-v10 (`ba4c337`, `36eb839`, `5137eb3`):
  - `verify-blockers-not-addressed` (blocker);
  - `pause-hidden-tab-steps-advance` (blocker);
  - `smoke-boot-timeouts-unexplained` (major);
  - `report-stale`, `stray-files`, `boot-scene-unused-template-file` (minor or major).

## 4. Decision records

| Game | File | Gate | Decision | Mode | Decided at (UTC) |
|---|---|---|---|---|---|
| 2D | `decision-record-strategy-review/v1..v3` | G2 | approved x3 | auto-approved | 08:13, 08:26, 18:41 on 10-03 |
| 2D | `decision-record-tech-plan-review/v1..v2` | G3 | approved x2 | auto-approved | 08:35, 21:47 on 10-03 |
| 2D | `decision-record-prototype-review/v1` | G4 | pass | human (the Lead) | 2026-10-04 06:14 |
| 2D | `decision-record-release-review/v1` | G5 | approved | human (the Lead) | 2026-10-04 06:42 |
| 3D | `decision-record-strategy-review/v1` | G2 | approved | auto-approved | 2026-10-03 08:25 |
| 3D | `decision-record-tech-plan-review/v1` | G3 | approved | auto-approved | 2026-10-03 08:33 |
| 3D | `decision-record-prototype-review/v1` | G4 | iterate (marble swirl band hidden, a VQA major) | human (the Lead) | 2026-10-03 18:53 |
| 3D | `decision-record-prototype-review/v2` | G4 | pass | human (the Lead) | 2026-10-03 23:06 |
| 3D | `decision-record-release-review/v1` | G5 | approved | human (Worker B under the Lead's rule) | 2026-10-04 01:16 |

No G6 record exists. Nothing was submitted, and `WGF_PUBLISH_LIVE` was never set (both
review packages). The JSON holds each record's rationale and the files its `subject` pins.

## 5. Content

Definitions:
- 2D units are `public/content/units.json` at `96f5cea`.
- 3D units are `COURSES` in `src/game/courses.ts` at `64ff4c6`. The 3D game has no
  `public/content/units.json`, and its design (schema 1.8.0) has no `build_spec.content`.
- An *element combination* is the set of a unit's element kinds:
  - 2D: brick and capsule cell kinds plus structure kinds;
  - 3D: segment kinds plus features (bumpers, walls, rails, narrow, plaza, slope,
    drop-landing).
- A *mechanic combination* is a unit's `mechanics` list (2D only).

| Metric | 2D | 3D |
|---|---|---|
| Design the content follows | game-design v3 (`wgf:game-design:brick-breaker-worlds:20261003-04`, schema 1.9.0) | game-design v1 (`wgf:game-design:sky-marble:20261003-01`, schema 1.8.0) |
| Units | 32 (authored rounds) | 12 (courses) |
| Groups | 4 worlds x 8 | 3 tiers x 4 (Meadow Isles, Sunset Cliffs, Storm Peaks) |
| Purpose arc (design) | teach 6, breather 7, test 11, twist 4, climax 4 | not declared |
| Distinct mechanics | 12 (units.json `mechanics`) | 7 (design `build_spec.mechanics`) |
| Distinct element kinds | 10 cell kinds + 5 structure kinds (static, slides, descend, embers, boss) | 12: 5 segment kinds (line, turn, jump, mover, drop) + 7 features |
| Elements per unit (min / mean / max) | mechanics 4 / 5.94 / 8 | elements 4 / 7.08 / 11 |
| Distinct mechanic combinations | 24 of 32 | - |
| Distinct element combinations | 29 of 32 (0.906) | 12 of 12 (1.0) |
| Repeated layouts | 0 | - |
| Introduction points | 10 units introduce something; the last at unit 27 | not declared |
| Objectives | 32 distinct lines in 4 classes: clear the board 20, clear without losing a ball 4, clear before the descending field lands 4, defeat the boss 4 | 1 class: reach the goal gate (+ par stars, gems) |
| Structure kinds | 5 | 5 segment kinds |
| Climax units | 4 bosses: w1-l8 sentinel HP 8, w2-l8 prism HP 10, w3-l8 crusher HP 12, w4-l8 forge HP 14 | none declared |
| Boss art ids | all 4 kinds use the one `boss` sprite (`sprites/boss.svg`); distinct boss art = 1 | - |
| Difficulty axes (first unit to last) | speed 0.05-0.40, density 0.08-0.60, variety 0.09-0.91, precision 0.17-0.70 | not declared (width, mover speed and hazards rise in the data) |
| Unlock gates | world gates in the design: 18 / 36 / 54 stars + the previous boss | course 5 at 8 stars, course 9 at 18 stars |
| Designed play time | sum of `expected_duration_s` 854 s (16-50 s per unit); par sum 1 149 s | par sum 345.5 s (18-39 s per course); course length 234-440 m; 120 gems |
| Design session | first session 220 s, target 300 s, first play 5 s | first session 220 s, target 300 s, first play 5 s |

Both games' content was made release-grade by people outside the workflow. The 2D game went
from 12 to 32 levels, and the 3D game from 6 straight courses to 12 authored ones. See
`docs/quality-gap-audit-2026-10.md` section 1, and section 2 for the intervention inventory.
So these numbers are the baseline of the *accepted* games, not of what the workflow produced
unattended.

## 6. Cost and time

| | 2D | 3D |
|---|---|---|
| Developer budget at start | 14 sessions, US$110 | 14 sessions, US$110 |
| Budget raises | 1 (to 18 sessions, a human, 2026-10-03 22:01Z) | 0 |
| Developer sessions recorded | 18 (greybox 7, develop 11) | 9 (greybox 6, develop 3) |
| Developer cost recorded | **US$62.86** (greybox 39.33, develop 23.53) | **US$29.25** (greybox 20.42, develop 8.83) |
| Largest single session | US$18.97 (greybox visit 5, the content expansion) | US$17.62 (greybox visit 1) |
| Agent processes spawned by steps (`claude`) | 139: assets 92, design 11, develop 11, visual-qa 9, greybox 7, review 5, sdk-review 4 | 224: assets 175, visual-qa 17, store-listing 9, review 8, greybox 6, sdk-review 4, develop 3, design 2 |
| Handoff visits (a person's `done` on greybox/develop) | 11 (greybox 5, develop 6) | 14 (greybox 3, develop 11) |
| Resumes | 29 | 45 |
| Loop-limit blocks | 4 (greybox, develop x2, store-listing) | 2, plus 1 listing BLOCKED (feature bullets share no word with their source) |
| Wall time to G4 pass | 22.04 h | 14.67 h |
| Wall time to the drafted release | 22.47 h | 16.83 h |
| Wall time to the G6 wait | 22.50 h | 16.84 h |
| Engine step time (sum of step durations) | 15.87 h | 9.18 h |

The recorded cost is a lower bound:
- Only developer sessions record a cost (`STEP_LOG` `budget: developer-cost`).
- The design, asset-author, judge, reviewer and copy sessions in the spawn counts record none.
- Handoff visits are work done outside the engine by workers and delegated agents. The Lead
  and the workers are not in the run records at all.
- Wall time includes pauses while Factory fixes were merged.

## 7. Known defects (OBSERVED BASELINE)

These defects were present in the accepted games or in the old Factory during these runs.
They are a record of the old Factory, not expected findings for the new one.

### 7.1 In the games, at the release commits

| # | Game | Defect | Source |
|---|---|---|---|
| G-01 | 2D | The four bosses share one drawing (`boss` asset) and differ only by tint and name | `val-2d/review/README.md` known issue 1; `val-2d/games/audit-2.md` deficiency 1; section 5 above (distinct boss art = 1) |
| G-02 | 2D | On desktop the board is a portrait column with side scenery (design's portrait layout) | review README issue 2; audit-2 deficiency 2; visual-qa v5 `desktop-board-narrow-column` |
| G-03 | 2D | In late levels the ball can rise into the HUD band | review README issue 3; audit-2 deficiency 3 |
| G-04 | 2D | The real Poki SDK logs "localStorage ... sandboxed" errors from its own frame (36 in one session) | review README issue 4; audit-2 note 4 |
| G-05 | 2D | Listing copy: the controls line names touch only; ru copy is the objective line only; a feature bullet calls bricks "one-hit" | review README issue 5; listing-validation v4 warnings `metadata.ru.*` |
| G-06 | 2D | Visual-qa minors: clear card caught mid-entrance, hint far from the board on desktop, faint World 1 backdrop, hint covers the ember | review README issue 6; visual-qa v5 findings |
| G-07 | 2D | Endless mode, asked for in the brief, not built (design v3 `optional`, outside the G2 strategy) | review README "Content summary" and issue 7 |
| G-08 | 2D | The probe reports no `entities[].kind`, so `content.variety` is WARNING | playability v23; review README issue 7 |
| G-09 | 2D | Units w1-l2, w2-l3 and w4-l8 reported `partial` by develop (29 built of 32) | prototype-report `content_coverage`; review-report v9 notes |
| G-10 | 3D | The time-trial mode in the brief is not built (personal best per course instead); no settings beyond the sound toggle | `val-3d/review/README.md` known issues; audits 2-3; G4 v2 rationale |
| G-11 | 3D | The marble reads deep red under the dusk grade | review README; audit-3 minor 1; visual-qa v10 `marble-colour-dull` |
| G-12 | 3D | The far goal gate is a few pixels tall at the start of long desktop courses | review README; audit-3 minor 2 |
| G-13 | 3D | ru store copy is machine-written. Its feature bullets carry English terms because grounding compares words with English facts | review README known issues; listing-validation v6 BLOCKED |
| G-14 | 3D | Visual-qa minors: faded wordmark without a call to action, intro card covering the course | visual-qa v10 findings |
| G-15 | 3D | The content contract never applied: content and difficulty checks SKIPPED, `progression.persists` WARNING | playability v15; verification v4 warnings; section 1 |
| G-16 | 3D | The Poki SDK debug pill shows top-left in local runs (not on the portal) | review README; audit-3 minor 4 |
| G-17 | both | The trailer is WebM only (the bundled ffmpeg has no libx264) | store-listing problems `trailer-note`; both review READMEs |
| G-18 | both | Evidence is PASS_MOCK: no real device, real portal or human playtest; the low-end figure is a CPU-throttled proxy | qa-report perf_results; both review READMEs "UNVERIFIED" |
| G-19 | both | Only the Poki package exists; Yandex and CrazyGames fail `platform.build-target` | verification failed_checks; review READMEs |

### 7.2 Found earlier in the same runs, then fixed by a person

| # | Game | Defect | Source |
|---|---|---|---|
| E-01 | 2D | 12 levels, one brick type, no hazards, no bosses: "a demo, not a game" | `val-2d/games/audit-1.md` deficiency 1 |
| E-02 | 2D | Laser state drew a flat brown box; unbalanced result cards; empty accessible names; broken wordmark letterforms | audit-1 deficiencies 2-5 |
| E-03 | 3D | Every course a straight corridor; par far too loose; 6 courses with one look; banner over the view; camera inside the gate at the finish; marble band hidden | `val-3d/games/audit-1.md` deficiencies 1-6 |
| E-04 | 3D | Ink start-line bar; flat track strip; bright day sky instead of dusk; marble behind the title label; small marble on phones | `val-3d/games/audit-2.md` open deficiencies |

### 7.3 In the old Factory during these runs

These are recorded with their fixes in `docs/handoff/2026-10-03-two-game-validation.md`
(defects 1-29) and `docs/quality-gap-audit-2026-10.md` (top findings 1-7). Those still open
there at the end of the runs:
- 9: no `daily_challenge` retention hook.
- 19: `wgf pause` on a live step trips the event-log guard.
- 22: a re-entered assets step rebuilds untouched 3D models with new node names.
- The listing copy gaps.

The audit's structural findings:
- The release tier is not built; the workflow ships the MVP by construction.
- The genre bars could not fail the builds a person rejected.
- A person's play-through detected the problems, not a gate.
- Every routed fix goes to one generalist.
- Brief features drop silently.
- The consistency checks match words.

`main` gained 24 commits after the 2D release-time Factory (`d67b24b`) and 32 after the 3D one
(`5a8adf4`), up to `8daeec8`. Several of them address items above:
- mechanic-id consistency and a brief-grounded strategy (findings 2, 3 and 8);
- WS-1, the quality tier and release content budget;
- WS-5, feature evaluation instead of dropping features;
- WS-10, assets re-entry remakes only refused models and climax units get distinct art (22
  and G-01);
- platform profiles 1.2.0. Both games were validated under profiles 1.1.0.

None of these were exercised by the two runs.

## 8. What this baseline does not cover

- No run was resumed, decided or rebuilt for this file. The games were not played again.
- The cost does not include the non-developer agent sessions or any session outside the
  engine (section 6).
- The 3D content metrics come from game code, not a content-contract file. The 3D and 2D
  element definitions are different, so do not compare their element counts directly.
- Objective classes for 2D come from the wording of the objective lines (`objective_class`
  in the script), not from a field the design declares.
