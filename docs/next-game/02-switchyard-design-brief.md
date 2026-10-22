# Switchyard: design brief

Date: 2026-10-22. Status: Phase 2 input. This is the human-written brief that the Factory's design step (`wgf_design`) expands into the schema-valid `game-design` artifact; numbers are targets for that step to confirm or tighten, not measurements. Selection and acceptance criteria: `01-opportunity-selection.md`.

## Audience and USP

- Players: browser casual-to-mid-core strategy fans on desktop and phone, sessions of 10-20 minutes [H, portal survey figures in the selection doc].
- USP: a tower defense where enemies ride rails and the player also **throws the track switches**. Towers decide what enemies meet; switches decide where they go. Same level, many solutions.
- Differentiation axis for `patterns.differentiate_on`: routing as a second verb.

## Core loop (one wave, 30-90 s)

1. Preview: the wave's enemy kinds and entry rails are shown.
2. Build: spend gold to place or upgrade towers on slots beside the rails (pause-free; the wave timer starts when the player presses Go, never automatically on level 1-3).
3. Run: enemies ride the rails; the player flips switches (tap a junction) to send groups down a longer, tower-lined branch or a dead end; each switch has a cooldown so routing is a choice, not a flick race.
4. Resolve: enemies reaching the depot cost lives; kills pay gold.
5. Between waves: spend, re-plan. After the last wave: stars (1-3) for lives left.

Secondary loops: star-gated world unlocks (meta), tower upgrades inside a level (short), a best-stars board per level (return reason). No shop, daily login or leaderboard in version 1; they are not justified by the loop and the portals' adapters do not support leaderboards (`docs/monetization/factory-audit.md` T7).

## Controls and onboarding

- One input scheme: pointer/touch. Tap a slot to open the tower ring; tap a junction to flip; tap Go. Keyboard shortcuts optional on desktop.
- Level 1: one rail, no switch, one tower type: teaches placement. Level 2 introduces one junction with a visibly better branch: teaches switching. Level 3 adds a trap branch (dead end). Each new verb is introduced alone, with a one-sentence prompt and a highlighted target; no text wall.
- First-session target: first tower placed within 15 s of Play, first switch flipped within 60 s.

## Progression, difficulty, content

- 4 worlds x 4 levels = 16 levels at the release tier (the quality benchmark in `core/reference/quality-benchmark.yaml` sets the exact bar; the design step confirms or raises it). Each world introduces one new enemy kind and one new tower kind, plus one new rail rule (e.g. one-way junction, timed junction, merge junction).
- 4 tower kinds (rapid, splash, slow, long-range), 5 enemy kinds (runner, tank, swarm, shielded, boss-wagon). Boss levels reuse earlier elements in a new rail shape; no invented elements outside the design's list.
- Difficulty: levels 1-3 are won by naive play; from level 4 naive play (no switching) loses and switching wins; stars from level 6 need a planned route.
- Designed time at 16 levels x about 3 minutes = about 48 minutes of first play, plus star replays. This is designed content, not measured retention.
- Level generation: authored by hand as data (rails graph, slots, waves) in `public/content/units.json`; each level validated by the deterministic simulation (see tests).

## Win, loss, retry

- Win: all waves cleared with lives > 0. Loss: lives reach 0. Retry is one tap, restores the pre-wave-1 state, keeps the player's tower choices as a suggestion.
- Feedback: hit flashes, kill coin pops, junction click and light, wave banner, life-loss shake (honouring reduced-motion).

## Art, audio, accessibility, layout

- Art: flat geometric low-detail 2D, readable at phone size; a coherent palette per world; rails and junction state shown by shape, not colour alone. Assets come from the Factory asset pipeline's placeholder/library backends; no paid generation without authorization.
- Audio: short sound set (place, shoot, hit, switch, win, lose) and one loop per world, mute toggle on every screen.
- Accessibility: colour-blind-safe junction states (shape + colour), no flashing above the safe rate, tap targets at least 44 px, reduced-motion setting.
- Layout: responsive from 360x640 portrait to 1920x1080; the board scales to fit; HUD outside the play area on narrow screens.

## Save, offline

- Local storage: stars per level, unlocked worlds, settings, mute. Versioned save with a safe fallback if the save is corrupt. No network needed after load; portal SDK cloud save optional where the adapter supports it.

## Monetization (per target portal)

- Interstitial: after the player taps Next or Retry on a result screen (a player click, a natural break), at most once per portal's cap (Y8 about 180 s; CrazyGames 1 per 3 minutes via SDK).
- Rewarded (optional): on defeat, "retry with +50 gold start"; a non-ad alternative (plain retry) is always one tap away; granted only on the portal's completion signal; late rewards handled once.
- No banners; no ad during a wave; pause and mute only inside the portal's before/after callbacks.
- Ad placement is declared in `integration-plan.ts` for every target portal, and `platform.ads-integrated` must pass per portal (Factory PR #84).

## Performance budgets and test strategy

- Budgets: load under 10 s (mid-range phone profile), bundle under 20 MB, 60 fps target, no console errors.
- Tests: unit tests for the simulation (pathing along rails, switch cooldown, damage and economy, win/loss transitions, save versioning, exactly-once reward grant); a solvability test that runs a scripted solution for every level and a no-switch naive run for the difficulty curve; Playwright desktop and mobile first-session runs through the play probe; Factory gates (playability, production-quality, visual-qa, content-sufficiency, quality-gate).

## Release acceptance

The ten criteria in `01-opportunity-selection.md` section 6. Release stays a draft: no portal submission without a person's G5/G6/submit decisions.

## Idea string for the Factory run

`A 2D tower defense where enemies ride rails and the player throws track switches to route them through tower kill zones. Four worlds of four levels; each world adds one enemy, one tower and one rail rule. One-tap controls for desktop and phone; interstitial after result screens and an optional rewarded retry.`
