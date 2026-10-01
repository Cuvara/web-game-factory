# 3D production art

**Serves** `build_spec.assets[]` of `type: model` / `dimension: 3d` (`role`, `readability`,
`spec`), `build_spec.visual_identity` (`palette`, `shape_language`, `primitive_style`), the
model spec (`core/artifacts/shared/model-spec.schema.json`), and the 3D scene the game
builds around its models. Judged by the model checks in `core/reference/asset-quality.yaml`
(`models`), the visual gate (`core/reference/visual-quality.yaml`), the production gate and
visual QA.

`production-art-and-ui.md` states the bar; `3d-assets-and-animation.md` and
`3d-scene-and-physics.md` cover loading, animation and the update order. This playbook is
how the reference 3D port (a neon arena racer) went from boxes on a grid helper to a scene a
stranger takes for a product: models as data, then a light, fog and camera set-up that lets
them read on a phone.

## 1. Models are specs: decompose by what a player recognises

Write a model spec, build it with the pinned Blender, inspect the GLB
(`docs/blender-pipeline.md`). One box standing for a whole object is a placeholder and is
refused for a readable role: the model check wants at least 3 composed parts and 2 distinct
part shapes (`models.min_composed_parts`, `.min_distinct_pieces`).

**Decompose by the parts a first-time player names.** Per object type:

| Object | Parts (shape) | What sells it |
|---|---|---|
| Vehicle / craft | hull (box, tapered, bevelled), nose (cone), keel (box, wider on top), canopy (sphere, glass), wings (box, swept, mirrored), wing trim and fins (parented, mirrored), tail, thrusters (cylinder + ring + glowing cone, mirrored), side trim strips | a pointed nose and glowing thrusters say "front" and "back" from any angle |
| Barrier / wall | feet (mirrored), two posts (tapered, bevelled), beam, sill, hazard panel, a chevron (3-segment cone), hazard bars, neon trims, lamps on the posts (mirrored) | the warning colour and lamps read as "danger" before the shape does |
| Track / floor module | plane with a checker texture, lane lines, centre dashes, cross lines every 2.5 m, emissive edge strips, tapered rails, a light pylon | lines running to the horizon make speed visible |
| Backdrop / skyline | a large emissive disc (sun), cut bands across it, 4 layered ridges (low-segment cones), tapered towers with a stripe texture, emissive beacons, a horizon line | depth and a sense of place behind the play space |
| Character | torso (tapered), head, arms and legs (capsules, mirrored), hands or gloves, feet or boots | proportions and the one prop the role is known by |
| Pickup | a disc or gem with a raised rim and an emblem | a shape that is round where threats are angular |
| Prop (pylon) | base, tapered mast, arm, lamp (capsule), ring | it may be simple: props are not readable roles |

**Shape every part.** The tools that turn primitives into objects:

- `taper [x, z]` scales the top of a part: a hull `[0.62, 0.8]` narrows to the front; a keel
  `[1.25, 1.0]` widens on top; a fin `[1, 0.45]` sweeps; a post `[0.8, 0.85]` thins upward.
- `bevel` (metres, up to a third of the smallest side) catches light on edges: 0.035 on a
  0.42 m hull, 0.015-0.03 on trims and posts, 0.04 on a rail. Unbevelled boxes read as
  placeholder.
- `mirror: "x"` writes the other wing, wheel, arm, lamp as `<id>-mirror` - model one side
  only (the reference craft: 13 authored parts, 7 mirrored, 20 nodes).
- `rotation` sweeps and angles: wings `[0, -22, -7]`, a tail `[-15, 0, 0]`, a nose cone
  `[90, 0, 0]`.
- `parent` keeps attachments attached: trim and fin parented to the wing mirror with it.
- `segments`: 8 for small cones and lamps, 12 for thrusters, 14 for a canopy, 40 for a
  large disc. Low segment counts are the style; visible faceting on a
  silhouette edge that should be round is not.

Four of the reference craft's 13 parts, verbatim, and its whole-model fields:

```json
{"parts": [
  {"id": "hull", "shape": "box", "size": [0.42, 0.2, 1.0], "position": [0, 0.1, -0.05],
   "taper": [0.62, 0.8], "bevel": 0.035, "material": "paint"},
  {"id": "nose", "shape": "cone", "size": [0.36, 0.48, 0.16], "position": [0, 0.17, 0.7],
   "rotation": [90, 0, 0], "segments": 8, "material": "paint"},
  {"id": "wing", "shape": "box", "size": [0.5, 0.045, 0.46], "position": [0.4, 0.08, -0.2],
   "rotation": [0, -22, -7], "taper": [1.0, 0.7], "bevel": 0.012, "mirror": "x",
   "material": "paint"},
  {"id": "thruster-glow", "shape": "cone", "size": [0.13, 0.16, 0.13],
   "position": [0.17, 0.11, -0.77], "rotation": [-90, 0, 0], "segments": 10, "mirror": "x",
   "material": "glow"}],
 "pivot": "base-center", "fit": {"size": 1.5, "axis": "z"},
 "collision": {"shape": "box"}, "budget": {"max_triangles": 3000}}
```

**Pivot, scale, orientation.** glTF metres, +Y up, the model faces +Z. `pivot: base-center`
for anything that stands or drives; `origin` for a tiling module. `fit` the longest axis to
world size (craft 1.5 m along z, wall 1.0 m along x) so code never scales by guesswork. Add
`collision: {"shape": "box"}` so the game collides with a proxy, not the visual mesh.

**Budgets** (`budget.max_triangles`; the reference shipped well under them): player 3000
(shipped 1754), threat 1000 (548), track module 4000 (1062), backdrop 6000. Generated textures at 64-256 px
(`checker`, `stripes`) instead of image files.

## 2. Materials: dark bodies, emissive edges

The palette's roles become materials. The reference set (a dark-neon identity):

| Material | Colour | Metallic / roughness | Emissive | Used for |
|---|---|---|---|---|
| paint (player accent) | `#FF2E88` | 0.35 / 0.35 | - | player body |
| hull-dark (surface) | `#16162A` | 0.5 / 0.45 | - | under-bodies, frames, floor |
| glass | `#2EF2FF` | 0.1 / 0.1 | x0.6, opacity 0.82 | canopy |
| metal | `#8A8AA3` | 0.9 / 0.3 | - | thrusters, mechanics |
| trim | `#EDEBFF` | - | `#FF2E88` x2.5 | edge strips that outline the silhouette |
| glow (cool accent) | `#2EF2FF` | - | x4 | engines, lane lines |
| hazard (danger) | `#FFB020` | - / 0.5 | x0.45 panel, x3 neon, x5 lamps | threats only |
| ink | `#0B0B12` | - / 0.6 | - | hazard bars, near ridges |

Rules:

- **The player owns one accent; threats own the danger colour.** Never swap them, never
  decorate with the danger colour.
- **Emissive strength encodes importance:** 0.35-0.8 for world lines, 2-3 for trims and edges,
  4-6 for engines, lamps and beacons - the brightest things on screen are the ones that
  matter.
- **Dark bodies, lit edges.** A mostly dark object with emissive trim along its outline reads
  at any distance against a dark scene, without real lights.
- `model.palette` checks material colours lie within distance 48 of a palette colour.

## 3. Lighting rig

Three lights, no shadows, no point lights - every light is paid for in every lit pixel on a
phone:

| Light | Reference | Job |
|---|---|---|
| Hemisphere | sky `0x8A7CFF`, ground `0x0B0B12`, 1.1 | the shadow side is coloured, never black |
| Key (directional) | white, 1.8, at (4, 9, 7) - high, front-right | form and value on every model |
| Rim (directional) | the accent `0xFF2E88`, 0.8, at (-6, 4, -12) - behind, left | separates the player from the backdrop |

- Light sources the player sees (lamps, engines, pylons) are **emissive materials plus an
  additive halo sprite**, not lights: a 64 px radial gradient texture (1 -> 0.55 at 0.25 ->
  0), `AdditiveBlending`, `depthWrite: false`, opacity 0.55-0.75 (thrusters flicker
  `0.75 ± 0.2·sin(t/45)`). A soft decal under the player (plane 1.6x2.4, opacity 0.5) grounds
  it on the floor where a shadow map would cost too much.
- Glow from emissive + additive sprites replaces bloom post-processing on a phone budget.
- Textures in sRGB (`colorSpace = SRGBColorSpace`).
- Too dark is the common failure: the visual gate wants at least 1 % of pixels lit
  (luminance >= 64) and a luminance spread (std >= 18). The reference sits at 1.3-4.3 % lit.

## 4. Fog, sky and ground

- **Linear fog in a dark purple of the palette**: `Fog(0x1A1030, 16, 62)` - near geometry
  crisp, far geometry fades into the sky colour, depth for free.
- **Sky** is a vertical gradient texture (`#05050C` -> `#16162A` at 0.42 -> `#3A1450` at 0.6
  -> `#1A1030` at 0.66 -> `#0B0B12`), 16x512 is enough, used as `scene.background`; the fog
  colour matches the gradient at the horizon.
- **An emissive backdrop beyond the fog** (`fog: false`, behind the play space) keeps the
  horizon alive: the skyline model at z -95.
- **Never a void**: a large unlit ground plane just under the floor (`#0B0B12`, 400x400).
- **Speed reads from the ground**: a tiled track (9 modules of 10 m) scrolled at simulation
  speed; on the title screen it idles at a slow speed (6 u/s) so the menu is alive.

## 5. Camera and portrait framing

Frame the play space by **width at the player**, not by a fixed position, so portrait phones
see the same lanes as desktop:

| | Landscape | Portrait (aspect < 1) |
|---|---|---|
| Half-width to show at the player | 5.0 | 3.4 |
| FOV (deg) | 38 | 56 |
| Lateral follow factor | 0.4 | 0.55 |

```js
const want = portrait ? 3.4 : 5.0, fov = portrait ? 56 : 38;
const dist = Math.max(6.4, want / (Math.tan(fov * Math.PI / 360) * aspect));
const k = dist / 6.4;
camera.position.set(x * follow, 2.7 * k, dist);
camera.lookAt(x * follow * 0.6, 0.2 - 0.4 * (k - 1), -9);
```

- A long lens from further back makes far threats read larger - better than a wide lens
  close up. Recompute on every resize.
- The player must stay in frame: the visual gate wants a readable entity visible in at least
  half the samples; the reference monitor caught a craft leaving the portrait frame.
- Model life without animation clips: bank toward the steer (`-steerRate*0.06`, eased at
  `min(1, dt*10)`), hover `0.035·sin(t/260)`, thruster flicker.

## 6. Building and checking models

```bash
python3 scripts/wgf-model.py doctor
python3 scripts/wgf-model.py build craft.model.json --id craft --kind model -o craft.glb --twice
python3 scripts/wgf-model.py inspect craft.glb --spec craft.model.json --role player \
  --palette "#0B0B12,#16162A,#EDEBFF,#FF2E88,#2EF2FF,#FFB020"
```

- `--twice` builds twice and requires identical bytes.
- `inspect` needs no Blender; it judges any GLB (a library GLB too): `model.valid`,
  `.parts`, `.triangles`, `.normals` (flat normals present), `.palette`, `.bounds`,
  `.primitive` (fewer than 3 pieces or 2 distinct shapes for a readable role fails).
- Deliver through the assets step: a library (`library.json` mapping the requirement to the
  GLB and its spec, licence CC0-1.0 for your own) or the model author, whose request carries
  the schema, the rules, the palette and this playbook (`craft`).
- Performance: merge static geometry per material and use Lambert for the world (the
  reference held 60 fps that way); keep PBR for the player.

## Failure modes

- **Primitive-only models.** A box craft, a box wall, a grid helper floor - the reference's
  starting point, and what the gate refuses.
- **Too dark.** No hemisphere light, no emissive edges, a black sky: unreadable on a phone.
- **Threat colour on the player** or decoration in the danger colour.
- **Bloom and real point lights** instead of emissive + halo sprites - the frame budget goes.
- **Landscape-only framing:** the player leaves the frame on a portrait phone.
- **Unbevelled, untapered boxes:** technically composed, still reads as placeholder.

## Distilled from

The template's reference 3D port, `examples/neon-drift-arena/wgf-golden/` in the template
repository: `library/models/craft.model.json`, `wall.model.json`, `arena-track.model.json`,
`arena-skyline.model.json`, `library/build-models.sh` (build and inspect commands),
`library/textures/make-textures.py` (sky gradient), `src/rendering/threejs/arena-view.ts`
(lights, fog, sky, ground, halos, wash decal, camera framing, bank and hover, merging);
frames `baseline/` (title, close wall, mobile playing, crash); the 3D asset agent's specs
(craft, barrier, pylon, floor; the one-box cube refused for `player`); the defects "3D scene
too dark, barriers low contrast, craft leaves the portrait frame" and "library GLBs never
inspected" from the 2026-10-01 quality monitor.
