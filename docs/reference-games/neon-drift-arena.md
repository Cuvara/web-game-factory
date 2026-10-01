# Neon Drift Arena: replay and return features (spec)

**Status: specification only.** No template code is changed here. Implementation agents build
this in the template's `examples/neon-drift-arena` and its golden port
(`examples/neon-drift-arena/wgf-golden`, Three.js) after the audio work merges. Every number
below is starting tuning in one data table (`src/game/tuning.ts` or similar). The
simulation stays deterministic from its seed (mulberry32), so every rule here can be
unit-tested without a renderer.

Factory side: these features are the `arena-dodge` archetype's `build_spec.depth`
(`scripts/wgf_design/archetypes.py` `DEPTH["arena-dodge"]`, game-design 1.7.0). Everything
past the speed tiers and the best score is `post-mvp` there. A golden design does not claim
the port builds it. Craft: `core/craft/retention-and-progression.md`.

## Reviewed against the current port

Port reviewed: `agent-ref-3d-neon-drift` worktree at `7c132ef`
(`examples/neon-drift-arena/src/game/simulation.ts`, `wgf-golden/src/**`).

| Area | Exists today | New in this spec |
|---|---|---|
| Arena | Half-width 4; craft half-width 0.5; steer 6 u/s | Unchanged. Zone kits re-dress it (F1) |
| Speed | `8 + 0.35 × t` u/s, uncapped | The same ramp, capped at 34 u/s (reached at about 74 s). Relief beats at zone borders (F1) |
| Walls | One type, spawned at z 40 in a random lane, half-width 0.4–0.8; interval `0.9 × 8 / speed` s | Moving walls, laser gates and closing gates by zone (F1) |
| Score | 10 per s survived + 5 per wall passed | Distance in metres shown alongside. Score × near-miss multiplier (F3) |
| Near-miss | "Close call!" when the gap is < 0.8: display only | A combo multiplier up to ×4, paying coins (F3) |
| Lose | A wall overlaps the craft in x while its z is in [−2, 0.5] | Unchanged. A shield absorbs one hit (F2) |
| Persistence | `best` only (`platform.storage`, namespace `neon-drift-arena`) | Versioned save: best score and distance, coins, ships, upgrades, missions, milestones, daily streak (F7) |
| Screens | Title, HUD (best, score, objective, close-call callout, pause), pause, crashed (race again, watch ad to revive) | Title with garage and missions, HUD distance and zone, combo chip, pickup timers, zone banner, result card with coins and missions, garage, missions sheet |
| Variety | One obstacle type; speed only | 4 zones, 4 obstacle types, 3 pickups, coins, 5 ships |
| Seeds | Per run 1, 2, 3, … | Unchanged for normal runs. A daily seed from the date (F8) |
| Probe | `metrics {score, best}`; `entities` `craft` (player), `wall-<id>` (threat) | `distance`, `zone`, `multiplier`, `coins`, `shield`, `ship`, `missions-done`; `entities[].kind`; pickups and coins as `collectible` |
| Ads | Rewarded revive (clears the walls ahead, once per run), interstitial on restart | Revive unchanged. Rewarded "double coins" on the result card, once per run. No ad gates a ship, a mission or a run |
| Models | `craft.glb`, `wall.glb`, `arena-track.glb`, `arena-skyline.glb`; `sky.png`, `spark.png` | Four new ships, three obstacle models, three pickups, a coin, zone kits (Assets) |

None of these exist today: zones or biomes, obstacle variety, pickups, coins, a combo
multiplier, missions, a garage or unlockable ships, upgrades, distance milestones, a daily
seed, achievements.

## Targets

| Measure | Target |
|---|---|
| First session | 3–5 min (design `first_session.target_s` ≥ 140 s): 4–6 runs, the first zone border crossed at least once |
| First new element | The near-miss combo in the first 10 s. The first pickup in the second run. Zone 2 at 500 m (about 35 s) |
| First persistent progress | Coins banked from run 1, and a mission completed in the first session (the easy slot) |
| Retry | ≤ 1 s from the crash card (exists) |
| Return hook on the last card | Coins to the next ship, mission progress, or the next distance milestone |

## Features

Priority **MVP** is the next implementation pass. **Next** comes after it, in order. The ids
in brackets are the archetype's depth ids.

### F1. Distance, zones and obstacle types: MVP [`zones`, `moving-walls`, `lasers`, `closing-gates`]

- `distance` = ∫ speed dt, in metres (1 unit = 1 m). It is shown on the HUD and on the result
  card, and the best distance is kept.
- Speed is `min(8 + 0.35 × t, 34)`. Distance bands at that speed:
  - 500 m at about 35 s;
  - 1000 m at about 56 s;
  - 1500 m at about 72 s;
  - 2000 m at about 86 s.

| Zone | Band | Palette and kit | Obstacle mix (share of spawns) |
|---|---|---|---|
| 1 Neon Grid | 0–500 m | Current cyan/magenta | Walls 100 % |
| 2 Sunset Circuit | 500–1000 m | Orange/violet sky, warm rails | Walls 60 %, **moving walls** 40 % |
| 3 Laser Yard | 1000–1500 m | Green/black, scanline floor | Walls 40 %, moving 30 %, **laser gates** 30 % |
| 4 Storm Core | 1500–2000 m | Deep blue, lightning skyline | Walls 30 %, moving 25 %, lasers 20 %, **closing gates** 25 % |
| Loop | 2000 m + | Zones 2→4 again, palette hue-shifted | As zone 4; spawn interval ×0.95 per loop, floor 0.22 s |

The new obstacle types:

- **Moving wall:** a wall whose gap centre oscillates as `sin(z × 0.35) × 1.5` while it
  approaches, so it slides at up to about 1.5 u/s. It is always passable at the craft's
  steer speed.
- **Laser gate:** three pylons with two beams, one across each half of the arena. The beams
  alternate on 0.6 s and off 0.6 s, so exactly one half is open at any instant. The craft
  passes on the half whose beam will be dark when the gate reaches it. That half is
  predictable, because the gate's arrival time is fixed by the speed, and it is shown as a
  dark floor stripe from 2.5 s ahead. The spawner only places a gate whose open half is
  reachable from the craft's x at steer speed.
- **Closing gate:** two wall halves start at the rails and close toward a gap centre at
  1 u/s. The gap is never smaller than 1.4 (craft width 1.0).
- **Zone border, a relief beat:** for 2 s nothing spawns. A banner shows "ZONE 2 · SUNSET
  CIRCUIT", the palette cross-fades over 1 s and the music layer changes. The first time
  each zone is reached is saved (milestones, F7).
- A new obstacle type's first appearance in a session comes alone, with a wide margin (the
  gap is +30 %), and with a one-line caption ("Pass on the dark side").
- Probe: metrics `distance`, `zone`. Each `entities[]` threat carries `kind: wall |
  moving-wall | laser | closing-gate`.

### F2. Pickups: MVP [`pickups`]

| Pickup | Effect | Duration |
|---|---|---|
| Shield | Absorbs one crash. The craft flashes and the wall shatters. At most one is held | Until hit, or 20 s |
| Magnet | Pulls coins within 3 u in x | 6 s |
| Boost | Speed ×1.3 and invulnerable. Walls passed during it score +5 each and break apart | 3 s |

- One pickup spawns in every 8 wall rows, in a lane reachable from the craft's current x at
  steer speed. There are none in the first 10 s of a player's first run.
- The draw is weighted 40 % shield, 35 % magnet, 25 % boost, and never the same type three
  times in a row.
- Boost never ends inside a wall: it extends until the craft is clear.
- The HUD shows a timer ring per active pickup (bottom-left).
- Probe: pickups are `entities` with `role: collectible` and `kind: shield | magnet | boost`.
  The `shield` metric is 0 or 1.

### F3. Near-miss combo: MVP [`combo`, `near-miss-combo`]

- A near-miss is passing a wall (any type) with an x gap < 0.8 u. This is today's
  `NEAR_MISS_GAP`.
- Each near-miss raises the multiplier by 0.5, up to ×4. It resets after 4 s with no
  near-miss, or on a shield hit.
- The multiplier applies to the per-second score, the wall bonus and coins collected.
- The HUD combo chip (top-right) shows `×2.5`. "Close call!" stays and gains the multiplier.
- Probe metric: `multiplier`.

### F4. Coins: MVP [`coins`]

- Lines of 5 coins appear in the gaps between wall rows, one line in about every 3 rows,
  placed along the safe path.
- Each coin is worth 1 × multiplier, rounded down, with a minimum of 1. Missions and
  milestones pay more.
- Coins are earned only in play and **never sold**.
- The result card counts up the coins earned. A rewarded "double coins" is offered there
  only, once per run.
- Typical earnings are 30–60 coins per run in the first session and 80–150 for a skilled
  run.
- Probe: metric `coins` (the balance). Coin entities are `role: collectible`, `kind: coin`
  (the 8 nearest only).

### F5. Missions, three active: MVP [`missions`]

- There are always 3 active missions, one per slot: easy, medium, hard.
- Completing one pays coins and draws the next mission of that slot from its list
  (deterministic order, no repeats until the list is exhausted).
- Progress is saved continuously, and missions may span runs where they say "total".
- The pause screen and the result card show the three missions with progress bars. A
  mission completing mid-run shows a toast.

| Slot | Missions (in order) | Pays |
|---|---|---|
| Easy | Reach 300 m · Collect 20 coins in one run · Pass 25 walls · 3 near-misses in one run · Use a shield | 20 |
| Medium | Reach 800 m · Reach ×2 combo · Collect 3 pickups in one run · 500 coins total · Reach zone 3 | 40 |
| Hard | Reach 1500 m · Reach ×4 combo · Pass 10 laser gates in one run · Finish a run without steering for 3 s · Reach 2000 m without a shield | 80 |

- Probe metric: `missions-done` (a count).

### F6. Ship garage and upgrades: MVP (ships 1–3, upgrades), Next (ships 4–5) [`garage`, `full-garage`, `next-ship`]

Five ships with distinct models. Each has one bounded trait, so skill decides the run and no
ship is strictly better:

| Ship | Price | Half-width | Steer (u/s) | Trait |
|---|---|---|---|---|
| Dart (current craft) | free | 0.50 | 6.0 | – |
| Wisp | 300 | 0.42 | 5.6 | Narrower, slower to steer |
| Bulwark | 700 | 0.58 | 5.4 | Starts every run with a shield |
| Comet | 1200 (Next) | 0.50 | 7.0 | Pickups last 25 % shorter |
| Nova | 2000 (Next) | 0.50 | 6.0 | A magnet of radius 1.5 is always on; coins ×0.8 |

There are three upgrades, each with three steps, costing 100, 250 and 500:

- **Magnet** 6 → 7.5 → 9 → 10.5 s;
- **Boost** 3 → 3.5 → 4 → 4.5 s;
- **Shield** 20 → 25 → 30 → 35 s held.

Upgrades apply to every ship.

The garage screen shows the ship on a turntable (the GLB, auto-rotating at 20°/s, lit by the
zone 1 kit), its stats as bars, and Buy / Select. A locked ship shows its price and the coins
still needed.

- Probe metric: `ship` (the id string). `window.__game.ship` is available too.

### F7. Persistence and milestones: MVP [`next-zone`, `beat-best`]

- One versioned save through `integration.save/load`, written after every change:

  ```
  { v: 1, best, bestDistance, coins, ship, ships: [...],
    upgrades: {magnet, boost, shield}, missions: {easy: {id, progress}, ...},
    zonesReached: [1, 2], milestones: [500, 1000], daily: {last, streak, freezes} }
  ```

- **Distance milestones** are at 500, 1000, 1500, 2000, 3000 and 5000 m. The first time each
  is crossed pays 25, 50, 75, 100, 150 and 250 coins, and it stays marked on the title
  screen.
- The best distance appears as a glowing line across the track when the run approaches it.
- A missing, corrupt or unknown-`v` save starts fresh, keeping the legacy `"best"`. It never
  crashes.

### F8. Daily run: Next [`daily`, `daily-run`]

- Seed = `YYYYMMDD` (UTC) through mulberry32. It fixes walls, obstacle types, pickups and
  coins.
- One daily goal comes from the seed's row: "reach 1200 m" or "×3 combo".
- Retries are unlimited and the best is kept. The first completion each day pays 50 coins
  and extends the streak.
- The streak survives one missed day with a freeze (one per 7 days, at most 2). There is no
  countdown copy.
- Probe metrics: `daily-best`, `streak`.

### F9. Achievements: Next

There are 12, routed to the platform achievement capability where it exists. Each pays 25
coins.

1. First 500 m
2. Zone 4
3. 3000 m
4. ×4 combo
5. 50 near-misses total
6. Shield save
7. Boost through 5 walls
8. Own 3 ships
9. Max an upgrade
10. 10 missions
11. 7-day streak
12. 5000 m

## Assets needed

These are for the asset agents. 3D models are model specs built headless by the pinned
Blender (`docs/blender-pipeline.md`), in the existing kit's style: low-poly, flat-shaded,
emissive edges, vertex colours in the zone palette. Size is the fitted size along the stated
axis. UI is SVG in the current library's style.

| Id | Kind | Size / budget | Role | Readability | Priority |
|---|---|---|---|---|---|
| `ship-wisp` | model | 1.3 along z; ≤ 3,000 tris; ≥ 10 parts | player | A needle-thin dart with swept fins; reads as narrower than Dart from the chase camera | MVP |
| `ship-bulwark` | model | 1.6 along z; ≤ 3,000 tris | player | A wide, armoured wedge with a visible shield emitter ring | MVP |
| `ship-comet` | model | 1.5 along z; ≤ 3,000 tris | player | A forward-swept racer with twin long engine trails | Next |
| `ship-nova` | model | 1.5 along z; ≤ 3,000 tris | player | A disc-hulled craft with a glowing magnet core | Next |
| `wall-moving` | model | 1.0 along x; ≤ 1,000 tris | threat | The current wall with rail sliders and chevrons showing its slide direction | MVP |
| `laser-gate` | model + vfx | three pylons 1.2 tall; two beams as quad strips | threat / hazard | Pylons and two half-width beams, each unmistakably on (bright) or off (dim dashed line), plus the dark floor stripe | MVP |
| `closing-gate` | model | two halves, each 2.0 along x; ≤ 1,200 tris | threat | Hazard-striped halves whose closing motion is readable from 30 u away | MVP |
| `pickup-shield`, `pickup-magnet`, `pickup-boost` | model | 0.8; ≤ 600 tris each | collectible | Distinct silhouettes (orb, horseshoe, chevron), not told apart by colour alone, bobbing and spinning | MVP |
| `coin` | model (instanced) | 0.5; ≤ 200 tris | collectible | A spinning gold hex coin | MVP |
| `zone-kit-2..4` | material / texture | palette swap on `arena-track` and `arena-skyline`, plus `sky-zone-2..4.png` (1024×512) | environment / background | Each zone recognisable in one frame by its sky and rail colour | MVP |
| `vfx-shield-break`, `vfx-boost-trail`, `vfx-coin-pickup` | vfx | particle presets reusing `spark.png` | vfx | — | MVP |
| `garage-turntable` | model | 2.5 diameter; ≤ 800 tris | prop | A lit platform the ship sits on | MVP |
| `icon-coin`, `icon-shield`, `icon-magnet`, `icon-boost`, `icon-missions`, `icon-garage` | icon | 64 px SVG | icon | The same silhouettes as the models | MVP |
| `badge-<achievement>` ×12 | icon | 64 px SVG | icon | — | Next |

Audio cues (A1):

- `zone-enter` (with a music layer change per zone);
- `laser-hum` (looped while near, synced to the blink);
- `gate-close` (looped while near);
- `pickup-shield`, `pickup-magnet`, `pickup-boost`;
- `shield-break`;
- `coin` (the pitch rises with the multiplier);
- `combo-up`, `combo-reset`;
- `mission-complete`;
- `buy`.

Every cue has a visual twin.

## Probe and test hooks

Additions to `window.__wgf__.play.snapshot()`:

- `metrics`:
  - existing: `score`, `best`;
  - new: `distance`, `best-distance`, `zone`, `multiplier`, `coins`, `shield`, `ship`,
    `missions-done`, `streak`, `mode` (`run` | `daily`).
- `entities[]`:
  - `craft` (`player`, `kind` = the ship id);
  - threats with `kind` (`wall` | `moving-wall` | `laser` | `closing-gate`);
  - `pickup-<id>` (`collectible`, `kind` = the pickup type);
  - `coin-<id>` (`collectible`, `kind: coin`, the 8 nearest).
- `oracle` (`wgf-probe=1`): the steer that clears the nearest threat. For a laser gate,
  this is toward the half open at arrival. It now also includes the safe-path lane for
  coins.
- `window.__game` (tests only):
  - existing: `seed`;
  - new: `setDistance(m)`, `spawnObstacleAt(kind, x)` (extends today's
    `spawnObstacleAt`), `givePickup(kind)`, `setCoins(n)`, `save()` / `reload()`.

## Acceptance tests

Unit tests are on the simulation (`simulation.ts`, `zones.ts`, `save.ts`). Browser tests
drive real input and read the probe.

1. **Distance and zone.** From seed 1 with no input other than the oracle, `zone` becomes 2
   when `distance` ≥ 500 and never before. Nothing spawns for 2 s after the border.
2. **Speed cap.** Speed never exceeds 34 u/s, and the spawn interval never drops below
   0.22 s.
3. **Zone mixes.** Over 10,000 seeded spawns per zone, the obstacle shares are within ±3
   points of the table. No moving wall, laser or closing gate appears in zone 1.
4. **Fair lasers.** For every laser gate spawned over 1,000 seeded runs, the half that is
   open when the gate reaches z = 0 is reachable from the craft's x at spawn time
   (|Δx| ≤ steer speed × time to arrival). The floor stripe marks that half.
5. **Closing gates** never leave a gap < 1.4 u.
6. **Shield.** With a shield, a crash consumes it, destroys the wall and keeps the run going.
   The next crash ends the run.
7. **Boost.** During boost, crashes do not end the run. Boost never expires inside a wall.
8. **Combo.** Three near-misses within 4 s give `multiplier` 2.5. Then 4 s with none
   resets it to 1. Coins collected at ×2.5 count 2 each.
9. **Pickup placement.** Every pickup over 1,000 seeded runs is reachable: |Δx| ≤ steer
   speed × time to arrival. There is no pickup in the first 10 s of the first run.
10. **Missions.** "Reach 300 m" completes during the run that crosses 300 m, pays 20 coins
    and is replaced by the next easy mission. Progress on a "total" mission survives a
    reload.
11. **Garage.** Buying Wisp with ≥ 300 coins deducts 300, selects it, and the next run uses
    half-width 0.42 (a collision test at x offset 0.45 passes). A ship the player cannot
    afford shows the coins needed and cannot be bought.
12. **Upgrades** change pickup durations exactly as in the table.
13. **Persistence (`depth.persists`).** After a run that banks coins and buys a ship, a
    reload keeps `coins`, `ship`, ships owned, upgrades, mission progress and
    `best-distance` equal before any input.
14. **Corrupt save** starts fresh, keeps the legacy `best`, with no console error.
15. **Variety (`depth.variety`).** Oracle play shows `kind: moving-wall` within 15 s after
    `distance` 500, and a `collectible` pickup by the second run.
16. **Ramp (`depth.ramp`).** Under fixed bad play (seeded, non-oracle), the median time to
    crash is under 30 s, and under oracle play the required-input rate rises from zone 1 to
    zone 3.
17. **Return line.** The crash card always shows one of: coins to the next ship, a mission
    in progress, or the next milestone.
18. **Models.** Each new GLB passes `wgf-model.py inspect` against its spec (parts,
    triangles, fitted size). Ships are distinguishable in a frame at play distance (visual
    QA).
19. **No dark patterns.** No ad gates a ship, an upgrade, a mission or a run. Declining every
    offer never blocks progress.
