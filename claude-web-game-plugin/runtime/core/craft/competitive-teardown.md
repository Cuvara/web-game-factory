# Competitive teardown

**Serves**
- `portfolio:market-scan`: game records under `workspace/research/games/` (the research
  corpus) and listing snapshots under `workspace/research/snapshots/`, the inputs the
  discovery step reads
- `title:strategy`: `concept`, `prototype_must_prove`, kill criteria
- `title:design`: session numbers, monetization placement

Market data says what is popular. A teardown says **how the successful games in a niche
actually play**, and that is what lets a strategy commit to measurable targets rather than
guesses.

## Choosing what to tear down

- Pick 3–5 games from the same portal category and the same control scheme as the
  opportunity. Include at least one that ranks well and one recent entrant.
- Only publicly playable builds on the portal itself. Never decompile, scrape assets, or
  reuse any part of another game. The teardown observes; it never copies.

## What to record, per game

Play each game at least twice: once as a first-time player on a phone viewport, and once
trying to master it. Record observations with times:

| Dimension | Observe |
|---|---|
| Load | Time to first frame; time to first play; clicks before play |
| Onboarding | Tutorial approach (none / diegetic / guided / text); the first verb taught |
| Loop | Core verbs; decision frequency; risk/reward present? |
| First reward | Time to it; what it is; how it is signalled |
| Session | Time to first failure; typical run length; retry time |
| Progression | What carries across runs; terminal or looping |
| Monetization | Placement moments (which state, which trigger); rewarded offer value; interstitial frequency |
| Feel | Standout feedback (hit-stop, pops, audio) and anything that felt bad |
| Presentation | Thumbnail subject; orientation; visual identity in one line |

## Coding it: the game record

A teardown is written as one **game record** per game, `<corpus>/games/<game-id>.json`,
validated by `core/artifacts/shared/game-record.schema.json`. Every value is a code from
`core/reference/research-vocabulary.yaml`, so the next scan can count across games:

| Observe (above) | Facets |
|---|---|
| Load, onboarding | `time_to_first_play_seconds`, `taps_before_play`, `tutorial` |
| Loop | `mechanics`, `gameplay_steps`, `controls`, `decision_type`, `skill`, `randomness` |
| First reward, session | `time_to_first_reward_seconds`, `first_failure_seconds`, `run_seconds`, `retry_seconds` |
| Progression, difficulty | `progression`, `difficulty_shape`, `difficulty_axes`, `retention_hooks` |
| Monetization | `ad_formats`, `ad_triggers`, `interstitial_interval_seconds` |
| Presentation | `theme`, `setting`, `art_dimension`, `art_rendering`, `art_tone`, `art_palette`, `camera`, `animation`, `orientation` |
| Fantasy, audience | `player_fantasy`, `emotional_fantasy`, `audience_type`, `intent`, `device`, `age_band` |
| Production | `physics_engine`, `networking`, `unique_assets`, `bundle_mb` |

Procedure, per game:

1. **Open a session** for each sitting: the page URL, the time, the method (`played`,
   `store-page`, `screenshot`, `video`, `listing`), who observed, and - for a played
   session - the viewport and the number of runs. Its `note` says what was done, plainly
   enough to repeat. Keep a capture (recording or screenshots) and name it in
   `capture_uri`.
2. **Code each facet against a session**, with an excerpt the capture can confirm. Mark it
   `observed` when the excerpt is the thing itself - a stopwatch reading, the portal's own
   category tag, an ad offer seen on screen - and `interpreted` when it is your reading of
   the capture (a theme, a tone, a fantasy, an audience). An interpreted coding becomes a
   derived claim resting on the session, never an observation.
3. **Leave uncoded what you did not see.** An uncoded facet is counted as unknown, not as
   "no". Do not code an age band a portal does not state.
4. **Keep what does not fit a facet as a note** (`strength`, `exception`, `ux`, ...). Notes
   are evidence; they are never counted.
5. **Name the listing names** the game appears under, so portal listings join the record.

A record no session supports, a code outside the vocabulary, or a session dated after the
scan is refused. Test data is marked `"fixture": true` and is never real evidence.

## Turning it into evidence

The discovery step does the counting; the discipline is unchanged:

- Each measured fact is an **observed** claim, citing the game's page URL and the time
  observed. Example: "Game X reaches first play in 4 s with one tap on a throttled phone
  viewport."
- Patterns across games are **derived** claims, referencing the observed ones. Example:
  "3 of 4 category leaders put the first reward within 20 s."
- What it implies for this title is a **hypothesis**, confidence ≤ 0.6. Example: "A 20 s
  first reward is a market expectation for this niche."
- Observation and interpretation are always separate claims.

Patterns across games ("3 of 4 category leaders ...") are derived by the scan itself from the
coded records, with the numerator, the denominator, the games and the exceptions - do not
write them by hand.

## How it feeds the title

- **Strategy.** The derived timings become starting kill-criteria thresholds and `session`
  targets. The loop comparison becomes the differentiator stated in `concept`: what this
  title does that the observed games do not.
- **Design.** Placement moments that the leaders converge on inform
  `monetization_touchpoints`, subject always to the platform profiles.

## Failure modes

- **Cloning the leader.** The teardown sets the bar, and the concept must still say why this
  game is different.
- **Desktop-only teardowns.** Most portal traffic is on phones.
- **Undated observations.** Portal games update, and a teardown is evidence as of a date.
