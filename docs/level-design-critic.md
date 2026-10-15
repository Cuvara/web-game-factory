# The level-design step: the level critic and risk and reward

`level-design` (workflow 19 of `core/workflows/new-game.workflow.yaml`, module
`scripts/wgf_leveldesign/`) runs after `content-sufficiency`. Content sufficiency counts what a
build carries. This step asks whether the units are *designed*, and whether an optional risk
exists and pays. It writes a `level-design-report` (`core/artifacts/level-design-report.schema.json`).

**As shipped it is advisory.** It reports and never holds a build: see
[Advisory, and what makes it blocking](#advisory-and-what-makes-it-blocking).

## What it reads

- **The playability step's records.** With `with: survey: true`, the survey captures every
  surveyed unit at its start, middle and end (`level_frames`, under `<project>/level/`, with
  each frame's sha256 and the entities the probe reported). With `with: risk: true`, the risk
  test plays sampled units under the game's own oracle policies `safe` and `greedy` (the
  probe's optional `play.policy`) and writes `risk.json`. What the risk test plays (projects,
  units, attempts, windows, policies) is `core/reference/play-realism.yaml` `risk`, the one
  source both steps read. A probe without `play.policy` costs one page load: the bot records
  that and stops.
- **`core/reference/level-design-rubric.yaml`.** The moments, the unit sample, the dimensions
  (play space, identity, route choice, reveal, climax, distinct from the previous unit), the
  blockers, the bars, and what the `baseline` critic measures.
- **`core/reference/risk-reward.yaml`.** The reward and failure metrics, and the bars greedy
  must clear over safe.

The run pins both reference files, beside play-realism (`pinned_references`). A rubric
configured by path (`factory.leveldesign.rubric`) is read as configured.

## Checks

| Check | Tier (`check-tiers.yaml` 1.8.0) | Means |
|---|---|---|
| `level.frames` | advisory | every sampled unit has its start, middle and end frame |
| `level.critic` | advisory | every unit at or above the rubric's bars, no blocker, the mean at its bar |
| `risk.measured` | advisory | every sampled unit played under both policies with a reward reading |
| `risk.reward` | advisory | greedy earns measurably more, at a measurably higher failure rate, on the rubric's share of units |

`level.*` is not reported for a design that authors no units. `risk.*` is always reported.
The quality floor reads them as `floor.level_design` (variety) and `floor.risk_reward`
(gameplay), both release **warnings** (`core/reference/quality-floor.yaml` 1.4.0) read with
`required_only: passed`: an advisory check counts only when it passed, so a check that failed
or measured nothing never lowers a dimension's score. Triage routes their findings to the
level designer (`develop`) or to design (`design-gap`) (`core/reference/specialist-routing.yaml`),
but only from a report that FAILs - which an advisory report never does.

## Outcomes

As shipped (`factory.leveldesign.hold: false`), at every tier: every check is reported
`required: false`; a shortfall is WARNING, a check that measured nothing (no critic, no
`play.policy`) is SKIPPED with the reason, and the step succeeds. A critic that cannot judge -
its frames cannot be staged or no longer match the recorded sha256, the judge fails or
writes into its frames - is a SKIPPED `level.critic` with why, never the run's outcome.

Held (`hold: true`) at a strict tier (quality-policy `skipped_checks`: the release tier as
shipped), every check is required and unmeasured is not passed. A failure is FAILED, routed
`design-gap` when a failure routes there and otherwise `develop`. No judge configured is
BLOCKED, and so is a frame no longer on disk. Below a strict tier a held step reports like an
advisory one.

At any tier, a reference file the run pinned that was edited after the start BLOCKS.

## The critic

`factory.leveldesign.judge` in `workspace/config/factory.yaml` (`scripts/wgf_leveldesign/settings.py`):

- `none` (shipped): nothing is judged and nothing is spent. `level.critic` is SKIPPED.
- `command`: an agent able to read images, run read-only and isolated like visual QA's judge.
  Placeholders are `{frames_dir}`, `{brief}`, `{verdict}` and `{prompt}`. The frames it reads
  are copies, verified against the recorded sha256. It is a paid agent session per visit;
  neither the shipped configuration nor the autonomous profile configures one.
- `baseline`: no agent. It measures what entity boxes and frame signatures can, and carries a
  person's approved scores for a unit whose frames match the approved ones. Everything else is
  left unmeasured.

## Advisory, and what makes it blocking

Nothing the step measures can hold a build yet:

- No pinned template and no golden port implements the probe's `play.policy`, so
  `risk.measured` and `risk.reward` measure nothing on any current game.
- No level critic is configured by default, and a configured one costs an agent session
  per visit.
- Every bar of both reference files is `basis: proposed`.

Making a check blocking is a change in core, in new versions of the files, never an edit in
place:

1. A pinned template (and both golden ports) implements `play.policy`, and greedy and safe
   have been measured on real builds; the risk-reward bars are recalibrated in a new version.
2. A level critic is configured where the run is supervised, and its verdicts have been read
   against people's on real builds; the rubric is recalibrated in a new version.
3. Then: `check-tiers.yaml` moves `level.frames` and `risk.measured` to `hard` and
   `level.critic` and `risk.reward` to `quality`; `quality-floor.yaml` makes
   `floor.level_design` and `floor.risk_reward` release `blocker`s without
   `required_only: passed`; the step holds by default; and `quality-policy.yaml` adds
   `level-design` to `floor.required_steps`, with `development_when` entries for a `baseline`
   critic and an installation's rubric.

Until then an installation that has both may set `factory.leveldesign.hold: true`.

## Calibration

Every bar in both reference files is `basis: proposed`. The rubric records a reading of the r1
builds of the two 2026-10 validation runs. Those builds have no `play.policy`, so the
risk-reward bars have not been measured on a real build. Recalibrate in a new version of the
file as verdicts accumulate.
