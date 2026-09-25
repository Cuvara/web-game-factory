# Core v1

What the Factory's executable core guarantees, how those guarantees are tested, and the rule
every change after the freeze follows. The detail lives in the documents linked from each
section; this one is the map and the contract.

"Core" means the parts every module depends on and no module owns:

| Part | Where | Detail |
|---|---|---|
| Workflow engine: definitions, routing, retry, resume, pause, cancel, gates, loop bounds | `scripts/wgflib/workflow/` | `docs/workflow-engine.md` |
| Run persistence: state, events, artifacts, locks | `scripts/wgflib/workflow/store.py` | `docs/workflow-engine.md` |
| Contracts: full schema validation, provenance hash, lineage | `scripts/wgflib/jsonschema_lite.py`, `scripts/wgflib/workflow/contracts.py`, `core/artifacts/` | `docs/core-contracts.md` |
| Process ownership, heartbeat, liveness | `scripts/wgflib/procs.py` | `docs/agent-lifecycle.md` |
| The CLI | `scripts/wgf.py`, `bin/wgf` | `docs/workflow-engine.md` |
| The Core Acceptance Suite | `scripts/tests/core_suite.py` + `test_core_*.py`, `test_golden_*.py` | below |

Modules — `wgf_discovery`, `wgf_strategy`, `wgf_design`, `wgf_techplan`, `wgf_init`,
`wgf_assets`, `wgf_develop`, `wgf_review`, `wgf_sdk`, `wgf_verification`, `wgf_release` —
are not core. They plug into it through `factory.steps.modules` and the step contract
(`docs/workflow-module-contract.md`), and they are what gets improved one at a time from here.

## Architecture

```
core/workflows/new-game.workflow.yaml        what runs, in what order, where each result goes
        │
        ▼
WorkflowEngine ── StepRegistry (type -> module) ── LocalRuntime ── step.execute(inputs, ctx)
        │                                                              │
        │  validate inputs, run, validate outputs,                     │  procs.run / spawn
        │  persist atomically, route by `on:`                          ▼
        ▼                                                     owned process tree
RunStore  .factory/workflows/<run-id>/                        (session + env tag,
          state.json   events.jsonl   artifacts/<id>/v<n>.json  heartbeat, cancel)
```

- The engine knows steps by **type** and results by **outcome** and **route**. It never names
  a step type or a route (`test_engine_source_names_no_step_type`). "Verification failure goes
  back to development" and "request-changes goes back to development" are lines in the
  workflow file, not code.
- It is renderer- and platform-agnostic: nothing in `scripts/wgflib/` knows PixiJS,
  Three.js, Poki, Yandex, CrazyGames or GameVui. The engine choice travels as data
  (`game_design.engine` → `tech_plan.repo_params.game_config` → `game.config.yaml`), and
  platforms travel as pinned profile ids. The same workflow runs a 2D and a 3D game —
  that is what the two golden runs prove.
- A step never moves a lifecycle entity. `wgf-state.py`, guards and gates do.

## The pipeline

```
research → strategy → [G2] → design → tech-plan → [G3] → init → assets
  → develop ⇄ review → sdk → verify ─fail→ develop
                                   └─pass→ release (draft)
```

| Boundary | Artifact | Refused when |
|---|---|---|
| research → strategy | `opportunity` | schema-invalid, hash does not reproduce |
| strategy → design | `title-strategy` (after G2) | as above; G2 rejected blocks the run |
| design → tech-plan | `game-design` | as above |
| tech-plan → init | `tech-plan` (after G3) | engine not pixijs/threejs, platform pin not in `core/reference/platforms` |
| init → develop | `scaffold-record` | infrastructure missing from the template copy |
| develop → review | `prototype-report` | no real commit (no placeholder shas) |
| review → sdk | `review-report` | reviewer changed anything, malformed verdict, wrong commit |
| sdk → verify | `sdk-report` | integration not committed / not on the reviewed commit |
| verify → release | `qa-report`, `verification-report` | not the newest visit, not passing, commit lineage broken, dirty tree |

Every boundary is enforced twice: the engine validates each **output** against its full schema
before persisting it and each **input** again before the consuming step runs (a hand-edited or
tampered artifact fails the step, non-retryably, naming `id@vN` and its producer). The
domain rules in the last column are the consuming module's. `docs/core-contracts.md` has the
full table with the fields each consumer reads.

## Workflow lifecycle guarantees

| Guarantee | Mechanism | Test |
|---|---|---|
| Deterministic routing | pure `_route`; fixed clock + run-id ⇒ identical state and events | `test_core_workflow.Determinism` |
| Retry | FAILED + retryable, per-step policy with backoff | `Retry` |
| Resume | state saved before and after every execution; a step recorded as succeeded is never executed again by `resume`, even if the driver died before the cursor moved (it follows the recorded route instead) | `Resume`, `StaleRunResume` |
| Pause / cancel | request files honoured between steps; cancel also terminates a running child tree and ends CANCELLED | `Pause`, `Cancel` |
| Human gates | `human-checkpoint` waits; G4/G6/G7 never auto-approve; `wgf <step> --run` and `resume --from` refuse to start past an upstream step that is BLOCKED, WAITING or FAILED, or past a gate this run has not passed | `HumanGate` |
| Event log is load-bearing | a run that cannot write `events.jsonl` ends FAILED with the reason, never COMPLETED | `test_core_persistence.EventLogLoss` |
| No infinite loops | `max_visits` per step, including skipped and `--run` paths | `MaxVisits`, `VerifyDevelopLoop` |
| One driver per run | O_EXCL lock with guarded stale takeover | `ConcurrentRunLock` |
| Atomic persistence | temp + fsync + rename for state, artifacts, pointers; torn event lines skipped and reported | `test_core_persistence` |

## Agent lifecycle

A developer or reviewer is a **configured command** (an agent host's non-interactive mode, or a
person via `handoff`). The provider is named only in installation config, never in `core/`.

- **Ownership.** Every child runs through `wgflib.procs`: own session, `WGF_PROC_TAG` in its
  environment, and on every exit path — success, failure, timeout, idle timeout, cancel,
  `wgf` receiving SIGTERM/SIGHUP — the group and every tagged descendant (including ones that
  `setsid()` themselves, as Playwright's webServer does) are terminated, SIGTERM then SIGKILL.
  No module may call `subprocess` itself (`EveryChildGoesThroughProcs`).
- **Observability.** `STEP_PROGRESS` events (`spawned`, `heartbeat`, `timeout`,
  `idle-timeout`, `cancelled`, `cleanup`, `exited`) and `pid` / `last_activity_at` /
  `last_event` on the step state. `wgf status` derives liveness: `running` (lock held,
  recent activity), `hung` (lock held, silent for `factory.execution.hung_after_seconds`),
  `stale` (says RUNNING, driver dead — resume it).
- **Reviewer isolation.** Enforced, not requested: the checkout, refs, index, hooks, config and
  the Factory's own workflow/config are fingerprinted before and after; any change fails the
  review (`reviewer-isolation-violation`) and is undone. It is detection and restoration, not
  a sandbox — `docs/review-module.md` lists what it cannot see.
- **Verdicts.** `approve` with blockers, `request-changes` without, a different commit, extra
  keys, no file: all `malformed-verdict`, never retried. `kind: none` records `skipped`,
  never an approval, and release carries it as skipped.

Details: `docs/agent-lifecycle.md`, `docs/review-module.md`, `docs/development-module.md`.

## Evidence vocabulary

`PASS`, `PASS_MOCK`, `BLOCKED_EXTERNAL`, `UNVERIFIED`, `FAIL`
(`core/artifacts/shared/evidence.schema.json`). A report's status is the weakest of its
required checks. `PASS_MOCK` — anything observed against a mocked portal SDK — is never
promoted to `PASS` by any step; a portal's own QA is `BLOCKED_EXTERNAL` until live evidence
exists. Release carries per-platform evidence unchanged into the manifest.

## The Core Acceptance Suite

```bash
bin/wgf test-core                 # fast categories; golden categories report SKIP
WGF_GOLDEN=1 bin/wgf test-core    # everything, including both real pipelines (minutes)
WGF_GOLDEN=1 bin/wgf test-core --strict   # the release gate: nothing may be skipped
bin/wgf test-core --only SECURITY --json
```

| Category | Modules | Proves |
|---|---|---|
| WORKFLOW | `test_core_workflow`, `test_core_persistence` | engine semantics and crash safety |
| AGENTS | `test_core_agents` | developer → reviewer → request-changes → developer → approve, isolation, verdicts, timeouts, retry budget, loop bound |
| CONTRACTS | `test_core_contracts`, `test_core_lineage`, `test_core_template`, `test_golden_fast` | full schema validation, lineage pins, malformed/missing/tampered artifacts |
| VERIFY | `test_core_verify` | PASS only from evidence; stale/missing/mocked evidence never PASS |
| RELEASE | `test_core_release` | release gated by verify, commit lineage, package hygiene, hashes |
| 2D GOLDEN | `test_golden_2d` | the whole pipeline on a real PixiJS game |
| 3D GOLDEN | `test_golden_3d` | the same workflow on a real Three.js game |
| PROCESS CLEANUP | `test_core_process` | no survivor on any exit path |
| SECURITY | `test_core_security` | the adversarial pass, one test per attack |

A category whose module is missing is `MISSING` and fails the suite; a category that ran
nothing or only skips is `SKIP`, which is not `PASS`. A `PASS` category can still contain
skipped tests (an opt-in flag that is off, a missing `npx`). The mapping is data in
`scripts/tests/core_suite.py`.

What is skipped is never hidden. The output lists every skipped test by category, grouped
by its skip reason, and `--json` adds a `skips` list (`id`, `reason`) to each category plus
`complete`, `skipped_categories` and `skipped_in_pass`. The summary line says `OK` only when
nothing was skipped. Otherwise it says, for example,
`OK (INCOMPLETE — skipped: 2D GOLDEN, 3D GOLDEN; 12 tests skipped in PASS categories; …)`.

| Exit | When |
|---|---|
| 0 | no category is `FAIL` or `MISSING`. Without `--strict`, skips do not change the exit code. |
| 1 | a category is `FAIL` or `MISSING`, with or without `--strict` |
| 4 | `--strict` only: nothing failed, but a category is `SKIP` or a `PASS` category skipped a test |

Plain `bin/wgf test-core` is the everyday check: it is fast and exits 0 with the goldens
skipped. **`WGF_GOLDEN=1 bin/wgf test-core --strict` is the release gate.** A skip there
means something was not proved on this machine: enable its flag (see
[env-vars.md](env-vars.md)) or install what it needs. Do not merge a skip as a pass. The
live-agent, ajv and template opt-ins inside the fast categories count too, so a strict run
needs them enabled (and `npx`, `pnpm` and the pinned template available), not only
`WGF_GOLDEN=1`.

## Golden runs

Two canonical regression paths through the one `new-game` workflow, real modules, no `--mock`,
offline (`factory.init.source: local`, deterministic research snapshots, reversible gates
auto-approved and recorded as such): Tower Merge Rush (PixiJS) and Neon Drift Arena
(Three.js), both from `web-game-template/examples/`. The developer in a golden run is a
**replay** of the known-good example game through the real `command` developer kind — it
proves the pipeline, not an AI developer. See `docs/golden-runs.md`.

## The template boundary

The Factory contains no game or template source. web-game-template
(https://github.com/Cuvara/web-game-template) holds the template, the example games, their
golden-run ports (`examples/*/wgf-golden/`), the platform adapters and the PixiJS/Three.js
support. The Factory pins one commit in `workspace/config/template.lock.json` — Core v1:
`22482b4`, which is template main `1f5dee2` plus the commit that added the golden-run ports
(branch `wgf/golden-ports`) — and every reader of template files goes through
`scripts/wgflib/template.py`, which checks out exactly that commit and refuses any other.
`test_core_template` proves the pin, the refusal, that the golden runs build from it, that
nothing reads the sibling working copy, and that the Factory tracks no game source (each
non-Python file it does track is named with its reason). Moving the pin: run both golden
runs with `WGF_TEMPLATE_COMMIT=<sha>`, then change the lock in the same commit.

## Known external blockers

Not faked, not bypassed, and not part of the acceptance suite:

- **Portal QA** — Yandex moderation, CrazyGames QA, Poki Inspector, GameVui submission: need
  portal accounts and human review. Status `BLOCKED_EXTERNAL`. The template's opt-in harness
  (`pnpm test:sdk:live`, `web-game-template/docs/audits/`) is where live evidence would come
  from.
- **GitHub repository creation** — `init` in `github` mode creates a real repository; golden
  runs use `local` mode instead. Pushing, tagging and publishing stay behind G5/G6 in the game
  repository's CI.
- **A real agent host as developer/reviewer** — covered by opt-in tests
  (`WGF_LIVE_AGENT=1`, see `docs/review-module.md`); not run by the suite because it costs
  money and is not deterministic.

## Changing anything after the freeze

Every module improvement follows this, in order, and stops at the first red:

```
change ONE module
      ↓
that module's tests               python3 -m unittest scripts/tests/test_<module>*.py
      ↓
contract tests                    bin/wgf test-core --only CONTRACTS
      ↓
Core Acceptance Suite             bin/wgf test-core
      ↓
2D golden run                     WGF_GOLDEN=1 bin/wgf test-core --only "2D GOLDEN"
      ↓
3D golden run                     WGF_GOLDEN=1 bin/wgf test-core --only "3D GOLDEN"
      ↓
adversarial review                of the diff: false PASS, fake approval, stale resume,
                                  wrong-commit release, orphan process, silent failure
      ↓
merge
```

- One module per change. Touching several unrelated modules at once needs a stated reason in
  the commit message.
- A change to `scripts/wgflib/`, `core/workflows/` or a schema's required fields is a **core
  change**: it needs the whole ladder and its own entry in `CHANGELOG.md`.
- A module may add optional fields to its own artifact's schema (additive, CHANGELOG entry). It
  may not relax a validation, a lineage rule or an evidence status to make itself pass.
- Never weaken an acceptance test to get green. A test that encoded a bug is changed in the same
  commit that fixes the bug, and the commit says so.
