# Workflow Engine

The executable backbone of the Factory: a small kernel that runs a workflow definition step by
step, persists every change, and can be stopped, resumed, retried and routed without anyone
calling a step by hand. It ships with a placeholder for every step type. Discovery, strategy,
design, init ([init-module.md](init-module.md)), assets, development, review
([review-module.md](review-module.md)), SDK and verification
([verification-module.md](verification-module.md)) are real modules that plug into it;
`release` is still a placeholder —
**[workflow-module-contract.md](workflow-module-contract.md) is what they implement against.**

Standard library Python, like every other script here. No database, no toolchain.

```bash
bin/wgf new-game --mock                     # the whole workflow, placeholder steps
bin/wgf status                              # where the latest run stands
python -m unittest discover scripts/tests   # includes the acceptance tests below
```

`bin/wgf` is a three-line shim for `python3 scripts/wgf.py`. Put `bin/` on `PATH` to type
`wgf`.

---

## 1. Architecture

```
                          wgf CLI  (scripts/wgf.py)
                                  │
             ┌────────────────────┴────────────────────┐
     individual commands                         wgf new-game
  research, plan, init, assets,             (the whole workflow)
  develop, sdk, verify, release
             └────────────────────┬────────────────────┘
                                  ▼
                 WorkflowAPI  (workflow/api.py) ── factory.yaml
                                  │    assembles one engine; nothing else orchestrates
                                  ▼
               WorkflowEngine  (workflow/engine.py)
      resolve step ─ execute + retry ─ persist ─ route ─ next step
          │               │                │         │
          │               ▼                │         ▼
          │     AgentRuntime ◄── Task      │   WorkflowDefinition
          │     (local today)              │   core/workflows/new-game.workflow.yaml
          │               │                │
          │               ▼                ▼
          │     StepRegistry ─► step    RunStore  .factory/workflows/<run-id>/
          │     type → impl             state.json · events.jsonl · artifacts/
          │     (mock | modules)               ▲
          ▼                                    │
      EventBus ──► store (events.jsonl = structured log)
               └─► CLI progress, and later a UI / monitor / agent host

  research → strategy → [G2 checkpoint] → design → init → assets → develop → review → sdk → verify → release
                                                                   ▲ ▲ request-  │              │ fail
                                                                   │ └─ changes ─┘              │
                                                                   └────────────────────────────┘
                                                                                        │ pass
                                                                                        ▼
                               release-manifest (draft) ─► game repo CI ─► G5 ─► G6 ─► publish
                               ─────────── Factory ends here ───────────   (outside the engine)
```

The boundary the whole design protects: **the engine knows `Workflow`, `WorkflowStep`,
`WorkflowContext`, artifacts in and out, `StepResult` and run state — and nothing else.** It
does not know what research is. `test_engine_source_names_no_step_type` fails if a step type or
route label ever appears as a literal in `engine.py`.

| Module (`scripts/wgflib/workflow/`) | Holds |
|---|---|
| `model.py` | Statuses, `StepResult`, `ArtifactRef`, `StepState`, `RunState` |
| `definition.py` | Parser and validator for `*.workflow.yaml` |
| `step.py` | `WorkflowStep`, `StepInputs`, `StepRegistry` |
| `context.py` | `WorkflowContext`, `StepLogger` |
| `runtime.py` | `Task`, `AgentRuntime`, `LocalRuntime` |
| `engine.py` | `WorkflowEngine` |
| `events.py` | Event names and the `EventBus` |
| `store.py` | `RunStore`: state, events, artifacts, lock |
| `config.py` | `workspace/config/factory.yaml` |
| `checkpoint.py` | The built-in `human-checkpoint` step type |
| `contracts.py` | Structural artifact checks against `core/artifacts/` schemas |
| `api.py` | `WorkflowAPI`: assembles an engine for the CLI |
| `mock.py`, `fixtures/` | Placeholder steps for every business step type |

### Two state machines, kept apart

| | Workflow state | Lifecycle state |
|---|---|---|
| Describes | a *run* of work | an *entity* — opportunity, title, release, publication |
| Values | `PENDING RUNNING WAITING PAUSED FAILED BLOCKED COMPLETED CANCELLED` | `concept strategy design … live abandoned sunset` |
| Defined in | `scripts/wgflib/workflow/model.py` | `core/lifecycle/*.machine.yaml` |
| Stored in | `.factory/workflows/<run>/state.json` | `workspace/titles/<id>/state.json` |
| Moved by | the engine | `wgf-state.py` only — guards, gates, decision records |

A workflow says **which units of work run, in what order, and where each result goes**. A
machine says **what state an entity is in** and which transitions are legal. Each step names
the lifecycle stage it serves (`stage: title:design`) and `check-integrity.py` resolves it,
but running a step — or completing, failing or cancelling a whole run — **never mutates
lifecycle state**. The kernel does not import the workspace or guard modules and never writes
`workspace/`; `LifecycleSeparation` in `test_workflow_contracts.py` runs a full mock workflow
and asserts `workspace/` is byte-for-byte unchanged, and that no run status shares a name
with a lifecycle state. A step that must advance a title does so only through `wgf-state.py`,
with its guards and, on a gated edge, a decision record.

---

## 2. Workflow definition

`core/workflows/<id>.workflow.yaml` — data, read by `yamllite`, validated in full before any
run starts. The filename stem is the id.

```yaml
workflow:
  id: new-game
  version: 1
  start: research                    # default: first step
  untyped_artifacts: []             # temporary gaps only; see below
  defaults:
    retry: {max_attempts: 3, backoff: exponential, delay_seconds: 2}
    max_visits: 3
  groups:
    plan: [strategy, strategy-review, design]
  steps:
    - id: verify
      type: verify                   # which registered implementation runs it
      stage: release:qa              # lifecycle stage served; checked by check-integrity
      inputs: [prototype-report]     # artifact types it reads
      outputs: [qa-report]           # artifact types it must produce on success
      retry: {max_attempts: 2}
      with: {}                       # free-form parameters handed to the step
      on:
        fail: develop                # route label -> target
      next: release                  # success target; default is the next step listed
```

Targets are step ids, `$end` (complete) or `$fail` (fail). Step types are kebab-case and
may be namespaced by module (`discovery.research`); a type is only a registry key. The
parser reports every problem at once: unknown targets, duplicate ids, groups naming unknown steps, malformed retry, an
unqualified `stage`, a `start` that is not a step. `check-integrity.py` additionally checks
that every stage resolves to a machine state or stage procedure, that every gate exists, and
that every artifact type has a schema in `core/artifacts/` — or is listed under
`untyped_artifacts`, a visible, temporary gap that the integrity check reports on every run
and the engine accepts only as a non-empty JSON object. `new-game` lists none.

Retry and loop settings layer: `factory.execution` in config, then the workflow's
`defaults`, then the step.

## 3. Step interface

```python
class WorkflowStep:
    type = "verify"
    def execute(self, inputs: StepInputs, context: WorkflowContext) -> StepResult: ...
```

`inputs.refs[type]` is the newest `ArtifactRef` of each declared input type the run holds;
`inputs.load(type)` reads it (and refuses it if the file changed since it was recorded);
`inputs.missing` lists declared types the run does not have. Whether a missing input is fatal
is the step's decision — `wgf verify` run on its own legitimately has nothing upstream.

A step returns a `StepResult`:

| Outcome | Meaning | Retried | Unrouted default |
|---|---|---|---|
| `SUCCESS` | Done; artifacts attached | never | `next`, else the following step, else `$end` |
| `FAILED` | Could not do it. `retryable=False` if trying again cannot help | per policy | run `FAILED` |
| `BLOCKED` | Cannot proceed without an external change | never | run `BLOCKED` |
| `WAITING_FOR_INPUT` | Needs data that is not there yet | never | run `WAITING` |
| `WAITING_FOR_HUMAN` | Needs a person's decision | never | run `WAITING` |

`route` is an optional label the definition can branch on. A verification that ran and
found defects returns `FAILED`, `route="fail"`, `retryable=False`: it is a result, retrying
cannot change it, and it routes to `develop` only because the workflow file says so.

The engine also enforces the contract: a step that produces an artifact type it did not
declare, or succeeds without a declared output, fails non-retryably.

## 4. State machine

```
Run      PENDING → RUNNING → COMPLETED
                      │  ├─→ FAILED     (retries exhausted, or routed to $fail)   ─┐
                      │  ├─→ BLOCKED    (blocked step, rejection, loop limit)       │ resume
                      │  ├─→ WAITING    (a step is waiting for input or a person)   ├──────→ RUNNING
                      │  └─→ PAUSED     (`wgf pause`, honoured between steps)       │
                      └────→ CANCELLED  (`wgf cancel`; terminal)                   ─┘

Step     PENDING → RUNNING → SUCCESS | FAILED | BLOCKED | WAITING      (+ SKIPPED as an event)
```

Every step keeps `attempts` (this visit), `executions` (whole run), `visits` (times entered),
timestamps, duration, last route, error and outputs, and — for the execution in progress —
`pid` (the child process it waits on), `last_activity_at` and `last_event`, fed by
`context.progress` and by every `wgflib.procs.run` the step makes. `state.json` is the whole
truth; `wgf status` renders it and holds nothing of its own. A run that is `RUNNING` on disk
with no process holding its lock is a crashed run, and is resumable.

### Liveness

`wgf status` adds one derived word, computed by the pure `model.derive_liveness(state,
lock_owner, now, hung_after_seconds)` and never stored:

| Liveness | Means | What to do |
|---|---|---|
| `running` | `RUNNING`, a live process holds the lock, activity within the threshold | wait |
| `hung` | `RUNNING`, lock held, no sign of life for longer than `factory.execution.hung_after_seconds` (default 300) | inspect the child `pid`; `wgf cancel` terminates its tree |
| `stale` | `RUNNING` on disk but no live process holds the lock: the driver crashed | `wgf <cmd> --resume <run>` |
| `pending` `waiting` `paused` `blocked` `failed` `completed` `cancelled` | the run status itself | as the status says |

"Activity" is the newest of the step's `last_activity_at`, its `started_at` and the run's
`updated_at`. Heartbeats from a child process arrive every `heartbeat_seconds` and are
persisted at most every 5 s, so a threshold well above both is what makes `hung` mean hung.

## 5. Artifact flow

Steps never call each other. A step returns `ArtifactOutput(type, content, name=None,
metadata=None)`; the engine checks it against its contract, writes it to
`artifacts/<id>/v<n>.json`, and records only a reference in state:

```json
{"id": "qa-report", "type": "qa-report", "version": 2,
 "location": "artifacts/qa-report/v2.json", "checksum": "sha256:…",
 "content_hash": "sha256:…", "schema_version": "1.0.0",
 "produced_by": "verify", "created_at": "…", "metadata": {…}, "seq": 12}
```

- `version` counts productions of that id in the run; every version is kept, and a second
  one is emitted as `ARTIFACT_UPDATED`. It is always one more than the versions state has
  recorded — see *Persistence and atomicity* below for what that means after a crash.
- `seq` orders every artifact in the run by production. "The newest artifact of a type" —
  what a step's `inputs` resolve to — is the highest `seq`, not the latest timestamp: two
  artifacts can be written in the same millisecond, and a clock can step backwards. Refs
  from before `seq` existed sort first, then by `created_at`.
- `schema_version` is the contract version the content claims (`provenance.schema_version`).
- `checksum` is over the file bytes and is verified on every read.
- `content_hash` is the Factory's canonical digest (`provenance.schema.json#/$defs/hash`) —
  the value a gate pins.
- Each step's `consumed` list (and each trail entry) records the exact `id@vN` of every input
  it read.

Before writing, the engine applies `contracts.ArtifactContracts`: the type must have a
schema (or be listed as untyped), the content must have every required top-level key and no
forbidden one, and provenance must name the type and reproduce its hash. A violation is a
non-retryable `FAILED` and nothing is written. Full JSON Schema validation remains ajv's job.

The same boundary is checked on the way **in**. Before a step executes, every input it
resolved is read back — its checksum verified — and, when the engine has a validator,
checked against its contract again (a run resumed under a newer definition or schema may
hold inputs that no longer satisfy it). An input that is missing, changed on disk or fails
its contract fails the step non-retryably before it runs, with a message naming the input
type, `id@vN`, the step that produced it and the problems. A validator that raises is
reported the same way instead of escaping the engine, and so is a step class whose
constructor raises.

### Persistence and atomicity

| What | How it is written | What a crash can leave |
|---|---|---|
| `state.json`, `artifacts/<id>/v<n>.json`, `LATEST`, `pause`/`cancel` | to `<name>.tmp`, flushed, fsync'd (`storage.fsync`), renamed over the target, directory fsync'd | the old file or the new one; possibly a `.tmp` beside it |
| `events.jsonl` | appended | a partial last line |
| `lock` | `O_EXCL` create, then the pid | an empty lock file |

- **One save per execution.** A step's artifact files are written first; then its artifact
  refs, status and trail entry are saved in a single `state.json` write; only then are the
  `ARTIFACT_*` and `STEP_*` events emitted. A crash between the file writes and that save
  leaves files state does not know about (orphans) and a log that does not mention them.
  Resume re-executes the step, which writes the same version number again, replacing the
  orphan, and records it once — with a `STEP_LOG` warning that an unrecorded file was
  replaced. A failure to write an artifact (disk full) is a retryable `FAILED` that
  records nothing.
- **Unreadable state is an error, not a guess.** `load` of a truncated or non-object
  `state.json` raises `StoreError` naming the file, and says so if a `state.json.tmp` from an
  interrupted write sits beside it. `wgf runs` lists such a run as `UNREADABLE` instead of
  hiding it.
- **A torn log is readable.** `read_events` skips a line that is not a JSON event object and
  reports it (`wgf logs` prints a warning on stderr); the next append starts on a fresh line,
  so the torn line never swallows a later event. State is never derived from events, so
  duplicate or lost event lines cannot change a run.
- **The lock.** A lock naming a live process — or this process, while it drives the run on
  any thread — is refused (`RunLocked`); there is no reentrant acquire. A lock whose owner is
  dead, or an empty one older than 5 s, is stale and is taken over — but only under a second
  `O_EXCL` guard (`lock.takeover`) and only after re-reading it there, so two processes that
  both saw the same dead owner cannot both end up holding the run. `release` never removes a
  lock it does not own. `wgf pause` / `wgf cancel` of a run nobody drives change its state
  while holding the lock; of a driven run, they leave a request file for the driver.

The mock steps emit schema-valid instances of all nine output types, with provenance whose
`inputs` pin what they consumed by hash. The step-by-step input/output contract is in
[workflow-module-contract.md §5](workflow-module-contract.md#5-outputs).

## 6. Retry

A `FAILED` result that is `retryable` is re-executed up to `max_attempts` for that visit,
waiting `delay_before(attempt)` between tries — `none`, `fixed`, or `exponential` (doubling
from `delay_seconds`, capped at `max_delay_seconds`). An exception raised by a step is a
retryable failure. No other outcome is ever retried, so nothing loops on a retry. Mock runs
skip the waiting: a placeholder that fails instantly teaches nothing by sleeping.

## 7. Resume

```bash
wgf new-game --resume <run-id>                       # continue from the stopped step
wgf new-game --resume <run-id> --from develop        # rerun from a given step
wgf new-game --resume <run-id> --decision approve    # answer a waiting checkpoint
```

Resume continues from the cursor. Steps that succeeded are not executed again; the stopped
step gets a fresh attempt budget and every step a fresh loop budget. A run started with
`--mock` resumes with the mocks; a run remembers its own definition, so fixture workflows
resume too.

Resume refuses a run another live process — or another thread of this one — is driving
(`RunLocked`), before changing anything. A `stale` run (its driver died) is resumed by taking
over the dead lock; the step that was interrupted runs again, nothing before it does. A pause
requested of a driver that then died is cleared by the resume, which is its answer; a pending
cancel is still honoured.

`--run <run-id>` is the other way to continue: it runs a command's slice *inside* an existing
run, reusing its artifacts, and skips any step in that slice that already succeeded (`--force`
to redo). `wgf init --run <id>` twice executes `init` once. It refuses a `RUNNING` run (resume
it) and a cancelled one, and like resume it grants every step a fresh loop budget.

`--decision` must be a plain label (letters, digits, `- _ . :`, at most 64 characters) and a
note must contain no NUL; anything else is refused before the run is touched.

**The engine guarantees state-level idempotency. The step implementation is responsible for
side-effect idempotency.** The engine cannot make creating a repository or uploading a file
happen once; it can only make sure a completed step is not re-executed, and hand the step
what it needs to find its own earlier work. Each
execution also gets `context.idempotency_key` (`<run>:<step>:<visit>`, stable across attempts,
crashes and resumes) and `context.previous_outputs`, so a step with an outside side effect can
find what it already made.

## 8. Failure routing and loops

Routing is looked up in the step's `on:` map — first by the result's route label, then by
its outcome — and falls back to the outcome's default. An unrouted `fail` therefore fails
the run instead of guessing. A loop is just a route that points backwards:

```yaml
- id: verify
  on:
    fail: develop
```

**Loop safety.** Every step has `max_visits` (new-game: 3, from `defaults`; installation
default 5). Entering a step more often than that since the run last started or resumed stops
the run as `BLOCKED` with a `loop limit` message instead of looping; a person resuming it
grants every step a fresh budget. For `new-game` that is at most three develop → review →
sdk → verify passes per start or resume, and a reviewer that never approves blocks the run
on its third request for changes instead of looping. Retries are bounded separately by `max_attempts`, and no
outcome but a retryable `FAILED` is ever retried, so there is no unbounded path. The graph is not assumed to be linear: any step can route
anywhere, and a human checkpoint with more than two choices is a branch. When `--run` skips
completed steps, each is skipped at most once per drive and every entry after the first
counts against `max_visits`, so even a cycle of `next:` edges through completed steps ends
`BLOCKED` rather than spinning.

**Cancel.** `wgf cancel` of a driven run is honoured between steps *and* while a step runs:
the step's child processes started through `wgflib.procs` poll `context.should_stop()` and
are terminated, tree and all; when the step returns, the engine does not retry it (whatever
it returned) and ends the run `CANCELLED` — never `FAILED`. The interrupted step keeps its
reported status with the message `cancelled while running`.

## 9. Human checkpoints

`type: human-checkpoint` is the one step type the kernel ships, because pausing for a person
is a workflow property rather than a business one.

```yaml
- id: strategy-review
  type: human-checkpoint
  with:
    gate: G2
    choices: [approve, reject]
  on: {}                 # e.g. rework: strategy
```

With no decision recorded it returns `WAITING_FOR_HUMAN`; the run parks as `WAITING` and
`wgf status` prints the command to answer it. `approve` (or any other choice) continues with
that choice as the route; `reject` is `BLOCKED` unless routed. A decision answers one visit,
so a loop back through the checkpoint waits again.

`WAITING_FOR_HUMAN` is not a failure: no `STEP_FAILED` or `WORKFLOW_FAILED` is emitted, and
nothing is retried.

A checkpoint tied to a reversible gate may be auto-approved when the run allows it —
`factory.checkpoints.auto_approve` (empty by default), or, under `--mock`, only the
reversible gates the workflow's own checkpoints name (`G2` for `new-game`) unless
`--hold-gates`. A checkpoint with no gate is never auto-approved. **G4, G6 and G7 are never auto-approved and never accept a non-human
decision here**, whatever config says; the list is read from `irreversible: true` in
`core/lifecycle/gates.yaml`. This mirrors the rule `decision-record.schema.json` and
`wgf-state.py` already enforce. The comparison ignores case and surrounding space (`g4` is
G4), and a gate `gates.yaml` does not define is never auto-approved either.

Who decided is recorded as `decided_by`. A `--decision` given to the CLI is `human`, unless
the command runs inside a process tree a step started (it, or one of its ancestors, carries
`WGF_PROC_TAG`): a developer or reviewer agent answering its own run is `automation`, and
G4/G6/G7 refuse it. And a decision is only *used* when `events.jsonl` holds the
`DECISION_RECORDED` event the engine emitted with it — one written into `state.json` alone
answers nothing, and the checkpoint waits again (`wgflib/workflow/integrity.py`).

## 10. Events and logs

Every change is an event on one bus. Each is a flat JSON object appended to `events.jsonl`,
which is the structured log:

| Field | Always | Meaning |
|---|---|---|
| `format` | yes | Event format version, currently `1`; bumped only if a field is removed or changes meaning |
| `ts` | yes | UTC ISO-8601 with milliseconds |
| `event` | yes | One of the names below |
| `workflow_id`, `run_id` | yes | The run |
| `step_id` | on `STEP_*`, `ARTIFACT_*`, `TRANSITION`, `DECISION_RECORDED` | The step |
| `attempt`, `status`, `duration_ms`, `error` | where they apply | Omitted when not |
| `data` | often | Event-specific payload, below |

| Event | `data` |
|---|---|
| `WORKFLOW_STARTED` | `scope`, `start` |
| `WORKFLOW_RESUMED` | `from_status`; `from_step`, `scope`, `force`, `definition_version` when relevant |
| `WORKFLOW_PAUSED` | `reason` (`requested`, `waiting_for_human`, `waiting_for_input`), `next_step` or `message` |
| `WORKFLOW_BLOCKED` | `message` (a blocked step, a rejection, or the loop limit) |
| `WORKFLOW_COMPLETED` | `exit`: `{step, route, outcome, next}` |
| `WORKFLOW_FAILED` | `message` |
| `WORKFLOW_CANCELLED` | — (`step_id` is the cursor when the cancel was honoured) |
| `STEP_STARTED` | `type`, `visit` |
| `STEP_COMPLETED` | `route`, `message`, `outputs`, `result` (the step's own small data) |
| `STEP_FAILED` | `will_retry`, `route`, `outputs` |
| `STEP_RETRIED` | `delay_seconds`, `max_attempts` |
| `STEP_SKIPPED` | `reason` |
| `STEP_WAITING` | `message`, `result` |
| `STEP_BLOCKED` | `message`, `result` |
| `STEP_LOG` | top-level `level`, `message`; `data` is the logged fields (the engine itself logs one `warning` when it replaces an unrecorded artifact file: `data.artifact` = `id@vN`) |
| `STEP_PROGRESS` | `kind` (`started spawned heartbeat timeout idle-timeout cancelled cleanup exited`), plus `pid`, `elapsed_s`, `idle_s`, `killed`, `returncode` as they apply |
| `TRANSITION` | `route`, `outcome`, `kind` (`goto end abort block wait`), `to` |
| `DECISION_RECORDED` | `decision`, `decided_by`, `decided_at`, `visit`, `note` |
| `ARTIFACT_CREATED` | the `ArtifactRef` |
| `ARTIFACT_UPDATED` | the `ArtifactRef` (version ≥ 2) |

Consumers must ignore fields and events they do not know. `EventContract` fails if an event
is added without being documented here. The CLI's progress output is just another
subscriber; a UI, a monitor or an agent host subscribes the same way without the engine
changing, and a failing subscriber never stops a run.

`wgf status` renders `state.json`; `wgf logs` renders `events.jsonl`. Neither reconstructs
anything from console output. An `ARTIFACT_*` event is emitted only after the state that
records the artifact is saved, so the log never names an artifact state does not hold.

## 11. CLI

```
wgf new-game [--mock] [--from STEP] [--project ID]    the whole workflow
wgf research | plan | init | assets | develop | sdk | verify | release [--mock]
wgf <cmd> --resume RUN [--from STEP] [--decision CHOICE --note TEXT]
wgf <cmd> --run RUN [--force]                          a slice inside an existing run
wgf <cmd> --mock --mock-plan '{"verify": ["fail"]}'   script placeholder outcomes
wgf <cmd> --mock --hold-gates                          stop at checkpoints
wgf status [RUN] [--json]    wgf logs [RUN] [--json] [--step S]    wgf runs
wgf pause RUN                wgf cancel RUN
wgf test-core [--only CATEGORY]... [--json]            the Core Acceptance Suite
common: --store DIR  --config PATH  --workflow ID|PATH  --json  --quiet
```

`wgf status` ends with the current step — the cursor, or the last step executed once the
run has finished:

```
Step:     develop  attempt 2, visit 1  RUNNING
Liveness: running  (driver pid 41022; child pid 41090; last event heartbeat)
Started:  2026-09-24T04:04:31.611Z   elapsed 3m12s
Activity: 2026-09-24T04:07:40.020Z   3s ago
```

`--json` prints `state.json` plus a `liveness` object with `run_id`, `run_status`,
`liveness`, `driver_pid` (the lock owner), `step`, `attempt`, `visit`, `status`,
`started_at`, `last_activity_at`, `pid`, `last_event`, `elapsed_seconds`, `idle_seconds` and
`hung_after_seconds`. `RunState.from_dict` ignores the extra key.

### `wgf test-core`

Runs the Core Acceptance Suite category by category — `WORKFLOW`, `AGENTS`, `CONTRACTS`,
`VERIFY`, `RELEASE`, `2D GOLDEN`, `3D GOLDEN`, `PROCESS CLEANUP`, `SECURITY` — and prints a
table of results and counts. The category → test-module mapping is data, in
`scripts/tests/core_suite.py`.

| Result | When |
|---|---|
| `PASS` | tests ran and none failed or errored |
| `FAIL` | any failure or error, including a module that does not import |
| `SKIP` | zero tests ran, or every test that ran was skipped |
| `MISSING` | a module the mapping names does not exist yet |

The exit status is `1` if any category is `FAIL` or `MISSING` — an incomplete suite can
never look green — else `0`. `--only WORKFLOW` (repeatable, case-insensitive) runs a subset;
`--json` prints `{"ok", "categories": [...]}` with the same counts and the failure
tracebacks. It runs in-process with `unittest`; nothing is installed.

The run commands are generated from the workflow's own step ids and group names:
`new-game` is the workflow, `plan` is a group (`strategy → strategy-review → design`), the
rest are single steps. There is one `cmd_run`, one `WorkflowAPI.run`, one engine. Adding a
step to the YAML adds a command.

Exit status: `0` completed, `1` failed / blocked / cancelled (or a slice that left its scope on
a failure), `2` usage, `3` waiting or paused.

`wgf release` prepares a release — a `release-manifest` in state `draft` — and stops.
Building, packaging and publishing are the game repository's CI, behind G5 and G6, and are
deliberately outside the engine.

### `wgf new-game`

```
$ bin/wgf new-game --mock
Run new-game-20260923-051421-470ce6: research -> strategy -> strategy-review -> design -> …
✓ research  47ms
…
✓ release  8ms

✓ research
✓ strategy
✓ strategy-review
✓ design
✓ init
✓ assets
✓ develop
✓ sdk
✓ verify
✓ release

Status: COMPLETED

Workflow completed successfully.
```

`--mock-plan` scripts outcomes per step execution (`success`, `pass`, `fail`, `failed`,
`fatal`, `blocked`, `waiting`, `raise`, or any route label), so every failure path is
reproducible from the command line:

```bash
wgf new-game --mock --mock-plan '{"develop": ["failed","failed","failed"]}'  # FAILED at develop
wgf new-game --resume <run-id>                                              # completes; research..assets not rerun
wgf new-game --mock --mock-plan '{"verify": ["fail"]}'                      # develop→sdk→verify loops once
wgf new-game --mock --hold-gates                                            # WAITING at strategy-review
```

## 12. Configuration

`workspace/config/factory.yaml` — every key optional:

```yaml
factory:
  workflow:    {default: new-game}
  execution:   {max_attempts: 3, backoff: exponential, delay_seconds: 2,
                max_delay_seconds: 60, max_visits: 5,
                hung_after_seconds: 300}      # when `wgf status` calls a quiet step hung
  agents:      {default: local}
  storage:     {directory: .factory, fsync: true}
  steps:       {modules: [wgf_discovery, wgf_strategy, wgf_init, wgf_assets, wgf_develop,
                          wgf_verification, wgf_design, wgf_sdk]}
  design:      {author: archetype}   # read by the design module, not the engine
  checkpoints: {auto_approve: []}
```

`storage.directory` resolves against the directory `wgf` is run from; `--store` overrides
it. A module may read its own section from the same file — `factory.init` and
`factory.verification` configure those modules; the engine ignores keys it does not know.
`.factory/` is git-ignored — run state is instance data.

A step module may own a section of its own, which the engine passes through untouched in
`context.config`: `develop:` belongs to the development module
([development-module.md](development-module.md)).

## 13. How a real module registers itself

The full contract is [workflow-module-contract.md](workflow-module-contract.md). In short:

1. Write a module with step classes and a `register` function:

   ```python
   from wgflib.workflow import StepResult, ArtifactOutput, WorkflowStep

   class ResearchStep(WorkflowStep):
       type = "research"
       def execute(self, inputs, context):
           opportunity = ...                       # the real work
           return StepResult.success([ArtifactOutput("opportunity", opportunity)])

   def register(registry):
       registry.register("research", ResearchStep)
   ```

2. List it in `factory.steps.modules` (it must be importable — on `PYTHONPATH`, or a package
   under `scripts/`).
3. Run without `--mock`. The engine refuses to start a run whose scope contains a step type
   nothing implements, before creating any state.

`scripts/wgf_discovery/` is the shipped, tested example: the `research` step, registered
from `factory.steps.modules`, with its own evidence collectors and fixtures.

`--mock` registers the placeholders *after* configured modules, so under `--mock` every step
type is a placeholder whether or not a real module exists. Without `--mock`, only configured
modules and the built-in checkpoint are available.

Installed modules include `wgf_discovery`, `wgf_init`, `wgf_assets`, `wgf_develop` and `wgf_verification` (each has its own doc or docstring), and:

**`wgf_design`** (`scripts/wgf_design/`) implements `design`. It reads the
title-strategy and the pinned platform profiles, has an *author* write the creative draft
(the built-in `archetype` author is offline and deterministic; `factory.design.author`
selects another by name), derives scope tiers and SDK touchpoints, refuses a draft whose MVP
cannot be built without guessing, and evaluates the design-consistency rules. A blocking
breach returns `FAILED` with route `descope` and the design persisted as evidence.

**`wgf_sdk`** (`scripts/wgf_sdk/`) implements `sdk`. With a game-design and a
scaffold-record in the run it first integrates the template's platform SDK into the game —
a gameplay layer, the develop step's seam and `main.ts` wired to the `Platform` interface,
checked by its own mock suite. Then it reads the game repository's `game.config.yaml` and the
pinned platform profiles, runs the repository's SDK conformance suite against mocked portal
SDKs (optionally the browser smoke), and writes the sdk-report per platform and feature. It
never publishes. See [platform-architecture.md](platform-architecture.md) and
[platform-sdk-verification.md](platform-sdk-verification.md).

Rules for a step implementation:

- Read only `inputs`; never another step, never the run directory's state.
- Return every declared output on success, with `provenance` for any type that has a schema.
- Put side effects outside the run directory behind `context.idempotency_key`.
- Return `FAILED` with `retryable=False` for failures that will recur; raise for ones that
  might not.
- Never pick a provider in `core/`. A runtime that delegates to an agent host is an
  `AgentRuntime` subclass in the module that registers it, added to `runtime.RUNTIMES`, and
  selected by `factory.agents.default`.

## 14. Tests

```bash
python -m unittest discover scripts/tests
```

| File | Covers |
|---|---|
| `test_workflow_definition.py` | Parser, refusals, scopes, retry policy layering and delays |
| `test_workflow_engine.py` | Engine against scripted test doubles: artifacts, events, retry, permanent failure, resume, crash recovery, idempotency, routing, loop limit, checkpoints, irreversible gates, pause/cancel, store integrity and locking |
| `test_workflow_cli.py` | `wgf` as a subprocess with the real mocks: `new-game --mock`, every individual command, chaining slices in one run, retry, permanent failure + resume, verification loop, human checkpoint, status and logs |
| `test_workflow_contracts.py` | The gate before module work: an external module plugged in through config; artifact contract (versions, consumption, invalid and untyped artifacts, path-shaped ids); lifecycle separation; security; every run status; configuration-driven routing; event contract; one engine behind every command; docs match the workflow |
| `fixtures/workflows/` | The acceptance workflows: `verify-loop`, `human-checkpoint`, `retry` |
| `test_core_workflow.py` | Core v1 acceptance, one named scenario per class: happy path, failure, retry, resume, pause, cancel (between steps, and mid child process), human gate, max_visits, verify→develop loop, stale-run resume, concurrent-run lock refusal, determinism; input contracts, continue_in, liveness, `wgf status` and `wgf test-core` |
| `test_core_persistence.py` | Interrupted writes (rename/fsync failing), unreadable state, torn and duplicated event logs, a crash between an artifact write and the state save, lock takeover races, hostile run/artifact ids, decisions and definitions |
| `core_suite.py` | The Core Acceptance Suite mapping `wgf test-core` runs (data, not tests) |

All deterministic and offline. The cancel test starts a real `sleep`; the lock-race test
starts six Python processes.

## Security

The engine executes no code it was not given by the installation:

- A workflow file is data. A step `type` is a registry key — never imported, evaluated or
  resolved to a path — and must match `^[a-z][a-z0-9-]*(\.[a-z][a-z0-9-]*)*$`.
- YAML goes through `yamllite`, which refuses tags, anchors and aliases: there is no
  object-construction path.
- The only import of configurable code is `factory.steps.modules`, in the installation's own
  config file, and each entry must be a dotted Python identifier.
- Run ids and artifact ids become directory names, so both are validated (whole-string
  match, so a trailing newline is refused too) before they touch a path; `..`, separators,
  NUL and whitespace are refused. An artifact `location` read back from `state.json` must be
  `artifacts/<id>/v<n>.json`, so an edited state file cannot point a read outside the run.
  A `LATEST` pointer that is not a valid run id is ignored. Request files are a closed set
  (`pause`, `cancel`).
- Step ids, types, stages and route labels in a definition are whole-string matched too, and
  a malformed shape (a list where a target belongs, `on:` that is not a mapping) is a
  `DefinitionError` listing it — never an exception from inside the parser.
- Decisions, `decided_by` and notes are checked before a run is touched (see §7).
- `resume` and `continue_in` refuse a `state.json` the engine could not have written
  (`integrity.state_problems`): an unknown status, a cursor naming no step, negative or
  non-integer counters, `loop_base` above `visits`, an artifact version that is not at its
  canonical location or not numbered 1..n, a step's outputs naming a version state no
  longer records (a failed report's ref deleted to expose the passing one before it), or a
  decision for a visit that never happened. This catches inconsistent edits. A writer who
  rewrites state, artifacts and events *consistently* is not detectable locally; the
  Security category of the Core Acceptance Suite (`test_core_security.py`) lists what is
  and is not defended.
- The kernel and CLI contain no `subprocess`, `eval`, `exec`, `shell=True` or `pickle`;
  `Security.test_the_kernel_executes_nothing` enforces it. `--mock-plan @FILE` reads a file
  the person running the command named.

## Known limits

- **Single machine.** The lock is a pid file; two hosts sharing a store are not coordinated.
  One residual window remains in the takeover: a process killed *inside* the guarded
  re-check (microseconds) leaves a `lock.takeover` naming a dead pid, which the next taker
  clears unguarded. A pid reused by an unrelated process makes a dead driver's lock look
  live; `wgf status` then says `running` or `hung`, and removing the lock file by hand is the
  way out.
- **Orphaned grandchildren of a killed driver.** `wgflib.procs` takes a step's process tree
  down on every exit it sees, including Ctrl-C; a driver killed with SIGKILL cannot, and a
  resumed step does not look for survivors of the previous execution.
- **Steps run in-process and sequentially.** The definition format permits branching but not
  parallel fan-out; nothing in this phase needs it.
- **Artifact checks are structural.** Top-level required and forbidden keys and provenance
  only; nested shapes are ajv's job in each module's tests.
- **Checkpoint decisions are recorded in run state, not as `decision-record` artifacts.** When
  a checkpoint stands for a lifecycle gate, the real gate module should emit the decision
  record and advance the entity through `wgf-state.py`.
- **CLI test runtime** (~30 s for `test_workflow_cli.py`) is interpreter start-up: about
  0.25 s per `wgf` process, most of it importing modules from the Windows-mounted checkout,
  against about 0.4 s for a whole mock `new-game`. It is not engine cost. The tests read run
  state in-process rather than spawning `wgf status` for each inspection.
- **Baseline failures outside this code.** `test_hashing.AgreesWithTheGameRepoImplementation`
  errors when `../web-game-template` has no `node_modules` (`Cannot find package 'yaml'`).
  It predates the engine; `pnpm install` in the template resolves it.

## Upstream steps cannot be stepped over

`continue_in` (`wgf <step> --run <id>`) and `resume --from <step>` start a step inside an
existing run. Both refuse (EngineError, nothing executes) when any step before it in the
definition is BLOCKED, WAITING or FAILED in that run, or when a step before it whose `with:`
names a `gate` has not succeeded in that run. That is what keeps `wgf init --run <id>` from
scaffolding a repository after G3 was rejected, or while G4 is unanswered. A fresh run of a
single step (`wgf verify`) has no upstream in its run and is not affected; each module still
refuses inputs it cannot trust.

A resume whose cursor sits on a step already recorded as SUCCESS - the driver died between
recording the success and moving on - follows that step's recorded route without executing
it again. Only a run BLOCKED at the loop limit re-enters its cursor step ("one more pass").

A run whose event log cannot be written (disk full, permissions) ends FAILED with the reason:
decisions are corroborated from `events.jsonl`, so carrying on would silently ignore them.

