# Tower Merge Rush: replay and return features (spec)

**Status: specification only.** No template code is changed here. Implementation agents build
this in the template's `examples/tower-merge-rush` and its golden port
(`examples/tower-merge-rush/wgf-golden`, PixiJS) after the audio work merges. The numbers
below are starting tuning. They live in one data table (`src/game/tuning.ts` or similar),
never inline, so a playtest can move them without a code change.

Factory side: these features are the `drop-merge` archetype's `build_spec.depth`
(`scripts/wgf_design/archetypes.py` `DEPTH["drop-merge"]`, game-design 1.7.0). Every entry
past the drop ramp and the best score is `post-mvp` there. A golden design does not claim
the port builds them. Craft: `core/craft/retention-and-progression.md`.

## Reviewed against the current port

Port reviewed: `agent-ref-2d-tower-merge` worktree at `8f49d28`
(`examples/tower-merge-rush/src/game/rules.ts`, `wgf-golden/src/**`).

| Area | Exists today | New in this spec |
|---|---|---|
| Board | One row of 7 cells; equal neighbours merge left, pieces slide left, merges cascade | Unchanged. Special pieces sit in cells like levels do |
| Score | Placed level + the new level for each merge | Cascade step and chain multipliers (F1) |
| Ramp | Drop level `min(1 + floor(merges/4), 4)` | Unchanged in Endless. Stages set their own ramp (F5) |
| Lose | All 7 cells full | Unchanged. Power-ups (F3) and the bomb (F2) give ways out |
| Persistence | `best` only (`platform.storage`, namespace `tower-merge-rush`) | Versioned save: coins, power-up charges, stages and stars, themes, achievements, daily streak (F6) |
| Screens | Title, HUD (score, best, next, objective, sound, pause), pause, game over (continue ad, double-score ad, play again) | Title with three modes and a coin chip, stage map, stage intro, stage result, power-up tray, combo chip, themes, achievements, daily card |
| Variety | Piece levels 1–4 arrive by merges; levels above 8 get crowns | Wildcard, bomb and freeze pieces; hammer, undo and shuffle power-ups; 40 stages with 5 goal types; 4 themes |
| Probe | `metrics {score, best, next-piece, merges}`; `entities tower-<col>` (role `target`) | Metrics for combo, coins, stage, stars, drops left and charges; `entities[].kind`; power-up inputs (P1) |
| Ads | Rewarded continue (clears the board, once per run), rewarded double score, interstitial on restart | Rewarded "double coins" on the result card replaces double score, once per run. Continue unchanged. No ad gates a stage or a power-up |
| Audio | Oscillator tones: tap, merge, over, reward | Cues per new event (A1). The audio work supplies the sound set |

None of these exist today: special pieces, power-ups, coins, combo or chain multipliers,
stages, missions, achievements, a daily seed, themes, a stage map.

## Targets

| Measure | Target |
|---|---|
| First session | 4–6 min (design `first_session.target_s` ≥ 180 s): Endless once or twice, then stages 1–3 |
| First new element | Level-2 drops after about 20 s (exists). The first special piece at stage 3, inside the first session |
| First persistent progress | Stage 1 cleared and coins banked inside the first 3 min |
| Retry | ≤ 1 s from the result card (exists) |
| Return hook on the last card | The next stage's goal and stars left to earn, or the coins needed for the next theme |

## Features

Priority **MVP** is the next implementation pass. **Next** comes after it, in order. The ids
in brackets are the archetype's depth ids.

### F1. Cascades and chain multiplier: MVP [`next-cascade`, `cascade`]

- A drop scores its placed level, as today. The k-th merge in that drop's cascade then
  scores `newLevel × k` (k = 1, 2, 3...). This replaces "+ new level per merge".
- **Chain:** a drop that produces at least one merge extends the chain, and a drop with no
  merge resets it. Score multiplier = `1 + 0.25 × (chain − 1)`, capped at ×2.5 (chain 7).
  It multiplies the whole drop's score.
- HUD **combo chip** (top-right, under Next). It shows `×1.5` and so on, is hidden at ×1,
  pops on increase and shatters on reset. A cascade of 3 or more stamps the word "CASCADE!"
  and raises the merge pitch per step (exists for merges).
- Probe metrics: `combo` (current chain length), `multiplier` (number).

### F2. Special pieces: MVP [`wildcard`, `bomb`, `freeze`]

A special piece arrives as "next" instead of a numbered piece.

| Piece | Rule | Endless | Stages |
|---|---|---|---|
| Wildcard ★ | When placed, it takes the level of its higher equal-able neighbour and merges with it at once. With no neighbour it becomes the current drop level | 1 in 15 drops after 16 merges | From stage 3 |
| Bomb 💥 | Placed in an empty cell, it clears that cell and both neighbours. Each cleared piece scores its level × 2. Pieces then slide left and merges resolve. It never ends a run | 1 in 20 drops while ≥ 5 cells are full | From stage 6 |
| Freeze ❄ | The next 5 drops keep the current drop level and the ramp does not advance. A frost overlay shows 5 pips that count down | 1 in 25 drops after 24 merges | From stage 10 |

- Never two specials in a row, and never in the first 8 drops of a run.
- Each special's first appearance shows a one-line rule card (≤ 6 words, 1.5 s, play
  continues): "Wildcard: merges with anything".
- Probe: the `entities` of a special have `role: target` and `kind: wildcard | bomb |
  freeze`. `metrics.next-piece` is the level, or the special's kind as a string.

### F3. Power-ups: MVP [`hammer`]

| Power-up | Effect | Use |
|---|---|---|
| Hammer | Remove one chosen piece (no score); the track slides left and merges resolve | Tap the hammer, then a piece. Tap the hammer again to cancel |
| Undo | Restore the board, score, chain and next piece from before the last drop | Tap. One undo per drop |
| Shuffle | Re-roll the next piece and show the following two for this drop only | Tap |

- Charges are held per type, at most 5 each.
- Endless: start every run with 1 of each, and gain 1 random charge per 10 merges in a run.
- Stages: the stage table grants charges on clear. Coins buy charges (F4).
- The tray sits at bottom-center: 3 buttons ≥ 56 CSS px with a count badge. A button with
  0 charges is shown dimmed with a coin price, and tapping it opens the buy sheet. It is
  never a dead button.
- Keyboard: `H` hammer, `U` undo, `S` shuffle.
- Probe: metrics `powerup-hammer`, `powerup-undo`, `powerup-shuffle`. `inputs` lists each
  usable power-up as an action (`use-hammer`, ...).

### F4. Coins: MVP [`coins`]

- Coins are earned only in play and **never sold**:
  - 1 per merge, +1 per cascade step beyond the first;
  - +10 per stage star the first time it is earned;
  - +5 for a new best in Endless;
  - 25 for completing a daily challenge (F8).
- The result card shows the coins earned, counted up. A rewarded "double coins" (once per
  run) is offered on the result card only. Declining costs nothing.
- Prices: a power-up charge costs 30. Themes (F9) cost 300, 600 and 1200.
- Typical earnings are 25–40 coins per Endless run and 30–60 per stage. The first theme
  arrives in about 8–12 sessions, and all of them in about 25.
- Probe metric: `coins` (the balance).

### F5. Stage map, 40 stages: MVP (stages 1–20), Next (21–40) [`stage-map`, `stage-goal`, `map-complete`]

Every stage is one row from a parameter table, the same 7-column track and one goal. Stars
are counted by drops left at the moment the goal is met:

- ★★★ when ≥ 40 % of the drop limit is left;
- ★★ when ≥ 15 % is left;
- ★ when the goal is met.

There are five goal types:

- `tower L`: make a level-L piece;
- `score S`: reach S points;
- `merges M`: make M merges;
- `clear`: empty the track from a preset start;
- `chain C`: reach chain C.

| Stage | Goal | Drop limit | Start | Ramp cap | Specials | Grants |
|---|---|---|---|---|---|---|
| 1 | tower 4 | 30 | empty | 2 | – | 1 hammer |
| 2 | score 60 | 30 | empty | 3 | – | – |
| 3 | tower 5 | 35 | empty | 3 | wildcard | 1 undo |
| 4 | merges 12 | 30 | empty | 3 | wildcard | – |
| 5 | clear | 20 | `2 1 3 2 1 . .` | 3 | wildcard | 1 shuffle |
| 6 | tower 6 | 40 | empty | 4 | wildcard, bomb | – |
| 7 | chain 4 | 35 | empty | 3 | wildcard, bomb | 1 hammer |
| 8 | score 200 | 40 | empty | 4 | wildcard, bomb | – |
| 9 | clear | 25 | `3 4 . 2 4 1 .` | 4 | bomb | 1 undo |
| 10 | tower 7 | 50 | empty | 4 | all three | 1 of each |
| 11–20 | The cycle repeats: tower, score, merges, clear, chain, each +1 level or +25 % target and +10 % drops | | | | all three | a charge every second stage |
| 21–40 | Next: the same generator with a tighter drop limit (−10 %) and a "banned column" modifier from stage 25 | | | | | |

- Stage n+1 opens when stage n is cleared with ≥ 1 star. Replays keep the most stars.
- Failing a stage means the drop limit was reached or the track filled. The result card
  shows "Try again" and the goal progress. The rewarded continue gives +5 drops, once per
  attempt.
- Every 5th stage is a breather: its targets come from the stage 3 below it (a relief beat).
- Probe metrics: `stage`, `stars` (total), `drops-left`, `goal-progress` (0..1).

### F6. Persistence: MVP

- One versioned save object through `integration.save/load` (`platform.storage`, cloud save
  where the platform offers it), written after every change, not only on exit:

  ```
  { v: 1, best, coins, charges: {hammer, undo, shuffle},
    stages: {"1": 3, "2": 1, ...}, theme, themes: [...], achievements: [...],
    daily: {last: "20261001", streak, freezes} }
  ```

- A missing or corrupt save, or an unknown `v`, starts fresh with `best` migrated from the
  old `"best"` key. It never crashes.
- Acceptance: everything above reads back identically after a reload (`depth.persists`).

### F7. Screens and flow: MVP

- **Title:** wordmark, coin chip (top-right), and three buttons: **Endless** (shows best),
  **Stages** (shows the next stage number), **Daily** (Next; hidden until F8). Themes and
  achievements are icon buttons.
- **Stage map:** a vertical path of 20 nodes per page, with states locked, open and cleared
  (★ count). It scrolls to the next open node, and tapping a node opens the stage intro.
- **Stage intro card:** the goal in words and an icon ("Make a level 6 tower"), the drop
  limit, the star thresholds and the power-up tray. One tap to play.
- **HUD additions:** combo chip, power-up tray, and in stages the goal progress bar and
  drops left (top-center, under the score).
- **Results:**
  - Endless: score, best, coins and the double-coins offer.
  - Stage clear: stars filling one by one, coins, Next stage (primary), Map.
  - Stage fail: goal progress, Try again (primary), Map, continue offer.
  - Every card shows one return line: the next goal, or the coins to the next theme.
- First session flow:
  1. The first launch goes straight into **stage 1**, not Endless, so the player gets a goal
     at once.
  2. After stage 1 is cleared, the map shows stage 2 open and Endless unlocked.

### F8. Daily challenge and streak: Next [`daily-run`]

- Seed = `YYYYMMDD` (UTC) through mulberry32. It fixes the full drop sequence, including
  specials. The goal is a stage-style score target from the seed's table row, with a
  40-drop limit.
- Retries are unlimited and the day's best is kept. The first completion each day pays 25
  coins and extends the streak.
- The streak counts days completed. A missed day uses a freeze if one is held (one is
  granted per 7-day streak, at most 2), otherwise the streak resets. There is no countdown
  pressure and no "your streak will die" message.
- Probe metrics: `daily-best`, `streak`.

### F9. Tower themes: Next [`tower-themes`, `next-theme`]

- Four themes. Each re-skins the 8 piece sprites, the track frame and the backdrop:
  - **Classic** (current, free);
  - **Paper Lantern** (300);
  - **Brass Works** (600);
  - **Night Market** (1200).
- Themes are purely cosmetic and change no rule.
- Selected in a themes sheet that previews level 1–8 pieces.

### F10. Achievements: Next [`achievements`]

There are 12, shown with progress bars and routed to the platform achievement capability
where it exists (local storage otherwise):

1. First Merge
2. Cascade ×3
3. Cascade ×5
4. Level 6
5. Level 8
6. Chain 5
7. Stage 10
8. Stage 20
9. 30 stars
10. 60 stars
11. Use every power-up
12. 7-day daily streak

Each pays 20 coins.

### F11. Two-piece preview: Next

"Next" shows two pieces. This is the archetype's `next-two`. It comes from Shuffle in stages
and is permanent in Endless after stage 15.

## Assets needed

These are for the asset agents: 2D SVG in the current library style (`library/tools/make_art.py`,
palette and shape language of the port). Atlas group `hud` for the icons, `pieces` for
pieces.

| Id | Kind | Size (logical px) | Role | Readability | Priority |
|---|---|---|---|---|---|
| `piece-wildcard` | sprite | 96 | target | A star-faced piece with a rainbow rim, unlike any numbered piece, readable at 48 px | MVP |
| `piece-bomb` | sprite | 96 | target | A round black piece with a lit fuse; reads as "explodes" at 48 px | MVP |
| `piece-freeze` | sprite | 96 | target | An ice-blue crystal piece with frost edges | MVP |
| `vfx-bomb-blast` | vfx | 3 cells wide | vfx | A burst covering exactly the three cleared cells | MVP |
| `vfx-freeze` | vfx | track overlay | vfx | Frost on the track frame with 5 pips | MVP |
| `icon-hammer`, `icon-undo`, `icon-shuffle` | icon | 64 | icon | Distinct silhouettes, readable at 32 px, never told apart by colour alone | MVP |
| `coin` | sprite + icon | 48 / 24 | collectible / icon | A gold coin with an embossed tower | MVP |
| `star-full`, `star-empty` | icon | 48 | icon | Stage stars | MVP |
| `stage-node` | ui | 72 | ui | Locked (padlock), open (pulsing ring), cleared (star count) | MVP |
| `map-backdrop` | background | 720×1280 tile, vertical repeat | background | A quiet path landscape, lower contrast than the nodes | MVP |
| `combo-chip` | ui | 120×48 | ui | Chip frame for ×n | MVP |
| `goal-icons` | icon ×5 | 48 | icon | tower / score / merges / clear / chain | MVP |
| `theme-<id>-piece-1..8`, `theme-<id>-track-frame`, `theme-<id>-backdrop` | sprite / ui / background | as the current set | target / environment / background | Same readability rules as the classic set: the level by numeral and size | Next (3 themes) |
| `badge-<achievement>` ×12 | icon | 64 | icon | One badge each | Next |

Audio cues (A1): `special-arrive`, `wildcard-merge`, `bomb-blast`, `freeze-on`,
`powerup-use`, `coin-tick`, `star-1..3`, `stage-clear`, `stage-fail`, `chain-up`
(the pitch rises per step), `chain-break`. All are short and each has a visual twin.

## Probe and test hooks

Additions to `window.__wgf__.play.snapshot()`. Metric ids are the design's (`[a-z][a-z0-9-]*`).

- `metrics`:
  - existing: `score`, `best`, `next-piece`, `merges`;
  - new: `combo`, `multiplier`, `coins`, `powerup-hammer`, `powerup-undo`,
    `powerup-shuffle`, `stage` (current, 0 in Endless), `stars`, `drops-left`,
    `goal-progress`, `streak`, `mode` (`endless` | `stage` | `daily`).
- `entities[]`: each piece keeps `role: target` and adds `kind` (`piece-<level>`,
  `wildcard`, `bomb`, `freeze`).
- `inputs`: `use-hammer`, `use-undo`, `use-shuffle` when usable, plus map and node taps on
  the map screen.
- `oracle` (`wgf-probe=1`): the column that maximises merges this drop, and with power-ups
  the move that avoids a full track.
- `window.__game` (tests only): `seed(n)`, `setNext(kind|level)`, `startStage(n)`,
  `save()` / `reload()`.

## Acceptance tests

Unit tests are on the pure rules (`rules.ts`, `stages.ts`, `save.ts`). Browser tests drive
real input and read the probe.

1. **Cascade scoring.** Track `3 2 1 . . . .` with a drop of 1 into column 4 cascades
   2→3→4 and ends as `4 . . . . . .`. The score delta is 1 (placed) + 2×1 + 3×2 + 4×3 = 21
   before the multiplier.
2. **Chain.** Three consecutive merging drops give `multiplier` 1.5. A non-merging drop
   resets `combo` to 0 and `multiplier` to 1.
3. **Wildcard.** Track `3 . . .`: a wildcard dropped into column 2 becomes level 3 and merges
   into a 4 in column 1.
4. **Bomb.** Track `2 3 . 4 5 1 2`: a bomb into column 3 empties columns 2–4, scores
   (3+4)×2 = 14, and leaves `2 5 1 2 . . .`. The run never ends on a bomb drop.
5. **Freeze.** After a freeze, `next-piece` stays at its level for 5 drops while `merges`
   rises past a ramp threshold.
6. **No special in the first 8 drops.** Over 1,000 seeded runs, no special appears in drops
   1–8 and none appears twice in a row.
7. **Hammer and undo.** Hammer on column 4 removes the piece and slides left. Undo after
   any drop restores the board, score, chain and next piece byte-for-byte (rules state
   equality).
8. **A 0-charge power-up** opens the buy sheet and is never a disabled dead button. Buying
   deducts 30 coins.
9. **Stage 1.** It can be cleared by the oracle within 30 drops. Clearing with ≥ 12 drops
   left shows 3 stars, pays 30 star coins (plus merge coins) and opens stage 2.
10. **Stage failure.** At drops-left 0 with the goal unmet, the result is a fail. Retry
    restarts the same stage with the same seed.
11. **Persistence (`depth.persists`).** After stage 2 is cleared and coins banked, a reload
    keeps `coins`, `stars`, `stage` progress and charges equal before any input.
12. **Corrupt save.** A garbage save value starts fresh, keeps the legacy `best`, and logs
    no console error.
13. **First session.** The first launch opens stage 1's intro card, and the title is not
    shown first.
14. **Variety (`depth.variety`).** Oracle play reaches the first wildcard in stage 3, and
    level-2 drops within 30 s of Endless.
15. **Return line.** Every result card shows the next goal or the coins to the next theme.
16. **Daily (Next).** Two clients with the same date seed get identical drop sequences. The
    streak increments once per day, and a missed day consumes a freeze.
17. **No dark patterns.** No ad is required to play any stage. Declining every offer never
    blocks progress. No countdown copy.
