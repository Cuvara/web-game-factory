# Onboarding and portal UX

**Serves** `session.time_to_first_play_s`, `session.time_to_first_reward_s`,
`ux.onboarding`, `build_spec.tutorial`, `.screens`, `.monetization_touchpoints`,
`.sdk_touchpoints`, and the store metadata assembled at `release:draft`.

Portal traffic arrives with no commitment. The player clicked a thumbnail between two other
games. Everything in the first 30 seconds either earns the next 30 or loses the player.

## The first 30 seconds

Default targets. The design's `session` numbers override them, but should not be looser
without a reason.

| Moment | Target |
|---|---|
| First meaningful frame (not a blank canvas) | ≤ 2 s on the mid device class |
| Control in the player's hands (`time_to_first_play_s`) | ≤ 5–10 s from load, with **at most one tap** before play |
| First reward (`time_to_first_reward_s`) | ≤ 20–30 s, and reachable by doing the obvious thing |
| First failure | Not before the player has succeeded at the core verb at least once |

Rules:

- **One tap to play.** No account, no settings, no story screen, no mode select before the
  first run. Menus appear after the first session, or behind a small icon.
- **The loading screen shows progress and is branded.** It never shows a spinner alone.
  Load only what the first run needs; stream the rest in (`web-performance.md`).
- **Audio starts muted or unlocks on the first tap** (`audio.md`). A game that blares on load
  gets closed.

## Teaching

Choose `build_spec.tutorial.approach` in this order of preference, and write the reason
into `rationale`:

1. **none**: the verb is obvious from the scene (one button, one visible target).
2. **diegetic**: the level teaches it. The first obstacle can only be passed by using the
   verb, and it is placed so that failure is impossible or harmless.
3. **guided-first-run**: a hand or arrow shows the gesture once, and the game waits for it.
4. **explicit**: text instructions. A last resort, at most one line, never a wall.

Other rules:

- Teach one verb at a time, at the moment it is first needed, never up front.
- Show the gesture, not the words: an animated hand for swipe, a pulsing target for tap.
- `shown_once` is true for anything the player completes. A returning player never repeats
  it.
- Detect whether the device is touch or pointer, and show the matching prompt.

## Portal behaviour players expect

- Pause on tab blur and during ads, and resume cleanly. This is also a verification aspect.
- No external links, no requests for personal data, and no fake UI (a close button that is
  an ad).
- Save progress locally, or through the platform abstraction, so a reload does not wipe it.
- A visible mute toggle on every screen.
- Monetization touchpoints: a rewarded offer states its reward *before* the ad, is always
  optional, and when unavailable is hidden or explained (`when_unavailable`), never a dead
  button. Interstitials sit only on beat boundaries (`core-loop-and-difficulty.md`).

## Store presentation (release)

The thumbnail is the actual onboarding step for most players. It is assembled at
`release:draft` and checked at `release:validating` against the pinned platform profile.

- **Thumbnail:** one subject, the core verb implied, readable at 150 px wide, and no text
  beyond the title. Captured from the real game in the committed visual identity, not
  mocked up.
- **Screenshots:** mid-action moments from a real session, one per pillar. Not menus.
- **Description:** the first line says what the player *does*. Controls are listed in one
  line per device.
- Captures come from a real build at the release commit, never from a mock.

## Failure modes

- **Tutorial as a feature.** A long tutorial means the verb is too complex. Simplify the
  verb.
- **Front-loaded menus.** Every screen before play costs players.
- **A thumbnail that promises another game.** It lifts clicks, then kills retention and
  approval.
