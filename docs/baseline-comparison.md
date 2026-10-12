# The baseline comparison

A run that adopts an existing game holds every candidate build to the build a person
accepted. `scripts/wgf_playability/baseline.py` reads both builds' recordings - made by the
same bot with the same settings - and reports, per accepted unit and per measured quantity,
what got worse beyond a stated tolerance. It is deterministic and uses no AI judge.

| | |
|---|---|
| Producer | the `playability` step type (both `greybox-playability` and `playability` in `new-game`) |
| Measurement | `scripts/wgf_playability/baseline.py` (`play_settings`, `profile`, `compare`) |
| Reference data | `core/reference/baseline-compare.yaml` (1.0.0), pinned by new-game 18 |
| Report | `playability-report` 1.5.0: the `baseline.*` checks and `baseline_comparison` |
| Check tiers | `core/reference/check-tiers.yaml` 1.4.0, source `baseline-compare` |
| Routing | `core/reference/specialist-routing.yaml` 1.8.0 (`baseline.` prefixes) |
| Quality gate | `core/reference/quality-floor.yaml` 1.3.0 `floor.accepted_baseline` (content, blocker) |
| Assessment | `core/reference/quality-assessment.yaml` 1.1.0 families `accepted-content`, `accepted-on-screen`, `accepted-play`, `accepted-timing` |
| Lesson | L8 (`core/reference/lessons.yaml`) |
| Tests | `scripts/tests/test_baseline_compare.py`; real fixtures in `scripts/tests/fixtures/real/baseline-compare/` |

## Why it exists

The K6 retrospective of the 2026-10-05 validation loops (Brick Breaker Worlds 2D, Sky Marble
3D) found that both loops made their gates pass and made the person-accepted games worse:

- H1: the 2D loop head was judged worse than r1, and no gate compared with the accepted build.
- H4: the 2D paddle, capsules, opener and speed curve changed against r1.
- H6: the 3D courses were cut from 234-440 m to 38-124 m corridors.
- H7: the 3D course 1 was cleared in 5.8 s against a 24 s par.

Every gate was an absolute floor (lesson L8). A smaller, flatter, faster build passed them all.

## Which build is the accepted one

The minimal record already exists: the adopted run's design carries the existing-content floor
(`game-design.existing_content`, [autonomous-runs.md](autonomous-runs.md),
`scripts/wgf_design/existing.py`), counted at one commit:

- the commit a person names in `factory.init.accepted_baseline` (a tag or a sha, never a
  branch) - recorded as `source.baseline`;
- else the commit the adopted checkout shipped before the run (HEAD less this run's own
  commits).

`baseline.accepted_of(design)` takes `existing_content.source.commit` and the floor's
`unit_ids`. A run that adopted nothing reports no `baseline.*` check (NOT_APPLICABLE to the
quality gate). A visit that plays the accepted build itself reports none either
(`baseline_comparison.same_build`).

A person changes accepted content on purpose by recording it in the project's
`workspace/config/factory.yaml` (a path the agents of a run cannot write):

```yaml
factory:
  init:
    accepted_changes:
      - check: baseline.unit_extent   # the check
        unit: w1-l1                   # required for a unit-scoped check ("*" only with a quantity)
        quantity: extent              # default "*": every quantity of the check
        reason: the opener was cut on purpose after the 2026-10-09 playtest
        decided_by: a-person
```

A matching regression - or a matching quantity the candidate no longer reports - is reported
as an `accepted-change` item with the reason and who decided, and does not fail the check. An
entry without a `baseline.*` check, a reason or who decided waives nothing and is listed under
`baseline_comparison.invalid_changes`. So is an entry for a unit-scoped check
(`baseline.UNIT_SCOPED`: `units_kept`, `unit_content`, `unit_extent`, `difficulty_order`,
`unit_kinds`, `clear_time`, `clear_rate`) that names no `unit`, or names `unit: "*"` without the
`quantity` it changes on every unit (e.g. `total.extent`): a check named alone would waive every
accepted unit of it. A change nobody recorded is a `QUALITY REGRESSION`.

## How both builds are measured the same way

When the design names an accepted commit other than the one played:

1. The step builds the bot's settings as always, then `baseline.play_settings` adds every
   accepted unit to the survey (`content-sufficiency.yaml survey`), samples naive play on the
   accepted units (the middle and last beside the opening, as `play-realism.yaml naive.units`
   asks), and plays each naive unit and policy `clear_rate.runs` times.
2. The candidate is played with those settings, as every visit is.
3. The accepted commit is cloned, installed, built and played with **the same settings and the
   same bot** on the comparison's viewports (`baseline-compare.yaml play.projects`: desktop),
   under `<run>/baseline/<commit[:12]>-<sha256(settings + bot)[:12]>/`. A later visit with the
   same bot and settings reuses it (`baseline_comparison.cached`); other settings play it again.
   A play with any recording made on a degraded host is used by its own visit (those timings
   unmeasured) and never kept: the next visit plays the accepted build again, and a kept play
   whose records read degraded is played again too.
4. `baseline.profile` reads each build's records and the content data file it ships, and
   `baseline.compare` reports the checks. Both profiles are kept beside the records and named,
   with their sha256, in `baseline_comparison.profiles`.

The accepted play also feeds play-realism's `naive.clear_rate` when the step has no
`with: accepted_play` of its own: the fall of a clear rate is that check's, against the same
play. An accepted naive recording made on a degraded host is not compared there: a slowed bot
clears less and would hide a real drop, so `naive.clear_rate` is BLOCKED, required,
`environment-degraded`.

An accepted build that cannot be played (install, build or the bot fails) makes every
`baseline.*` check BLOCKED and required (`accepted-not-played`), and the playability step
BLOCKED for a person - never a pass, and not a defect of the candidate to send to develop -
unless a real failure already sends the build back. A recording either build made on a degraded host (every
attempt degraded, `visual-quality.yaml environment`) makes the timing quantities it carries
unmeasured: BLOCKED, never a pass and never a regression - a host-slowed accepted play would
make any candidate look fast. Observed while calibrating: the accepted 3D build's naive play,
made while another build was played on the same machine, degraded on every attempt.

## The checks

Every bar is in `core/reference/baseline-compare.yaml`; the clear-rate band is
`play-realism.yaml clear_rate`'s and the difficulty tolerance `genre-models.yaml
implementation.difficulty_tolerance`'s, read where they are stated.

| Check | Tier | Class | Fails when |
|---|---|---|---|
| `baseline.units_kept` | hard | deterministic | an accepted unit (the accepted content data file's units, else the units its probe reached) is no longer shipped under its id - removed or renamed |
| `baseline.unit_content` | hard | deterministic | an accepted unit's declared layout is not identical (`unit_content.min_similarity` 1.0 on `wgf_design.layouts` sequences: container names dropped, 30.0 is 30), or its declared element set changed |
| `baseline.unit_extent` | quality | deterministic | an accepted unit's extent (a path's centre-line length, a grid's solid cells) or par is below `unit_extent.min_ratio` / `min_par_ratio` (0.9) x the accepted one; or the whole game's total extent or par is - whatever its units are called |
| `baseline.tuning` | hard | deterministic | an accepted tuning value (the data file's `tuning` block, flattened) is gone or changed beyond `tuning.max_relative_change` (0.0) |
| `baseline.difficulty_order` | quality | deterministic (the data's values, else the probe's) | an accepted unit's difficulty value on an axis moved beyond the tolerance (0.05), or a pair of accepted units is in the opposite order on an axis |
| `baseline.unit_kinds` | hard | self-reported | an accepted unit draws other content kinds (the survey's `entities[].kind`) |
| `baseline.clear_time` | quality | heuristic | a unit's fastest naive clear (per policy), or the oracle's clear in the survey, is below `clear_time.min_ratio` (0.6) x the accepted build's - with lower bounds kept: a run that did not clear its unit only says its clear is later still, and a regression is reported only when the candidate's clear is shorter than the bar whatever that unknown is |
| `baseline.clear_rate` | quality | heuristic | naive play clears a unit more often than on the accepted build beyond the band (rise >= `min_drop` 0.15, one-sided two-proportion z >= `min_z` 2.33, both builds >= `min_runs` 6) - the unit got easier; the drop is `naive.clear_rate`'s |
| `baseline.entity_size` | quality | self-reported | the median drawn size of a readable role (player, projectile, goal, target, threat) moved more than `entity_size.max_change` (0.25) on either axis |
| `baseline.responsiveness` | quality | deterministic | play begins (from the page's first byte) later than max(1.5 x, + 1000 ms) the accepted build's; an action the accepted build acknowledged within the window no longer changes `min_ack_fraction` of the frame; or frames per second while the oracle plays fall below 0.6 x |

A measured regression holds the build at every tier (`enforce.fail_required_at: all`), and its
summary starts `QUALITY REGRESSION against the accepted build`. What is not measured is never
a pass, and says why:

| `measured.unmeasured` | Means | Status |
|---|---|---|
| `not-reported` | the **candidate** does not report what the accepted build does - for the whole check (no content data file, no unit reached, no kinds) or for one accepted unit, role or action beside others that were compared: a unit's layout, extent, par or difficulty it no longer declares while still declaring the unit elsewhere is a regression instead; a unit, role or action it no longer reports (a role reported under another name, an action the act test did not press, a policy naive play did not enter, no frame counted) is not reported. The `not_reported` count is in `measured` | held as quality-policy.yaml `skipped_checks` says: a required FAIL at the release tier, a WARNING below - whatever else was compared |
| `accepted-unmeasured` | the **accepted build** does not report it - its probe or data predates the contract (no content data file, no unit link, no entity kinds). No candidate can fix that | WARNING, not held; the assessment reads it INCONCLUSIVE. Name an accepted build that reports it (`factory.init.accepted_baseline`) to compare |
| `accepted-declares-none` | the accepted build ships a content data file with none of this quantity (no tuning block): nothing accepted to keep | WARNING, NOT_APPLICABLE to the quality gate |
| `undetermined` | measured on both builds and no measurement decides (neither cleared the unit within its run) - alone, or beside items that were compared (the summary counts both; `measured.undetermined`) | WARNING, not held - never a PASS |
| `environment-degraded` | a recording read was made on a degraded host | BLOCKED, required: measured again on a quiet host (the step is BLOCKED) |
| `accepted-not-played` | the accepted commit could not be built or played | BLOCKED, required; the step is BLOCKED |

## Findings and routing

Triage reads the checks like every playability check (specialist-routing 1.8.0): `baseline.`
to level design; `units_kept` and `unit_kinds` to content; `difficulty_order` and `clear_rate`
to difficulty; `tuning` and `entity_size` to gameplay; `responsiveness` to the performance
engineer. The quality gate's `floor.accepted_baseline` (content dimension, blocker at mvp and
release) holds the same checks: a quality gate never passes a build its own playability report
found worse than the accepted one.

## Metric table

What each quantity is, how it is measured, and what it cannot justify. The assessment
families in `core/reference/quality-assessment.yaml` restate it by class.

| Quantity | Class | Measured from | Limits, false positives and negatives | Cannot justify |
|---|---|---|---|---|
| Units shipped, by id | deterministic | the content data file's units; else the units the probe reached in the survey, traverse and naive play | an accepted build whose probe reports no unit and that ships no data file has no ids (`accepted-unmeasured`) | that the units play as they did |
| Layout, elements | deterministic | the data file's `layout` per unit and the layout source (`content-sufficiency.yaml layout`), the unit's `elements` | compares what the data declares; a game that ignores its data is gate-gaming review's to find | that the change is worse to a player - only that it is a change nobody recorded |
| Extent, par, totals | deterministic | path length (`realism.layout_length`), grid solid cells (`extent.grid_empty`), `par_keys` | a unit of another layout kind is not compared; cells are not difficulty | that a longer unit is a better one |
| Tuning | deterministic | the data file's `tuning` block | exact by design; a refactor that renames keys without changing feel fails until a person records it | that the feel changed |
| Difficulty values and order | deterministic (data), self-reported (probe) | the data's `difficulty`, else the survey's `metrics.difficulty` | values are the game's declared or reported numbers | that the curve is fair |
| Drawn kinds | self-reported | the survey's entity kinds per unit | the kinds are the game's own words | that the unit looks as it did |
| Drawn role sizes | self-reported | the win test's per-frame entity boxes, median per role | the box is the probe's; a HUD element reported as `goal` changes with the HUD | that the paddle or ball feels as it did |
| Clear time | heuristic | naive play's fastest clear per unit and policy; the survey's oracle clear (12 s cap) | a bot's clear, with lower bounds; only the opening unit is comparable on a build without a unit link | that the unit is as long or as interesting to a player |
| Clear rate (easier) | heuristic | naive play, `clear_rate.runs` runs per unit and policy | six runs detect only large changes; seeded jitter is not a player | that the unit is as fair or as hard to a player |
| Start, acknowledgement, frame rate | deterministic | first-session timing from the page's first byte, the act test's before/after frames, requestAnimationFrame count over the win test | software rendering on the build host, two builds measured minutes apart on one host; no input-to-photon latency is measured | that the game feels as responsive on a player's device |

Nothing here measures fun, feel or whether a change was an improvement. A person decides that,
and records it.

## Calibration

Every bar was held against real measurements made on 2026-10-10 (K7) on this Windows 11
machine, CPU only, while other work shared it: the accepted builds (tag `baseline-r1`: 2D
96f5cea, 3D 64ff4c6) measured twice each with the same settings in two run directories, the
regressed loop heads (2D 68a12b7, 3D 1c6b099) and the current candidates (2D 0db72b6, 3D
43c08e2). The profiles are fixtures (`scripts/tests/fixtures/real/baseline-compare/`, with
their commits, how they were captured and the sha256 of every record), replayed by
`test_baseline_compare.py` `TheRealGames`.

| Quantity, bar | Accepted vs its own repeat | Regressed head vs accepted | Margin |
|---|---|---|---|
| Content, layouts, extents, pars, tuning (exact; extent and par 0.9) | identical (2D; 3D declares none) | 2D: all 32 layouts changed, w1-l1 16 -> 10 bricks (0.625), 15 levels smaller, 45 tuning values gone or changed. 3D against the accepted courses as data: 12 of 12 courses gone, total length 4025 -> 844 m (0.21) | deterministic: the accepted build is identical to itself |
| Clear time (0.6) | 3D opening course held forward 22.86 / 20.65 s (0.90, 1.11) | 3D: 6.18 s (0.27); jittered at most 0.31 | 0.30 above the head, 0.30 below the repeat's worst |
| Clear rate rise (play-realism's band) | 3D steady 5/6 vs 4/6, z -0.67 | 3D jittered 0/6 -> 6/6, z 3.46 | z bar 2.33 |
| Role size (0.25) | 0 (2D), at most 1.6 % (3D) | 2D paddle 0.71 x wide, 1.23 x tall | 0.04 below the head's change |
| Start (max(1.5 x, + 1000 ms), from the first byte) | 510 / 820 ms (2D), 708 / 317 ms (3D) | not slower | 0.6 s on the worst repeat |
| Frame rate (0.6) | 10.6 / 10.0 (2D), 8.5 / 11.0 (3D: 0.77 x against itself) | not slower | 0.17 |

Three bars were changed by the calibration before they were first committed, each recorded
here: the frame-rate bar was 0.8, and the accepted 3D build failed it against itself (0.77);
the start was timed from navigation, and one candidate's start read 2801 ms of which 2301 ms
were the local server's first byte - it is timed from the first byte now (a failing test first,
`test_the_start_is_timed_from_the_page_s_first_byte`); and a value of an accepted unit's layout
outside every list (2D w3-l2 `descend.interval_s` 4.2 -> 4.6 on the candidate) was not
compared - it is now (`test_a_unit_s_own_tuning_changed_fails`). The frame-rate and start bars
are calibrated on noise only: no measured build was slower than its accepted build, so neither
has been shown to catch a real regression.

What could not be measured, and why:

- The accepted 3D build (64ff4c6) ships no content data file and its play probe reports no
  content unit and has no unit link: its courses, layouts, tuning, difficulty and drawn kinds
  cannot be read off it, and only its opening course is played. Those checks are
  `accepted-unmeasured` against it. Its courses as data exist only at c340631 (r1-forward:
  dc73132 reverts to 64ff4c6, e6672e3 moves "r1's twelve course layouts verbatim" to data), and
  the course-length comparison is made against that data - a person who wants it held in a
  run names such a commit in `factory.init.accepted_baseline`.
- The accepted 2D build (96f5cea) has no unit link either (only w1-l1 is entered) and names no
  entity kind: per-unit clear times and drawn kinds are compared on the opening level only, and
  naive play clears no 2D level within its 25 s run on any build - `undetermined`.
- Two recordings degraded on every attempt while two builds were played at once: the 2D
  head's naive play (its clear time and rate are BLOCKED in the fixture) and the 3D head's win
  test (its sizes and frame rate are BLOCKED); an earlier measurement of the accepted 3D build
  degraded its naive play and was set aside, not used.

The current candidates, as measured (not tuned to pass; `test_K7_the_2d_candidate_as_measured`,
`test_K7_the_3d_candidate_as_measured`):

- 2D 0db72b6 (main) against 96f5cea: every accepted level kept with its extent, par and
  difficulty; drawn sizes, clear rates and timings within tolerance. It FAILS
  `baseline.unit_content` on seven levels - layouts of w1-l7, w2-l6, w3-l2, w4-l6, w4-l7 and
  the descent of w3-l1, w3-l2, w3-l7 (e.g. w3-l7 `descend.interval_s` 3.8 -> 4.8) - and
  `baseline.tuning` on `ball-rebound.ball_radius_px` 11 -> 20 and
  `descending-field.min_interval_s` 3.8 -> 4. No person has recorded these changes.
- 3D 43c08e2 (feat/release-content) against 64ff4c6, played: the opening course held forward
  in 19.0 s against 22.86 s (0.83 x), cleared as often, drawn the same size, as responsive -
  PASS, except `baseline.clear_time`: a WARNING, because under jittered input neither build
  cleared the opening course in its 25 s run (undetermined beside the kept steady clear). The
  accepted 3D build against its own repeat reads the same WARNING. Against the accepted courses as data (c340631): all twelve courses, their layouts,
  extents, pars and tuning kept - and `baseline.difficulty_order` FAILS on one item:
  hairpin-rise's declared `difficulty.precision` 0.73 -> 0.89 (beyond the 0.05 tolerance). Its
  `speed` 0.87 -> 0.82 and its precision against switchbacks and the-gauntlet (0.81 each on
  c340631, 0.84 each now: 0.05 apart) moved by exactly the tolerance, which is within it. An
  earlier version of this comparison read those three as regressions - in floating point
  0.87 - 0.82 is 0.050000000000000044 - and reported "two pairs in the opposite order"; the
  difference is now read at the values' own precision
  (`test_a_difficulty_moved_by_exactly_the_tolerance_is_within_it`). The course itself is
  unchanged; 43c08e2's values are computed from the built course
  (`tests/unit/helpers/difficulty.ts`, game commit 742f643), c340631's were stated by hand.

## What it does not claim

- It does not judge frames: a paired frame judgement against the accepted build is the gap L8
  still names.
- It compares only what both builds report. An accepted build that predates the content
  contract (no content data file, no unit link, no entity kinds) can be compared on its opening
  unit's play, its drawn sizes and its timings only; the rest is `accepted-unmeasured`.
- It plays the accepted build on desktop only; mobile layout regressions against it are not
  measured.
- A tolerance is a bar, not taste: a change inside it can still be worse, and a person's
  recorded change can still be wrong.

## Known limitations (independent review of 43c4554)

- **Which commit is "accepted".** Without `factory.init.accepted_baseline` the accepted build
  is the adopted checkout's HEAD less this run's own commits - on a repository an earlier run
  left regressed, that is the earlier run's head, not a build a person accepted at G4.
  `baseline_comparison.by` records which case applied; every K7 run on the validation games
  must set `factory.init.accepted_baseline: baseline-r1`.
- **The accepted 3D build is mostly unmeasured.** 64ff4c6 ships no content data file and its
  probe reports no unit, so `units_kept`, `unit_content`, `unit_extent`, `tuning`,
  `difficulty_order` and `unit_kinds` are `accepted-unmeasured` WARNINGs against it, which
  `floor.accepted_baseline` (required checks only) does not hold. The course cut (H6) is caught
  against r1 only through the opening course's clear time and rate: a cut that kept the first
  course intact passes every held check against r1. Naming c340631 (its courses as data) as
  `accepted_baseline` compares the courses, but c340631 is not a commit a person accepted at
  G4 - that is a person's decision to record, not a default.
- **The whole game's totals count new units.** `total.extent` and `total.par_s` sum every
  declared unit, so a candidate that adds units raises them; each accepted unit's own extent
  and par - including one it no longer declares - is compared on its own and is what holds.
- **A unit the survey could not enter** fails `units_kept` only where the accepted build's
  survey entered it; an accepted build with no unit link (2D 96f5cea) cannot show that.
- **The timing bars rest on two samples per build.** The frame-rate bar (0.6) is 0.17 from the
  accepted 3D build against itself, the start bar 0.6 s from the worst repeat, and neither has
  been shown to catch a real regression; their false-FAIL rate on a shared host is unknown.
  More repeats per build are needed before `baseline.responsiveness` is trusted at release.
- **A `not-reported` item is a required FAIL at release, so chance absences can fail a build.**
  Examples: a role the win test happened not to draw on the candidate, a naive policy cut below
  `min_runs` by the time budget, or an action the act test did not press. Any of these holds the
  candidate even when nothing got worse. The accepted builds against their own repeats show none
  of this, but it has not been measured in a live run; watch it in the first runs.
- `baseline.clear_rate` reads play-realism's `clear_rate.min_drop` as its minimum *rise* (one
  band both ways; reported as `max_rise` in `expected`).
- Waivers (`accepted_changes`) are read from the project's config on every visit; they are not
  snapshotted at run start or pinned by hash, and `decided_by` is free text - weaker than a
  decision-record.
