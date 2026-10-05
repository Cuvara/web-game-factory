# Juice: the numbers

**Serves** `build_spec.controls`, `.rewards[].feedback`, `.hud[].feedback`,
`.failure.feedback`, `build_spec.experience` (acknowledgement, grace, retry), `build_spec.vfx`,
`visual_identity.motion`, and the playability checks `act.acknowledged`, `idle.grace`,
`restart.works` (`docs/playability-module.md`).

`game-feel.md` sets the bar (acknowledged, noticed, understood) and the budgets. This
playbook is the concrete tuning the two reference ports shipped, so a new game starts from
values that are known to feel right on a phone and adjusts from there. Durations are
milliseconds of wall time, scaled by elapsed time, never per frame.

## 1. Acknowledge within 100 ms

`experience-rules.yaml` `feedback.max_ack_ms: 100`; the playability bot measures a pixel
change after each input (`visual-quality.yaml`: at least 0.2 % of the frame by 24+ levels).

- Redraw **synchronously** in the input handler (the 2D reference redraws on drop, capped at
  one redraw per 8 ms), and fire an audio cue in the same handler ("tap", or "merge" when it
  merged).
- Buttons acknowledge on press, not release: 60-80 ms `steps(2)` translate into their shadow
  or scale to 0.96.
- Continuous input (steer) shows on the next frame: the 3D craft banks toward the input
  (`bank -> -steerRate*0.06`, eased at `min(1, dt*10)`).
- Show where the input will land **before** it lands: the 2D "ghost" of the next piece over
  the hovered (or first open) column, alpha 0.92, bobbing `sin(t/260)*0.06*cell`, with an
  arrow to its slot.
- Every keyboard action has a key (2D: `1`-`7` drop in a column, Space/Enter drop, Esc/P
  pause) and every pointer action a key equivalent.

## 2. Landing: drop bounce and squash

Drop (2D reference): 340 ms from `-1.6*cell` above the slot, `easeOutBounce`, with squash in
the last 45 % (`s = sin(...)*0.1`; `sx = 1+s`, `sy = 1-s`).

```js
const easeOutBounce = (x) => { const n = 7.5625, d = 2.75;
  if (x < 1 / d) return n * x * x;
  if (x < 2 / d) return n * (x -= 1.5 / d) * x + 0.75;
  if (x < 2.5 / d) return n * (x -= 2.25 / d) * x + 0.9375;
  return n * (x -= 2.625 / d) * x + 0.984375; };
const easeOutBack = (x, c = 1.70158) => 1 + (c + 1) * (x - 1) ** 3 + c * (x - 1) ** 2;
```

## 3. Reward: merge pop, burst, confetti, streak, number

Scale every reward channel with its size (`merges` = chain length, capped at 3):

| Effect | Duration | Numbers |
|---|---|---|
| Pop on the result | 380 ms | scale up to 1.38 over the first 35 %, back with `easeOutBack(c = 1.9)` |
| Burst sprite behind it | 420 ms | size `cell*(1.35 + 0.2*merges)`, grows 0.35 -> 1.0 (easeOutBack, 1.6x speed), rotates 0.9 rad, alpha 0.95, fades after 45 % |
| Confetti | 620 ms | count `6 + 3*merges` (6-15), size `cell*(0.09 + 0.035*(i%3))`, speed `cell*(1.4 + 0.45*(i%3))`, gravity `+cell*1.4*p^2`, spin 6 rad alternating, alpha `1 - p^2`, palette tints |
| Chain streak | 360 ms | length `max(1.4*cell, distance + cell)`, grows 0.4 -> 1.0, height `0.22*cell`, head leads |
| Points text | 900 ms | `+N` (`+N  xK` on a chain), display face with a 6 px ink stroke, `max(18, cell*0.32)` px, rises `0.7*cell` (easeOutBack), scale 0.6 -> 1.1 in 15 % -> 1.0, fades after 70 %, clamped on screen |
| HUD bump | 240 ms | ease-out, scale peaks at 1.25 at 40 %, on score and next-piece changes |
| Shake | 260 ms | linear decay, amplitude `min(10, 2 + 2.5*merges)` px, offset `sin(t/17)`, `cos(t/23)` |

- **Combo text** is the points text with the multiplier: the chain length is the reward's
  size, readable in words.
- **Throttle**: events less than 50 ms apart share one burst - a chain is one celebration,
  not five.
- A restart or continue clears the board with no fanfare.
- Idle invitation: empty slots pulse `alpha 0.75 + 0.25*sin(t/220)` while the board is bare.

## 4. Danger: near-miss

The 3D reference rewards skill the player did not have to show:

- **Detect**: the clear gap between player and threat < 0.8 units while the threat passes
  (z in -2..1.2); fire once, when the threat leaves, and only if not crashed.
- **Feedback**: a call-out ("Close call!") at the lower quarter of the screen (bottom 26 %),
  display face `clamp(22px, 5vmin, 40px)`, accent glow; pop 1000 ms - scale 0.7 -> 1.08 at
  18 % -> 1, then fades while rising 18 px. Pair with a sound.

## 5. Failure: crash

Show what happened before any overlay covers it:

| Channel | 3D reference |
|---|---|
| Burst at the contact | 90 additive points, size 0.22, spark texture (danger colour); speed 2.5-5.8, up 1-5, back 1.5; gravity 9.8, stops at the floor; fades over 1.1 s |
| Camera shake | amplitude `0.18*(1 - t/450 ms)`, offsets `sin(t/23)`, `cos(t/29)` |
| Screen flash | radial gradient at 50 %/70 % (danger 0.55 -> accent 0.25 -> transparent), fades 600 ms |
| Model | bank back to 0, engines out |
| Result card | enters 650 ms after the crash |
| Audio | "over" cue |

Freeze or slow the world under the burst; never cut straight to the card.

## 6. Opening grace

`onboarding.min_grace_s: 10` - a first-time player cannot fail before the first success, or
before 10 s of play when the grace is a time.

- **Grace until the first input** (3D reference): until the first non-zero steer of a run,
  a collision revives the player and the wall passes through. The player cannot lose by
  not knowing the controls yet.
- Or a time window: no spawn on the player's line for the first 10 s, threats slower.
- A game where nothing threatens (the 2D merge board) needs none: there is no way to lose
  before the first merge.
- `idle.grace` is checked by the bot doing nothing - your grace must survive that.

## 7. Ramps that feel fair

- Speed rises continuously, not in steps: base 8 u/s, +0.35 u/s per second.
- Spawn interval scales inversely with speed (`0.9 * 8/speed` s), so the space between
  threats stays readable as everything speeds up; spawn 40 units ahead.
- Reward pacing: an audio "score" cue every 10 points, so progress is heard as well as seen.

## 8. Motion that stays alive

- Hover `0.035*sin(t/260)`, flicker `0.75 ± 0.2*sin(t/45)`, a slowly scrolling track on the
  title (6 u/s) - nothing on screen is perfectly still.
- Card entry: 260 ms `steps(4)` stamp from scale 1.12, -1.5 degrees.
- `prefers-reduced-motion`: drop shake, flash and bumps; keep the colour, sound and text.

## 9. Interaction effects: the design's contract, measured

Sections 3-5 tune effects; `build_spec.vfx` makes them a contract
(`core/reference/vfx.yaml`): one effect per interaction kind the game has, each with what it
draws, its `duration_ms` and the largest share of the screen it may cover. At a release
quality tier the design must state one for every kind it has (rule
`vfx_covers_interactions`); the production gate checks each fires after its interaction and
stays inside its cap (`vfx.fires`, `vfx.screen_share`), and that the result screen leaves the
win's celebration in view (`vfx.celebration`); visual QA judges the interaction and win
frames (`feedback_visible`, `celebration_visible`).

| Kind | Draw | Duration | Screen-share ceiling |
|---|---|---|---|
| pickup | a ring or glow burst at the item in its accent + the item flying to its HUD counter, which pops | 300-600 ms | 0.08 |
| impact | a short burst at the contact point in the danger colour, a squash of what was hit | 200-400 ms | 0.15 |
| checkpoint | the checkpoint itself lights and a flag or ring snaps at it, in the world | 400-800 ms | 0.2 |
| goal | a celebration at the goal: burst, confetti, the goal lit | 900-1500 ms | 0.6 |
| fail | the cause shown where it happened: a splash, a puff, a flash on the player | 400-800 ms | 0.35 |
| trail | streaks or a trail behind the player growing with speed | segments live 250-450 ms | 0.08 |

- **Effects belong to the world, not the lens.** A checkpoint ring drawn around the camera
  fills the frame; draw it at the checkpoint, sized against the player.
- **More than flecks.** A pickup's few flat squares read as dust: a pickup needs a shape (a
  ring, a glow) and a destination (the counter).
- **The celebration plays before the card.** Delay the result card by the goal effect's
  duration, or place it clear of the goal (a bottom sheet, a side panel) and keep the goal in
  view; the card covering the goal from the first frame of the win hides the moment the
  player earned.
- **In the family's language.** Neon effects are additive glows; lit-stylized effects are
  paper confetti, puffs and lit shapes with no bloom; toon effects are flat shapes with ink
  outlines (`core/reference/art-style-families.yaml`).
- **Report them to the probe.** While an effect draws, the probe lists it as an entity of
  role `vfx` naming its effect id with bounds covering all of it, and each interaction is a
  probe `event` (`core/artifacts/shared/play-probe.schema.json`); a game that does not report
  them fails `vfx.fires`.

## Failure modes

- An acknowledgement that waits for the game action (or the release) - over 100 ms.
- Every merge at maximum: effects that ignore chain size.
- Overlapping bursts from one chain (missing throttle).
- A crash that cuts to the result card before the cause is seen.
- A win card that covers the goal and its celebration from the first frame.
- A pickup that leaves a few flat flecks; a checkpoint ring that fills the screen.
- No grace: the first-time player dies to the first threat before the first input.
- Per-frame constants: a 120 Hz phone plays faster.

## Distilled from

The template's reference ports: `examples/tower-merge-rush/wgf-golden/src/rendering/pixijs/
tower-view.ts` (drop, pop, burst, confetti, streak, points text, shake, throttle, pulse,
ghost), `index.html` (bump, stamp keyframes), `src/game/app.ts`, `src/main.ts` and
`src/input/columns.ts` (synchronous redraw, cues, keys); `examples/neon-drift-arena/
wgf-golden/src/rendering/threejs/arena-view.ts` (crash burst, shake, near-miss detection,
bank, hover, flicker), `index.html` and `src/ui/screens.ts` (flash, call-out, card delay),
`src/game/app.ts` (grace until first steer, cues) and the example's `src/game/simulation.ts`
(speed ramp); frames `baseline/` (2D merge, 3D close wall and crash).
