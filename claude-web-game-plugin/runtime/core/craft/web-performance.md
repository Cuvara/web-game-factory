# Web performance

**Serves** `tech-plan.perf_budgets`, `prototype-report.perf_measurements`, the release
performance benchmarks, the asset pipeline (`asset-policy.yaml` `optimizations`), and the
`boot`/`loading` verification aspects.

For a portal game, load time is part of onboarding and frame rate is part of game feel. The
budgets in the tech plan are the contract. This playbook is how to set them sensibly and
meet them.

## Setting budgets (tech-plan)

`perf_budgets` records FPS, memory, time to interactive and bundle size per device class.
Set them before any code exists, and write the ones the schema has no field for into the
tech plan's architecture notes, so they are budgets and not afterthoughts:

| Budget | Default, low-end mobile class | Why |
|---|---|---|
| `target_fps` | 60 (a stable 30 accepted for 3D, if stated) | Frame drops read as input lag |
| `max_time_to_interactive_s` | ≤ 5 s on a throttled mid-tier connection | See `onboarding-and-portal-ux.md` |
| First meaningful frame | ≤ 2 s | A blank iframe is a closed tab |
| Initial download (before first play) | ≤ 5 MB 2D, ≤ 10 MB 3D, and within the tightest `max_bundle_mb` | Everything else streams after play starts |
| `max_memory_mb` | ≤ 200 on low-end mobile | Mobile browsers kill tabs quietly |
| Draw calls per frame | ≤ 100 for 2D, ≤ 150 for 3D on low-end | CPU-bound on phones |
| Texture memory | Stated per device class | Usually the first memory limit hit |
| Long tasks during play | None over 50 ms | Each one is a visible hitch |

## Meeting them

**Loading**
- Split: a boot chunk (engine, first scene, the loading screen) and deferred chunks (later
  scenes, music, extra content).
- Preload only what the first run uses. Load the rest while the player plays.
- Hash and cache assets, and avoid redundant requests. Portal CDNs reward static,
  cacheable files.

**2D**
- Pack sprites into atlases per scene. Keep one atlas bound per batch where possible.
- Pool sprites, text and particles. Never create or destroy per frame.
- Cache static text as textures. Use bitmap fonts for fast-changing numbers.
- Cap the renderer's resolution at `max_pixel_ratio`.

**3D**
- Compress geometry (mesh compression) and textures (GPU-compressed formats). This is what
  `asset-policy.yaml` names per 3D kind.
- Budget triangles and materials per scene. Reuse materials, instance repeated meshes.
- Bake lighting where possible. Keep dynamic shadows to one light, or none, on mobile.
- Dispose geometries, materials and textures on scene change. The engine will not do it for
  you.

**Runtime**
- A fixed or clamped time step, delta-time movement (`game-feel.md`), and no allocation in
  the frame loop.
- Restarting a run must not leak memory. Heap after 10 restarts ≈ heap after 1.
- Throttle or stop the loop when paused or hidden.

## Measuring (prototype and QA)

- Measure on the **lowest planned device class**, or an emulation of it: CPU throttled 4–6×,
  a mid-tier mobile network profile, and a phone viewport. A fast development machine
  proves nothing.
- Measure the built bundle served as a preview, never the dev server.
- Record FPS during the busiest moment of the session, not the menu. Record memory after
  repeated restarts, and time to interactive from a cold cache.
- Capture a performance trace for any FAIL, and attach it to the defect. A performance
  defect without a trace is an argument, not a defect.
- Report per device class in `perf_measurements`, with `within_budget` true only when every
  budget for that class is met.

## Failure modes

- **Budgets written after measuring.** They are then descriptions, not budgets.
- **One giant bundle** because splitting was left until release.
- **Leaks on restart**, which only show in the long sessions players actually play.
