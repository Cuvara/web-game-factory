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
| BLOCKED | the step could not establish a result: no experience contract in the design, no checkout, the commit would not install or build, the browser would not start - or, with no check failed, a required check could not be measured: every attempt of its recording ran on a degraded host (`environment-degraded`), or the unit content.variety's negative rests on was cut short (`sample-cut`). Nothing about the game is claimed; resume on a quieter host |

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
   network access is refused outside localhost: the refusing proxy (`wgflib.netguard`) is
   set in the environment and handed to the browser as Playwright's `proxy` by the bot's
   generated config, since Chromium ignores the environment off Linux.
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

### The bot's tests, per viewport

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
  `transitions[]`, `per_unit[]` and a frame `unit-<index>-1s.png` per unit. When it stops
  (window or units) inside a unit that has shown fewer kinds no earlier unit showed than the
  family asks of every unit (`qa.min_new_kinds_per_unit`), it plays on in that unit - never
  into the next, and stopping the moment it is completed - for up to `visual-quality.yaml
  sample.variety_extend_s` (30 s), and records `extended_ms` (at least the extension's
  length when it ran all of it).
- **Persist** (only when the design states `build_spec.depth`): the oracle plays until the
  best or the unit reached moves, the page is reloaded, and the probe is read **before any
  input**. Whatever is gone was not persisted.
- **Session** (only with a depth contract): one first session with instant retries, held open
  to the design's own first-session length. Records how long play lasted, each attempt's
  oracle input rate per third of it, when the designed closing beat first arrived, and the
  difficulty in each `endless_window_s` window. The time ramp is not read on the session
  (design-depth.yaml 1.4.0): the ramp test samples its own runs.
- **Ramp** (only when the design promises a time ramp, `analysis.time_ramp`: the endless
  play itself, or an endless mode beside authored units): `ramp.samples` (3) **fresh runs**,
  each on a fresh page - and, for a mode, with the mode entered again through the probe's
  optional `play.mode.enter(mode)` (see
  [template-contract.md](template-contract.md#the-play-probe-mode)) - each played by the
  oracle for `ramp.run_s` (the budget's share of it) or until the game ends it; no retry
  inside a sample. Per sample the record keeps the oracle inputs per third and their times
  (`input_ms`), how it ended, and `longest_idle_ms` / `idle_at_ms`: the longest stretch in
  state `playing` with **no oracle input and no progress** - no change in the design's goal
  metric, the unit's `progress.value` or `unit_index` (a pause, a wave break or an
  interstitial is not play, so not idle). While the samples do not decide the ramp (the
  pooled counts short of `min_inputs_per_third` or inside the noise band, no stall, no
  sample's own fall), the bot plays further **whole** samples, as many as fit in
  `ramp.extend_s`, and records `extended_ms`. The record (`ramp.json`) also says whether the
  mode was entered and why sampling stopped (`reason`: play never began, `play.mode` absent,
  `modes()` not offering it, `enter` answering false), with frames
  `ramp-<mode|session>-start` and `-end`. Any other design gets `{applies: false}`.
- **Showcase** (only when the probe declares the optional `play.showcase`; see
  [template-contract.md](template-contract.md#the-play-probe-showcase)): last, after every
  fresh-save test, which all only meet the opening content. The bot reads
  `play.showcase.targets()` (at most 16) and, for each runtime asset id, calls
  `play.showcase.show(id)`, waits up to 6 s for the probe to report `playing` with a visible
  entity drawn from that asset (or one of its runtime-manifest `variants`), lets the screen
  settle, and keeps the frame `state-showcase-<id>.png` with the entities in it (each box
  swept between the snapshots before and after the shot, with its drawn size as `own: [w, h]`, as for a glimpse of play) under
  `ui["showcase-<id>"]` (`showcase: true`). `visits[]` records what each call did (staged,
  refused, timed out, never reported drawn). Its window is `SHOWCASE_S` (90 s), outside the
  time budget below, so a game without a showcase plays exactly as before; its record is then
  `{applies: false}`. No playability check reads it beyond `page.errors`: it exists for the
  production gate, which credits an asset in a staged frame only where the frame shows it.
- **Survey** (only when the step is asked for it, `with: {survey: true}` - the `playability`
  step of `new-game`, not the greybox - and the design authors its units): the traverse stops
  after the first few units; a release carries many more. For every unit the design lists
  (except `optional` ones), the bot opens `/?wgf-probe=1&wgf-unit=<unit id>` - the probe's unit
  link, which starts play in that unit as a level select would - and lets the oracle play it
  for at most `survey.unit_s` (12 s). It records which unit the probe reports, the entity
  kinds and runtime assets drawn in it by role, how many entities of a content role carried
  no `kind`, the difficulty in force, and whether and how fast the oracle completed it, plus a
  frame `survey-<unit id>-1s.png`. Only the `survey.projects` viewports run it (desktop:
  content is the same on every viewport), within `survey.total_s` (480 s); a unit it could not
  reach in time is recorded as not entered, with the reason. Both values are
  `core/reference/content-sufficiency.yaml`'s. No playability check reads it: the
  content-sufficiency step counts it ([content-sufficiency-module.md](content-sufficiency-module.md)).
  The step also keeps the played commit's `public/content/units.json` beside the records
  (`<records_dir>/content/units.json`), so that step measures exactly the build that was
  played.
- **Naive** (desktop, `core/reference/play-realism.yaml` `naive`): the oracle plays
  perfectly; a first-time player does not. The bot plays the opening unit from a first session
  and the middle and last of the authored units the build carries through the unit link, each
  under every policy for its input kind, for `naive.run_s` (25 s), retrying a loss at once:
  `steady` holds and repeats the first move the oracle names ("hold forward"); `jitter` follows
  the oracle `reaction_ms` late, a pointer up to `jitter_px` off, and with probability
  `error_rate` another listed move (never a utility, retry or begin control). Seeded, and each
  run starts as a first session (local and session storage cleared). `naive.json` records, per
  run, how long it played, whether and when it cleared the unit, its losses, the probe's
  `setbacks`, `content.par_s`, and a sample every 250 ms of `track` and `view`. Each unit and
  policy is played once, or `clear_rate.runs` times when the step compares clear rates with an
  accepted build (`with: accepted_play`). Like the timing-sensitive recordings it is made
  again on a degraded host. Its window is outside the time budget, like the showcase's; the
  process timeout grows by it.
- **Risk** (only with `with: risk: true`; `play-realism.yaml` `risk`): sampled units played
  under the game's own oracle policies `safe` and `greedy` (the probe's optional
  `play.policy`), `risk.json` recording what each attempt earned and how it ended.
- **The adopted floor** - when the design records the existing-content floor `unmeasured`
  (the adopted checkout ships no content data file) and this visit plays exactly its commit,
  the traverse plays up to `brief-commitments.yaml existing_content.probe.max_units` units
  and the report's `existing_content` records what the probe reached (`source.method:
  probe`, `wgf_design/existing.py probe_floor`). The bot records the build's own
  `content.unit_count` (`traverse.unit_count_reported`) and each unit's probe objective. A
  floor once measured is carried unchanged by every later report of the run.

The time budget (`design-depth.yaml playability.time_budget.bot_total_s`) is a hard cap per
viewport. What the first five tests cost is subtracted; the rest is shared between the
traverse, persist, session and ramp windows in proportion to what they asked for, and every check
judged from a window that was cut carries `measured.truncated: true` - and, where the
shortfall is the budget's rather than the build's, drops to a warning. The bot's process
timeout is `2 x (bot_total_s + SHOWCASE_S + 45) + 120` s, not a fixed number, plus the
survey's window and a start per surveyed unit when it runs, and, when a time ramp is read,
`2 x ramp.extend_s` and a start per ramp sample (the ramp asks the budget for `ramp.samples x
ramp.run_s`, 180 s as shipped, and each sample gets an even share of what the cut leaves;
the starts of its fresh pages are outside the cap), and - per viewport - every further attempt a degraded host may cost (the
first-session, win, lose and traverse windows and four starts, and every ramp sample with its
start, `environment.max_attempts - 1` times) and the traverse's `sample.variety_extend_s` on every attempt. A healthy host whose
units show their kinds spends none of it.

### Whether the host could measure it

A playability bot shares its machine with builds, other runs and agents. A host that stops
scheduling for seconds turns a game that starts in 0.3 s into one that "starts" in 10 s, and
a winning oracle into one that loses after three inputs: a live 2D run (game commit
`68a12b7`, whose gameplay was that of `48a80bb`) failed `start.playable` at 10339 ms and
`win.reachable` after 3 inputs on desktop, where the same gameplay had measured 309-574 ms
and won after 26. So every attempt of the recordings the timing-sensitive checks read -
first-session, win, lose, traverse and ramp (`analysis.EVIDENCE`; the ramp since 1.2.0:
a ten-second host stall is a ten-second idle stretch `depth.stall` would read as play that
stopped) - carries its `health` (`core/reference/visual-quality.yaml` `environment`),
measured only on what the game cannot cause:

- `bot`: a timer in the bot's own process, expected every `tick_ms` - the longest lag, the
  time lost to lags of `stall_ms` or more, the attempt's wall clock;
- `worker`: the same timer in a worker thread inside the page, off the game's main thread
  (`worker_error` when the page refused one); a recording that plays on several pages (the
  ramp, a fresh page per sample) reads each page's timer before leaving it and sums them;
- `nav.server_wait_max_ms`: the longest the local preview server - a static file server -
  took to start answering any of the page's requests (`responseStart - requestStart`).

Beside them, as evidence only, the navigation breakdown (`nav`: time to first byte,
DOMContentLoaded, load, the first frame, the first probe answer, play) and the page's
`requestAnimationFrame` gaps (`frames`). Those are the game's own: a game that blocks its main
thread is a defect the checks fail, never a degraded host (measured: a page blocking its main
thread 3 s every second left both timers under 1 ms). An attempt is **degraded** when either
timer stalled `max_stall_ms` at once or lost `max_stalled_share` of the attempt to stalls, or
the server waited `max_server_wait_ms`.

A degraded attempt is made again, in a fresh browser (a Playwright retry the bot asks for by
throwing; it skips every retry it did not ask for, so a test that threw still records
nothing), up to `max_attempts` in all. The record written is the last attempt's, with every
attempt in `attempts[]`; `analysis.environment_health` re-judges each from its numbers, and
decides:

- the last attempt healthy: the checks read from it are judged exactly as before; when an
  earlier attempt was degraded, `measured.environment` lists every attempt and why;
- every attempt degraded: each check read from it is **unmeasured** -
  `measured.unmeasured: environment-degraded`, the verdict it would have had in
  `measured.judged_as` - and never a pass, whatever it read. It is `BLOCKED` and required,
  and the step is BLOCKED rather than sent back to develop (a developer cannot fix the host;
  a person re-measures on a quiet host), where an unmeasured check is not passed
  (`quality-policy.yaml skipped_checks`, the release tier as shipped) **and, at every tier,
  when what it read was a failure or the check is required** (1.2.0): a degraded host never
  softens a failure into a warning the step passes over. Only a check that is neither - not
  required, and read no failure - is a `WARNING`;
- a record without health (made before 1.1.0) is judged as it always was: nothing is claimed
  about its host. Replayed, the live run's v15 desktop records still fail `start.playable`
  and `win.reachable` - they carry no health to say otherwise.

**The limit.** The timers share a machine with the game. A game that floods it itself - busy
workers on every core, a storm of requests to the local server - can make its own attempts
read as degraded: the bot cannot tell that load from another process's, and no bar here
attributes it (the frame gaps it can attribute are already never read as the host's). What
the rule above bounds is what that buys: a failure it read, or a required check, is BLOCKED -
never a pass, never a warning - and the step stops for a person, who sees a flood that
follows the build from host to host for what it is. `TheHost.test_a_game_that_floods_its_host_cannot_pass_its_own_failures`
holds this.

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
  `[id, role, visible, x, y, w, h, asset, render, collider]` (`asset` and `render` `null`
  when the probe does not report them; `collider` `[shape, x, y, w, h]` or `null`), and
  `sampled.playfields` the probe's `playfield` per frame when it reports one;
- `console`: every `console.error` line with where it was logged from and whether that is
  the page's own origin, and how many `webglcontextlost` events a canvas fired (an init
  script the bot adds to every page) - for `runtime.console_errors` and
  `runtime.webgl_context`;
- `ui`: the DOM UI measured on each screen state seen - `title` (before the begin input),
  `playing`, `paused`, `won` / `lost`, and `retry` (play after the retry) - each with its
  frame `frames/state-<name>.png`. Per state: every visible interactive element
  (`button`, `[role=button]`, `a`, `input`) with its box, font size and weight, colour, the
  opaque background behind it (own and ancestors' background colours composited; `null`
  when none is opaque, when one of them up to it paints an image, a border-image, a mask or
  a painting pseudo-element, or when another painting element lies between the text and it,
  so only the frame can tell; a control's colour, font and background are those of the
  element drawing its text), `glyph_box` (the rectangle of its own text, where the
  production gate reads the frame behind it), `paint` (its text-shadow and stroke colours),
  `decoration` (its text-decoration line), `ua_default` (its computed style equals the user-agent default for its tag, read from a
  blank frame no page stylesheet reaches) and the properties that differ; every visible text
  outside a control, measured the same way; the overlaps between controls and between a
  control and text; the probe's `ui`-role entities; and every entity the probe reported at
  that moment (with `asset` and `render`), so a state frame can be read at an entity's box.

## The checks

| Check | Passes when |
|---|---|
| `probe.present` | `snapshot()` answers. Without it nothing else is judged |
| `probe.valid` | snapshots match the schema and carry the contract's goal, win and lose metrics; with authored content, every playing snapshot reports `content` and its `unit_id` is one of the design's units the run builds (`scripts/wgflib/build_scope.py`: quality-benchmark `tiers[].builds.design_tiers` at the design's tier, else the run's - the MVP at `mvp`, the MVP and post-mvp units at `release`); an `optional` unit or an id the design does not list never is |
| `start.playable` | play begins within `first_30s.playable_s` of navigation, less the time the bot itself spent measuring the title screen (settling, styles, a frame; recorded as `observerMs` beside the wall-clock `playingMs`) |
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
  run is judged only where the family has a window for one, and only on a run of the play
  that promises one - never on an authored unit. Elsewhere the number is still
  measured, and reported as a warning naming why it is not a bar. The one thing this costs:
  for a unit-authored family a bad run that ends far too late is a `depth.ramp` warning rather
  than a failure - a bad run that never ends at all is still a `lose.reachable` failure.

| Check | Passes when |
|---|---|
| `content.units_reachable` | authored content: the transitions show units 1..N in the design's order (N = `min(mvp units, qa.min_units_traversed)`), each entered only after the previous one reached `won` (else its progress target) - a unit left `lost` or `unknown` fails - with the **game** moving on within `transition_grace_ms` (`design-depth.yaml` 1.4.0). The game's latency (`measured.transitions[].game_ms`, `analysis.transition_timing`) is what the bot observed it waiting: from the unit's first ended read to the last read before it offered an advance, plus from the bot's first delivered input (or the end, when the game advances by itself) to the last read still in the finished unit. The bot's reaction, click, pause and read round-trip are not the game's: the raw `since_end_ms` failed an unchanged 3D build on a loaded machine (1687 ms; 586 ms for the same gameplay before). Polling makes `game_ms` a lower bound; `game_max_ms` is the upper (the whole interval less the bot's reaction and click). Each transition records `ended_ms`, `unoffered_ms`, `offered_ms`, `act_started_ms`, `acted_ms`, `inputs`, `last_old_ms` and `at_ms` (`basis: recorder`); a record from an older bot is timed from its snapshots (`basis: snapshots`, the clicks in between still counted), else from `since_end_ms` |
| `content.objective_shown` | each traversed unit shows ≥ `objective_min_share` of the content words of **its own** `objective` (the design's per-unit line, not the game's generic one) in the text on screen while that unit was in play. The traverse test starts counting once the probe reports `playing`, in its own browser context, so no title screen is counted: the first 3 s of play are `start.objective`'s business |
| `content.win_lose_per_unit` | every unit the traverse **left** - a later unit was entered, or it was won, or it failed - and that states a `success` was completed, and bad play failed a unit that states a `failure`. With `qa.time_target_axis`, completion also needs `metrics.time` inside the unit's own `parameters.time_target` |
| `content.variety` | authored: ≥ `min_changed_pairs_share` of consecutive unit pairs change their entity kinds or their mechanics, and each unit introduces ≥ `qa.min_new_kinds_per_unit` kinds not seen before. The unit the traverse stopped inside, neither completed nor left (after the bot played on in it, above), counts for what it showed and decides nothing by what it had not shown yet - unless the bot played on in it for the whole `sample.variety_extend_s` (`extended_ms` at least that long): then the cut no longer decided anything, the unit is judged as seen whole (`measured.seen_whole_after_extension`), and still short of kinds it fails, its pair counted (visual-quality.yaml 1.2.0; before, such a unit stayed unmeasured however long it was played, so a unit with no new kind could avoid failing forever by being the last one reached). Otherwise its shortfall is `measured.unmeasured_units` (and an unchanged pair into it `unmeasured_pairs`), never `new_kinds_short`. The check is decided on the units the traverse saw whole when they are at least `min(mvp units, qa.min_units_traversed)`; fewer, and nothing else falls short, it is unmeasured (`measured.unmeasured: sample-cut`) - BLOCKED where an unmeasured check is not passed, else a WARNING; never a pass, and never a failure read off where the cut fell (the live run read "unit 3: 0 new kind(s)" off 1.4 s of a unit whose new kind arrives 3-20 s in). **Required only when `qa.min_new_kinds_per_unit` ≥ 1**; otherwise the share is measured and reported as a warning with `measured.reason`. At a tier where an unmeasured check is not passed (`core/reference/quality-policy.yaml` rule 5, `skipped_checks`: the release tier), a probe that reports no `entities[].kind` while a content unit is in play fails it, required - the play probe requires `kind` of every content-role entity then; below that tier it stays an unmeasured warning. Generated: a kind not on screen at the start arrives by the earliest MVP `content_schedule.at_s` + `first_new_kind_slack_s` |
| `difficulty.axes_progress` | authored: every traversed unit reports the difficulty the **design** authored for it, within `genre-models.yaml implementation.difficulty_tolerance`, on every declared axis; and on every axis the family says escalates, ≥ `min_rise_share` of consecutive units hold or dip no deeper than `relief_dip_max`. The last above the first is asked only when every MVP unit was traversed (otherwise `measured.partial: true`), and judged at the design's own `quality_tier` the way `content.axes_monotone_with_relief` judges the design: at tier mvp on every escalating axis; above it (units past the prototype) only where the design's own values for the traversed units rise - an axis the release design's MVP holds flat is held to the design's values and never below its start (`measured.held_by_design`). Above tier mvp, when the survey entered every release unit, each visit is held to the design's value too and every reported escalating axis ends the release above where it started (`measured.release`); a survey short of the release reports `measured.release_partial` with its reason, never a pass of that curve. Generated or endless: the last `endless_window_s` window is above the first. An axis the family marks `probe: required` and the build does not report **fails**; an optional one it does not report is a warning |
| `progression.persists` | after a reload, read before any input, every MVP `meta_loop.persists[]` metric the probe reports - and `content.unit_index` - is what it was. An entry's measure is the HUD metric its `delivered_by` names, else its kind's in `core/reference/design-depth.yaml` `playability.persists.probe_measures` (1.2.0): a best is `metrics.best`, stage progress the unit reached, `content.unit_index`, which the probe reports with every unit. Stage progress counts as shown only once the bot reached a unit past the first before the reload (a build that saves nothing starts at unit 1 too); a kind with no measure is SKIPPED, and the quality floor fails a release build on it. Required only for the generation modes in `persists.required_generations`; a warning otherwise. With `qa.checkpoint`, the unit's own progress must also survive an in-unit loss |
| `depth.session_length` | one oracle session with instant retries reaches `min_share` x `depth.first_session.target_s`. The window is that bar plus a margin, never `max_multiplier` x the target: playing longer measures nothing more and slows every measurement after it on the same machine. Required for authored designs; a warning otherwise, and never a failure when the budget cut the window |
| `depth.ramp` | bad play ends a run inside `bad_play_max_multiplier` x the run length, and good play is asked for more as a run goes on, **shown beyond noise on several runs** (design-depth.yaml 1.4.0, `analysis.ramp_verdict`). **Required only where a time ramp is promised** (`analysis.time_ramp`): a family whose `qa` states `endless_window_s`, and then read on runs of the play that promises the ramp - the endless play itself (`genre.ending: endless`, or content that is not authored), else a mode the design includes at a tier the build carries (a feature whose `catalogue` is in `design-depth.yaml playability.ramp.mode_features`, decided `include`; the greybox carries the MVP tier only), entered through `play.mode` (`measured.ramp_run`, `mode`, `mode_entered`). A unit-authored design with no such mode ramps between units (`difficulty.axes_progress`): its longest unit is not a time ramp, and its rate is recorded with `measured.reason` "no time ramp" rather than judged. The ramp samples' thirds are **pooled**, leaving out any sample that stalled (`depth.stall`); with n = first + last thirds' inputs, the noise band is `ramp.noise_z` x sqrt(n) (2 x: under an unchanging rate the split is Binomial(n, 1/2), so a flat game reads as a rise about 2.3% of the time per look). **FAIL**: one sample's own fall beyond its own band (its first third holding at least `min_inputs_per_third`), or the pooled fall beyond the pooled band - however few samples were played. **PASS**: `ramp.samples` (3) clean samples whose pooled last thirds exceed the first by more than the band. **Unmeasured** (`measured.unmeasured`): no clean sample, pooled first thirds under `ramp.min_inputs_per_third` (10), fewer clean samples than planned, a mode the bot could not enter, or - after the extension - a difference inside the band; a warning, never a pass, and a FAIL at a tier whose skipped checks are not passed (`quality-policy.yaml skipped_checks`, the release tier as shipped). A rate that does not change therefore never passes. `measured` carries every sample (`samples`: thirds, duration, longest idle, how it ended), `pooled_inputs_per_third`, `noise_band`, `stalled_samples`, `planned_samples` and `extended_ms`. Why several runs: one endless run per viewport, cut by the bot the moment its first third reached 10 inputs, read [10, 14, 23] PASS on one commit of the 2026-10-05 brick game and [10, 29, 9] FAIL on the next, an art-only commit with identical gameplay code - the fall was a ball trapped above steel bricks, a real defect (game fix 48a80bb) sampled by chance and blamed on the art. (`relief_dip_s`, "one relief dip of at least 2 s allowed", was removed in 1.4.0: it was stated and never measured. Only the first and last thirds are compared, so a breather in the middle third is allowed at any length; a dip into the last third is the decline this check catches; play that stops is `depth.stall`.) |
| `depth.stall` | in every ramp sample, no stretch in play longer than `ramp.stall_max_s` (10 s) with no oracle input and no progress (`measured.longest_idle_ms` per sample). **Emitted only where ramp samples were played**, required there. Its own finding - routed to gameplay (`specialist-routing.yaml` 1.5.0 `depth.: gameplay`) - so a game that stops being playable is classified as that, not as a ramp that asks for less: a stalled sample's counts are left out of `depth.ramp`. 10 s is the experience floor's opening grace (`experience-rules.yaml onboarding.min_grace_s`) and a third of the time-ramp families' endless window; an oracle playing those games acts about once a second (the live brick game's endless runs: 38-76 inputs in 32-67 s). The ramp recording carries its host's health and is made again on a degraded host (visual-quality.yaml 1.2.0): with every attempt degraded, `depth.stall` (required) is BLOCKED `environment-degraded`, never a FAIL routed to gameplay for a stall the host made, and never a pass; so is `depth.ramp` where it is required or read a failure, else a WARNING |

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

### Play realism

`scripts/wgf_playability/realism.py`, every bar in
[`core/reference/play-realism.yaml`](../core/reference/play-realism.yaml) with its
calibration. The checks above judge what is drawn and play with a perfect oracle; validation
builds of 2026-10 passed them with a ball that turned at a ceiling nothing drew (2D 68a12b7),
a course held forward through in about a third of its par and hairpins narrower than the
track (3D 1c6b099), a collider grown until the steel rows' one-cell gaps could hardly be
threaded (2D 894b4b8), and nothing that looked at the console (factory-learning-ledger L11,
L13, L14, M1, M5). These read the play probe's optional realism fields
([template-contract.md](template-contract.md#the-play-probe-realism-fields-and-the-layout-file)),
the bot's records and the content data file of the commit played.

**How hard they hold.** A measured FAIL is required - the step FAILs and routes the build to
develop - at the tiers `play-realism.yaml enforce.fail_required_at` names (`release`,
`premium`); below them it is a WARNING the report lists (a greybox, an MVP run, the golden
runs). A check whose data the build does not report is **unmeasured** - never a pass,
`measured.unmeasured: not-reported` with the reason - and is held as
`core/reference/quality-policy.yaml skipped_checks` says: not passed at the release tier (a
required FAIL naming the probe field to add), a WARNING below it. A recording the host
degraded is re-made, then judged as `analysis._environment` judges every timing-sensitive
check (a degraded host never softens a failure).

| Check | Passes when |
|---|---|
| `physics.undrawn_collision` | (2D builds; a 3D build's screen positions are projections, so it is not judged there) every turn or stop of a projectile in the win test's per-frame samples happens at a drawn surface: the face of another visible entity on the side the mover was moving toward (in that frame or the one before - a brick the hit breaks), an edge of the probe's `playfield`, something the mover is inside, or a surface moving with it (a ball carried on a paddle), within `tolerance_px` plus the frame's travel, measured from the mover's `collider` when it reports one, else its drawn box. Without a `playfield`, a turn at nothing drawn fails only when a drawn entity still lies ahead of the mover; otherwise it is unmeasured |
| `physics.collider_size` | every entity that reports a `collider` is drawn `min_drawn_to_collider`-`max_drawn_to_collider` x it on each axis (median over the frames), judged on its opaque `body` when the probe reports one (a solid disc inside a glow, declared `halo: true`), else on its whole drawn box. A halo without a body, an empty body or a body outside the drawn box fails: a collider is never passed with nothing drawn to hold it to. No collider reported: unmeasured |
| `naive.setbacks` | in the OPENING unit, the probe's `setbacks` rise at most `setbacks.max_per_min` a minute of jittered play (a FAIL needs `min_count`). Without `setbacks`, losses are a lower bound: a FAIL above the bar, unmeasured below it. Every unit's rate is reported |
| `naive.drift` | the time-weighted mean of `track` `\|offset\| / half_width` under jittered play in the opening unit is at most `drift.max_mean_share`. No `track`: unmeasured on the dimensions `drift.dimensions` lists (3D), not judged elsewhere |
| `naive.alignment` | the 90th percentile angle between `view.camera_forward` and `view.control_forward` is at most `alignment.max_p90_deg`. No `view`: unmeasured on `alignment.dimensions` (3D) |
| `naive.pace` | every naive run that cleared a unit took at least `min_clear_to_par` x its par (`content.par_s`, else the design unit's `parameters.par_s` / `time_target`); a run still short of the end after that share of par is a lower bound that passes |
| `naive.unit_duration` | the fastest naive clear of every unit took at least the tier's `min_unit_s`; a unit no policy cleared lasted at least its run (a lower bound) |
| `naive.clear_rate` | with the step's `with: accepted_play` (the accepted build's naive record, or `{units: {id: {policy: {won, n}}}}`), no unit and player model clears at least `clear_rate.min_drop` less often with a one-sided two-proportion z of at least `min_z` (both builds `min_runs` runs or more; the bot then plays each unit `clear_rate.runs` times). Without an accepted build the rates are reported as unmeasured - never a pass, never a blocker |
| `level.geometry` | (project `build`, once per build) no bend of a declared PATH layout is tighter than `min_radius_to_width` x the width, and none under `tight_radius_to_width` has an open inner edge |
| `level.unit_length` | every path layout is at least `min_length_to_width` x its width long and is crossed at top speed (the layout's `top_speed`, else `play_geometry.top_speed`) in at least `min_traverse_to_par` x its par and the tier's `min_traverse_s`; no top speed stated: unmeasured |
| `level.clearance` | (a proxy: blocking only for a unit whose `naive.clear_rate` against the accepted build was not measured; advisory where the unit's clear rate was measured and passed; where it failed, both are reported and the clear rate blocks) in every GRID layout, each row holding a solid cell (`play_geometry.grid.solid`) leaves a passage at least `clearance.min_widest_to_body` x the moving body's diameter (`play_geometry.body`); a build whose units lay out what reads as a grid but declares no `play_geometry.grid` is unmeasured and not held (the grid is a guess from the data's shape); a declared grid missing its cell or body is held |
| `runtime.console_errors` | no `console.error` from the game's own origin in any recording (lines matching `runtime.ignore` - the sandbox refusing a network request - are counted apart, never against the build) |
| `runtime.webgl_context` | no `webglcontextlost` on any canvas in any recording |

Geometry is read from the content contract's one declared place
(`core/reference/content-sufficiency.yaml` `layout`: a unit's `layout` entry in
`public/content/units.json`, and its entry in the layout source), the same files the
content-sufficiency step compares units on.

The **risk test** (`with: risk: true`, `play-realism.yaml risk`) plays sampled units under the
game's own oracle policies `safe` and `greedy` through the probe's optional `play.policy` and
writes `risk.json`; it judges nothing here (the level-design step reads it).

Triage routes the checks by `core/reference/specialist-routing.yaml`: `physics.`, `runtime.`
and `naive.alignment` to gameplay, the rest of `naive.` to difficulty, `level.` to the level
designer. What is calibrated on which build, and what is only reasoned (`collider_size`,
`alignment`, and `drift` on regressed builds), is stated beside each bar; the replay tests are
`scripts/tests/test_play_realism.py` over `scripts/tests/fixtures/real/play-realism/`.

## What it does not claim

The report's `measurement_class` is `automation-bot`. It shows the game can be played
and seen. It never shows that first-time players understand it. That is a kill
criterion, measured from people (MV-4), and an automation report never stands in for it.

## Running it outside a run

The step takes the same `checkout.locate` precedence as every step that works in the game
repository ([checkouts.md](checkouts.md)). Its unit tests synthesise records and frames
(`scripts/tests/test_playability.py`). Both golden runs play their ports through it
([golden-runs.md](golden-runs.md)).
