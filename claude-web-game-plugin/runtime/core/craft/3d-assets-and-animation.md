# 3D assets and animation

**Serves** the asset manifest (`model`, `texture`, `material`, `animation`, `environment`
kinds), `build_spec.assets`, `tech-plan.perf_budgets.max_bundle_mb`, and the `assets` and
`loading` verification aspects.

`core/reference/asset-policy.yaml` says what a 3D asset *is* — its directory, formats, size
cap and the compression it owes. This playbook is what the game does with it at runtime, and
the checks that stop a model from being wrong in a way no test notices.

## Loading

- **The manifest is the list.** Every model, texture and animation clip the build loads is a
  manifest item, loaded from the path its kind's `directory` implies under the game's public
  assets. A file fetched from a URL that is not in the manifest has no licence and no size
  budget, and the `assets` checks will find it.
- **Decoders are payload too.** Mesh compression and GPU texture compression need decoder
  files shipped alongside the build. They count against `max_bundle_mb` like anything else.
  Configure their path once, in the loader setup, not per call site.
- **One loading manager, one progress number.** The loading screen reads it; `loading` is a
  verification aspect and needs something real to observe.
- **A failed load is an error, not a silent resolve.** The most expensive 3D bug is a loader
  whose rejection was swallowed, leaving an empty scene that still boots and still runs its
  loop. Surface it, show it, and report it.
- **Load what the first run needs, stream the rest** (`web-performance.md`). A model loaded
  before the player can act is time to interactive.

## After import, verify the model

A downloaded or generated GLB is not yet a game asset. Before it is wired into anything:

| Check | Why |
|---|---|
| Scale against world units | A model authored in centimetres is 100× wrong and reads as a bug in the camera |
| Bounding box and pivot | An off-centre pivot makes every rotation wrong; a pivot at the head makes placement guesswork |
| Orientation | Forward axis agrees with the movement code's forward |
| Material count and texture sizes | A hero model with 40 materials is 40 draw calls (`web-performance.md`) |
| Animation clip names and count | Code that looks up a clip by name fails silently when it was renamed on export |
| A collision proxy exists | Never simulate against the visual mesh (`3d-scene-and-physics.md`) |

Generated and purchased models both need this pass. Record what was checked; a placeholder
that never got it becomes a scope delta, not a surprise at QA.

## Animation

- **Clips are data.** Name them in one place and map names to states there; do not spread
  string literals through gameplay code.
- **Drive the mixer from the fixed update**, with the same delta everything else uses.
- **Blend transitions.** A cut between locomotion states reads as a glitch; a short crossfade
  reads as motion. Idle → walk → run needs the blend, not more clips.
- **Root motion: pick one owner.** Either the clip moves the character and gameplay reads it,
  or gameplay moves the character and the clip is stripped of root translation. Both at once
  is the classic foot-slide-plus-drift bug.
- **Contact timing is gameplay.** A hit lands when the animation says it lands, or the player
  reads the feedback as broken (`game-feel.md`).
- **Stop mixers on pause and dispose them on restart.** An animation that keeps advancing
  while the game is paused will desynchronise from the state it represents.
- Motion is judged **in motion**. A still screenshot proves a model loaded, never that it
  animates correctly.

## Cost control

- Reuse materials and textures across entities; a shared material is a shared draw call
  batch. Instance repeated meshes (props, crowd, trees) rather than cloning them.
- Texture memory is usually the first budget hit. Size textures for how many pixels they
  actually cover on screen at the target viewport, not for how they look in a viewer.
- Prefer one atlas-style texture set per visual family over one per object.
- Keep level-of-detail simple: if a model is only ever seen at one distance, it needs one
  level.

## Disposal

Every loaded resource is owned by whatever loaded it, and released on scene exit and on
restart: geometries, materials, textures, render targets, animation mixers, and any body the
model's proxy created. The renderer frees nothing on its own, and a leak here only shows up
in the long sessions players actually play.

## Failure modes

- **A model in the build that is not in the manifest** — no licence, no budget, no provenance.
- **A swallowed loader error**, leaving a scene that boots and renders nothing.
- **Decoder files forgotten**, so a compressed model silently fails on the built bundle while
  it worked on the dev server.
- **Scale and pivot discovered during play**, after the movement tuning was built around the
  wrong numbers.
- **Clip lookups by a name the exporter changed.**
- **Root motion owned twice**, or by neither.
- **Placeholders shipped as final**, because nothing re-checked them after the real asset
  arrived.

---

Parts of this playbook are adapted from `majidmanzarpour/threejs-game-skills` (MIT).
