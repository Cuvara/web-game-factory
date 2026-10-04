# Quality gap audit: two validation releases vs an unattended `/new-game` (2026-10-04)

This audit compares two things. The first is what the unattended `new-game` workflow built in
the two-game validation (see [handoff/2026-10-03-two-game-validation.md](handoff/2026-10-03-two-game-validation.md)).
The second is the game a person accepted at G4. Every step between them was a person, a
worker or a delegated agent acting outside the workflow. For each step, this audit says
what the Factory would need in order to detect it, plan it, delegate it and validate it.
It also proposes the measurable bars that close the gap
([`core/reference/quality-benchmark.yaml`](../core/reference/quality-benchmark.yaml)) and
splits the work into independent workstreams.

It is written from the runs' own records only. Nothing was re-run.

| Label | Path |
|---|---|
| **RUN-2D** | `wgf-runs/val-2d/project/.factory/workflows/new-game-20261003-081154-4e5e0a/` |
| **RUN-3D** | `wgf-runs/val-3d/project/.factory/workflows/new-game-20261003-082542-0de9b5/` |
| **REPO-2D** | `wgf-runs/val-2d/games/brick-breaker-worlds` |
| **REPO-3D** | `wgf-runs/val-3d/games/sky-marble` |
| **LEAD** | `wgf-runs/LEAD-STATE.md` |

Event times are UTC and come from the run's `events.jsonl` (EV). Commit SHAs are in the game
repositories.

## Top findings

1. **The workflow builds MVP content only, and nothing measures the release tier.**
   - `units.min_total` is checked on the design (`scripts/wgf_design/content.py:498`). No
     task is planned for it: `content_units()` keeps only `tier: mvp` units
     (`scripts/wgf_techplan/devplan.py:41-53`).
   - `post-mvp` means "production, after G4 passes" (`game-design.schema.json` `$defs.tier`).
     In `new-game`, the step after G4 is the store listing and then release.
   - So a release is the MVP by construction. Both releases were made release-grade by hand:
     2D went from 12 to 32 levels, 3D from 6 straight courses to 12 authored ones.
2. **The genre bars could not fail the builds a person rejected.**
   - The unattended 2D game had 12 levels, one plain brick type, no hazards and no bosses.
     Player audit 1 called it "a demo, not a game" (`val-2d/games/audit-1.md`).
   - That game clears the `arcade` family's `units: {min_mvp: 3, min_total: 6}`
     (`genre-models.yaml:1140`) four times over.
   - No bar counts distinct elements, element combinations, introduction points or
     structural variety on the built content.
   - `content.variety` was a WARNING in both final builds, because the probe reports no
     `entities[].kind`.
3. **Detection was a person's play-through, not a gate.**
   - Every gate passed the 12-level 2D build: playability v12, production-quality v7,
     visual-qa v1 and review v1 (RUN-2D).
   - On 3D, playability passed the 6-corridor build (EV 13:32:38). Production-quality failed
     it on art only.
   - The content gaps came from the workers' player audits (`audit-1.md` in both runs).
     Nothing turned an audit finding into a routed task.
4. **Every routed fix goes to one generalist.**
   - Quality steps route to `develop` or `assets` only, and G4 `iterate` goes to `develop`
     (`core/workflows/new-game.workflow.yaml:181-367`).
   - The improvements that mattered were specialist work that the lead chose by hand:
     - level design: `T-bbw-levels`, and the 3D course rework;
     - UI: `T-bbw-ui`;
     - environment art and lighting: `T-skymarble-environment`, `T-skymarble-dusk`;
     - store copy: the 3D `listing-copy`.
   - No artifact scores the build per discipline, so nothing could choose the specialist.
5. **The content budget is set by the strategy's MVP number and a session cap, not by a
   quality target.**
   - 2D needed a person to raise the budget from 14 to 18 sessions (EV 22:01:31
     `BUDGET_RAISED`). The extra content session alone cost US$18.97.
   - The strategy wrote "not hand-built levels" into a brief that asked for hand-built levels
     (finding 2, `scripts/wgf_strategy/planner.py:777-780`). The 2D strategy v3 holds that
     sentence beside "32 hand-built levels".
6. **Brief features drop silently.** Each brief asked for a mode that did not ship: 2D
   endless, 3D time trial. 2D's design tiered endless `optional`. 3D's design v1 put
   "Three themed worlds" in `out_of_scope` and never listed a time trial. The 3D omission
   surfaced only as a note at G4 #2. Nothing evaluates a candidate feature or accounts for
   one the brief named.
7. **Consistency checks match words, and the repair rounds learn to dodge them.**
   - `design_adds_no_foreign_mechanic` is a bag of words: `concept_terms` at
     `design-consistency-rules.yaml:149-181`, compared in `scripts/wgf_design/consistency.py:102-112`.
   - In A, B and D it flagged paraphrase ("tap hops" read as `jump`), and repair rounds
     renamed words (LEAD findings 3 and 8).
   - 2D design v1 FAILED on it at 08:23:57, and `descope` ends the run (`$fail`).

## 1. What the workflow produced vs what was accepted

| Quantity | 2D unattended (design v2, `41942ab`) | 2D accepted (`96f5cea`, code `8916d19`) | 3D unattended (design v1, `c2d113c`) | 3D accepted (`64ff4c6`, code `2944b3b`) |
|---|---|---|---|---|
| Units | 12 (4 worlds x 3) | 32 (4 x 8) | 6 courses, one group | 12 (3 tiers x 4) |
| Distinct elements | 5 mechanics, 1 brick kind | 12 mechanics; 4 brick kinds + boss core | 5 element types | 13 segment/obstacle kinds |
| Introduction points | not measured | 10 (last at unit 27 of 32) | not measured | not measured |
| Distinct element combinations | not measured | 24 of 32 (0.75) | 4 of 6 (0.67) | 12 of 12 (1.0) |
| Repeated layouts | 0 of 12 | 0 of 32 | 0, but all straight corridors along -z | 0 of 12 |
| Structure kinds | 1 (static grid) | 4 (static, sliding rows, descending field, boss) | 1 (straight corridor) | 5 segment kinds (line, turn, jump, mover, drop) |
| Objective kinds | clear the grid + stars | 4 primary + stars | reach gate + stars + gems | reach gate + stars + gems (one primary) |
| Climax units | none | 4 bosses (8/10/12/14 HP), one shared sprite | none | none |
| Gated unlocks | star gates 5/11/18 | 18/36/54 stars + previous boss | course 5 at 8 stars, course 6 at 11 | course 5 at 8 stars, course 9 at 18 |
| Escalating axes | ball speed, paddle | speed, density, variety, precision | width, hazards | width, mover speed, hazard count, turn severity |
| Designed play | not recorded | 854 s (`content.units_fit_session`) | par 36-58 s per course | par sum 345.5 s |
| Player-facing features | ~8 | ~10 (3 power-ups, stars, best, assist, map, pause, rewarded, en/ru, title showcase) | ~9 | ~11 (steering, checkpoints, result card, tiered select, pause, sound toggle, rewarded continue, interstitials, en/ru, assist, records) |
| Brief features not shipped | endless | endless (design v3 `optional`) | worlds, time trial | time trial (accepted at G4 #2) |
| Visual-qa | v1 PASS; environment, ui_polish, composition 3; 2 majors | v5: 4,4,4,4,4,3,5,5 (mean 4.13); 4 minors | v1 FAIL: 3,4,3,4,5,4,3,5 (mean 3.88) | v10: 4,4,4,4,4,4,5,5 (mean 4.25); 3 minors |
| Production-quality | v7 PASS | v16 PASS (19 checks) | v1 FAIL (skybox placeholder) | v13 PASS (19 checks) |
| Playability | v12 PASS (26 checks) | v23 PASS (38 checks; content.variety, depth.session_length WARNING) | PASS (EV 13:32:38) | v15 PASS (28; 4 SKIPPED content/difficulty, 2 WARNING) |
| Audio | sfx 10, music 3 | sfx 16, music 3 | sfx 9 (roll a one-shot) | sfx 9 (roll looped), music 1 |
| Store package | not reached | 5 screenshots (3 showcase), 20.0 s trailer, en + one-line ru | not reached | 5 screenshots, 20.3 s trailer, en/ru supplied by worker |

Visual-qa scores are listed in rubric order: art_completeness, character_readability,
environment, ui_polish, typography, composition, consistency, no_debug.

The 2D numbers were computed from `public/content/units.json` at `96f5cea`. The 3D numbers
come from `src/game/courses.ts` at `64ff4c6`, and the first build's `src/game/tuning.ts`
`COURSE_TABLE` at `c2d113c`. The 3D content contract never applied: the run
started on `cc9e2ff`, which predates `genre-models.yaml`, so its design v1 (schema 1.8.0)
has no `build_spec.content`, and the content checks SKIPPED to the end.

Cost of the developer sessions the engine counted: 2D 18 sessions, US$62.86; 3D 9 sessions,
US$29.25. Worker, lead, delegated-agent and judge sessions are not recorded anywhere.

## 2. Interventions

Each row below is one intervention that materially changed a final game.

**Categories:** Research, Game design, Content planning, Level design, Gameplay
implementation, Feature implementation, Difficulty/progression, Art/visual polish, Audio,
UI/UX, Production quality, Visual QA, Campaign/store listing, Platform integration, Bug
fixing, Factory defect workaround.

**Assessment columns:** "Det/Plan/Del/Val" says whether the Factory, as it stands on `main`
`8698008`, could **detect** the need, **plan** the work, **delegate** it to the right worker,
and **validate** the result without a person. Each answer is yes, no or partly, with a
reason.

### 2.1 Inventory

| ID | Game | Intervention | Who | Evidence | Category |
|---|---|---|---|---|---|
| I-01 | 2D | Canvas Retry/Pause mirrored as named DOM buttons so the bot can restart | worker, greybox handoff visit 4 | `e976643`; `val-2d/patch-a11y.py`; EV 11:02:07; LEAD 15 | Factory defect workaround, UI/UX |
| I-02 | 2D | Player audit 1: "12 levels, one brick type, no hazards, no bosses ... a demo, not a game" | worker | `val-2d/games/audit-1.md` on `086a793` | Content planning (detection) |
| I-03 | 2D | Content expansion 12 -> 32 levels: armored/steel/explosive bricks, sliding rows, descending field, embers, 4 bosses, `?level=N`, autopilot test | delegated agent `T-bbw-levels` to the lead's spec | `03d6f29`, `29fbe6d`; `val-2d/content-expansion-spec.md` | Content planning, Level design, Feature implementation, Difficulty/progression |
| I-04 | 2D | UI and visual pass: laser-paddle frame, result cards re-laid with 48 px targets, HUD pips, world backdrops, boss objective text, map contrast, a11y names, wordmark, title boss showcase | delegated agent `T-bbw-ui` | `8c1c1e0`, `0db8178`; visual-qa v1 -> v2 environment and ui_polish 3 -> 4 | UI/UX, Art/visual polish, Visual QA |
| I-05 | 2D | Delegated tree applied to the run as a handoff develop visit | worker, develop visit 8 | `55ab02d` (tree equal to `0db8178`); EV 18:12:31 | Factory defect workaround |
| I-06 | 2D | Design revision "option A": `concepts.yaml` edited, resumed from research, design v3 with 32 authored units; needed Factory fixes to revise rather than regenerate | lead + worker; Factory `c35a327`/`cc6982c` | design v3 EV 21:47:03 (`provenance.supersedes` v2); review v3 blockers `out-of-scope-armored-hazards-bosses`, `star-gates-and-level-count-changed`; `T-design-revise.md` | Game design, Content planning |
| I-07 | 2D | Develop budget raised 14 -> 18 sessions for the content rebuild | person | EV 22:01:31 `BUDGET_RAISED`; greybox 5 session US$18.97 | Content planning |
| I-08 | 2D | Probe `play.showcase` stages boss, embers, laser-bolt; `?level` limited to opened levels; e2e seeds an all-cleared save | worker, develop visit 14; Factory `d6e15a7` | `f662c51`; `patch-showcase.py`, `patch-e2e.py`; command developer: "could not fix it without inventing content" (report.json `known_issues`) | Production quality, Factory defect workaround |
| I-09 | 2D | Asset loader moved out of `src/assets`; wordmark lines fitted | worker, develop visit 15 | `e8c2571`; `patch-wordmark.py`; verify v1 `assets.formats` (fixed by #41); visual-qa v3 major `wordmark-clipped-and-crowded` | Factory defect workaround, Visual QA |
| I-10 | 2D | Six visual-qa minors polished (ring pulse, brick count, title demo, coarse-pointer hint, laser ports, phone objective card) | worker, develop visit 16 | `8916d19`; `val-2d/polish-shots/`; G4 #1 waited 04:03:48 and was skipped with `resume --from develop` (no decision record) | Art/visual polish, Visual QA |
| I-11 | 2D | Store screenshots from showcase states (2-3 usable -> 5) | Factory fix | `d67b24b` (`T-listing-showcase.md`); listing-validation v4 PASS | Campaign/store listing |
| I-12 | 2D | Platform readiness: mute through ads, spent reward offer, context menu; per-portal config | delegated agent `T-2d-platforms` (after release, not in `96f5cea`) | `830ef35`, `e7a03fb`, `56f7af1` | Platform integration, Bug fixing |
| I-13 | 3D | Greybox handoffs: session work committed after the netguard fix; probe steer as one 150 ms tap; `bad-play-loses` test | worker, greybox visits 2 and 4 | `7abfea0`, `5d4be2d`; EV 10:46:58, 11:32:12 | Factory defect workaround, Gameplay implementation |
| I-14 | 3D | Player audit 1: straight corridors, loose par (17.1 s vs 36 s), 6 courses with one look, banner up all run, camera ends inside the gate, plain-sphere marble | worker | `val-3d/games/audit-1.md` on `c2d113c` | Level design (detection) |
| I-15 | 3D | Course rework: 12 authored courses on oriented pieces in 3 tiers, with turns, S-bends, hairpins, climbs, drops and narrow bridges; par 1.15-1.25x autopilot; banner fade; finish camera; skybox wired | worker + subagent, develop visit 3 | `3cae2dd` (+3107/-1097); scratch `content-work` `f1bd80b`, `c8f9a8a`, `ab0248d`, `2703152` | Level design, Content planning, Difficulty/progression |
| I-16 | 3D | Production-quality fixes: bumper in view on course 1, gate pillar contrast, icon-only pause | worker, develop visit 4 | `4c35c25`; PQ v4 PASS EV 15:54:36 | Production quality |
| I-17 | 3D | Visual-qa v1 fixes: outcome card, confetti size, banner time, pillars | worker, develop visit 5 | `6e76fb2`; VQA v2 PASS | Visual QA, UI/UX |
| I-18 | 3D | Environment: grass lips, rock undersides, satellite islets, 3 layers of distant islands, instanced clouds, per-tier fog, key/hemisphere/rim rig, PCF shadows | delegated agent `T-skymarble-environment` | `3b58e6f` merged `9059961` | Art/visual polish |
| I-19 | 3D | Dusk grade, gate contrast measured at 4.2-4.4:1, portrait camera 16 m -> 11 m | delegated agent `T-skymarble-dusk` | `ac62f9b`, `22320b0`, `5ed140e`; merged at develop visit 7 (`7e2f23b`); VQA v3 majors `not-dusk-mood`, `black-ground-bar` | Art/visual polish, Visual QA |
| I-20 | 3D | Marble readability: the composed round-body rule (PR #29), its visible-piece follow-up (`7f974ad`), the game-side `hugSwirl()`; G4 ITERATE | worker + lead; G4 by a person | `2944b3b`; `decision-record-prototype-review/v1.json` (18:53:58); VQA character_readability 3 -> 4 | Art/visual polish, Visual QA |
| I-21 | 3D | Part lookups for GLB node names the re-entered assets step renamed | worker | `7e2f23b`; `scratch/patch_alias.py`; LEAD 22 | Factory defect workaround |
| I-22 | 3D | Four docs-only handoff visits to get through verify-worker and review/verify-deadlock defects; one BLOCKED loop limit | worker | `ba4c337`, `36eb839`, `5137eb3`, `64ff4c6`; EV 20:14:40 | Factory defect workaround |
| I-23 | 3D | Store copy replaced: the agent copy said "six floating-island courses" and "the last two courses ask for stars"; en/ru supplied by the worker; ru carries English terms to pass cross-locale grounding | worker | `store-listing/v4.json` vs `v8.json` (`copy.supplied`, `writer.runs: 0`); LEAD 33 | Campaign/store listing |
| I-24 | 3D | Listing fix: required-locale copy, per-platform age rating and categories | Factory fix | `a2ce3d8`, `3ea0f42`; EV 23:17:26 BLOCKED -> 23:27:09 PASS | Campaign/store listing |
| I-25 | 3D | Platform readiness: context menu, Yandex rules 1.6.1.8/1.6.2.7, config proposal, suite; found the template's Yandex rewarded onClose defect | delegated agent `T-3d-platforms` (after release) | `120dda8`, `fd40e03`, `17c2c29`, `433aadb` | Platform integration, Bug fixing |
| I-26 | both | Mid-run Factory fixes the runs merged between steps: netguard (#26), port lock (#28), round body (#29), developer shell (#30), asset loops (#32, #33), `ui.text` (#39), verify workers (`74ef0c4`), judge repair (`bc5de94`), review guard (`ededa2e`), review/verify order (`4aac3a4..91acb76`), handoff report (`abba993`), PQ swept box (#42) | fix workers | handoff doc, "Outcome (2026-10-04)" | Factory defect workaround |

### 2.2 Assessment

Abbreviations used in this table:

- **"no ext"**: no external check reads it.
- **"gen"**: the only route is the generalist `develop` / `assets`.
- **PQ**: production-quality. **VQA**: visual-qa.

| ID | Det | Plan | Del | Val | New gate/check? | New role? | Rule that should have caught it, and why it did not |
|---|---|---|---|---|---|---|---|
| I-01 | yes: `restart.works` failed 3x | no: no route says "make the canvas UI reachable" | partly: gen develop tried 3x and hit `max_visits` | yes: playability v4 | no; fix the bot (LEAD 15 open) | no | `restart.works` reads only a retry action or a DOM role; it cannot see canvas UI |
| I-02 | no | - | - | - | **yes**: content sufficiency on the build | no | `units.min_mvp`/`min_total` (3/6) count units only; there is no element/combination/structure bar and no release tier |
| I-03 | no | partly: `CONTENT-nnn` tasks exist, but only for `tier: mvp` units | no: no level-design brief or role | partly: unit checks traverse 3 units; `content.variety` WARNING | **yes**: release-tier content tasks + sufficiency gate | **level designer** | `devplan.py:41` drops non-MVP units; `content.variety` needs probe `entities[].kind`, which neither build reported |
| I-04 | partly: VQA v1 PASSED with 2 majors and 3 dimensions at 3 | no | partly: gen develop | yes: VQA v2 | **yes**: release tier = no majors, mean >= 4.0 | **UI specialist** brief (the role `ui` exists, but nothing routes to it) | `visual-qa-rubric.yaml` `pass_bar: 3`, `mean_pass_bar: 3.5`, majors allowed: a passing prototype is not a release |
| I-05 | n/a | n/a | no: no way to accept specialist work into a run | yes | no | no | there is no "accept external branch" step; the handoff is the only door |
| I-06 | partly: review v3 found the expansion contradicted design v2 | no: no route from a quality finding back to design | no | yes: design v3 consistency + content rules | **yes**: a `content-gap` route from G4/audit to design that *revises* | game designer exists | re-entry regenerated from the archetype (fixed `cc6982c`); nothing routes a scope increase back to design |
| I-07 | no | no | n/a | n/a | **yes**: budget derived from the planned content | no | the develop budget is a fixed config number (`max_sessions 14`), not a function of tasks x tier |
| I-08 | yes: PQ "fails at rendered" for later-level assets | partly | no: the developer refused to invent content | yes after `d6e15a7` | partly done (showcase); required at release | no | PQ saw only what the bot played (LEAD 21), now fixed by the showcase |
| I-09 | yes | yes | partly | yes | no (defect fixed, #41) | no | `assets.formats` counted code as an asset |
| I-10 | yes: VQA minors | no: minors route nowhere | no | partly: no re-judge of minors | **yes**: release tier caps minors | UI / visual polish | minors never block, so a release keeps them unless a person acts |
| I-11 | yes: listing-validation | yes | yes | yes | no (fixed `d67b24b`) | no | the capture played only level 1 |
| I-12 | no | no | no | partly: platform-validate | **yes**: per-portal behaviour checks (mute in ads, reward close) | platform/SDK role exists | profiles state requirements; nothing exercises them in a browser |
| I-13 | yes | no | partly | yes | no (defects fixed) | no | Windows netguard, port 4173 |
| I-14 | no | - | - | - | **yes**: structure kinds, combination ratio, par calibration | no | content contract not in run; even then `racing`/`arcade` bars (3/8, 3/6) pass 6 corridors on count |
| I-15 | no | no | no | partly: playability unit checks SKIPPED (no content block) | **yes**: sufficiency gate; par from autopilot | **level designer** | design v1 put worlds out of scope; the generator built corridors from a seed (`c2d113c:src/game/course.ts:1-4`) |
| I-16 | yes: PQ v3 | yes | yes: gen develop could, but a worker did it | yes | no | no | - |
| I-17 | yes: VQA v1 | yes | partly | yes | no | no | - |
| I-18 | partly: VQA `environment` 3 (pass) | no | no: assets/develop have no environment brief | partly: VQA | **yes**: release bar environment >= 4 | **environment/lighting artist (3D)** | `environment` route is `assets`, which remakes a design asset; a dressed world is code + composition, not one asset |
| I-19 | yes: VQA v3 majors | no | no | yes: VQA v4, contrast measured | yes (as I-18) | environment/lighting artist | majors routed `assets` + `develop`; neither brief names lighting or camera framing |
| I-20 | partly: VQA major at v5, but VQA PASSED | no | no | yes: VQA v6 | **yes**: release = 0 majors; asset rule `7f974ad` | no | `model.silhouette` refused a ball (fixed #29), then let an invisible band pass (fixed `7f974ad`) |
| I-21 | no | no | no | no | **yes**: assets re-entry keeps untouched models' node names (LEAD 22, open) | no | rebuild scope = every model |
| I-22 | n/a | n/a | n/a | n/a | no (defects fixed) | no | review/verify ordering, verify workers |
| I-23 | no: grounding passed false counts | no | no | no | **yes**: copy counts equal build counts; ru full description | **copywriter** | grounding checks words against the design, not numbers against the build; the design still said 6 courses |
| I-24 | yes | yes | yes | yes | no (fixed) | no | - |
| I-25 | no | no | no | partly | yes (as I-12) | platform/SDK role exists | as I-12 |
| I-26 | yes, mostly | n/a | n/a | n/a | covered by their PRs | no | see the handoff document |

**Pattern.** Defects in the Factory itself were detected and fixed (I-09, I-11, I-13, I-24,
I-26). Gaps in game quality were not:

- **Content and level design** (I-02, I-03, I-14, I-15): nothing detected them.
- **Polish beyond the pass bar** (I-04, I-10, I-18, I-19, I-20): passed the bar, so nothing
  acted.
- **Copy** (I-23): grounded on words, not on the build's numbers.

Every one of these was detected by a person or by an agent playing as a player, planned by
the lead, and delegated by hand.

## 3. What exists vs what is missing

| Need | Exists (v2.7, `main` `8698008`) | Missing |
|---|---|---|
| **Proactive content budget per genre + quality tier** | `genre-models.yaml` `units.min_mvp`/`min_total` per family; strategy commits `concept.content_model.min_units` and the release total (`planner.py:781-787`); `implementation.content_unit_hours: 1.5`, `task_batch: 3` | No quality tier anywhere (`$defs.tier` is mvp/post-mvp/optional = *when*, not *how good*). `min_total` is never planned or built (`devplan.py:41-53`). The develop budget is fixed config and is not derived from `content_unit_hours` x units. No element/group budget. |
| **Content sufficiency gate on ACTUAL content** | Design-side `content.*` rules (22, `scripts/wgf_design/content.py:57-111`); develop `conformance` compares `public/content/units.json` to the design's MVP units; playability traverses `min_units_traversed` (3) units and checks reachability, objective shown, per-unit win/lose, axes rise, `content.variety` (consecutive pairs' entity kinds) | Nothing counts the build's distinct elements, combinations, structural kinds, repeated-layout ratio, objective kinds, obstacle kinds, unlock gates or progression depth. Traversal stops at 3 units. `content.variety` depends on the probe's `entities[].kind`, which both builds lacked (WARNING). A design without `build_spec.content` SKIPs everything (3D). |
| **Variety definition** | `genre-models.yaml` `variety` block (`min_dimensions_changed_between_units`, `max_consecutive_scaling_only_units`, `mechanic_reuse_min_units`, `max_identical_objectives_ratio`) and per-family `variety.dimensions`, judged on the design's `variation_from_previous` labels | *Mechanical* is per unit pair only, with no total. *Structural*: only per-family labels (`layout_motif`, `route_shape`), never counted on the build. *Difficulty*: axes rise/relief only. *Visual*: no per-group look requirement; visual-qa judges frames of the units the bot reached. *Strategic* (distinct viable approaches): absent. *Feature* variety: absent. |
| **Feature planning** | `game-design.features[]` (id, name, tier, description, acceptance, depends_on); tech plan makes one `GAME-nnn` per mvp/post-mvp feature (`devplan.py:153-200`) | No candidate-feature evaluation (player value, cost, risk, brief source, decision). No rule that every brief or strategy feature is built or cut with a reason (endless and time trial dropped silently). Post-mvp features are planned in `M2` but `new-game` never builds `M2` before release. |
| **Strategy boilerplate (finding 2)** | `planner.py:777-780` writes "Difficulty comes from one data-driven ramp, not hand-built levels." whenever `content_model` is None; `test_strategy.py:417-428` pins it | Not reconciled with the brief: 2D strategy v3 carries it beside "32 hand-built levels". The `out_of_scope` list is not reconciled with MVP (F08: unlock planes vs no cosmetics). |
| **Consistency word matching (findings 3/8)** | `concept_terms` + `detail_terms` (`design-consistency-rules.yaml:149-181`); `concept_view` (`consistency.py:102-112`) | Matching is lexical: paraphrase ("tap hops" -> `jump`, "gaps" -> `gate`) is foreign, and renaming a word passes. The concept writer is not given the lexicon (F14). `descope` -> `$fail`, with no route to strategy. |
| **Automatic specialist routing from findings** | Roles `gameplay`, `ui`, `asset`, `game-designer`, `sdk` (`core/roles/roles.yaml`); craft playbooks for level design, UI kit, production art 2D/3D, audio, store listing; VQA dimensions carry `route: assets\|develop` and `rebuild_roles` | Routes are `assets`, `develop`, `design-gap`, `listing` only. A develop visit is one generalist brief whatever the finding. No level-design, environment/lighting or copywriter role. No route from a VQA/PQ/playability finding to design. A G4 `iterate` carries a note, not a typed finding. |
| **Scorecard that drives routing** | Per-step reports (playability, PQ, VQA, review, verify); G4 is shown the content rules and checks | No aggregate artifact scores the build per quality dimension against a tier bar with an owner per dimension. The 2.7 release mentions a "scorecard" only in its evidence folder. Nothing routes on a score. |

## 4. Recommended workstreams

Ordered by dependency. Each is sized for one agent and one PR, with its own tests. Every
`core/` change bumps the file's version and regenerates the runtime
(`scripts/build-plugin-runtime.py`). Changing `scripts/wgflib/` needs a stated reason (Core v1).

| WS | Goal | Files | Depends on |
|---|---|---|---|
| **WS-1 Quality tier and release content budget** | A run states its quality tier (`factory.strategy.quality_tier: mvp\|release`, default `release` for `new-game`). The strategy commits units, groups and elements for that tier from the larger of `genre-models` `min_total` and `quality-benchmark.yaml` `content`. Remove the boilerplate sentence (finding 2): the content direction comes from the brief's words ("hand-built", "procedural") and the content model, and `out_of_scope` is reconciled against the MVP. | `core/artifacts/title-strategy.schema.json` (`concept.content_model.quality_tier`, minor bump), `scripts/wgf_strategy/planner.py:777-787`, `workspace/config/factory.yaml`, `scripts/tests/test_strategy.py`, `docs/factory-lifecycle.md` | none |
| **WS-2 Design states the release tier** | Content rules hold `build_spec.content` to the tier: `content.unit_count_total` against the tier's bar; new design-side rules for elements, introduction points, combination ratio, structure kinds, objective kinds and groups (all values from `quality-benchmark.yaml`). Units gain an optional `structure` kind and `group`. | `core/artifacts/game-design.schema.json` (minor), `scripts/wgf_design/content.py`, `core/reference/genre-models.yaml` (consumer note), `core/craft/content-and-level-design.md`, tests | WS-1 |
| **WS-3 Plan and budget the release content** | `content_units()` plans every unit of the run's tier, not only `mvp`. The develop budget is derived: sessions/cost from `CONTENT-`/`GAME-` task hours, unless config caps it lower, and the cap is reported up front (no mid-run `BUDGET_RAISED`). Post-mvp features of a `release` tier are built before G4. | `scripts/wgf_techplan/devplan.py:41-53`, `scripts/wgf_develop/` (budget), `docs/development-module.md`, `docs/techplan-module.md` | WS-2 |
| **WS-4 Content sufficiency gate on the build** | A deterministic check over `public/content/units.json` and the probe. It counts every `quality-benchmark.yaml` `content`/`progression` quantity on the build, traverses past 3 units (or uses `?unit=` / showcase), and requires probe `entities[].kind` so `content.variety` is measurable. Failure routes `develop` (build short of design) or `design-gap` (design short of tier). | `scripts/wgf_playability/analysis.py` (or a new `content_audit.py` there), `core/artifacts/playability-report.schema.json`, `core/artifacts/shared/play-probe.schema.json` (`entities[].kind` required for authored content), `core/reference/design-depth.yaml` `playability.content`, `docs/playability-module.md` | WS-2 |
| **WS-5 Feature evaluation** | `features[]` gains `source` (brief, strategy, design), `evaluation` {player_value, cost_h, risk, decision, reason}. A consistency rule says every brief/strategy-named feature is either a feature or `decision: cut` with a reason, and G4 is shown the cut list. Fixes the silent drops (endless, time trial). Add `daily_challenge` to `retention.hooks` (F13). | `core/artifacts/game-design.schema.json`, `core/reference/design-consistency-rules.yaml`, `scripts/wgf_design/consistency.py`, `core/craft/game-design` craft, G4 checkpoint display | none |
| **WS-6 Mechanic matching, not word matching** | `concept_terms` become mechanics with synonyms and a "verb + object" form. The concept writer and research agent get the lexicon (F14a). A foreign term must appear as a mechanic id/rule, not anywhere in prose. Repair rounds are compared on mechanics before and after (a rename is no repair). `descope` routes to `strategy` with the measured terms (F14b). | `core/reference/design-consistency-rules.yaml:149-181`, `scripts/wgf_design/consistency.py:102-112`, `core/workflows/new-game.workflow.yaml` (`descope`), `core/craft/research-evidence.md`, `scripts/wgf_discovery` (concept writer prompt) | none |
| **WS-7 Quality scorecard artifact** | A new `quality-scorecard` artifact (schema with `x-wgf`). It scores each dimension against the run's tier: content, level design, difficulty, art, environment, UI, audio, feel, store. Each score names its evidence (playability, PQ, VQA, content audit, listing-validation) and an owner discipline. It is produced after visual-qa (and again before G4), and G4 is decided on it. Release tier: VQA mean >= 4.0, 0 majors, <= 4 minors (`quality-benchmark.yaml` `presentation`). | `core/artifacts/quality-scorecard.schema.json`, a step module `scripts/wgf_scorecard/`, `core/workflows/new-game.workflow.yaml`, `core/lifecycle/gates.yaml` (G4 `required_artifacts`), `core/bindings/adapter-binding.yaml`, `scripts/gen-adapters.sh`, `docs/` | WS-4 (content), WS-5 (features) |
| **WS-8 Specialist routing** | Scorecard routes by discipline. `develop` takes `with: specialist: level-design\|ui\|environment\|audio\|gameplay`, which selects the brief focus, the craft playbooks and the findings it owns. New routes `level-design`, `environment`, `ui` map to `develop` with that `with:`, and a `design` route for scope increases (I-06). Add role charters: level designer, environment/lighting artist (3D), copywriter. G4 `iterate` takes typed findings that route the same way. | `core/roles/roles.yaml` + charters, `core/workflows/new-game.workflow.yaml`, `scripts/wgf_develop/brief.py`, `docs/workflow-engine.md`, adapter binding + `gen-adapters.sh` | WS-7 |
| **WS-9 Store copy grounded in the build** | The copywriter agent is the default writer. Every number the copy states equals the content audit's count (I-23 "six courses"). Controls are derived from the design's `actions` for every input. Every required locale gets a full description; cross-locale grounding checks against the source fact, not shared words (LEAD 33). | `scripts/wgf_listing/`, `core/reference/store-listing.yaml`, `docs/store-listing-module.md` | WS-4 (counts) |
| **WS-10 Assets re-entry scope** | Re-entered assets remakes only the refused items and keeps the GLB node names of untouched models (LEAD 22, I-21). Climax units get distinct art (`distinct_climax_art`). | `scripts/wgf_assets/`, `docs/assets-module.md` | none |
| **WS-11 Platform behaviour checks** | platform-validate exercises per-portal behaviour in a browser: mute through ads, rewarded onClose grants, context menu. This found real bugs in both games after release (I-12, I-25). | `scripts/wgf_publish/` (platform-validate), `core/reference/platforms/*.yaml` checks | none |
| **WS-12 Built-in authors at the release tier** (follow-up from WS-2) | The deterministic design authors (`archetypes.py`, the genre seed in `seed.py` from `genre-models.yaml` `seed` blocks) write MVP-sized content: a few units, two to four mechanics, no declared elements, structures, objective kinds or groups. Since WS-2 they fail the `content.tier_*` rules at `release`, a true finding, so a run without an agent author, the golden runs and research-to-design declare `quality_tier: mvp`. Make the seed author write release-tier content from per-family seed data (elements, structures, objective kinds, groups closed by the family milestone), then move the goldens back to `release`. | `scripts/wgf_design/seed.py`, `scripts/wgf_design/archetypes.py`, `core/reference/genre-models.yaml` `seed`, `scripts/golden/harness.py`, `docs/golden-runs.md` | WS-2 |

Independent now: WS-1, WS-5, WS-6, WS-10, WS-11. The critical path is
WS-1 -> WS-2 -> WS-3 / WS-4 -> WS-7 -> WS-8, then WS-9.

## 5. The benchmark

[`core/reference/quality-benchmark.yaml`](../core/reference/quality-benchmark.yaml) 1.0.0
holds the release-tier bars, which are genre-neutral and name no game. WS-10 wired
`presentation.assets.distinct_climax_art` (the assets step, 1.2.0). WS-4 wired `content` and
`progression` on the built content (the `content-sufficiency` step, 1.4.0,
[content-sufficiency-module.md](content-sufficiency-module.md)). WS-2, WS-7 and WS-9 wire the
rest.

### 5.1 Sources and measurements per bar

Values are in the order: 2D release / 3D release / 2D unattended / 3D unattended.

| Bar | Value | 2D rel | 3D rel | 2D unatt | 3D unatt | Source | Basis |
|---|---|---|---|---|---|---|---|
| `content.units.min_total` | 12 | 32 | 12 | 12 | 6 | units.json `96f5cea`; `courses.ts` `64ff4c6`; design v2; `COURSE_TABLE` `c2d113c` | measured-2 |
| `min_groups` / `min_units_per_group` | 3 / 4 | 4 / 8 | 3 / 4 | 4 / **3** | **1** / 6 | same | measured-2 |
| `min_total_designed_s` | 300 | 854 | 345.5 (par sum) | n/r | ~280 (par 36-58 x 6) | `content.units_fit_session`; par per course | measured-2 |
| `elements.min_distinct` | 8 | 12 | 13 | **5** | **5** | mechanic ids; segment/obstacle tags | measured-2 |
| `min_introduction_points` | 6 | 10 | n/m | n/m | n/m | units.json `introduces` | measured-1 |
| `last_introduction_min_position` | 0.66 | 27/32 = 0.84 | n/m | n/m | n/m | same | measured-1 |
| `min_units_per_element` | 2 | 4 (boss-fight minimum) | n/m | n/m | n/m | units.json | measured-1 |
| `combinations.min_distinct_ratio` | 0.7 | 0.75 | 1.0 | n/m | **0.67** | units.json; `courses.ts` | measured-2 |
| `max_repeated_layout_ratio` | 0.1 | 0 | 0 | 0 | 0 | layouts | measured-2 |
| `min_structure_kinds` | 3 | 4 | 5 | **1** | **1** | hazards/boss; segment kinds | measured-2 |
| `objectives.min_kinds` | 2 | 4 + stars | 1 + stars + gems | 1 + stars | 1 + stars + gems | units.json; `tuning.ts` SCORING | measured-2 |
| `objectives.max_identical_ratio` | 0.5 | 1/32 | **1.0** | n/m | 1.0 | objective strings | measured-1 |
| `difficulty.min_escalating_axes` | 2 | 4 | 4 | 2 | 2 | design v3 axes; `courses.ts` | measured-2 |
| `relief_every_units` | 6 | 7 breathers / 32 | n/m | n/m | n/m | design v3 `purpose` | measured-1 |
| `min_climax_per_group` | 1 | 1 boss per world | **0** | 0 | 0 | units.json | measured-1 |
| `progression.min_gated_unlocks` | 2 | 3 | 2 | 3 | 2 | star gates | measured-2 |
| `per_unit_records_persist`, `min_rating_steps` | true, 3 | yes, 3 stars | yes, 3 stars | yes | yes | `progression.persists`; review README | measured-2 |
| `features.min_player_facing` | 8 | ~10 | ~11 | ~8 | ~9 | review READMEs, design features | measured-2 |
| `max_unaccounted_brief_features` | 0 | 0 (endless `optional`) | 0 after G4 #2 note (time trial) | 0 | **2** (worlds out of scope; time trial absent) | designs; G4 v2 note | measured-2 |
| `visual_qa.min_mean` | 4.0 | 4.13 | 4.25 | n/r (v1) | **3.88** | VQA v5 / v10 / v1 | measured-2 |
| `visual_qa.max_major_findings` | 0 | 0 | 0 | **2** | majors | VQA v5 / v10 / v1 | measured-2 |
| `visual_qa.max_minor_findings` | 4 | 4 | 3 | - | - | same | measured-2 |
| `production_quality.all_checks_pass` | true | v16 | v13 | v7 PASS | **v1 FAIL** | PQ reports | measured-2 |
| `later_unit_assets_judged` | true | showcase | n/m | no | no | `d6e15a7`, `f662c51` | measured-1 |
| `playability.content_checks_skipped` | 0 | 0 | **4** | - | - | playability v23 / v15 | measured-1 |
| `assets.min_sfx` / `min_music_tracks` | 8 / 1 | 16 / 3 | 9 / 1 | 10 / 3 | 9 / 1 | `assets.json` | measured-2 |
| `store_listing.min_screenshots` | 5 | 5 | 5 | 2-3 before `d67b24b` | - | store-listing 4-1 / v8 | measured-2 |
| `trailer_s` | 15-30 | 20.0 | 20.3 | - | - | same | measured-2 |
| `copy_counts_match_build` | true | "one-hit bricks" still in copy | **false** in v4, fixed by hand in v8 | - | - | store-listing v4/v8; review README | measured-1 |
| `full_description_per_required_locale` | true | **ru = objective line** | ru supplied | - | - | same | measured-1 |

In the table:

- **n/m**: not measured in the sources.
- **n/r**: not recorded.
- **Bold**: a value below the bar.

**What the bars do and do not separate.** Unit count alone does not separate the rejected
2D build: 12 units meets `min_total` 12. That build falls below on elements (5 < 8),
structure kinds (1 < 3), units per group (3 < 4) and visual-qa majors. This is the reason
the benchmark counts elements and structure, not only units. The rejected 3D build falls
below on units, groups, elements, combinations, structure kinds, visual-qa mean and
production-quality.

Several bars are `measured-1`: the accepted 3D release does not meet
`objectives.max_identical_ratio`, `min_climax_per_group` and `content_checks_skipped`. The
2D release does not meet `full_description_per_required_locale` or
`copy_counts_match_build`. A person accepted both releases at G4 with those gaps as known
non-blocking items. Wiring these bars as blocking is a decision for the implementing
workstream, not a measurement.

### 5.2 Limits

- **Two titles is not a population.** Both are arcade-family-shaped single-verb games, and
  both are PASS_MOCK: no real device, no real portal, no stranger playtest. The bars are
  floors that a person judged necessary, not evidence of player retention.
- **Element counts depend on how a design names its elements.** 2D counted mechanic ids and
  brick kinds; 3D counted course segment and obstacle tags from code. WS-2 must make
  "element" a declared field (unit `introduces` + `mechanics` + `structure`) so the count
  is mechanical, not interpretive.
- **Feature counts are approximate (~)**, taken from the review READMEs, because neither
  design lists the shipped features completely. 3D's design artifact still describes 6
  courses: it was never revised.
- **Not recorded anywhere:** the cost of the worker, lead and delegated-agent work.
