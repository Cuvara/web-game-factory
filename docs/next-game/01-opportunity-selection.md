# Next game: opportunity selection

Date: 2026-10-22. Status: Phase 1 of the next-game task. Planning only; no code, build or paid call was made to produce it. A free `--mock` `new-game` run was made only to check that the idea string routes through the workflow to G4; its placeholder output is workflow evidence, not evidence about game quality, and nothing in this document depends on it.
Labels: **[F]** verified fact with source; **[H]** hypothesis; **[U]** unknown. Sources accessed 2026-10-22 unless a repository path is given.

## 1. Constraints from the repository

- Template pin: `web-game-template` v1.2.4, commit `34d5641` (`workspace/config/template.lock.json`, merged in PR #89) [F].
- Portfolio so far: Brick Breaker Worlds (breakout, 2D), Sky Marble (marble, 3D), Animal Out (tap-away puzzle, 2D), Zombie Swarm Survivor (survivor shooter, 2D). None has portal outcome data beyond Animal Out's 398 plays / 200 impressions on Y8 [F, Y8 console snapshot of 2026-10-21 recorded in `docs/monetization/README.md`; figures not independently re-checked].
- Portfolio rules (`docs/monetization/market-research-strategy.md` section 5): no two consecutive titles in the same archetype before the first clears a portal's Full Launch bar; at most half of active titles in one genre family; at least 3 non-exclusive portals per title [F, repository policy].
- Portal bars the game must be able to meet: CrazyGames Full Launch looks at average playtime, D1 and conversion; successful titles often see 10+ minutes, D1 10-15%, 80%+ conversion, load under 10 s, build under 20 MB [F, https://docs.crazygames.com/resources/basic-launch-metrics/]. Poki Player Fit Test: 3+ minutes average and 25%+ of plays over 3 minutes; final review targets 65%+ conversion and 5+ minutes (10+ for management and simulation) [F, https://developers.poki.com/guide/how-testing-works]. Y8 rejects copied, low-quality, repeatedly reskinned or mass-generated games [F, https://developer.y8.com/].
- Corpus gap: `workspace/research/games/` holds no teardown records, so no candidate can carry an `observed` market claim from our own teardowns [F, `docs/monetization/market-research-strategy.md` section 1]. Everything about competitors below comes from public pages and is labelled as such.
- Engines available: PixiJS, Phaser (2D), Three.js (3D) [F, `CLAUDE.md`].

## 2. Market evidence collected today

- No portal publishes plays by genre in a usable table; genre popularity claims are indirect [F, search results; low-authority trend pages are not used as evidence].
- CrazyGames has a dedicated tower defense category; its most-popular list led with Mage Castle Idle Defense, Tower Swap, Bloons Tower Defense 4 and Evil Tower (page about 17 months old, may be stale) [F, https://www.crazygames.com/t/tower-defense].
- Bloons Tower Defense on CrazyGames: rating 9.3 over six months, 28K likes, 2.7K dislikes, desktop only (runs on Ruffle). Tower Defense Clash: 9.0, 43K likes, 6.2K dislikes, desktop and mobile [F, https://www.crazygames.com/game/bloons-tower-defense and https://www.crazygames.com/game/tower-defense-clash]. Votes indicate engagement, not plays and not revenue.
- Poki's tower defense page lists Bloons Tower Defense, War of Sticks, Like a King, Stickman Kingdom Clash, Age of War at the top (popularity order, no ratings) [F, https://poki.com/en/tower-defense].
- Kingdom Rush levels run about 10-15 minutes and it is not on Poki or CrazyGames in the results [F, search summary of third-party roundups; low confidence].
- Poki's 2026 survey puts the average web session at 11-20 minutes [F, secondary report; unverified in Poki's own words].
- Hybrids are common (match-3 plus tower defense in Tower Swap; idle plus defense) [F, listing pages].
- Not found: play counts, revenue, or retention for any comparable [U].

## 3. Candidate concepts

All six differ in archetype from the last four titles unless noted. Concept names are working titles.

| ID | Concept | Genre family | Engine | Archetype note |
|---|---|---|---|---|
| C1 | **Switchyard**: tower defense where the player also throws track switches to route rail-riding enemies through kill zones | strategy | PixiJS | New archetype for the portfolio |
| C2 | Endless idle breaker with prestige | arcade/simulation | PixiJS | Same archetype as Brick Breaker Worlds: vetoed by portfolio rule 1 |
| C3 | Roguelite wave survivor, new theme | survival | PixiJS | Same archetype as Zombie Swarm Survivor: vetoed |
| C4 | Merge/physics drop puzzle | puzzle | PixiJS | Puzzle just shipped (Animal Out); category saturated [H] |
| C5 | Low-poly 3D time-attack racer | racing | Three.js | Poki lists cars as 10% of plays [F, https://poki.com/]; 3D asset and physics cost high; Neon Drift Arena example exists in the template |
| C6 | Precision platformer with a gravity mechanic | platformer | PixiJS/Phaser | Crowded; demands hand-tuned level design the Factory does not yet validate [H, `docs/monetization/level-design-improvements.md`] |

## 4. Scoring

Rubric: the v2 scorecard dimensions proposed in `docs/monetization/market-research-strategy.md` section 4, grouped into the seven the task names. Scale 0-5, weights below. Scores are **judgements [H]** from the evidence above, not measurements; they rank candidates, they do not predict revenue. A veto removes a candidate regardless of score.

| Dimension (weight) | C1 | C2 | C3 | C4 | C5 | C6 |
|---|---|---|---|---|---|---|
| Differentiation (0.20) | 4 | 2 | 2 | 1 | 2 | 2 |
| Gameplay depth, replay (0.20) | 4 | 3 | 4 | 2 | 3 | 3 |
| Production feasibility (0.15) | 4 | 4 | 4 | 4 | 2 | 3 |
| Performance and load budget (0.10) | 5 | 5 | 4 | 4 | 3 | 4 |
| Monetization compatibility (0.15) | 4 | 3 | 4 | 3 | 3 | 3 |
| Portal demand signal (0.10) | 4 | 3 | 3 | 3 | 3 | 3 |
| Moderation / originality risk (0.10, higher = safer) | 4 | 2 | 2 | 1 | 3 | 3 |
| **Weighted total (max 5)** | **4.10** | 3.05 | 3.30 | 2.45 | 2.65 | 2.90 |
| Veto | none | portfolio rule 1 | portfolio rule 1 | `reskin_risk` likely | none | none |

Totals are the weight-by-score sums (C1: 0.8+0.8+0.6+0.5+0.6+0.4+0.4 = 4.10). The gap between C1 and the next-highest score (C3, 3.30, vetoed) is 0.8, and 1.2 to the best unvetoed alternative (C6). Either is larger than the +-1 point judgement error on any single dimension times its weight (at most 0.20), so the ranking is robust to one mis-scored dimension, not to a systematically wrong view of the market.

## 5. Selection

**C1, Switchyard.** Why it beats the others:
1. It is the only candidate that is both a new archetype for the portfolio and unvetoed with a named differentiating axis: a tower-defense layer plus a routing layer (switching rails) so the player shapes where enemies travel as well as what they meet. Comparable titles in the lists above place towers on fixed or player-drawn paths; none found in the lists above routes enemies on switchable rails [H: absence in a short listing sweep, not a full survey].
2. Strategy/tower defense sustains 10+ minute sessions: levels of 10-15 minutes are the genre norm [F, secondary], which fits the CrazyGames and Poki playtime bars better than short-round arcade formats [H].
3. Natural ad breaks exist: between waves, between levels, and on defeat; an optional rewarded offer fits (retry with bonus gold). That matches the portals' rules: ads between levels, rewarded optional [F, `docs/monetization/monetization-and-distribution.md` (CrazyGames, Yandex rules) and portal profiles in `core/reference/platforms/`].
4. It is feasible in 2D with geometric art, small bundle and no physics engine; load and size budgets are easy [H].
5. Its content scales by data (maps, rail layouts, enemy mixes), which the Factory's genre model already counts (`core/reference/genre-models.yaml`, family `strategy`).

Risks accepted and mitigations [H]: onboarding complexity of two verbs (towers and switches) - introduce one verb per early level; pathing correctness - needs solvability tests for every level; novelty may not match what players search for - keep the genre label "tower defense" in the title and description; balance depth - deterministic simulation with seeded tests.

What would change the decision: a teardown of 10 tower-defense games that shows switch-routing already exists in a top title, or a greybox playtest where first-session understanding fails the kill metric below.

## 6. Acceptance criteria for the concept (before any implementation)

These are the gates the Factory design and QA steps must satisfy; numeric targets are starting values to be tightened by the design step.

1. **Originality**: a written differentiation statement naming the routing mechanic, and at least 5 teardown records of comparable tower-defense games in `workspace/research/games/` (`scripts/wgf-corpus.py`), none showing the same mechanic as the core. If one does, the concept is reworked, not shipped.
2. **Depth**: designed content of at least 12 levels in at least 4 themed worlds with enemy kinds and tower kinds introduced progressively; total designed play time of at least 40 minutes at the release tier (the quality benchmark governs the exact bar; design step confirms). Designed minutes are not measured retention.
3. **First session**: a new player places the first tower and flips the first switch within 60 seconds of pressing Play, with no text wall; a bot-played greybox reaches wave 2 of level 1 without error.
4. **Every level solvable**: for each level, a scripted solution exists and is verified by the simulation; naive play (no switches) loses on at least levels 4 onward and wins levels 1-3 (difficulty curve test).
5. **Performance**: loads under 10 s on a mid-range phone profile; build under 20 MB; 60 fps target in desktop and mobile Playwright profiles; zero console errors in a full level.
6. **Ads**: interstitial only after a player click at a natural break; rewarded optional with a non-ad alternative; pause and mute only inside the portal's before/after callbacks; `platform.ads-integrated` passes per target portal; mock and real-SDK evidence reported separately.
7. **Persistence and recovery**: progress, settings and best stars survive reload; asset-load failure shows a recoverable error screen; pause, resume and restart tested.
8. **Portal readiness**: listing assets valid per profile; no outbound links; AI-use disclosure prepared; targets Y8, CrazyGames, GamePix, Yandex (Poki deferred).
9. **Measurement**: the analytics events from `docs/monetization/analytics-and-feedback-loops.md` are emitted to a sink where the portal permits, and a portal-report record exists for it after release.
10. **Kill metric (greybox)**: with 5 players unfamiliar with the game, at least 4 complete level 1 and at least 3 re-start level 2 unprompted; otherwise stop before production spend.

## 7. Open items needing a person or authorization

- The live Factory run is paid agent work: earlier runs cost about US$130-250 per game (`budget-ledger.md`). It needs your explicit authorization and a cap. No such run has been started.
- Ten teardowns are human play-throughs (20-30 minutes each); I did not fabricate any.
