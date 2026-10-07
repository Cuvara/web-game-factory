# Content and level design

**Serves** `genre`, `genre.session_profile`, `build_spec.content.unit_kind`,
`build_spec.content.units[]`, `.content.generation`, `build_spec.difficulty.axes`,
`.difficulty.model`, `build_spec.mastery`, `build_spec.progression.model`,
`build_spec.content.quality_tier`, `.content.elements`, `.content.groups`,
`.content.secondary_goals`, the units' `group`, `structure`, `elements` and `objective_kind`,
`references`, the units' `beat`, `.content.signature_moments`, `.content.meta_systems`, a
secondary goal's `par`, and the strategy's `prototype_must_prove` and
`concept.content_model.budget`.

A loop worth repeating still needs somewhere to happen. The content units are that
somewhere: the levels, waves, tracks, encounters, scenarios, shifts or run-segments the
player meets, in order. A prototype carrying one of them proves the verb and nothing else —
not whether the game holds up as it changes, which is what G4 is asked to judge.

The bars per genre family are data in `core/reference/genre-models.yaml`: the unit kinds, the
difficulty axes, the shape of win and loss, how many units the MVP and a release carry, what
counts as variety, and how mastery shows. The design step checks a design against its
family's entry; the developer brief turns the unit list into a content table the build reads
from `public/content/units.json`; playability traverses that table from outside. Every number
below is read from that file or is a default with a reason.

## What a content unit is

One thing the player meets, with one purpose. Not a slice of a tuning curve and not a
difficulty tier: a unit is the thing a player would name — "the level with the moving
blocks", "the wave with the shielded rushers", "the night shift".

Each entry in `build_spec.content.units[]` is identified by `id` and `index` — the one name
the design, the data file, the tech plan's tasks and the QA traversal all use for the same
thing — and states its `purpose` (`teach`, `test`, `twist`, `breather`, `climax`, `bonus`),
its `objective`, the `mechanics` in play and which of them it `introduces`, a `difficulty`
value on each of the family's axes, `expected_duration_s`, `success`, `failure`, the
`acceptance[]` that makes it built, the `variation_from_previous[]` dimensions separating it
from unit n−1, and its `tier` — `mvp` for what the prototype builds and G4 judges. The
schema is authoritative for the fields; the rest of this playbook is how to fill them.

A unit the design cannot state a purpose and an objective for is not a unit. It is a
parameter change, and it belongs inside one.

## The purpose arc

`units.min_mvp` is 3 for arcade, racing and survival; 4 for shooter, strategy and
simulation; 5 for platformer; 6 for puzzle. A 4–6 unit MVP sequence spends them like this:

| # | `purpose` | What it is for |
|---|---|---|
| 1 | `teach` | One mechanic, shown safely. Failure almost impossible, no timer worth fearing. |
| 2 | `test` | The same mechanic under pressure. Nothing new arrives — this is where the player finds out they learned it. |
| 3 | `twist` | One new mechanic or rule that recombines with the first, so the old skill is re-read rather than replaced. |
| 4 | `breather` | Difficulty dips. The safe place to introduce the next thing, and where the player notices they are improving. |
| 5 | `climax` | The hardest MVP unit: every mechanic introduced so far, combined, at the top of the ramp. |
| — | `bonus` | Off the spine. Optional, skippable, never the only home of a mechanic the spine needs. |

A 3-unit MVP runs `teach`, `test`, `twist`, with the climax in the last unit's late phase; a
breather is not required before `relief_every_units` (3 units on the `casual` session
profile, 5 on `standard`). Above the MVP, repeat the arc per block, each block starting from
a higher floor. Two `teach` units in a row means the first did not teach; two `climax` units
in a row means neither is one.

A climax is met as a new antagonist or set piece, so it names its own art: `art` lists the
`build_spec.assets` ids (or a counted asset's variant ids, `boss-2`) that draw what is
particular to the unit. Four bosses drawn as one sprite tinted per world read as one boss
four times; at the `release` tier every climax unit has a drawing or model no other climax
unit shares, and none is a recolour of another's (`core/reference/quality-benchmark.yaml`
`presentation.assets.distinct_climax_art`, checked by the assets step). Plan a counted
asset (`count` = the number of climax units) or one asset per climax, and budget the art.

## Introduce, then reuse

Every mechanic the MVP declares appears in at least `mechanic_reuse_min_units` units (2)
*after* the one that introduces it. A mechanic used once is a cutscene with inputs: the
player never gets to be good at it, and the timebox paid for it anyway.

- Introduce one mechanic per unit at most, during a `teach`, a `breather` or the opening of a
  `twist` — never on a peak.
- The reuse recombines rather than repeats: the mechanic meets a different other mechanic, a
  different layout, or a different objective. The climax reuses everything; a mechanic that
  cannot appear there was decoration.

## Variety, not scaling

Consecutive units differ on at least `min_dimensions_changed_between_units` (1) of the
family's variety dimensions, named in `variation_from_previous`. The dimensions are the
family's own list; `introduces` counts as one.

**Scaling** is a number that moved: "level 2 has 12 HP instead of 10", 14 enemies instead of
11, a lap target half a second tighter. It is legitimate — a ramp is made of it — but it is
not variety. A unit whose only change is a number, with no new mechanic, the same objective
and no declared dimension, is scaling-only, and at most
`max_consecutive_scaling_only_units` (2) may sit in a row.

**Variation** changes what the player has to do: a different objective, layout motif, mix of
things to deal with, rule in force, or pacing. At most `max_identical_objectives_ratio`
(0.5) of the units may share one objective — a game where every unit says "survive" has one
unit and several durations.

## Difficulty as values on named axes

Difficulty is data per unit, on the axes the family names (`build_spec.difficulty.axes`,
drawn from `core/reference/genre-models.yaml`), each in 0..1. A design may not invent an
axis, and every unit carries a value on every axis of its family.

- **Escalation.** Every axis marked `escalates` ends higher than it starts across the units
  the design's tier ships: the MVP units at tier `mvp`, every release unit in order above it.
  Above `mvp` the MVP is the start of that curve - one axis raised per casual unit cannot
  raise every axis in three units - so it climbs (at least one escalating axis rises, none
  ends lower than it starts) and the release carries the rest. An axis that never moves is
  not a difficulty axis for this game; say so rather than listing it flat.
- **One or two axes per unit.** A unit raises at most `max_axes_raised_per_unit` axes over the
  previous one: 1 on the `casual` session profile, 2 on `standard`. Stacked increases read as
  unfair even when each is small.
- **Relief dips, not regressions.** A breather dips an axis by no more than `relief_dip_max`
  (0.35) of its previous value, and the ramp recovers within `relief_recovery_units` (2). A
  deeper dip reads as the game getting easier, which reads as the game ending.
- **Sawtooth across units.** Climb, release at a milestone, climb from a higher floor. A
  monotonic ramp exhausts; a flat one bores (`core-loop-and-difficulty.md`). The onboarding
  plateau is unit 1, not a special case inside it.
- **Measured, not asserted.** An axis marked `probe: required` is reported by the build as
  `metrics.difficulty.<id>`.
- **Copied, not re-derived.** A value in `public/content/units.json` may differ from the
  design's by at most `implementation.difficulty_tolerance` (0.05) absolute.

## Objectives, success and failure

Each unit states its objective, `success` and `failure` in the player's words: "clear every
crate before the timer", "hold the gate for five waves", "finish under 48 s". Not "reach
`state=cleared`", and not "difficulty 0.6".

- Where the family's `win`/`lose` is `per_unit: true`, every unit states its own and both are
  reachable inside that unit. Where it is not — an endless arcade or survival run — the units
  state the segment's objective and the run states win and loss once.
- The player is told the objective before the unit starts, and told which clause they missed
  when they fail. A loss the player cannot attribute is a defect, not a difficulty.
- A `finite` game has an actual ending: the last unit's success is the game's success.

## Acceptance criteria a bot can check

`acceptance[]` carries at least `acceptance_min_items` (2) lines per unit, and no two
acceptance lines anywhere in the design may be closer than `acceptance_max_similarity` (0.8)
— near-duplicates mean the criteria were copied, and a copied criterion checks nothing. The
reusable shapes, all decidable from outside the game:

- **Reachable.** The unit is entered from the previous one by playing, with no debug jump.
- **Objective shown.** Its text appears on screen before play, readable at portrait size.
- **Win reachable.** Competent play reaches success within `expected_duration_s`, itself
  within the family's `max_unit_s` (90 s on `casual`, 240 s on `standard`).
- **Loss reachable.** Deliberately poor play reaches the failure state, and restart returns to
  a clean unit.
- **Data matches.** The unit exists in `public/content/units.json` under its `id`, with its
  mechanics and its per-axis difficulty values.

"Feels fair" is not acceptance. "The level is fun" is not acceptance.

## Authored, parametric or procedural

`build_spec.content.generation.mode` says how the units come to exist. Every family allows
`authored` and `parametric`; `arcade` and `survival` also allow `procedural`. Whichever is
chosen, **every unit is listed in `build_spec.content.units[]` with what makes it
different** — the mode changes who writes the numbers, never whether they are stated.

- **Authored.** Each unit designed by hand. Right where the solution *is* the content: puzzle
  levels, platformer layouts, a tower-defense map. Budget
  `implementation.content_unit_hours` (1.5 h) each, in tasks of `implementation.task_batch` (3).
- **Parametric.** A table of named parameters generates the units, and the table is the
  authored thing. Still list every unit: its row, purpose, objective and what it varies. A
  parametric ramp with no unit list is a difficulty curve pretending to be content.
- **Procedural.** The unit is a band of a generator — a seed range, a pattern pool, a spawn
  table. List each band with its purpose, objective, axes and acceptance, and state the
  invariants the generator may never break (always solvable, always a visible gap, never two
  elites at once). An endless game's ramp *is* a parametric unit sequence; it is not an
  excuse to have none.

## The release tier

The strategy states the run's quality tier (`concept.content_model.quality_tier`) and, at
`release`, a content budget: units, groups, distinct elements, introduction points and
designed play, each the larger of the family's genre model and
`core/reference/quality-benchmark.yaml`. The design states the same tier in
`build_spec.content.quality_tier` (never a lower one) and is held to that budget and to the
benchmark's `content` bars at the tier, the larger of the two (the `content.tier_*` rules). The
benchmark's bars were measured on releases a person judged shippable; the unit count alone
did not separate them from the builds that were not, so the bars count what the units are
made of. Every count is mechanical, so declare what is counted:

- **Elements.** List what the units are made of beyond the mechanics in
  `build_spec.content.elements` — each obstacle, hazard, enemy, target, block or segment kind
  that changes what the player does, of the family's `budget.element_kinds` — and name the
  ones each unit uses in its `elements`. A unit's mechanics count too. A number-only change
  (speed, count, width) is never an element.
- **Introduce, then combine.** Spread the introductions: a new element first appears at many
  points, the last one in the final third, and every element is used again after it arrives.
  Most units use a combination of elements no other unit uses: later units combine what
  earlier ones taught instead of repeating a set at higher numbers.
- **Structure.** Give each unit its `structure` — one id shared by every unit built the same
  way: a static field, a moving field, a path with turns, an arena, a climax. A release has
  several structure kinds, and few units repeat another's layout (structure, elements and
  parameters).
- **Objectives.** Give each unit its `objective_kind` (clear-all, survive, reach-exit,
  collect, beat-time...). A release asks for more than one kind, and no one kind fills most of
  its units. A scored secondary goal — stars, collectibles, a par time — in
  `build_spec.content.secondary_goals` is a kind of its own.
- **Groups.** Where the family presents units in groups (`budget.group_kind`: world, chapter,
  cup, region), name each unit's `group` and list the groups in `build_spec.content.groups`.
  A group's units run one after another, every group brings an element the player has not
  met, and where the family names a `budget.milestone` each group closes with it — a unit of
  purpose `climax`. The milestone is the family's own: a capstone level, a cup final, a siege
  map, a set-piece encounter. A boss is one milestone, not the default. Name what each
  milestone unit draws of its own in its `art` (its antagonist or set piece), one drawing per
  milestone: the assets step holds climax units to distinct art. A family whose units are one
  sequence (`group_kind: null`) is not asked for groups.
- **Designed play.** The units' `expected_duration_s` add up to the budget's designed play:
  more units, not longer ones.
- **Difficulty asks for new skills.** Over every unit of the release, not only the MVP: more
  than one axis escalates from the first unit to the last, consecutive units change the
  family's variety dimensions, a run of units that differ only in their numbers (the same
  objective kind, elements and structure) is short, and relief arrives on a regular beat.

A generated design (`parametric`, `procedural`) lists representative units, so it is held on
what it can state — elements, structure kinds, objective kinds, groups and designed play —
and the order, combinations and difficulty sequence are measured on the build. At tier `mvp`
the benchmark states no bars and the family's own bars apply. A design short of its tier
fails with a finding that names the rule, what is short and by how much; repair the content,
never the tier.

## Beyond the counts: references, beats and moments

A design can meet every count above and still play like a genre's first draft: a first unit
that teaches six mechanics, a climax that is the same unit wearing a new drawing, risk and
reward that live only in the prose, five minutes of designed play, and nothing compared with
the games a player already knows. At the tier `core/reference/quality-benchmark.yaml`
`design` states its bars for (`release`), the design is also held to these (the `design.*`
rules, `scripts/wgf_design/beats.py`); below it they are advice, recorded on the result.

- **References first.** Read the teardown records of the genre's leaders the strategy's
  research carries (`research.competitors`, depth `teardown`; how to write one is
  `competitive-teardown.md`). Fill `references`: the games, and for every dimension the bars
  name — core verbs, signature moments, set pieces per world, content duration, meta systems —
  what they do and the design line that answers it (or deliberately departs, `departs: true`,
  saying why). Never name a game the research did not tear down. When it carries too few,
  write `references.status: unknown` with the reason: the run goes back to research for the
  records, which a designer cannot write without playing the games.
- **A beat per unit.** `purpose` is the beat kind; `beat` is what it promises. `claim` is
  falsifiable ("a first-time player clears it without losing a life") and `test` names the
  observation that would falsify it — the bot's attempts, a probe metric, a playtest.
  `decision` is the choice the player makes most often there, as a choice rather than an
  input, and how often it recurs in seconds: a few seconds, not a minute.
- **One mechanic at a time.** A unit introduces one mechanic at most — the game's first unit
  may add the core verb (`progression_role: core`) — and introduces it in a `teach`, a
  `breather` or a `twist`, never on a `test` or a `climax`. A `teach` unit is no harder on any
  axis than the breather before it: it is the safe place to meet something new.
- **A world has a shape.** Every group (the whole sequence, without groups) has at least one
  `twist` and ends in a `climax`. A climax declares in `beat.climax` what changes mid-unit —
  a phase, the state, the rules, the arena or the objective — and what the player does
  differently after it. Its own drawing (`art`) is still owed; it is not the climax.
- **Risk against reward, per world.** At least one unit in every group offers a harder line
  for a payoff (`beat.risk_reward`): the narrow route for the gold star, the greedy chain for
  the multiplier.
- **Signature moments.** Declare in `build_spec.content.signature_moments` what a player
  retells — an `end-of-unit-payoff`, a `combo-escalation`, a `rare-spectacle` — each with what
  triggers it, and build each into a unit (`beat.signature_moment`).
- **Meta systems, decided.** List in `build_spec.content.meta_systems` every system above the
  units the genre's leaders use — currency, upgrades, cosmetics, achievements, missions,
  collections, unlocks, leaderboards, streaks, daily challenges — each included for what the
  player gets from it, or declined with why. Whatever the meta loop persists is included.
- **The market's designed play.** A finite (level-based) release carries what the genre's
  leaders carry — 30 minutes and more, a hypothesis until teardowns measure it — in more
  units and more to do in each, not slower ones.
- **Par is calibrated on people.** A timed secondary goal (par, gold, star time) says in `par`
  whether its threshold comes from a person's playtest or is the bot's time scaled by at least
  the benchmark's ratio: a bot clears faster than a first-time player.

## Mastery

`build_spec.mastery` names the family's mastery `model` and what shows the player got better:

| Model | Families | What a better player does |
|---|---|---|
| `reading` | puzzle | Sees the solution before moving |
| `execution` | platformer, arcade | Hits the input windows |
| `routing` | shooter | Picks the order to deal with things |
| `planning` | strategy, survival | Commits early to something that pays later |
| `optimisation` | racing, simulation | Shaves the same run closer to its limit |

The family lists the `signals` shown in play or on the result card — best lap, moves left,
leaks, accuracy, survived seconds — and at least one is visible during play, not only after
it. `mastery.statement` says in one sentence what a better player does differently: not "gets
a higher score" but "banks gold through wave 3 to afford the splash tower before wave 5".

## By family

`core/reference/genre-models.yaml` is authoritative for each family's unit kinds, axes, unit
counts and variety dimensions. What follows is how to spend them.

**Puzzle.** Unit: `level`. Axes: `depth`, `move-limit`, `board-complexity`, `piece-variety`.
MVP 6, release 20. Each level is a designed situation with a clean solution the designer
knows: teach one rule on an open board, test it under a tight move budget, twist with a
blocker that invalidates the obvious line, breathe on a wide board that shows the new rule
off, climax on a board needing both rules in sequence. **Trap:** random boards instead of
designed solutions — a generated board has no intended insight, so `depth` is noise and the
player is tuning luck.

**Platformer.** Unit: `level`. Axes: `precision`, `timing`, `hazard-density`,
`spatial-complexity`. MVP 5, release 12. One motif per level — a hazard on a cycle, a
vertical shaft, a collapsing floor — introduced on flat safe ground, then combined;
checkpoints are expected, so a long level is allowed to be hard. **Trap:** smaller platforms
as the only ramp — shrinking the landing raises `precision` and nothing else, so level 5 is
level 1 with less margin.

**Arcade.** Unit: `run-segment`, `round` or `wave`. Axes: `speed` (probe-required), `density`,
`variety`, `precision`. MVP 3, release 6. Segments of a run: an opening that reads at a
glance, a middle that adds one pattern kind, a late band that mixes patterns rather than only
going faster, each segment introducing at least one new kind. **Trap:** numbers up — speed
and density rising forever over the same three obstacles, so the run ends at the player's
reaction limit instead of their reading limit. Cap the intensity and vary the mix.

**Shooter.** Unit: `wave` or `encounter`. Axes: `enemy-count`, `enemy-variety`
(probe-required), `composition`, `resource-pressure`. MVP 4, release 10. Each encounter asks a
different question: one kind to learn the weapon, a second that punishes standing still, then
a composition — shield plus rusher, sniper plus swarm — where the answer is an order, not more
shooting. **Trap:** ten encounters that are the same fight with more enemies; if
`composition` never rises, `enemy-count` is a longer wave 1.

**Racing.** Unit: `track` or `lap`. Axes: `route-complexity`, `opponent-skill`, `hazards`,
`time-target`. MVP 3, release 8. Each track has a shape the player can describe and a corner
they will learn: a fast open circuit, a technical one with two hairpins, a mixed-surface
route where the braking points move. **Trap:** reskinned tracks — a new palette on the same
layout teaches nothing, and `optimisation` mastery has nothing new to optimise.

**Strategy.** Unit: `map`, `wave` or `scenario`. Axes: `decision-density`,
`economy-pressure`, `opponent-escalation` (probe-required), `composition`. MVP 4, release 10.
Each map or wave block forces a different build: a path that rewards range, a split path that
punishes one strong cluster, an armoured mix one tower type cannot answer. **Trap:** stat
inflation — more HP and speed each wave while the composition stays single-kind, so the player
repeats one opening and the game reduces to whether the numbers permit it.

**Survival.** Unit: `run-segment`, `wave` or `encounter`. Axes: `spawn-rate`
(probe-required), `enemy-variety`, `elite-frequency`, `build-pressure`. MVP 3, release 8.
Segments that change what the build must answer: a swarm segment, a ranged segment, an elite
window, each with a new kind on screen. **Trap:** spawn rate only — more of the same enemy
makes the run longer and the upgrade choice irrelevant; `build-pressure` exists only when
different segments punish different builds.

**Simulation.** Unit: `scenario`, `shift` or `round`. Axes: `demand-rate`,
`resource-scarcity`, `concurrency`, `decision-density`. MVP 4, release 10. Each scenario has
a target and a constraint that changes the plan: a rush hour, a staff shortage, a day with
one station broken. **Trap:** a few buttons and counters — numbers rising on a screen with no
scenario target, no scarcity and nothing to juggle is a spreadsheet; `concurrency` is what
makes it a game.

## Failure modes

- **One unit dressed as a game.** A single endless board with a difficulty ramp, shipped as a
  prototype. It cannot show whether the loop survives change, so G4 has nothing to judge.
- **Scaling as content.** Twelve units whose only difference is a number. Two in a row is
  allowed; a game of them is one unit with a volume knob.
- **Units in the design, not in the build.** A unit list the developer re-typed, approximated
  or skipped. The data file is the contract: a missing id, or a difficulty value outside the
  0.05 tolerance, is a design-fidelity blocker, not a tuning note.
- **Difficulty re-derived in code.** Per-unit values computed by a formula in logic instead of
  read from the data file. It cannot be tuned at a playtest and cannot be reviewed.
- **Introduce-and-abandon.** A mechanic that appears in exactly one unit. Cut it or reuse it.
- **Bonus content first.** Optional units built before the spine is complete, so the MVP has
  six units and no climax.
- **A release that is a prototype.** Twelve units of one element in one list: the count of a
  release, the content of a demo. The tier rules count elements, structures, objective kinds
  and groups for this reason.
- **Acceptance that is an opinion.** "The level is fun", "difficulty feels right". Nothing
  outside the game can decide either, so neither is ever checked.
