# Retention and progression

**Serves** `build_spec.depth` (meta loop, goal ladder, content schedule, first session, return
hooks), `build_spec.player_goals`, `.progression`, `.rewards`, `.difficulty`,
`.session_flow`, `retention`, `session`, and the strategy's retention criteria.

A core loop that is fun for one minute is a prototype. A game is that loop plus the reasons
to play for ten minutes and to come back tomorrow. On a web portal there is no install, no
icon on a home screen and no notification. A player returns only because something they
care about is waiting, and they decide that on the result card they leave from. This
playbook covers what goes above the run, how it is paced, and how it is measured.

The bars a design is held to are data in `core/reference/design-depth.yaml`. The design step
checks them (`scripts/wgf_design/depth.py`). Everything else here is a default with a reason.

## Three loops

Design all three loops and state each one. Each loop must feed the one above it.

| Loop | Length | The player's question | What it is made of |
|---|---|---|---|
| Moment-to-moment | 1–10 s | "Where does this go?" | The verb, its decision and its feedback (`core-loop-and-difficulty.md`, `game-feel.md`) |
| Session | 30 s – 2 min per run; 3–8 runs | "Can I beat that?" | A run with a goal, escalation, a clear end and a fast retry |
| Meta | Days to weeks | "What's next for me?" | Persistent progress: stages, unlocks, coins and what they buy, missions, achievements |

- **The moment feeds the session.** Every merge, near-miss or pickup moves a number the run
  is judged on.
- **The session feeds the meta.** Every run pays into something that persists, even a run
  that fails: coins earned, mission progress, a milestone marked.
- **The meta feeds the moment.** What the meta unlocks changes how the run plays: a new
  piece type, a ship with a trait, a power-up charge. Pure cosmetics are welcome, but a meta
  made only of cosmetics does not change the decision the player makes every few seconds.

`depth.meta_loop.statement` writes the meta loop as a cycle, the same way `core_loop` is
written: *play a stage -> earn stars and coins -> open the next stage, buy a charge or a
theme -> come back for the next stage*. If it cannot be written as a cycle, it is a list of
features.

A best score is a mastery signal, not a meta loop. It is one number, and most players stop
improving it within a few sessions. `depth.meta_loop.persists` must list at least one thing
beyond a score or a setting (`meta_loop.score_only_kinds`).

## Goal ladder

At every moment the player should see one goal at each of three horizons
(`depth.goal_ladder`):

| Horizon | Reach | Example | Where it is shown |
|---|---|---|---|
| short | 5–30 s | land this cascade; pass the next gate; finish this combo | In play: the HUD, the board itself |
| mid | this run or this session | beat the best; clear the stage goal in 40 drops; reach the next zone | The HUD and the result card |
| long | across sessions | three-star the map; own every ship; finish the mission list | The title screen, the stage map, the garage |

Defaults:

- **The next rung is always visible.** The result card shows the mid goal just missed ("12
  points short of your best") and the next long goal ("2 stars to open stage 9").
- **Overlapping, not sequential.** A mid goal should complete before the player gets bored
  of the short one, and a long goal should advance in every session.
- **Goals the player chooses.** Missions and stage stars let a player pick which goal to
  chase. Only a best score forces everyone to chase the same thing.
- The prototype proves the short and mid horizons (`goal_ladder.mvp_horizons`). The long
  horizon is usually post-mvp. State it anyway, at its honest tier.

## Session-to-session progression

Pick from this catalogue and say why each piece fits the game. One or two systems done well
beat six done thinly.

- **Stages or levels with goals.** The strongest structure for a puzzle or merge game. Each
  stage reuses the same core loop with one changed constraint: a target ("build a level-6
  tower"), a limit ("in 40 drops"), a starting layout or a banned column. Grade with one to
  three stars on a margin the player can see, such as moves left or time left. Show stages
  on a map, so the next one is always one tap away. Size: 20–40 stages for a first release.
  Generate them from a parameter table, never author them one by one
  (`core-loop-and-difficulty.md` § Difficulty).
- **Unlock track.** New pieces, zones, ships or arenas open at milestones the player can see
  coming: "1000 m unlocks Zone 3". Place the first unlock **inside the first session**, by
  minute 3–5. The second should be visible before the first session ends.
- **Missions.** Three active at a time. Each is specific, finishes inside one to three runs,
  and pays something ("pass 30 walls in one run: +40 coins"). Completing one draws the next
  from a list. Mix one easy, one medium and one that needs a different style of play. Never
  write "play N days", which is a login chore wearing a costume.
- **Daily challenge.** One seeded run per calendar day, the same layout for everyone, from
  a date seed (`YYYYMMDD`, UTC). Retries are unlimited and the day's best is kept. It costs
  almost no content and gives a reason to open the game *today*. Pair it with a **streak**
  of days played that survives one missed day (a freeze). A streak that resets to zero after
  one miss teaches the player to quit for good.
- **Achievements.** 12–30 of them, with names, a mix of skill goals ("a five-step cascade")
  and discovery goals ("use every power-up"), shown with progress bars. Route them to the
  platform's achievement capability where it exists (`sdk_touchpoints`), with local storage
  as the fallback.
- **Soft currency, upgrades and cosmetics.** Coins are earned only in play and are never
  sold. Buying them with money turns the game pay-to-win. Coins buy things in three classes:
  - **Consumables** (power-up charges): small, bought often.
  - **Upgrades** (longer shield, one extra hammer): bounded, so skill still decides the run.
    Cap each upgrade's effect at about +30 %, in three to five steps.
  - **Cosmetics** (themes, ships, trails): the long tail.

  Price the first purchase to land in the first or second session, and the most expensive
  item at roughly 15–25 sessions of earning. Write earn rates and prices down as data
  (`mechanics[].parameters`), not prose.
- **Persistence.** Everything above survives a reload. It goes through the platform's
  storage or cloud save capability, never a portal SDK directly. Save a versioned object
  (`{v: 1, best, coins, stages, ...}`) after every change, not only on exit, since tabs get
  killed. A corrupt or missing save is a fresh start, never a crash.
  `build_spec.progression.persistence` lists what is saved.

## Content variety on a schedule

Players read variety as progress. The same board for ten minutes reads as a demo.
`depth.content_schedule` lists every new kind of thing the player meets, and when they meet
it:

- **Kinds:** a new piece level, a special piece (wildcard, bomb, freeze), a power-up (undo,
  shuffle, hammer), a pickup (shield, magnet, boost), an obstacle type (moving wall, gate,
  laser), a zone or biome (palette and obstacle mix), an event (golden piece, bonus wave), a
  modifier (speed tier, tighter limits).
- **The first new thing arrives within the first minute** of a first run
  (`max_first_in_run_s`). After that, one new element every 30–60 s of play inside a run,
  and one per stage or every few runs across sessions.
- **Spread it out** (`min_distinct_introductions`). Content that all arrives at second 0 is a
  menu, not a schedule.
- **Introduce one thing at a time, safely.** A new element's first appearance is easy to
  survive: a laser with a wide gap, a bomb on a nearly empty track. Its rule is shown once,
  in a few words, at the moment it appears.
- **Variety in the MVP** (`min_mvp_items`). Even a prototype shows something arriving, such
  as the drop ramp's new piece levels or the speed tiers. The prototype is judged on whether
  the loop holds up as it changes, not only at its opening.

## Difficulty pacing with relief

`core-loop-and-difficulty.md` sets the ramp. Depth adds rhythm to it:

- **Sawtooth.** Pressure climbs for 20–40 s, then drops after a milestone: a zone border, a
  stage goal reached, a new element introduced. The drop is a **relief beat** of 2–5 s, such
  as a calm stretch of track, a guaranteed safe row or a slower drop. The player gets to
  breathe and notice that they are improving.
- **Never stack a new element on a peak.** Introduce it during a relief beat.
- **Endless runs need a ceiling the best players reach.** Cap speed or density, then vary the
  mix rather than the intensity, so a long run turns into a test of reading.
- **Stage games ramp across stages, not inside one.** Stages 1–3 teach, the middle of the map
  tests, and every fifth stage or so is a breather.

## Near-miss and "one more try", done ethically

The pull of a near-miss is real. Use it to show the player true information, and never to
trick them.

Do:
- Show how close the run came: the distance to the best, the merge one drop away, the gap
  that was 0.2 units wide. A near-miss can score or build a combo, which rewards skilful risk.
- Make a retry cost nothing: one tap and **≤ 1–3 s** (`failure.retry`). Put the next goal on
  the result card.
- End a session on an up: a new best, a stage cleared or an unlock reached is the natural
  stopping point (`depth.first_session.ends_on`).

Never (these are defects, and review rejects them):
- **Fake or rigged near-misses.** Losses the outcome generator manufactures to look close.
  Randomness picks what comes next. It never picks to make the player fail.
- **Energy or lives that block play** behind a wait or an ad. They are hostile to portal
  traffic and to most portal policies.
- **Pay-to-win**, or a premium currency. Ads may speed up the meta (a rewarded "double coins")
  but never gate the core loop or a stage.
- **Rewarded ads presented as anything but an offer.** Continues are once per run. Declining
  costs nothing and is never shamed.
- **FOMO countdowns and streak shaming.** No "your streak dies in 2 h!" pressure, no guilt
  copy, no loot boxes or paid randomized rewards.
- **Hidden odds and misleading progress bars.**

Portal reviews and audiences punish these patterns, and so do players who leave and do not
come back.

## Session length on web portals

Portal players play in short sessions and do not stay out of loyalty. The defaults:

| Measure | Default target | Where it lives |
|---|---|---|
| Time to first play | ≤ 5–10 s | `session.time_to_first_play_s` |
| First reward | ≤ 30 s | `session.time_to_first_reward_s` |
| First new content | ≤ 60 s into the first run | `depth.content_schedule` |
| Run length | 30–120 s | the archetype's run, `session.structure` |
| **First session** | **3–8 min; never < 2 min** (`first_session.min_s`) and never > 15 min | `depth.first_session.target_s` = `session.first_session_seconds` |
| First persistent unlock | inside the first session | `depth.content_schedule`, `.goal_ladder` |
| Runs per session | 3–8 | `session.reward_moments_per_session` |

The first session must show the loop more than once and end on a beat that names a reason
to return.

## Measurable targets

Each target is stated in the design and measured from outside the game. The playability
step's proposed depth checks are in `docs/production-architecture.md` § Design depth.

| Target | Measured as | Default |
|---|---|---|
| First-session length | Median length of a first session (playtest, or the oracle bot) | ≥ `depth.first_session.target_s` |
| Retry rate | Share of runs followed by another within 5 s | ≥ 70 % in a first session |
| Difficulty ramp | Time to loss under fixed poor play falls as the run goes on | Monotonic within a run; relief beats visible |
| Variety seen | New entity kinds or roles seen per minute of play | ≥ 1 per 60 s in the first 3 min |
| Progress persists | The probe's progression metrics after a reload | Equal to before the reload |
| D1 return hook | A reason to return shown on the last result card of a session | Always (`depth.return_hooks`) |
| D1 retention | The strategy's success criterion | The strategy's number |

## Tiers, stated honestly

`build_spec.depth` states the whole design. Each entry's tier says what will actually be
built:

- **mvp:** the prototype builds it and G4 judges it. An MVP entry names its deliverer
  (`delivered_by`), and the deliverer is MVP too. "Persistent stage map" cannot be MVP while
  the stage map feature is post-mvp.
- **post-mvp:** production builds it, after G4. Most meta systems belong here. The prototype
  proves that the core loop is worth wrapping, and production wraps it.
- **optional:** stated and committed to nothing, such as depth the strategy excludes ("Any
  metagame or daily-quest layer"). Record it as optional and name the exclusion. Do not
  delete it, and do not build it anyway.

Under-claiming is fine; over-claiming is a defect. A design that marks its stage map MVP and
ships without one has misled G4.

## Failure modes

- **One loop.** A merge game with no stages, no specials and nothing persisted but a best
  score. It is fun for five minutes and then forgotten.
- **Meta without moment.** Currencies and shops around a loop that is not fun. Fix the loop
  first (`core-loop-and-difficulty.md`).
- **Everything at once.** Every special piece unlocked in the first run, so nothing is left
  to discover.
- **Treadmill.** Progression with no end and no loop. State a terminal or a deliberate loop
  (`scope.progression_terminal`).
- **Dark patterns as retention.** They raise D1 and lower everything after it.
