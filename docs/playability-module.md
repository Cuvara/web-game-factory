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

The report's artifact id is `wgf:playability-report:<title>:<yyyymmdd>-<nn>`, `nn` the
step's execution count. A step that names a phase (`greybox-playability`, `with: {phase:
greybox}`) puts it in the scope - `wgf:playability-report:<title>-greybox:...` - because
each step counts its executions from 1: before, the greybox's and develop's reports of one
day shared ids (five pairs in the 2D run of 2026-10-05, six in the 3D run). Older reports
keep their ids; the ledger tells them apart by content hash and run-local seq.

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
  Since new-game 19 the survey also keeps three frames of every surveyed unit - its start,
  middle and end as the oracle played it (`level_frames`, under `<project>/level/`, each with
  its sha256 and the entities the probe reported) - for the level-design step's critic
  ([level-design-critic.md](level-design-critic.md)). The capture time is added to the unit's
  and the survey's windows, so the survey reaches as many units as without it.
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
- **Contact** (2D builds only, `play-realism.yaml contact`): the oracle plays for up to
  `contact.window_s` on each of `contact.projects`, with the page's clock **stepped** - every
  frame's callbacks get a timestamp `contact.frame_ms` after the last, whatever the host took to
  draw it (`clock: frame-stepped`), so a loop that takes its delta from the frame's timestamp
  (the template's fixed-step loop) moves one step per frame drawn and a turn is seen where it
  happened even on a loaded host. At the start of each frame, before the page's callbacks run,
  the probe is read; when a mover of `contact.roles` reverses on an axis (the `physics` rules'
  `min_speed_px` and `max_step_px`), every requestAnimationFrame callback is **held**: the
  canvas keeps the frame the snapshot describes, and the bot keeps a crop of it around the turn
  at one pixel per CSS px (`contact-<n>-at`), lets the game run `contact.after_frames` frames,
  freezes it again and keeps the same crop (`contact-<n>-after`), in which the mover has left,
  and as many frames on a third (`contact-<n>-later`, from play-realism 1.2.0): a spark of the
  hit has faded by then, and the mover's drawing is read there away from the impact. A turn at
  a surface that moved (a paddle) or at a composite (a row of bricks) is frozen on too, marked
  `passing` and counted in `passed` (before 1.2.0 it was not frozen on: such a surface was left
  to the probe's word); at most `contact.max_captures`, at least `contact.gap_ms` of game time
  apart. The no-mover exit (`no <roles> in play`) waits six seconds of GAME time, not of the
  host's. When movers were in play and none was frozen on, the bot asks for one set of frames
  anyway (`kind: asked`), for the drawn extent. `contact.json` records each capture's three
  snapshots around the turn and at each later frame, the event (the axes it turned on),
  whether the page was still frozen on the same frame after each shot, how many turns it saw
  (`turns`, of them `passed`), the frames with a mover in play (`movers_seen`), the game time
  armed (`game_ms`) and the page's real frame pacing (`frame_gaps`). The crops are
  evidence of the physics checks only: they are left out of the report's `frames` (visual QA
  judges screens, not crops) and each check pins every crop it read by sha256
  (`measured.frames`). Its window is outside the time budget, like naive play's; the process
  timeout grows by it. Any other build records `{applies: false}` with why.
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
- `events`, `effects`, `celebration` (win and lose tests): every interaction the probe
  reported in its optional `events` (each once, by `seq`, with the time and state it was
  seen); per visual effect the probe drew (an entity of role `vfx`, by the
  `build_spec.vfx` id it names) the times it was drawn, the largest share of the viewport
  its bounds covered, a frame while it was drawn (`state-vfx-<id>`, its box swept across the
  shot as for a glimpse; tried again at its next appearance when it ends mid-shot, up to 4
  times, at most 8 effects per test) and a frame of the same place once it ended
  (`state-vfx-<id>-after`); and the screen the moment the probe first reports `won`, before
  anything settles: its frame `state-won-enter`, the entities in it, the time since the
  last `goal` event, and a 32x32 grid of which cells the page paints over the game's canvas
  (an element above the canvas with a background at least half opaque, a background image,
  an image, svg, video or another canvas). The production checks `vfx.*` read them
  ([production-quality-module.md](production-quality-module.md#the-visual-effect-checks)).

### The scenario each check was measured on (playability-report 1.4.0)

A check's status alone cannot say whether a later PASS measured the same thing as an earlier
FAIL. Every check names its `scenario`, `<check>@<project>` - stable across reports - and
the report lists, per scenario (`scenarios[]`, built by `wgf_playability/scenario.py` from
the records the bot already writes; nothing the bot did not record is added):

- `bot` - the bot's version (sha256 of `bot.spec.ts` as the step copied it into the clone)
  and the sha256 of the settings it was handed (`<records_dir>/settings.json`); the report's
  own `bot` says the same once;
- `viewport` - the project's width and height (null for `level.*`, a check of the commit's
  content data file, project `build`);
- `policy` - how the bot played each recording the check reads (`idle`,
  `each-offered-input`, `oracle`, `anti-oracle`, ...), and naive play's seed and policies
  from the settings, or risk's policies from its record;
- `records` - the raw records the check is judged on (`analysis.EVIDENCE`, extended for the
  checks that table leaves out; every record for `page.errors` and `runtime.*`), each with
  its run-relative path and sha256;
- `actions` - the inputs those records list, in order, as recorded: the begin press, each
  act input with its coordinates or key and the probe state before and after, each
  anti-oracle press with its time, a reset inside the unit, the retry, a pause, each naive
  or risk run (its policy, unit, inputs and time). Where the bot keeps only a count - the
  oracle's presses in the win test - one entry carries that count, and `actions_complete` is
  false. `actions_complete` is true only when every press is listed one by one;
- `states` - the probe state transitions the records list, with their times;
- `frames` - the frames the check and its records name, each with its path and sha256.

Lists are capped (80 actions, 40 states, 16 frames) and `omitted` says how many were left
out. The ledger reads the scenario of the check a finding failed and the one it later passed
(docs/specialist-routing.md, "What counts as a re-measurement"): a different bot version,
other settings or another viewport make that comparison weaker, and it says so. What the
records do not hold stays unrecorded: the oracle's individual presses in the win, traverse,
persist, session and ramp tests, and the timing of act inputs. Tests:
`scripts/tests/test_playability.py` `Scenarios`.

## The checks

| Check | Passes when |
|---|---|
| `probe.present` | `snapshot()` answers. Without it nothing else is judged |
| `probe.valid` | snapshots match the schema and carry the contract's goal, win and lose metrics; with authored content, every playing snapshot reports `content` and its `unit_id` is one of the design's units the run builds (`scripts/wgflib/build_scope.py`: quality-benchmark `tiers[].builds.design_tiers` at the design's tier, else the run's - the MVP at `mvp`, the MVP and post-mvp units at `release`); an `optional` unit or an id the design does not list never is |
| `start.playable` | play begins within `first_30s.playable_s` of navigation, less the time the bot itself spent measuring the title screen (settling, styles, a frame; recorded as `observerMs` beside the wall-clock `playingMs`) |
| `start.objective` | ≥ 60 % of the objective statement's content words are on screen in the first 3 s of play |
| `idle.grace` | no loss during the idle window |
| `act.acknowledged` | every action changes ≥ `min_changed_fraction` of the frame by ≥ `min_pixel_delta` luminance; each is measured in play (a pause goes last, and the bot resumes through the game's own resume input before the next action); an action whose attempt ended by the game's clock around it (in play before, `won`/`lost` after) is taken again from play (the game's retry, then its resume or begin input), at most twice, and one that still ends it is kept with `ended_attempts` (#67) |
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
| `physics.contact_drawn` | (2D, contact frames) every frozen turn whose surface a later frame can show - a turn the probe explains by nothing, by its `playfield`, or by an entity still in place and not a composite - is at something DRAWN: in the frame after the mover left, along each line across the contact (the mover's span on the other axis), the largest colour distance between the band from the mover's centre to `tolerance_px` + its travel past its leading edge and the median colour of the quarter behind its centre (where it was, now background); the median over the lines is at least `contact.min_edge`. FAILs at `contact.min_undrawn` contacts under it, naming whether the probe reported a surface there (a box or edge the screen does not draw) or nothing. A turn at the board's edge where that edge is the viewport's own (the canvas fills the screen) is at a drawn edge (`surface: screen edge`). A turn at a surface a later frame cannot show where the mover met it is read where it is (play-realism 1.2.0, K7 review): at a moving surface the contact is carried with the surface to its place in the frame after (`read: carried`); at a composite, along its face, drawn if any part of it near the contact is (`read: along its face`); a surface gone by the frame after but reported anew under another id at the same place is that surface. With a third frame the contact is read on both frames and the lower reading counts (a spark of the hit has faded). Left to `physics.undrawn_collision` (counted in `measured.unverified`): a surface gone by the frame after (a brick the hit broke) - unmeasured instead when the mover meets it again (`measured.gone_and_met_again`); a composite with nothing drawn along its face near the contact - unmeasured instead when nothing is drawn in its box in any frame read (`measured.composites_drawn_nowhere`, `contact.composite_min_share`); a turn that travelled more than `contact.max_travel_px` in its frame (a loop on its own clock: the band would reach that far). A contact masked on every line by something reported in the frame after is read under the mask against the background behind it: nothing drawn there either is a turn at nothing drawn. Movers in play that never turned: PASS, nothing to verify (as `physics.undrawn_collision`) - unless the win test's samples show them turning (unmeasured). Turns seen and none it could read: unmeasured. No mover of the roles in play: not reported when the design declares none of `contact.roles` (`build_spec.assets[].role`), else unmeasured |
| `physics.drawn_extent` | (2D, contact frames) every entity of `contact.extent_roles` that reports a `collider` is drawn `physics.min_drawn_to_collider`-`physics.max_drawn_to_collider` x it (per axis on a record without the third frame; across and along its travel on one with it - see below) - the same bar as `physics.collider_size`, measured on the PIXELS: the pixels whose colour changed by at least `contact.min_delta` and `contact.solid_share` of the change inside the collider (90th percentile) between the frozen frame and the frame after the entity moved away, connected to the collider, other entities' boxes masked. Median per axis over the captures; an axis whose measured body reaches a mask or the crop's edge is a lower bound (it can show a body too large, never one small enough). With a third frame (play-realism 1.2.0) the body is read away from the impact - on the frame after the turn against the third frame - and across the entity's direction of travel there (`measured.across`; a trail or a stretch along the travel is not the body, a squash on the hit frame is not read), against the collider's own extent across the same direction; along the travel, on its opaque pixels only (`contact.along_share` of the change inside the collider, `measured.along`), held to the upper bar - a solid tail or a body drawn long along its motion FAILs, a fading trail does not, and a shaded body reads short there (lenient). Records without the third frame are read on the frozen frame against the frame after. The reported collider is held to where it touched (`contact.max_collider_to_contact`, the largest over the entity's turns). Nothing inside the collider changed: FAIL. No collider reported: unmeasured. An entity masked in every frame (`measured.masked_out`) is unmeasured unless another entity of the same drawing - role and asset - was read (play-realism 1.3.0; `measured.covered_by_same_drawing`); one drawn otherwise never covers it. After a window with no turn the bot asks for up to three captures, each on a mover clear of everything else reported within `contact.window_colliders` of it, the oracle playing on until one is in view (`asked_frames`: frames read, with a mover, with one clear) |
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

### What the contact frames measure, and what they cannot

The two contact checks exist because the probe-reported physics checks can be satisfied without
drawing anything. In the 2D validation game (2026-10) a specialist cleared the visibility bar by
enlarging the ball's drawing while its collider stayed r11 (68a12b7, H3), and a level designer
added undrawn ceilings mid-board so the bot reached units in time (cbac64e, H2). A build that
reported a playfield edge or an entity box at that ceiling, or a `body` the collider's size,
would pass `physics.undrawn_collision` and `physics.collider_size` as they stand.

| What | Measurement class |
|---|---|
| where the mover was when it turned, and its collider | **self-reported** (the probe) |
| that it turned: the reversal of its reported centre between consecutive frames | derived from the self-report |
| whether the page was frozen on the frame the snapshot describes | derived: the hook's own state, read again after the shot - every requestAnimationFrame callback is held, so a game drawing from rAF (the template's loop) keeps its frame; one drawing from timers or a worker would keep drawing, and nothing here would show it |
| whether anything is drawn at the contact | **pixels** (the frame after, against where the mover was) |
| what is drawn of an entity: its solid extent | **pixels** (the frozen frame against the frame after) |

Calibration (real, `scripts/tests/fixtures/real/play-contact/`): on the 2D game's builds
(96f5cea, cbac64e, 68a12b7, 894b4b8), every drawn wall, static brick and board edge read 172-385
and every undrawn ceiling 13-34 (the highest, 33.5, a ceiling crossing the backdrop's hill line).
`min_edge` 48 sits 1.4 x above the highest undrawn reading and 3.6 x under the lowest drawn one.
Drawn extent, with the collider reported (a harness patch to a scratch build, see the README):
68a12b7 2.6-2.7 x its collider across (the enlarged paper ball and its dart), r1 96f5cea
1.9-2.05 x (its solid disc, 42 board px over a 22 px collider - the figure 894b4b8's own tuning
states), 894b4b8 1.03-1.2 x (r1's art with the collider grown to the solid disc). So the accepted
r1 build FAILs `physics.drawn_extent` too: it held the same bar `physics.collider_size` already
fails it on once a collider is reported, and 894b4b8 is the build that cleared it.

Closed by the bypass review (2026-10-12, `Bypasses` in `scripts/tests/test_play_contact.py`,
each failing on the code before its fix): an entity reported over the contact in the frame
after masked it out of the reading (a mask hides what is drawn under it, never that nothing is:
read under the mask against the background behind it, nothing drawn is a turn at nothing
drawn); an entity whose collider was masked in every frame dropped out of the drawn extent
(now unmeasured, named in `measured.masked_out`); a collider reported larger than the
simulation's (above); a hit-stop - up to `physics.hit_stop_frames` still frames at a bounce -
hid the turn from `physics.undrawn_collision` and from the bot (a turn is now seen across the
stall); and a contact test that froze on no turn PASSed although the win test's samples show
the mover turning (now unmeasured).

What they cannot catch:

- a collider the probe does not report: `physics.drawn_extent` is unmeasured, never a pass; a
  collider reported smaller than the simulation's is believed. One reported LARGER is held to
  where it touched (`contact.max_collider_to_contact`): at a turn read as drawn, its half
  extent against the distance from its centre to the surface's first pixel plus its step;
  honest readings 0.48-0.92 (the largest over an entity's turns), the real records with the
  collider scaled to pass the extent 1.09-1.97. The step bounds that reading from above, so a
  collider reported up to about 1.5 x the simulation's still passes both bars (96f5cea's
  scaled x1.6 on desktop, cbac64e's x1.5);
- a wall the bot never touched in the window; a surface gone by the frame after (a brick the
  hit broke) that the mover never meets again; a composite with nothing drawn along its face
  near the contact while something is drawn elsewhere on that face (a ghost box made the union
  of a real brick row and an invisible ceiling ALONG the same face - one bundled behind the
  row, whose hit face is drawn nowhere, is unmeasured: `measured.composite_face_drawn`); a box
  that moves with a mover of the judged roles (two balls passing are not read as a contact);
- a trail dense enough to blend past `contact.along_share` reads as body along the travel;
  and the other way round (K7 review round 3, P12), a body drawn long along its motion at
  80-94 % opacity - a shaded dart, a comet with a slightly translucent tail - is not held along
  the travel: only its opaque pixels count there (a uniform 0.8 or 0.9 tail three times the
  body reads 1.03 x and PASSes; at 0.97 it FAILs at 3.03 x; 3e8d25f FAILed all three). Lenient
  by design, so that a blended motion trail (P5, 94 % where its ghosts overlap) is not the body;
- OPEN RISK, to watch in the first live run (K7 review round 3, P13): an HONEST composite whose
  face it was hit on is drawn nowhere in any frame read - its bricks near the hit broken and
  the rest of that face outside the crop - reads 0.0 on `measured.composite_face_drawn`: the
  check is unmeasured, which holds the build at release. The only honest real reading so far is
  0.034 (894b4b8 mobile) against `contact.composite_min_share` 0.01. Candidate fixes, not made:
  read the face strip on the whole viewport rather than the crop, or apply the face rule only
  when the same composite is skipped at two or more captures;
- turns frozen on are capped (`contact.max_captures`) and a turn at a paddle or a brick row
  now takes one of them: in the step's window (`contact.window_s`, on a loaded host a few
  seconds of game time) fewer captures go to walls than before 1.2.0;
- a spark of the hit still drawn in the frame after, on a record without the third frame (a
  bot before 1.2.0): it reads as a surface;
- a game that detects the harness (the wrapped requestAnimationFrame) and draws differently
  while measured, and one drawing from timers or a worker (the freeze holds rAF callbacks only;
  `still` is the hook's state, not the canvas's);
- an undrawn wall that happens to coincide with a backdrop feature as strong as `min_edge`
  along the contact (a contrasting horizon exactly where the ceiling is);
- a drawn surface whose colour equals the background's behind the mover (it reads undrawn; to a
  player it is invisible too) - or is within `min_edge` of it: a wall at a colour distance of
  20-35 from its backdrop is visible on a monitor and FAILs as undrawn (a false positive: the bar
  was calibrated on one game's palette; `test_a_low_contrast_wall_reads_undrawn_a_known_limitation`);
- an opaque outline darker than half the body's change is read as background, so a body with
  such an outline measures smaller (lenient: 68a12b7's ink outline, which still FAILs on its fill);
- a 3D build (screen positions are a moving camera's projection), and a game whose loop reads
  its own clock instead of the frame's timestamp - its turns are seen at the host's pace; a turn
  that travelled more than `contact.max_travel_px` in its frame is not read (1.1.0's
  `max_frame_ms` gap test could never fire: the bot records the stepped timestamps).

Geometry is read from the content contract's one declared place
(`core/reference/content-sufficiency.yaml` `layout`: a unit's `layout` entry in
`public/content/units.json`, and its entry in the layout source), the same files the
content-sufficiency step compares units on.

The **risk test** (`with: risk: true`, `play-realism.yaml risk`) plays sampled units under the
game's own oracle policies `safe` and `greedy` through the probe's optional `play.policy` and
writes `risk.json`; it judges nothing here (the level-design step reads it).

The realism bars and the bot's viewports (`visual-quality.yaml`) are the copies the run
pinned when it started (new-game `pinned_references`); a copy edited after the start BLOCKS
the step.

Triage routes the checks by `core/reference/specialist-routing.yaml` (1.6.0): `physics.` and
`naive.alignment` to gameplay, `naive.pace`, `naive.unit_duration` and `level.` to the level
designer, the rest of `naive.` to difficulty, `runtime.console_errors` to browser QA (as
`page.errors` is) and `runtime.webgl_context` to the performance engineer. Each has a tier in
`core/reference/check-tiers.yaml` (source `play-realism`: `physics.undrawn_collision`,
`physics.contact_drawn` and `runtime.webgl_context` hard, the rest quality, `level.clearance` advisory unit by unit where
its clear rate passed), and the quality gate places them on its scorecard
(`core/reference/quality-floor.yaml` 1.2.0, `applies: reported`): `floor.physics_drawn` on game
feel, `floor.naive_control` on gameplay, `floor.naive_challenge` and `floor.level_geometry` on
level design, `floor.runtime_console` on the browser line and `floor.webgl_context` on
performance. `level.clearance` is held by this step only: a proxy whose clear rate
`naive.clear_rate` already carries to the floor. Lessons L11 (2D), L13, L14, L23 and L24
(`core/reference/lessons.yaml`) name these checks. What is calibrated on which build, and what is only reasoned (`collider_size`,
`alignment`, and `drift` on regressed builds), is stated beside each bar; the replay tests are
`scripts/tests/test_play_realism.py` over `scripts/tests/fixtures/real/play-realism/`.

### The accepted build (playability-report 1.5.0)

When the run adopted a game, the design names the build a person accepted
(`existing_content.source.commit`: `factory.init.accepted_baseline`, else the adopted
checkout's shipped commit). Every visit that plays another commit also plays the accepted one -
with the same bot and the same settings, the accepted units surveyed and sampled by naive play,
each naive unit and policy played `clear_rate.runs` times - on desktop, kept under
`<run>/baseline/` and reused while the bot and settings are the same. The `baseline.*` checks
then report what got worse, unit by unit and quantity by quantity: units removed or renamed,
layouts, elements and tuning changed, units cut, difficulty values moved or reordered, drawn
kinds and role sizes changed, units cleared in a fraction of the accepted time or more often,
a slower start or frame rate. A measured regression fails at every tier; a person changes
accepted content only by recording why (`factory.init.accepted_changes`). The accepted play
also feeds `naive.clear_rate` when the step has no `with: accepted_play`. See
[baseline-comparison.md](baseline-comparison.md).

## What it does not claim

The report's `measurement_class` is `automation-bot`. It shows the game can be played
and seen. It never shows that first-time players understand it. That is a kill
criterion, measured from people (MV-4), and an automation report never stands in for it.

## Running it outside a run

The step takes the same `checkout.locate` precedence as every step that works in the game
repository ([checkouts.md](checkouts.md)). Its unit tests synthesise records and frames
(`scripts/tests/test_playability.py`). Both golden runs play their ports through it
([golden-runs.md](golden-runs.md)).
