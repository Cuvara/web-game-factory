# The level-design step: the level critic and risk and reward

`level-design` (workflow 19 of `core/workflows/new-game.workflow.yaml`, module
`scripts/wgf_leveldesign/`) runs after `content-sufficiency`. Content sufficiency counts what a
build carries. This step asks whether the units are *designed*, and whether an optional risk
exists and pays. It writes a `level-design-report` (`core/artifacts/level-design-report.schema.json`).

## What it reads

- **The playability step's records.** With `with: survey: true`, the survey captures every
  surveyed unit at its start, middle and end (`level_frames`, under `<project>/level/`, with
  each frame's sha256 and the entities the probe reported). With `with: risk: true`, the risk
  test plays sampled units under the game's own oracle policies `safe` and `greedy` (the
  probe's optional `play.policy`) and writes `risk.json`. What the risk test plays (projects,
  units, attempts, windows, policies) is `core/reference/play-realism.yaml` `risk`, the one
  source both steps read.
- **`core/reference/level-design-rubric.yaml`.** The moments, the unit sample, the dimensions
  (play space, identity, route choice, reveal, climax, distinct from the previous unit), the
  blockers, the bars, and what the `baseline` critic measures.
- **`core/reference/risk-reward.yaml`.** The reward and failure metrics, and the bars greedy
  must clear over safe.

The run pins all three reference files (`pinned_references`). A rubric configured by path
(`factory.leveldesign.rubric`) is read as configured and makes the run `development`
(`core/reference/quality-policy.yaml` `development_when`).

## Checks

| Check | Tier (`check-tiers.yaml`) | Means |
|---|---|---|
| `level.frames` | hard | every sampled unit has its start, middle and end frame |
| `level.critic` | quality | every unit at or above the rubric's bars, no blocker, the mean at its bar |
| `risk.measured` | hard | every sampled unit played under both policies with a reward reading |
| `risk.reward` | quality | greedy earns measurably more, at a measurably higher failure rate, on the rubric's share of units |

`level.*` is not reported for a design that authors no units. `risk.*` is always reported.
The quality floor reads them as `floor.level_design` and `floor.risk_reward` (blockers at the
release tier). Triage routes their findings to the level designer (`develop`) or to design
(`design-gap`) (`core/reference/specialist-routing.yaml`).

## Outcomes

At a strict tier (quality-policy `skipped_checks`: the release tier as shipped), every check
is required and unmeasured is not passed. A failure is FAILED, routed `design-gap` when a
failure routes there and otherwise `develop`. No judge configured is BLOCKED. Below that tier
the same results are reported as WARNING or SKIPPED and the step succeeds.

## The critic

`factory.leveldesign.judge` in `workspace/config/factory.yaml` (`scripts/wgf_leveldesign/settings.py`):

- `none` (shipped): nothing is judged. SKIPPED below the release tier, BLOCKED at it, the same
  as visual QA's judge.
- `command`: an agent able to read images, run read-only and isolated like visual QA's judge.
  Placeholders are `{frames_dir}`, `{brief}`, `{verdict}` and `{prompt}`. The frames it reads
  are copies, verified against the recorded sha256.
- `baseline`: no agent. It measures what entity boxes and frame signatures can, and carries a
  person's approved scores for a unit whose frames match the approved ones. Everything else is
  left unmeasured. A baseline critic makes the run `development`.

## Calibration

Every bar in both reference files is `basis: proposed`. The rubric records a reading of the r1
builds of the two 2026-10 validation runs. Those builds have no `play.policy`, so the
risk-reward bars have not been measured on a real build. Recalibrate in a new version of the
file as verdicts accumulate.
