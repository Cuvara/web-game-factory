# UI, HUD and mobile

**Serves** `build_spec.screens`, `.hud`, `.menus`, `.responsive`, `ux.screens`, and the
`responsive` verification aspect.

Most portal sessions are on phones, in an iframe, in whichever orientation the player happened
to be holding. Design for the smallest viewport the platform profiles allow, then let larger
ones breathe.

## Touch and pointer

- **Touch targets ≥ 44 CSS px** (`responsive.min_touch_target_px`), with at least 8 px
  between them. Game-world targets that are smaller than that get a larger invisible hit
  area.
- **Thumb zones.** In portrait, primary actions sit in the bottom third. In landscape, they
  sit at the lower left and right edges. Pause and settings go top-right, away from the
  thumbs.
- **Never rely on hover.** Anything hover reveals on desktop needs a tap equivalent.
- **Gestures stay simple.** Tap, hold and swipe in one of four directions. Multi-finger
  gestures and long, precise drags do not survive an iframe on a small phone.
- Stop browser gestures inside the game area (pull-to-refresh, pinch zoom, text selection,
  the long-press menu). Leave them alone outside it.

## Layout

- Fill `responsive` completely: orientation, `design_resolution`, `scale_mode`, per-layout
  anchors, `safe_area`, what happens in the `wrong_orientation`, and the `resize` behaviour.
- Anchor HUD elements to screen edges and the safe area, never to fixed pixel positions in the
  design resolution.
- **The wrong orientation** either reflows or shows a clear, animated "rotate" prompt that
  pauses the game. It never shows a squashed game.
- Test at three sizes at least: a small phone (about 360×640), a large phone (about 430×930),
  and a desktop 16:9. Test both orientations if the profile allows both.
- Cap `max_pixel_ratio` (typically 2) so high-density screens do not render four times the
  pixels (`web-performance.md`).

## HUD

- **Show at most three live values** during play. Everything else goes on the pause or result
  screen.
- The score and the value the current decision depends on are the largest elements. Labels
  are icons where the meaning is unambiguous.
- Values animate when they change (`game-feel.md`).
- The HUD never covers the play area where the next decision happens. Keep a clear central
  column in portrait and a clear centre in landscape.
- HUD text keeps contrast against every background it can appear over: outline it, shadow it,
  or give it a backing plate (`accessibility.md`).

## Screens and menus

- Every screen in `build_spec.screens` has one primary action, visibly dominant. On the result
  screen that action is **retry**, not the menu.
- Back or close is always in the same place.
- Text is set in the display face from `visual_identity.typography` for headings, and a
  legible face for everything else. Body text is at least 16 CSS px on phones.
- All player-facing strings go through the localization layer from the first commit, so
  required locales do not force a rewrite.

## Failure modes

- **Desktop-first layouts** that shrink to unreadable on a phone.
- **Hidden controls**: a mechanic only reachable by a key the touch player does not have.
- **Generic UI.** Stock buttons and the default font. The UI is where `visual_identity` is
  most visible. Generic UI is a design failure (`design.md`).
