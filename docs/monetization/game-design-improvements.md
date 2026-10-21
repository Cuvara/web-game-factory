# Game design improvements

How the design stage can produce games that players choose, finish and return to, not only
designs that pass consistency rules. Grounded in `core/artifacts/game-design.schema.json`,
`core/artifacts/title-strategy.schema.json`, `scripts/wgf_design/` and `scripts/wgf_strategy/`.

Labels: [C] confirmed, [I] inferred, [U] unknown.

## 1. Current state

- **Schema and rules are rich** [C]. The game design carries:
  - `core_loop` and `session` (first play, first reward, target length);
  - `retention` (hooks, return reason, targets) and `monetization` (placements with player value);
  - a 24-block `build_spec`: mechanics, content, experience, depth, mastery, tutorial, difficulty,
    progression, vfx, visual identity.

  About 14 blocking and 13 warning consistency rules, roughly 30 content rules, the first-30s
  budget (`experience.py`) and depth rules (`depth.py`) hold them.
- **Authors are weak at the release tier** [C].
  - The default author is one of 6 archetype templates.
  - The genre-seed author is one fixed seed per family.
  - The LLM author is opt-in, costs about US$8 a round with up to 3 repairs, and is required for
    release-tier content (`workspace/config/factory.yaml:868-876`).
- **Strategy is templated** [C].
  - Kill criteria (`control_not_understood` below 0.6, `no_retry_pull` below 0.5, overrun,
    mobile fps) and success criteria (D1 0.25-0.35, session length) are fixed
    (`scripts/wgf_strategy/planner.py:1243-1280`).
  - They are never measured: the develop report writes "NOT MEASURED"
    (`scripts/wgf_develop/report.py:181-188`).
- **Briefs lose features silently** [C]. BBW's endless mode and SM's time trial were in the
  briefs and were not built (baseline G-07, G-10).
- **A blocking design breach routes `descope`, which ends the run** [C]. Nothing consumes it.

## 2. The ten questions every design must answer

| # | Question | Where it lives today | Gap | Proposal |
|---|---|---|---|---|
| 1 | Why should the game exist? | `title-strategy.why_this_opportunity` (templated string) | Not evidence-based | Fill from the opportunity's research claims; cite them |
| 2 | Which audience? | strategy `audience`; research audience or `unknown` | Often "casual" by default | Require the portal audience notes (age, device) from teardowns |
| 3 | How does it differentiate? | Only `opportunity.research.patterns.differentiate_on` | **No field in strategy or design** | Add `title-strategy.differentiation {axis, versus[], evidence}` and a consistency rule that a design mechanic realizes it |
| 4 | What makes the core loop enjoyable? | `core_loop`, `pillars`, `build_spec.mastery`, `design.decision_cadence` warning | Structure only, no judgement | Stranger playtest at greybox (section 4); no AI "fun score" |
| 5 | How do the first 30-60 s work? | `build_spec.experience.first_30s`, `session.time_to_first_play_s` | Held | Keep; measure on real players |
| 6 | How do challenge and content evolve? | `build_spec.difficulty`, `content.axes_monotone_with_relief` | Held | Keep; add naive-play difficulty ([level-design-improvements.md](level-design-improvements.md)) |
| 7 | Why do players return? | `retention.hooks`, `return_reason`, `depth.return_hooks` | Hook enum lacks `daily_challenge` | Extend the enum; see section 5 |
| 8 | Which monetization fits? | `monetization.placements`, three blocking rules | Held | Add the ad opportunity estimate (P2 in the roadmap) |
| 9 | Which networks, and why? | `platform_constraints_applied`, strategy `platform_set` | Constraints only, not fit | Add `portal_benchmark_targets` derived from target profiles (playtime, conversion, size) |
| 10 | How are success and failure measured? | strategy `success_criteria` / `kill_criteria` | Templates, never measured | Measure at G4 by playtest; after launch from portal reports |

## 3. Design targets from the portals, not from our own games

The Factory's content bars come from two of its own games ("measured-2",
`core/reference/quality-benchmark.yaml`). Its release bar is 300 s of designed play. The portals'
published bars are higher:

| Bar | CrazyGames | Poki | Factory today |
|---|---|---|---|
| Average playtime | 10+ min (what successful titles often see; a benchmark, not a threshold) | 3+ min to pass Player Fit; 5+ min final (10+ management/sim) | 300 s designed content (release tier) |
| Conversion | 80%+ plays past 1 minute | 65%+ conversion to play | first play in 5 s (design) |
| D1 | 10-15% | not stated | 0.25-0.35 (strategy template, unmeasured) |
| Initial download | 20 MB or less for the mobile homepage | under 8 MB (3P guide) | per-profile `max_bundle_mb` |

Sources: https://docs.crazygames.com/resources/basic-launch-metrics/ ;
https://docs.crazygames.com/requirements/technical/ ;
https://developers.poki.com/guide/how-testing-works (OFFICIAL, accessed 2026-10-21);
https://app.cinevva.com/guides/publish-game-poki (3P).

**Proposal.** A design's `portal_benchmark_targets` take the strictest published bar among its
targets. A consistency rule warns when the designed content cannot reach it. Designed playtime
counts replays: content seconds x expected replays from mastery goals (stars, par), stated as a
hypothesis.

## 4. Measuring the kill criteria

The kill gate (G4) is the most valuable decision in the lifecycle, and today it is decided
without player data.

- Use the stranger playtest protocol that exists ([docs/mv-4-playtest-protocol.md](../mv-4-playtest-protocol.md)):
  5 players who have never seen the game, recorded.
- Measure at least three things:
  - `first_time_understood_share`: played the core action correctly without help within 30 s;
  - `unprompted_retry_share`: chose to play again after the first fail;
  - median session.
- Record the result into the prototype report fields that today say "NOT MEASURED".
- A G4 `pass` requires measured kill metrics, or a recorded human override stating why.
- Cost: people's time, no paid calls.

## 5. Retention features, by genre

Carried over from the earlier genre matrix. The rule is: no feature without a player problem it
solves. A small arcade game does not get a shop, login rewards or meta-progression by default.

Legend:
- **now**: build in every game of this family.
- **test**: build, then keep only if an experiment supports it.
- **defer**: not until there is evidence.

| Feature | Player problem it solves | Fits | Cost | Events needed | Risk | Home | Verdict |
|---|---|---|---|---|---|---|---|
| Level progression and difficulty curve | "What next?"; mastery | all except idle | in design already | level start/complete/fail | none | core game | **now** (exists) |
| Stars / par medals per level | replay with a reason | puzzle, platformer, racing, levelled arcade | low (uses saves) | level complete with score | small | reusable module | **now** for levelled games (competitors show replay value; measure with E4) |
| Meta-progression (permanent upgrades, prestige) | progress across failed runs | survival, shooter, arcade roguelite, idle breakout | high | upgrade bought | balance | game | **test**: the top breakout title on Poki is an idle/prestige design |
| Cosmetic unlocks with soft currency | identity, collection | arcade, racing, platformer, marble | medium (art) | unlock | art cost, bloat | game | **test**: Sky Balls 3D uses coin-paid skins |
| Achievements | long goals | strategy, simulation, survival | low-medium; no template interface call | achievement unlocked | bloat in short games | template adapter + game | **defer** |
| Leaderboards | competition | arcade, racing, puzzle | medium; Yandex and Y8 offer them, the template does not expose them | score submitted | cheating, empty boards | template adapter | **defer** |
| Daily challenge | return reason | puzzle, arcade, racing | medium (seeded content) | challenge start/complete | blocked for very short sessions by `short_session_no_daily_quest` | reusable module | **test** after D1 data |
| Login reward / streak | return reason | simulation, idle, strategy | low | day claimed | pressure pattern | reusable module | **defer** |
| Shop / economy | spending goal | strategy, simulation, idle, survival | high | currency earn/spend | bloat, balance | game | **defer** |
| Missions / quests | short goals | simulation, strategy, racing | medium | mission complete | bloat | game | **defer** |
| Seasonal events | novelty for returning players | live titles with traffic | high, ongoing | participation | maintenance | live ops | **defer** |
| Local 2-player | play together on one device | arcade, racing, sports | medium | mode chosen | input complexity | game | **test** where the genre supports it (competitors use it) |

**The two validation games:**

| Game | Family | Present | Recommended next (after P0 data) | Not recommended |
|---|---|---|---|---|
| Brick Breaker Worlds | arcade (levelled) | interstitial on Next/Map from the 2nd clear; rewarded Extra Ball on fail | stars per level (E4); near-win offer timing (E1) | shop, login rewards, leaderboards |
| Sky Marble | platformer / racing-like (par timer) | interstitial on the result card; rewarded +20 s on time-over | par medals per course (E4); first-minute trim (E3) | currencies, daily rewards |

**Banned patterns, every genre:**
- energy or lives that block play to force ads;
- streak loss used as pressure;
- pay-to-win;
- fake close buttons;
- overstated reward claims;
- ads during play.

See `core/craft/retention-and-progression.md:164-168`.

## 6. Proposals, in priority order

| ID | Change | Files | Why |
|---|---|---|---|
| D1 | Measure kill metrics at G4 by stranger playtest | `scripts/wgf_develop/report.py`, G4 procedure `core/lifecycle/stages/prototype-review.md` | Kill gate decided on evidence |
| D2 | `title-strategy.differentiation` plus a consistency rule | `core/artifacts/title-strategy.schema.json`, `scripts/wgf_strategy/planner.py`, `core/reference/design-consistency-rules.yaml` | Y8 and Poki originality rules |
| D3 | `portal_benchmark_targets` and a warning rule | `game-design.schema.json`, `scripts/wgf_design/consistency.py`, platform profiles | Content depth against portal bars |
| D4 | Brief commitments cannot be dropped silently: a dropped brief feature needs a recorded `descoped` entry approved at G3 | `scripts/wgf_design/` (`brief_commitments_met` exists; extend to build-time) | BBW endless and SM time trial vanished |
| D5 | A blocking breach routes back to design with the finding, not run end | `core/workflows/new-game.workflow.yaml` (route `descope`) | Today a design failure ends the run |
| D6 | Release tier defaults to the agent author with metered cost | `workspace/config/factory.yaml`, `profiles/autonomous.yaml` | The template authors fail the release tier by design |
| D7 | Strategy thresholds from portal benchmarks, not fixed constants | `planner.py:1243-1280` | D1 0.25-0.35 vs CrazyGames' 10-15% benchmark |

Not proposed:
- An AI "fun" judge. There is no evidence that it predicts player behaviour, and it would add
  paid sessions. Player tests are cheaper and valid.
- One design formula for all genres. Genre models already hold family-specific shape.
