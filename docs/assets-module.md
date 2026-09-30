# Assets module

The `assets` workflow step: a `game-design` in, an `asset-manifest` out, and the files behind
it written into the game repository's `public/assets/`. Code is `scripts/wgf_assets/`; the
rules it applies are `core/reference/asset-policy.yaml`. It implements
[workflow-module-contract.md](workflow-module-contract.md) and changes nothing in the kernel.

```
game-design ─► inspect ─► classify ─► for each asset:
                                        existing file?  ─ validate, license, origin
                                        library?        ─ first licensed, valid candidate
                                        placeholder?    ─ backends in order, procedural last
                                        else missing
                                      ─► optimize (lossless)
            ─► pack atlas groups ─► runtime manifest (public/assets/assets.json)
            ─► prune stale placeholders/atlases ─► asset-manifest
            (every GLB read and checked by gltf.py; a model spec built by Blender)
```

The same pipeline runs outside a workflow as `python3 scripts/wgf-assets.py build`, and the
game repository can be checked against what it wrote with `wgf-assets.py validate` - see
[CLI](#cli). Standard library only; no image tool, no network, no toolchain.

## Inputs

| Input | | Used for |
|---|---|---|
| `game-design` | required | `asset_requirements`, or a derived baseline; `scope.asset_budget` |
| `scaffold-record` | optional | target platforms, whose `max_bundle_mb` the delivered files are checked against |

`game_design.asset_requirements` lists what the design needs: `id`, `kind` (a key of the
policy's `kinds`), and optionally `scope_tier`, intended `source`, `tags` for library search,
`width`/`height`/`frames`, and `existing` — a file already chosen, with its license and
origin. 2D requirements may also say (game-design 1.2.0):

| Field | For | Meaning |
|---|---|---|
| `atlas` | sprite, ui, icon, vfx | a kebab-case group; the group's images are packed into one atlas |
| `scale` | any image | 1-4: pixels are authored at `scale` × the logical `width`/`height` |
| `animations` | spritesheet | `{name: {frames: [index or name], fps, loop}}`; default one looping animation over every frame, named after the asset |
| `tile_width`, `tile_height` | tileset | logical tile size (default 32); the image must divide into it |
| `existing.atlas` | spritesheet | the descriptor of an existing sheet; default `<stem>.atlas.json`, then `<stem>.json` | A design without the list gets a **baseline** derived from its screens, locales,
audio direction and ad placements; every derived item says so in `notes`, because a floor is
not a design.

Kinds: `sprite`, `spritesheet`, `background`, `tileset`, `ui`, `icon`, `vfx`, `font`, `sfx`,
`music` (2D and audio), and `model`, `texture`, `material`, `animation`, `environment` (3D). The game
is 3D when the step's `dimension` says so, else when the design's `engine.dimension` does,
else when a requirement is 3D-only or the art direction says so; audio and fonts take the
game's dimension, UI stays a 2D overlay.

## What each item records

| Field | Meaning |
|---|---|
| `status` | `planned` nothing yet · `sourced` a file, not cleared · `in-progress` a placeholder stands in · `delivered` a valid, cleared final file |
| `files` | path (repository-relative), sniffed format, bytes, `sha256:` of the bytes, image size |
| `license`, `license_status` | the identifier, classified: `generated`, `verified`, `restricted`, `unknown` |
| `origin` | `generated` (with the generator), `library` (with the entry), or `external`; source URL, author, vendor, attribution, evidence |
| `usage_constraints` | from the license's policy entry plus the source's own |
| `placeholder`, `production_ready` | a placeholder is never production-ready; neither is anything with an error |
| `optimization` | lossless steps applied, and the pipeline steps still owed (atlas, KTX2, Draco, transcode, subset); `texture-atlas` moves to `applied` when the item was packed |
| `atlas` | `{id, frame}`: the atlas the item was packed into; its own file (under `src/assets/`) is then the source, not what ships |
| `scale` | the authored resolution, when not 1 |
| `model` | for a GLB: triangles, vertices, dimensions and bounds of the visual model at rest, materials, embedded textures, clips, LOD levels, collision proxy, extensions; for a generated model, the tool, version, pin and key that built it |

The manifest also carries `atlases` (each packed group: its two files and its members) and
`runtime_manifest` (path, bytes and hash of `public/assets/assets.json`).

Everything wrong is in the manifest's `issues`, with a code and a severity. The manifest pins
the policy it was classified under by id, version and hash.

## The license rule

An asset the Factory did not make needs a license **in the policy's permitted list** and an
origin (a source URL, author, vendor or evidence). Otherwise:

- `license-unknown` — missing, or not an identifier the policy knows (`CC0` is not `CC0-1.0`);
- `license-restricted` — NC, ND, GPL and the like;
- `provenance-missing` — a license nobody can check.

Each is an error: the file stays on disk and in the manifest as `sourced`, usable to
prototype, never `delivered` and never `production_ready`. A library candidate with any of
these problems is never picked; the manifest records that it was passed over and why.
Unknown licensing does not silently become production.

## Placeholders

Backends are tried in `placeholders.backends` order; the first that is available, supports
the kind and returns a valid file wins. Every backend's availability and use is recorded under
`generation.backends`.

- **`procedural`** — always available, standard library only, deterministic: coloured PNGs
  (textures checkered and power-of-two), spritesheets with an atlas, shaped synthesised WAVs,
  GLB boxes, environments and animated clips, glTF materials, and a system font stack for
  fonts.

  **Sound effects.** `encoders.synth` is a small jsfxr-style synthesiser: square, saw, sine or
  noise, with an attack/sustain/decay envelope, a pitch slide, vibrato and an arpeggio step,
  rendered mono 22 050 Hz 8-bit.
  - The preset is picked from the words of the item's id, label and tags
    (`placeholders.SFX_RULES`): `ui`, `coin`, `jump`, `hit`, `powerup`, `whoosh` or `lose`,
    else `blip`.
  - It is detuned by the id, so two items never share bytes.
  - Noise comes from a seeded LCG, so output is deterministic and golden package digests
    reproduce.

  **Music.** `encoders.music_loop` is an 8 s square bass plus an eighth-note arpeggio over
  four chords, transposed by the id.

  Both are still placeholders (`placeholder: true`, `LicenseRef-factory-generated`, never
  production-ready). They are shaped so a playtest can tell a reward from a failure
  (`core/craft/audio.md`).
- **`2d-assets-mcp`** — optional. A 2D asset generator run as an MCP server over stdio, used
  for sprites, backgrounds, UI, icons, VFX and textures when configured. Not configured, not on
  PATH, failing to start, erroring or returning a non-image: recorded, and the next backend is
  used. Its output is `license_status: unknown` unless the server's terms are recorded as
  `license`.
- **`blender`** — joins first whenever a requirement carries a buildable `model` spec. Builds
  it headless with the pinned Blender 4.5 LTS, or reuses the file already in the checkout when
  its stamped key matches the spec. With `source` unset or `procedural` the output is **final**
  (`<id>.glb`, `delivered`, not a placeholder); otherwise a better stand-in. Without Blender,
  or with another series, the procedural box stands in and the item carries
  `model-spec-unbuilt`. Settings under `placeholders.blender`
  ([blender-pipeline.md](blender-pipeline.md#configuration)).

Placeholders are named `<id>.placeholder.<ext>`, so a stand-in is never mistaken for art. A
new backend registers with `wgf_assets.placeholders.register_backend(id, factory)` from any
step module, and is named in the config.

## 3D models: GLB validation and the runtime manifest

3D models described as data (`asset_requirements[].model`) are built headless by a pinned
Blender: [blender-pipeline.md](blender-pipeline.md).

Every `.glb`/`.gltf` the step touches — generated, library or the design's own — is read by
`gltf.py` (standard library): structure, references and ranges, node tree, transforms,
embedded images, animations, skins, required extensions against what three.js r170 loads, and
plausible scale. Its findings are the manifest's issues (`model-invalid`,
`model-external-reference`, `model-unsupported-extension`, `model-needs-decoder`,
`model-transform`, `model-scale`, `animation-invalid`). A requirement's `model` spec —
buildable or not — adds expectations: declared clips, LOD levels, collision proxy, fitted
size, pivot and budgets (`animation-missing`, `lod-missing`, `lod-invalid`,
`collision-missing`, `model-pivot`, `model-over-budget`, `texture-too-large`). Policy budgets
are warnings; the spec's own are errors. A stand-in box is not held to a spec it was never
built from.

A GLB's entry in `public/assets/assets.json` carries `model`: its clip names, its LOD nodes,
its collision node and shape, its dimensions and triangles — what a three.js loader looks up
instead of guessing node names.

## Atlas groups

Requirements naming the same `atlas` are packed, after every item is sourced, into
`public/assets/atlases/<group>.png` and `<group>.json` (TexturePacker JSON Hash - PixiJS
`Assets` and Phaser `load.atlas` read it unchanged; `meta.app` is `wgf-assets`). Members'
own PNGs go to `src/assets/<kind dir>/`: in the repository, out of the build (Vite ships
`src/` only through imports), so each pixel ships once. A member's existing file under
`public/` is packed too, with an `atlas-source-served` warning to move it.

Packing is deterministic: frames sorted by height, width, then name; candidate atlas widths
tried in a fixed order, the smallest area kept; edges extruded (policy `atlas.extrude`, 1 px)
against filtering seams and padded (`atlas.padding`, 2 px); power-of-two edges; nothing
run-specific in the descriptor. The same members give the same bytes, whatever order the
design lists them in. PNG only (the packer decodes every PNG colour type and bit depth,
non-interlaced); a WebP or SVG member is refused with `invalid-atlas`. Members of one group
share one `scale`. A group that does not fit `atlas.max_size` (2048) fails every member with
`atlas-overflow`, naming the group: split it.

## The runtime manifest

`public/assets/assets.json` is what game code loads assets through. It is not an artifact -
no provenance, no timestamp - because it ships inside the build and must be byte-identical
for identical assets. Its schema is `core/artifacts/shared/runtime-assets.schema.json`:

```json
{
  "format": "wgf-runtime-assets", "version": 1, "title_id": "tower-merge-rush",
  "assets": {
    "background-main": {"type": "background", "url": "backgrounds/background-main.placeholder.png",
                        "format": "png", "width": 960, "height": 540, "placeholder": true},
    "coin":     {"type": "sprite", "atlas": "hud", "frame": "coin", "width": 32, "height": 32},
    "hero-run": {"type": "spritesheet", "url": "sprites/hero-run.png",
                 "data": "sprites/hero-run.atlas.json", "format": "png", "width": 576,
                 "height": 96, "scale": 2, "frames": ["hero-run-0", "..."],
                 "animations": {"run": {"frames": ["hero-run-0", "..."], "fps": 10, "loop": true}}},
    "grass":    {"type": "tileset", "url": "tilesets/grass.png", "tile_width": 32,
                 "tile_height": 32, "columns": 8, "rows": 4, "...": "..."},
    "font-primary": {"type": "font", "family": "system-ui, ..., sans-serif", "placeholder": true}
  },
  "atlases": {"hud": {"url": "atlases/hud.png", "data": "atlases/hud.json", "width": 256,
                      "height": 64, "scale": 1, "frames": ["button-play", "coin", "star"]}},
  "files": {"atlases/hud.png": {"bytes": 1234, "hash": "sha256:..."}}
}
```

- Keys are asset ids, sorted; ids are the design's, so code never names a file.
- Every `url` and `data` is relative to the manifest itself: `new URL(url, manifestUrl)`, or
  the engine loader's base path set to `assets/`. Nothing is absolute, nothing names the
  machine.
- `width`/`height` are pixels of the file (of the frame, for an atlas member); display size is
  pixels / `scale`.
- `files` holds the size and sha256 of every file referenced, for cache-busting and so a
  check can tell a stale manifest from a current one.
- Items with no loadable file (`planned`, `cut`, failed) are absent. A file outside
  `public/` cannot be served and is reported `not-served`.

How a game consumes it in PixiJS and Phaser, with code: `core/craft/2d-assets.md`. The develop
brief tells the developer to load through it (`runtime_assets` in the brief), and the verify
step checks it (`assets.runtime-manifest`).

## Validation

Every file is sniffed from its bytes. Issues, by code (the manifest's `issues`; `wgf-assets.py
validate` reports the runtime-side codes):

| Code | Severity | When |
|---|---|---|
| `invalid-format` | error | unrecognisable bytes, or content not what the extension says (PNG named `.jpg`) |
| `format-not-allowed` | error | a format the kind does not accept |
| `unsafe-svg` | error | script, `on*` handlers, `javascript:`, `<foreignObject>`, DOCTYPE/ENTITY, `href`/`url()` to another file, `@import` |
| `texture-too-large` | error / warning | an edge over `limits.max_texture_edge` (4096) / `warn_texture_edge` (2048) |
| `transparency-mismatch` | warning / info | cut-out art (sprite, spritesheet, vfx) without alpha / a background carrying an unused alpha channel |
| `dimension-mismatch` | warning | a file not the `width`×`height`×`scale` the design asked for |
| `invalid-atlas` | error | a spritesheet without its descriptor; frames outside the image; animations naming missing frames; `meta.image` not the image's file; an atlas member that is not a PNG; mixed scales in a group |
| `atlas-overflow` | error | a group that does not fit `atlas.max_size` |
| `atlas-source-served` | warning | an atlas member's own file is also under `public/` |
| `invalid-tileset` | error | the image does not divide into its tiles |
| `duplicate-path` | error | two assets claim one file |
| `not-served` | warning | a delivered file outside `public/`, which the runtime manifest cannot list |
| `too-large`, `not-power-of-two`, `duplicate-content`, `license-*`, `provenance-missing`, `missing`, ... | | as before |

Malformed requirements - duplicate id, unknown kind, bad `atlas`/`scale`/`animations`/tile
fields, an animation index past `frames`, a tileset that cannot divide - fail the step before
anything is written.

`runtime.validate(root)` - the CLI's `validate`, and the verify step's
`assets.runtime-manifest` check - reads only the repository: the document against its schema
(duplicate ids caught before JSON would drop one), every `url`/`data` relative, inside
`public/`, present, the recorded size, hash and format, atlas and spritesheet descriptors
against their images, member frames and animation frames present, tilesets dividing, SVGs
safe, texture edges, and `unused-file` for anything under `public/assets/` nobody lists. In
the verify step a stale hash, an unlisted or unused file and a large texture are a WARNING (the
build still loads); every other error FAILs.

## Configuration

`factory.assets` in `workspace/config/factory.yaml`, overridden per step by `with:`:

| Key | Default | |
|---|---|---|
| `root` | the run's game repository checkout | files go under `<root>/public/assets/`; see below |
| `libraries` | `[]` | directories with an `index.json` (see `library.py`) |
| `placeholders` | `{enabled: true, backends: [2d-assets-mcp, procedural]}` | plus a settings block per backend |
| `optimize` | `true` | lossless, only on files the step writes — never on the design's own |
| `runtime_manifest` | `true` | write `public/assets/assets.json` |
| `prune` | `true` | remove `*.placeholder.*` files and `wgf-assets` atlases under `public/assets/` and `src/assets/` that nothing references any more; nothing else is ever removed |
| `dimension` | inferred | `2d` or `3d` |
| `fail_on` | `[]` | issue codes that fail the step |
| `strict` | `false` | fail on any error-severity issue |

### Where the files go

With a scaffold-record in the run and the game repository checked out, the files are written
into the checkout - found as every step finds it ([checkouts.md](checkouts.md)) - under
`public/assets/`. `public/` is one of develop's `writable_paths`, so the development commit
carries them, and the develop brief lists every asset's repository-relative file paths
(`public/assets/...`) for the developer to load. The step holds the checkout's lock while it
writes; another run in it is `BLOCKED`. `root` overrides this (relative to the Factory
root). Without a scaffold-record, or before the checkout exists, the files go to
`.factory/assets/<title>` under the Factory root: git-ignored scratch no build sees.

## Outcomes

| Situation | Result |
|---|---|
| Manifest built | `SUCCESS`, whatever its issues — an honest manifest with issues is the output |
| No `game-design` | `WAITING_FOR_INPUT` |
| Malformed requirements (duplicate id, unknown kind, bad size) | `FAILED`, not retryable |
| `game-design` of a newer major schema | `FAILED`, not retryable |
| An issue in `fail_on`, or any error with `strict` | `FAILED`, not retryable, with the manifest as evidence |

Re-execution is idempotent: files are deterministic and written only when their bytes change,
so a retry, resume or loop reuses everything (`metadata.writes`; `removed` counts pruned
files). Deterministic here means: no timestamps, no absolute paths, sorted keys, fixed frame
and file order, and the same zlib - PNGs are compressed with the interpreter's zlib, so a
different zlib build can compress the same pixels to different bytes. The hashes in the
runtime manifest are of the bytes actually written, so a check is never fooled either way.

## CLI

`scripts/wgf-assets.py`, standard library only. Exit 0 clean, 1 problems (errors; warnings
too with `--strict`), 2 the command could not run. `--json` on every command.

```bash
# Run the pipeline on a design against a checkout: files, atlases, assets.json, prune.
python3 scripts/wgf-assets.py build --design design.json --root ../my-game [--library DIR]
# Check a checkout against its runtime manifest (what the verify step runs).
python3 scripts/wgf-assets.py validate ../my-game [--strict] [--no-unused]
# Pack loose PNGs into one atlas (frame name = file stem), deterministically.
python3 scripts/wgf-assets.py pack out/hud frames/ [--trim] [--animation run=hero-run-]
# What a file really is: format, size, alpha, SVG hazards, atlas problems.
python3 scripts/wgf-assets.py inspect public/assets/ui/*.svg
```

`build` accepts a whole game-design or any JSON with `asset_requirements`. It prints items,
atlases and issues; the `asset-manifest` artifact itself is produced only inside a run,
where it is pinned and validated.

## How agents create and register assets

1. **Declare** it: one entry in `game_design.asset_requirements` - id, kind, logical size,
   `atlas` group for anything drawn together, `animations` for a sheet. Designs are produced
   at `design`; the entry is the registration.
2. **Let the step source it**: the `assets` step (or `wgf-assets.py build`) finds an existing
   file, a licensed library entry, or generates a placeholder, then packs, writes
   `assets.json` and records everything in the asset manifest.
3. **Load it by id** in game code through `public/assets/assets.json`
   (`core/craft/2d-assets.md`). Never a path literal, never an unregistered file.
4. **Replace a placeholder** by putting the final file in the repository and naming it in
   the requirement's `existing` with its license and origin; re-run. The id, and therefore
   the code, does not change; the stale placeholder is pruned.
5. **Check** with `wgf-assets.py validate` before committing; the verify step runs the same
   check.

Generated art from an external generator is a placeholder backend
(`register_backend`, see [Placeholders](#placeholders)) or a library entry - never a file
dropped into `public/` without a requirement: that is exactly what `unused-file` reports.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `atlas-overflow` | The group's frames (with padding and extrusion) exceed 2048². Split the group by scene, or lower member sizes. |
| `invalid-atlas: ... cannot join atlas ... supply a PNG` | Atlas members must be PNG. Re-export, or drop `atlas` for that item. |
| `invalid-atlas: meta.image is 'x.png' but the image is 'y.png'` | A spritesheet's descriptor names another file; loaders follow `meta.image`. Fix the descriptor or name the image to match (library sheets are rewritten automatically). |
| `interlaced (Adam7) PNG; re-save it without interlacing` | Re-export without interlacing; interlaced PNGs are larger and cannot be packed. |
| `hash-mismatch` in `validate` | A file changed after `assets.json` was written. Re-run the assets step / `build`; never edit the manifest. |
| `unused-file` | A file under `public/assets/` no asset references: register it in the design, or delete it. |
| `missing-file` after a checkout | The asset files were not committed with the manifest; commit `public/assets/` and `src/assets/` together. |
| `not-served` | An `existing` file outside `public/`; move it under `public/assets/` (or into an atlas group). |
| A 2x sprite draws twice as big | Display at pixel size / `scale`: Phaser `setScale(1 / scale)`; PixiJS `data: {resolution: scale}` (atlases carry `meta.scale`). |

## Tests

`scripts/tests/test_assets.py`, against `scripts/tests/fixtures/assets/` — 2D and 3D designs,
a library with licensed, restricted and unlicensed entries, a repository checkout with valid
and broken files, and a fake MCP server. `WGF_AJV=1` adds ajv validation of the emitted
manifest and design.

`scripts/tests/test_asset_pipeline_2d.py` — the PNG codec (every colour type, bit depth and
filter), atlas packing (bounds, overlap, pixels, extrusion, trim, order-independence,
overflow), atlas descriptor checks, AVIF and SVG sniffing and hazards, the new requirement
fields, atlas groups and the runtime manifest through the step (schema-valid, byte-identical
across roots and input orders, idempotent, pruning), every runtime validation failure, the
CLI's commands and exit codes, and the develop brief and verify check that consume it.

`scripts/tests/test_models.py` covers the model spec, the GLB inspector, the Blender layer
(with a fake Blender through the real process layer), the step with models, three.js loading,
and — with `WGF_BLENDER_TEST=1` — real Blender builds.
