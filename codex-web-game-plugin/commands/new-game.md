# /new-game (Web Game Factory)

**Workflow entry point** `core/workflows/new-game.workflow.yaml` — not a transition.
**Engine** `bin/wgf` (`scripts/wgf.py`), the Factory's only orchestrator.

This surface starts or resumes a run of the workflow above and reports it. The workflow file
is the single source of step order, retries, loops, gates, decisions and resume; nothing here
restates it, and nothing here decides for the engine or for a person.

Arguments: the text given with this prompt.

## Read first

1. `core/workflows/new-game.workflow.yaml`
2. `core/lifecycle/gates.yaml`
3. `docs/workflow-engine.md`
4. `workspace/config/factory.yaml`

## Arguments

Accept exactly these (the engine's own flags, `bin/wgf new-game --help` and
`bin/wgf resume --help`), and nothing else:

- new run: `--mock`, `--mock-plan <JSON|@FILE>` (with `--mock` only),
  `--hold-gates`, `--project <ID>`, `--from <STEP>`, `--store <DIR>`
- `resume <run-id>`, optionally with `--from <STEP>` and `--store <DIR>`: continues that
  run with the settings it started with

With `--store <DIR>`, pass the same `--store <DIR>` to every `bin/wgf` command for that
run (status, logs, resume).

Refuse, and run nothing, if the arguments contain anything else — in particular
`--decision`, `--note`, `decide`, `--budget-sessions`, `--budget-cost` or any other
`--budget-*` (a decision or a budget is a person's, typed by that person), `--config` or
`--workflow` (this surface runs this workflow under the configuration it reports),
`--resume`, `--run` or `--force` (use `resume <run-id>`), `--quiet` or `--json`
(the surface sets the output), or a second command.

## Procedure

1. **Preflight.** Stop unless `core/workflows/new-game.workflow.yaml` exists in the working directory
   (run from the factory repository root). For `resume <run-id>`, read
   `bin/wgf status <run-id> --json` first and stop unless `workflow_id` is `new-game`.
   Then act on it without starting anything when there is nothing to continue:
   `COMPLETED` — report it (step 6); `RUNNING` with liveness `running` — another
   process drives it, only report progress; `WAITING` at a gate whose `pending.timeout`
   is not `eligible` — report the gate (step 6) and stop. Anything else (a stopped,
   blocked, stale or failed run, or one waiting for input) is resumed at step 4.
2. **Report the effective autonomy** from `workspace/config/factory.yaml`, as configured —
   never change it: `factory.develop.developer.kind`, `factory.review.reviewer.kind`,
   `factory.checkpoints.auto_approve` (and `timeout_auto_approve`),
   `factory.init.source`. With `--mock` every step is a placeholder, and a mock run approves
   the reversible gates itself unless `--hold-gates` is given.
3. **Outward effects.** For a new run without `--mock` and with
   `factory.init.source: github`: warn that once G3 is passed the init step creates a
   GitHub repository (`gh repo create`), and start only after the user confirms.
4. **Start** as a long-running background process, not a blocking call: a run can take hours.
   Poll `bin/wgf status <run-id>` for progress.

   - new run: `bin/wgf new-game <arguments> --json`
   - resume: `bin/wgf resume <run-id> [--from <STEP>] [--store <DIR>] --json`

   Where `bin/wgf` cannot be executed (Windows), use `python scripts/wgf.py` in its place.
   Read `run_id` from the first event, `WORKFLOW_STARTED` (on resume, `WORKFLOW_RESUMED`),
   and tell the user.
5. **Progress.** Summarise `STEP_STARTED`, `STEP_COMPLETED` and `STEP_FAILED` events as they
   arrive. For detail: `bin/wgf status <run-id>` or `bin/wgf status <run-id> --json`.
   Retries, loops and resume belong to the engine: report them, never re-run a step, edit
   `.factory/`, or edit an artifact to move the run along.
6. **When the process exits**, read `bin/wgf status <run-id> --json` and act on the run's
   status (the process's exit code is the same contract: 0, 1, 2, 3):
   - **COMPLETED** (exit 0): report the run id, the artifacts it produced and the
     release-manifest draft. If `ended_by` is set — `Ended: kill at G4` — report the kill
     as the end of the title, never as a release.
   - **FAILED, BLOCKED or CANCELLED** (exit 1): show `status`, `cursor`, `blocked_reason`
     and `bin/wgf logs <run-id> --step <cursor>`. A release refused as `unreviewed` is
     the configured reviewer (`factory.review.reviewer.kind: none`) doing its job: report
     it; do not configure a reviewer or weaken the release. Suggest
     `/new-game resume <run-id>` or `bin/wgf resume <run-id> --from <STEP>`; fix nothing.
   - **Usage error** (exit 2, no run started): show stderr.
   - **WAITING or PAUSED** (exit 3): show `pending` — step, gate, choices, evidence — and
     `blocked_reason` if any, then stop. See the rule below. `pending: null` means the
     run waits for input, not a decision: report `cursor` and `message`.
7. **Result.** Run id, final status, artifacts, and what comes next. The workflow ends at a
   drafted release; G5 and G6 — building, packaging and publishing — are not part of it and
   belong to the game repository's CI.

## The gate rule

Never run `bin/wgf decide`, `wgf resume ... --decision`, or anything else that answers
a checkpoint — for any gate, and for the develop handoff. Commands run from this session are
recorded as a person's decision, so answering one would forge a human decision. Tell the user
how to decide, and stop. A decision is the engine's resume: typed by the user, it records the
decision and drives the run on, in the user's own shell, to its next stop — and a real run's
next stop can be hours away. `/new-game resume <run-id>` afterwards reports where it
stopped, and continues it if that shell was interrupted.

- at a gate: `! bin/wgf decide <run-id> <choice> --note "..."`, then `/new-game resume <run-id>`
- at `develop` with `factory.develop.developer.kind: handoff` (`pending` names no gate):
  report the step, its message and the brief path it gives; the developer finishes the work
  and runs `! bin/wgf resume <run-id> --decision done`, then `/new-game resume <run-id>`.
  Development is not complete until the engine says so.

Do not change `workspace/config/factory.yaml` to make a run more autonomous, and do not
advance a lifecycle state: the engine never moves one, and neither does this surface.
