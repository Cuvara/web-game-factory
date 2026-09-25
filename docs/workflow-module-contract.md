# Workflow Module Contract

How to implement a real workflow step — discovery, strategy, design, init, assets,
development, SDK or verification — against the workflow kernel, without touching the kernel.

Read [workflow-engine.md](workflow-engine.md) for how the engine works. This document is
what a module owes the engine, and what the engine promises back.

> **A workflow module owns its domain logic. The workflow engine owns orchestration. A module
> must not modify the workflow engine merely to implement domain behaviour.**

| A module owns | The engine owns |
|---|---|
| Discovery — market research logic | execution |
| Strategy — game opportunity analysis | state and its persistence |
| Design — GDD / game design logic | routing and transitions |
| Assets — asset search and generation pipeline | retry and backoff |
| Development — PixiJS / Three.js game implementation | resume and idempotent re-entry |
| SDK — platform SDK adapters | events and logs |
| Verification — QA, policy and technical verification | artifact references, versions, checksums |
| Init — repository scaffolding from the template | the workflow run lifecycle |

If a module needs something the engine does not offer, that is a gap in the kernel: raise it
and fix it there once, for every module — never special-case one module in `engine.py`.
`test_engine_source_names_no_step_type` fails if a step type or route label ever appears in
the engine.

---

## 1. Step interface

```python
from wgflib.workflow import ArtifactOutput, StepResult, WorkflowStep

class ResearchStep(WorkflowStep):
    type = "research"                                   # the registry key

    def execute(self, inputs, context) -> StepResult:
        ...
```

| Part | What it is |
|---|---|
| `self.definition` | The step's entry in the workflow file (`id`, `type`, `inputs`, `outputs`, `retry`, …) |
| `self.id` | The step id in this workflow (`research`) — not the type |
| `self.params` | The step's `with:` block: free-form, per-workflow parameters |
| `inputs` | `StepInputs` — the artifacts this step declared, see §4 |
| `context` | `WorkflowContext` — identifiers and services, see below |
| return | `StepResult` — outcome, optional route, artifacts, message/error, see §5 and §7 |

A new instance is constructed for every execution, so per-execution state on `self` never
leaks into a retry.

`context` carries, and only carries:

| Field | Meaning |
|---|---|
| `workflow_id`, `workflow_version`, `run_id`, `project_id` | Where this execution sits |
| `current_step`, `step_type` | This step's id and type |
| `attempt` | 1, 2, … within this visit (retries) |
| `visit` | 1, 2, … times the run entered this step (loops, `--from`) |
| `execution` | Total executions of this step in the run |
| `idempotency_key` | `<run_id>:<step_id>:<visit>` — stable across retries, crashes and resumes |
| `previous_outputs` | `ArtifactRef`s this step produced on its last successful execution |
| `decision` | A human decision recorded for this visit, or `None` (§9) |
| `config` | The factory configuration (read-only by convention) |
| `environment` | Run parameters: `mock`, `auto_approve`, … (read-only by convention) |
| `params` | Same as `self.params` |
| `logger` | Structured logging: `.debug/.info/.warning/.error(message, **fields)` |
| `emit(event, **fields)` | A custom event on the run's bus, tagged with this step |
| `run_dir` | The run's directory. For diagnostics only — never write state here |
| `mock` | True in a `--mock` run |

## 2. Registration

A module is an importable Python module with a `register(registry)` function:

```python
def register(registry):
    registry.register("research", ResearchStep)
```

`registry.register(type, factory)` — `factory(definition)` must return the step object; a
`WorkflowStep` subclass is such a factory. Types are kebab-case and may be namespaced with
dots (`discovery.research`); registering a type again replaces the earlier implementation.
`registry.resolve(type)` returns what is registered or raises `RegistryError`.

There is no `if step_type == ...` anywhere in the engine: a step type is only ever a registry
key. It is never imported, evaluated or turned into a path.

## 3. Configuration

Modules are declared in `workspace/config/factory.yaml`:

```yaml
factory:
  steps:
    modules: [wgf_discovery, wgf_strategy.steps]
```

At start-up the API imports each name with `importlib.import_module` and calls its
`register(registry)`. Names must be dotted Python identifiers — not paths, not expressions.
The module must be importable: installed, on `PYTHONPATH`, or a package under `scripts/`.
Only this installation-owned file names code; a workflow file never does.

Resolution order: the built-in `human-checkpoint`, then configured modules in list order
(later wins), then — only with `--mock` — the placeholders, which replace everything. A run
whose scope names a type nothing implements is refused before any state is written.

## 4. Inputs

A step declares `inputs: [artifact-type, …]` in the workflow file. At execution:

- `inputs.refs[type]` — the newest `ArtifactRef` of that type in the run
- `inputs.load(type)` — its content; refused if the file changed since it was recorded
- `inputs.missing` — declared types the run does not hold
- `type in inputs` — whether one is present

Missing inputs are not an engine error, because `wgf verify` run on its own legitimately has
nothing upstream. The step decides: proceed, or return `WAITING_FOR_INPUT`. The engine
records which versions were consumed (`StepState.consumed`, and `consumed` in the run's
trail), so every output can be traced to the exact input versions it was built from.

Never read another step's output any other way, and never call another step.

## 5. Outputs

```python
return StepResult.success([ArtifactOutput("opportunity", content, metadata={"sources": 12})])
```

- The type must be one of the step's declared `outputs`, or the step fails.
- On `SUCCESS`, every declared output must be present, or the step fails.
- `name=` (optional, kebab-case) gives the artifact its own id; default is the type.
- Producing the same id again is a new **version** (`v1`, `v2`, …); all are kept.
- `metadata` is small and structured; it lands in the `ArtifactRef`, never the content.
- Content goes to `artifacts/<id>/v<n>.json`. Run state holds only the reference.

Any artifact returned with a non-`SUCCESS` result is still persisted — a failing QA report is
evidence.

### The pipeline's input/output contract

The executable source is `core/workflows/new-game.workflow.yaml`. This table restates it for
reading, and `DocumentedIoContract` fails if the two disagree.

<!-- io-contract:start -->
| Step | Type | Inputs | Outputs |
|---|---|---|---|
| `research` | `research` | — | `research-report`, `opportunity` |
| `strategy` | `strategy` | `opportunity` | `title-strategy` |
| `strategy-review` | `human-checkpoint` | `title-strategy` | — |
| `design` | `design` | `title-strategy` | `game-design` |
| `tech-plan` | `tech-plan` | `game-design`, `title-strategy` | `tech-plan` |
| `tech-plan-review` | `human-checkpoint` | `game-design`, `tech-plan` | — |
| `init` | `init` | `game-design`, `tech-plan` | `scaffold-record` |
| `assets` | `assets` | `game-design`, `scaffold-record` | `asset-manifest` |
| `develop` | `develop` | `game-design`, `asset-manifest`, `scaffold-record`, `title-strategy`, `qa-report`, `review-report` | `prototype-report` |
| `review` | `review` | `prototype-report`, `game-design`, `scaffold-record` | `review-report` |
| `sdk` | `sdk` | `game-design`, `scaffold-record`, `prototype-report` | `sdk-report` |
| `verify` | `verify` | `prototype-report`, `sdk-report`, `game-design`, `scaffold-record`, `asset-manifest` | `verification-report`, `qa-report` |
| `prototype-review` | `human-checkpoint` | `qa-report`, `verification-report`, `prototype-report`, `title-strategy`, `game-design` | — |
| `release` | `release` | `qa-report`, `verification-report`, `sdk-report`, `prototype-report`, `scaffold-record`, `review-report` | `release-manifest` |
<!-- io-contract:end -->

A `human-checkpoint` lists the artifacts its gate is decided on (gates.yaml
`required_artifacts`) and waits for input until the run holds them; `prototype-review` is
G4, which only a person decides (pass / iterate / kill).

`develop` declares `qa-report` so that on a verify → develop loop it receives the failing
report; on its first visit that input is missing, which is expected. It declares
`review-report` for the same reason on a review → develop loop: when `review` requests
changes to the commit develop made, the next brief leads with the reviewer's blockers
([review-module.md](review-module.md)). It reads
`scaffold-record` to find the game repository it builds in, and `title-strategy` for the
questions and kill criteria its `prototype-report` must list. `verify` emits the
`verification-report` — every check with its evidence — and the `qa-report` computed from it;
see [verification-module.md](verification-module.md). `release` produces a
`release-manifest` in state `draft` and stops: it refuses unless the newest qa-report passed
and every report and the clean checkout name one commit, packages with the game repository's
own scripts, and never publishes; see [release-module.md](release-module.md). Publishing is
behind G5 and G6.

Routing, retry and gates for each step are in the workflow file; read it, not a copy.

## 6. Artifact schemas

Every type above has a schema in `core/artifacts/<type>.schema.json`, and its `x-wgf` block
names producer, consumers, repository path, run-store path and contract version
(`x-wgf.version`). check-integrity fails when a workflow step's stage is not the producer of
what it outputs, or not among the consumers of what it reads. Before persisting an artifact
the engine validates it against the full schema (`contracts.ArtifactContracts`, the draft
2020-12 validator in `wgflib/jsonschema_lite.py`, differential-tested against ajv):

- content is a JSON object valid against the schema;
- `provenance.artifact_type` equals the type;
- `provenance.schema_version` has the major of the schema's `x-wgf.version`;
- `provenance.content_hash` reproduces (`wgflib.hashing.content_hash`, the canonicalization
  on `provenance.schema.json#/$defs/hash`).

A failure is a non-retryable `FAILED` and nothing is written.

Build provenance with `wgflib/provenance.py`, as every module and the mock steps do:
`build(artifact_type, artifact_id=..., produced_by=..., produced_at=..., inputs=...)` takes
`schema_version` from the schema's `x-wgf.version`; `artifact_id(...)` gives the
`wgf:<type>:<scope>:<yyyymmdd>-<nn>` shape; `producer(role)` a role from
`core/roles/roles.yaml`; `pin_inputs(inputs)` pins each consumed artifact by `content_hash`;
`seal(artifact)` computes `content_hash` last.

**Versioning.** `ArtifactRef.version` counts productions within a run. The *contract* version
is `provenance.schema_version`, copied to `ArtifactRef.schema_version`. Expectations:

- Adding an optional field is a minor schema version; consumers ignore fields they do not know.
- Removing or changing the meaning of a field is a major version: bump it, and teach the
  consumer to check `inputs.refs[type].schema_version` and refuse what it cannot read with
  `FAILED, retryable=False`.
- There is no migration framework. Schema changes follow CLAUDE.md: `core/` first.

**New types.** A module that needs a new artifact adds its schema in `core/artifacts/`,
names it in the producing and consuming machine stages and in `adapter-binding.yaml`, and
declares it in the workflow. A workflow may list a type under `untyped_artifacts` as a
temporary gap; the engine then accepts only a non-empty JSON object, and
`check-integrity.py` reports each such type on every run. The shipped workflow lists none.

## 7. Error handling

| Situation | Return | Engine does |
|---|---|---|
| Done | `StepResult.success(artifacts, route=None, message=…)` | routes `success` (or `route`) |
| Transient failure (network, rate limit, flaky tool) | `StepResult.failed(error)`, or raise | retries per policy |
| Failure that will recur (bad input, precondition refused) | `StepResult.failed(error, retryable=False)` | no retry; routes `failed` |
| A result that means "go elsewhere" (QA found defects) | `StepResult("FAILED", route="fail", retryable=False, artifacts=[report])` | routes `fail` if the workflow maps it, else fails the run |
| Cannot proceed without an outside change | `StepResult.blocked(message)` | run `BLOCKED` unless routed |
| Needs data that is not there yet | `StepResult.waiting_for_input(message)` | run `WAITING` |
| Needs a person | `StepResult.waiting_for_human(message)` | run `WAITING` |

Never return anything but a `StepResult`; never call `sys.exit`; never swallow an exception
into a `SUCCESS`. An exception escaping `execute` is a retryable failure with its traceback in
the event log.

## 8. Retry semantics

Retry is configuration, not code: `retry: {max_attempts, backoff, delay_seconds,
max_delay_seconds}` on the step, over workflow `defaults`, over `factory.execution`. Only a
retryable `FAILED` is retried; the attempt budget is per visit and resets on resume. After
the last attempt the result is routed like any other `failed`.

**Idempotency.** The engine guarantees *state-level* idempotency: a step that succeeded is not
re-executed by resume, and `--run` skips it. The engine cannot make an outside side effect
idempotent. **The step implementation is responsible for side-effect idempotency**: key the
effect on `context.idempotency_key` (or on `run_id` + step id, for effects that must happen
once per run rather than once per visit), and on re-execution look for what it already made
before making it again. `init` must never create a second repository; its
`scaffold-record.outcome` says `created` or `reused`, and the mock demonstrates the pattern.

## 9. Human checkpoints

A module does not implement approval gates; the workflow places a `human-checkpoint` step
where a person decides. A step that itself needs a person returns `waiting_for_human`, and
on resume finds the answer in `context.decision` (`{"decision", "decided_by", "decided_at",
"note"}`), which applies to one visit only.

Only a checkpoint tied to a *reversible* gate may be approved automatically, and only when
the run allows it. G4, G6 and G7 never are, and never accept a decision whose `decided_by` is
not `human`. A module must not work around this — for example by returning `SUCCESS` where
a human decision belongs.

A checkpoint records its decision in run state. Advancing a title's lifecycle is a separate
act: see §13.

## 10. Events

Log through `context.logger` (becomes `STEP_LOG`) and, rarely, `context.emit(...)` for a
custom event. The engine emits every lifecycle event itself; a module must not emit
`STEP_*`, `WORKFLOW_*` or `ARTIFACT_*` events. The event contract is in
[workflow-engine.md §10](workflow-engine.md#10-events-and-logs).

## 11. Testing

Every module ships tests that are deterministic and offline: no internet, GitHub, AI
provider, portal or external API. Fake them behind the module's own interfaces.

At minimum:

1. **Unit** — the step's `execute` with a fake `inputs` and `context`.
2. **Contract** — run the step through the real engine, the way
   `scripts/tests/test_workflow_contracts.py::ModuleContract` does: register it, run a small
   workflow, assert the run completes, the artifact is persisted and its reference recorded.
3. **Schema** — validate an emitted artifact with ajv (the command in CLAUDE.md).
4. **Failure paths** — each row of §7 the step can produce.
5. **Idempotency** — execute twice with the same `idempotency_key`; the side effect happens
   once.

Run the whole suite with `python -m unittest discover scripts/tests`.

## 12. Example module

The complete, tested version of this is `EXAMPLE_MODULE` in
`scripts/tests/test_workflow_contracts.py`.

```python
# wgf_example_module.py
from wgflib.workflow import ArtifactOutput, StepResult, WorkflowStep


class ExampleModuleStep(WorkflowStep):
    type = "example.module"

    def execute(self, inputs, context):
        if "example-brief" in inputs.missing:
            return StepResult.waiting_for_input("needs an example-brief")
        brief = inputs.load("example-brief")
        context.logger.info("example ran", topic=brief["topic"])
        return StepResult.success(
            [ArtifactOutput("example-output", {"summary": "about " + brief["topic"]})],
            message="example done",
        )


def register(registry):
    registry.register(ExampleModuleStep.type, ExampleModuleStep)
```

```yaml
# workspace/config/factory.yaml
factory:
  steps:
    modules: [wgf_example_module]
```

```yaml
# a workflow step using it
- id: example
  type: example.module
  inputs: [example-brief]
  outputs: [example-output]
```

## 13. What a module must NOT modify

- `scripts/wgflib/workflow/` — the kernel. Not to add a branch for your step, not to add a
  field you need; raise the gap instead.
- `scripts/wgf.py` — commands come from the workflow file.
- Another module's code, or another module's artifacts in a run.
- Run state (`.factory/…/state.json`, `events.jsonl`) — write only through `StepResult`.
- **Lifecycle state.** Workflow state (`RUNNING`, `WAITING`, `BLOCKED`, …) and a title's
  lifecycle state (`strategy`, `prototype-review`, `live`, …) are different machines. The
  engine never writes `workspace/`; a full mock run leaves it byte-for-byte unchanged, and a
  test checks that. A step that must advance a title does it only through `wgf-state.py`,
  with its guards and a decision record for gated edges — never by editing `state.json`.
- `core/` for a provider-specific reason. `core/` names no AI provider; a runtime that
  delegates to one lives in the module that registers it.
- The workflow's routing, retry or gates, to make a module's tests pass.
