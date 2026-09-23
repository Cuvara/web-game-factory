# Workflow Engine

The executable backbone of the Factory: a small kernel that runs a workflow definition step by
step, persists every change, and can be stopped, resumed, retried and routed without anyone
calling a step by hand. It ships with placeholder steps for every step type. Init
([init-module.md](init-module.md)) and verification
([verification-module.md](verification-module.md)) are real modules; discovery, strategy,
design, assets, development and SDK are separate modules that plug into it later —
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

  research → strategy → [G2 checkpoint] → design → init → assets → develop → sdk → verify → release
                                                                   ▲                   │ fail
                                                                   └───────────────────┘
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
timestamps, duration, last route, error and outputs. `state.json` is the whole truth; `wgf
status` renders it and holds nothing of its own. A run that is `RUNNING` on disk with no
process holding its lock is a crashed run, and is resumable.

## 5. Artifact flow

Steps never call each other. A step returns `ArtifactOutput(type, content, name=None,
metadata=None)`; the engine checks it against its contract, writes it to
`artifacts/<id>/v<n>.json`, and records only a reference in state:

```json
{"id": "qa-report", "type": "qa-report", "version": 2,
 "location": "artifacts/qa-report/v2.json", "checksum": "sha256:…",
 "content_hash": "sha256:…", "schema_version": "1.0.0",
 "produced_by": "verify", "created_at": "…", "metadata": {…}}
```

- `version` counts productions of that id in the run; every version is kept, and a second
  one is emitted as `ARTIFACT_UPDATED`.
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

`--run <run-id>` is the other way to continue: it runs a command's slice *inside* an existing
run, reusing its artifacts, and skips any step in that slice that already succeeded (`--force`
to redo). `wgf init --run <id>` twice executes `init` once.

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
grants every step a fresh budget. For `new-game` that is at most three develop → sdk →
verify passes per start or resume. Retries are bounded separately by `max_attempts`, and no
outcome but a retryable `FAILED` is ever retried, so there is no unbounded path. The graph is not assumed to be linear: any step can route
anywhere, and a human checkpoint with more than two choices is a branch.

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
`wgf-state.py` already enforce.

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
| `WORKFLOW_CANCELLED` | — |
| `STEP_STARTED` | `type`, `visit` |
| `STEP_COMPLETED` | `route`, `message`, `outputs`, `result` (the step's own small data) |
| `STEP_FAILED` | `will_retry`, `route`, `outputs` |
| `STEP_RETRIED` | `delay_seconds`, `max_attempts` |
| `STEP_SKIPPED` | `reason` |
| `STEP_WAITING` | `message`, `result` |
| `STEP_BLOCKED` | `message`, `result` |
| `STEP_LOG` | top-level `level`, `message`; `data` is the logged fields |
| `TRANSITION` | `route`, `outcome`, `kind` (`goto end abort block wait`), `to` |
| `DECISION_RECORDED` | `decision`, `decided_by`, `decided_at`, `visit`, `note` |
| `ARTIFACT_CREATED` | the `ArtifactRef` |
| `ARTIFACT_UPDATED` | the `ArtifactRef` (version ≥ 2) |

Consumers must ignore fields and events they do not know. `EventContract` fails if an event
is added without being documented here. The CLI's progress output is just another
subscriber; a UI, a monitor or an agent host subscribes the same way without the engine
changing, and a failing subscriber never stops a run.

`wgf status` renders `state.json`; `wgf logs` renders `events.jsonl`. Neither reconstructs
anything from console output.

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
common: --store DIR  --config PATH  --workflow ID|PATH  --json  --quiet
```

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
                max_delay_seconds: 60, max_visits: 5}
  agents:      {default: local}
  storage:     {directory: .factory, fsync: true}
  steps:       {modules: []}
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

All deterministic and offline.

## Security

The engine executes no code it was not given by the installation:

- A workflow file is data. A step `type` is a registry key — never imported, evaluated or
  resolved to a path — and must match `^[a-z][a-z0-9-]*(\.[a-z][a-z0-9-]*)*$`.
- YAML goes through `yamllite`, which refuses tags, anchors and aliases: there is no
  object-construction path.
- The only import of configurable code is `factory.steps.modules`, in the installation's own
  config file, and each entry must be a dotted Python identifier.
- Run ids and artifact ids become directory names, so both are validated before they touch a
  path; `..` and separators are refused.
- The kernel and CLI contain no `subprocess`, `eval`, `exec`, `shell=True` or `pickle`;
  `Security.test_the_kernel_executes_nothing` enforces it. `--mock-plan @FILE` reads a file
  the person running the command named.

## Known limits

- **Single machine.** The lock is a pid file; two hosts sharing a store are not coordinated.
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
