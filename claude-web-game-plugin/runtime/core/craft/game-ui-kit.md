# Game UI kit

**Serves** `build_spec.visual_identity.ui` (`font_px`, `min_target_px`, `button`, `surface`),
`.typography`, `build_spec.screens`, `.hud`, `.menus`, `.responsive`, `scope.locales`, the
font assets of role `font`, and the UI checks of `core/reference/experience-rules.yaml`
(`ui`) and `core/reference/production-quality.yaml` (`ui.*`), and the visual QA rubric's
`ui_polish` and `typography` (`core/reference/visual-qa-rubric.yaml`).

`ui-hud-mobile.md` says where things go and `production-art-and-ui.md` that the interface is
drawn in the identity. This playbook is the kit both reference ports shipped - fonts, tokens,
buttons, HUD, screens, portrait - with the numbers, so the next game starts from a working kit
instead of browser defaults.

## 1. Fonts are assets

- **Two or three faces, each with a job.** Display (title, buttons, HUD numerals), body
  (rules, notes), optionally numeric. References: Bungee + Figtree (2D, riso), Unbounded 800
  + Instrument Sans 500 + JetBrains Mono 700 (3D, neon). All SIL OFL 1.1.
- **Licence and source recorded** like any asset: OFL fonts from the upstream font
  repository, the OFL text shipped beside each file, `license: OFL-1.1` in `library.json`
  with `attribution`.
- **Glyph coverage per locale.** Every face must cover the scripts of `scope.locales`.
  Subset to what you ship (the 2D reference: `U+0020-007E, U+00A0-00FF, U+2010-2027, ...`,
  WOFF2, layout features kept) - and check the subset against the locale list. The 2D
  reference shipped `ru` with no Cyrillic in either face, so Russian fell back to a system
  font: pick a face with Cyrillic (or add one for that locale) when `ru`, `uk`, `be`, `kk` are
  listed. The fallback stack is a last resort, not a plan.
- **Load before the first UI frame.** Declare, preload, await:

  ```css
  @font-face { font-family: "wgf-display"; src: url(assets/fonts/display.woff2) format("woff2");
               font-weight: 100 900; font-display: block; }
  ```
  ```js
  await Promise.all([document.fonts.load('700 24px "wgf-display"'),
                     document.fonts.load('600 16px "wgf-body"')]);
  ```

  `font-display: block` so no fallback flashes; URLs come from the runtime asset manifest
  (`production-wiring.md`), never a hard-coded path. Canvas text uses the same family after
  the await.
- **Prove it.** `document.fonts.check('16px "wgf-display"')` is true, and the computed
  `font-family` of every button and HUD element resolves to the bundled face. The production
  gate and the regression guard both check this.

## 2. Tokens

UI colours are palette tokens, declared once as CSS custom properties, used by DOM and
canvas alike:

| Token | 2D reference (light) | 3D reference (dark) |
|---|---|---|
| ground / paper | `#F4EDE1` | `#0B0B12` |
| surface | `#E4D9C6` | `#16162A` |
| ink (text) | `#1C1A17` | `#EDEBFF` |
| lead accent (primary button, player) | `#FF48B0` | `#FF2E88` |
| second accent | `#0078BF` | `#2EF2FF` |
| heading / overlap | `#6C3C9E` | - |
| danger | `#E3350D` | `#FFB020` |
| min target | `--target: 48px` | 48 px |

## 3. Contrast and size floors

| Rule | Number | Source |
|---|---|---|
| Text on its background | >= 4.5:1 (>= 3:1 only at 24 px, or 18.66 px bold) | `production-quality.yaml` `ui.min_contrast`, `min_contrast_large` |
| Button label token on its fill token | >= 4.5:1 | `experience-rules.yaml` `ui.min_contrast` |
| Body and HUD text | >= 14 CSS px (the gate's absolute floor is 12) | `experience-rules.yaml` `ui.min_font_px` |
| Touch targets | >= 44 CSS px, kits use 48; the design may raise it | `ui.min_target_px` |
| Overlap | no control overlapping text or another control | `ui.overlap` |

Pairs measured in the references: ink on pink 5.6, ink on paper 14.9, paper on purple 6.5 -
pass. Paper on blue 4.07 and red on paper 3.77 - large text only. **White on cream 1.16** was
the first-pass defect (HUD text near-invisible): compute every pair before you ship it, on the
frame, not in your head. A HUD over a moving scene gets a chip or a scrim behind it.

## 4. Buttons

Drawn, never browser defaults. The 2D "slab":

```css
.btn { min-width: var(--target); min-height: var(--target); padding: 10px 22px;
       font: 18px "wgf-display"; text-transform: uppercase; color: var(--ink);
       background: var(--pink); border: 3px solid var(--ink); border-radius: 4px;
       box-shadow: 4px 4px 0 var(--ink); transition: transform 60ms steps(2), box-shadow 60ms steps(2); }
.btn:active { transform: translate(4px, 4px); box-shadow: none; }
.btn:focus-visible { outline: 3px solid var(--blue); outline-offset: 4px; }
.btn:disabled { opacity: .5; box-shadow: none; }
.btn.big { min-height: 60px; font-size: 24px; }        /* the one primary action */
.btn.secondary { background: var(--purple); color: var(--paper); font-size: 16px; }
```

- **States**: idle, pressed (the press must be visible within one frame - translate into the
  shadow, or scale 0.96), focus ring, disabled.
- **One primary per screen**: `.big`, min 220x60 measured, the lead accent. Secondary
  buttons smaller and quieter (paper or purple fill, 16 px). The 3D kit: a 60 px pill
  (radius 28) in the accent with dark text and a glow; secondaries square-cornered with a
  2 px ink border.
- **Icon buttons** 48x48 (52x52 in the 3D HUD), the kit's icon at 24-30 px; a toggled-off
  state that reads without colour (the 2D sound button: a red 34x4 slash at -45 degrees).
- Overlay controls stop `pointerdown` from reaching the playfield.

## 5. HUD

- **A row of chips at the top, inside the safe area**, one value per chip: label small
  (13-14 px, uppercase, letter-spaced 0.12-0.24 em), value large (20 px 2D, 34 px 3D centred
  score) with `font-variant-numeric: tabular-nums` so rolling numbers do not jitter.
- **Reserve the corner for Pause and Sound**: right padding 120 px on the chip row; Pause at
  `top: max(8px, env(safe-area-inset-top))`, `right: 12px`. The first-pass defect was a
  "Next" chip clipped under Pause - reserve space, then let chips wrap (`flex-wrap`, gap
  `10px 12px`, `white-space: nowrap` per chip).
- **Chips** carry the kit: paper fill, 2-3 px ink border, radius 4, hard shadow `3px 3px 0`.
  On a dark scene: `rgba(11,11,18,.62)` with a 2 px accent border at 0.45 alpha.
- **The objective** is one line under the HUD (top + 60-66 px), centred,
  `max-width: min(92vw, 560px)`, on a translucent panel - visible within 3 s of play
  (`start.objective`).
- **Feedback** on change: a 240 ms bump on the value (`juice.md`), never a silent swap.

## 6. Screens: title, pause, result, retry

| Screen | Contents, in order | Primary |
|---|---|---|
| Title | wordmark (`min(80vw, 460px)`), one-line rules, Play | Play (`.big`) |
| Pause | heading, Resume, (sound) | Resume |
| Result | heading ("Crashed", "Game over"), score large (56 px 2D, 40 px 3D), best (celebrate a new best), a short note, optional rewarded offers as secondary, Play again | Play again (`.big`, retry icon) |

- **Cards, not pages**: `min(92vw, 480px)` (560 for the title), padding 26/24/30, gap 14,
  hard shadow `8px 8px 0`, the 9-slice panel art as `border-image` when delivered.
- **The game shows through**: a scrim (the 2D kit: ink halftone dots at 0.16 on a 7 px grid
  over paper at 0.42; the 3D kit: a surface card at 0.92 with a glowing accent border), so a
  result reads "in play's context".
- **Entry motion**: a 260 ms stamp (`steps(4)`, from scale 1.12, -1.5 degrees, opacity 0); the
  3D result card waits 650 ms after a crash so the crash is seen first.
- **Retry goes straight to play** within `max_retry_s` (3 s): no title screen, no reload, an
  interstitial only where the design places one (an ad in front of retry measured 12 s in
  the UI demo - it fails the contract).
- Headings in the display face, 32 px (`clamp(32px, 9vmin, 64px)` on a full-bleed title),
  with the kit's signature (a misregistered `text-shadow: 4px 3px 0 pink, 7px 5px 0 blue`).

## 7. Mobile portrait

- **Design the portrait layout; do not shrink desktop.** Defect from the first pass: a tiny
  track in an empty portrait screen. The 2D reference in portrait (`h > w*1.15`): slots
  1.7x taller, the track at two-thirds down, towers taller, and the empty top filled with a
  large "next piece" card (only when >= 90 px of room) - the HUD's Next chip hidden at
  `orientation: portrait and max-width: 600px` because the card replaces it.
- **Breakpoints**: `max-width: 480px` - chips min-width 50, objective 14 px, big buttons
  20 px; `max-width: 600px` - HUD wraps to two rows, the 3D Best moves beside Pause
  (`right: 64px`).
- **Safe areas** on every edge (`env(safe-area-inset-*)`), nothing interactive within
  16 px of an edge.
- **Test at 390x844 (touch) and 1280x720**, title -> HUD -> pause -> result -> after retry,
  and look at every frame.
- `prefers-reduced-motion` turns off card and bump animations, not the feedback itself.

## Failure modes

- A system font on any button, HUD value or result (a fallback is a missing asset).
- Locale text in a face without its script.
- White or light text on a light ground; text straight on a busy scene.
- A control clipped by, or overlapping, another control.
- Two primary-looking buttons on one screen; a browser-default button.
- A portrait layout that is the desktop layout, smaller.

## Distilled from

The template's reference ports: `examples/tower-merge-rush/wgf-golden/index.html` (tokens,
slab buttons, chips, cards, scrim, breakpoints, keyframes), `src/ui/screens.ts` (screen
structure, art lookup), `src/assets/runtime-assets.ts` (`loadFonts`), `library/library.json`
(font licences), `src/rendering/pixijs/tower-view.ts` (`trackLayout` portrait);
`examples/neon-drift-arena/wgf-golden/index.html` (dark kit, pill button, HUD bar, result
delay, portrait Best) and `src/rendering/threejs/assets.ts` (`FontFace` loading); frames
`baseline/` (title, game over, mobile) of both; the design/UI demo of 2026-10-01 (frames
desktop and mobile title, hud, pause, result, after-retry; the contrast table); the defects
"white text on cream", "Next chip under Pause", "tiny portrait track" and "no Cyrillic for
`ru`" from the 2026-10-01 quality monitor.
