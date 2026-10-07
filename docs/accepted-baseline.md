# The accepted baseline

A build a person accepted is the bar the next build of the same game must not fall below.
Workflow 16 of `new-game`; `scripts/wgf_baseline`; `core/reference/accepted-baseline.yaml`.

## Why

Every gate before this held a build to an **absolute** floor: playability plays it against
the experience contract, visual QA scores its frames 0-5 against a rubric, the quality gate
holds it to `quality-floor.yaml`. None of them asked whether the build was better or worse
than the one a person had already accepted.

Observed 2026-10-05 (`factory-learning-ledger.md` L8, L12; diagnosis frames in
`wgf-runs/diagnosis/{2d,3d}`): both validation games had a build a person passed at G4
(tag `baseline-r1`: 2D brick-breaker-worlds `96f5cea`, 3D sky-marble `64ff4c6`). A new run
adopted each repository, wrote a new design, and rewrote the game: the 3D greybox's first
commit cut the courses from 234-440 m to 38-124 m, deleted 939 lines of the environment and
changed the marble's drag from 0.6 to 0.15; the 2D run rewrote every one of its 32 units and
later narrowed the paddle and halved the capsules. Every gate still passed. Visual QA scored
the 3D environment 4 for the accepted build and 4 for the rewrite. The person who played
both found the accepted builds much better. The reports the Factory already held said so -
good play won in 6 inputs where it had taken 60, the frames' mean luminance went from 122 to
184 - and nothing compared them, because nothing read the accepted build or its G4 decision.

## The pieces

| Piece | Where | What |
|---|---|---|
| The bars | `core/reference/accepted-baseline.yaml` 1.0.0 | how the accepted build is found, the replacement maximum, the metrics and their tolerances, the paired judgement, playtest severities; calibration evidence. Pinned by the run like the quality floor (`pinned_references`). |
| `accepted-baseline` step | `wgf_baseline.step.AcceptedBaselineStep`, before `design` | pins the accepted build into the run: artifact `accepted-baseline` |
| `baseline-regression` step | `wgf_baseline.step.BaselineRegressionStep`: `greybox-baseline` after `greybox-playability` (`phase: greybox`), `baseline-regression` after `content-sufficiency` | holds each build to it: artifact `baseline-regression-report` |
| Briefs | `wgf_baseline/brief.py`, read by design (`commitments.accepted_baseline`) and every develop visit | without a person's approval: **extend** the accepted build |
| Triage | `specialist-routing.yaml` 1.4.0 producer `baseline-regression-report` | its findings routed to the specialist that owns each |
| Quality gate | `wgf_quality.step.baseline_status`, quality-report 1.2.0 `baseline` | a baseline that exists and was not measured against the build is never skipped |
| Playtest notes | `scripts/wgf-playtest.py`, `wgf_baseline/playtest.py` | a person's findings against a build, blocking until re-measured or confirmed |

## Finding the accepted build

`accepted-baseline` (inputs: `title-strategy`) looks for, in order:

1. `factory.baseline.accepted: {commit, run}` - a person names the accepted commit and the
   run whose reports measured it;
2. the newest **G4 `pass`** decision-record **a person** gave for the title
   (`decided_by.mode: human`): in every run of the project's run store (artifacts named
   `decision-record-*`) and in `workspace/titles/<id>/decisions/`. `iterate`, `kill`, an
   automation's record and another title's are never a baseline.

The accepted commit is the decision's pinned `prototype-report`'s (the development commit);
the shipped commit its `qa-report`'s. The reports of `locate.reports` - playability,
production-quality, visual-qa, content-sufficiency - are taken by the decision's pin when it
pinned them (a pin whose content no longer hashes is a problem, never replaced by another
report), else as the newest report of that type in the decision's run that describes the
accepted commit (`pinned_by: commit`). They are **copied into the run** with the frames the
playability report recorded (each checked against its sha256), and the metrics are read from
them. The run no longer depends on the old run store.

`status`: `present`; `none` (nothing was accepted for the title - every baseline check is
SKIPPED, with that reason); `unmeasured` (an accepted build exists but its commit or its
playability report cannot be resolved - every baseline check BLOCKS, never skips).

There is no switch that turns the baseline off. A person who wants a run to replace the
accepted work approves the replacement when the run asks.

## Replacement: a person decides

`baseline-regression` measures, from git objects between the accepted commit and the
candidate (`wgf_baseline/replacement.py`):

| Quantity | Measured | Maximum |
|---|---|---|
| `units_replaced_share` | accepted units of `public/content/units.json` removed, or changed (a key the accepted unit had is gone or holds another value; a key added is an extension) | 0.25 |
| `files_rewritten_share` | accepted text files under `src/` deleted, or with at least half their accepted lines deleted | 0.25 |
| `lines_deleted_share` | accepted lines under `src/` deleted | 0.25 |

A quantity the accepted commit does not ship (no content data file) is `null` - unmeasured
and named - never 0. Above any maximum, with no approval on record, the step returns
**WAITING_FOR_HUMAN**:

```
the candidate 68a12b7a237e replaced the build a person accepted (96f5ceaa7abf):
units_replaced_share 1.0 (maximum 0.25). Approve the replacement, or restore the accepted
build and extend it: wgf decide <run> approve | restore [--note TEXT]. Only a person decides
this; it never approves on a timeout.
```

* `approve` (a person's): recorded in the report (`replacement.decision`: who, when, the
  note, the accepted commit, the commit and shares it was decided on) and carried by every
  later report of the run while the accepted commit is the same. The metrics marked
  `waived_by_replacement` (look and tuning a replacement changes on purpose) are then
  SKIPPED; the outcome of good play, the visual-qa score drop and the paired judgement still
  apply - a replacement may be different, never worse.
* `restore`: FAILED, route `restore` - from `greybox-baseline` back to `greybox` (two passes,
  `greybox.max_visits_by_route`), from `baseline-regression` through triage to develop - with
  a finding that names the rewritten files and the replaced units, and the brief says
  *restore and extend*.
* An answer recorded by automation (from inside a step's process tree) is refused: the run
  keeps waiting. The step never approves on a timeout; it is not a gate, so
  `factory.checkpoints.timeout_auto_approve` cannot name it.

Why not a gate. Gates (`core/lifecycle/gates.yaml`) authorize lifecycle transitions; this
decision moves no entity. It reuses the engine's decision machinery the way the publish
step's `submit` does: the choice is recorded as a `DECISION_RECORDED` event bound to the
visit (`wgf decide`, `wgf runs --waiting` show it), the step accepts only `decided_by:
human`, and the step's own report is the durable record.

## Metrics: the same bot on both builds

At the production phase the step compares the metrics the accepted build's reports carry
with the candidate's (`wgf_baseline/metrics.py`), from the playability report of the
candidate commit (a report of another commit is never compared) and its visual-qa report:

| Metric | Read from | Compared | Viewports |
|---|---|---|---|
| `win.outcome` | `win.reachable` measured.reached | equal | desktop |
| `win.inputs` | `win.reachable` measured.inputs | ratio 0.5-2.0 | desktop |
| `unit.duration_ms` | `content.units_reachable` transitions (mean over the units both left) | ratio 0.67-1.5 | desktop |
| `bad_play.ended_ms` | `depth.ramp` measured.bad_play_ended_ms | ratio 0.5-2.0 | desktop |
| `session.length_ms` | `depth.session_length` measured.length_ms | ratio 0.5-2.0 | desktop |
| `frame.luminance` | `frames.readable` mean of mean_luminance | delta <= 32 | both |
| `frame.contrast` | `frames.readable` mean of contrast | delta <= 24 | both |
| `entity.area.<role>` | `entities.visible` median_area per role; a role the candidate lost fails | ratio 0.67-1.5 | desktop |
| `vqa.score.<dimension>` | visual-qa `scores`; owner and route the rubric dimension's | drop <= 1 | - |

SKIPPED when the accepted build did not measure it (with the reason); UNMEASURED - a
`major` finding, never a pass - when it did and the candidate did not; FAIL - a `blocker`
finding in the metric's dimension (`lighting` and `art` resolve by the design's engine
dimension) - beyond tolerance.

Why desktop for play metrics: two plays of the **same commit** (2D `f55653dc` playability
v9/v10, 3D `db651f92` v8/v9) stayed inside every band on desktop, but on the 3D game's mobile
viewport the bot's own play varied (entity areas x0.21 and x0.53, unit time x1.87, inputs
x0.47). A tolerance tighter than the measuring instrument's noise would fail good builds.

The accepted build's reports are the ones recorded when it was accepted (`measured_by`
their own runs); re-measuring the accepted commit with the current bot at run start is not
implemented yet (below).

## The paired judgement

The visual-qa judge (`factory.visualqa.judge`) is shown, for each state both builds
captured (`paired.states`: first-session-1s, play-2s, state-playing, unit-1..3-1s, won,
lost, retry, paused; at most 6 per viewport, at least 2), the accepted and the candidate
frame side by side (`<workdir>/pairs/<viewport>/<state>/{accepted,candidate}.png`, copies
checked against their sha256), and answers per rubric dimension **better, same or worse**
with a reason (`wgf_baseline/paired.py`). Worse on any dimension is a blocking finding
`paired:<dimension>`, routed by the rubric dimension's route (`assets` for art, environment
and consistency; `develop` for UI, typography, composition) to the owner the visual-qa
producer table names.

* `command`: the same argv, isolation (the frames and the Factory's guarded paths
  fingerprinted around it) and `verdict_from` as visual QA; an unusable verdict is retried
  once, then the judgement is UNMEASURED.
* `baseline` (golden runs): no agent - each pair's similarity
  (`wgf_visualqa.baseline.similarity`); a pair below the bar (0.70) makes
  `paired.baseline_dimensions` (art_completeness, consistency, environment) `worse`. A
  mechanical judge cannot tell better from different: it never answers better.
* `none`, too few pairs, a judge that wrote where it may only read: the step is BLOCKED.
  Unjudged is never a pass.

## Playtest notes

```bash
cat > notes.json <<'EOF'
{"findings": [{"id": "marble-falls", "dimension": "gameplay", "severity": "blocker",
  "summary": "the marble rolls off-centre and falls off on the meadow circuit",
  "task": {"change": "keep the marble on the course under straight input",
           "acceptance": ["a person plays meadow-circuit without falling"]}}],
 "measures": {"marble-falls": "bad_play.ended_ms"}}
EOF
python3 scripts/wgf-playtest.py file <run-id> notes.json [--build <commit>]
python3 scripts/wgf-playtest.py list <run-id>
python3 scripts/wgf-playtest.py confirm <run-id> baseline-regression-report:playtest:marble-falls
```

The file is the `request` shape `wgf decide <run> iterate --findings` takes, validated the
same way, stored in the run by content hash (`<run>/playtest/`), its act appended to
`playtest/notes.jsonl` with the commit played. The run's next `baseline-regression` reads it
back (refusing a file that no longer hashes, and any act not filed by a person): each finding
is `baseline-regression-report:playtest:<id>`, and one of a blocking severity (`blocker`,
`major`) fails the step - triage routes it to its owner - and so holds the quality gate. It
closes only when the metric it `measures` passes on a build newer than the one it was filed
against, or when a person confirms it. A newer build alone never closes it. Both commands are
refused from inside a step's process tree.

## Routing and the quality gate

`baseline-regression` FAILED routes `assets` before `develop` (the findings' routes) and
`restore`; the workflow sends all three through triage (`triage.max_visits_by_route`:
`baseline-regression.develop: 2`, `.assets: 2`, `.restore: 1`). The quality gate's
`baseline` block (docs/quality-gate-module.md, "The accepted baseline"): SKIPPED without a
baseline, PASS on a passing report of the build's development commit at the production
phase, FAIL with the report's routes, and UNMEASURED - BLOCKED, `not-release` - when a
baseline exists and the build was not measured against it. Release requires a passing
quality-report, so it follows.

## Calibration

The replay of the real reports is `scripts/tests/test_accepted_baseline.py` (`Replay`,
fixtures trimmed from the run stores, each naming its source file and content hash).

**Replacement** (`wgf_baseline.replacement.measure` on the games' repositories):

| | units | files rewritten | lines deleted |
|---|---|---|---|
| 2D 96f5cea -> greybox 9f92931 (the adopted visit that ran no developer) | 0.0 | 0.0 | 0.0 |
| 2D 96f5cea -> 1a53551 (greybox's second commit) | **1.0** | 0.0 | 0.036 |
| 2D 96f5cea -> 68a12b7 (the build a person judged worse) | **1.0** | 0.026 | 0.115 |
| 3D 64ff4c6 -> greybox:1 b6b9edb | unmeasured (no content data file) | 0.190 | **0.462** |
| 3D 64ff4c6 -> 1c6b099 (the build a person judged worse) | unmeasured | 0.172 | **0.460** |
| largest improving visit of the accepted runs (commit to commit) | 0.0625 | 0.0556 | 0.0842 |

The maximum (0.25) is three to four times the largest improving visit; both rejected
replacements exceed it from their first rewriting commit.

**Metrics**, accepted -> judged worse (desktop): 2D good play won -> **lost**, inputs 20 ->
3 (x0.15), target area x0.52, luminance 25.8 -> 92.4 (+66.6), contrast +20.7 (mobile +31.9);
3D inputs 60 -> 6 (x0.10), luminance 121.8 -> 183.7 (+61.9), goal area x27.5, target role
gone, session 155.3 s -> 71.9 s (x0.46), bad play survives 29.9 s -> 66.0 s (x2.21). The
visual-qa scores moved by at most 0.5 (3D 4 -> 3.5 on three dimensions): within the judge's
own noise, which is why an absolute score could not catch it.

**End to end** on the real run stores (read-only; a temporary store linking the accepted run,
the candidate's frames copied): `accepted-baseline` found both G4 passes (2D
`wgf:decision-record:brick-breaker-worlds-g4:20261004-03`, 3D
`wgf:decision-record:sky-marble-g4:20261003-04`; 3D's earlier `iterate` ignored), copied 3
reports and 52 / 35 frames, read 19 / 17 metrics. `baseline-regression` on 2D `68a12b7` and
3D `3f394e2`: **WAITING_FOR_HUMAN** on the replacement (2D units 1.0, 3D lines 0.46). With a
simulated approval (replay only) both were still **FAILED**: 2D on good play's outcome, the
unmeasured visual-qa scores (that run never reached visual QA) and the paired judgement; 3D on
the paired judgement. The mechanical (`baseline`) judge put every pair at similarity
0.32-0.44 (2D) and 0.38-0.47 (3D) against a bar of 0.70; two plays of the same commit (2D `f55653dc`, 3D `db651f92`)
paired at 0.87-1.00.

## What is not done

* **Re-measuring the accepted commit at run start.** The accepted build's metrics are the
  ones its own run recorded. The bot changed between the runs (new checks, new measured
  fields); where the accepted report lacks a metric it is SKIPPED, never compared against a
  default. Playing the accepted commit again with the current bot when the run starts would
  make every metric comparable and is the next step.
* **Live runs.** No `new-game` run has executed workflow 16 against a live agent host. The
  evidence is the unit tests, the mock workflow tests and the replay above.
* **Tuning values.** Drag, speeds and camera parameters are not read directly: what they do
  is read through the bot's play (inputs to win, survival, unit time) and the frames.
