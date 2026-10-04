# Quality-consistency tests

> If an intentionally bad game can pass `/new-game`, the quality system is not finished.

`scripts/tests/test_quality_consistency.py` is the Core Acceptance Suite's `QUALITY` category
(`scripts/tests/core_suite.py`, `bin/wgf test-core --only QUALITY`). It runs the shipped
`new-game` workflow through the real engine on six genres. It puts each of ten degradations
into a build that is otherwise release quality, plus one into the store copy, and checks four
things:

- a gate detects the degradation;
- the run stops (no G4, no release);
- the degradation becomes a typed finding;
- triage routes the finding to the specialist that owns it.

It then lets that specialist fix the build, and checks that the run is released only after
the fixed build is measured again. It is workstream WS-13 of
[quality-gap-audit-2026-10.md](quality-gap-audit-2026-10.md). It uses the standard library
only. It starts no agent session and makes no network call. On Windows it runs in about
2.5 minutes.

## What is real and what is a fixture

| Step | In this suite |
|---|---|
| engine, routing, loop budgets, gates G2-G4, quality policy (`params.quality`), pinned references | real (`scripts/wgflib/workflow`) |
| design | the design the **real design step** writes at the release tier. The author (`fixtures/quality/designs.py`) lays the family's seed out as a release: groups of four units, two new elements per group, three structure kinds and a climax arena, four objective kinds, a secondary goal, and difficulty with relief. The design module's own rules (consistency, `content.tier_*` against `quality-benchmark.yaml`) must pass it, or the suite fails |
| init, assets, develop, sdk, review, verify | fixtures (`fixtures/quality/world.py`). The developer builds what the design describes and adds the scenario's degradations. Entered by triage as a specialist (the real `wgf_develop.specialist.resolve`), it removes only the degradations that specialist owns in the scenario's fix map. It records the visit in the prototype-report's `specialist` block and returns `next-specialist` while groups are pending, as the real develop step does |
| playability | the **real step**, with only its bot replaced. It clones nothing, builds nothing and opens no browser. It writes the records and frames `bot.spec.ts` writes, from the build, and the real `analysis.judge` judges them. The records are first-session, act, win, lose, pause, traverse, persist, session and survey, plus `content/units.json` |
| production-quality, content-sufficiency, quality-gate, triage | the **real modules** |
| visual-qa | the **real step** with a command judge (`fixtures/quality/judge.py`). The judge decodes the frames and reports a blocker only for what the pixels show |
| store-listing, listing-validation | placeholders of the build the run verified, with one real check. The listing's facts are grounded in the build as the real step grounds them (`wgf_listing.buildfacts`: tier, store bars, the counts the build's content-sufficiency report measured). Validation runs the real count check (`buildfacts.count_problems`, `grounding.counts.<locale>`). `listing-triage` is the real triage step |
| release | the real release step's refusals (`wgf_release.lineage.evidence_refusals`, with the step's defaults). It drafts a placeholder manifest only when nothing is refused. Packaging is not what this suite tests |

A build is the design as built plus the degradations it carries. Its commit is a digest of
that build. Each develop visit makes a new commit, and the sdk commit sits on top of it.
Degradations go into the production build only. The greybox is the loop drawn in
primitives, before any of the things the degradations remove exist.

## A. Multi-genre consistency

| Genre | Family | Why it is here |
|---|---|---|
| `arcade-2d` | arcade | a 2D arcade game: endless, one verb, a score to beat |
| `racing-3d` | racing | a 3D game with different mechanics: a chase camera, laps, rivals and a clock |
| `puzzle-casual` | puzzle | the simple genre. Its own family bar (20 levels) is higher than the benchmark's (12) |
| `platformer-content` | platformer | content-heavy: levels in worlds, hazards, traversal elements |
| `strategy-content` | strategy | content-heavy in another shape: maps in regions, a gold economy |
| `simulation-systems` | simulation | a management loop whose loss is a resource running out |

For each genre, `test_every_genre_runs_every_gate_and_releases_only_when_all_pass` proves
the following:

- The run records its tier, its class and the benchmark version at the start
  (`params.quality`). It pins the floor, the benchmark and the rubric (`pinned_references`).
- The design is the family's, at the release tier, in the engine's dimension.
- Every required gate runs on the production build and passes it: playability (both
  viewports, nothing skipped), production-quality, visual-qa, content-sufficiency, review,
  sdk-review, verify and the quality gate. Every report describes the same build. The
  development commit, the sdk commit on top of it, and the quality-report's `build` all
  agree.
- The quality gate derives the genre contract. The universal floor, the family's own
  criteria (exactly the ids `quality-floor.yaml` lists under the family) and the 3D criteria
  are all applied, the 3D criteria only to the 3D game. The decision is `release`.
- The content budget is the larger of the benchmark's bar and the family's own:
  `>= 20 units` for the puzzle and `>= 12` for the others.
- Release does not run before G4. It runs only after a person passes G4, with no refusal.
  The run is `release-ready` only after that.

## B. Intentional degradations

Each degradation is the only defect in an otherwise release-quality build of its genre. The
developer never fixes it, so the run spends the loop budget of the gate that keeps failing
and stops BLOCKED. Every case proves the following:

- **Detected**: the gate's newest report is `FAIL` and names the check, finding or
  criterion. The gate detects it on every pass.
- **Blocking**: G4 is never asked and release never runs. `api.quality` reports the run as
  not release-ready. The release step's own refusals, run on the run's evidence, are not
  empty.
- **Typed**: the first triage after the failure normalizes it into quality findings. The
  engine validates the triage-report against its schema. Each finding names the gate report
  as its source and the build that report measured. Each finding has an acceptance that the
  owner must make pass. Each finding is `assigned` in the ledger.
- **Routed**: the finding's owner is the specialist that
  `core/reference/specialist-routing.yaml` assigns. Triage routes that specialist's group.

| # | Degradation | Genre | Detected by | Names | Routed to |
|---|---|---|---|---|---|
| 1 | content removed (the last group never ships) | platformer | content-sufficiency | `content.units_shipped` | level-designer |
| 2 | mechanic variety reduced (every unit built from one element) | puzzle | content-sufficiency | `content.elements`, `content.combinations` | level-designer |
| 2 | the same, in a family whose probe must show a new kind in every unit | arcade | playability | `content.variety` | level-designer |
| 3 | mobile layout broken (targets 30 px, controls over the HUD) | puzzle | production-quality | `mobile:ui.targets`, `mobile:ui.overlap` (desktop passes) | ui |
| 4 | severe visual defect (a black band and a magenta stripe crop the play area) | racing (3D) | visual-qa | `cropped-*` blocker, `score:composition` | environment-artist |
| 4 | the same in 2D | arcade | visual-qa | the same | artist-2d |
| 5 | progression removed (nothing survives a reload, no unlocks) | simulation | playability | `progression.persists` | systems-designer |
| 6 | placeholder assets | arcade | production-quality | `assets.present` | the assets step (route `assets`, straight from the gate) |
| 7 | win and loss broken (play never reaches `won` or `lost`) | strategy | playability | `win.reachable`, `lose.reachable` | gameplay |
| 8 | performance regression (24 fps against 60) | racing | quality-gate | `floor.performance` (technical below its floor) | gameplay |
| 9 | duplicate level (one level ships another's layout) | platformer | content-sufficiency | `content.structure` (2 of 12 repeated, bar 10%) | level-designer |
| 10 | one dimension below the floor (3 sfx against 8) while every other dimension is high | simulation | quality-gate | `floor.sfx`; `failed == ["audio"]`, overall score above 75, decision `not-release` | the assets step, finding owned by audio-designer |
| 11 | store copy claims 20 levels where the build measured 12 (after G4) | platformer | listing-validation | `grounding.counts.en` | listing-triage -> store-listing, finding owned by copywriter |

Case 11 comes after G4, so G4 is asked and passed; what stops is release. Cases 8 and 10
pass every producing gate. Only the quality floor holds them back, and it
does not average a dimension away. In case 6 the gate sends the build straight to the
assets step, as `new-game` routes `production-quality.assets`. Triage then drops the
finding as handed over. The test shows that the gate's report, normalized by triage's own
normalizer, gives a typed finding with route `assets`.

## C. Recovery

| Test | Proves |
|---|---|
| `test_content_restored_by_the_level_designer_is_verified_on_the_new_commit` | The level designer's visit makes a new commit. Every gate measures it again; the failing report is about the old commit and the passing one about the new. In the ledger, the finding moves `detected -> classified -> assigned -> implemented -> verified -> closed`. It is implemented by the specialist's commit and verified by the gate that raised it, re-measuring that commit. Only then are G4 and release reached, and the run is release-ready |
| `test_a_fix_that_regresses_another_gate_is_not_verified` | The ui fix makes the production gate pass but drops content. The next triage keeps the ui finding `implemented` with verdict `regressed`, names the content finding as the regression, and routes the level designer. After that fix, the ui finding is verified and the run is released |
| `test_art_made_again_through_the_assets_step` | The assets step makes the placeholder again, the gates pass the new build, and the run is released |
| `test_store_copy_rewritten_by_the_copywriter_is_validated_again` | listing-triage routes the copywriter's finding to store-listing. The rewritten copy is validated again (`FAIL`, then `PASS`), and only then is the release drafted |
| `test_a_quality_gate_finding_is_closed_only_on_a_newer_build` | The quality-report's own finding lifecycle closes the performance finding on the newer build's commit (`closed_on`). The newer report names the failed build as its `previous` |

The ledger is read by running the real triage step on the run's newest artifacts, outside
the run. See the gaps below for why that is needed.

## D. Anti-gaming

| Test | Proves |
|---|---|
| `test_evidence_about_an_older_commit_is_stale_and_blocks` | After a new build (`develop --force`), G4 asked again stops at the quality floor. The quality gate, shown the new build beside the old build's reports, is BLOCKED (`another build`) and scores nothing. Release refuses |
| `test_a_benchmark_edited_mid_run_does_not_apply_to_it` | The live benchmark is lowered after the run started (near-identical levels allowed at 50%). The running build is still held to the pinned 10%, and its duplicate level blocks the run. A run started after the edit pins the edited file and is held to it |
| `test_a_pinned_reference_edited_in_the_run_blocks` | A bar edited in the run's own pinned copy blocks the step that reads it: the floor blocks the quality gate, the benchmark blocks content-sufficiency. The engine then starts nothing downstream |
| `test_tier_mvp_is_development_never_release` | `strategy.quality_tier: mvp`. Every artifact and the run are `development`, and the run is never release-ready |
| `test_a_downgraded_configuration_is_development` | `sdk.run_tests: false` makes the run `development`, with the reasons recorded |
| `test_a_skipped_check_is_not_green` | The design's meta loop keeps only what a progression step names, which no probe metric reports. Playability skips `progression.persists` and passes. The quality floor fails `floor.content_checks_measured` and `floor.progression_persists`, and the run never reaches G4 |
| `test_an_unmeasured_check_is_not_green` | A probe that names no entity kind fails `probe.valid` on both viewports, because element variety cannot be counted. Unmeasured is never a pass |
| `test_content_deleted_after_qa_is_measured_again` | Content is deleted after every gate passed the build. G4 asked on the old reports stops at the floor, and release will not start. Going on measures the new build, which fails `content.units_shipped` |

## Gaps

Each item below was found by this suite. Where the fix was small and inside the gate's own
module, it was fixed. The others are open, and the suite states them.

| Gap | Status |
|---|---|
| content-sufficiency read the **live** `quality-benchmark.yaml`, not the run's pinned copy. A bar lowered mid-run reached the running build. The quality gate reads that report's checks, so it passed the build too: a duplicate-level build reached G4. | **Fixed** in `scripts/wgf_sufficiency/step.py`: the bars come from the run's pin, and an edited pin is BLOCKED. Tests: `test_a_benchmark_edited_mid_run_does_not_apply_to_it`, `test_a_pinned_reference_edited_in_the_run_blocks`, `test_content_sufficiency.Step` |
| A build with **no gated unlocks** (a flat level list) whose persistence still works passes every gate. `content.progression` counts the design's progression steps when the content data states no `unlocks` (documented in [content-sufficiency-module.md](content-sufficiency-module.md)). | Open. `KnownGaps.test_gap_a_build_without_gated_unlocks_is_not_detected` is an expected failure until a gate measures unlocks on the build |
| The run's **finding ledger** advances only when triage runs. After the last fix passes every gate, nothing sends the build back to triage, so the run reaches G4 and release with that finding still `assigned`. The verification is only visible when triage runs again. | Open. Asserted in `test_content_restored_by_the_level_designer_is_verified_on_the_new_commit`. The fix belongs to the workflow, for example a triage pass, or a ledger update, on the way to G4 |
| A release-tier design whose meta loop persists only `stage-progress` named by a progression step leaves `progression.persists` SKIPPED. Of the six genres here, every seed except arcade and racing is like this. The quality floor then fails a clean build and routes it to develop, which no developer visit can fix. The design step accepts such a design at the release tier. | Open. The suite's release author adds a persisted best score. `test_a_skipped_check_is_not_green` uses the seed's own loop |
| visual-qa reads the **live** `visual-qa-rubric.yaml` (`factory.visualqa.rubric` default), not the copy `new-game` pins. A mid-run rubric edit applies to the running build's visual-qa. The quality gate still holds the visual scores to the pinned floor and benchmark. | Open. The same fix as content-sufficiency's, in `scripts/wgf_visualqa` |

## Running it

```bash
python -m unittest scripts.tests.test_quality_consistency
bin/wgf test-core --only QUALITY
```

To add a degradation:

1. Add a defect to `world.py` `DEFECTS`.
2. Make the build, its records or its frames show it.
3. Add a row to `fixtures/quality/scenarios.json` `degradations`, naming the gate, the report,
   the ids that report must name, and the owner's label.
4. Add a test that calls `degrade(<id>)`.

A degradation that no gate detects is a gap. Write the test that states what should happen,
mark it `expectedFailure`, and list it under Gaps. Never weaken the test to make it pass.
