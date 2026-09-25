# Gameplay review

**Serves** the `review-report` returned on each development commit during
`title:prototype`, written by a reviewer who did not write the commit and cannot change it.

A read-only reviewer cannot play the game. What it can do is read the code for the defects
that make a game *feel* broken. Players report these as "laggy", "unfair" or "it froze
after the ad". They are all visible in source.

The review brief the Factory writes sets the verdict shape and the review scope. This
checklist adds a gameplay lens to it. Every item below is a **blocker** when it fails on an
`mvp` path, and at most `minor` elsewhere. Style preferences are never blockers.

## Game state

- [ ] **Restart resets everything.** Score, timers, difficulty step, spawned entities, tweens,
      listeners, audio. Look for state held in module-level variables, or in closures created
      once.
- [ ] **The game's states match `build_spec.game_states`.** Transitions happen only through
      the declared exits. Nothing can reach `playing` from `game-over` except through restart.
- [ ] **No double entry.** Rapid taps on Play or Retry cannot start two runs or two loops.

## Time and frame rate

- [ ] **Movement, timers and spawns scale by elapsed time**, never per frame. A search for
      per-tick constants added to positions or counters finds most of these.
- [ ] **Large gaps are clamped.** A tab returning after 30 s does not simulate 30 s in one
      step (tunnelling, instant death).
- [ ] **Pause stops the simulation, tweens, timers and audio**, and resume continues them.
      Look for `setTimeout`/`setInterval` or wall-clock time used for gameplay while paused.

## Input

- [ ] Touch and mouse are not both handled for one tap. Pointer events are used
      consistently.
- [ ] Inputs during a transition or tween are either buffered or ignored deliberately, not
      lost or duplicated.
- [ ] Listeners added per run or per scene are removed on exit.

## Tuning and design fidelity

- [ ] **The tuning in `build_spec.mechanics[].parameters` and `difficulty.curve` lives in
      data or config**, not as literals scattered through logic.
- [ ] Every mvp reward and failure has its feedback hook: the visual and the audio cue named
      in `build_spec.rewards[].feedback` / `.failure.feedback` / `.audio`. A missing one is a
      design-fidelity blocker (`game-feel.md`, minimum feedback bar).
- [ ] The tutorial approach matches `build_spec.tutorial`, and `shown_once` is persisted.
- [ ] Monetization touchpoints fire only at their declared `state`/`trigger`, and pause the
      game around the ad.

## Resources and performance

- [ ] No allocation in the frame loop (new objects, arrays or closures per tick in hot
      paths).
- [ ] Sprites, particles and meshes are pooled, or destroyed on scene exit. 3D resources are
      disposed.
- [ ] Assets load through the loader with progress, and nothing blocks the first frame.

## Accessibility and safety

- [ ] No effect can flash more than 3 times per second. Reduced motion is honoured where the
      design says so (`accessibility.md`).
- [ ] Audio starts only after a user gesture, and respects mute (`audio.md`).

## Tests that test something

- [ ] Unit tests exercise rules from `build_spec.mechanics[].rules`: the scoring, the ramp,
      the failure condition. A test that only mounts the scene asserts nothing.
- [ ] Browser tests tagged with an aspect actually reach that aspect. A `@game-over` test
      that never loses is not evidence.

## Writing the finding

Each blocker names the file and line, what goes wrong in play ("after restart, the spawn
timer from the previous run still fires, so two waves overlap"), and what would show it
fixed. The next development brief carries it forward as a fix-first item.
