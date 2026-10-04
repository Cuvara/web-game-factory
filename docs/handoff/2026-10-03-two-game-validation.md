# Two-game validation on Windows (2026-10-03)

From `main` at `cc9e2ff`. This records what a one-day validation run established about the
Factory, every defect it found, which pull request fixes each one, and what is still not
verified. It is written from the run's own records: the lead's state file, the plugin
dogfood findings (F01-F26) and the descriptions of PRs #25, #26 and #28-#39. Nothing here
goes beyond them; where they do not say, this document says so.

**Status: every fix PR listed below was open, not merged, when this was written.** See "Outcome (2026-10-04)" at the end for what was merged and what the runs reached. The plan
in the lead's PR map is: merge #34 first (it turns `main` green), then one integration branch
of `main` plus every other PR, the plugin runtime regenerated once, one CI run, one merge. The
goldens on Linux after that integration have not run yet (see "Not verified").

## What the run was

Two games driven through the full `new-game` workflow by the engine on one Windows host,
started from authored `concepts.yaml` briefs, plus a dogfood of the Claude plugin's
`/new-game` surface:

| Worker | Game / task | Run | Notes |
|---|---|---|---|
| A | 2D brick-breaker, **Brick Breaker Worlds** | `new-game-20261003-081154-4e5e0a` | engine-driven |
| B | 3D marble-roll, **Sky Marble** | `new-game-20261003-082542-0de9b5` | engine-driven (an earlier attempt, `new-game-20261003-081332-f7bb0b`, failed at design) |
| D | Plugin `/new-game` dogfood (plugin 2.6.0 via `--plugin-dir`, Claude Code 2.1.288, auto permission mode, an empty project) | mock `new-game-20261003-085640-5dc4c9`; real `new-game-20261003-085910-1e7ead` | the real run was **cancelled** before G4 (no budget, F26) |

Fix workers (C, E-J and delegated agents) turned findings into the PRs below while the game
runs continued; the game runs merged an integration branch (`integ/val-fixes`) between steps.

- **No G4 was decided** in the lead's record at the time of writing. The final state of runs
  A and B is not in the sources; two delegated tasks on them (Sky Marble 3D environment,
  Brick Breaker Worlds levels) were still active.
- The plugin mock run reached G4 in 37 s and, after a person's decisions (iterate, then pass),
  completed at the drafted release.
- The plugin's real run, after G2 and G3, spent about 4.5 hours and never reached G4. The
  engine recorded US$20.63 of developer cost over 14 sessions. Design, asset and visual
  sessions are on top of that and the Factory does not sum them.
- At 14:34Z a subagent ran `taskkill /IM python.exe`. That killed the drivers of runs A and
  B (both were resumed) and is the reason delegated agents are now told to stop processes
  only by PID.

## Defects found in the engine-driven runs (lead's findings 1-22)

| # | Defect and evidence | Status |
|---|---|---|
| 1 | Research `idea_match` counted one generic word: the marble brief's verb `collect` selected the Endless Runner archetype, and the brief was silently replaced. | PR #25 |
| 2 | `wgf_strategy` always writes "Difficulty comes from one data-driven ramp, not hand-built levels", even when the brief asks for hand-designed levels (A). The plugin run saw the same sentence, plus an unlock-vs-no-cosmetics contradiction (F08). | **open** |
| 3 | `design_adds_no_foreign_mechanic`: the agent author's repair rounds rename words to dodge the check (A). | **open** (see 8) |
| 4 | The installed Claude plugin was stale (0.3.0, 2026-09-22): no `/new-game`, no runtime. The repository plugin is 2.6.0 (F01). | **open**: no PR adds update instructions |
| 5 | The `new-game` surface said the workflow ends at the drafted release and that G5/G6 belong to game CI, which contradicts workflow v7's `publish` group. No plugin surface drove `wgf publish --run` (`gen-adapters.sh:350`; F02). | PR #31 |
| 6 | Shipped defaults cannot carry an off-catalog idea. Research accepts `design_archetype: agent` regardless of `factory.design.author`. The archetype author falls back to `archetypes.select()`, which ignores `rendering: 2d`, so a 2D brief became a 3D arena-dodge and design FAILED (F09). | PR #36 (no `/new-game` preflight warning yet) |
| 7 | The autonomous profile's `Edit(/{draft})`, `Edit(/{out}/**)`, `Edit(/{dir}/**)` rules break on Windows: they render as `/C:\...`, which Claude Code reads as project-relative and denies. The design author "left the draft unchanged"; asset authors failed the same way (F11). | PR #36 |
| 8 | `design_adds_no_foreign_mechanic` flags a paraphrase of the brief ("tap hops" read as `jump`; `gate`). Seen in A, B and D: the check matches words, not mechanics (F14). | **open** |
| 9 | The retention hook enum has `daily_quest` only. The brief's "daily challenge" plus rule `short_session_no_daily_quest` made the design drop the hook (F13). | **open** |
| 10 | `new-game.md` had no `allowed-tools`, so auto mode blocked the surface reading `wgf status`/`logs` as `[Self-Modification]` (F15). | PR #31 (not live-verified, per the PR) |
| 11 | The template's `playwright.config.ts` fixes preview port 4173 with `--strictPort`. Concurrent runs on one host fail smoke/e2e; B's greybox FAILED three times while A's suite ran. | PR #28 |
| 12 | The headless developer gives up after one denied compound Bash command and leaves scratch files (B greybox attempt 2; A greybox visit 2 attempt 2). | PR #30 |
| 12b | An orphan `vite preview` of the same run held port 4173 (A, greybox visit 2). | PR #28 (Windows job object) |
| 12c | The developer quit on denied Bash three more times in D's greybox (`python3`, `netstat`, `sed -i`, `git -C`; F19, F24). | PR #30 |
| 13 | On Windows, Chromium ignores the refusing proxy passed through environment variables (`netguard.enforced()` was False on win32). The template test "makes no insecure requests" failed when the Poki SDK loaded the IMA bridge over `http://` (B). | PR #26 |
| 14 | `main` holds CRLF blobs (`i/crlf`): `design-consistency-rules.yaml`, `wgf_assets/pipeline.py`, `requirements.py`, `wgf_design/consistency.py`, `wgf_playability/bot.spec.ts`, `docs/playability-module.md`, the font `OFL.txt`, and their runtime copies. | partly: PR #34 normalizes `bot.spec.ts` and its module doc; the rest **open** (cleanup PR planned) |
| 15 | The playability bot finds restart only through an action named retry/restart or a DOM button found by role. A canvas-only Retry in a design without a retry action is invisible, and A hit `max_visits=3` BLOCKED. A worked around it game-side by mirroring canvas buttons as named DOM buttons. | **open** in the Factory |
| 16 | `auto_approve` is snapshotted at run start. Copying the autonomous profile mid-run does not auto-approve G3, but the surface said it would (D). | PR #31 (the surface now reports the run's snapshot; the snapshot itself is by design) |
| 17 | The CI 2D golden failed `start.playable` (5679/6326 ms on PR #25, 6380 ms mobile on PR #26), and `main` failed too. Root cause: since 2026-10-01 the bot's title-screen measurement (settle, measureUI, screenshot; 1.1-2.3 s) ran inside the `start.playable` clock. | PR #34; PR #37 adds the playability reports to the CI evidence |
| 18 | `model.primitive` plus `model.silhouette` (`max_dominance 0.6`) refuse a marble player by construction: a ball has one dominant component. Repair prompts turned it into a drum, then into a placeholder (B). | PR #29 |
| 19 | `wgf pause <run>` on a live run appends to `events.jsonl` from a second process, and the driver's tamper guard then FAILS the live step (B, assets). The docs say pause is honoured between steps. | **open** |
| 20 | Blocker: a run started supervised has no develop budget, and copying the autonomous profile mid-run never applies one. D's run spent 14 developer sessions unbounded (F26). | PR #35 |
| 21 | production-quality and playability only see the first level the bot plays. Assets that first appear in later levels "fail at rendered" and cannot be judged (B: bumper, low-wall on course 3/4; goal-gate not probe-reported). | **open** |
| 22 | A re-entered assets step rebuilds untouched 3D models, not only the refused items, and renames their GLB nodes. A game that composes parts by node name breaks at boot (B, twice). | **open** |

Defects fixed by PRs in the lead's PR map that have no number above:

| Defect and evidence | Status |
|---|---|
| 2D asset loop (A): `audio_duration` read "repeat every 0.45 s" as a minimum length; `variants.distinct` counted full-bleed base fills, so every backdrop variant "differed by 0.00" and stayed a placeholder. | PR #32 |
| 3D asset loop (B): the skybox (3D `texture`, role `background`) had no producer; looping `sfx-roll` rendered a 0.5 s one-shot. production-quality routed back to `assets` and nothing was remade. | PR #33 |
| production-quality `ui.text` measured an icon button's never-painted `aria-label` ("'Pause' 1.4:1 < 4.5:1"), which no game change could pass (B). | PR #39 (to integrate after #34: both touch `bot.spec.ts`) |
| Orchestration: workers were started in the coordinator's checkout and made worktrees by hand, so about 20 worktrees had no owner. | PR #38 (operator tooling, `scripts/wgf-delegate.py`; nothing in `core/` or the engine depends on it) |

## Plugin dogfood: the top 10 (`FINDINGS.md`)

| Rank | Finding | Status |
|---|---|---|
| 1 | F26: no develop budget for a run that switched to the autonomous profile (blocker, spend). | PR #35: a command developer in a run with no budget is BLOCKED; a person's `resume` records `BUDGET_ADOPTED` |
| 2 | F19/F24: the developer quits after one denied command, and the step blames conformance/smoke. No code was written in 7 of 14 sessions. | PR #30: a "Your shell" brief section; `permission_stall` fails such an attempt with its cause |
| 3 | F11: on Windows, the autonomous profile's design and 2D/3D authors cannot write. | PR #36 (`wgflib/permpath.py`, `{draft_rule}`/`{out_rule}`/`{dir_rule}`) |
| 4 | F09: shipped defaults plus any off-catalog idea always FAIL at design. | PR #36 (research waits with the fix; no preflight warning yet) |
| 5 | F14 (+F07, F08, F13): design consistency is a word game the research concept never sees; `descope` routes to `$fail`. | **open**. F07 (the research agent sets its own concept's priors), F08 (strategy boilerplate) and F13 (`daily_challenge`) are also open |
| 6 | F02: the surface sends G5/G6 to game CI; no plugin surface reaches `wgf publish --run`. | PR #31 (`/new-game publish <run-id>`, adapter-binding 1.8.0) |
| 7 | F25 + F22 + F18: the run's driver lives in the chat's background-task table. It was reaped under memory pressure; there is no progress while it runs; a `!` decide starts a second stream. | **open**: no detached driver (`--detach`) and no record-only `decide` |
| 8 | F15 + F21: the surface cannot read its own run under auto mode, and re-spends on FAILED runs without saying why. | PR #31 (F15 not live-verified) |
| 9 | F12: `wgf status` reports live runs as `stale` on Windows (`os.kill(pid, 0)` is `CTRL_C_EVENT` there), and `acquire()` can take a live lock. | PR #35 (OpenProcess + GetExitCodeProcess) |
| 10 | F23: fonts are never produced. The design counts 3 font files while the typography names 2 families. | PR #36 |

Next tier, from the same file:

- **F16** (mid-run profile half-applied): reporting fixed by PR #31.
- **F05** (a pasted decide template recorded a G4 with the note `"..."`): the surface lines
  are fixed by PR #31. The engine refusing a placeholder note on G4/G6 is **open**.
- **F10** (`docs/autonomous-runs.md` "Enabling it" assumes a marketplace install): no PR
  names it, so it is treated as **open**.
- **F20** (a resume overwrites earlier attempt logs) and **F17** (local init says
  "Cuvara/... created"): **open**.
- **F03/F04** (the mock autonomy report): no PR names them, so they are treated as **open**.
- **F01** (stale 0.3.0 install): **open**.
- **F06** (a 404 for `claude-sonnet`) came from the user's environment, not the plugin.

## Not verified

- **Goldens on Linux after the integration.** Every PR was tested on Windows against a `main`
  baseline. Each PR names Linux CI as its gate. At 15:50Z, #25, #26, #28 and #30-#33 failed only the
  2D golden that #34 fixes, #29 was green at `448bf30` (a new commit had just been pushed),
  and CI was still running on #34-#39. Before #34, `main` itself was red. The integrated
  `main` has not had `WGF_GOLDEN=1 bin/wgf test-core --strict`.
- **A live plugin rerun.** No `/new-game` run has gone from idea to G4 on the fixed surfaces
  and engine. PR #31 says auto mode classifies even pre-approved calls, so F15 is not
  live-verified.
- **Windows-only pre-existing failures.** Several PRs report failures that also fail on
  `main` under Windows: symlink privilege, POSIX paths, fake Blender, assets_production
  ReEntry, `FileOwnershipInTheBrief` path separators. They were not investigated here.
- **PR #30**: the full `test_develop_module` and `test_core_agents` runs were killed locally
  for low memory. Its CI run is the gate.
- **PR #28**: a developer's own unlocked e2e can still fail against a Factory check that
  already holds the port.
- **Runs A and B**: their outcome after the fixes, and their G4 decisions, are not in the
  sources.

## Outcome (2026-10-04)

Written after both runs reached G6. Sources: the lead's state file, the workers' reports and
the merge commits on `main`.

**Integration.** Every fix PR above (#25, #26, #28-#39) is merged. Later fixes came from the
same runs and were merged as integration batches: `c67fcc9`, `aec02b1`, `f228557`, `5a8adf4`,
`549e0e8`, then #41, #42 (`096f9d7`) and the listing showcase (`d67b24b`). `main` was green
with both goldens on Linux at `f9d789d`, `c67fcc9`, `f228557` and `549e0e8`. The CI result
for `d67b24b` is in its own run.

**Runs.** Both reached G6 (publish-review). Nothing was submitted, and `WGF_PUBLISH_LIVE` was
never set. G4 and G5 were recorded by the lead. The human's approval of each game, and G6,
are still outstanding.

| Run | Game | Release | Evidence class |
|---|---|---|---|
| A `new-game-20261003-081154-4e5e0a` | Brick Breaker Worlds (2D, PixiJS): 32 levels, 4 worlds, 4 bosses | r1 v0.1.0, `96f5cea`, `poki.zip` 6.08 MB | PASS_MOCK |
| B `new-game-20261003-082542-0de9b5` | Sky Marble (3D, three.js) | r1, `64ff4c6`, `poki.zip` 1.72 MB | PASS_MOCK |

### Defects found after the first writing

| # | Defect and evidence | Status |
|---|---|---|
| 21 | (above) Later-level assets could not be judged. | Fixed: the probe's optional `play.showcase` (`d6e15a7`). The bot stages each declared target and production-quality credits it only from pixels in the frame. |
| 23 | `verify` ignored the develop section of the dict configuration a step receives when sizing its e2e workers (B). | `74ef0c4`, `f5616ad` |
| 24 | The visual-qa judge's slightly malformed structured reply failed the step after two attempts. No repair round showed the judge the validation error (B, twice). | `bc5de94` |
| 25 | A review/verify ordering deadlock, and the read-only review guard (B). | `4aac3a4`, `c1be772`, `91acb76`, `ededa2e` |
| 26 | The listing failed Yandex: required-locale copy was missing and there was no per-platform age rating (B). The copy was grounded only on the design, not on the build. | `a2ce3d8`, `3ea0f42` |
| 27 | `assets.formats` treated source code under `src/assets/` as an asset ("unsupported format: src/assets/manifest.ts"). The craft guides' reference port keeps its loader there (A). | #41 |
| 28 | production-quality judged a small fast mover over the box it swept during the ~1 s screenshot. An ember (~22x30) swept 23x230, which diluted its changed share below the bar ("embers: fails at rendered") although the frame plainly drew it (A). | #42: the bot records `own: [w, h]` and the gate slides a window of that size along the box. Bars are unchanged. |
| 29 | The store-listing capture played only the first ~12 s of level 1. The frames differed by 0.3-3.3 % against a 5 % bar, and the title and result states were never reached, so 2 screenshots were usable against CrazyGames' 4 (A). | `d67b24b`: the capture also shoots the probe's showcase states under the same bars. In run A the package reached 5 screenshots. |

### Still open

- 2, 3/8, 9, 19, 22 above.
- Listing copy: the controls line lists touch only (desktop mouse and keys are not stated).
  The `ru` copy from the template writer is the in-game objective line only. A real
  description needs the agent copywriter or copy supplied by a person.
- The real Poki SDK (not the bots' stub) logs "localStorage ... sandboxed" errors from its own
  frame (A). The game keeps working. Run Poki's QA tool before publishing.
- Game-side minors, recorded in each review package: A's four bosses share one drawing, A's
  ball can enter the HUD band in late levels, and A is a portrait column on desktop by design.
- Verification evidence for both games is PASS_MOCK. There are no real-device measurements.
