# Real evidence for the play-realism checks

Size-limited, path-free copies of what the two 2026-10 validation games produced, replayed by
`scripts/tests/test_play_realism.py` against `core/reference/play-realism.yaml`. The sources
are read-only evidence kept outside this repository (the validation runs, the rebase evidence
and the 2026-10-07 investigation harness); nothing here was re-measured or edited by hand
beyond the conversions stated below.

| Game | Accepted at G4 (r1) | r1-forward | Regressed head |
|---|---|---|---|
| 2D brick breaker | 96f5cea | 894b4b8 (collider r20) | 68a12b7 |
| 3D marble | 64ff4c6 | c340631 | 1c6b099 |

| File | What it is | Expected |
|---|---|---|
| `physics-2d-r1-run.json.gz` | the win test's per-frame entity samples (`sampled`), desktop and mobile, of every `playability` visit of the run that ended at 96f5cea (17 visits) | no viewport FAILs `physics.undrawn_collision`; 96f5cea PASSes on both |
| `physics-2d-head-run.json.gz` | the same for the run that ended at 68a12b7 (10 visits) | 8 of 20 viewports FAIL - a ball turning upward 220-248 px short of anything drawn; 68a12b7 FAILs (mobile) |
| `naive-bot-2026-10-05.json` | the playability bot's naive test (the play-realism WIP's bot, desktop, Playwright against each build's `dist/`) on 64ff4c6, 1c6b099 (two unit samples), 96f5cea and 68a12b7. The builds predate the realism fields: that copy of the bot read each build's `falls` metric as `setbacks` and its `par` metric as `content.par_s`. Per-run samples were not kept | 1c6b099 FAILs `naive.pace` and (release) `naive.unit_duration`; 64ff4c6 and 96f5cea PASS |
| `naive-bot-3d-c340631.json`, `naive-bot-3d-1c6b099.json` | THIS branch's bot (`bot.spec.ts` naive test only, desktop, behind the refusing proxy, settings from `PlayabilityStep._naive_settings`) on each build's `dist/` on Windows, 2026-10-07, healthy host; per-run samples dropped (no probe field fills them) | 1c6b099 FAILs `naive.pace` (meadow-roll held forward in 6.83 s, 0.285 x par) and `naive.unit_duration`; c340631 PASSes both (first-roll held forward in 19.1 s); the refused Poki SDK requests are foreign, never counted |
| `naive-harness-3d-c340631.json` | the r1 harness's naive survey (`RunSim` stepped headless at 60 Hz, no browser): every course held forward (`steady`) and five seeded jittered drags (`jitter`), converted to the bot's naive-run shape - `falls` as `setbacks`, `drift_mean_m` over half the course width as `drift_mean_share`, a run that ended `lost` as one loss. The harness ran identically on r1 and r1-forward (identical output) | c340631 PASSes setbacks (4.55 a minute in the opening course), drift (0.633), pace and unit duration |
| `content-3d-c340631.json`, `content-3d-1c6b099.json`, `layouts-3d-1c6b099.json` | `public/content/units.json` of each commit (units trimmed to id, index, tier, parameters, layout; tuning kept) and 1c6b099's layout source | 1c6b099 FAILs `level.geometry` (bends of 0.84 x the width) and `level.unit_length` (all 12 units); c340631 PASSes both (crossing time measured once its top speed is declared) |
| `content-2d-96f5cea.json`, `content-2d-894b4b8.json`, `content-2d-68a12b7.json` | the same for the 2D builds | with the grid declared from each build's own tuning, 894b4b8 FAILs `level.clearance` on w3-l7 and w4-l7 (widest steel-row passage 72 px for a 40 px ball), 96f5cea PASSes (22 px ball) |
| `clear-rates-2d.json` | the 2026-10-07 investigation harness (the game's own simulation, headless, nudged / noisy / casual aim models): per-level clears for 96f5cea (`*-r1`), 894b4b8 (`*-new`) and 894b4b8 at the r1 collider (`full-nudge-new11`), the steel-gap variants, and the thread rates of w4-l7's steel rows by ball radius | 894b4b8 regresses on w3-l2, w3-l7, w4-l6, w4-l7; the r11 control regresses nowhere; variant "w4-l7 E" passes |
