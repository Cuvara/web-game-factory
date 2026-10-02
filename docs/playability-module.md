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

### The bot's five tests, per viewport

- **First session:** opens the game. If the title screen lists a begin input (`play`,
  `start`, ...), the bot presses it. Then it makes no input at all for the idle window,
  `max(experience-rules min_grace_s, the design's grace seconds)`. It records the text on
  screen in the first 3 s of play and any loss.
- **Act:** for each input action listed during play, a frame before and a frame
  `max_ack_ms` after the input.
- **Win:** the oracle plays well. Every rendered frame's entities are sampled for 10 s,
  long enough for a threat that spawns far away to reach the player.
- **Lose and restart:** one success first, then bad play: the first listed move that is
  not the oracle's, never a pause or settings toggle. On a loss, the bot presses the retry
  the result screen offers, then the ready screen's begin input if it lands on one.
- **Pause:** the probe's pause input, else a visible pause button, else Escape. If the
  probe then reports `paused`, the pause screen is measured, then play is resumed. A game
  without a pause is recorded as such; no check here fails on it.

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
| `probe.valid` | snapshots match the schema and carry the contract's goal, win and lose metrics |
| `start.playable` | play begins within `first_30s.playable_s` |
| `start.objective` | ≥ 60 % of the objective statement's content words are on screen in the first 3 s of play |
| `idle.grace` | no loss during the idle window |
| `act.acknowledged` | every action changes ≥ `min_changed_fraction` of the frame by ≥ `min_pixel_delta` luminance |
| `win.reachable` | good play reaches `won`; with no win in the contract, the goal metric rises |
| `lose.reachable` | bad play reaches `lost` |
| `restart.works` | the retry returns to play within `retry_s` + 1 s, with the goal metric reset |
| `entities.visible` | every readable role (player, threat, goal, target, projectile) is visible in ≥ half its samples and, at its largest on screen, covers ≥ `min_area_fraction` of the viewport (median over the role's entities that left during the sample; all of them when none did) |
| `entities.projectile` | a projectile is seen moving for ≥ `min_projectile_frames` consecutive frames |
| `frames.readable` | ≥ `min_lit_share` of pixels lit (luminance ≥ `lit_luminance`), contrast ≥ `min_contrast`, mean ≤ `max_mean_luminance` |
| `page.errors` | no uncaught page error |

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
