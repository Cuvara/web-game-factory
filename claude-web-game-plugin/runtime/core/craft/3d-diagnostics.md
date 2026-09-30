# 3D diagnostics

**Serves** the repair loop (a failed verification or a reviewer's blocker going back to
development), `prototype-report.known_issues`, `perf_measurements`, and the `boot`,
`loading` and `core-loop` verification aspects.

3D fails differently. A 2D game that renders nothing usually throws. A 3D game that renders
nothing often **passes every check it has**: it boots, it reports ready, its loop advances,
its tests are green, and the canvas is black. This playbook is the triage order for that
class of defect, and the measurement discipline for the performance half.

Find the cause before changing anything. A fix applied to a guess is a second defect.

## Reproduce first

Same command, same URL, same viewport as the report. Read the console, the page errors and
the network log before reading the code — a 404 on a model or a decoder answers most of this
list on its own. Then fix the root cause in the module that owns it, and re-run the exact
path that was broken.

## Nothing renders (or renders wrong)

Work down. Each step is cheap and rules out a whole class.

1. **Is anything drawn at all?** Read the renderer's own info counters (draw calls,
   triangles, programs, geometries, textures) during play. Zero draw calls is a scene-graph
   problem; non-zero draw calls with a black canvas is a camera, material or lighting
   problem. This split saves most of the time spent on a blank canvas.
2. **Is the loop running?** Confirm the render call happens every frame, and that it happens
   **once**. Two active loops — one from the template, one the game started — double-render,
   double-step and eat the frame budget.
3. **Where is the camera?** Inside geometry, behind the subject, or with a near/far range
   that clips it. Point it at a known object at a known distance as a test.
4. **Is anything lit?** A material that needs light in a scene with none is black and
   correct. Swap one object to an unlit material to prove it.
5. **Is it in the scene?** Loaded, but never added; added to a different scene; added with
   scale near zero; behind the camera; or with visibility off.
6. **Did the assets arrive?** A swallowed loader rejection leaves an empty, healthy-looking
   scene. Check the network log, then check that the loader's error path is not a resolved
   promise.
7. **Does the canvas have a size?** A drawing buffer that does not match the display size
   gives a stretched, blurred or zero-area image. Resize handling runs on the first frame
   too, not only on a resize event.

## Motion is wrong

- **Delta units.** Milliseconds used where seconds were meant is a 1000× error that usually
  shows as "everything teleports" or "nothing moves".
- **Unclamped delta.** A tab switch produces one enormous frame; without a clamp, bodies
  tunnel through the world on return.
- **Two writers for one transform.** The mesh and the simulation disagree slightly and drift
  over a session (`3d-scene-and-physics.md`).
- **Frame-rate dependence.** Movement that adds a constant per frame is twice as fast at
  120 Hz. `gameplay-review.md` treats this as a blocker.
- **Animation advancing while paused**, so the pose no longer matches the state.

## Input does nothing

- The intent is produced but no system reads it, or the system reads it before it is set
  (update order, `3d-scene-and-physics.md`).
- Listeners bound to an element that the renderer replaced, or to the window when the canvas
  has focus.
- Touch handled as mouse: no touch events, no pointer events, or default gestures scrolling
  the page instead of driving the game. Mobile is a target viewport, so this is a `responsive`
  failure, not a nice-to-have.

## Profiling

Measure, then change one thing, then measure the same thing again. Anything else is a story.

1. **Baseline one fixed scenario** — the busiest moment of a real session, on the lowest
   planned device class or an emulation of it, against the built bundle served as a preview
   (`web-performance.md`). Not the menu, not the dev server, not a fast laptop.
2. **Classify the bottleneck** before optimizing:

| Symptom | Likely class | First moves |
|---|---|---|
| High draw calls, low triangles | CPU / draw submission | Share materials, instance repeats, merge static geometry |
| High triangles | Vertex | Simplify meshes, level of detail, cull aggressively |
| Cost scales with window size | Fragment | Fewer full-screen passes, cheaper materials, lower pixel-ratio cap |
| Frame time fine, stutters | Allocation / garbage | Remove per-frame allocation, pool objects |
| Growing memory across restarts | Leak | Disposal and body removal (`3d-scene-and-physics.md`) |
| Slow first play, fine after | Network / decode | Split bundles, compress meshes and textures, preload less |

3. **Change one thing, re-measure the same scenario**, and confirm the game still looks and
   plays the same. An optimization that changed the visuals is a design change.
4. **Attach the trace to the defect.** A performance claim without a measurement is an
   argument (`web-performance.md`).

## Reporting

Whatever the outcome, say what was run and what was seen. Record the counters (draw calls,
triangles, geometries, textures) and the before/after numbers for the same scenario in
`perf_measurements`; record what could not be reproduced or measured in `known_issues`
rather than leaving it implied. A defect that was not reproduced has not been fixed.

## Failure modes

- **Screenshots as proof.** A still frame shows a canvas, not a game. Gameplay changes need
  gameplay evidence.
- **Optimizing before classifying**, so effort goes to the half of the frame that was never
  the cost.
- **Measuring on the dev server**, which has different code, different assets and no
  compression.
- **Fixing the symptom in the caller** instead of the module that owns the failure, leaving
  the same bug reachable by another path.

---

Parts of this playbook are adapted from `majidmanzarpour/threejs-game-skills` (MIT).
