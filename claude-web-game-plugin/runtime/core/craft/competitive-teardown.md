# Competitive teardown

**Serves**
- `portfolio:market-scan`: claims and research snapshots under
  `workspace/research/snapshots/`, the input the discovery step reads
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

## Turning it into evidence

Evidence discipline applies unchanged:

- Each measured fact is an **observed** claim, citing the game's page URL and the time
  observed. Example: "Game X reaches first play in 4 s with one tap on a throttled phone
  viewport."
- Patterns across games are **derived** claims, referencing the observed ones. Example:
  "3 of 4 category leaders put the first reward within 20 s."
- What it implies for this title is a **hypothesis**, confidence ≤ 0.6. Example: "A 20 s
  first reward is a market expectation for this niche."
- Observation and interpretation are always separate claims.

Where the result is a reusable research input, write it as a snapshot file in the existing
snapshot format: one observation per fact, `source_kind` describing a played observation,
`retrieved_via` naming the method. It is then read like any other evidence.

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
