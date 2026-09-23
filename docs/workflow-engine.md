# Workflow Engine

The executable backbone of the Factory: a small kernel that runs a workflow definition step by
step, persists every change, and can be stopped, resumed, retried and routed without anyone
calling a step by hand. It ships with placeholder steps only. Discovery, strategy, design,
assets, development, SDK and verification are separate modules that plug into it later.

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
| `api.py` | `WorkflowAPI`: assembles an engine for the CLI |
| `mock.py`, `fixtures/` | Placeholder steps for every business step type |

### Relation to the lifecycle machines

These are two different things and must stay that way. `core/lifecycle/*.machine.yaml` say
what **state an entity is in** — an opportunity, a title, a release — and which transitions
are legal, behind which gates. A workflow says **which units of work run, in what order, and
where each result goes**. Each step names the lifecycle stage it serves (`stage:
title:design`), and `check-integrity.py` resolves it, but running a step does not move a
title. Advancing an entity still goes through `wgf-state.py`, its guards and its decision
records. A step implementation that wants to advance a title calls that, from inside the
step; the engine never will.

---

## 2. Workflow definition

`core/workflows/<id>.workflow.yaml` — data, read by `yamllite`, validated in full before any
run starts. The filename stem is the id.

```yaml
workflow:
  id: new-game
  version: 1
  start: research                    # default: first step
  untyped_artifacts: [scaffold-record, sdk-report]
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

Targets are step ids, `$end` (complete) or `$fail` (fail). The parser reports every problem
at once: unknown targets, duplicate ids, groups naming unknown steps, malformed retry, an
unqualified `stage`, a `start` that is not a step. `check-integrity.py` additionally checks
that every stage resolves to a machine state or stage procedure, that every gate exists, and
that every artifact type has a schema in `core/artifacts/` — or is listed under
`untyped_artifacts`, which is the visible list of contracts core does not have yet.

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

Steps never call each other. A step returns `ArtifactOutput(type, content)`; the engine
writes it to `artifacts/<id>/v<n>.json` and records only a reference in state:

```json
{"id": "qa-report", "type": "qa-report", "version": 2,
 "location": "artifacts/qa-report/v2.json", "checksum": "sha256:…",
 "content_hash": "sha256:…", "produced_by": "verify", "created_at": "…"}
```

`checksum` is over the file bytes and is verified on every read. `content_hash` is the
Factory's canonical digest (`provenance.schema.json#/$defs/hash`) when the artifact carries
provenance — the value a gate pins. Producing the same artifact again (a develop/verify loop)
is a new version, emitted as `ARTIFACT_UPDATED`; every version is kept.

The mock steps emit schema-valid instances of `opportunity`, `title-strategy`, `game-design`,
`asset-manifest`, `prototype-report`, `qa-report` and `release-manifest`, with provenance
whose `inputs` pin what they consumed by hash.

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
to redo). This is the idempotency guarantee — `wgf init --run <id>` twice scaffolds once. Each
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

Loops are bounded by `max_visits` per step; exceeding it blocks the run with a message, and
resuming grants another pass. The graph is not assumed to be linear: any step can route
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

A checkpoint tied to a reversible gate may be auto-approved when the run allows it —
`factory.checkpoints.auto_approve`, or every reversible gate under `--mock` unless
`--hold-gates`. **G4, G6 and G7 are never auto-approved and never accept a non-human
decision here**, whatever config says; the list is read from `irreversible: true` in
`core/lifecycle/gates.yaml`. This mirrors the rule `decision-record.schema.json` and
`wgf-state.py` already enforce.

## 10. Events and logs

Every change is an event on one bus: `WORKFLOW_STARTED`, `WORKFLOW_RESUMED`,
`WORKFLOW_PAUSED` (also emitted when a run parks as `WAITING`), `WORKFLOW_BLOCKED`,
`WORKFLOW_COMPLETED`, `WORKFLOW_FAILED`, `WORKFLOW_CANCELLED`, `STEP_STARTED`,
`STEP_COMPLETED`, `STEP_FAILED`, `STEP_RETRIED`, `STEP_SKIPPED`, `STEP_WAITING`,
`STEP_BLOCKED`, `STEP_LOG`, `TRANSITION`, `DECISION_RECORDED`, `ARTIFACT_CREATED`,
`ARTIFACT_UPDATED`.

Each is a flat JSON object — `ts, event, workflow_id, run_id, step_id, attempt, status,
duration_ms, error, data` — appended to `events.jsonl`, which is the structured log. The CLI's
progress output is just another subscriber. A UI, a monitor or an agent host subscribes the
same way without the engine changing, and a failing subscriber never stops a run.

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
  checkpoints: {auto_approve: []}
```

`storage.directory` resolves against the directory `wgf` is run from; `--store` overrides
it. `.factory/` is git-ignored — run state is instance data.

## 13. How a real module registers itself

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

`--mock` registers the placeholders *after* configured modules, so under `--mock` every step
type is a placeholder whether or not a real module exists. Without `--mock`, only configured
modules and the built-in checkpoint are available.

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
| `fixtures/workflows/` | The acceptance workflows: `verify-loop`, `human-checkpoint`, `retry` |

All deterministic and offline.

## Known limits

- **Single machine.** The lock is a pid file; two hosts sharing a store are not coordinated.
- **Steps run in-process and sequentially.** The definition format permits branching but not
  parallel fan-out; nothing in this phase needs it.
- **`scaffold-record` and `sdk-report` have no schema.** They are listed in
  `untyped_artifacts` until someone writes one.
- **Checkpoint decisions are recorded in run state, not as `decision-record` artifacts.** When
  a checkpoint stands for a lifecycle gate, the real gate module should emit the decision
  record and advance the entity through `wgf-state.py`.
