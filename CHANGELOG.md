# Changelog

Notable changes to the methodology. A change here can invalidate an artifact that already
exists, so each entry says what it would take to bring one forward.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). The Factory is
released as a whole (`v1.0.0` is Core v1, frozen); schemas still carry their own versions,
and `core/` is still the contract.

## [Unreleased]

Wave 1 of the v1.1 architectural audit (P0 safety, template contract, CLI, test honesty).
Core changes are listed with their reason, as docs/core-v1.md requires.

### Changed - gate semantics (M4)
- **G4 `prototype-review` is a real checkpoint** in `new-game`, after `verify` passes and
  before `release`, decided on the verified `qa-report`, `verification-report` and
  `prototype-report` against the kill criteria and design (`title-strategy`, `game-design`),
  with `pass` / `iterate` / `kill`. gates.yaml G4 `required_artifacts`, the title machine's
  prototype-review inputs, the stage procedure and every schema's `required_for_gates` agree
  on those five, and check-integrity now fails when a schema's `required_for_gates`
  disagrees with gates.yaml. *Reason (core change,
  core/workflows + wgflib/workflow):* the workflow went from verify straight to release, so
  the one gate the factory exists for - the kill gate - was never asked. `iterate` returns
  to develop (a success routed back; lineage kept) and G4 asks again; `kill` ends the run
  (BLOCKED routed to `$end`: `DECISION_RECORDED`, `exit.route: kill`, `wgf status` "Ended:
  kill at G4", exit 0) and the run cannot be continued. Only a person decides it.
  *Migration:* `wgf new-game --mock` now stops `WAITING` at G4 - answer it with
  `wgf decide <run-id> pass`; scripts that expected it to complete unattended must decide
  G4. A run started before this change resumes under the current definition; one whose
  cursor is already past verify (at release) is not sent back to G4 by a plain resume, but
  `--run release` in it is refused until G4 is passed.
- **A gate is passed only by a forward answer.** The engine refuses a later step past a
  gate whose last answer routed backwards (`iterate`, `rework`) or ended the run, not only
  past one never answered; `--run` in skip mode asks such a gate again. *Reason:* `iterate`
  is a SUCCESS and would otherwise have counted as passing G4. `context.gates_passed` lists
  the gates a run has passed (for steps that want to check).
- **A checkpoint is decided on its gate's `required_artifacts`** (gates.yaml): without them
  in the run, as the step's inputs, it waits for input and asks nobody. G2 and G3 now list
  them as inputs. gates.yaml: G3 no longer requires `asset-manifest` (assets are sourced
  after G3), G4 requires the verified evidence. *Migration:* a custom workflow whose gated
  checkpoint does not list its gate's required artifacts as inputs now waits for input.
- **Reject and kill stop the run**; a run a decision ended at `$end` exits 0 and shows
  `Ended:` in `wgf status` (`ended_by` in `--json`), and `--run` refuses to continue it.
- **`design.on.descope: $fail`**, explicit: a blocking design-consistency breach ends the
  run with the design's own message (it already did, unrouted).

### Changed - the shipped commit is reviewed, and release refuses what was not (M7)
- **`sdk-review`: the sdk commit is reviewed too** (P0-8). `new-game` gains a step after
  `sdk`, before `verify`: `type: review`, `stage: title:prototype`, `with: subject:
  sdk-report`, inputs `sdk-report`, `prototype-report`, `game-design`, `scaffold-record`.
  The review step reads a generic `with: subject` (`prototype-report`, the default, or
  `sdk-report`): the reviewed commit is that artifact's `build_ref.commit_sha`, which must
  be HEAD; for the sdk subject the brief's change is prototype commit..sdk commit. Its
  `request-changes` routes to `develop` - the developer fixes the game side, sdk integrates
  again, both reviews run again, `max_visits` bounds it; a requested change never reaches
  verify. Verdict files are now `<run>/review/<step>-<visit>-<attempt>.*`, so the two
  reviews never overwrite each other. `sdk-report`'s x-wgf consumers gain
  `title:prototype`. *Reason (core change, core/workflows + core/artifacts):* `review` read
  develop's commit, then sdk committed integration code on top of it, and that unreviewed
  sdk commit is what verify checked and release shipped.
- **Release refuses an unreviewed or mis-reviewed build** (P0-9). The newest review-report
  must approve exactly the commit being released (the sdk commit, HEAD), from a reviewer
  that ran (`reviewer.kind: command`), pinning the run's newest prototype-report and
  sdk-report. `skipped`/absent is `unreviewed` (FAILED, not retryable); an approval of
  another commit - develop's alone included - or of an older report is
  `review-commit-mismatch` (was `commit-lineage-mismatch`). New
  `factory.release.allow_unreviewed` (default `false`, read only from config, never a
  step's `with:`) drafts a skipped/absent review anyway, recorded as UNREVIEWED; it waives
  nothing else. *Reason:* release recorded "UNREVIEWED" and shipped, and with the shipped
  `review.reviewer.kind: none` every release was unreviewed.
- **Release checks G4 itself** (M4 follow-up). `evidence_refusals` takes the engine's
  `context.gates_passed` (a required keyword: no default) and refuses `g4-not-passed`
  (BLOCKED) unless every gate in the release step's `with: required_gates` (default `[G4]`,
  read only from the workflow, never from config) is passed and current. The step cannot
  see its workflow definition and no engine change was in scope, so the workflow declares
  what its release requires and the default fails closed; `test_workflow_definition` checks
  every shipped workflow's release requires each irreversible gate it checkpoints.
- `--mock`: the review mock approves the commit its subject names (`reviewer.kind: none`,
  so no real release could accept it); the review-report fixture is `approve`.
- *Migration:* **with the shipped `review.reviewer.kind: none`, every real release is now
  refused (`unreviewed`)** - configure `factory.review.reviewer` (see the commented Claude
  Code block in factory.yaml), or set `factory.release.allow_unreviewed: true` knowingly. A
  custom workflow with a `release` step and no G4 checkpoint must add `with:
  required_gates: []`; one that lists `review-report` as a release input should add a
  review of the commit it ships. A run in flight past `sdk` when this lands has no
  sdk-review: resume it `--from develop` (or `--from sdk-review` in a run whose sdk commit
  is HEAD) to get the approval release now requires. Existing drafts are unaffected.

### Changed - gates emit decision-records (M5)
- **Workflow gates emit decision-records (P1-1, P0-11).** The G2, G3 and G4 checkpoints emit
  a schema-valid `decision-record` on every decided outcome - a person's choice,
  auto-approval, timeout approval, reject and kill - whose subject and provenance pin exactly
  the evidence consumed. One table in `wgflib/workflow/decisions.py` maps workflow choices to
  the schema (`kill` -> `abandon`). check-integrity requires every step naming a gate to
  output a decision-record, and only such steps may. *Reason (core change):* CLAUDE.md said
  every gate emits one; workflow gates did not. *Migration:* runs gain one
  `decision-record-<step>` artifact per decided gate visit.
- **Lifecycle bridge.** `factory.lifecycle.sync` (default off, snapshotted per run) appends a
  run's decision-records to `workspace/titles/<id>/decisions/` and advances the title cursor
  through `wgf-state.py`'s own guards and gate rules; a refused move is a warning, never the
  run's outcome. Never for a `--mock` run.
- **Guards read run evidence.** `ci_green`, `verify_suite_green` and `playable_build` can
  answer from a run's qa-report and verification-report (`wgflib/guards.py` `RunEvidence`);
  `PASS_MOCK` never counts as a pass for `verify_suite_green` / `playable_build`.
- `test_decisions` joins the WORKFLOW category of the Core Acceptance Suite.

### Changed - one checkout resolver (M6)
- **One checkout resolver (P0-14, P1-2, P1-3).** `wgflib/checkout.py`: every step that
  touches the game repository finds it by `with: repo_dir|game_repo` -> `WGF_GAME_REPO` ->
  scaffold-record `repository.local_path` -> `factory.checkouts` + name, relative paths
  resolved against the Factory root (docs/checkouts.md). *Migration:* `factory.checkouts`
  replaces `develop.checkouts`, `init.projects_dir`, `review.checkouts`, `sdk.games_dir`,
  `verification.checkouts` and `release.checkouts` (deprecated aliases, warned when they
  disagree); `WGF_GAME_REPO` now applies to develop and review too.
- A per-checkout advisory lock (pid + start time) blocks a second live run from working in
  the same tree while a step runs (`checkout-in-use`).
- scaffold-record 1.2.0 adds an optional `repository.local_path`, written by init.
- Assets default into `<checkout>/public/assets/`, which develop commits; the develop brief
  lists every asset's repository-relative file paths.
- Vendored platform profiles are verified by content hash in init, verify
  (`platform.profile:<id>`) and sdk (`wgf_init.profiles.verify_pins` / `pin_identity`).
- `wgf_develop` reads its template literals from `wgflib/template_contract.py`.

### Changed - loop and session budgets (M13)
- **Loops into one step are bounded per route (P1-7).** A workflow step may declare
  `max_visits_by_route: {<route>: n}`; entries through that route (the label or outcome
  that routed into the step) are counted in the step's new `route_visits` and bounded apart
  from each other, while `max_visits` still holds. A key is a route from any step or
  `<source>.<route>` from one step; entries are counted per `<source>.<route>`. new-game's
  develop takes `review.request-changes: 2`, `sdk-review.request-changes: 2`, `fail: 2`
  (verify) and `iterate: 2` (G4) over the run, with `max_visits: 9` on develop and on every
  later step of the loop. Route budgets last the run: resuming a run a route limit stopped
  refills that limit only, and `--from` all of them (M13 review: the two reviewers had
  shared one `request-changes` count, and every resume refilled every route, so G4's
  `iterate` - always decided by a resume - was never bounded).
  *Reason (core change, core/workflows + wgflib/workflow):* the four loops back into develop
  shared develop's one `max_visits` of 3, so a review loop could spend the passes a failing
  verification needed, and nothing said which loop had. The definition refuses a key that
  is no route into its step; the engine names no route.
- **Why a run stopped at a loop limit is data.** `state.blocked_reason = {kind: loop-limit,
  step, route, scope: step|route, limit, entered, from}` (also `WORKFLOW_BLOCKED`
  `data.blocked`), and resume's "one more pass" is decided from it instead of the message
  prefix (P1-8). *Reason (core change, wgflib/workflow):* string coupling. Integrity checks
  its shape and the route counters like `loop_base`.
- **A run-level budget for developer sessions that resume does not reset.**
  `factory.develop.budget: {max_sessions, max_cost, cost_from: {jsonl_key}}`, snapshotted
  into run params (`develop_budget`, corroborated like every param). The develop step counts
  command-developer sessions and their reported cost from the run's event log (STEP_LOG
  `data.budget`) and returns `BLOCKED` - no agent spawned - with `budget exhausted: N
  developer sessions used of N`, or on the cost limit. A session with no readable cost is
  counted and reported as unknown; the host's per-session flag stays that session's bound.
  *Reason (core change, wgflib/budget.py, wgflib/workflow/{config,api,integrity}.py):* every
  resume refilled the loop budget, so with a command developer nothing capped a run's
  sessions or spend.
- **Raising a budget is a person's act:** `wgf resume <run> --budget-sessions N |
  --budget-cost X` records a `BUDGET_RAISED` operator event (new generic
  `engine.resume(operator_events=...)`: refused for `decided_by: automation` and for the
  engine's own event names). Refused from inside a step's process tree. A raise counts only
  when the engine's `WORKFLOW_RESUMED` corroborates it by `resume_nonce`, and the develop
  step fails - not retried - when a developer session edited the event log, recording the
  raises it forged so they never count (M13 review: any appended `BUDGET_RAISED` line naming
  a person was honoured). `develop_budget` is a guarded param. *Residual:* no hash chain on
  `events.jsonl`; the run directory lying outside every agent's write scope is the
  containment.
- A step's context gains `entered_by` (the route into this visit), `visit_budget` (what the
  visit leaves of its limits) and `read_events()` (the run's recorded events);
  `STEP_STARTED` carries `entered_by`. The develop brief says which loop brought the work
  back and how many passes it has left (`brief.json` `loop`).
- *Migration:* none required. A run started before this change has no `route_visits`,
  `blocked_reason` or `develop_budget` and resumes as before (a loop-limit stop recorded only
  in its message still gets its one more pass); it has no budget, since none was
  snapshotted. `factory.develop.budget` applies to runs started after it is set.
  `max_visits_by_route` counts only from this version: an old run's earlier loops are not
  charged to any route. `wgf new-game --mock --mock-plan '{"verify": [fail x4]}'` now
  blocks on develop's `fail` route (as before, after the third failed verification); a
  review that always requests changes still blocks on its third request, and a third G4
  `iterate` now stops for a person. develop may be visited up to 9 times instead of 3 when
  the loops mix - set `factory.develop.budget` to bound what a command developer may spend
  in the run.

### Added
- **Timeout auto-approval (M4).** `factory.checkpoints.timeout_auto_approve: {G2: 48h}`
  lets a reversible gate approve itself once it has waited that long. *Reason (core
  change, wgflib/workflow):* gates.yaml's `auto_approve_after` was documented but never
  implemented. Conservative by construction: only listed gates; an irreversible or unknown
  gate listed refuses the run at start; the windows are snapshotted into the run's params
  (corroborated on resume, and a run started before has none); `waiting_since` is recorded
  per visit from the engine clock and corroborated by its `STEP_WAITING` event, and upstream
  work redone restarts it; the approval is recorded as `DECISION_RECORDED`
  (`decided_by: automation`, `mode: timeout`) and applied only by `wgf resume` - `wgf
  status` and `wgf runs --waiting` report eligibility and change nothing.
- **A silent child reads `hung`, and can be stopped (M3, P0-13).** The step state keeps
  `last_output_at` (the child wrote something, or a lifecycle event) and
  `last_heartbeat_at` apart from `last_activity_at` (any event, heartbeats included), and
  `wgf status` reads `hung` with `hung_reason: output` when heartbeats show the driver alive
  but the child has written nothing for `factory.execution.hung_output_seconds` (default
  900: above the reviewer's 600 s and the developer's documented 900 s idle timeouts), or
  `hung_reason: driver` as before. The status text says which, and names `wgf cancel`.
  Opt-in watchdog `factory.execution.on_hung: cancel` (default `none`): the driving engine
  terminates such a child's tree through the cancel path, the step ends not retryably, and
  a `STEP_LOG` warning says why; the policy is snapshotted into the run's params and
  corroborated on resume. *Reason (core change, wgflib/procs + wgflib/workflow):* every
  heartbeat refreshed `last_activity_at`, so a live but stuck child always read `running`
  and nothing acted on `hung`. *Migration:* none; older `state.json` has neither new field
  and derives as before, and a run started with `on_hung: none` records no new params.
- **SIGKILL recovery (M3, P0-12).** Children of a step carry
  `WGF_PROC_RUN=<run-id>@<store digest>`; resuming - or cancelling - a run that is
  `RUNNING` with no live driver first terminates every process still naming that run
  (Linux `/proc`; elsewhere a warning that it cannot) and logs the pids. Nothing untagged,
  and nothing of another run or store, is touched. *Reason (core change, wgflib/procs +
  wgflib/workflow):* a SIGKILLed driver runs no cleanup, so its trees were orphaned and no
  later process knew their pids.

### Security
- **Developer boundary (M1).** develop's git runs hardened like the reviewer's
  (`wgflib/gitsafe`: pinned git dir and work tree, safe env, filter drivers neutralised
  unless `factory.develop.git.allow_filters`, signing programs off). `package.json`,
  `tsconfig.json` and `pnpm-lock.yaml` are protected: only dependency additions allowed by
  `factory.develop.allowed_package_changes` pass conformance, so a developer can no longer
  rewrite the `test`/`lint`/`test:e2e` scripts every later check runs. The Factory's guarded
  paths are fingerprinted and restored around the developer. The commit is scoped to
  `factory.develop.writable_paths`; hidden paths (`.claude/`, `.github/`, ...) and agent
  instruction files are refused. Developer and reviewer processes get a scrubbed
  environment (`wgflib/agentenv.py`; add names with `factory.agents.env_passthrough`).
  Reviewer isolation moved to `wgflib/isolation.py`. *Migration:* a live agent host that
  authenticates through an environment variable needs it in `env_passthrough`; a developer
  that edited package.json scripts or wrote outside the writable paths now fails develop.
- **Game code gets no Factory secrets (M1b).** The code the Factory runs inside a game
  repository - the develop checks, verify's commands, the sdk conformance suite and release
  packaging, all written or editable by the developer agent - ran with the Factory's whole
  environment. It now gets `wgflib/agentenv.game_code_env`: the agents' allowlist (plus
  `PLAYWRIGHT_*` and `COREPACK_*`, toolchain configuration) and the names in the new
  `factory.agents.game_env_passthrough` (default `[]`) - never the agents'
  `env_passthrough`. Core change (`wgflib/agentenv.py`): the allowlist is shared kernel
  code, and one definition keeps the agents' and game code's rules from drifting.
  *Migration:* an installation whose `pnpm install` (or build) reads a registry or other
  credential from an environment variable must name it in `game_env_passthrough`;
  credentials in `~/.npmrc` under HOME keep working.
- **Run params are corroborated (M2).** `WORKFLOW_STARTED` records the run's params and
  resume refuses a state.json whose params differ. *Migration:* a run started before this
  change whose state claims `mock`, `mock_plan` or `auto_approve` is refused on resume;
  start a new run.
- **`--from` cannot step over a gate (M2).** A fresh run started with an explicit `--from`
  past a gate in its scope is refused (`wgf new-game --from design` skipped G2). Fresh
  single-step runs (`wgf verify`) are unaffected.

### Fixed
- Run lock identity is pid + process start time, so a recycled pid no longer holds a dead
  run; an empty lock tolerates mtime skew (M2).
- Atomic writes use unique temp names; concurrent `LATEST` writes no longer race (M2).
- A cancel is honoured while a step waits out its retry backoff; a crash between entering a
  step and moving the cursor no longer burns a visit (M2).
- Platform profiles are identified by id, version and content hash; init re-vendors a
  same-version profile with other content, and `wgf_init.profiles.verify_pins` checks it.
  check-integrity reads platform ids from the pinned template, never the sibling, and warns
  on template profiles that diverge under the same version (M8).
- **x-wgf agrees with the workflow (M9, P1-1).** check-integrity now fails when a workflow
  step outputs an artifact whose `x-wgf.producer` is not the step's `stage`, or takes an
  input whose `x-wgf.consumers` omit it. The 11 disagreements it found are fixed in
  `core/artifacts/`: `asset-manifest`'s producer is `title:prototype` (the `assets` step;
  `title:design` joins `updated_by`); consumers gained `title:scaffolding` (game-design),
  `title:prototype` (qa-report, prototype-report), `release:qa` (prototype-report,
  scaffold-record) and `release:draft` (qa-report, verification-report, sdk-report,
  prototype-report), plus `title:prototype-review` on qa-report and verification-report for
  the G4 checkpoint. *Core change, reason:* two statements of who produces and consumes an
  artifact had drifted with nothing comparing them. *Migration:* none for artifacts; a
  workflow that uses an artifact at a stage its schema does not name now fails the check.
- **One validator for the release manifest (M9, P1-6).** `scripts/wgf_release/schema.py`, a
  second, subset JSON Schema validator, is deleted; release validates the manifest it drafts
  and the game repository's `manifest.json` with `ArtifactContracts` (full schema through
  `jsonschema_lite`, provenance type, contract major, hash). A game manifest that only
  passed the subset (wrong `artifact_type`, an impossible date) is now refused as
  `invalid-manifest`. *Migration:* none for the template's make-manifest.mjs.
- **Recorded gameplay sessions are validated against their schema (M9, P1-6).**
  `wgf_verification/checks/gameplay.py` validates `build/verification/gameplay-session.json`
  with `jsonschema_lite` against `shared/gameplay-session.schema.json` (formats, unknown
  keys, browser entries) instead of a hand-written subset, and keeps the one rule the schema
  cannot state (the aspect is one the template contract knows). *Migration:* a session with
  keys the schema does not define is no longer used; verification falls back to the
  repository's Playwright suites, as for any unusable session.

### Added
- `wgflib/template_contract.py` (CONTRACT_VERSION 1.0.0): every path, npm script, CLI and
  output the Factory assumes of a game repository, used by init, verification, sdk and
  release, with a drift test against the pinned template (M10, `docs/template-contract.md`).
- `wgf resume`, `wgf decide`, `wgf runs --waiting [--json]` (M11).
- `wgf test-core --strict` (exit 4 on a SKIP category; opt-in tests skipped inside a PASS category are listed, not failed); the summary never reads a bare OK when
  anything was skipped, and every skipped test is listed by reason (M12).
- `docs/env-vars.md`; `test_review_module.py`, `test_netguard.py`, `test_check_integrity.py`,
  `test_template_contract.py`.
- **`x-wgf.version` and one provenance builder (M9, P1-6).** Every top-level schema declares
  its contract version (semver) as `x-wgf.version`; check-integrity requires it.
  `scripts/wgflib/provenance.py` (`build`, `artifact_id`, `producer`, `pin`, `pin_inputs`,
  `seal`, `version_of`) replaces the provenance each step module and the mock steps
  assembled by hand; `schema_version` is read from the schema. `ArtifactContracts` refuses
  an artifact whose `provenance.schema_version` has another MAJOR than `x-wgf.version`.
  Versions, set to what the producing module already emitted: asset-manifest 1.1.0,
  game-design 1.1.0, qa-report 1.1.0, release-manifest 1.2.0, scaffold-record 1.1.0,
  sdk-report 1.2.0, title-strategy 1.1.0, verification-report 1.1.0; decision-record,
  evaluation, opportunity, performance-review, platform-publication, prototype-report,
  research-report, review-report, state and tech-plan 1.0.0. *Core change, reason:* the
  version a producer claimed was a per-module constant nothing checked (sdk carried two,
  1.2.0 and 1.1.0). *Migration:* existing artifacts stay valid - only the major is compared,
  and every artifact written so far is major 1. Mock runs now write each schema's version
  instead of 1.0.0 for all, so new mock artifacts hash differently; real modules' output is
  unchanged apart from key order inside `provenance`, which the content hash ignores.
- **`x-wgf.run_path` (M9, P1-1).** Artifacts a workflow step produces name where an engine
  run stores them, `<storage>/workflows/<run-id>/artifacts/<id>/v<n>.json`, next to
  `repo_path`, their home in the methodology (workspace/ or the game repository), which the
  engine never writes (docs/artifact-contracts.md). *Migration:* none; `repo_path` keeps its
  meaning for adapters.

### Changed
- `wgf status` exits with the run's code (1 failed/blocked/cancelled, 3 waiting/paused).
  Flags a command would silently ignore are refused (exit 2). pause/cancel import no step
  module. A relative `factory.storage.directory` resolves against the repository root (M11).
- Test opt-in flags mean exactly `=1`; `WGF_TEMPLATE_REPO` (a pin bypass) is removed, the
  real SDK suite runs on the pinned checkout with `WGF_TEMPLATE_SDK_TEST=1` (M12).
### Added

- **The developer brief recommends the plugin's craft skills (F7).**
  - `brief.DEFAULT_SKILLS` names `web-game-factory:game-feel`, `core-loop`,
    `web-performance`, `audio` (area `craft`), `onboarding-ux` (`ui`), and the engine's
    `pixijs` / `threejs`, alongside the generic skills.
  - Configured areas are no longer silently dropped: every area except the other engine's
    reaches the brief. `[]` drops an area.
  - `develop.skills` is validated.

  *Migration:* none.

- **Opt-in developer self-playtest (F6).** The defaults are unchanged: developer `handoff`,
  `self_playtest: false`.
  - `developer.argv` gains a `{factory}` placeholder (the Factory root, substituted once).
  - New `workspace/config/mcp-playwright-localhost.json`: `@playwright/mcp@0.0.82`, headless,
    isolated, localhost origins only.
  - New `develop.self_playtest` setting, which adds a "Playtest your build" section to the
    brief.
  - A second commented developer block in `factory.yaml` (`--- opt-in: self-playtest`) adds
    `--mcp-config`, `--plugin-dir` and `Skill` / `mcp__playwright` to the verified argv,
    keeping `--strict-mcp-config` and every restriction.
  - `docs/claude-capabilities.md` records it as VERIFIED offline, UNVERIFIED live.

  *Migration:* none.

- **Shaped procedural audio (F5).** The procedural backend's sound effects were a bare sine
  tone. They now come from a deterministic jsfxr-style synthesiser (`encoders.synth`):
  waveform, envelope, pitch slide, vibrato and arpeggio. The preset (ui, coin, jump, hit,
  powerup, whoosh, lose, blip) is picked from the item's words and detuned by its id. Music
  is an 8 s bass-and-arpeggio loop (`encoders.music_loop`). The files remain placeholders,
  factory-generated and never production-ready, and each item's notes name its preset.
  *Migration:* none; `encoders.wav` is kept.

- **The `agent` design author (F4)**, `scripts/wgf_design/agent.py`. It is opt-in
  (`factory.design.author: agent`); the default stays `archetype`.
  - An agent host improves the archetype's draft from a request holding the strategy, the
    platform profiles and a starting draft.
  - The design module then applies exactly the checks it applies to any author:
    `finalize`, buildability, and the consistency rules including `descope`.
  - A malformed draft is refused before `finalize` (not retryable). A failing or silent
    host is retryable.
  - The design is attributed `actor: ai`.
  - The design step's brief now carries `config`, `run_dir`, `visit` and `attempt`.
  - `factory.yaml` has a commented read-only host example.

  *Migration:* none.

- **`core/craft/`: production craft playbooks.** What a *good* web game looks like inside
  the fields the artifacts already have: core loop and difficulty, game feel (a minimum
  feedback bar, distinct from polish), onboarding and portal UX, UI/HUD/mobile, audio, art
  direction, accessibility, web performance, playtesting (agent playthrough, stranger
  playtest and performance pass protocols), a gameplay-review checklist, competitive
  teardowns, and provider-neutral tool capability classes with their limits. Stage files
  `design`, `prototype`, `qa` and `tech-plan` point at them. `prototype.md` clarifies that
  the feedback bar is not the polish it warns against. *Migration:* none; no field, state
  or gate changed.
- **Adapter binding 1.2.0.** Eight new skills (`core-loop`, `game-feel`, `onboarding-ux`,
  `audio`, `art-direction`, `web-performance`, `gameplay-review`, `playtesting`). Existing
  skills and agent must-read lists are widened to the playbooks; `gameplay` and `ui` now
  read the game-design schema, and `asset` reads the asset policy. Skill entries list their
  `reads:`, which the integrity check verifies. Claude plugin 0.4.0; both adapters
  regenerated. *Migration:* none.
- `docs/production-craft-and-mcp.md`: skills and MCP tools by phase, what belongs in host
  configuration versus the repository, and Factory-module follow-ups found in the audit
  (F1-F7, not implemented).

### Changed

- **`docs/GDD.md` is rendered into the game repository (F3).** `game-design` declared
  `rendered_to: <game-repo>/docs/GDD.md`; nothing produced it. The develop step now writes
  it (`scripts/wgf_develop/gdd.py`) in `core/templates/gdd.md`'s section structure, pinned to
  the design's artifact id and content hash. It is written before the developer runs and again
  after, so a hand edit never survives, and it is committed with each visit. The development
  and review briefs point at it. The golden reviewer allows `docs/GDD.md`. The scaffolding
  procedure and the GDD template now say who renders it. *Migration:* none. `docs/tech-plan.md`
  is still not rendered; the tech plan reaches the developer through the brief (F1).

- **The review brief adds a gameplay lens and a design-fidelity section (F2).** "Look for"
  was code-only. It now also covers what players feel: restart state, frame-rate
  independence, pause, double starts and taps, tuning as data, frame-loop allocation, flash
  rate, audio unlock, and tests that reach their aspect. The lens is condensed from
  `core/craft/gameplay-review.md`. When the committed development brief carries F1's
  `build_spec` / `dev_plan`, the brief lists the MVP feedback, the tutorial approach and each
  task's acceptance criteria to check against. *Migration:* none; the verdict contract is
  unchanged.
- **Golden reviewer: every blocker carries `file`** (null for a whole-build finding).
  `scripts/golden/reviewer.py` omitted the key. `wgf_review.verdict.parse` rightly
  discards such a verdict as malformed, which failed a golden run after a verify → develop
  loop.

- **The develop brief carries the design's `build_spec` and the approved plan's tasks**
  (core change: `core/workflows/new-game.workflow.yaml`). The design authored mechanics
  with rules and tuning, the difficulty curve, reward and failure feedback, tutorial steps
  and audio cues, and the tech plan authored tasks with acceptance criteria. None of it
  reached the developer, whose brief held only the design's summary strings. `develop` now
  takes `tech-plan` as an optional input. `brief.md` gains a "Build spec (MVP tier)" and a
  "Development plan" section, and `brief.json` gains `build_spec` and `dev_plan`.
  `sdk_touchpoints` stay with the sdk step and `assets` with the asset manifest. The
  prototype-report now pins the tech plan it was briefed from. *Migration:* none; a run
  without a tech plan, or a design without `build_spec`, briefs exactly as before. A run
  resumed at develop under this definition consumes its existing tech plan.

## [1.1.0] - 2026-09-25

Factory v1, usable (`docs/v1-usable.md`). Core v1 against the latest **released**
web-game-template, v1.1.0 (`bca41a97665f8a32d0f803d46a7bbd001ac94d41`), running one complete
real workflow - research to a drafted release - with a real Claude developer and a real
read-only Claude reviewer. Core v1's architecture is unchanged; contract changes are additive.
Live portal behaviour, submission and publishing remain BLOCKED_EXTERNAL.

### Added

- **Platform profiles for Y8, GameDistribution and GameMonetize**
  (`core/reference/platforms/`). The shared profile schema gains `requirements.game_id`
  (`required | optional | none`), `game_id_pattern` and `hosting`. *Migration:* none; the
  fields are optional.
- **Portal registrations** - `workspace/titles/<title>/portals.yaml` - carried by the tech
  plan into `game_config.platforms[].game_id` (and `hosting` / `game_url`); a required Game
  ID that is missing blocks the tech plan. tech-plan schema: `game_id`, `hosting`,
  `game_url` on platform entries. *Migration:* none.
- **The integration seam module.** The develop step provides `src/game/integration.ts` and
  `src/platform/integration.ts` (`createGamePlatform`, `createGameIntegration`) before a
  game is built; the sdk step writes its integrated wiring over the latter as a whole file.
  *Migration:* a game built before 1.1.0 does not boot through the seam, and the sdk step
  now refuses it; rebuild it through develop.
- **`wgflib.netguard`** (moved from the golden harness): the develop smoke check and
  verify's browser commands run behind a refusing proxy, so no test contacts a portal.
- scaffold-record `template.generated_from_sha` and `template.pin_commit`.

### Changed

- **Pinned to web-game-template v1.1.0**, a release, instead of the development commit
  `22482b4`. The golden runs read their ports from a separately pinned fixture commit.
- The tech plan's `repo_params.template_ref` is always `<repository>@<pinned sha>`; init
  refuses a plan approved against another revision and brings a repository GitHub generated
  from another revision to the pin with one local commit. *Migration:* a tech plan naming
  `<template>@main` must be re-planned.
- init writes `game.id`/`game.name` itself for either source (bootstrap's own derivation).
- The sdk step never edits `src/main.ts`; it reads seam calls with the game's TypeScript
  compiler, resolves named placement ids and reports unresolvable ones.
- The develop brief states verification's evidence contract (aspect tags and the aspects
  this build must prove); a retry after a failed developer is told to continue its work.
- Shipped Claude developer example: `--max-turns 400`, `--max-budget-usd 40`.

### Fixed

- Reviewer isolation no longer reports pnpm-store hard links as reviewer writes.
- A reviewer's fenced verdict after quoted code is found.
- See `docs/v1-usable.md`, "What the real runs found and fixed".

## [1.0.0] - 2026-09-24

Core v1, frozen (`docs/core-v1.md`). The executable workflow core - engine, persistence,
contracts, process ownership, agent runtime, verify and release - protected by the Core
Acceptance Suite (`bin/wgf test-core`) and two real golden pipelines, Tower Merge Rush
(PixiJS) and Neon Drift Arena (Three.js). Validated against web-game-template
`22482b4eb81084a89ff8ecdeea9130f06ebb8026` (`workspace/config/template.lock.json`).
Everything below was added on the way there. Portal QA, publishing and real ad fill remain
BLOCKED_EXTERNAL.

### Added

- **Core v1 hardening (security pass).** `scaffold-record.repository.name` refuses `.` and
  `..` (schema pattern; consumers also resolve checkouts through
  `wgflib.paths.checkout_path`). `wgflib.procs.install_subreaper()` — installed by the `wgf`
  CLI — reparents orphans to the Factory, so a descendant that detaches and clears its
  environment is still ended with its step. *Migration:* a scaffold-record naming `.` or
  `..` was never usable; none exist.

- **Review module (`scripts/wgf_review`, step type `review`) and the `review-report`
  artifact.** An independent reviewer reads every development commit and approves it or
  requests changes with named blockers. The loop is data: `new-game` now runs
  `develop → review → sdk`, with `review` `on: {request-changes: develop}`, and
  `max_visits` bounds it. Request-changes is `FAILED` with a route and not retryable, so
  a workflow that forgot to route it fails closed. The reviewer is read-only and that is
  enforced: HEAD, refs, index, every tracked and untracked file, package/lock/test/config
  paths, `.git/config`/hooks and the Factory's `core/workflows` + `workspace/config` are
  fingerprinted before and after. Any change fails the review
  (`reviewer-isolation-violation`) and is undone. Verdicts are validated strictly
  (`malformed-verdict`). Timeouts and crashes are retryable and end the whole process tree
  through `wgflib.procs`. `kind: none` records `skipped`, never an approval. `develop`
  now takes `review-report` as an input: a request for changes to the commit it starts
  from puts the blockers first in the next brief (`review_blockers`). It also gains an
  optional `developer.idle_timeout_seconds`. Proved by
  `scripts/tests/test_core_agents.py`, the AGENTS category of the Core Acceptance Suite,
  with real subprocesses, real git and the real engine. See `docs/review-module.md`.
  *Existing artifacts:* none change. Existing runs of `new-game` resume into a workflow
  that has one more step. Installations must add `wgf_review` to `factory.steps.modules`
  (done in the shipped config) or run it with `--mock`.

- **Full schema validation inside the engine (`scripts/wgflib/jsonschema_lite.py`).** A
  standard-library JSON Schema draft 2020-12 validator covering every keyword
  `core/artifacts/**` uses (enumerated by the tests), with `$ref` across the shared schemas,
  asserted formats, ECMA-faithful patterns and JSON-pointer errors in a fixed order. It raises
  on any keyword it does not implement instead of ignoring it. `ArtifactContracts` now
  validates the whole schema, not only top-level keys, rejects content JSON cannot represent
  (NaN, non-string keys, Python-only values), and caps diagnostics at 20 while always keeping
  the provenance type and hash problems. New `check_lineage(content, consumed)` checks that
  `provenance.inputs` pins exactly the input versions a step consumed; the engine does not
  call it yet. Deliberately stricter than ajv-formats@2 in one place: a `date-time` must
  carry an RFC 3339 offset. **Bringing an artifact forward:** nothing to do if it already
  passed ajv; every workspace instance, reference file and module output under the test
  suite validates unchanged. See `docs/core-contracts.md`, which also audits every pipeline
  boundary. No schema changed.

- **Tech-plan module (`scripts/wgf_techplan`, step type `tech-plan`) and the G3 checkpoint.**
  `new-game` now runs design → `tech-plan` → `tech-plan-review` (G3, reversible, same shape
  as `strategy-review`) → init, as the title machine always said. The module is minimal and
  deterministic: the engine is the one the design declares (dimension or asset kinds only as
  a fallback for older designs), platforms are the strategy's pins resolved against
  `core/reference/platforms/`, the bundle budget is the tightest required limit, ad kinds
  come from the design's placements, and the dev plan's estimates are a stated heuristic
  reported against the timebox, never fitted to it. See `docs/techplan-module.md`.
  *Existing runs:* a run started before this change has no `tech-plan` step; resume it as
  before, or start a new run to get one.
- **Init writes `game.config.yaml` from the tech plan.** With a `tech-plan` in the run, init
  rewrites `engine`, `platforms` and `monetization` in place (comments and every other field
  kept, the result parsed back and checked), vendors the pinned profiles into
  `config/platforms/`, and makes one local commit carrying the idempotency key as a trailer.
  It never pushes. A 3D design now reaches the game repository as `engine.type: threejs`
  instead of the template default.
- **Init `factory.init.source: local`.** Makes the project from a local template checkout
  (`template_path`, pinned by `template_ref`) with `git archive` into a new repository with no
  remote: offline, for golden-regression runs. `github` stays the default and is unchanged.
- **`scaffold-record` fields (additive, schema 1.1.0):** `template.source` (`github` |
  `local`), `game_config.engine`, `game_config.commit_sha`, `game_config.pushed`. Existing
  records remain valid; an absent `template.source` means `github`.

- **Release module (`scripts/wgf_release`, step type `release`, stage `release:draft`).**
  The `release` step is real: `wgf new-game` no longer needs `--mock` for it. It drafts a
  release only when the newest qa-report in the run passed, pins the newest
  verification-report, prototype-report and sdk-report by hash, and names the same commit as
  each of them and as the checkout's HEAD; the checkout is clean and its bundle is the one
  verification digested. It then runs the game repository's own `release:package` and
  `release:manifest` (as owned process trees, `wgflib.procs`), checks every package's sha256
  against its file, refuses archives with sourcemaps, test files, env/secret files or
  secret-looking content or without `index.html` at their root, validates the manifest
  against the schema, and returns it in state `draft`. It never pushes, tags, publishes or
  contacts a portal. See `docs/release-module.md`. **Contract change:** the `release` step
  now declares `verification-report`, `sdk-report`, `prototype-report` and
  `scaffold-record` besides `qa-report`; `factory.release.checkouts` locates the game
  repository.
- **Evidence statuses.** `PASS`, `PASS_MOCK`, `BLOCKED_EXTERNAL`, `UNVERIFIED`, `FAIL`, in
  the new shared primitive `core/artifacts/shared/evidence.schema.json`, alongside (not
  instead of) the routing statuses. A check observed only against a stand-in — every SDK
  feature exercised against a mocked portal SDK — is `PASS_MOCK`, and so is every
  verification, qa-report, platform and release manifest resting on one; nothing promotes it
  to `PASS`. A platform's own portal QA is `BLOCKED_EXTERNAL` unless its SDK evidence says it
  was observed on the live portal (`NOT_APPLICABLE` for a profile whose review process is
  `none`).

  *Schema changes, all additive:* `verification-report` gains `evidence_status`,
  `workflow`, `checks[].evidence_status`, `platform_readiness[].evidence_status` and
  `portal_status`; `qa-report` gains `evidence_status`, `workflow` and
  `platform_checks[].evidence_status` / `portal_status`; `release-manifest` gains
  `workflow`, `template`, `evidence` (what the draft was cleared by: qa and verification
  reports, commit lineage, bundle hash, per-platform evidence, package audit,
  reproducibility) and `packages[].content_digest` / `files`. Reports the verify step writes
  now declare `schema_version` 1.1.0; drafted manifests 1.1.0.

  *Migration:* none for existing artifacts, which stay valid. A qa-report without
  `evidence_status` (1.0.x) is refused by the release step: re-run verify.

- **Assets module (`scripts/wgf_assets`, step type `assets`).** Turns a game design into an
  asset manifest and the files behind it: inspects `game_design.asset_requirements` (or
  derives a baseline), classifies each against the new `core/reference/asset-policy.yaml`,
  reuses a design's existing file or a licensed library asset, otherwise generates a
  placeholder — through an optional 2D asset MCP server when one is configured, always
  falling back to a standard-library procedural backend — then validates formats from the
  bytes, optimizes losslessly and records licence, origin and usage constraints per item.
  An asset whose licence is unknown or restricted, or that has no recorded origin, is never
  `production_ready`. Covers 2D (sprites, sheets, backgrounds, UI, icons, VFX, fonts, audio)
  and 3D (models, textures, materials, animations, environments). Registered in
  `factory.steps.modules`; see `docs/assets-module.md`.

  *Schema changes, all additive:* `asset-manifest` items gain `dimension`,
  `license_status`, `usage_constraints`, `origin`, `placeholder`, `production_ready`,
  `files`, `reference`, `optimization` and `issues`, the `type` enum gains `background`,
  `material` and `environment`, and the manifest gains `policy`, `issues` and `generation`
  (instances now declare `schema_version` 1.1.0). `game-design` gains optional
  `asset_requirements`. The `assets` step and `title:prototype` now also consume
  `scaffold-record` (for platform bundle limits), and `title:prototype` names
  `asset-manifest` among its outputs.

  *Migration:* none. Existing manifests and designs stay valid.

- **Development module.** `scripts/wgf_develop` implements the `develop` step and is
  registered in `workspace/config/factory.yaml`. It briefs the build from the game design
  (`docs/development/brief.md` in the game repository), hands it to a developer — a person
  (`handoff`) or a configured command — then checks template conformance, typecheck, lint,
  tests, build and the browser smoke suite, commits once per visit, and emits a
  `prototype-report` that records only what it measured. See
  `docs/development-module.md`. **Contract change:** `develop` now declares
  `scaffold-record` and `title-strategy` as inputs in `core/workflows/new-game.workflow.yaml`;
  existing runs resume unaffected, and a run without them is told what is missing.

- **SDK integration phase (`scripts/wgf_sdk`).** Before its conformance check, the `sdk`
  step now integrates web-game-template's existing platform SDK into a game's gameplay: it reads
  the SDK the game repository carries, compares what each target platform's adapter offers
  with what the game-design needs, writes a gameplay layer (`bootPlatform`,
  `PlatformGameplay`), a plan generated from the design's placements and an SDK-mock suite
  into the game repository, routes the template's boot through it, and reports per platform
  and feature, laid over the conformance result (the worse status wins). It implements no
  SDK and contacts no portal. Settings in `factory.sdk`; `--mock` runs are unaffected. See
  `docs/platform-architecture.md`.
- **The sdk module checked against each portal's current documentation** (Yandex, CrazyGames,
  Poki, GameVui; 2026-09-23). The gameplay layer now keeps one "playing" state with the
  adapter's own, mutes and pauses for every ad and for the portal's own pause (Yandex
  `game_api_pause`), hands late rewards to the game, says why a reward was not granted,
  hides offers when the portal SDK did not load, and gives Poki an ad opportunity before
  every continue (`factory.sdk.break_on_continue`) while keeping interstitials off
  CrazyGames' pause menu (`factory.sdk.interstitial_forbidden_moments`). The boot timeout is
  gone: every adapter bounds its own waits, and replacing one on a timer lost Yandex Game
  Ready and CrazyGames gameplay events. `python -m wgf_sdk.e2e` builds a PixiJS and a
  Three.js game per platform from a template revision and drives it in Chromium against the
  template's own SDK mocks. Platform limitations are listed in
  `docs/platform-architecture.md`. The step also wires the develop module's seam
  (`src/game/integration.ts`): it implements `GameIntegration` on the platform, maps the
  game's own placement ids to the design's moments, and swaps the developer's default
  implementation out of `main.ts`.
- **Workflow module contract.** `docs/workflow-module-contract.md` is what the discovery,
  strategy, design, init, assets, development, SDK and verification modules implement
  against; `scripts/tests/test_workflow_contracts.py` holds the gate — an external module
  plugged in through `factory.steps.modules` runs without engine changes. The engine now
  checks every produced artifact against its schema's top level and provenance before
  persisting it, records which input versions each step consumed, versions its events
  (`format: 1`), accepts dot-namespaced step types, and validates run ids, artifact ids and
  module names before they reach a path or an import. `--mock` auto-approves only the
  workflow's own reversible checkpoint gates. Pausing or cancelling a crashed run takes
  effect at once.
- **`scaffold-record` and `sdk-report` schemas**, named as outputs of `title:scaffolding` and
  `title:prototype`, replacing the workflow's `untyped_artifacts`. Additive: no existing
  artifact changes. The title machine keeps version 1.0.0 because only its declared outputs
  grew.
- **Executable workflow engine (`wgf`).** `core/workflows/new-game.workflow.yaml` defines the
  work from research to release preparation as data; `scripts/wgflib/workflow/` runs it —
  step registry, retry with backoff, failure routing (`verify` fail → `develop`), human
  checkpoints tied to gates, resume, idempotent re-entry, events and a file store in
  `.factory/`. `bin/wgf` exposes `new-game`, `research`, `plan`, `init`, `assets`, `develop`,
  `sdk`, `verify`, `release`, `status`, `logs`, `runs`, `pause` and `cancel`, all through
  one engine. Every step is a placeholder (`--mock`) that emits schema-valid artifacts;
  nothing is researched, built or published. `workspace/config/factory.yaml` configures it.
  `check-integrity.py` now validates workflow files. Existing artifacts are unaffected.

- **`tech_plan.repo_params.game_config.monetization`** — the ad kinds a title commits to,
  carried into the game repository. Platform profiles assert on `package.uses_banner_ads` and
  `package.uses_rewarded_ads`, and on GameVui the latter is blocking; but observing a run can
  only prove an ad *was* requested, never that one is never requested. Without a declaration
  reaching the game repository, those assertions could not be evaluated honestly. Derived from
  `game_design.monetization.placements[].kind` — not decided in the tech plan.

  *Migration:* optional. An existing tech plan stays valid; a game repository built from one
  without it measures both ad facts as `false`.

- **`scripts/wgf-org-setup.sh`** — creates and reconciles the organization's `WGF_*` Actions
  secrets and variables for the game pipelines. Idempotent, and the living inventory of what
  the organization should hold. It never rewrites an existing secret's value: GitHub cannot
  return one, so `gh secret set` on an existing name would replace a real credential with the
  sentinel.

### Changed

- **Agent-host capability audit (docs/claude-capabilities.md).**
  - `workspace/config/factory.yaml` `review.guarded_paths` is back to the module default,
    `[core, scripts, bin, workspace/config]`. It had narrowed it to
    `[core/workflows, workspace/config]`, which undid the widening from the security pass.
    A test now pins it.
  - The file gains commented, verified headless developer/reviewer argvs for the one host
    audited. The active defaults (`handoff` / `none`) are unchanged.
  - Adapter binding 1.1.0: `architect` produces `review-report` as the read-only reviewer
    in `title:prototype`. `gameplay` and `release` consume what their steps read. Both
    plugins are regenerated.
  - `test_core_agents` gains `LiveDeveloperAndReviewer` (opt-in). `LiveReviewer` could not
    pass against a competent live host and is fixed.
  - No existing artifact is affected.

- **Commit lineage: a real run can release.** The pipeline develop → review → sdk → verify →
  release now names one chain of commits, and every step that reads it applies one rule
  (docs/core-contracts.md §5, `scripts/wgf_verification/lineage.py`). The `sdk` step commits
  its integration once, locally, keyed by the idempotency key in a `Wgf-Sdk-Key` trailer
  (reusing develop's keyed-commit mechanism), and never pushes; it refuses (`BLOCKED`) a
  checkout whose HEAD is not the prototype-report's commit or this run's sdk commits on it,
  and uncommitted changes it did not make. `sdk-report.build_ref` gains `base_commit_sha` and
  `sdk_commits` (**sdk-report 1.2.0, additive**). verify's `source.upstream-commits` and
  release both require: sdk-report commit == verified commit == HEAD; prototype-report commit
  == sdk base; `git log base..sdk` holds only this run's sdk commits — otherwise
  `commit-lineage-mismatch`. release now takes `review-report` as an input (workflow
  `new-game`, and `release:draft` added to its consumers): an approval must be of exactly the
  prototype commit, a request for changes refuses (`review-not-approved`), and a skipped
  review is recorded as `evidence.review.status: skipped` — never as approved
  (**release-manifest 1.2.0, additive**: `evidence.review`). Placeholder commits are gone:
  develop returns `BLOCKED` instead of `"0"*40`, sdk `BLOCKED` instead of `"unknown"`, and
  release refuses either as `commit-unknown`. The engine now enforces artifact lineage: with
  a validator, an output declaring `provenance.inputs` must pin exactly the versions its step
  consumed (`contracts.check_lineage`, plus no pin of a declared input the step was not
  given), else a non-retryable `FAILED`. Proved by `scripts/tests/test_core_lineage.py`.
  *Existing artifacts:* sdk-reports and release-manifests from before still validate; an
  sdk-report without `base_commit_sha` is read as having made no commit, so it must name the
  prototype's commit. A prototype-report or sdk-report naming a placeholder commit can no
  longer be released from: re-run develop (and sdk) so they commit.

- **Verification no longer passes on stale or unowned evidence.** An sdk-report or
  prototype-report naming another commit than the one under test is now a required,
  `BLOCKED` `source.upstream-commits` check (was a non-blocking warning), and SDK checks
  built on such an sdk-report are `BLOCKED`. Runtime facts and assertion results left by an
  earlier run are deleted before the commands that write them, an assertion evaluator that
  exits non-zero without a blocking breach is `FAIL`, a Playwright run that exits non-zero
  with a green report is `FAIL`, a recorded scenario citing a screenshot that does not exist
  is not counted, and the Playwright report, assertion results, runtime facts, recorded
  session and screenshots are pinned by sha256 in the evidence.
- **`sdk-report` 1.1.0**, additive: optional `sdk`, per-platform `adapter`, per-feature
  `required_by`/`hooks`/`fallback`, feature status `unsupported`, and an `integration` block
  (files, placements, game hooks, tests). Existing 1.0.0 reports still validate.
- **The workflow's `sdk` step reads `game-design` and `scaffold-record`** as well as
  `prototype-report`: it integrates what the design placed into the repository init made.
  A run whose `sdk` step was already completed is unaffected.
- **`criteria-expression` now states which way `in` and `not_in` read.** Platform profiles use
  `{left: package.locales, op: in, right: [ru]}` to mean "the package ships Russian". Read as
  the conventional "left is a member of right", that assertion passes for a package with no
  locales at all — and locale assertions are blocking on three platforms. The operator
  description now fixes the semantics: an array measurement asks whether every element of
  `right` is present in it; a scalar measurement asks whether it appears in `right`.

  *Migration:* none to the data. Any evaluator written against the old reading must be
  corrected, and its locale results re-checked.

### Notes from implementing the template's pipelines

Findings that belong with the methodology even though the code lives in the sibling repository:

- A **gate needs a mechanism, not a name**. `environment: production` in a workflow is not a
  gate — GitHub creates an unconfigured environment implicitly, with no protection, the first
  time a job names one. G6 and G7 are enforced by *required reviewers* on that environment, and
  the workflows now verify that rather than assume it.
- **Required reviewers are unavailable on private repositories under a free plan.** A private
  game repository on a free organization cannot enforce G6 or G7 through environments at all.
  Worth deciding per title, since `repo_params.visibility` defaults to `private`.
- **Platform profiles must be vendored into the game repository** at the pinned version. A game
  repository has no access to `core/`, and `platform-validation.md` names validating against
  the current profile rather than the pinned one as a failure mode. They go to
  `config/platforms/` as byte-identical copies, so drift is a plain diff.
- **Only Poki has a headless upload path.** Yandex, CrazyGames and GameVui accept a ZIP through
  a console a person logs into. `publish.md` already says no portal APIs are integrated by
  design; this is the same conclusion arrived at from the other direction.

## 2026-09-22 — initial

- `core/`: four lifecycle machines, seven gates as data, thirteen artifact schemas with their
  contracts in `x-wgf`, five platform profiles, twelve role charters, adapter bindings.
- `claude-web-game-plugin/` and `codex-web-game-plugin/`, generated from `gen-adapters.sh`.
- `workspace/`: a complete worked example from a market claim to a kill decision at G4.
- `scripts/check-integrity.py` for referential integrity across machines, schemas, roles and
  bindings.
