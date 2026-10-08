# The content-sufficiency module

`scripts/wgf_sufficiency/` registers the `content-sufficiency` step type. In `new-game`
(workflow version 9) it runs after `visual-qa` and before `review`. It answers one question
about the build that production-quality and visual-qa passed: **does the built game carry
the content its quality tier asks for?** It counts the content on the build, not on the
design and not by file counts:

- the content data file the played commit ships (`public/content/units.json`);
- what the play probe reported while the playability bot played the build: the units the
  traverse played in order, and every unit the survey entered through the probe's unit link.

It holds what it counts to the bars of `core/reference/quality-benchmark.yaml` at the
design's quality tier (`content`, `progression`), the larger of each and the genre family's
own bar (`core/reference/genre-models.yaml`), and to the design's own commitments. How each
quantity is measured, who owns a failure, its severity and its route are data:
`core/reference/content-sufficiency.yaml`. No bar is written in code, and nothing branches on
a family or a game.

The benchmark is the copy the run pinned when it started (new-game `pinned_references`,
`scripts/wgflib/workflow/references.py`), the same copy the quality gate scores against: an
edit to `core/reference/quality-benchmark.yaml` made while a run is going applies to the next
run, never to this one's build. A run that pinned nothing reads the live file. Before WS-13
the step read the live file, so a bar lowered mid-run reached the running build - and through
this report, its quality gate ([quality-consistency-tests.md](quality-consistency-tests.md)).

| | |
|---|---|
| Step type | `content-sufficiency` (`scripts/wgf_sufficiency/step.py`) |
| Measurement | `scripts/wgf_sufficiency/audit.py` |
| Reference data | `core/reference/content-sufficiency.yaml` (1.0.0), `core/reference/quality-benchmark.yaml` (1.4.0) |
| Output | `content-sufficiency-report` (`core/artifacts/content-sufficiency-report.schema.json`, 1.0.0) |
| Tests | `scripts/tests/test_content_sufficiency.py`; end to end, `scripts/tests/test_quality_consistency.py` |

## Why it exists

The 2026-10 validation runs ([quality-gap-audit-2026-10.md](quality-gap-audit-2026-10.md)):

- Every gate passed a 12-level 2D build with one brick kind, no hazards and no bosses.
- Playability passed a 3D build of six straight corridors.
- A person had to play each build to see that it was a demo. The design step now holds a
  design to its tier (WS-2, `content.tier_*`), but nothing held the build to it.
- `content.variety` was a WARNING on both final builds, because neither probe reported
  `entities[].kind`.
- The playability traverse stops after three units.

This step closes those gaps. It is workstream WS-4 of the audit.

## Inputs, output, outcomes

| Input | Used for |
|---|---|
| `playability-report` (required) | `records_dir` and `commit`: the bot's records and the content data file of the commit it played |
| `game-design` (required) | the units owed at the tier, their elements, groups, structures, objective kinds, climax art and durations |
| `scaffold-record` (required) | the title id |
| `title-strategy` (optional) | the quality tier, when the design does not state one |
| `visual-qa-report` (optional) | ordering only: the step runs on the build visual QA passed |

| Verdict | Step result |
|---|---|
| `PASS`: every required check passed | `SUCCESS` |
| `FAIL`: a required check failed | `FAILED`, not retryable. The route is `design-gap` when any failure is the design's (the design is short of the bar), else `develop` |
| `BLOCKED`: playability was blocked or left no records; or the run's pinned benchmark is gone or was edited after the start | `BLOCKED` |

The step never plays the game and never opens the checkout. It reads what playability
recorded of the same commit, so every gate judges one build. The evidence is automation
evidence (`measurement_class: automation-bot`).

## What the playability step records for it

- **The survey.** The `playability` step of `new-game` runs with `with: {survey: true}`
  (the greybox does not). Its bot then enters every unit the design lists, except
  `optional` ones, through `/?wgf-probe=1&wgf-unit=<unit id>`, and lets the oracle play
  each unit for at most `survey.unit_s`. It records per unit:
  - which unit the probe reports;
  - the entity kinds and runtime assets drawn, by role;
  - how many entities of a content role carried no `kind`;
  - the difficulty in force;
  - how long the oracle took to complete it.

  See [playability-module.md](playability-module.md). The probe contract is in the probe
  schema and in [template-contract.md](template-contract.md#the-play-probe-unit-link-and-entity-kinds).
- **The content data file.** The played commit's `public/content/units.json` is kept at
  `<records_dir>/content/units.json`, and with it the **layout source**, when the commit
  ships one: the JSON file under `public/content/` that holds each unit's geometry keyed by
  unit id. It is `public/content/layouts.json` (its `layouts` object, or its root) by default
  (`core/reference/content-sufficiency.yaml` `layout.source`); a data file may name another
  with `layout_source` (`{path, key}` or a path, only under `public/content/`). It is kept at
  `<records_dir>/content/<the same relative path>`.
- **Entity kinds.** While a content unit is in play, every entity of a content role must
  carry `entities[].kind`. This is required by `core/artifacts/shared/play-probe.schema.json`,
  and playability's `probe.valid` checks it.

## Two views, one route

The step measures every quantity twice, on two views of the same units:

- **The build view:**
  - a unit's elements are its data mechanics plus the content kinds the probe showed in it.
    The kinds of the player and the interface are left out;
  - its geometry is the lists in its own `layout` entry in the data file
    (`layout.unit_key`) and in its entry in the layout source - nowhere else (see
    near-identical units);
  - its structure, group, objective kind and art are the data file's values where it
    carries them, else the design's;
  - its difficulty is what the probe reported, else the data's.
- **The design view:** what the design declares - mechanics plus `elements`, `parameters`
  as the layout, `structure`, `group`, `objective_kind`, `art`.

A check fails on the build view. Its route says who must act:

- **`design-gap`**: the design view is short of the same bar, so the design must grow. The
  finding carries a design gap in the prototype-report `design_gaps` shape. The design step
  repairs the design it holds with it, the same way as a gap the developer reports. It reads
  the gaps only from a report that judged the design the run holds now.
- **`develop`**: the design meets the bar and the build does not. The develop brief lists the
  `develop` findings under "Fix first: what the content audit counted on the build".

A check that only the build can fail always routes `develop`: data present, units reachable,
entity kinds, drift.

## The checks

Each check is `PASS`, `FAIL`, `WARNING` or `SKIPPED`. A skip is never a pass. The report
lists every skip in `skipped_checks`, and the step names them in its summary.

| Check | Measures on the build | Bar |
|---|---|---|
| `content.contract` | The design states `build_spec.content` | At the release tier, a design without content fails (`design-gap`). Below it, every check is skipped |
| `content.data_present` | The played commit ships `public/content/units.json` (authored content) | Present and readable |
| `content.units_shipped` | Every unit the design owes at the tier is in the data file, and the count | The tier owes the units of the design tiers it builds (`scripts/wgflib/build_scope.py`, quality-benchmark `tiers[].builds`, the rule the tech plan plans by): `release` the MVP and post-mvp units, `mvp` or no tier the MVP units. Count >= max(`content.units.min_total`, family `units.min_total`) at release, family `units.min_mvp` below it |
| `content.units_reachable` | Every shipped unit was entered, by the traverse in play order or by the survey | All of them. Without a survey, or with a build that ignores the unit link, the units past the traverse are unreached, and the summary says why |
| `content.entity_kinds` | Entities of a content role carry `kind` (first session, act and survey samples) | None without one. Required for authored content; a warning for generated content |
| `content.elements` | Distinct elements; each used in >= N units (elements only climax units use are their set pieces); introduction points; how late the last one arrives | `content.elements.*` |
| `content.combinations` | Share of units whose set of elements no other unit has | `content.combinations.min_distinct_ratio` |
| `content.structure` | Distinct structure kinds; share of near-identical units, on the units' geometry | `content.structure.*`. SKIPPED as `UNMEASURED` when units without geometry could carry the repeated share past `max_repeated_layout_ratio` |
| `content.groups` | Groups, units per group, and every group after the first bringing an element the player has not met. The same elements with only cosmetic change fails | `content.units.min_groups`, `min_units_per_group`. Skipped where the family has no `budget.group_kind` |
| `content.difficulty` | Axes that escalate first unit to last; runs of units that change only their numbers; relief | `content.difficulty.min_escalating_axes`, `relief_every_units`, genre-models `variety.max_consecutive_scaling_only_units` |
| `content.objectives` | Objective kinds (`objective_kind`, else the normalized objective), plus the design's secondary goals; the share of the most common kind | `content.objectives.*` |
| `content.climax` | Every group closes with a climax unit where the family names a milestone. Climax units each name their own art, and no two share one. The build does not draw two climax units with the same assets | `content.difficulty.min_climax_per_group`, `presentation.assets.distinct_climax_art` |
| `content.progression` | Gated unlocks on the built content: the data file's `unlocks` entries that open a unit the build ships, or a group one of them is in, behind a stated `after` or `condition`, and its units carrying `unlock`. An entry opening nothing shipped, or with no condition, is void and listed. A data file that states none is a flat list: 0, whatever the design's progression steps say (the design's count only decides the route) | `progression.min_gated_unlocks` |
| `content.playtime` | Designed play of the shipped units. The oracle's measured durations are reported, not judged: a perfect player is a lower bound | `content.units.min_total_designed_s` |
| `content.drift` | Every shipped unit carries the design's commitments: `index`, `objective`, every mechanic, and `group`, `structure`, `objective_kind`, `purpose`, `elements` and `art` wherever the data states them | No departure |
| `content.introductions_one_at_a_time` | (1.5.0, lesson L29) The shipped units in the design's index order, each as units.json states it: after the opening unit, none debuts more than one element - what it states it `introduces` (an element and the mechanic it stands for are one introduction), or, for a unit stating none, every element and mechanic no earlier shipped unit named. The design rule of the same id (design-consistency-rules.yaml) counts the design; this counts the build, so a design that paces its introductions and a build that does not FAILs (`develop`; `design-gap` when the design itself debuts two at once). A content data file that names no shipped unit's elements or mechanics is SKIPPED as unmeasured, never a pass. Hard tier | at most one debut per unit after the first |
| `content.regression` | Only when the design records an existing-content floor (`existing_content`: the run adopted a repository that already shipped a game). The build's units, groups, climax units and elements, each counted by the method the floor was counted with (`core/reference/brief-commitments.yaml` `existing_content`), and every shipped unit id | None below the floor, no shipped unit gone. A failure says `QUALITY REGRESSION`; it routes `design-gap` when the design itself plans below the floor, else `develop`. Absent - not skipped - when the run adopted nothing. When the adopted checkout shipped no content data file the floor is the probe floor the playability-report carries (`source.method: probe`): a build with a content data file is counted on it, one without through the probe; until that floor is measured the check is SKIPPED as `UNMEASURED FLOOR`, which the quality gate holds as a blocker (`floor.existing_content`) |

A `content.regression` failure is a blocker, so the report's verdict is FAIL, and the
quality gate's `floor.content_sufficient` holds the content dimension below its floor: the
gate fails with `QUALITY REGRESSION` ([quality-gate-module.md](quality-gate-module.md)).

**Near-identical units.** Units are compared on their **geometry**
(`scripts/wgf_design/layouts.py`), and geometry comes only from a **declared place**:

- in the build, each unit's own `layout` entry in `public/content/units.json`
  (`core/reference/content-sufficiency.yaml` `layout.unit_key`) - an object such as
  `{"width": 8, "segments": [...]}`, or a list - and its entry in the layout source
  (`public/content/layouts.json` `layouts`, keyed by unit id, or the file the data file names
  in `layout_source`). A game may use either or both: a 3D course game ships each course as
  its unit's `layout` and no layouts.json;
- in the design, each unit's `parameters` (game-design `units[].parameters`).

No other key of a unit counts: a `tags` list, a `parameters` block or any other list beside
the layout is not geometry, so adding one cannot turn an unmeasured check into a measured one.

Inside a declared layout, the geometry is its **sequences**: every outermost list - a track's
segments, a grid's rows, a wave list, a board's cells, a spawn table - wherever it sits and
whatever its container is called (`segments` renamed `pieces` is the same course). Items are
compared by value: a record keeps its own field names, and 30.0 is 30. A scalar outside every
list (a width, a par time, a speed, a flag, a word) is tuning: the same layout at another
difficulty, and a key the game may never read.

Similarity is how much of the smaller layout the larger one holds, in order: each sequence's
items are matched to one sequence of the other (longest matching blocks, pairs one to one,
the best first), over the item count of the smaller layout. A copy of another unit's course
padded with an unrelated list (a 40-piece `decor`) is therefore still a copy. Two units are
the same unit with other numbers when either is true:

- one's geometry is wholly inside the other's (similarity 1.0: identical, renamed, padded),
  whatever the units are called;
- they share their structure kind, their element combination and their objective kind, and
  their geometry is at least `layout.near_identical_similarity` (0.85) alike.

A design unit is also repeated when another design unit has its structure, its elements and
the same parameter values, whatever its geometry says - the identity the design check had
before geometry, so the design side is never looser than it was.

A build unit whose declared layout holds no list has **no geometry**: it is *undetermined*,
never repeated. Its scalar names are no evidence of identity: under content-sufficiency 1.2.0
a unit's "layout" was the set of its parameter names, so two different courses that both
carried `par_s`, `limit_s`, `gems` were flagged near-identical, and naming a parameter nothing
reads "fixed" it. Adding, renaming or removing a scalar key changes no verdict. The repeated
share is held to `content.structure.max_repeated_layout_ratio` on the units with geometry;
while the undetermined units could carry it past the bar (each repeating a unit not yet
repeated - the report's `repeated_ratio_at_most`, with the units in `undetermined`), the check
is SKIPPED as `UNMEASURED`, never a pass: the quality gate holds a skipped content-sufficiency
check at the release tier (`floor.sufficiency_measured`). The developer's fix is to ship each
unit's geometry as data in a declared place. Measured repetition over the bar still fails,
routed by the design view as every by-design check. The design step's
`content.tier_structure` applies the same rule to the design's `units[].parameters`, so a
design gap is not closed by renaming parameters.

**What this does not establish.** The judge reads the declared geometry; it does not verify
that the game builds each unit from it. A `layout` the game never reads would be measured all
the same. What holds that is the develop contract - the unit is built from its `layout` entry
loaded at boot, and nothing in `src/` hard-codes a unit (the develop brief) - and the play
probe's survey, which enters every unit through its unit link and records what it drew there.
There is no runtime check that the drawn geometry matches the declared one.

**Generated content** (`parametric`, `procedural`). The units listed are representative, so
no unit list is counted, and every unit check is skipped with that reason. Entity kinds are
still measured, as a warning.

**Tiers.** `release` holds every bar above. `mvp`, or no tier, holds these checks:

- the family's MVP unit count;
- that every MVP unit is shipped and reachable;
- entity kinds;
- drift.

Each other check is skipped and names the bar its tier does not state. The golden runs are
`mvp` runs ([golden-runs.md](golden-runs.md)), and their designs are endless (parametric)
content, so they pass with skips.

## Findings

Each `FAIL` or `WARNING` check becomes one typed finding in the report's `findings`. The
WS-8 finding contract (specialist routing, WS-7 scorecard) reads the same fields:

| Field | Value |
|---|---|
| `id` | `content-sufficiency:<check>` |
| `check` | the check id |
| `dimension` | `content`, `level-design`, `difficulty` or `progression` (reference data) |
| `severity` | `blocker` or `major` for a failure (reference data); `minor` for a warning |
| `summary` | what was counted, against which bar |
| `observed`, `bar` | the measurement on both views, and the bar |
| `owner` | `game-design` for a design gap, else the check's discipline: `level-design` or `gameplay` |
| `route` | `design-gap` or `develop` |
| `evidence` | the design's own shortfalls, when the route is `design-gap` |
| `design_gap` | for `design-gap`: `{field, question, assumed: null, severity: blocking}` |

## Workflow

- `develop` gains the budget `content-sufficiency.develop: 2`.
- `design` gains `content-sufficiency.design-gap: 1`. A design repair runs tech-plan, G3,
  init and the greybox again, as for a gap the developer reports.
- Visit limits grow to match: design 4, greybox 6, develop 24, and every later loop step 24.
- The engine is unchanged: routing is data.
- `--mock` runs replace the step with a placeholder. `{"content-sufficiency": ["develop"]}`
  or `["design-gap"]` scripts a failure routed there.

## What it does not claim

- It does not check that the content is fun, readable or well paced. Playability, visual QA
  and people judge that.
- The oracle's durations are a lower bound on playtime, so they are reported and never judged.
- Gated unlocks are counted on the content data the build ships. The probe's survey enters
  every unit directly, as a level select would, so it cannot show that a gate holds in play;
  that a stated gate is enforced is review's and playability's to judge.
- A unit the survey could not enter is unreached. The step does not tell a missing unit
  link from a missing unit; the summary names the survey's own account.

## Not wired yet

- G4 is not decided on this report: `gates.yaml` G4 `required_artifacts` does not list it,
  and the release step does not refuse a build without a passing report. The quality
  scorecard (WS-7) is the planned consumer.
- A release-tier run plans and builds the post-mvp units before G4 (WS-3, the tech plan's
  `dev_plan.build_scope`); a build that still ships only the MVP units fails
  `content.units_shipped` and routes `develop`. That is a true finding: the build is short of
  the design.

## Running it outside a run

The audit is a function of three JSON documents:

```python
import sys
sys.path.insert(0, "scripts")
from wgf_sufficiency import audit
result = audit.audit(design, strategy, data, records)  # data: units.json; records: {project: {test: record}}
for check in result["checks"]:
    print(check["id"], check["status"], check.get("route"), check["summary"])
```

`records` is a playability `records_dir` read with
`wgf_sufficiency.step.load_records(dir, ["desktop", "mobile"])`.
`wgf_sufficiency.step.read_data(dir)` reads the content data file kept beside the records.
