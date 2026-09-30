# Art direction

**Serves** `art_direction`, `build_spec.visual_identity`, `build_spec.assets`, the asset
manifest, and `core/reference/asset-policy.yaml`.

At this scale a game cannot outspend anyone on art. It can be **coherent**. A small, strict
visual identity applied everywhere reads as intentional. A pile of individually nice assets
reads as an asset flip.

## From `visual_identity` to a style sheet

`design.md` requires a palette with one leading colour, a display face, a shape language, a
motion rule and an avoid list. Turn them into a one-page style sheet that every asset is
checked against:

| Element | Decide | Check |
|---|---|---|
| Palette | 4–6 colours: 1 lead, 1 accent, 2–3 neutrals, 1 danger | Player, hazards, collectibles and UI are distinguishable in greyscale |
| Value structure | Background dark and low-contrast, gameplay objects mid, interactives brightest | Squint test: the next decision stands out |
| Shape language | e.g. rounded = friendly or safe, angular = danger | Hazards and pickups differ in silhouette, not only in colour |
| Line and edge | Outline weight, or none; soft or hard shading | Same across every sprite and UI element |
| Scale | Sprite size relative to the design resolution | Nothing important below about 24 CSS px on the smallest phone |
| Motion | The rule from `visual_identity.motion` | Every tween follows it (`game-feel.md`) |
| Avoid | Concrete exclusions, e.g. "no gradients on UI", "no photo textures" | Reviewed on every asset batch |

## Consistency across sources

A title's assets come from libraries, procedural generation and sometimes AI generation. They
must look like one game:

- **Library packs.** Prefer one pack, or one artist, per title. Where two are mixed,
  normalise palette and outline weight.
- **Procedural.** Generated from the palette tokens, never from hard-coded colours.
- **Generated images:**
  - Write one reusable **style prompt**: palette as hex values, shape language, edge
    treatment, lighting and camera, and the avoid list. Reuse it verbatim for every asset.
    Only the subject changes.
  - Generate from a reference image of an approved asset where the tool allows it, rather
    than from text alone.
  - Keep the background transparent, or trivially keyable. Produce sprites at 2× the display
    size.
  - Review in batches, side by side, on the real game background. Reject any asset that
    breaks the style sheet, however good it looks alone.
- Record `origin`, the tool or source, and the prompt in the manifest line. An asset whose
  origin or licence is unknown can prototype, never ship (`asset-policy.yaml`). Terms of
  generated output differ between tools, and they are recorded, never assumed.

## Readability before beauty

- **Gameplay readability wins every conflict.** If a background detail can be mistaken for a
  hazard, remove it.
- The player's object has the highest contrast on screen, and is recognisable in silhouette.
- Effects never obscure the next decision (`game-feel.md`).
- Check colour-blind safety (`accessibility.md`) at the style-sheet stage, not after
  production.

## Prototype vs production

- **Prototype:** placeholders are fine, but they already follow the palette and the shape
  language. Grey boxes hide readability problems, and coloured placeholders reveal them.
  A placeholder is never production-ready.
- **Production:** replace in batches, and re-run the readability checks after each batch.

## Failure modes

- **Mixed styles.** Three packs, three outline weights.
- **Detail at the wrong scale.** Illustrations drawn for 512 px, shown at 48 px.
- **Unrecorded provenance.** Discovered at release, when replacing the asset is most
  expensive.
