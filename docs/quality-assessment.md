# The quality assessment

The quality-report's `assessment` section (quality-report 1.5.0,
`scripts/wgf_quality/assessment.py`, `core/reference/quality-assessment.yaml`). It answers
three separate questions about one build, on the evidence the quality gate already read:

| Dimension | Question | Can automation pass it? |
|---|---|---|
| `design_validity` | Is the design coherent, and does the built content carry what the design and its tier ask for? | yes |
| `runtime_correctness` | Does the build load, run, take input and reach its states without errors? | yes |
| `player_facing` | Is it fun, does it feel right, is it fair, well paced and clear to a player? | **no** - only a person's G4 decision on this build |

**It decides nothing.** It is a view, not a second scoring system: it measures nothing
again, it reads every check through the one reader of producers' results
(`core/reference/check-tiers.yaml` `status_at` through `wgf_quality.registry.check_status`,
the same `read_check` knowledge compliance uses), and the floor, the verdict and the release
decision are computed without it. `scripts/tests/test_quality_assessment.py` holds that the
release decision, verdict, routes, dimensions, criteria, findings and scorecard are identical
with and without the section.

## Why

The quality floor answers "may this build ship". It did not say what kind of evidence the
answer stands on. The retrospective of the two 2026-10-05 validation runs (Brick Breaker
Worlds 2D, Sky Marble 3D; K6, not in this repository) found 73% (2D) and 55% (3D) of failing
checks were reported by the game's own play probe, 17 of 25 3D repairs closed on one AI judge
run each, two MAJOR findings of a passing visual-qa report were dropped, and none of eleven
problems a person found was caught by a gate. A green floor read as "the game is good". The
assessment says which question each check answers, how it was measured, and what it cannot
justify - and that nothing here measures fun.

## Statuses

| Status | When |
|---|---|
| `FAIL` | a check of the dimension whose tier holds a build (`hard` or `quality` in check-tiers.yaml) FAILED - or, for player-facing quality, a person's G4 decision on this build was `iterate` or `abandon` |
| `INCONCLUSIVE` | no failure, but a held check measured nothing on this build - no report, no entry, `SKIPPED`, `BLOCKED`, `UNMEASURED`, a `WARNING` (not held at this tier), a stale report or `DEFERRED`. **Never a pass.** For player-facing quality: no person has judged this build |
| `NOT_SUPPORTED` | no held check applies to this game (only advisory ones, or none): nothing here can say |
| `PASS` | every held check that applies passed - and, for player-facing quality, a person's G4 decision passed this build |

An advisory check is `supporting`: listed with its status, never deciding. Every automated
check of player-facing quality is a supporting **proxy**: one that holds a build and FAILED
still fails the dimension (automation can show a defect a player meets), but no number of
passing proxies makes it PASS.

A check of a `when: reported` family - one its producer reports only for a build it concerns
(play realism, browser QA, a model the pipeline built, a design rule the design step
evaluated) - with no entry in its report is listed under `not_reported` and counts for
nothing, as the floor's `applies: reported` treats it. Every other missing entry is
UNMEASURED.

## Measurement classes

| Class | Means |
|---|---|
| `deterministic` | Measured by the Factory from outside the game - bytes, pixels, the DOM, the browser's errors and timings, the design and data files. |
| `heuristic` | A measured quantity held to a bar that stands for a quality it does not define (contrast for readability, a bot's clear rate for fairness). Wrong both ways on a game the bar was not calibrated on. |
| `self-reported` | The game's own play probe (`window.__wgf__`) says what state it is in. The bot's inputs are real; whether the state is true is the game's word. |
| `ai-judged` | An agent read frames or code and gave a score, a verdict or a flag. Never a measurement. |
| `human` | A person's recorded G4 decision on this build. The only class that can pass player-facing quality. |

Each dimension reports its class mix (`classes`) and, when PASS, its `basis`: `measured` when
no passing held check is self-reported or AI-judged, `qualified` when some are, `weak` when
all are; `person` when a person's G4 decision passed player-facing quality. The Factory never repeats or cross-checks a judge, so every AI judgment is a single
one; `judges` records each judge's kind and `judge_runs` as its report states them (a repair
round re-asks the same judge, it is not a second opinion). G4 shows a qualified or weak pass
as `PASS (qualified)` / `PASS (weak)` with the reason.

## Unresolved judge findings

The visual-judge family names `unresolved: {report: visual-qa-report, list: findings,
severities: [blocker, major]}`: every blocker or major finding the judge raised is listed on
player-facing quality - **whatever the report's verdict**, a MAJOR finding of a PASS report
included - with its id, severity, summary and the report's verdict, and shown at G4 as
`! unresolved major finding ... on a PASS visual-qa-report`. Listed, never deciding: the
release decision and every threshold are unchanged.

## The person

Player-facing quality is PASS only on a `decision-record` of gate G4 with
`decided_by.mode: human` that pins, by content hash, a current report of this build (the
gate's evidence entries) and decided `pass`; `iterate` or `abandon` on this build is FAIL. A
decision on an earlier build is listed (`about: earlier-build`) and decides nothing; an
auto-approved or other gate's decision is never listed. In a normal run the quality gate runs
before G4, so the section says INCONCLUSIVE and **the G4 decision is the human evidence**.

What it does not read, and why:

* MV-4 records (`scripts/mv4/`, `docs/mv-4-plan.md`) are taken outside a run and are not an
  input of the gate: a person brings them to G4.
* `prototype-report.playtest_sessions` is written by the develop step
  (`observer: automation:develop`, `player_context: internal`): not a person.
* `decided_by.mode: human` is what `wgf decide` records for whoever runs it. The assessment
  cannot tell a person from an agent driving the CLI; that is the operator's discipline
  (the retrospective found one older G4 record whose rationale says an agent decided it).

## The metric table

Generated from `core/reference/quality-assessment.yaml` `families` (the file is the source;
this table restates it for a person). Three conclusions it states outright:

* `win.reachable` (and every oracle state) rests on the game's own `won` state, and the bot
  presses what the game's oracle says to press.
* visual-qa is an AI judge reading still frames.
* nothing here measures fun, feel, fairness or pacing.

| Family | Dimension | Class | What it measures | How | Limits, false positives and negatives | Evidence | Cannot justify |
|---|---|---|---|---|---|---|---|
| **Design consistency rules** (`design-rules`) | design validity | deterministic (only where reported) | The design's own rules - monetization against the platforms, session and scope, locales, the concept's mechanics carried and no foreign one added, the brief's commitments, one new element per unit, the knowledge trace. | Evaluated by the design step over the game-design's fields (consistency.rule_results). | Judges the document, not the build. A rule the design step did not evaluate for this design is not reported. | `design-consistency:*` | That the design is fun, or that the build implements it. |
| **Built content against the design and the tier** (`content-contract`) | design validity | deterministic | The content data the build ships (public/content/units.json at the played commit) counted against the units, elements and structure the design owes and the benchmark's bars at its tier; drift between the two. | Counted from the data file and the design by the content-sufficiency step. | Counts what the data declares. Difficulty and playtime are the design's own declared values, not measured play. Generated (non-authored) content is skipped, so it is unmeasured here. | `content-sufficiency:content.contract`, `content-sufficiency:content.data_present`, `content-sufficiency:content.units_shipped`, `content-sufficiency:content.elements`, ... (15 checks) | That the content is varied to a player, that any level is good, or that the declared playtime is how long anyone plays. |
| **Content kinds reported on screen** (`content-on-screen`) | design validity | self-reported | Every on-screen entity of a content role carries its kind, so elements can be counted on the build. | Read from the probe's entities while the bot played. | The kind is the game's own label for an entity. | `content-sufficiency:content.entity_kinds` | That the entity looks like, or behaves as, the element it names. |
| **Level layout geometry** (`level-layout`) | design validity | heuristic (only where reported) | The path and grid layouts the content data file declares - geometry, unit length, clearance - against play-realism.yaml's bars. | Computed from the declared layouts by the playability step's realism pass. | Bars calibrated on the reference games; a layout of a kind the data file does not declare is not judged. | `play-realism:level.geometry`, `play-realism:level.unit_length`, `play-realism:level.clearance` | That a level is well designed or interesting to play. |
| **Independent review of the build** (`independent-review`) | design validity | ai-judged | An independent reviewer's verdict and blockers on the shipped commit - fidelity to the design, invented content, code that games a gate. | A read-only reviewer agent reads the diff and the design (docs/review-module.md). | An agent's reading; it can miss a defect and flag a sound change. | `quality-floor:floor.review_blockers`, `quality-floor:floor.review_approved` | That the build is correct at runtime, or good to play. |
| **Audio the design owes, delivered** (`design-assets`) | design validity | self-reported | The asset manifest lists the music and sound effects delivered or integrated. | Counted from the asset-manifest the assets step wrote. | A manifest status is the assets step's record, not a sound heard. | `quality-floor:floor.music`, `quality-floor:floor.sfx` | That the audio plays (runtime) or suits the game (player-facing). |
| **The play probe answers, and the page raises no error** (`probe-and-errors`) | runtime correctness | deterministic | window.__wgf__.play.snapshot() answers while the game starts; no uncaught page error while the bot plays. | The playability bot in Playwright Chromium on the development commit's build, desktop and mobile viewports. | One browser engine; errors the bot's path never triggers are not seen. | `playability:probe.present`, `playability:page.errors` | That the game works on other browsers or real devices. |
| **States the game reports reaching** (`oracle-states`) | runtime correctness | self-reported | Play begins within the budget; good play reaches won, bad play reaches lost, retry returns to play with the goal reset; progress survives a reload; every unit can be entered and won or lost. | Real page inputs at the coordinates the probe lists; the states are read from the probe. | win.reachable rests on the game's own won state, and the bot presses what the game's oracle says to press. A probe that reports won without a win passes it (gate-gaming review is what looks for that). | `playability:start.playable`, `playability:win.reachable`, `playability:lose.reachable`, `playability:restart.works`, ... (8 checks) | That a player can win or lose by playing, or that winning feels earned. |
| **Every action changes the frame** (`input-response`) | runtime correctness | deterministic | Each action the probe offers, pressed for real, changes at least a share of the frame's pixels. | Before/after frames compared pixel by pixel (acknowledgement bars in the play rules). | Any visible change counts - a flicker passes, a meaningful but tiny response may fail. | `playability:act.acknowledged` | That the response is the right one or feels responsive. |
| **Console errors and WebGL context** (`runtime-errors`) | runtime correctness | deterministic (only where reported) | Console errors from the game's origin and lost WebGL contexts during the bot's play, per viewport. | Recorded by the browser while the bot plays. | Only the paths the bot played. | `play-realism:runtime.console_errors`, `play-realism:runtime.webgl_context` | Stability over long sessions or on other GPUs. |
| **Assets loaded and used, UI layout and states** (`production-runtime`) | runtime correctness | deterministic | Every required asset is in the build, fetched and used at runtime; audio plays; no UI control overlaps another; every screen state can be reached. | The production-quality step's network, DOM and frame records of the build. | Measured on the viewports the step renders. | `production-quality:assets.present`, `production-quality:assets.runtime`, `production-quality:assets.loaded`, `production-quality:assets.used`, ... (7 checks) | That the assets look right or the UI is pleasant. |
| **No placeholder geometry or browser-default UI** (`production-completeness`) | runtime correctness | heuristic | The scene draws no primitive placeholders and the UI is not unstyled browser controls. | Frame and DOM analysis against production-quality's detectors. | A detector - a deliberately geometric art style can trip it, an unusual placeholder can pass it. | `production-quality:scene.no_primitives`, `production-quality:ui.styled` | That the art is finished or good. |
| **Browser QA - measured by the browser** (`browser-run`) | runtime correctness | deterministic (only where reported) | The shipped build loads, draws, raises no error, keeps its UI inside the viewport and off the play, and handles audio (decodes, no stray loops, silent when hidden, mutes). | verify's browser-QA spec on the verified commit (core/reference/browser-qa.yaml), per viewport. | Chromium under Playwright on the build host. | `browser-qa-run:browser.run`, `browser-qa:browser.loads`, `browser-qa:browser.canvas`, `browser-qa:browser.page-errors`, ... (19 checks) | Behaviour on Safari, Firefox or a real handset. |
| **Browser QA - states the game reports** (`browser-oracle`) | runtime correctness | self-reported (only where reported) | Loading completes, the title screen leads to play, win, loss, retry, pause and hidden-page pause work, and actions start their sounds - on the shipped build. | verify's browser-QA spec, reading the probe's state. | The states are the game's own word, as in oracle-states. | `browser-qa:browser.ready`, `browser-qa:browser.menus`, `browser-qa:browser.win`, `browser-qa:browser.lose`, ... (8 checks) | That a player reaches them by playing. |
| **Browser QA - timings** (`browser-timing`) | runtime correctness | deterministic (only where reported) | Load time, time to first input, frame-time percentiles and heap growth. | Measured in the browser on the build host; a degraded host blocks the timing instead of passing it. | Desktop host timings - never a mobile device's (MV-4 measurement classes). | `browser-qa:browser.load-time`, `browser-qa:browser.first-interaction`, `browser-qa:browser.frame-stability`, `browser-qa:browser.memory-growth` | Performance on a player's phone. |
| **3D model validity** (`model-validity`) | runtime correctness | deterministic (only where reported) | Each GLB the pipeline built is valid, has its parts, bounds, normals and triangle budget, and is not a bare primitive. | Read from the GLB by the model checks (core/reference/asset-quality.yaml models). | Only models built from a spec by the pipeline report these. | `model-review:model.valid`, `model-review:model.parts`, `model-review:model.primitive`, `model-review:model.bounds`, `model-review:model.normals`, `model-review:model.triangles` | That a model looks good. |
| **Changes that game a gate** (`gate-gaming`) | runtime correctness | ai-judged | The reviewer's flags for a change that makes a check pass without the behaviour - an unread content field, a moved play area, a changed probe path, a sprite resized without its collider. | The review step's reviewer, against core/reference/gate-gaming.yaml. | An agent's reading of a diff; no flag is not proof of none. | `gate-gaming:*` | That the self-reported states are true. |
| **Verification, QA, performance budget and platform readiness** (`qa-and-verify`) | runtime correctness | deterministic | The verified bundle builds and packages, QA records no blocking defect, the frame budget holds, every required platform is ready and its SDK integration is complete. | The verify, QA and sdk steps' reports on the shipped commit, read by the quality floor. | The performance budget is measured on the build host; the SDK status is a static inspection of the integration against the platform profile, never the live portal SDK. | `quality-floor:floor.no_blocking_defects`, `quality-floor:floor.qa_pass`, `quality-floor:floor.valid_package`, `quality-floor:floor.platform_ready`, `quality-floor:floor.performance`, `quality-floor:floor.platform_sdk` | That the portal accepts the build, or that it runs well on a player's device. |
| **Clarity proxies** (`clarity-proxies`) | player-facing (proxy) | heuristic | The objective's words on screen in the first seconds; frame and scene contrast; text size and touch-target size against their bars. | Text found on screen, pixel statistics and DOM measurements. | Words on screen are not words read; contrast is not legibility; a target's size is not its findability. | `playability:start.objective`, `playability:frames.readable`, `production-quality:scene.contrast`, `production-quality:ui.text`, `production-quality:ui.targets` | That a player understands the goal or can read the screen. |
| **Variety and difficulty as the game reports them** (`pacing-proxies`) | player-facing (proxy) | self-reported | New content kinds appear in time, the design's difficulty axes rise across units, projectiles are reported as entities, and play is not lost without input before the grace. | The probe's entity kinds, difficulty values and lost state while the bot plays. | Every value is the game's own report. | `playability:content.variety`, `playability:difficulty.axes_progress`, `playability:entities.projectile`, `playability:idle.grace` | That the variety is felt, that the difficulty curve is fair, or that the opening is welcoming. |
| **Depth and session-length proxies** (`depth-proxies`) | player-facing (proxy) | heuristic | Challenge rises over timed play, a session lasts the designed length, and the ramp does not stall. | Samples of the game's reported metrics over a bot session, against the design's depth bars. | A bot's session, not a player's; the bars are the design's. | `playability:depth.ramp`, `playability:depth.session_length`, `playability:depth.stall` | That a player wants to keep playing. |
| **A naive bot's experience** (`naive-player`) | player-facing (proxy) | heuristic (only where reported) | How a bot that does not follow the oracle fares - setbacks, drift and alignment on a 3D path, pace, unit duration, clear rate. | The realism pass of the playability step (core/reference/play-realism.yaml), calibrated on the reference games. | A naive bot is not a first-time player; its clear rate stands for fairness only as far as the calibration holds. | `play-realism:naive.setbacks`, `play-realism:naive.drift`, `play-realism:naive.alignment`, `play-realism:naive.pace`, `play-realism:naive.unit_duration`, `play-realism:naive.clear_rate` | That the game is fair or well paced for a person. |
| **Collisions match what is drawn** (`physics-fairness`) | player-facing (proxy) | heuristic (only where reported) | No collision with something not drawn, and colliders the size of their sprites, on a 2D board with moving bodies. | The probe's bodies against the drawn frame. | Only bodies the probe reports; a 3D camera's screen positions are not judged. | `play-realism:physics.undrawn_collision`, `play-realism:physics.collider_size` | That a hit or a miss feels fair. |
| **Visual judge** (`visual-judge`) | player-facing (proxy) | ai-judged | A vision judge's verdict, its 0-5 scores per rubric dimension and its findings on the runtime frames, held to the rubric's and the benchmark's bars. | The visual-qa step's judge (core/reference/visual-qa-rubric.yaml) - an agent reading frames; the baseline judge of a golden run compares frames with a stored baseline. Read through the quality floor's visual criteria. | An AI judge reading still frames - it can be fooled, is not stable between runs, and is blind to motion and timing. | `quality-floor:floor.visual_verdict`, `quality-floor:floor.no_critical_visual_findings`, `quality-floor:floor.visual_major_findings`, `quality-floor:floor.visual_minor_findings`, ... (12 checks) | That the game looks good to a person, or feels good in motion. |
| **3D model look proxies** (`model-look`) | player-facing (proxy) | heuristic (only where reported) | A model's palette, contrast and silhouette against the asset-quality bars. | Rendered and measured by the model checks. | Bars, not taste. | `model-review:model.palette`, `model-review:model.contrast`, `model-review:model.silhouette` | That the model reads well in play. |
| **Audio balance** (`audio-balance`) | player-facing (proxy) | heuristic (only where reported) | Shipped clips' loudness spread and music under effects. | Loudness computed from the shipped clips. | A level window, not a mix a person judged. | `browser-qa:browser.audio-loudness` | That the audio is pleasant or fits the game. |

Not mapped, and why (`excluded`, `aggregates` in the file): a floor dimension's score (the
mean of criteria the families map); the visual judge's own blocker and score entries (read
through the floor's visual criteria instead: a blocker finding names no rubric blocker, a
score is a value, not a verdict); the store listing (publishing readiness, after G4); and the
floor criteria that aggregate checks a family already maps (counting them again would count a
result twice).

## Coverage

`scripts/check-integrity.py` (through `wgf_quality.registry.assessment_problems`) holds that
every check a family names is declared in check-tiers.yaml; every check of a source a family
names is in exactly one family; every check-tiers source is named by a family or excluded
with why; every quality-floor criterion is in a family, a listed aggregate, a `checks` or
`scores` aggregate over a report a family maps, or excluded with why; an `ai-judged` family
names its judge and only it does; no family is `human`; `player_facing` requires a person;
and every family says what it measures, how, its limits and what it cannot justify. A new
check without a place in the assessment fails integrity.

## Reading it

* The section: `quality-report.assessment` (`reference` - the file's path, version, digest and
  whether the run pinned it; `dimensions[]` - status, reason, basis, checks with class, tier,
  status, role and evidence, not_reported, human, judges, unresolved, classes,
  cannot_justify).
* G4: `wgflib/gate_evidence.py` prints one line per dimension with its status as stated, the
  held, failed and unmeasured counts and the class mix, the reason when not PASS, the basis
  of a qualified or weak PASS, each judge and every unresolved finding.

Tests: `python -m unittest scripts.tests.test_quality_assessment` (QUALITY), and the
six-genre run of `scripts/tests/test_quality_consistency.py`, whose engine-validated reports
assess design and runtime PASS (qualified) and player-facing INCONCLUSIVE with every gate
passed.
