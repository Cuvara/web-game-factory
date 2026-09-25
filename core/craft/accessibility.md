# Accessibility

**Serves** `ux.accessibility`, `build_spec.visual_identity`, `.controls`, `.hud`,
`.responsive`, and the reduced-motion rules in `game-feel.md`.

On a portal, accessibility is mostly reach. A game that is readable in sunlight, playable one
handed, and safe for photosensitive players reaches more of the traffic it already paid for.
`ux.accessibility` must list which of the defaults below the design meets, and why any are
out of scope. An empty or generic value means this was not considered.

## Baseline (every title)

| Area | Default |
|---|---|
| **Photosensitivity** | No content flashes more than **3 times per second**. No full-screen red flashes. Checked on every effect, including hit and damage feedback. |
| **Colour** | No information by colour alone. Hazards, pickups and team or state carry a shape, icon or pattern too. The palette passes a greyscale and a deuteranopia/protanopia check. |
| **Contrast** | HUD and body text contrast at least 4.5:1 against every background it appears on. Large display text at least 3:1. |
| **Text** | Body text at least 16 CSS px on phones. There is no gameplay-critical text in the play area. |
| **Motion** | Honour the system reduced-motion preference: no shake, no parallax, no flashing, shortened tweens. Offer an in-game toggle when the game relies on motion effects. |
| **Input** | Playable with one hand on a phone. Nothing requires simultaneous multi-touch, rapid mashing or precise long drags, unless it is the core skill and the design says so. |
| **Timing** | Reading and menu screens never time out. Where the game allows, a pause is always available. |
| **Audio** | Nothing gameplay-critical is audio-only. Every critical cue has a visual counterpart. |

## Cheap wins worth taking

- A larger HUD option, or a scale-up in the settings.
- Hold as an alternative to tap-repeat.
- An optional assist mode in non-competitive modes (`core-loop-and-difficulty.md`).
- Keyboard support on desktop, with visible focus on menus.

## How it is checked

- **At design**, against the style sheet (`art-direction.md`): greyscale and colour-blind
  simulations of the palette on real screens.
- **At prototype and QA**, in the browser: the reduced-motion setting on, a small phone, one
  hand, sound off. Record what was observed as notes in a gameplay-session scenario or a
  playtest (`playtesting.md`). A flash-rate violation is a blocking defect.

## Failure modes

- **Colour-coded matching games** with no second channel.
- **Flash as the only damage feedback.**
- **"Accessibility: TBD"** at design. It is harder to retrofit than to design in.
