# The playability module

`scripts/wgf_playability/` implements the `playability` step type. `new-game` runs it
twice:
- **`greybox-playability`**, after the `greybox` phase of develop, before any asset is
  made. A loop that cannot be played or read is rebuilt with primitives; assets are made
  only for one that can.
- **`playability`**, after `develop` integrates the assets, before `review`. An asset
  that hides the player or darkens the scene is caught here.

Either way, a bot plays the commit from outside, the way a first-time player's device would.

```
init -> greybox -> greybox-playability -> assets -> develop -> playability -> review -> ...
          ▲               │ fail                      ▲              │ fail
          └───────────────┘                           └──────────────┘
                 (with the playability-report: failed checks, and the frames)
```

## Why it exists

A real `/new-game` run produced a three.js game that passed every check: install,
conformance, typecheck, lint, unit, build, smoke, and a review loop. Its owner could not
see or understand it. Played from outside, it:

- rendered at about 4 % brightness;
- lost by itself 2.8 s after play began;
- never showed a shot travel;
- never stated its objective.

Every check before this step was about the code, or about the developer's own tests. None
looked at a rendered frame or played the game. This step does both.

## Inputs, output, outcomes

| | |
|---|---|
| inputs | `prototype-report` (the commit), `game-design` (its `build_spec.experience`), `scaffold-record` (the checkout) |
| output | `playability-report` (`core/artifacts/playability-report.schema.json`, 1.1.0): every check with what was measured and the bar, the captured frames with their hashes, `records_dir` (the bot's raw records, relative to the run directory), the verdict |
| SUCCESS | every required check passed on every viewport |
| FAILED, route `fail` | a required check failed: back to develop, whose brief leads with *Fix first: what the build did when it was played* (each failed check and the frames that show it) |
| BLOCKED | the step could not establish a result: no experience contract in the design, no checkout, the commit would not install or build, the browser would not start. Nothing about the game is claimed |

The route budgets `greybox-playability.fail: 2` (on greybox) and `playability.fail: 2` (on
develop) bound the loops. The third unplayable build blocks the run for a person, like the
other loops (`max_visits_by_route`,
[workflow-engine.md](workflow-engine.md)).

## What it does

The step works in a scratch directory under the run, `<step>/<visit>-<attempt>/` -
`greybox-playability/1-1/`, `playability/1-1/` - so the greybox's frames, which its report
cites, are not erased when the production build is played. It never touches the game
checkout itself.

1. Clones the checkout at the reported commit, detached.
2. Runs `pnpm install --frozen-lockfile --prefer-offline` and `pnpm build`. Every process
   goes through `wgflib.procs`. The game's environment is scrubbed (`wgflib.agentenv`) and
   network access is refused outside localhost.
3. Runs `bot.spec.ts` with the repository's own Playwright against `pnpm preview`. Two
   projects: desktop (1280×720) and mobile (Pixel 5, touch). Each test is a fresh browser
   context, so each one starts as a first session.
4. Judges the recordings (`analysis.judge`) against the design's experience contract and
   [`core/reference/visual-quality.yaml`](../core/reference/visual-quality.yaml).

### The play probe

The bot reads the game's play probe (`core/artifacts/shared/play-probe.schema.json`):
`window.__wgf__.play.snapshot()`. It returns:

- the session state;
- the contract's metrics;
- the entities a player must see, with their screen bounds;
- the inputs available now, as real pointer or key input (`hold_ms` for a held control);
- the `oracle`: the input that succeeds now. It is present only with `?wgf-probe=1`.

The bot acts **only** through real input at the listed positions, never through the
probe. The developer brief embeds the schema, so a developer knows how the build is judged.

### The bot's eight tests, per viewport

- **First session:** opens the game. If the title screen lists a begin input (`play`,
  `start`, ...), the bot presses it. Then it makes no input at all for the idle window,
  `max(experience-rules min_grace_s, the design's grace seconds)`. It records the text on
  screen in the first 3 s of play and any loss.
- **Act:** for each input action listed during play, a frame before and a frame
  `max_ack_ms` after the input.
- **Win:** the oracle plays well. Every rendered frame's entities are sampled for 10 s,
  long enough for a threat that spawns far away to reach the player.
- **Lose and restart:** one success first, then bad play: the **k-th** listed move that is not
  the oracle's, never a pause or settings toggle, with `k` advancing on every press - and
  advancing again when the press before it changed nothing the probe reports (metrics and the
  unit's progress). A direction a wall blocks costs no move and changes nothing, and the first
  live authored puzzle was pressed into it for 85 s and never lost; bad play rotates, so a
  blocked input is tried once, not forever. Every press is recorded in `wrongPresses[]`. On a
  loss, the bot presses the retry the result screen offers, then the ready screen's begin input
  if it lands on one.
- **Pause:** the probe's pause input, else a visible pause button, else Escape. If the
  probe then reports `paused`, the pause screen is measured, then play is resumed. A game
  without a pause is recorded as such; no check here fails on it.
- **Traverse** (only when the design states `build_spec.content`): the oracle plays unit
  after unit. Every sample records which unit is in play, its progress, the difficulty on
  each declared axis (`metrics.difficulty.<axis>`) and the entity kinds drawn. When a unit
  ends in `won` or reaches its progress target, the bot presses the advance input the oracle
  names (`next`, `continue`, ...) - never a jump to a unit the player has not finished. It
  stops at the traverse window, after `max_units` units, or at a second loss, and writes
  `transitions[]`, `per_unit[]` and a frame `unit-<index>-1s.png` per unit.
- **Persist** (only when the design states `build_spec.depth`): the oracle plays until the
  best or the unit reached moves, the page is reloaded, and the probe is read **before any
  input**. Whatever is gone was not persisted.
- **Session** (only with a depth contract): one first session with instant retries, held open
  to the design's own first-session length. Records how long play lasted, each attempt's
  oracle input rate per third of it, when the designed closing beat first arrived, and the
  difficulty in each `endless_window_s` window.

The time budget (`design-depth.yaml playability.time_budget.bot_total_s`) is a hard cap per
viewport. What the first five tests cost is subtracted; the rest is shared between the
traverse, persist and session windows in proportion to what they asked for, and every check
judged from a window that was cut carries `measured.truncated: true` - and, where the
shortfall is the budget's rather than the build's, drops to a warning. The bot's process
timeout is `2 x bot_total_s + 120` s, not a fixed number.

### What every record also carries

The bot records more than this step judges, so that later steps read the same play instead
of replaying it. `production-quality` ([production-quality-module.md](production-quality-module.md))
reads these from `records_dir`:

- `asset_requests`: every response for a URL under `/assets/` (path and status, `null` for
  a failed request), and `runtime_assets`: the body of `assets/assets.json` as the page
  fetched it;
- `assets_loaded`: every runtime asset id any snapshot reported in `assets_loaded`;
- `audio`: every snapshot's `audio` (state, music, playing, measured level) when the probe
  reports one; the first-session record also carries `audio_unfocused` - the level after a
  window blur, the platform mute every portal requires - for the production check
  `audio.plays`;
- the win test's per-frame entity samples are
  `[id, role, visible, x, y, w, h, asset, render]` (the last two `null` when the probe
  does not report them);
- `ui`: the DOM UI measured on each screen state seen - `title` (before the begin input),
  `playing`, `paused`, `won` / `lost`, and `retry` (play after the retry) - each with its
  frame `frames/state-<name>.png`. Per state: every visible interactive element
  (`button`, `[role=button]`, `a`, `input`) with its box, font size and weight, colour, the
  opaque background behind it (own and ancestors' background colours composited; `null`
  when none is opaque or an ancestor paints an image, so only the frame can tell),
  `ua_default` (its computed style equals the user-agent default for its tag, read from a
  blank frame no page stylesheet reaches) and the properties that differ; every visible text
  outside a control, measured the same way; the overlaps between controls and between a
  control and text; the probe's `ui`-role entities; and every entity the probe reported at
  that moment (with `asset` and `render`), so a state frame can be read at an entity's box.

## The checks

| Check | Passes when |
|---|---|
| `probe.present` | `snapshot()` answers. Without it nothing else is judged |
| `probe.valid` | snapshots match the schema and carry the contract's goal, win and lose metrics; with authored content, every playing snapshot reports `content` and its `unit_id` is one of the design's |
| `start.playable` | play begins within `first_30s.playable_s` |
| `start.objective` | ≥ 60 % of the objective statement's content words are on screen in the first 3 s of play |
| `idle.grace` | no loss during the idle window |
| `act.acknowledged` | every action changes ≥ `min_changed_fraction` of the frame by ≥ `min_pixel_delta` luminance; each is measured in play (a pause goes last, and the bot resumes through the game's own resume input before the next action) |
| `win.reachable` | good play reaches `won`. Never degraded to "the metric rose" when the contract states a win; and a design whose genre family wins by anything but a best score, with no `experience.win`, fails here - there is nothing for good play to reach |
| `lose.reachable` | bad play reaches `lost`, and - when the family names a `resource_metric` - that number is seen to fall under the anti-oracle |
| `restart.works` | the retry returns to play within `retry_s` + 1 s, with the goal metric reset; and, when the family says a unit can be restarted from inside it (`reset_in_unit`), a restart pressed mid-unit returns to a clean unit. Reported **BLOCKED** with `measured.reason` "no loss to retry from" when bad play never reached `lost` and nothing offered a retry: this check waits on `lose.reachable`, which fails on its own |
| `entities.visible` | every readable role (player, threat, goal, target, projectile) is visible in ≥ half its samples and, at its largest on screen, covers ≥ `min_area_fraction` of the viewport (median over the role's entities that left during the sample; all of them when none did) |
| `entities.projectile` | a projectile is seen moving for ≥ `min_projectile_frames` consecutive frames |
| `frames.readable` | ≥ `min_lit_share` of pixels lit (luminance ≥ `lit_luminance`), contrast ≥ `min_contrast`, mean ≤ `max_mean_luminance` |
| `page.errors` | no uncaught page error |

### The content, difficulty and depth checks

These hold the build to what the design committed it to *contain*, not only to being
playable. Every bar is data - `core/reference/design-depth.yaml` `playability:` merged with
the genre family's `qa:` block (`core/reference/genre-models.yaml`), read through
`wgflib/genre_models.py` `qa_of()`, plus `genre-models.yaml`'s own `implementation:` block
(`implementation()`), which is what the developer was told to write the unit data to. No number
is in code.

Two rules decide what a failure here may rest on, and both generalise - never a special case
for a family:

- **The bot's budget is not the build's defect.** The bot is asked for a bounded number of
  units (`qa.min_units_traversed` + 1) inside a bounded window, so the unit in play when the
  traverse stops is normally mid-attempt. A unit the traverse never *left* decides nothing
  about completion (`content.win_lose_per_unit` records it as `measured.in_progress`), and a
  capped traversal is not held to the design's whole curve (`measured.partial`).
- **A check is required only where the family's own vocabulary can carry it.** Variety is held
  to entity kinds only where the family asks for a new kind per unit; a time ramp inside one
  run is judged only where the family has a window for one. Elsewhere the number is still
  measured, and reported as a warning naming why it is not a bar. The one thing this costs:
  for a unit-authored family a bad run that ends far too late is a `depth.ramp` warning rather
  than a failure - a bad run that never ends at all is still a `lose.reachable` failure.

| Check | Passes when |
|---|---|
| `content.units_reachable` | authored content: the transitions show units 1..N in the design's order (N = `min(mvp units, qa.min_units_traversed)`), each entered within `transition_grace_ms` of the previous one reaching `won` or its progress target |
| `content.objective_shown` | each traversed unit shows ≥ `objective_min_share` of the content words of **its own** `objective` (the design's per-unit line, not the game's generic one) in the text on screen while that unit was in play. The traverse test starts counting once the probe reports `playing`, in its own browser context, so no title screen is counted: the first 3 s of play are `start.objective`'s business |
| `content.win_lose_per_unit` | every unit the traverse **left** - a later unit was entered, or it was won, or it failed - and that states a `success` was completed, and bad play failed a unit that states a `failure`. With `qa.time_target_axis`, completion also needs `metrics.time` inside the unit's own `parameters.time_target` |
| `content.variety` | authored: ≥ `min_changed_pairs_share` of consecutive unit pairs change their entity kinds or their mechanics, and each unit introduces ≥ `qa.min_new_kinds_per_unit` kinds not seen before. **Required only when `qa.min_new_kinds_per_unit` ≥ 1**; otherwise the share is measured and reported as a warning with `measured.reason`. Generated: a kind not on screen at the start arrives by the earliest MVP `content_schedule.at_s` + `first_new_kind_slack_s` |
| `difficulty.axes_progress` | authored: every traversed unit reports the difficulty the **design** authored for it, within `genre-models.yaml implementation.difficulty_tolerance`, on every declared axis; and on every axis the family says escalates, ≥ `min_rise_share` of consecutive units hold or dip no deeper than `relief_dip_max`. The last above the first is asked only when every MVP unit was traversed (otherwise `measured.partial: true`). Generated or endless: the last `endless_window_s` window is above the first. An axis the family marks `probe: required` and the build does not report **fails**; an optional one it does not report is a warning |
| `progression.persists` | after a reload, read before any input, every MVP `meta_loop.persists[]` metric the probe reports - and `content.unit_index` - is what it was. Required only for the generation modes in `persists.required_generations`; a warning otherwise. With `qa.checkpoint`, the unit's own progress must also survive an in-unit loss |
| `depth.session_length` | one oracle session with instant retries reaches `min_share` x `depth.first_session.target_s`. The window is that bar plus a margin, never `max_multiplier` x the target: playing longer measures nothing more and slows every measurement after it on the same machine. Required for authored designs; a warning otherwise, and never a failure when the budget cut the window |
| `depth.ramp` | bad play ends a run inside `bad_play_max_multiplier` x the run length, and the oracle's input rate in the last third of its longest run is at least the first third's. **Required only for a time-ramp family** - one whose `qa` states `endless_window_s`; a unit-authored family ramps between units (`difficulty.axes_progress`), has no ramp inside one run, and its rate is recorded with `measured.reason` "no time ramp for a unit-authored family" rather than judged |

**`SKIPPED` is never a pass.** A check is skipped only when the design does not claim what it
measures - no `build_spec.content` at all, or generated content where a unit sequence would be
traversed, or no declared difficulty axes, or nothing persisted at the MVP tier. Every skip is
listed in the report's `skipped_checks` with its reason, named in the step's summary, and
subtracted by anything counting passes. A thing the design *does* claim and the probe cannot
show is a FAIL, not a skip - including a build that authors content and reports no `content`.

None of the production records changes a check here: an asset, a primitive or a default
button is the production gate's to judge, not this step's.

The visual bars were calibrated on frames this step captured: the unreadable run's game,
and the template's two example games. The calibration and its margin are recorded in
`visual-quality.yaml` itself. `lit_share` is a floor against a dark screen, not a measure
of readability; `entities.*` judges what must be seen.

## What it does not claim

The report's `measurement_class` is `automation-bot`. It shows the game can be played
and seen. It never shows that first-time players understand it. That is a kill
criterion, measured from people (MV-4), and an automation report never stands in for it.

## Running it outside a run

The step takes the same `checkout.locate` precedence as every step that works in the game
repository ([checkouts.md](checkouts.md)). Its unit tests synthesise records and frames
(`scripts/tests/test_playability.py`). Both golden runs play their ports through it
([golden-runs.md](golden-runs.md)).
