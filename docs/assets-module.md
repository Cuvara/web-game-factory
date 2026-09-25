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
                                      ─► optimize (lossless) ─► asset-manifest
```

## Inputs

| Input | | Used for |
|---|---|---|
| `game-design` | required | `asset_requirements`, or a derived baseline; `scope.asset_budget` |
| `scaffold-record` | optional | target platforms, whose `max_bundle_mb` the delivered files are checked against |

`game_design.asset_requirements` lists what the design needs: `id`, `kind` (a key of the
policy's `kinds`), and optionally `scope_tier`, intended `source`, `tags` for library search,
`width`/`height`/`frames`, and `existing` — a file already chosen, with its license and
origin. A design without the list gets a **baseline** derived from its screens, locales,
audio direction and ad placements; every derived item says so in `notes`, because a floor is
not a design.

Kinds: `sprite`, `spritesheet`, `background`, `ui`, `icon`, `vfx`, `font`, `sfx`, `music`
(2D and audio), and `model`, `texture`, `material`, `animation`, `environment` (3D). The game
is 3D when a requirement is 3D-only or the art direction says so; audio and fonts take the
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
| `optimization` | lossless steps applied, and the pipeline steps still owed (atlas, KTX2, Draco, transcode, subset) |

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

Placeholders are named `<id>.placeholder.<ext>`, so a stand-in is never mistaken for art. A
new backend registers with `wgf_assets.placeholders.register_backend(id, factory)` from any
step module, and is named in the config.

## Configuration

`factory.assets` in `workspace/config/factory.yaml`, overridden per step by `with:`:

| Key | Default | |
|---|---|---|
| `root` | `.factory/assets/<title>` | the game repository checkout |
| `libraries` | `[]` | directories with an `index.json` (see `library.py`) |
| `placeholders` | `{enabled: true, backends: [2d-assets-mcp, procedural]}` | plus a settings block per backend |
| `optimize` | `true` | lossless, only on files the step writes — never on the design's own |
| `dimension` | inferred | `2d` or `3d` |
| `fail_on` | `[]` | issue codes that fail the step |
| `strict` | `false` | fail on any error-severity issue |

## Outcomes

| Situation | Result |
|---|---|
| Manifest built | `SUCCESS`, whatever its issues — an honest manifest with issues is the output |
| No `game-design` | `WAITING_FOR_INPUT` |
| Malformed requirements (duplicate id, unknown kind, bad size) | `FAILED`, not retryable |
| `game-design` of a newer major schema | `FAILED`, not retryable |
| An issue in `fail_on`, or any error with `strict` | `FAILED`, not retryable, with the manifest as evidence |

Re-execution is idempotent: files are deterministic and written only when their bytes change,
so a retry, resume or loop reuses everything (`metadata.writes`).

## Tests

`scripts/tests/test_assets.py`, against `scripts/tests/fixtures/assets/` — 2D and 3D designs,
a library with licensed, restricted and unlicensed entries, a repository checkout with valid
and broken files, and a fake MCP server. `WGF_AJV=1` adds ajv validation of the emitted
manifest and design.
