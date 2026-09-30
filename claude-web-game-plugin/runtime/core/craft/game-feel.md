# Game feel

**Serves** `build_spec.controls`, `.rewards[].feedback`, `.hud[].feedback`,
`.failure.feedback`, `visual_identity.motion`, and the prototype's claim that the core
gameplay works.

Game feel is how directly the game answers the player. It is not decoration. A good
mechanic with no feedback reads as a broken one, and a playtest of it measures the missing
feedback, not the mechanic.

## The minimum feedback bar (prototype and up)

These are required before a prototype is playtested. They are not polish, and
`prototype.md`'s warning against polish does not cover them.

1. **Every input is acknowledged in the same frame, or the next.** A press state, a sound
   cue, a visual response. If the game action itself is delayed (a jump buffer, a
   cooldown), acknowledge the *input* immediately anyway.
2. **Every reward is noticed.** Each `rewards[].feedback` fires with at least two channels,
   for example a motion plus a sound, or a number pop plus a colour flash. A reward nobody
   notices is not one.
3. **Every failure is understood.** `failure.feedback` shows what caused it (the colliding
   object, the empty meter) before any overlay covers it.
4. **State changes are visible.** A HUD value that changes animates or flashes
   (`hud[].feedback`). It never swaps silently.
5. **Nothing moves linearly.** UI and game objects ease in and out. Linear tweens read as
   placeholder.

## Polish (production)

Layer these on once the loop has passed G4. Each one has a budget, so feel never turns into
noise.

| Technique | Default | Limit |
|---|---|---|
| Hit-stop / freeze frame | 40–120 ms on impactful events | Never on routine events; never more than once per ~0.5 s |
| Screen shake | Small amplitude, decays in under 250 ms | Off with reduced motion; never on UI-only events |
| Squash and stretch | 5–15 % on land, launch and collect | Only on objects the player controls or collects |
| Particles | A short burst on reward or impact | Pool them; cap live particles per device class (see `web-performance.md`) |
| Number pops | Score and currency gains float from their source | Merge rapid gains into one counter |
| Anticipation | A 1–3 frame wind-up before big actions | Never delays the input acknowledgement in the bar above |
| Audio pitch | Rising pitch on combos and streaks | Reset on a break, so the rise stays readable |

`visual_identity.motion` states the motion rule, for example "snappy, overshooting" or "soft,
floating". Every tween follows it, so the game feels like one thing.

## Correctness that feels like feel

These are bugs, but players report them as "it feels bad":

- **Frame-rate dependence.** All movement and timers scale by elapsed time, never per frame.
  A game that is harder on a 120 Hz screen is broken.
- **Input loss.** Taps between frames, or during a tween, are buffered or deliberately
  dropped, never lost by accident. Touch and pointer events are not double-handled.
- **Pause leakage.** Tweens, timers and audio stop on pause (tab blur, ad break) and resume
  from where they were.
- **Hitboxes.** Player hitboxes are slightly *smaller* than the sprite, and collectible
  hitboxes slightly *larger*. Unfair collisions are felt, not seen.

## Respecting the player

- Reduced motion (`accessibility.md`) turns off shake, flash and parallax, and shortens
  tweens. It never removes feedback: swap motion for colour or sound.
- The flash limit applies to every effect in this file.

## Failure modes

- **Juice in place of a decision.** Feedback makes a loop readable. It does not make an empty
  loop interesting (`core-loop-and-difficulty.md`).
- **Effects that hide the game.** Particles over the next obstacle, shake during precision
  input.
- **Every event at maximum.** When everything is emphasised, nothing is.
