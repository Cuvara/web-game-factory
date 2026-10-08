# The quality-gate step

`scripts/wgf_quality` (step type `quality-gate`, workflow `new-game` 11). It runs after
`verify` and before G4 (`prototype-review`), and decides one question: **does this build hold
the Factory's quality floor on every dimension at once?**

Every producer before it judges one side of a build on its own bar: playability plays it,
production-quality checks its assets and UI, visual-qa reads its frames, content-sufficiency
counts its content, verify builds and checks it, review reads its code. Each can pass while
the build as a whole is not shippable - a build whose UI broke on the mobile viewport while
every other side scored high reached G4 looking finished (the "Mobile-40" case). The quality
gate holds the build to all of them together, on the evidence those producers recorded about
**that same build**, against a versioned contract (`core/reference/quality-floor.yaml`, see
`docs/factory-quality-benchmark.md`).

It plays nothing, renders nothing and never touches the checkout.

## Inputs

| Input | Required | Read for |
|---|---|---|
| `playability-report` | yes | core loop, controls, win/lose, runtime errors, played variety and difficulty, skipped content checks |
| `production-quality-report` | yes | assets present/loaded/used, no primitives, UI layout per viewport, audio, every check |
| `visual-qa-report` | yes | rubric scores, blocker/major/minor findings |
| `content-sufficiency-report` | yes | content, variety, progression, difficulty, drift, skipped checks |
| `qa-report` | yes | verdict, blocking defects, performance |
| `verification-report` | yes | verdict, platform readiness, the bundle digest |
| `prototype-report` | yes | the development commit |
| `game-design` | yes | genre family and node, quality tier, rendering dimension |
| `sdk-report` | no | the shipped commit and its base; SDK status per platform |
| `review-report` | no | the newest review (sdk-review's): verdict and blockers |
| `asset-manifest` | no | delivered music and sound effects |
| `title-strategy` | no | the quality tier when the design states none |
| `listing-validation-report` | no | the store dimension, once a listing exists |
| `triage-report` | no | the run's finding ledger, which the gate advances on this build |
| `decision-record` | no | G4's decision, which verifies a person's findings |

Without a required input the step waits for input: the build has not been judged on every
side yet. A missing optional input leaves the criteria that read it UNMEASURED - never a pass.

## The build, and stale evidence

The build is `{commit, development_commit, digest}`: the verified commit release would ship
(qa-report, verification-report, sdk-report), the development commit it sits on (sdk-report's
base, else the prototype-report's) and the verified bundle's digest
(`verification-report.build_artifact.content_hash`).

`quality-floor.yaml` `build_evidence` says which commit each report must describe: the
gates that play and judge the build before sdk commits on top of it (playability,
production-quality, visual-qa, content-sufficiency, prototype) describe the development
commit; verify, sdk, review and the listing describe the shipped one. A report about another
commit is **stale**: the step is BLOCKED, scores nothing, and lists the stale report in
`evidence[]`. A review of the development commit does not cover the sdk commit that ships.

## The contract

`scoring.derive` assembles the criteria this game is held to:

1. **Layer A, universal** - every criterion of `universal`, for every game.
2. **Layer B, genre** - the criteria of `genres.<family>` for the design's `genre.family`.
   A family the floor does not list falls back to the family that owns the nearest ancestor
   of the design's `genre.node` (walking `parent` in `core/reference/research-vocabulary.yaml`,
   families from `core/reference/genre-models.yaml` `nodes`); with no ancestor covered, the
   universal floor alone applies (`contract.resolved_by: none`). Never nothing.
3. **Layer B, rendering** - `dimensions_contracts.3d` for a 3D game (the design's engine and
   assets, `wgf_assets.requirements.game_dimension`).

A criterion applies at a tier only when its `severity` names that tier.

## Scoring

Each criterion is measured by an evaluator kind - `checks`, `verdict`, `scores`, `count`,
`all` - over one report, and is PASS, FAIL, UNMEASURED (the report says nothing about it:
never a pass) or DEFERRED (the store, before its listing exists). It scores 0-100: the share
of what it measures that met the minimum (per viewport, the worse viewport counts).

A `checks` criterion with `applies: reported` applies only to a build whose report lists one
of its checks in any status: `floor.existing_content` reads `content.regression`, which only
a run that adopted a repository reports. Reported but SKIPPED - the adopted checkout shipped
no content data file and its shipped build was never counted through the play probe - it is
an UNMEASURED blocker at every tier: a null floor never means no floor.

A dimension's score is the mean of its measured criteria. A dimension is **at its floor**
only when

* every blocker criterion of it met its minimum (an UNMEASURED blocker does not), and
* no blocker finding of it is still open from an earlier build (below), and
* its score reaches `min_score` at the tier (the release tier states one; at tier mvp a
  dimension's floor is its blocker criteria alone, and its score is reported).

No average carries a dimension past a failed blocker, and no dimension's score carries
another's: `overall_score` is reported and decides nothing. A dimension below its floor is a
**QUALITY REGRESSION** (`dimensions[].regression`, `regression.below_floor`): the build fell
below the versioned benchmark. At the release tier an UNMEASURED dimension is below its
floor too.

The store dimension (`phase: listing`) is measured by `listing-validation`, which runs after
G4. Before it exists the dimension is DEFERRED - listed in `deferred`, never passed - and
release separately requires the listing's validation (`docs/release-module.md`).

## The scorecard

The same criteria are read a second way, per discipline a person judges a game by
(`core/reference/quality-floor.yaml` `scorecard`, 1.2.0): gameplay, game feel and polish,
level design and content, 2D art, 3D art, UI/UX, audio, performance and runtime, browser
compatibility, technical integrity, accessibility and readability, platform compliance and
publishing readiness. Each
line takes the criteria of the floor dimensions it lists; a criterion that belongs to another
discipline than its dimension names its line itself (`scorecard: performance` on
`floor.performance`, which `technical` scores). `art_2d` and `art_3d` read the same criteria
and a game is scored on the one its rendering dimension is (the other is `NOT_APPLICABLE`).
Every floor dimension feeds exactly one line per rendering dimension, so every criterion is
on the scorecard; the contract is refused otherwise.

| Line status | When |
|---|---|
| `BELOW_FLOOR` | a blocker criterion of the line is below its minimum or unmeasured, or an open blocker finding of it is not yet re-measured on a newer build - whatever the line or any other line scores; or the line's own `min_score` (none shipped) is not met |
| `DEFERRED` | every criterion of it is deferred to the store listing |
| `UNMEASURED` | no criterion of the floor measures the line for this game - a gap in what the Factory measures, never a pass |
| `NOT_APPLICABLE` | an art line of the other rendering dimension |
| `PASS` | otherwise |

`scorecard.hard_blockers` lists every blocker below its minimum (`FAIL`), unmeasured
(`UNMEASURED`) or carried open (`OPEN`), apart from any score. A line `BELOW_FLOOR` fails the
gate - a blocker always also holds its floor dimension, so the floor semantics above are
unchanged - and the overall score decides nothing. G4 shows the lines and every hard
blocker (`wgflib/gate_evidence.py`). A report scored on a floor pinned before the scorecard
has none. Tests: `scripts/tests/test_quality_scorecard.py` (a build that scores high
everywhere with one blocker fails).

Which tier each check is in - Hard Gate, Quality Gate or Advisory - is
`core/reference/check-tiers.yaml` (see docs/specialist-routing.md "Regression knowledge").

Play realism (`docs/playability-module.md`, "Play realism") and browser QA
(`docs/verification-module.md`, "Browser QA") are on the floor with `applies: reported`: a
build whose reports carry their checks is scored on them, one that does not (a 3D build's
screen turns, a grid game's path geometry, a verification that ran no browser QA - which
verify itself holds BLOCKED at release) is not. `floor.physics_drawn` (game feel),
`floor.naive_control` (gameplay), `floor.naive_challenge` and `floor.level_geometry` (level
design), `floor.runtime_console`, `floor.browser_boot` and `floor.browser_session` (browser),
`floor.browser_layout` (UI/UX), `floor.browser_audio` (audio), `floor.webgl_context` and
`floor.browser_performance` (performance) are release blockers; `floor.browser_ui_advisory`
and `floor.browser_asset_weight` read the advisory checks and are warnings. The blockers
read `required_only: passed`: both producers hold a check by the run's own tier class, so
below the release class a quality check is optional - its failure the producer's WARNING,
an unmeasured one its note - and the floor counts its passes but is not held by the rest; a
criterion whose checks are all optional and none passed does not apply. At the release class
the producers report them required (an unmeasured one held as a required FAIL), and every
one counts. A timing check
verify could only measure on a degraded host is BLOCKED there, and counts here as not passed:
the build is measured again on a quiet host before it can pass.

## Gates the run's workflow lacks

A run started under an older definition, or a workflow from elsewhere, may lack a gate the
quality policy now requires before this step (`quality.missing_gates`, the engine's
`context.missing_gates`). The report names them (`missing_gates`), its release decision is
never `release` while any is named - their evidence does not exist - and G4 shows them. See
docs/new-game-quality-inheritance.md, rule 7.

## Lesson candidates

The lesson candidates specialist visits reported (prototype-report
`specialist.lesson_candidates`, triage-report `lesson_candidates`) are listed in
`lesson_candidates` and shown at G4. A person promotes one to `core/reference/lessons.yaml`
- with the check and the test that hold it - or not; the gate never applies one.

## The release decision

| Tier | Every dimension at its floor | Decision | Verdict |
|---|---|---|---|
| `release` | yes (store deferred) | `release` | PASS |
| `release` | no | `not-release`, with the reasons | FAIL |
| `mvp` or none | yes | `development` | PASS |
| `mvp` or none | no | `development` | FAIL |

A run at tier mvp is a development build: its decision is never `release`. Release drafts
it and records the decision in the manifest's `evidence.quality_report`, beside the run's own
class (`evidence.quality`, the quality policy of WS-12): a development build is never a
release, and the policy keeps its run from a live submission.

## Findings and their lifecycle

Every criterion below its minimum (or unmeasured) is a typed finding, in the record WS-8's
specialist routing reads:

```json
{"id": "quality:floor.ui_layout", "criterion": "floor.ui_layout", "dimension": "ui",
 "layer": "universal", "severity": "blocker", "summary": "...",
 "evidence": [{"artifact_type": "production-quality-report", "artifact_id": "...",
               "content_hash": "sha256:...", "commit": "<development commit>"}],
 "build": {"commit": "<shipped commit>", "digest": "sha256:..."},
 "expected": {"minimum": 1.0, "preferred": 1.0},
 "observed": {"by_viewport": {"desktop": 1.0, "mobile": 0.4}},
 "owner": "ui", "route": "develop", "status": "open",
 "first_seen": "<commit>", "closed_on": null, "regressed": false}
```

Against the run's previous quality-report (the step's own last output):

* a finding still failing stays `open`, with its `first_seen`;
* a finding whose criterion now meets its minimum **on a newer build** is `closed`, with
  `closed_on` naming the build that re-measured it;
* a finding whose criterion passes again **on the same build** stays `open` - nothing was
  re-measured, only a report changed - and holds its dimension below the floor;
* a criterion that met its minimum on the previous build and does not now is `regressed`,
  and a dimension score that dropped is listed in `regression.dropped`.

## The run's finding ledger

The quality gate sees every report of one build, so it is where the run's finding ledger
(docs/specialist-routing.md) moves on after the last specialist fix, when no triage runs. It
advances the newest triage-report's `lifecycle` on the build's reports and on its own
(`wgf_triage.ledger.remeasure`, the same rules as triage): a finding a specialist fixed is
implemented by the visit, verified by the producer that raised it and closed once every gate
measured the fix, or kept `implemented` as regressed. It records the result as the report's
`ledger`: `lifecycle`, `open` (blocking findings a gate raised that are still open) and
`awaiting` (a person's findings, which the next G4 decision verifies). With every dimension
at its floor and a blocking finding open, the verdict is BLOCKED (`not-release`): nothing
verified it on a newer build. Which severities block is
`core/reference/specialist-routing.yaml` `ledger.blocking_severities`.

## Routing

FAILED (not retryable) with the first of the routes of the open findings that hold a
dimension below its floor (`design-gap`, `assets`, `develop`; `listing` once the listing is
measured). Since workflow 11 every one of them goes to `triage`, like every gate's failure
(scripts/wgf_triage, docs/specialist-routing.md): triage reads the quality-report as the
`quality-report` producer (core/reference/specialist-routing.yaml 1.2.0 maps each quality
dimension onto a routing dimension), normalizes its open findings in the dimensions below
the floor into quality findings, and routes them - a `design-gap` finding to design
(triage's `design`, with its design gap), an `assets` finding to assets (with the asset ids it
names), the rest to the specialist that owns the dimension, whose develop visit's brief
carries them. The route budgets are on triage (`quality-gate.develop: 2`,
`quality-gate.assets: 2`, `quality-gate.design-gap: 1`).

## Anti-gaming

* **Evidence comes from the build.** Every score cites the reports it read, by artifact id,
  content hash and the commit they describe; a report of another commit blocks the gate.
* **Thresholds come from the run's start.** `new-game` lists the floor, the benchmark and
  the visual-qa rubric under `pinned_references` (and, since workflow 16, the play-realism,
  browser-QA and visual-quality bars and the regression registry the producers read -
  docs/new-game-quality-inheritance.md "Pinned references"): when a run starts, the engine copies them
  into the run directory and records their digests in the run's params (corroborated by
  WORKFLOW_STARTED like every param). The step reads the run's copies; a copy whose digest is
  not the recorded one BLOCKS the step. An edit made during a run applies to the next run. A
  run started before the pin existed reads the live files and records `benchmark.pinned:
  false`.
* **A finding closes only on a newer build** (above).
* **No bar is defaulted in code.** A contract that cannot be read or resolves a bar to
  nothing BLOCKS the step.

## G4 and release

G4's `required_artifacts` include the quality-report (`core/lifecycle/gates.yaml` 1.5.0), and
the checkpoint shows its scorecard: each dimension's score against its floor, the open
findings and the release decision (`wgflib/gate_evidence.py`). Release refuses
(`docs/release-module.md`) unless the newest quality-report PASSED exactly the build it ships
- its commit and development commit - pins the run's newest qa, verification, prototype, sdk,
review, playability, production-quality, visual-qa and content-sufficiency reports, and did
not decide `not-release` (a `development` decision is drafted and recorded as such). A
workflow without the quality gate says so with `with: required_quality: false` on its release
step. Release also refuses while the run's finding ledger, advanced once more on the newest
reports and G4's decision, holds an open blocking finding (`open-findings`).

## Running it

It runs inside `wgf new-game` / `wgf resume`. `--mock` replaces it with a placeholder whose
mock plan entries `develop`, `assets` and `design-gap` script a failure routed there.

Tests: `python -m unittest scripts.tests.test_quality_gate` (the Mobile-40 case, stale
evidence, tier mvp, an unknown family, regression, the finding lifecycle, pinning, release
refusals, the G4 display, a passing release-quality build).
