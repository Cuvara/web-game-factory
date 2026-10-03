# The 3D asset pipeline: Blender offline, three.js at runtime

A 3D game's models are described as data in the game design, built headless by a pinned
Blender into GLB files, checked without Blender, listed in the runtime asset manifest, and loaded by the
game's three.js `GLTFLoader`. Blender is an offline build tool of the `assets` step. It never
reaches a browser and nothing in a game bundle depends on it.

```
OFFLINE  (Factory, scripts/wgf_assets/)                     BROWSER  (game repository)

game-design.asset_requirements[].model   (model spec)
  └─ modelspec.validate / resolve  ── glTF frame, quaternions, linear colour, PNG textures
       └─ blender.py: discover → pin check → key → reuse?
            └─ blender --background --factory-startup ... --python build_model.py
                 parts · materials · textures · fit/pivot · clips · LODs · collision
                 └─ glTF exporter → GLB → stamp asset.extras.wgf {key, blender, …}
  └─ gltf.inspect + check_expectations   ── every GLB, any source, no Blender
  └─ asset-manifest item.model  +  assets.json entry .model   ──────►  fetch assets.json
                                                                        GLTFLoader.loadAsync
                                                                        AnimationMixer / LOD /
                                                                        collision userData
```

Code: `scripts/wgf_assets/` — `modelspec.py` (the spec), `blender.py` (discovery, pin,
command, build, backend), `blender_scripts/build_model.py` (runs inside Blender), `gltf.py`
(the inspector), wired into `pipeline.py` and `step.py`; `model_quality.py` (is it a model
or a primitive) and `model_author.py` (an agent writes the spec). Data: the model spec schema
`core/artifacts/shared/model-spec.schema.json`, the `toolchains.blender` pin and the 3D
budgets in `core/reference/asset-policy.yaml`, the quality bars in
`core/reference/asset-quality.yaml` (`models`), the manifest's `model` and `quality` blocks in
`core/artifacts/asset-manifest.schema.json`. CLI: `scripts/wgf-model.py`.

## What the audit found, and what was built on

- The `assets` step already produced 3D placeholders (procedural box GLBs), sniffed a GLB's
  header, and had a registry of placeholder backends (`procedural`, an optional MCP server).
  Blender is a third backend in that registry: no kernel, engine or `wgflib` change.
- Nothing read a GLB past its header. A truncated index, an external texture, a clip renamed
  on export or a model authored in centimetres all passed. `gltf.py` now reads every GLB the
  step touches — the design's own files, library files and generated ones.
- The runtime is the pinned template's `@wgf/three-framework` (three r170, `engine.type:
  threejs`). It has no loader code of its own yet, and game code cannot live in this
  repository (`test_core_template`), so runtime integration is a contract — node names,
  `extras`, the runtime asset manifest's `model` entry — verified by loading real files with that exact three.js.
- No compression dependency was added. Draco, Meshopt and KTX2 stay deferred build steps
  (`optimization.deferred`), as the policy already says; the inspector flags a GLB that needs
  a decoder (`model-needs-decoder`) and one that needs an extension three.js cannot read
  (`model-unsupported-extension`).

## Blender: version, discovery, headless use

**Pinned series: Blender 4.5 LTS** (`core/reference/asset-policy.yaml`, `toolchains.blender`:
`series: "4.5"`, `tested: 4.5.14`). The build script needs at least 4.2.

The same spec under another Blender series can export different bytes (verified: 4.5.14 and
5.0.1 give different bytes for the same model, each reproducible on its own). So another
series is **refused** unless the installation sets `allow_unpinned: true`, and then every
model it builds records `pinned: false`. Moving the series re-keys every generated model; do
it deliberately, with a changelog entry, and rebuild the fixture (below).

Discovery, first hit wins — never a hard-coded install path:

1. `factory.assets.placeholders.blender.executable` in `workspace/config/factory.yaml`
2. `$WGF_BLENDER`
3. `blender` on `PATH`

```bash
python3 scripts/wgf-model.py doctor          # where, which version, pinned or not; exit 2 if unusable
```

Installing: the portable Linux build needs no root —
download `blender-4.5.<n>-linux-x64.tar.xz` from https://download.blender.org/release/Blender4.5/,
check it against the `.sha256` published beside it, unpack, and point `WGF_BLENDER` at the
`blender` binary inside. On WSL use the Linux build: a Windows `blender.exe` runs, but cannot
read Linux paths.

Every build runs through `wgflib.procs` (own process tree, timeout, heartbeat, cleanup) as

```
blender --background --factory-startup -noaudio --offline-mode --python-exit-code 3 \
        --python scripts/wgf_assets/blender_scripts/build_model.py -- \
        --spec <resolved.json> --textures <dir> --out <model.glb> --report <report.json>
```

with an allowlisted environment (`PATH`, temp dirs, `LANG=C.UTF-8`, `PYTHONNOUSERSITE`) and
`HOME` and every `BLENDER_USER_*` directory inside the build's scratch directory:
`--factory-startup` ignores preferences and the startup file, and nothing from the machine's
Blender configuration or add-ons can reach the output. The script always writes its report;
on failure it names the error and Blender exits 3.

## The model spec

`asset_requirements[].model` on a `model`, `environment` or `animation` requirement. Full
schema: `core/artifacts/shared/model-spec.schema.json`. Coordinates are glTF's = three.js's:
metres, +Y up, the model faces +Z; rotations are Euler degrees, XYZ order.

```json
{
  "id": "hover-car", "kind": "model",
  "model": {
    "parts": [
      {"id": "hull", "shape": "box", "size": [1.2, 0.35, 2.2], "position": [0, 0.45, 0], "material": "paint"},
      {"id": "canopy", "shape": "sphere", "size": [0.7, 0.4, 0.9], "position": [0, 0.3, -0.1],
       "parent": "hull", "material": "glass"},
      {"id": "fan", "shape": "cylinder", "size": [0.5, 0.12, 0.5], "position": [0, 0.1, 0.8], "material": "metal"}
    ],
    "materials": [
      {"id": "paint", "color": "#ff3366", "roughness": 0.4,
       "texture": {"pattern": "stripes", "size": 64, "color2": "#aa1144", "repeat": 2}},
      {"id": "glass", "color": "#88ccff", "opacity": 0.6},
      {"id": "metal", "color": "#bbbbbb", "metallic": 1, "emissive": "#00ffcc", "emissive_strength": 2}
    ],
    "animations": [
      {"name": "hover", "duration": 1, "loop": true, "tracks": [
        {"part": "hull", "path": "translation", "keys": [
          {"t": 0, "value": [0, 0.45, 0]}, {"t": 0.5, "value": [0, 0.55, 0]}, {"t": 1, "value": [0, 0.45, 0]}]}]}
    ],
    "collision": {"shape": "box"},
    "budget": {"max_triangles": 2000, "max_texture_edge": 256}
  }
}
```

| Field | Meaning |
|---|---|
| `parts` | Primitives: `box`, `cylinder`, `cone`, `capsule` (stand along +Y), `sphere` (UV), `icosphere`, `plane` (XZ, facing +Y). `size` is the bounding size. One glTF node per part, named by its id; `parent` nests. |
| `parts[].taper` | `[x, z]`: the part's top is scaled by these factors, linearly from 1 at its base — a torso wider at the shoulders, a cabin narrower at the roof. `size` is the base's. Not on a plane. |
| `parts[].bevel` | Metres: edges where faces meet at 30° or more are rounded with two segments (`bmesh.ops.bevel` on a canonically ordered mesh). Box, cylinder, cone and extrude; at most a third of the smallest side. |
| `extrude` + `outline` | `outline: [[x, z], ...]`: a closed polygon seen from above (+Z the model's front), 3–64 points in order round the shape, concave allowed, never crossing itself; pulled up along +Y into a prism, fitted to `size` like a primitive. Swept and delta wings, fins (rotate it upright), blades, chevrons, arrows, angular slabs — the silhouettes no box can make. |
| `lathe` + `profile` | `profile: [[radius, y], ...]`: an open line, 2–64 points, swept round Y in `segments` steps; radius 0 only at an end (a pole), an end with a radius gets a flat cap. Fitted to `size` (widest radius = half of `size` x/z). Nozzles, bells, domes, bottles, turned posts. |
| `parts[].mirror` | `"x"`: also build the part mirrored across X = 0 of its parent, as `<id>-mirror` — whose parent is the parent's mirror when that is mirrored too. Expanded by `modelspec.resolve` (position x negated, Euler `[a, b, c]` → `[a, -b, -c]`); the primitives and a lathe are symmetric across X, so no mesh is flipped and no node gets a negative scale; an extrude's outline is reflected (x negated, order reversed). A track may animate the mirror by its id. |
| `materials` | Metallic-roughness PBR only — what three.js renders with `MeshStandardMaterial` and no custom shader: `color`, `metallic`, `roughness`, `opacity` (<1 blends), `emissive` + `emissive_strength`, and an optional generated `checker`/`stripes` texture (power-of-two, embedded). No Blender-only node graph is ever built. |
| `pivot` | `base-center` (default: origin at the centre of the base, for placing on the ground), `center`, or `origin`. |
| `fit` | Uniform scale so the model is `size` metres along `axis` (`x`/`y`/`z`/`max`). Baked into vertices and positions, never left as a node scale. |
| `animations` | Named clips of absolute TRS keys per part. `interpolation`: `linear` or `step`. Without `tracks`, a clip is only an expectation the delivered GLB must meet. |
| `lods` | A count (each halves the triangles) or decreasing ratios. Not on an animated model. |
| `collision` | A separate, unrendered proxy: `box` or `convex` (≤ 64 hull points). |
| `budget` | This design's own limits — exceeding one is an **error** (the policy's are warnings). |
| `fps` | Sampling rate of built clips; default 30. |

Rejected before Blender runs (`modelspec.validate`, a malformed requirement fails the step):
unknown or cyclic parents, missing materials, keys out of order or past the clip, a rotation
step of 180° or more (keys become quaternions and a runtime slerps the short way — a 0→360
pair is no motion), a track whose value never changes (the exporter drops constant channels,
so it would silently not exist), and LODs on an animated model.

Taper, bevel and the capsule are arithmetic on the vertices or a bmesh operator on a
canonically ordered mesh, so they are as deterministic as the rest (`--twice` on every one);
a spec that uses none of them builds exactly the geometry it built before they existed (only
the stamped key moves, because the build script is part of it). The same holds for
`extrude` and `lathe`: built vertex by vertex from the numbers, their UVs box-projected on
the finished triangles (a UV layer carried through the bevel operator was not reproducible
from run to run — caught by `--twice`). Adding them re-keyed every build: a committed GLB
built before is rebuilt once (its geometry bytes are unchanged; `hover-car.glb` was rebuilt
identical apart from the key).

A recognisable low-poly object is several shaped parts with palette materials. The keeper the
author tests use (`scripts/tests/fixtures/models/keeper.model.json`) is eight parts, four of
them mirrored: a tapered, bevelled torso; shorts; neck; head; capsule arms with sphere
gloves; capsule legs with bevelled boots — 12 nodes, about 1 500 triangles, fitted to 1.8 m.

**A spec without `parts`** is an expectation only — useful for a purchased or library GLB:
`{"animations": [{"name": "run"}], "collision": {"shape": "box"}, "budget": {...}}` makes the
step fail that file's production readiness if the clip or proxy is missing.

**Final or placeholder.** A buildable spec with `source` unset or `procedural` is the asset
itself: `public/assets/<dir>/<id>.glb`, `status: delivered`, `placeholder: false`,
`LicenseRef-factory-generated`, production-ready when clean. With another `source`
(`purchased`, `commissioned`, …) Blender builds a better stand-in, still
`<id>.placeholder.glb`.

## What the build makes

```
<asset>                  root; extras {wgf_asset, wgf_format: 1}
  <part> …               one mesh node per part, in the spec's hierarchy
  <asset>_LOD0           only with LODs: empty holding the parts; extras {wgf_lod: 0}
  <asset>_LOD1 …         one joined mesh per ratio; extras {wgf_lod: n}
  <asset>_collision      only with a proxy; no material;
                         extras {wgf_role: collision, wgf_shape, wgf_center, wgf_half_extents}
asset.extras.wgf         {generator, key, spec_hash, blender, exporter, format}
```

Exporter settings are fixed in `build_model.py` (`EXPORT_OPTIONS`): GLB, +Y up, extras on,
normals and UVs, no tangents, cameras, lights, skins, morphs, Draco or gltfpack; clips from
NLA tracks. An option a Blender version does not know is dropped and recorded
(`model.generation.export_options_unsupported`), never silently different.

**Skinning is not generated.** Parts animated as rigid nodes cover vehicles, props,
turrets, pickups and blocky characters; an armature generator would be most of a framework
and is left out until a game needs one. Skinned GLBs from other sources are validated
(joints, inverse bind matrices, `JOINTS_0`/`WEIGHTS_0`).

## Determinism

The same spec and the same Blender version give byte-identical GLBs across separate Blender
processes. What ran: on 4.5.14, every real-Blender test model built at least twice (the LOD
and convex-proxy model three times) and the committed fixture rebuilt byte for byte; on 5.0.1,
the car and the LOD model twice each. Cross-machine reproducibility follows from the same
inputs but was measured on one machine only. Getting there took three fixes, each found by
building twice and diffing buffers; a fourth change keeps the proxy light:

| Source of drift | Fix |
|---|---|
| Face order out of some bmesh primitive operators varies run to run | `canonical()`: vertices and faces sorted by geometry before every mesh is written |
| Quads tessellated by the exporter in varying order | every part triangulated in bmesh with fixed quad/ngon methods |
| Blender's collapse decimation picks different collapses per run | LODs by vertex clustering, pure arithmetic in fixed order, cell size binary-searched to the ratio |
| A convex hull of every vertex: deterministic but ~1000 triangles | at most 64 clustered hull points → ~100 triangles |

Other inputs are closed off: factory startup, isolated user directories, no timestamps or
random ids anywhere, names only from the spec, textures made by `modelspec` (not by Blender's
image encoder), JSON sorted when stamped.

`python3 scripts/wgf-model.py build spec.json --id x -o x.glb --twice` builds twice and fails
unless the bytes match.

## Reuse: CI and re-runs without Blender

A build is keyed: sha256 over the resolved spec, texture bytes, `build_model.py` and the
Blender series. The key is stamped into the GLB. When the file already at the model's path
in the game repository carries the key the spec would produce, it is reused and Blender is
not started (`model.generation.reused: true`).

So the pipeline's CI rule is: **generated models are committed in the game repository**
(the develop commit carries `public/`), and a runner — or a re-executed step — without
Blender keeps them. Only a changed spec, a changed build script or a new series needs Blender.
Without it, that model falls back to the procedural placeholder with a
`model-spec-unbuilt` warning (an error, and with `strict` a failed step, when the backend's
`required: true`). The backend's `generation.backends` note says why:
`reuse-only: Blender not available: …`.

## Validation

`gltf.inspect` (standard library, no Blender) runs on every GLB and `.gltf`:

| Check | Issue code |
|---|---|
| Container, chunk and JSON; glTF 2.0; every index in range; accessor and bufferView ranges; one parent per node; no cycle; a scene with nodes; visible triangles | `model-invalid` |
| A buffer or image by external URI (a data URI is a size warning) | `model-external-reference` |
| `extensionsRequired` three.js r170 cannot read / needs DRACOLoader, KTX2Loader or MeshoptDecoder for | `model-unsupported-extension` / `model-needs-decoder` |
| Non-finite TRS, matrix and TRS together, a non-unit quaternion, a zero scale (errors), a negative scale (warning) | `model-transform` |
| Visual model over 200 m (2 km for environments) or under 5 mm across | `model-scale` |
| Embedded image not PNG/JPEG/WebP/KTX2, not a power of two | `model-invalid`, `not-power-of-two` |
| Unnamed or duplicate clip; a channel animating a target twice; bad path; sampler output count | `animation-invalid` |

Then against the spec and the policy (`gltf.check_expectations`): a declared clip missing
(`animation-missing`) or of another duration; a declared LOD level missing (`lod-missing`) or
not reducing (`lod-invalid`); a declared proxy missing (`collision-missing`) or over 256
triangles; the fitted size (`model-scale`) and pivot (`model-pivot`); triangles, texture edge
and bytes against the budget (`model-over-budget`, `texture-too-large`, `too-large`).
Policy budgets per kind: model and animation 20 000 triangles and 1024 px; environment 100 000
and 2048 px. Duplicate asset ids are refused with the requirements, as before.

The result is the manifest item's `model` block: triangles and vertices of the visual model
at rest (LOD0, proxies excluded), nodes, meshes, materials, embedded textures, dimensions and
bounds, clips with duration and channel count, LOD levels with their triangles, the proxy,
skins, extensions, and for a generated model its `generation` (tool, version, exporter,
pinned, key, spec hash, reused).

```bash
python3 scripts/wgf-model.py inspect public/assets/models/car.glb --spec car.model.json
```

## Quality: a model, or a primitive standing in for one

A GLB can pass every check above and still be a 1 m cube where a goalkeeper should be — the
real run's 3D assets were 12-triangle boxes with no normals. `model_quality.assess`
(`scripts/wgf_assets/model_quality.py`, standard library, no Blender) judges the file itself
and returns the asset-manifest item's `quality` block (asset-manifest 1.4.0): `verdict`,
`checks`, `primitive_only`, `parts`, `triangles`, `colors`, `author`. Bars:
`core/reference/asset-quality.yaml`, section `models`.

The visual model (LOD0; proxies and LOD1+ excluded) is split into connected **pieces** —
triangles sharing a vertex position, so UV seams do not split one — per mesh instance, and
each piece is normalised to its bounding box in the mesh's own axes and tested against the
primitives, every vertex within `shape_tolerance` (2 %) of the piece's size:

| Primitive | Signature |
|---|---|
| box | 8 distinct positions, all corners of the bounding box |
| plane | flat on one axis, 4 corners |
| sphere | every vertex on the inscribed ellipsoid (UV and ico spheres) |
| cylinder / cone | vertices only at both ends of one axis, on the inscribed ellipse (or an apex) |
| capsule | a straight wall between two hemispheres, along the longest axis |

A bevelled, tapered or modelled piece matches none. **`primitive_only`** is true when every
piece matched and they are not composed: fewer than `min_composed_parts` (3) pieces, or
fewer than `min_distinct_pieces` (2) different shapes or proportions — one cube, a sphere, or
three equal cubes are primitive only; a keeper of torso, head, arms, gloves and legs, or a car
of body, cabin and wheels, is composed.

| Check | Fails when |
|---|---|
| `model.valid` | an error finding of the inspector or of the spec's declarations |
| `model.parts` | no piece, or fewer mesh nodes than the spec builds (mirrors included) |
| `model.triangles` | none, or over a budget the design declared |
| `model.normals` | a visible primitive has no `NORMAL` |
| `model.palette` | no material base colour within `palette_distance` of the visual identity's palette (skipped without a palette, or when only textured materials could match) |
| `model.bounds` | no bounding box, or not the spec's fitted size |
| `model.primitive` | `primitive_only` and the role is readable (`player`, `threat`, `goal`, `target`, `projectile`, `collectible`, `hazard`) — unless `visual_identity.primitive_style` is stated, or the model is a composed round body (below) |
| `model.silhouette` | a box with bumps: the role is in `silhouette_roles` (`player`, `threat`) and, in every view, one component covers more than `max_dominance` (0.6) of the outline — unless `primitive_style` is stated, or the model is a composed round body (below) |
| `model.contrast` | a dark model on a dark scene: under `min_contrast_share` of the visible surface (by area; base or emissive colour, the brighter) stands off the design's background by 3:1 - player 0.5, collectible 0.4, threat and hazard 0.25 (calibrated: the reference craft 0.76 and wall 0.30 pass, a black-hulled craft 0.35 and a near-black asteroid 0.07 fail) |

**The silhouette proxy.** `model.primitive` passes a hull with a canopy and a fin hidden
inside its outline — composed, yet "an orange brick with no wings" in the game. So the
visual model's triangles are projected orthographically from the front, the side and the top
onto a grid (64 cells on the longer side, every triangle covering each cell it touches), and
per view the share of the outline covered by its largest **part** (mesh node) is measured; a
model that is one mesh (another tool's export) uses the largest rectangle inside the outline
instead. The most distinctive view (smallest share) is the score, reported with the fill and
block measures per view (`geometry.silhouette`). A view in which the model is flat is
skipped. Calibrated on the 3D reference game's library (the golden ports' Blender builds,
`test_model_review.ReferenceLibrary`):

| Model | Dominance | |
|---|---|---|
| reference craft (13 parts, delta wings, thrusters) | 0.29 | pass |
| reference skyline / track / wall | 0.27 / 0.39 / 0.53 | pass |
| keeper (torso, limbs, gloves) | 0.38 | pass |
| body-cabin-wheels car | 0.53 | pass |
| hover car (box hull, sphere canopy, fan) | 0.63 | fail |
| the autonomous "brick" craft (audit 2026-10-02) | 0.66 | fail |
| one box | 1.00 | fail |

A pure outline measure (bounding-box fill, largest rectangle) could not separate the brick
from the reference craft — the brick's protrusions widen its box — and ranked a plain car
boxier than the brick: the brick's defect is that its parts do not reach the silhouette,
which is what the part share measures. It is a proxy, not taste: it catches a box with
bumps, it does not judge whether a ship reads as a ship. That is the renders' job, below.

**A round body.** A ball, a marble, an orb has no wings or limbs: its outline *is* the disk,
and a faceted sphere is what its design asks for, so both checks above refuse every correct
model of it (a marble game's player, 2026-10-03: refused three rounds running, bent into a
drum, then a placeholder). `models.round_body` in `core/reference/asset-quality.yaml` passes
`model.primitive` and `model.silhouette` for a model only when all three hold: the
requirement's own description, readability or spec names one of its `words` (ball, marble,
sphere, orb, bubble, globe, planet - a whole word or its plural); the outline is a disk in
every one of the three views (fill 0.62-0.86 of its rectangle - a disk is 0.785, a faceted
low-poly shell down to 0.65, a box or a drum's side 1.0 - and the rectangle at most 1.18
to 1); and at least two different pieces show on its surface (a shell and a swirl band),
each reaching at least 0.9 of its radius from its centre, and one of them other than the
shell the nearest surface over at least 10% of the outline in at least two of the three
views (`min_shown`, `min_shown_views`: a depth buffer on the 64-cell outline grid, from
the view's front or back). A lone sphere is still a placeholder, so is one with bands sunk
inside it or just under its surface, and so is a plain shell with a few specks on it (a
live run, 2026-10-04: a band sunk at half the radius and two specks passed, and visual QA
saw a plain red sphere); a goalkeeper drawn as a blob is not a round body. The passing check's
summary says "a round body: ..." so the asset report shows the exemption, and
`primitive_only` is false for it. The author is told to compose a round body, never to
reshape it (`model_author.RULES`). `wgf-model.py inspect --design --asset` reads the
requirement the same way.

The verdict is `fail` when any check fails. For a person:

```bash
python3 scripts/wgf-model.py inspect keeper.glb --role player --palette "#ff7a1a,#1d2b53"
python3 scripts/wgf-model.py inspect keeper.glb --design game-design.json --asset keeper
```

prints the pieces by primitive, `primitive_only`, the colours and every check; with a role
(`--role`, or `--design` with `--asset`), a failed verdict exits 1.

## The model author

`model_author.produce_model(requirement, visual_identity, out_dir, settings, context)`
(`scripts/wgf_assets/model_author.py`) is the `author` source for 3D: an agent writes a
model spec for one requirement, and everything after it is the Factory's own.

```
request (role, description, readability, palette, the schema, rules, a worked example)
  -> the author command writes a model spec          {request} {spec} {prompt} in argv
  -> schema + modelspec.validate + buildable         refused: shown back
  -> blender.build_model (pinned, headless)          failed: shown back
  -> gltf.inspect + check_expectations + model_quality.assess   failed: shown back
  -> up to 2 repair rounds with exactly those problems, then ModelAuthorError
```

It returns `{files: [<out_dir>/<id>.glb], quality, source: "ai-generated", license:
LicenseRef-factory-generated, placeholder: false, notes, spec, model, rounds, history}`. The
author only writes the spec; it never touches Blender, the file or the verdict. The command
runs through `wgflib.procs` with the allowlisted agent environment (`wgflib.agentenv`, plus
`factory.agents.env_passthrough`), like the design author. Settings: `kind: command`,
`argv`, `spec_from` (`file` | `stdout`), `timeout_seconds` (900), `idle_timeout_seconds`
(300), `max_repair_rounds` (2), `blender` (as the backend's). A host that fails or goes
silent raises `ModelAuthorError` with `retryable = True`; Blender missing or unpinned is
refused before the author runs. Requests, specs, logs and the accepted spec are kept under
`context.run_dir/<id>/`. The requirement's own `model` (clips, collision, fit, budget) is
held to the authored model like any delivered GLB. Wiring it into the `assets` step is the
step's: the `assets` step hands it a plain context dict (`run_dir`, `config`, `policy`,
`design`) — before 2026-10-02 it handed on the step's context object, `dict()` of which
raised, so every real run's model author failed with a `generation-failed` warning.

### Renders and self-review

The reference game's models were specs a person iterated by **looking at renders**. The
author gets the same pictures (`scripts/wgf_assets/render.py`,
`blender_scripts/render_models.py`): after each round's builds, the pinned Blender renders
every built GLB headless through `wgflib.procs` (the build's environment: no preferences,
add-ons or home) into a contact sheet `<id>.sheet.png`, left to right:

| View | What it shows |
|---|---|
| `three-quarter` | front-right, from above |
| `side` | the profile |
| `top` | from above, the model's front up |
| `game` | from the design's `engine.camera`, when it states one a view can be made from: a chase camera sees the player from behind and slightly high and everything else from the front; top-down, isometric, side views likewise |
| `gameplay` | that view (or the three-quarter) rendered at the size the `readability` line names ("readable at 80 px wide"; else 96 px) and enlarged without smoothing: the pixels a player gets |

Lighting is the craft guide's rig in the design's palette (`production-art-3d.md`, "Lighting
rig"): a hemisphere ambient (the darkest palette colour below, the lightest tinted toward the
accent above), a white key high front-right, a rim from behind in the player's accent (the
palette entry whose token or role names the player/accent/signal, never the danger colour;
else the most vivid). The background is the darkest colour; collision proxies and LOD1+ are
hidden. Engine: Eevee, else Cycles on the CPU (which needs no GPU); fixed samples, seed 0, no
denoiser, the Standard view transform so palette colours come out as authored. The PNGs are
evidence for a reader, never a build output, and are not hashed. Each view's alpha mask is
measured (`coverage` of the frame, `fill` of its own box). A render failure is not a
refusal: the round goes on without pictures, and no review round is asked for.

```
round 0   author (blind)  -> build -> judge -> render
repair    (max_repair_rounds, 2) the problems AND the renders of what was refused
review    (review_rounds, 1) every model passes: "open the renders; at gameplay size does
          the silhouette read as `readability`? leave the spec as it is, or revise it"
          -> an unchanged spec is the author's "it reads"; a revision is built, judged and
          rendered; one that breaks a check is repaired while repairs remain, else dropped
```

Only a passing spec ever replaces a passing spec. The result adds `renders` (`sheet`,
`views`) and `review` (`rounds`, `reads`, the author's one-line `note`); the manifest item's
notes name the sheet.

### Set mode

`mode: set` (`model_author.produce_models(requirements, ...)`) authors **every** 3D
requirement of the design in one session: one palette, one material language (the same
material ids and values in every spec), one level of detail, real sizes. The request carries
every asset, the full `visual_identity`, `art_direction`, the game's `camera`, `set_rules`,
the schema, the rules, the example and the craft guides by absolute path
(`production-art-3d.md` — which holds the reference game's own spec, material table and rig —
`3d-assets-and-animation.md`, `art-direction.md`). Each round also renders the set:
`set.png`, every model side by side at its real size from the three-quarter view and the
game's camera, through a long lens so relative size reads. Repair rounds name the refused
specs; the author may also change one the set render shows does not belong. The `assets`
step defers every 3D requirement that reaches the model author and calls the set author once;
a requirement it could not make falls back to placeholders exactly as in `each` mode.

With `spec_from: file` the session writes `<id>.model.json` files in `{dir}/specs/` (the
request's `spec_paths`); on a repair or review they hold the previous specs, to be edited in
place, and an untouched file is unchanged. Scope the host's writes to that directory: for
Claude Code, `--allowedTools "Read,Edit({dir_rule}/**)"` — `{dir_rule}` is `{dir}` as a
permission rule names it, `//` and the POSIX form, so it is absolute on Windows too
(`//c/Users/...`; `wgflib/permpath.py`; the older `Edit(/{dir}/**)` is read as this), and an
`Edit(...)` rule governs every file-editing tool (verified 2026-10-02 with a real `claude -p`:
a `Write(...)` rule is ignored with a warning; a write inside the directory and a
subdirectory succeeded, one outside was refused). With `spec_from: stdout` the answer ends
`{"models": {"<id>": <spec>, ...}}` (on a review: only the revised specs).

Settings: `mode` (`each` | `set`), `review_rounds` (1), `render` (`{enabled: true, engines,
samples, tile, timeout_seconds}`), and `{dir}` in argv. `python3 scripts/wgf-model.py render
[ID=]a.glb ... -o DIR [--design game-design.json | --palette ... --camera ...]` renders the
same sheets and set outside a run. The autonomous profile uses set mode, file specs and the
scoped Edit rule ([autonomous-runs.md](autonomous-runs.md)); a read-only per-model author
(`spec_from: stdout`, only `Read`) is commented in the shipped `factory.yaml`
([claude-capabilities.md](claude-capabilities.md), "The asset authors and the visual-QA
judge").

## Runtime integration (three.js)

Blender is not in the bundle; the game receives GLBs, listed like every other asset in the
runtime asset manifest `public/assets/assets.json` ([assets-module.md](assets-module.md),
`shared/runtime-assets.schema.json`). A GLB's entry adds `model`:

```json
"hover-car": {"type": "model", "url": "models/hover-car.glb", "format": "glb",
  "model": {"clips": ["hover", "spin"], "lods": [], "triangles": 280,
            "dimensions": [1.2, 0.91, 2.2],
            "collision": {"node": "hover-car_collision", "shape": "box"}}}
```

URLs are relative to `assets.json`; the file is deterministic and pinned by hash in the asset
manifest's `runtime_manifest`. The loading contract, which `core/craft/3d-assets-and-animation.md` states
for the developer:

- one `GLTFLoader` (with its `LoadingManager` for the progress number), preloading the manifest's
  `url`s relative to `assets.json`; a rejected load is an error, not an empty scene;
- clips by name through one `AnimationMixer` per instance, driven from the fixed update;
- a node with `userData.wgf_role === "collision"` is hidden and handed to physics
  (`wgf_shape`, `wgf_center`, `wgf_half_extents` for a box need no mesh at all);
- nodes with `userData.wgf_lod` become the levels of a `THREE.LOD`;
- dispose geometries, materials, textures and mixers on scene exit and restart.

**Verified with the runtime's own three.js**: `scripts/tests/threejs_runtime.py` loads GLBs
with the pinned template's three r170 `GLTFLoader` in Node — root and proxy `userData`,
`MeshStandardMaterial` with its map, `THREE.LOD` levels, and every clip resolving its nodes
and moving them through `AnimationMixer`. Node has no DOM, so `self`, `createImageBitmap`
(image size only, no pixel decode) and `fetch` of `blob:` URLs are shimmed; the rest is
three.js. It does not render a frame: pixels on a GPU remain the golden runs' and a person's.

## Configuration

`factory.assets.placeholders.blender` (or a step's `with: placeholders: {blender: …}`):

| Key | Default | |
|---|---|---|
| `executable` | `$WGF_BLENDER`, then `blender` on PATH | the Blender binary |
| `timeout_seconds` | 300 | per build |
| `allow_unpinned` | false | build with another series; models record `pinned: false` |
| `required` | false | a spec that could not be built is an error, not a warning |

The backend joins automatically — first in the order — whenever a requirement carries a
buildable spec; designs without one see no change.

## CI

`.github/workflows/acceptance.yml` is unchanged and needs no Blender: the fake-Blender tests
cover discovery, pinning, commands, the step, reuse and fallback through the real process
layer, and the runtime tests load the committed Blender-built fixture
(`scripts/tests/fixtures/models/hover-car.glb`).

The real builds are opt-in, exactly like the goldens:

```bash
WGF_BLENDER_TEST=1 WGF_BLENDER=/path/to/blender-4.5.14-linux-x64/blender \
  python3 -m unittest scripts/tests/test_models.py
```

They build every shape, track type, LOD and proxy; check determinism; run the step twice
(build, then reuse); and rebuild the committed fixture **byte for byte**. When the build
script changes on purpose, that last test fails with the command to rebuild the fixture:

```bash
python3 -c "import json; print(json.dumps(json.load(open('scripts/tests/fixtures/models/design-models.json'))['asset_requirements'][0]['model']))" > /tmp/hover.json
python3 scripts/wgf-model.py build /tmp/hover.json --id hover-car -o scripts/tests/fixtures/models/hover-car.glb --twice
```

## Troubleshooting

| Symptom | Cause, fix |
|---|---|
| `reuse-only: Blender not available: blender is not on PATH` | Install 4.5 LTS; set `WGF_BLENDER` or `executable`. `wgf-model.py doctor` confirms. |
| `not the pinned series 4.5` | A different Blender was found. Point at 4.5.x, or `allow_unpinned: true` knowingly. |
| `model-spec-unbuilt` | The spec's model was not built and a box stands in; the note says why. |
| `Blender build of 'x' failed: …` | The report's error (the traceback is in the report when kept); usually a spec the script cannot build. |
| `twice: DIFFERENT bytes` | Nondeterminism in this Blender: report it with the spec; do not ship until reproducible. |
| `animation-missing` on a built model | A clip whose tracks were dropped — should be caught earlier by the constant-track rule; check the spec. |
| `model-needs-decoder` | The GLB is Draco/Meshopt/KTX2-compressed: the game must configure the decoder and ship its files. |
| Model 100× too big | `model-scale`: authored in centimetres; set `fit` or fix the source's unit. |

## Known limitations

- **No generated skinning or morph targets.** Rigid-part animation only; skinned GLBs from
  other sources are validated, not made.
- **Shaped primitives, outlines and profiles only.** Parts are boxes, cylinders, cones,
  capsules, spheres, icospheres and planes, extruded outlines and lathed profiles, tapered,
  bevelled and mirrored - enough for a recognisable low-poly character, vehicle or prop, not
  for organic sculpting or jagged rock (no vertex noise); importing and cleaning a sourced
  mesh through Blender is not implemented (a sourced GLB is validated as delivered).
- **The silhouette check is a proxy.** It refuses a box with bumps; it cannot say a ship
  reads as a ship. The self-review over renders is the author's judgement of its own work,
  not an independent one - visual-qa judges the game's frames later.
- **Renders need a working Blender render engine.** Eevee needs a GPU context; without one
  the renderer falls back to Cycles on the CPU (slower, same rig).
- **Primitive detection is geometric.** A piece is judged by where its vertices lie, not by
  how it looks: a textured sphere is still a sphere, so a ball (a `projectile`) must be
  composed (panels, a seam ring) or the art direction must state `primitive_style`. A
  compressed or quantised GLB is not decoded (`model.primitive` skipped), and textured
  materials' colours are not read (`model.palette` skipped when only they could match).
- **LODs by vertex clustering** are deterministic but coarser than quadric collapse; fine for
  distant levels of simple models, not a substitute for authored LODs of a hero model.
- **Clips are sampled at `fps`** by the exporter (linear between samples, step clips exact).
- **No compression in place.** Draco/Meshopt/KTX2 remain deferred build steps; nothing
  validates a compressed file beyond flagging the decoder it needs.
- **A superseded final is not removed.** Pruning removes stale `<id>.placeholder.glb` files
  once a built `<id>.glb` replaces them; a built `<id>.glb` that a changed spec (without
  Blender) demoted back to a placeholder stays on disk until rebuilt or deleted. The runtime
  manifest lists only the current file.
- **Rendering is not verified here.** The runtime tests parse, build the scene graph and play
  clips with three.js in Node; drawing pixels is the golden runs' and a person's.
- **Reproducibility across machines is by construction, measured on one.** The fixture
  rebuild test is what proves it on a second machine: run it there.
