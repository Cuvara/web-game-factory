# Production art and UI

**Serves** `build_spec.assets[].role`, `.dimension`, `.readability`,
`build_spec.visual_identity.ui`, `.primitive_style`, `.typography`, the play probe's
`entities[].asset`, `.render` and `assets_loaded`, and `core/reference/experience-rules.yaml`
(`production_art`, `ui`).

A prototype proves the loop. A finished web game is the same loop that a stranger takes for a
product: they can tell at a glance what they are, what threatens them and what they aim at,
the buttons look like this game's buttons, the type is the game's type, and losing ends on a
screen that makes playing again the easiest thing to do. None of that is polish added at the
end. It is stated at design time, as data a check can read, and built in the production phase
on top of a greybox that already plays.

This file is the bar. How the reference ports reached it, with their numbers:
`production-art-2d.md` and `production-art-3d.md` (the art), `game-ui-kit.md` (fonts,
buttons, HUD, screens), `juice.md` (feedback timings) and `production-wiring.md` (loading,
the probe, the regression guard, checking yourself before reporting).

## What separates a finished game from a prototype

| | Prototype (greybox) | Finished |
|---|---|---|
| The player, threats, targets | Cubes, spheres, flat rectangles | A drawn character, a recognisable threat, a target that reads as one |
| Silhouette | Whatever the primitive is | Distinct per role: you can tell threat from pickup in black and white |
| Colour | Debug colours | The palette's roles: one lead accent for the player, a warning colour for threats, quiet neutrals for the world |
| Lighting (3D) | Default ambient, everything the same value | A key light, a fill, a rim on the player; shadows that ground objects |
| UI | Browser-default buttons, system font | Buttons and panels drawn in the identity, bundled faces, a type scale |
| End of play | `alert`, a reload, or nothing | A result screen with the outcome, the best, and Retry as the primary button |

## Readability at play size

Every MVP asset of an entity role (player, threat, goal, target, projectile, collectible,
hazard) carries a `readability` line: what a first-time player must recognise in it, and at
what size or distance. Write it as a test, not a mood:

- "A runner in the lead accent, facing up the track, readable at 64 px tall in the lower
  third" - a size, a position, a colour role.
- Not "a cool character" - nothing to judge.

Rules behind good lines:

- **Silhouette first.** Fill the shape with one flat colour: it must still say what it is. A
  threat is angular where a pickup is round; the player differs from both.
- **Value before hue.** The squint test: the thing the next decision depends on is the
  highest-contrast thing on screen. Background lowest, world middle, interactives highest.
- **Size from the camera.** Readable roles cover at least the visual gate's share of the
  viewport (`core/reference/visual-quality.yaml`). Design for the smallest phone in portrait.
- **Never colour alone.** A level, a team or a state differs in shape or numeral as well.
- **A projectile is seen travelling.** Big enough and contrasted enough to be followed for
  every frame of its flight; a trail if it is fast.

## Palette discipline

The identity kit names 4-6 tokens with roles. Keep to them:

- The lead accent marks the player and the primary button - nothing else competes with it.
- The warning/danger token means danger. Never decorative.
- Text and button labels sit on their fill at 4.5:1 or better (`ui.min_contrast`).
- UI tokens (`visual_identity.ui.button.fill`, `.text`, `.surface`) are palette tokens, so
  every screen uses the same colours the world does.

## Lighting for 3D

- One key light with soft shadows grounding the player and threats; a fill so the shadow side
  is not black; a rim or emissive accent on the player so it separates from the background.
- Flat-shaded low-poly is a style; unlit grey geometry is not.
- Fog or a gradient sky sets depth and keeps far geometry quieter than near.
- Characters are models (`type: model`, `dimension: 3d`) with parts that read from the play
  camera: a vehicle has a nose, a keeper has gloves. A capsule standing for a person is a
  placeholder.

## UI hierarchy and typography

- **One primary action per screen**, the largest and brightest target, in the thumb zone of
  the lower third on a phone. Secondary actions smaller, never competing.
- **Targets** at least `ui.min_target_px` (44 CSS px minimum; the kits use 48), none
  overlapping another or the HUD.
- **Type scale** from `visual_identity.ui.font_px`: body and HUD at least `ui.min_font_px`,
  headings clearly larger. Numerals tabular so a rolling score does not jitter.
- **Fonts are production assets.** The typography's faces ship as files with the game (an MVP
  asset of role `font`, its source and licence in the spec - the kits use SIL OFL faces from
  the Google Fonts repository), loaded with `@font-face` through the runtime asset manifest
  and awaited (`document.fonts.load`) before the first UI frame. The computed `font-family`
  of every button and HUD element resolves to the bundled face; a system fallback on screen
  is a defect, the same as a missing sprite.
- **Buttons** are drawn: the identity's fill, text, radius and style, with idle, pressed and
  disabled states. A browser-default button is the clearest sign of an unfinished game.

## Result screens and the retry flow

- Losing (and winning) ends on a result screen in play's context: the outcome in words, the
  score against the best (a new best celebrated), and **Retry** as the primary button.
- Retry returns to play within the experience contract's `retry_s` - no title screen, no
  reload, no ad in front of it unless the design's placement says so.
- Menu is small and secondary; Continue (a rewarded offer) sits above Retry only when the
  design names it.

## Mobile layout

- HUD inside the safe area; nothing interactive within 16 CSS px of an edge.
- Portrait first for one-thumb games; the same screens re-flow on desktop, never crop.
- Test at 360x640 and at desktop width: every target, every label, every result screen.

## Greybox to production: the replacement rule

The greybox draws every entity as a primitive and reports `render: "primitive"`,
`asset: null`. It gives each entity the **role** the design's asset requirements name, so the
production build replaces the primitive standing for each role with the asset of that role -
same entity, same role, same probe id - and reports `render: "asset"` (or `"composite"`) with
`asset` set to the runtime asset id, and every loaded id in `assets_loaded`. Nothing about
the loop changes: a replacement that hides the player, darkens the scene or drops the
objective is a regression the playability step catches.

A readable entity may stay a primitive in production only when the design states
`visual_identity.primitive_style` with a reason - the art direction is geometric on purpose
(an abstract neon runner). A character is never geometric by convenience, and visual QA still
judges a geometric look.
