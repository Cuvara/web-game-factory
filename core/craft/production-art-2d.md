# 2D production art

**Serves** `build_spec.assets[]` (`role`, `count`, `readability`, `spec`),
`build_spec.visual_identity` (`palette`, `shape_language`, `texture`, `avoid`), the asset
manifest, the runtime asset manifest, and the assets step's author and library sources
(`docs/assets-module.md`). Judged by `core/reference/asset-quality.yaml` (per file) and by
the production gate and visual QA (on screen).

`production-art-and-ui.md` says what a finished 2D game looks like. This playbook says how
the reference 2D port (a merge game drawn as a two-ink risograph print) got there, as rules a
new game can follow with its own look. The numbers are the reference's; keep the ratios when
the look changes.

## 1. Pick a style kit, not a pile of sprites

A style kit is a small set of treatments every drawing gets, so library, authored and
generated art read as one game. The reference kit, "riso-arcade":

| Treatment | Rule | Reference value |
|---|---|---|
| Ground | One warm, light paper colour behind everything | `#F4EDE1` |
| Ink | One near-black for outlines, shadows and the hard drop shadow | `#1C1A17` |
| Outline | Every shape stroked in ink, round joins and caps | 5 px at the 2x viewBox (2.5 px displayed) |
| Two inks | Two saturated colours carry everything else | pink `#FF48B0`, blue `#0078BF` |
| Overlap | Where the two inks would overprint, a third, derived colour | purple `#6C3C9E` |
| Misregistration | The second ink drawn again, offset, under the outlined fill | dx 4, dy 3, opacity 0.9 |
| Halftone | A dot pattern over the shadow side of a shape | dots 6 px apart, r 1.4, opacity 0.55 |
| Accent | One reserved colour with one meaning | red `#E3350D`: danger and chimneys only |
| Stated exception | One off-palette colour, declared on the file | sunflower `#FFD23F` for light, `data-wgf-off-palette="lamp and window light"` |

Rules behind it:

- **Four to six tokens, each with a role** (`visual_identity.palette[].role`). Tints are fine
  within the asset bar's palette tolerance (RGB distance 60 of a token, `svg.palette`); the
  reference used `#E4D9C6`, `#FF7AC6`, `#2E92D2`.
- **An off-palette colour is a decision, written on the file.** The root `<svg>` carries
  `data-wgf-off-palette="<reason, 12+ chars>"`; otherwise more than a third of distinct
  colours off-palette fails `svg.palette`.
- **One treatment set, applied everywhere.** The same outline width, the same offset, the
  same halftone - on pieces, frame, panels, icons, the wordmark and even the CSS (hard offset
  `box-shadow`s, a misregistered `text-shadow`). Consistency is what makes cheap shapes
  read as a product.
- **Choose the kit from the design's `shape_language` and `texture`.** Flat vector with a
  2-3 px dark outline, chunky pixel art, paper cut-out, neon line art - each needs the same
  table filled in before the first file is drawn.

**The kit follows the style family** (`visual_identity.style_family`,
`core/reference/art-style-families.yaml`; the 3D side is `production-art-3d.md` section 2a).
The reference above is one toon/print kit; the family decides what carries a shape:

| Family | Ground | What a shape reads by | Glow | Shadow |
|---|---|---|---|---|
| Neon / emissive | near-black | a bright stroke with an outer glow on a dark fill | the point of the look - but only the player, pickups and threats, at most one glowing element per screen outside play | none; light comes from the strokes |
| Lit stylized (paper, diorama, clay) | a lit backdrop, light to mid value | coloured fills shaded by one light direction, a short hard shadow down-right | none, except a real light (a lamp, a window) | one direction for every drawing |
| Toon / flat / print | a quiet flat colour | a thick ink outline and flat colour blocks, two or three value bands | none | a hard offset or halftone, never soft blur |

Mixing them is the failure the consistency score catches: a glowing sprite in a paper world,
a soft-shadowed cut-out next to flat toon pieces.

## 2. Silhouette first, one silhouette per variant

The single biggest defect in the reference's first pass: "level 2 and level 3 look alike".
A counted requirement (`count > 1`: levels, enemy types, pickups) is a **family of
silhouettes**, never one square with a number on it.

- **Each variant changes its outline, not only its colour or numeral.** Fill every drawing
  black: you must still tell all variants apart.
- **Order reads as growth.** For a progression, each step is taller, wider, or adds a
  feature, so the level reads before the numeral. The reference's 8 tower levels, each in a
  96x96 cell drawn at 2x (viewBox `0 0 192 192`, `data-level` on the root):

  | Level | Object | What makes the silhouette | Top of drawing (y of 192) |
  |---|---|---|---|
  | 1 | Shed | squat block, slab roof | 122 |
  | 2 | Cottage | gable, chimney, two windows | 88 |
  | 3 | Watchtower | tapered body, crenellations, pennant | 36 |
  | 4 | Water tower | tank on four braced legs, cone, ladder | ~30 |
  | 5 | Lighthouse | striped column, lit lantern, light rays | ~24 |
  | 6 | Clock tower | shaft, round clock face, belfry, spire | 10 |
  | 7 | Skyscraper | three setbacks, window grid, antenna | 8 |
  | 8 | Crown pagoda | three roofed tiers, star, ray halo | ~6 |

- **Colour alternates as well**, so neighbours differ in two channels (pink, blue, purple,
  red, paper bodies in turn).
- **Ship as many drawings as the rules can reach.** If levels go to 8, `count` is 8 - a
  design with `count: 6` truncates the art. Past the last drawing, reuse it with an added
  mark (the reference crowns it with one burst star per extra level), never a blank.
- **A numeral or badge is a second channel, not the first.** The reference's badge: a paper
  circle with an ink stroke, radius `max(11, cell*0.19)`, offset ink circle +2 px behind,
  numeral at `r*1.15` in the display face.

## 3. Draw in layers, in a fixed order

Every shape in the kit is built the same way, back to front:

1. **Ground shadow**: a halftone ellipse at the base (y 184 of 192, ry 6) and a 4 px ink
   baseline - objects stand on something.
2. **Misregistered second ink**: the body silhouette in the second ink, offset (4, 3).
3. **Body**: the fill, stroked in ink.
4. **Shade**: halftone over the right-hand (shadow) side.
5. **Details**: doors, windows, trims - small shapes in paper or the accent, also stroked.

At least 3 shapes per drawing is the asset bar's floor (`svg.min_shapes`: 4 for backgrounds
and environments, 2 for ui, icon and vfx); a recognisable object takes 6-20.

A minimal piece in this method (illustrative):

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 192 192" width="96" height="96" data-level="2">
  <defs><pattern id="dots" width="6" height="6" patternUnits="userSpaceOnUse">
    <circle cx="3" cy="3" r="1.4" fill="#1C1A17"/></pattern></defs>
  <ellipse cx="96" cy="184" rx="60" ry="6" fill="url(#dots)"/>
  <path d="M44 184V112L96 88L148 112V184Z" fill="#FF48B0" transform="translate(4 3)" opacity=".9"/>
  <path d="M44 184V112L96 88L148 112V184Z" fill="#0078BF" stroke="#1C1A17" stroke-width="5" stroke-linejoin="round"/>
  <path d="M96 88L148 112V184H96Z" fill="url(#dots)" opacity=".55"/>
  <rect x="80" y="140" width="32" height="44" fill="#F4EDE1" stroke="#1C1A17" stroke-width="5"/>
</svg>
```

Author with a **deterministic generator**, not by hand per file: one script that defines the
palette, the primitives (`path` with the ink stroke, `misreg`, `shade`, `ground`,
`halftone(step, r)`) and one function per drawing, seeded where it scatters anything
(the reference backdrop uses a fixed seed). Same input, same bytes - so a re-run is a no-op
and a change is a reviewable diff.

## 4. Sizes and anchors

- **Draw at 2x the displayed size** (96 px cell -> 192 viewBox) and let the loader rasterise
  SVG at `clamp(ceil(devicePixelRatio), 2, 3)`; rasterise a full-screen backdrop at 1.
- **Anchor where the object touches the world.** Standing things: anchor (0.5, 1),
  bottom-centre, so a taller variant grows upwards from the same slot. Centred things
  (bursts, pickups): (0.5, 0.5).
- **Size from the layout, keep the aspect.** Set the height from the layout
  (`sprite = cell*1.7` landscape, `cell*2.15` portrait in the reference) and derive width
  from the texture's aspect. Never stretch.
- **Frames and panels are 9-slice.** Declare the slice on the file (`data-slice="40"` on a
  144x144 frame, `"32"` on a 96x96 card) and scale the slice down
  (`k = min(1, height*0.9/(slice*2), cell/60)`) so corners never overlap on a phone.

## 5. Backgrounds and environment

- **Quieter than the play layer.** Lower contrast and saturation than anything interactive:
  the reference backdrop puts its far skyline at opacity 0.4, near skyline 0.32, a misprint
  copy at 0.22, grain at 10 %. The squint test must still find the pieces first.
- **Fill any screen.** 1920x1080 with `preserveAspectRatio="xMidYMax slice"`, anchored
  bottom-centre and scaled to cover (`max(w/texW, h/texH)`); the interesting band sits where
  every crop keeps it.
- **Tell a place, cheaply.** A big simple shape (a halftone sun r 240), a few layered
  silhouettes (two skylines), scattered light (90 lit windows) and a ground band. Four or
  more shapes is the bar; ten distinct elements read as a world.
- **The play surface is environment, not background.** A frame or track carries the kit's
  full treatment (offset shadow +6, stroked border, halftone corners at 0.35, coloured
  rules) because it frames the decisions.

## 6. VFX sprites

Effects are drawn assets too, in the kit, not engine circles:

- **Burst** (merge, hit): 160x160, a 24-point star (outer r 76, inner 38) in the lead ink
  with the second ink misprinted at (4, 4), a 16-point light core (r 40/20), a paper centre,
  a few loose dots.
- **Streak** (motion, chain): 256x64, a lens shape with a highlight, speed lines, a head dot
  at the leading end - rotate it to the direction of travel.
- **Confetti**: small copies of the burst texture, tinted from the palette - no new file.
- Two shapes is the bar for vfx; give it the outline and offset like everything else.

## 7. UI art and the wordmark

- **Panel / card**: a 9-slice in the kit (ink shadow +8, second ink +2, paper with a 4 px
  stroke, halftone corner, two coloured rules) used as the result and pause card's border.
- **Icons**: one set, one size (48x48), one stroke (ink 5, round), at least 3 marks each so
  they pass under any role. The reference order: play, pause, retry, menu, sound, ad.
- **Wordmark**: the title set in the display face, converted to outlines (so it needs no
  font at runtime), with the kit's offset copy (6, 5), a 12 px ink stroke under the fill,
  on a banner with a hard shadow (8, 8). 720x260 in the reference.
- Fonts themselves are covered by `game-ui-kit.md`.

## 8. Registering the art

Two routes into the assets step; both are judged exactly as anything else
(`docs/assets-module.md`).

- **A library** (`factory.assets.libraries`): a directory with `library.json` and the
  files. Map by requirement id (wins) or by role; every item carries `license` (a permitted
  one: CC0-1.0 for drawn SVGs, OFL-1.1 for fonts), `source`, `author`. A counted
  requirement lists exactly `count` files, in variant order.

  ```json
  {"library": {"id": "my-game-art"},
   "items": [
     {"requirement": "pieces", "files": ["svg/piece-1.svg", "svg/piece-2.svg"],
      "license": "CC0-1.0", "source": "tools/make_art.py", "author": "studio"},
     {"requirement": "backdrop", "files": ["svg/backdrop.svg"],
      "license": "CC0-1.0", "source": "tools/make_art.py", "author": "studio"}]}
  ```

- **The author** (`factory.assets.author`): the step asks an agent for one SVG per drawing,
  with a request carrying the requirement, palette, visual identity, quality bars and this
  playbook (`craft`). Answer it with one self-contained SVG: a viewBox, the kit's layers, no
  scripts, images or external references.

Role mapping the reference used: pieces `target`, track frame `environment`, backdrop
`background`, merge VFX `vfx`, panel and wordmark `ui`, icons `icon`, fonts `font`. A
counted requirement becomes runtime ids `<id>-1..N` (see `production-wiring.md`).

Before delivering: `python3 scripts/wgf-assets.py validate <checkout> --strict`, then look
at the drawings side by side at play size - every variant distinct in silhouette, nothing
mistakable for a threat that is not one.

## Failure modes

- **Numbered squares.** A family that differs only in label or hue.
- **Mixed treatments.** An outlined set beside an un-outlined icon, a flat backdrop beside
  halftoned pieces - the eye reads two games.
- **A loud background.** Saturation or contrast that competes with pieces (the squint test).
- **Off-palette drift** without a stated reason on the file.
- **Too few drawings.** `count` below the levels the rules reach.
- **Text on the art in a system font**, or a wordmark that needs a font at runtime.

## Distilled from

The template's reference 2D port, `examples/tower-merge-rush/wgf-golden/` in the template
repository: `library/tools/make_art.py` (palette, primitives, layer order, the 8 pieces,
frame, backdrop, VFX, panel, icons, wordmark, font subsetting), `library/library.json`
(roles and licences), `src/rendering/pixijs/art.ts` (raster resolution, slice),
`src/rendering/pixijs/tower-view.ts` (anchors, sizes, badge, extra-level crowns); frames
`baseline/` (title, merge, mobile, game over); the defects "level 2 and 3 look alike" and
"white text on cream" from the 2026-10-01 quality monitor.
