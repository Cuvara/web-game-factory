# 3D scene and physics

**Serves** `build_spec.mechanics`, `.controls`, `.game_states`, `.visual_identity`,
`tech-plan.architecture` (`rendering`, `physics`), `perf_budgets`, and the `core-loop`,
`input`, `restart` and `responsive` verification aspects.

A 3D game is a renderer, a simulation and a camera that have to agree about one thing each
frame. This playbook is the default shape of that agreement, and the defaults exist because
the alternatives fail in ways nobody notices until a stranger plays the build.

## What the template owns, and what the game owns

The template's 3D renderer binding is deliberately small: a WebGL renderer with a capped
pixel ratio, one scene, one perspective camera, resize, render and destroy. Nothing else.

| The renderer binding gives you | The game builds |
|---|---|
| The canvas, the context and the pixel-ratio cap | Everything drawn into it |
| One scene and one camera, resized for you | Camera rigs, extra cameras, layers |
| `render()` called from the template's loop | Update order, systems, entities |
| `destroy()` on teardown | Per-scene disposal (see below) |

Import it. Never re-implement it, never construct a second renderer, and never take over the
pixel-ratio cap — it is what keeps a phone's native ratio from missing a 30 FPS floor.

Rules, state, scoring and progression stay engine-free. A mechanic that can only be tested by
opening a browser is a mechanic that will not be tested.

## Update order

One order, every frame, stated in one place:

```
input intents → fixed-step physics → game state and collisions → VFX, camera, UI → render
```

- **Intents, not keys.** Input produces intents (`thrust`, `brake`, `fire`); systems read
  intents. A mobile touch control and a keyboard then emit the same thing, and a test can
  drive the game without a device.
- **Fixed step with a clamped accumulator.** Simulate at a fixed step and clamp the
  accumulated delta (about 100 ms). The clamp is what stops a tab switch or a frame spike
  from spiralling into a hundred catch-up steps.
- **One sync point.** Body transforms are copied to meshes in exactly one system, after the
  simulation. Two places that write a transform is the bug where the mesh and the collider
  slowly drift apart.
- **Camera after state, before render.** A camera that follows last frame's state is the
  input lag players report as "floaty".
- **No allocation in the loop.** Reuse vectors and quaternions; see `web-performance.md`.

## Camera

The camera is a design decision, not a default. Judge every rig by one question: **can the
player see the next decision in time to make it?**

| Rig | Use it for | Watch |
|---|---|---|
| Follow / chase | Driving, running, flying | Damping and look-ahead; too stiff reads as jitter, too soft as lag |
| Third person orbit | Exploration, melee | Never let geometry sit between camera and player |
| First person | Aiming, immersion | Motion sickness: no unrequested roll, no camera shake past a few frames |
| Fixed / isometric | Puzzles, strategy, arenas | Readability of height and depth without perspective cues |

- Pick a **world scale** early (one unit = one metre is a good default) and keep the near and
  far planes tight around it; a far plane of 1000 with a near plane of 0.01 buys z-fighting.
- Field of view is tuning data, not a constant buried in a rig. Widening FOV with speed is
  the cheapest speed cue in 3D.
- On a portrait phone the same rig shows much less. Check the framing at both aspect ratios
  as part of `responsive`, not after it fails.

## Physics: choose the lowest rung that works

Most portal games do not need a simulation. Start at the top and go down only when the
gameplay demands it. **The choice belongs to the tech plan at G3** (`architecture.physics`),
not to development: it is a dependency, a bundle cost and a determinism decision.

| Rung | Use when | Cost |
|---|---|---|
| **Custom collision** | Triggers, pickups, lanes, bullets, overlap tests, rails, endless runners, transform-driven racers, arcade dogfights — anywhere authored feel beats simulation | None. Deterministic, testable without a browser |
| **A rigid-body engine** (Rapier is the usual default; cannon-es where avoiding WebAssembly matters and the scene is small) | Ramps and slopes, stacks, rolling and bouncing, character controllers, moving platforms, destructible props, sensor-heavy levels, high-speed bodies | A dependency, a WebAssembly payload against the bundle budget, and non-determinism to design around |

Anything further (a full engine ported from native) is a tech-plan decision with a written
reason, not a preference.

### If a rigid-body engine is used

- **Never collide against visual meshes.** Use primitives, compound colliders, convex hulls,
  and simplified triangle meshes for fixed level geometry only. Imported models get their own
  collision proxy (`3d-assets-and-animation.md`).
- **Physics ownership is one system**, never render code. Entities hold body handles and
  release them.
- **Sensors are silent without active collision events enabled.** This is the single most
  common "the trigger does nothing" bug.
- **Continuous collision detection only where tunnelling is real.** It costs; a slow body
  does not need it, a bullet does.
- **Kinematic bodies for moving platforms and scripted obstacles**, so they push instead of
  being pushed.
- **Set friction, restitution, damping, mass and gravity scale explicitly**, as named tuning
  constants in one module (`core-loop-and-difficulty.md`), in units that match the world
  scale.
- **Remove bodies on restart.** A body that survives a restart is the leak that only shows up
  on the fourth run.

## Looking right at prototype scope

Order matters more than effort: **authored forms → materials → lighting → effects.** Glow,
fog and bloom on untouched primitives read as a prototype, because they are.

At prototype scope the bar is **readability**, not fidelity: the player, the threat, the
objective and the ground plane are distinguishable at a glance, at the target viewport, on
the lowest planned device class. Depth cues — a contact shadow, a ground grid or texture,
consistent silhouettes — do more for readability than any post-processing pass.

Scope beyond that comes from the design's `visual_identity` and the platform's bundle and
frame budgets. A production visual pass is production work; see `art-direction.md` and
`prototype.md` on polishing instead of proving.

## Disposal and restart

The renderer will not free anything for you. On scene exit and on every restart, dispose
geometries, materials, textures and render targets; remove bodies; cancel loaders in flight;
detach listeners. Heap after ten restarts should look like heap after one
(`web-performance.md`), and `gameplay-review.md` makes this a review blocker.

## Failure modes

- **A scene built first, mechanics bolted on after.** The result is a demo that cannot be
  tuned.
- **Variable-delta physics.** Feels different on every machine and cannot be tested.
- **Two update loops** — one from the template, one the game started — running the same
  systems twice.
- **Transforms written in two places**, so mesh and body drift apart over a session.
- **A camera that hides the next decision**, or that clips into level geometry.
- **Physics chosen at development time** because the plan did not say, adding a dependency
  nobody budgeted for.
- **Restart that does not reset**, leaking bodies, meshes and listeners.

---

Parts of this playbook are adapted from `majidmanzarpour/threejs-game-skills` (MIT).
