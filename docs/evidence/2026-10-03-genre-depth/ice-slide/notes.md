# ice-slide (level puzzle) - run notes

Run `new-game-20261002-202507-8c157a`, project overlay `C:\Users\duycu\wgf-runs\genre-depth\project`
(autonomous profile + raised developer budgets), driven from a detached Factory worktree moved
forward between steps as fixes landed. Idea: "A sliding-ice puzzle: a penguin slides until it
hits something; 24 hand-designed levels with keys, doors, crumbling tiles and a 3-star move target".

What happened, in order, and what each stop changed in the Factory (every fix is a commit on
the branch; none relaxed a bar):

1. **Research carried the catalog's own concept** (a colour grid clearing lines of three) instead
   of the idea. Fix: on a genre-model entry the idea is the concept (`concept.core_mechanic` =
   brief, `core_loop` = the family's `loop`). Run restarted.
2. **The design author asked for permission** and left the draft untouched: the profile's
   `Edit(/{draft})` path rule never matches a Windows path. Overlay allows `Edit`; documented.
3. **Repair rounds were spent one check at a time** (experience, then presentation, then the
   content check never reached). Fix: every check runs on every draft and one repair request
   carries every problem; a blocking consistency breach is repairable; three rounds; a resumed
   visit continues from the last draft.
4. **`wall`, `lock`, `exit` descoped the penguin design as foreign mechanics.** Fix: detail terms.
5. **Depth rose 0.08 to 0.16 over six levels and passed "ends higher".** Fix: `min_axis_rise`.
6. Design accepted: 24 authored levels (6 MVP), per-unit objectives, difficulty on the puzzle
   axes, win/lose/mastery, 5 design gaps reported later by the developer (two-star threshold,
   tutorial contradiction, what "Next" does after the last built unit, no literal boards).
7. **The develop guard restored Factory files** when this checkout was edited during a live
   session (lesson: drive runs from a frozen worktree). **A stray `scratch-check.mjs`** the
   host could not delete refused the whole commit: swept now. **Shortened design pin** in
   `units.json` refused: accepted as a prefix; brief shows the full hash. **The brief asked for
   `content.spec.ts`**, which the template never runs: `content.test.ts`.
8. **The bot never traversed a unit**: `progress` was moves-left 12 of target 0 and "done" from
   the first frame. Contract fixed (progress rises to its target), bot fixed.
9. **Judge findings that were the bot's**: a unit cut short by the cap counted as never
   completed; `difficulty.axes_progress` demanded the rise inside the traversed window; variety
   from entity kinds and a time ramp demanded of a puzzle. Fixed as family-vocabulary rules.
10. **Bad play never lost**: the anti-oracle pressed one wall-blocked direction forever; then
    stopped when the dead end offered no oracle; then pressed the new in-play restart. Fixed
    three times (rotate; press on without an oracle; never press an undo).
11. **Nobody told the developer the family's QA obligations** (a reset during play): the brief
    now lists them. **Cancel left orphans on Windows**: job objects.
12. **The developer reported a blocking design gap** (it could not reproduce the loss failure -
    the bot's) and the run took `design-gap` back to design; the repaired design pinned only the
    strategy and the engine refused its lineage: every consumed input is pinned, an accepted
    draft survives. The agent put each level's board into unit parameters: allowed now.
    Init refused its own checkout from the worktree root: origin compared by commit directory.
13. Developer budget exhausted at 14 sessions (US$155, most spent on the bot defects above);
    raised by hand (`--budget-sessions 24`).
14. **Greybox playability PASS** on iteration 8: 18 checks pass on desktop and mobile, including
    `content.units_reachable` (l-01 -> l-05 by the oracle), `content.objective_shown`,
    `content.win_lose_per_unit`, `difficulty.axes_progress`, `lose.reachable`, `restart.works`
    (reset during play), `depth.session_length`; `content.variety` WARNING (layout variety is
    not visible in entity kinds), `progression.persists` SKIPPED (nothing persists at the MVP
    tier by the design).

Operator interventions on the run store, recorded here: the run was reopened once after a
`cancel` (status CANCELLED -> FAILED, backup `state.cancelled-backup.json`), and the visit-2
design draft the step had accepted was seeded as `design/2-last-draft.json` so it was not
authored twice.
