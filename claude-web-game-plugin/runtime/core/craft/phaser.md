# Phaser

**Serves** `build_spec.mechanics`, `.controls`, `.screens`, `.hud`, `.responsive`, the
prototype's playable build, and `perf_budgets` when `engine.type` is `phaserjs`.

Phaser is the second 2D engine the template carries. PixiJS is a renderer and the default;
Phaser brings a scene manager, an input system, tweens, tilemaps, particles, an audio manager
and arcade physics with it. That bundle is roughly 1.5 MB minified, so it earns its place only
when the game uses several of those systems. A game that draws sprites and reads pointer input
is cheaper and just as good on PixiJS. The tech plan records which and why; this playbook is
what a developer needs once the answer is Phaser.

Read `web-performance.md` and `game-feel.md` alongside it: nothing here replaces the budgets
or the feedback bar.

## The one rule that is not Phaser's own

**`@wgf/game-core` owns the loop. Phaser does not.**

`@wgf/phaser-framework` boots `Phaser.Game`, stops its `TimeStep` immediately, and calls
`game.step(time, delta)` once per drawn frame from the renderer's `render()`. There is one
`requestAnimationFrame` in the page and one clock.

| Owner | What |
|---|---|
| `game-core` | The fixed simulation step (`Scene.update(stepMs)`), pause by reason, which scene the game is in, `#hud[data-steps]` |
| Phaser | Display list, input, tweens, animations, particles, arcade physics, audio — advanced once per drawn frame with the real frame delta |

So:

- **Simulation that must be deterministic goes in game-core's fixed `update(stepMs)`** —
  scoring, spawn timers, difficulty ramps, anything a replay or a test must reproduce.
- **Phaser `Scene.update(time, delta)` is for presentation** — reading input state, moving
  what the fixed step decided, driving tweens.
- **Never call `game.loop.start()`, `scene.scene.start()` from outside a scene's own
  lifecycle, or `game.step()` yourself.** A second loop makes the simulation and the drawing
  disagree about elapsed time, and the bug only shows under load.
- **Pause is game-core's.** `Game.pause(reason)` stops calling `render()`, which stops
  stepping Phaser — tweens, physics and animations all stop with it, which is what the portal
  profiles require during an ad break. Do not add a second pause flag inside a scene.

`renderer.game` is the `Phaser.Game`; `renderer.game.scene` is its `SceneManager`. A game
adds its Phaser scenes there, or passes them to `PhaserRenderer` at construction.

## Scenes

Phaser scenes and game-core scenes are different objects and both exist. Keep the split the
same way every time: **one game-core scene per game state** (menu, play, game over), and it
owns the Phaser scene(s) it needs.

- `preload()` loads; `create()` builds; `update(time, delta)` presents. Do not build in
  `preload()`.
- `scene.start(key)` shuts the current scene down and runs `create()` again. `scene.launch()`
  runs one *alongside* — that is how a HUD scene stays up while the play scene restarts.
- **Restart leaks are the defect Phaser games ship with.** On shutdown, a scene must remove
  what outlives it: `this.events.once("shutdown", …)` to clear timers
  (`this.time.removeAllEvents()`), tweens (`this.tweens.killAll()`), input handlers it added
  to `this.input.keyboard` and anything registered on the global registry or on
  `game.events`. Tested by playing, dying and restarting ten times and watching
  `framesRendered` and memory stay flat.
- Data between scenes goes through `scene.start(key, data)` and `init(data)`, or
  `this.registry`, never a module-level mutable.

## Assets

- Load in `preload()` with the loader (`this.load.image`, `.spritesheet`, `.atlas`,
  `.audio`), and report progress: `this.load.on("progress", …)` feeds the platform's
  loading API, which several profiles make a rejection cause if it is missing.
- **Paths are relative.** The bundle is served from a path the portal chooses. Assets live
  under `public/` and are referenced as `assets/…`, never `/assets/…`.
- One atlas beats twenty images: the budget is draw calls, and Phaser batches per texture.
- The asset manifest is the source of truth for what exists; a placeholder is reported as a
  placeholder in the development report, never quietly shipped.

## Input

- Keyboard: `this.input.keyboard.createCursorKeys()` or `addKeys("W,A,S,D")`, read in
  `update`. `keydown-<KEY>` events are for discrete actions (pause, confirm), not for
  movement.
- Pointer and touch: `sprite.setInteractive()` plus `on("pointerdown", …)`, or
  `this.input.on("pointerdown", …)` for anywhere. Every control has a touch path — mobile is
  the majority audience on several profiles, and a keyboard-only prototype cannot be
  playtested on a phone.
- Touch targets are at least 48 CSS px (see `ui-hud-mobile.md`).
- Input must not fire while game-core is paused. Because pause stops the steps, Phaser's
  own `update` stops with it; what still fires is DOM-level handlers the game added itself,
  so add those through Phaser, not to `window`.

## Movement, tweens and physics

- **Frame-rate independence is not optional.** Multiply by `delta`, or use tweens and arcade
  velocities, which are already time-based. A value changed by a constant per `update` is a
  game that plays differently at 120 Hz.
- Tweens: `this.tweens.add({ targets, …, ease: "Quad.easeOut" })`. Linear reads as
  placeholder (`game-feel.md`). Kill tweens on shutdown.
- Arcade physics is enough for platformers, top-down movement, projectiles and pickups:
  `physics: { default: "arcade" }`, then `this.physics.add.collider(a, b)` and
  `this.physics.add.overlap(a, b, onHit)`. Reach for Matter only when the game needs real
  rigid bodies — it costs more on low-end devices.
- Hitboxes: `body.setSize()`/`setOffset()` so the player's box is slightly smaller than the
  sprite and a collectible's is slightly larger.
- Groups (`this.physics.add.group({ maxSize })`) are the pool. Bullets, enemies and pickups
  are recycled with `get()`/`killAndHide()`, never created per shot.

## Camera, world and layout

- `this.cameras.main.startFollow(player, true, 0.1, 0.1)` with `setBounds` and `setDeadzone`.
  A camera that snaps is felt as jitter.
- Keep world coordinates and screen coordinates apart: HUD elements use `setScrollFactor(0)`
  or live in their own scene launched alongside.
- The renderer is resized from above (`renderer.resize(w, h)` on the container's size), which
  calls `game.scale.resize`. Scenes react in a `resize` handler on `this.scale`; they do not
  read `window.innerWidth` themselves. Design for a range of aspect ratios, not one
  (`ui-hud-mobile.md`).

## Tilemaps

- `this.make.tilemap({ key })` with a tileset image, then `createLayer`. Collision by
  property (`setCollisionByProperty({ collides: true })`) rather than by tile index: indices
  change when the tileset is edited, properties do not.
- Tilemap JSON is data, so it belongs in the asset manifest and the tuning data, not in code.

## Audio

- `this.sound.add(key)` and play on the event, with the cue list from `build_spec.audio`.
- The browser blocks audio until a gesture. Phaser unlocks its context on the first input;
  do not also build a second unlock path. Mute routes through the platform binding
  (`onAudioMutedChange`), never a private flag, so an ad break mutes the game.

## UI and HUD

- Phaser text and containers are enough for a prototype HUD; a DOM overlay is fine too, and
  is easier to make accessible (`accessibility.md`). Pick one per screen and stay with it.
- `#hud` and its data attributes are the verification probe the release pipeline reads. The
  game keeps writing them whatever it draws.
- Strings go through i18n, never literals in a scene.

## Debugging

| Symptom | First thing to check |
|---|---|
| Black canvas, no error | A scene was added but never started, or `create()` threw — check the console and that the scene key is registered |
| Nothing moves | `render()` is not being called: is the game-core `Game` started, or is it paused for a reason nobody released? |
| Everything moves at double speed | Something else is stepping Phaser — the TimeStep was restarted, or a second `Game` exists |
| Sprite is invisible | Loaded under a different key, wrong frame name, depth below the background, or alpha/scale 0 |
| `Texture "x" not found` | `create()` ran before `preload()` finished — the key is loaded in another scene, or the path is absolute |
| Collisions do not fire | No collider registered, bodies not enabled, or the group was created without physics |
| Input dead after restart | Handlers were added to a destroyed scene, or `shutdown` did not remove them |
| Game plays differently at 120 Hz | A per-`update` constant instead of `delta`, or simulation in Phaser's update instead of the fixed step |
| Memory grows every restart | Timers, tweens or global listeners not removed on `shutdown` |
| Blurry on mobile | The container is being scaled by CSS; resize the renderer instead |

Arcade physics has `debug: true`, which draws bodies and velocities. Turn it on to diagnose,
off before the commit — it is not a shipping feature.

## QA before reporting a visit done

Beyond the develop checks, play it:

1. The first screen appears with no console error.
2. Assets appear (no missing-texture placeholders).
3. Every control works with keyboard and with touch.
4. The loop is reachable: play, fail, see the failure, restart, play again.
5. Restart ten times: no leak, no duplicate handler, no drifting frame rate.
6. Hide the tab mid-play and come back: the game paused and resumed, and nothing jumped.
7. A narrow phone viewport and a wide desktop one both lay out.

## Reusing Phaser's own catalogue

Phaser publishes a large body of example games and reusable blocks through its own agent
tooling. Read them for API knowledge and for how a mechanic is usually built, and adapt what
fits. Do not let that tooling write this repository: it targets its own project layout and
build, and here the template owns both. Everything it produces arrives as something a
developer adapts into `src/`, under the same review and the same checks as hand-written code.
