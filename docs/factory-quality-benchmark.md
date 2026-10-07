# The Factory quality benchmark

Every game a `/new-game` run finishes is held to one minimum. A game is Factory-complete only
when it passes the full quality contract: the universal floor every game carries, its genre
family's contract, the 3D contract when it is 3D, at its quality tier, on the evidence of the
build itself. This page is the system: the files, how they fit, and how to version them.

## The files

| File | Holds | Read by |
|---|---|---|
| `core/reference/quality-benchmark.yaml` | What a release-tier game measurably carries: content, progression, features, presentation and store bars, each with its calibration `basis` | strategy, design, tech plan, develop, assets, content-sufficiency, the quality gate |
| `core/reference/quality-floor.yaml` | The two-layer contract the quality gate scores: dimensions and their floors, which report describes which commit, the universal criteria (layer A), the genre and 3D criteria (layer B) | the quality gate (`scripts/wgf_quality`) |
| `core/reference/visual-qa-rubric.yaml` | The visual judge's dimensions and its own pass bars | visual-qa; the floor reads its bars at tier mvp |
| `core/reference/content-sufficiency.yaml` | How each content bar is measured on the build | content-sufficiency |
| `core/reference/genre-models.yaml` | Families, their nodes, units and bars | design, playability, the floor's family resolution |

The benchmark states each bar once. The floor's criteria name benchmark bars by path
(`minimum: {release: "quality-benchmark:presentation.visual_qa.min_mean"}`) instead of
restating them, so the two cannot disagree.

## The two layers

**Layer A - the universal floor.** Every game, every genre: a functional core loop, reliable
controls, a meaningful win and loss, no blocking defects, no broken UI or layout on mobile or
desktop, no placeholder content, no missing required asset, content sufficient for the
designed session, meaningful progression, a stable runtime, a valid package, no critical QA
finding - and at the release tier the benchmark's presentation bars (visual-qa scores and
finding counts, every production-quality check, audio counts, no skipped content check).
Each criterion maps to an existing producer's check ids or fields; none measures anything new.

**Layer B - the genre contract.** Per family of `genre-models.yaml`: arcade (feedback,
responsiveness, replay), puzzle (mechanic combinations, escalation), platformer (movement,
encounter variety), shooter (readable projectiles, feedback, enemy variety), racing (track
variety, a readable course), strategy (decisions, compounding progression), survival
(pressure, an understood loss), simulation (a persistent meta). And per rendering dimension:
3D adds camera and spatial readability, environment and lighting. A family the floor does not
list takes its nearest ancestor's contract through the design's genre node, and always the
universal floor - never nothing. No consumer branches on a family id: a new family is a new
entry.

Each criterion states: the `dimension` it scores, the `metric`, how it is measured
(`evaluate`), its `minimum` and `preferred` target, its `severity` per tier (`blocker` |
`warning`), the `owner` discipline, the `route` of its finding, the `evidence` it reads, how a
`regression` of it is detected, and its `basis`.

## Dimensions and floors

Twelve dimensions: gameplay, content, variety, progression, visual, UI, audio, consistency,
polish, technical/performance, platform readiness, store. Each has a `min_score` at the
release tier and a `preferred` target; at tier mvp a dimension's floor is its blocker criteria
alone. A dimension is at its floor only when every blocker criterion met its
minimum and its score reaches `min_score`; no averaging passes a dimension below its floor
(`docs/quality-gate-module.md`).

## Calibration

Every bar records its `basis`:

* `measured-2` - both calibration releases meet it;
* `measured-1` - only one release could be measured on it, or one does not meet it;
* `proposed` - a defensible default no release has been measured against.
* `hypothesis` (1.7.0) - a market expectation no record in the research corpus measures yet,
  with its `confidence` (at most 0.6, as for a hypothesis claim) and the `evidence` it rests
  on. The `design` block's designed play for a finite release (1800 s) and par calibration
  (1.25 times the bot's time) are hypotheses: recalibrate them from teardown records
  (`core/craft/competitive-teardown.md`) as the corpus grows, never to let a design pass.

The dimension floors (`min_score`) and the criteria that read no benchmark bar
(performance, the 3D lighting check, `no_debug` at 5) are new with the floor and marked
`proposed`. Two releases are not a population: recalibrate as releases accumulate.

## Versioning

1. **Never lower a bar to let a build pass.** A build that falls short is a finding, not a
   calibration. Bars move only with measurements from shipped releases, recorded in the
   change's description.
2. **Every change bumps the file's `version`**: a new criterion, family or dimension is a
   minor bump; a recalibrated bar is a minor bump that names the releases measured; a
   comment or wording change is a patch.
3. **The run pins the version it started under.** `new-game` lists the floor, the benchmark
   and the rubric under `pinned_references`; a run copies them at its start and is scored
   against those copies for its whole life. Every quality-report records the versions and
   digests it was scored against (`benchmark`), and the release manifest carries the floor
   and benchmark versions (`evidence.quality_report`). An edit takes effect at the next run.
4. **Regression is against the pinned version.** A dimension below its floor under the
   pinned benchmark is a QUALITY REGRESSION; a dimension score that dropped since the run's
   previous build is listed in `regression.dropped`.
5. **A new criterion reads an existing producer.** If no producer measures what a bar needs,
   the measurement comes first (in the producing step, with its tests), then the criterion.
6. **Validate a change** with `python scripts/check-integrity.py`, `python -m unittest
   scripts.tests.test_quality_gate` (which resolves every bar at every tier and checks that
   every genre family has a contract), and rebuild the plugin runtime
   (`python scripts/build-plugin-runtime.py`).

## Where it is enforced

* The `design` step holds a design at its tier to the `design` block (1.7.0): references to
  teardown records, the beat chart, signature moments, meta systems, designed play and par
  calibration (`scripts/wgf_design/beats.py`, rules `design.*`), as the run pinned the file.
* The `quality-gate` step scores the build before G4 and routes a dimension below its floor
  back to design, assets or develop.
* G4 is decided on the quality-report and shows its scorecard.
* Release refuses a build whose quality-report did not pass exactly that build; a
  `development` decision (tier mvp) is drafted and recorded as such, never as a release.
