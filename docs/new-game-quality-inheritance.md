# Every `/new-game` inherits the quality policy

WS-12 of [quality-gap-audit-2026-10.md](quality-gap-audit-2026-10.md). The requirement: every
future `/new-game` starts from the same quality system, and nothing ships below the Factory's
quality floor. This document lists every entry point and resume path, what each one runs,
what it could skip before WS-12, and how that was closed. Paths are `file:line` at the WS-12
commit.

The rules are data: [core/reference/quality-policy.yaml](../core/reference/quality-policy.yaml)
(1.1.0; 1.1.0 added rule 5, `skipped_checks`, below). The engine applies them without naming a step
([scripts/wgflib/workflow/quality.py](../scripts/wgflib/workflow/quality.py), called from
`engine.py`); the test file is
[scripts/tests/test_quality_inheritance.py](../scripts/tests/test_quality_inheritance.py).

## The policy in nine sentences

1. **Snapshot.** A run records, when it starts, its quality tier (`factory.strategy.quality_tier`,
   default `release`), its class (`release` or `development`) and why, and the policy and
   benchmark versions (`quality-benchmark@1.2.0`) in `params.quality`. The snapshot is
   corroborated against `WORKFLOW_STARTED` like `auto_approve` and the timeout windows
   (`integrity.GUARDED_PARAMS`), and strategy and assets read the tier from it, never from a
   configuration changed since (`quality.run_tier`).
2. **Floor.** Before a step at a stage under `floor.enforce_at` (`title:prototype-review` -
   G4 -, `release:draft`, `release:validating`, `release:submitting`) executes, every step
   under `floor.required_steps` that comes before it must be *current*: its latest visit
   succeeded and no step before it has succeeded since. Otherwise the run stops BLOCKED
   with `blocked_reason.kind: quality-floor`, naming each stale or missing check. Every run
   but a `--mock` one is held to it.
3. **Class.** A run is `development` - never reported as a release - when it is a mock run,
   its tier is `mvp`, its workflow lacks a required step, its workflow is not one the
   Factory ships, or its configuration meets a `development_when` condition, at the start or
   at any later resume (recorded as `QUALITY_DOWNGRADED`; a class only goes down). Every
   artifact reference carries the class it was written under (`ArtifactRef.quality`), the
   release-manifest carries it (`evidence.quality`, release-manifest 1.4.0), and a
   `development` run does not execute a `production_only` step (`release:submitting`) while
   the submission would be live (`production_only_when`: `factory.publish.mode: live`); a
   dry-run submit, which publishes nothing, may still be rehearsed.
4. **Report.** `wgf status` (and `--json`, key `quality`) says `release-ready` only for a
   release-class run whose `release:draft` step passed, is current, and met the floor;
   otherwise `development - never a release` or `release class, not release-ready`, with
   the reasons, and the required steps no workflow contains yet.
5. **Preflight.** A new run the configuration cannot take to its tier is refused before it
   starts (a `ConfigError`, exit 2, no run created), with what to change: today a built-in
   design author (`archetype`, `genre-seed` - the shipped default) at the release tier,
   which WS-2's `content.tier_*` rules fail at design after research and strategy have run.
   The fix is an `agent` design author (the autonomous profile's) or tier `mvp` - which makes
   the run development. `wgf where --json` reports it (`quality.refused`), and the plugin's
   `/new-game` stops on it before starting anything.
6. **A planned shortfall waits for a person.** A reversible gate whose evidence names a
   field under gates.yaml `hold_for_person_when` (G3: the tech plan's
   `dev_plan.develop_budget.shortfall`, WS-3) is not auto-approved, not approved on a
   timeout, and not answered by automation: it waits for a person, as G4 does, and `wgf
   status` says why (`Held:`; `pending.held_for_person`, with no timeout eligibility).

7. **No bypass for a small game; missing gates are named** (WS-9, quality-policy 1.3.0). No tier, profile or
   configuration removes a required step: the tier changes a run's class and its bars,
   never the steps it runs, and no step of new-game carries a condition that could skip it.
   Rule 2 holds only the required steps a workflow *contains*, so a run whose workflow lacks
   one (started under an older definition, or a workflow from elsewhere) used to pass that
   gate without a word. Now `quality.missing_gates` names every required step the run's
   workflow lacks that the Factory's shipped definition places before the step about to run;
   the engine hands it to the step (`context.missing_gates`) at every stage the floor holds
   and to the quality gate. A checkpoint puts `MISSING GATES: ...` in front of its prompt,
   never decides automatically (no auto-approval, no timeout approval, no automation
   decision), and records them in the decision's note; the quality-report names them and is
   never a release; the run is recorded development (`QUALITY_DOWNGRADED`, "lacks required
   step(s)"). A resume reads the workflow by id - the current definition - so a resumed run
   meets the gate and the floor (rule 2) holds G4 until it passed.
8. **Independent review** (WS-9, quality-policy 1.3.0). Every path an implementer's change (develop, sdk) can take
   to G4 or release passes every judge `independent_review` lists for it; check-integrity
   holds it on the workflow's graph. See docs/specialist-routing.md "Independent review".
9. **Knowledge** (K2, quality-policy 1.4.0 rule 8, workflow 17, gates 1.7.0). A run records,
   when it starts, the version of each file under the policy's `knowledge`
   (`params.quality.knowledge`: `{"lessons": "lessons@2.0.1", "check-tiers":
   "check-tiers@1.1.0"}`) and the Factory's version and commit (`params.quality.factory`),
   corroborated like the rest of the snapshot and reported by `wgf status`; runs are
   comparable across Factory generations by them. A knowledge file that is missing,
   unreadable, versionless or not shaped as knowledge refuses the run (`ConfigError`, no run
   created). `new-game` pins every file the knowledge is read with - the lessons, the check
   tiers and every source they enumerate, the scope vocabularies (genre models, benchmark
   tiers, floor scorecard, platform profiles) and the policy - and its `knowledge-contract`
   step, after design and before tech-plan, resolves the rules that apply to the title from
   those pinned copies into the run's `knowledge-contract`: each rule's level, its checks
   and the steps that validate them, the regression suite, the genre and platform
   constraints, the exceptions a person granted. A run that cannot make it - knowledge it
   did not pin, a pinned copy edited since, versions that are not the ones it recorded,
   knowledge that breaks its own rules, a blocking or required check no step of its workflow
   produces - is BLOCKED there, unrouted: nothing is planned or built without it. G3 is
   decided on it. A person's exception is granted only by `wgf resume <run> --except` (an
   operator event, refused to automation, never by configuration; docs/workflow-engine.md
   §7). See docs/knowledge-enforcement.md.

Tests: `scripts/tests/test_no_bypass.py`.

**Pinned references.** A run is held to the bars it started under, on every entry point and
every resume. `new-game` lists under `pinned_references` the quality floor, the quality
benchmark and the visual-qa rubric (the quality gate, content-sufficiency, visual-qa), and -
workflow 16 - the bot's viewports and environment bars (`visual-quality.yaml`), play realism
(`play-realism.yaml`), browser QA (`browser-qa.yaml`, with the values it reads from
`visual-quality.yaml` through the same pinned copy) and the regression registry
(`check-tiers.yaml`, `lessons.yaml`), and - workflow 17 - everything the knowledge is read
with (the check sources, genre models, quality policy, platform profiles). The engine copies them when the run starts and records
their digests in the run's params; playability, verify's browser QA and triage read the run's
copies (`scripts/wgflib/workflow/references.py read`). So a run resumed on an updated
Factory gets no new required check and no changed tier: those apply to the next run. A copy
edited after the start BLOCKS the step that reads it; a run started before a file was pinned
reads the live file. Tests: `scripts/tests/test_pinned_quality_references.py`.

`content-sufficiency` (WS-4) and `quality-gate` (WS-7, workflow 10,
[quality-gate-module.md](quality-gate-module.md)) are in the workflow and enforced like every
required step (quality-policy 1.2.0: nothing is `pending`). A required step a later
workstream declares before its workflow has it is listed `pending`: the floor enforces it
from the first definition that adds a step with that id, and until then `wgf status` lists
it as not yet enforced.

## Entry points

ALLOWED = non-production by construction or by an explicit, recorded choice, and reported as
such. BYPASS = a production run could skip or neutralize a check, or be reported as a
release without it. Every BYPASS below is closed; the test that proves it is named.

| # | Entry point | What it runs | What it could skip before WS-12 | Class | Closed by | Test |
|---|---|---|---|---|---|---|
| 1 | `wgf new-game [IDEA]` (`scripts/wgf.py:623` `cmd_run` -> `WorkflowAPI.run`, `api.py:371`) | the whole `new-game` definition from `research`, stops at G4, ends at `release` | nothing in the definition; but a run did not record its tier, so a project config changed mid-run re-tiered strategy and assets, and `wgf status` called any completed run "completed successfully" | BYPASS (reporting) | snapshot at start (`api.py:465`); tier read from the run (`wgf_strategy/step.py`, `wgf_assets/step.py`); `quality` in status | `Snapshot.*`, `ReleaseReady.*` |
| 2 | plugin `/new-game` (`claude-web-game-plugin/commands/new-game.md`) | the same engine through `${CLAUDE_PLUGIN_ROOT}/runtime/scripts/wgf.py new-game|resume|publish`; it accepts only the engine's own flags | as 1 | BYPASS (reporting), as 1 | as 1: the runtime ships the same `quality.py` and policy (`build-plugin-runtime.py`) | as 1 |
| 3 | `wgf new-game --from STEP` (fresh run) | from STEP to the end | gates: refused already (`engine.py:501` `_refuse_gates_skipped_by_from`); `--from strategy` skipped research, and strategy then waits for an opportunity | ALLOWED (cannot proceed) | the floor also requires `research` at G4 | `FloorAtTheGate.test_a_fresh_release_slice_does_not_draft` (the same rule) |
| 4 | `wgf <step\|group>` fresh slice (`wgf release`, `wgf verify`) | only that slice, in a new run | a fresh `wgf release` had no inputs and waited; nothing stopped a slice at a release stage from running on whatever a run held | BYPASS | floor at `release:draft` | `FloorAtTheGate.test_a_fresh_release_slice_does_not_draft` |
| 5 | `wgf <slice> --run ID` (`engine.py:580` `continue_in`) | the slice inside the run, skipping steps already completed | **every non-gate step that had ever succeeded was skipped, even when work before it was redone** - `wgf new-game --run` after a re-plan skipped init..verify and asked G4 again on the old build (the per-platform agent's finding); `wgf prototype-review --run` after `wgf develop --run --force` asked G4 with the old build's reports | BYPASS | a completed step is skipped only while current (`engine.py:779`); the floor at G4 (`engine.py:812`) | `ReplanRunsTheStepsAfterIt.*`, `FloorAtTheGate.test_g4_run_by_name_after_a_new_build_stops_at_the_floor`, `FloorAtTheGate.test_verify_alone_on_a_new_build_does_not_reach_g4`, `test_workflow_engine.Idempotency.test_a_completed_step_whose_upstream_ran_since_is_not_skipped` |
| 6 | `wgf <slice> --run ID --force` | re-executes the slice's completed steps | a forced gate is a new visit, which a decision bound to an earlier visit cannot answer (`engine.py` `_run_once`, decisions per visit): it never marks a gate passed without asking | ALLOWED | - (unchanged) | `ForceAsksAgain.test_forcing_g4_asks_again` |
| 7 | `wgf resume ID [--from STEP]` (`engine.py:219`) | continues at the cursor, or restarts at STEP | upstream gates and stopped steps are refused (`engine.py:458` `_refuse_unmet_upstream`); a non-gate check that was stale (or never re-run after a new build) was not, so `--from verify` or a resume onto G4 could reach G4 or release past it | BYPASS | the floor at every enforced stage | `FloorAtTheGate.*` |
| 8 | `wgf resume` under a newer definition | the run's scope is widened to the new steps (`engine.py:299`) | - | ALLOWED | pending required steps are enforced as soon as the definition has them (`quality.effective`) | `LegacyRuns.test_a_pending_step_the_current_policy_enforces_is_enforced` |
| 9 | `wgf decide ID CHOICE` (`wgf.py:652`) | answers only a run WAITING for a person at its cursor; G4/G6/G7 refuse `automation` (`checkpoint.py:189`) | - | ALLOWED | the floor runs before the checkpoint executes, so a decision cannot pass a gate whose evidence is stale | `FloorAtTheGate.*` |
| 10 | `wgf publish --run ID` | `platform-validate`, G5, G6, `submit` in the drafting run | a run built at tier `mvp`, or under a weakening configuration, could be submitted | BYPASS | floor at `release:validating` / `release:submitting`; `production_only: [release:submitting]` refuses a development run while `factory.publish.mode` is `live` | `DevelopmentNeverRelease.test_a_development_run_is_never_submitted`, `test_a_development_run_may_rehearse_a_dry_run_submit`, `test_a_release_run_reaches_submit` |
| 11 | `factory.checkpoints.auto_approve` / `timeout_auto_approve` | G2, G3 (and G5) approve themselves; applied on resume | never G4, G6, G7: refused at start (`api.py:118` `timeout_windows`) and by the checkpoint; but **a G3 whose tech plan records a planned shortfall (WS-3) was approved by automation**, so nobody read it - the autonomous profile auto-approves G3 | BYPASS (the shortfall) / ALLOWED (the rest) | gates.yaml 1.5.0 `hold_for_person_when` (G3: `dev_plan.develop_budget.shortfall`), read by `checkpoint.hold_for_person` | `PlannedShortfallWaitsForAPerson.*` |
| 11b | shipped config, plain `wgf new-game IDEA` / plugin `/new-game` | research, strategy, then design with the built-in `archetype` author | after WS-2 the design step fails at the release tier, hours into a run | BYPASS-adjacent (a run that cannot meet its tier started anyway) | `preflight` refuses it before any step, naming the fix; `wgf where --json` `quality.refused`; the plugin stops on it | `Preflight.*` |
| 12 | autonomous profile (`workspace/config/profiles/autonomous.yaml`) | auto-approves G2/G3, real developer/reviewer/judge agents, a budget | nothing: it adds agents, weakens no check | ALLOWED | the class conditions would mark it development if it ever did | `test_autonomous_profile` |
| 13 | project config overlay (`config.py:236` `load_config`: the project's `workspace/config/factory.yaml` over the shipped one), and `wgf --config PATH` | every step reads the live config | `release.allow_unreviewed: true`; `visualqa.judge.kind: baseline` (passes with zero compared frames); `visualqa.rubric` (a laxer bar); `develop.checks` subset; `sdk.run_tests: false`, `sdk.typecheck: false`, `sdk.report` (no commit check); `listing.reference`; `strategy.quality_tier: mvp`; any of them set after the start | BYPASS | `development_when` conditions, at start and at every drive (`QUALITY_DOWNGRADED`); the tier from the snapshot | `DevelopmentNeverRelease.*` |
| 14 | `factory.workflow.default` / `wgf --workflow PATH` | a workflow file outside `core/workflows/` | its `with:` blocks can set `reviewer: {kind: none}`, `checks: []`, `required_gates: []`, `required_reports: []`, `required_listing: false`, verify `gameplay.required: []`, or drop a check | BYPASS | `shipped_workflows_only`: such a run is development; a missing required step is a reason too | `DevelopmentNeverRelease.test_a_workflow_the_factory_does_not_ship_is_development` |
| 15 | `wgf new-game --mock` (and every `--mock` slice) | placeholder steps, auto-approved reversible gates | everything (nothing is judged) | ALLOWED | class `development` with reason `a mock run`; the floor does not apply | `MockStaysAllowed.*` |
| 16 | golden runs (`scripts/golden/harness.py`) | the real modules with the replay developer, the rule reviewer and the `baseline` visual-qa judge | - | ALLOWED | development by the `visualqa.judge.kind: baseline` condition; the floor still holds them, and a golden run runs every step | (golden suite, `WGF_GOLDEN=1`) |
| 17 | test fixtures (`scripts/wgflib/workflow/fixtures`, tests building an engine directly) | test workflows | - | ALLOWED | a non-shipped workflow is development; an engine built without a policy holds only runs with a snapshot | `test_workflow_engine`, `test_core_workflow` |
| 18 | a run started before WS-12 (no `params.quality`) | as it was | could never be reported anything | ALLOWED, fail-closed | development (`the run has no quality snapshot`), and held to the current policy's floor; it cannot be submitted live | `LegacyRuns.*` |
| 19 | an edited `state.json` (`params.quality` changed to `release`) | refused | - | ALLOWED (refused) | `integrity.params_problems` | `Snapshot.test_an_edited_class_is_refused` |
| 20 | any new run (K2) | the `knowledge-contract` step after design | a run planned and built with no record of which lessons applied to it, and on live knowledge edited mid-run | BYPASS | the snapshot's `knowledge` and `factory`; unreadable knowledge creates no run; the step BLOCKS without a contract; the contract is resolved from the run's pinned copies only | `test_knowledge_run.*` |
| 21 | a run started before K2 (no `params.quality.knowledge`), resumed | as it was; under workflow 17 its knowledge step runs if it passes design again | - | ALLOWED, advisory | the step makes the contract it can, marked advisory with every problem that would have stopped a new run listed, and is blocked only when no contract can be made at all (no lessons or check tiers can be read) (its compliance is advisory); `knowledge-contract` is not a required step, so no gate is missing. One waiting at G3 waits for the contract (gates 1.7.0), as G4 waited for the quality-report in 1.6.0: `wgf resume <run> --from knowledge-contract` makes it | `test_knowledge_run.OldRuns.*` |
| 22 | `wgf resume ID --except RULE` | records a person's knowledge exception | - | ALLOWED (a person's act) | refused to automation, for a rule that does not apply or never blocks, without a 20-character reason or an expiry within `exceptions.max_days`, with a created_at in the future, for a platform or viewport the run does not have; `approved_by` (the person running the command by name, never a placeholder; mode human) and `created_at` stamped by the grant, never read from the request; `factory.knowledge.exceptions` is reported refused | `test_knowledge_exceptions.*` |

## What each WS gate looks like through this policy

| Gate | Where it runs | Inherited by every run because |
|---|---|---|
| research | `research` step | required step; `--from` past it is a fresh run that the floor stops at G4 |
| design validation, WS-2 design tier rules, WS-5 feature evaluation | `design` step (`wgf_design` consistency, content and features checks; a breach is `descope` -> `$fail`) | required step; a design redone after G3 makes every later step stale; a design author that cannot meet the tier is refused at start (`preflight`) |
| WS-1 quality tier and budget | `strategy` (budget), `assets` (climax bar) | the tier is snapshotted and read from the run; `mvp` is development |
| WS-4 content sufficiency | `content-sufficiency` (after visual-qa) | required: current at G4 and release |
| WS-3 release plan and develop budget | `tech-plan` (`dev_plan.develop_budget`) | a planned shortfall holds G3 for a person (`hold_for_person_when`) |
| playability, production-quality, visual-qa | their steps | required, current at G4 and release; `release` also checks they passed the commit it ships (`wgf_release/lineage.py`) |
| review, sdk-review | `review` steps | required; `reviewer.kind: none` passes the step as `skipped`, and release refuses it unless `release.allow_unreviewed`, which makes the run development |
| regression checks | `verify` | required, current at G4 and release |
| WS-8 specialist iteration (coming) | `develop` with `with: specialist` | routes into `develop`; every check after `develop` becomes stale and runs again |
| WS-7 final quality gate | `quality-gate` | required, current at G4 and release; `release` also checks its quality-report passed the build it ships and pins the newest reports of it (`wgf_release/lineage.py`) |
| K2 knowledge contract | `knowledge-contract` (after design) | every new run records its knowledge versions and makes its contract from its pins or stops; G3 is decided on it. Not yet a required step (rule 1): that is a follow-up once the runs started before it have ended |

## Residual risks (not closed here)

- **A check whose result is weaker than its name** - closed for develop and playability by
  policy rule 5 (`skipped_checks`, quality-policy 1.1.0, read by
  `scripts/wgflib/check_strength.py`; tests in `scripts/tests/test_check_strength.py`,
  `test_develop_module.py`, `test_playability.py`):
  - *develop* (`wgf_develop/checks.py`) used to count a skipped check - a script the
    `package.json` lacks, no browser for the smoke suite - as green. At a tier whose class is
    under `skipped_checks.not_passed_at` (`release`, the run's `params.quality.tier`, else the
    tier the brief was built for) the skip stays `skipped` in `checks.json` but is `required`
    and `blocking`: the build is not green, nothing is committed, and the next attempt's
    brief carries a finding naming the missing script or tool. At `mvp` (or an unknown tier)
    the skip does not hold the build up but is stated - the step's message says "SKIPPED, not
    measured" with the tier, and the prototype-report's session notes list it. A failure is
    never turned into a skip; only a skip is ever made weaker than a pass.
  - *playability* (`wgf_playability/analysis.py`) left `content.variety` a WARNING when the
    probe reported no `entities[].kind`. The play-probe schema requires `kind` of every
    content-role entity while a content unit is in play (WS-4), so on the same basis, at the
    release tier, a probe that reports no kind while a unit is in play fails `content.variety`
    (required, route `develop`). Below it the check stays the unmeasured WARNING with its
    reason.
  - An exception is data, not code: a `skipped_checks.optional` entry (step, check, tiers,
    platforms, why) declares a check optional; none is shipped.
  - *verify's PASS_MOCK* is kept and carried, not blocked: no real-device evidence is
    available here, and the MV-4 `measurement_class` rule forbids reading a weaker class as a
    stronger one, not shipping on it. The release-manifest carries it per platform as before,
    and the release step's message now states it ("evidence PASS_MOCK (observed only against
    stand-ins ...: not a PASS)"); G4/G6 read the same class from the qa-report and
    verification-report.
- **`factory.listing.platforms`** validates a subset of the scaffold's platforms; it is a
  person's platform choice, so it is not a downgrade condition, and release does not
  cross-check it (WS-9).
- **No secret.** As for every param, a writer who rewrites `state.json`, the artifacts and
  `events.jsonl` consistently is not detected (`integrity.py`).
- **Lifecycle edits by hand.** `wgf-state.py` moves a title through its own guards and gate
  records; it is outside the workflow and is not held by this policy.
