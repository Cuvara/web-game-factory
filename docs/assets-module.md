# Assets module

The `assets` workflow step: a `game-design` in, an `asset-manifest` out, and the files behind
it written into the game repository's `public/assets/`. Code is `scripts/wgf_assets/`; the
rules it applies are `core/reference/asset-policy.yaml`. It implements
[workflow-module-contract.md](workflow-module-contract.md) and changes nothing in the kernel.

```
game-design ─► build_spec.assets ─► classify ─► for each asset:
  (palette)     (requirements.py)                existing file?   ─ validate, license, origin
                                                 library?         ─ library.json by id/role,
                                                                    then index.json search
                                                 author? (2D)     ─ an SVG per drawing,
                                                                    judged, repaired ≤ 2×
                                                 model author? (3D, when installed)
                                                 placeholder?     ─ backends in order
                                                 else missing
                                               ─► optimize (lossless) ─► quality (quality.py)
            ─► pack atlas groups ─► runtime manifest (public/assets/assets.json)
            ─► prune stale placeholders/atlases ─► asset-manifest
            (every GLB read and checked by gltf.py; a model spec built by Blender)
```

The failure this shape prevents: a run whose game shipped nothing but hash-coloured
rectangles while every check passed. The work list is what the design asked for, every
stand-in says `placeholder: true`, and every delivered file carries a `quality` verdict the
production gate (`production-quality`) reads - see
[production-architecture.md](production-architecture.md).

The same pipeline runs outside a workflow as `python3 scripts/wgf-assets.py build`, and the
game repository can be checked against what it wrote with `wgf-assets.py validate` - see
[CLI](#cli). Standard library only; no image tool, no network, no toolchain.

## Inputs

| Input | | Used for |
|---|---|---|
| `game-design` | required | `build_spec.assets` (and `asset_requirements`), or a derived baseline; `build_spec.visual_identity` (palette, `primitive_style`); `scope.asset_budget` |
| `scaffold-record` | optional | target platforms, whose `max_bundle_mb` the delivered files are checked against |
| `production-quality-report` | optional | on re-entry: the failed checks with route `assets` name the items to rebuild ([Re-entry](#re-entry)) |
| `visual-qa-report` | optional | on re-entry: the findings with route `assets` name the items to rebuild |

The two reports are read when present; wiring them into `new-game` (the `production-quality`
and `visual-qa` routes back to `assets`) is the workflow's, not this module's.

### The work list: build_spec.assets

A game-design 1.6.0 lists its asset **requirements** in `build_spec.assets`, and that list is
the work list (`requirements.bridge`). Each entry carries onto its requirement:

| build_spec field | Requirement | |
|---|---|---|
| `id` | `id` | the manifest item id and the runtime asset id |
| `type` + `role` + dimension | `kind` | 2D: `sprite`; `texture` or role `background`/`environment` → `background`; `ui`, `icon`, `vfx`, `font` as named; a `spritesheet` or `animation` → `sprite` (one vector drawing, animated in code; the frames stay in the notes). 3D: `model` (role `environment` → `environment`), `texture`, `animation` |
| `dimension` | `dimension` | as stated, else `model` → 3d, else the engine's (`engine.dimension`, `threejs` → 3d); a flat kind (sprite, ui, icon, background) is 2D in any game |
| `tier` | `scope_tier` | `mvp` → mvp, produced now; `post-mvp` → production and `optional` → future, recorded, not produced |
| `role`, `description`, `readability`, `spec` | the same | what the author is asked for and the production gate judges |
| `count` | `count` | > 1: one drawing per `<id>-<n>`, each its own runtime asset ([variants](#the-runtime-manifest)) |
| `spec` sizes | `width`/`height` | `96x96` or `960x540` sets both; `64px` sets a square for sprite, icon, ui, vfx |

An `asset_requirements` entry with the same id adds what only it can say (atlas group, exact
size, scale, a `model` spec, `existing`); one build_spec does not name is kept as well. A
design with `asset_requirements` and no `build_spec.assets` is read as before.
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
| `existing.atlas` | spritesheet | the descriptor of an existing sheet; default `<stem>.atlas.json`, then `<stem>.json` |

A design that lists **no assets at all** (neither list) gets a **baseline** derived from its
screens, locales, audio direction and ad placements; every derived item says so in `notes`,
because a floor is not a design - and every one is a placeholder: no library or author is
asked for an asset nobody designed.

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
| `role`, `dimension` | from the requirement |
| `quality` | `{verdict: pass, fail or skipped, checks: [{id, status, summary}], primitive_only, parts, triangles, colors, author}` ([Quality](#quality)); `author` is `library:<entry>`, `author:<kind>`, `builtin:<generator>`, `existing` or `placeholder` |
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

## Sources: library, author, model author

Tried in this order for every requirement that is not a derived baseline item; the first that
delivers wins, and what each passed over is in the item's issues.

**Library** (`factory.assets.libraries`). A library directory holds a `library.json` that maps
requirements to files, an `index.json` searched by kind and tags, or both (`library.py`):

```json
{"library": {"id": "tower-merge-art"},
 "items": [
   {"requirement": "tile", "files": ["svg/tile-1.svg", "svg/tile-2.svg"],
    "license": "CC0-1.0", "source": "https://...", "author": "..."},
   {"role": "background", "files": ["svg/board.svg"],
    "license": "LicenseRef-studio-owned", "source": "studio pack 3, receipt 1182",
    "author": "..."}]}
```

A requirement-id entry wins over a role entry. The licence (`license` or `licence`) must be
in the policy's permitted list and the entry must say where it came from (`source`: a URL
becomes `origin.source_url`, anything else `origin.evidence`; or `author`/`vendor`), else it
is passed over (`library-candidate-rejected`). Imported items are `source: library`,
`placeholder: false`, and are judged like anything else. Fewer files than the requirement's
`count` is `variants-short`. This is how golden fixtures and purchased packs supply real art.

**Author** (`factory.assets.author`, 2D). `kind: command` runs an agent host once per drawing
(`author.py`, through `wgflib.procs`, with the agent environment of `wgflib.agentenv` plus
`factory.agents.env_passthrough`), exactly like the design step's agent author. argv
placeholders: `{request}`, `{output}`, `{prompt}`. The request JSON carries the requirement
(`id`, `variant`, `count`, `type`, `kind`, `role`, `dimension`, `tier`, `description`,
`readability`, `spec`, `width`, `height`, `transparency`), the design's `palette` and
`visual_identity` (concept, shape language, texture, avoid, primitive_style), the
`quality_bars` it is held to, and its repository `destination`. The host writes one SVG at
`{output}`; the step validates it (format, unsafe constructs) and judges it
([Quality](#quality)). A file that fails is shown to the host with exactly those problems -
`repair: {round, problems, previous}` - and asked again, `repair_rounds` times (default 2);
one that still fails is not delivered (`author-rejected`) and the requirement falls back to a
placeholder that says so. A host that crashes or times out is the same fallback. Accepted
files are `source: ai-generated`, licence `LicenseRef-factory-generated`, `origin.generator`
and `quality.author` `author:command`, `placeholder: false`.

Only kinds the policy lets be SVG are authored: `sprite`, `ui`, `icon`, `background`, `vfx`
(asset-policy 1.3.0), never an atlas member (atlases pack PNG) or a spritesheet.

What the author wrote is recorded in `src/assets/authored.json` (path → request key, file
hash, author): a re-executed step reuses a file whose request is unchanged - same description,
readability, role, spec, palette, bars and author - instead of asking again. Changing any of
them asks again.

**Model author** (3D). When `wgf_assets.model_author` is installed, a 3D `model`,
`environment` or `animation` requirement is passed to its `produce_model(requirement,
visual_identity, out_dir, settings, context)`, which returns `{files, quality, source,
license, placeholder, notes}` or raises `ModelAuthorError`. Its files are validated as any
GLB (`gltf.py`) and its `quality` is recorded as given. Absent, or failing, 3D requirements
fall back to placeholders. See [blender-pipeline.md](blender-pipeline.md).

## Quality

`quality.py` judges every delivered SVG and PNG against `core/reference/asset-quality.yaml`
and records the result as the item's `quality`. A placeholder is never judged (`skipped`,
author `placeholder`); a GLB, audio or font has no 2D check (`skipped`). A `fail` verdict is a
`quality-failed` issue (an error for mvp and prototype items) and the item is never
`production_ready`.

| Check | Fails when |
|---|---|
| `svg.well-formed` | larger than `svg.max_bytes`; a DOCTYPE or ENTITY (refused before parsing - nothing is expanded or fetched); not well-formed XML; the root is not `<svg>`; no usable `viewBox` |
| `svg.safe` | `<script>`, an `on*` handler, `<foreignObject>`, an embedded raster (`<image>`), a `javascript:` URL, an href or `url()` to anything but a fragment, a stylesheet `@import` |
| `svg.not-primitive` | the drawing elements outside `<defs>`/`<clipPath>`/`<mask>`/... are fewer than `min_shapes` for the role, or the whole drawing is one plain rect, circle or ellipse (`primitive_only: true`). With `visual_identity.primitive_style`, primitives pass |
| `svg.palette` | more than `max_off_palette_share` of the distinct colours (fill, stroke, stop-color, inline style) are farther than `tolerance` (RGB distance) from every palette colour - greys count as on-palette when `neutrals` - unless the root says why: `data-wgf-off-palette="<reason>"` |
| `svg.dimensions` | the declared size (width/height, else viewBox) exceeds `max_edge`, or its aspect differs from the spec's by more than `aspect_tolerance` |
| `raster.decodes` | not a PNG `wgf_assets.raster` can read |
| `raster.not-flat` | fewer than `min_distinct_colors` distinct opaque colours: one flat colour |
| `raster.alpha` | a kind with `transparency: required` (sprite, vfx) has no alpha channel |

`parts` is the number of drawing elements, `colors` the distinct colours used. The bars are a
floor against stand-ins, not a judgement of the art: that is visual QA.

## Re-entry

When the step runs again with a `production-quality-report` or `visual-qa-report` whose
`routes` include `assets`, it rebuilds only what those reports name: a production-quality
check that did not pass with `route: assets` names its `assets` (else the requirement ids its
summary mentions); a visual-qa finding with `route: assets` names the ids its id or summary
mentions. A drawing id (`tile-2`) names its requirement. Each named item skips the library
(it would hand over the same file) and goes to the author with the findings as `notes`; every
other item is reused - a library file is deterministic, an authored file comes from the
ledger, a placeholder from the same bytes. Without an author, a named item is rebuilt from
the same sources and the manifest says so in its `notes`.

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
| `libraries` | `[]` | directories with a `library.json` and/or an `index.json` (see `library.py`); relative to the project directory |
| `model_author` | `{kind: none}` | the 3D model author (`model_author.py`): `{kind: command, argv, spec_from: file\|stdout, repair_rounds: 2}`; only a configured one is asked |
| `author` | `{kind: none}` | `{kind: command, argv, timeout_seconds: 600, idle_timeout_seconds: 300, repair_rounds: 2}`; a misconfigured author fails the step, not retryably |
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
| `author.kind` unknown, or `command` without an `argv` | `FAILED`, not retryable |
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
# The same with the 2D author: a command, last on the line, its argv with placeholders.
python3 scripts/wgf-assets.py build --design design.json --root ../my-game \
    --author-command my-agent-host --request {request} --output {output}
# Check a checkout against its runtime manifest (what the verify step runs).
python3 scripts/wgf-assets.py validate ../my-game [--strict] [--no-unused]
# Pack loose PNGs into one atlas (frame name = file stem), deterministically.
python3 scripts/wgf-assets.py pack out/hud frames/ [--trim] [--animation run=hero-run-]
# What a file really is: format, size, alpha, SVG hazards, atlas problems.
python3 scripts/wgf-assets.py inspect public/assets/ui/*.svg
```

`build` accepts a whole game-design or any JSON with `asset_requirements`. It prints items
(status, quality verdict, files), atlases and issues; the `asset-manifest` artifact itself is produced only inside a run,
where it is pinned and validated.

## How agents create and register assets

1. **Declare** it: one entry in `build_spec.assets` - id, type, tier, role, description,
   readability, count, spec - and, when it needs more, an `asset_requirements` entry of the
   same id (logical size, `atlas` group, `animations`, `existing`). Designs are produced at
   `design`; the entry is the registration.
2. **Let the step source it**: the `assets` step (or `wgf-assets.py build`) finds an existing
   file, a licensed library file, an authored SVG, or generates a placeholder, judges it,
   then packs, writes `assets.json` and records everything in the asset manifest.
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

`scripts/tests/test_assets_production.py` — the build_spec bridge (roles, dimensions,
counts, tiers, sizes, the baseline always placeholder), the command author through the real
process layer with `fixtures/assets/fake_svg_author.py` (a multi-shape SVG passes; a one-rect
SVG is repaired on round 2; one that never passes, a script, an off-palette drawing and a
crashing host fall back to placeholders; the ledger reuses), zero placeholders among the mvp
items with an author and flagged placeholders without one, library.json by id and by role
(`fixtures/assets/library-mapped/`), re-entry from both reports, the 3D model author hook,
and every quality check.

`scripts/tests/test_models.py` covers the model spec, the GLB inspector, the Blender layer
(with a fake Blender through the real process layer), the step with models, three.js loading,
and — with `WGF_BLENDER_TEST=1` — real Blender builds.
