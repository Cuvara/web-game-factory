#!/usr/bin/env python3
"""wgf - run the Factory's workflows.

Every command that does work is a slice of one workflow definition, executed by one engine:

    wgf new-game [--mock]                the whole workflow
    wgf research | plan | init | assets | develop | sdk | verify | release [--mock]
                                         one step, or a group of steps (`plan`)
    wgf resume <run-id> [--from STEP]    continue a run from where it stopped
    wgf resume <run-id> --decision CHOICE [--note TEXT]
    wgf decide <run-id> CHOICE [--note TEXT]
                                         answer a run waiting at a human checkpoint
    wgf <cmd> --resume <run-id> [...]    the same as `wgf resume`, whatever <cmd> is
    wgf <cmd> --run <run-id>             run that slice inside an existing run, reusing its
                                         artifacts; steps it already completed are skipped
    wgf new-game --from develop          start a run at a later step

    wgf status [run-id]                  where a run stands (default: the latest run)
    wgf logs [run-id] [--json]           its events, which are also its structured log
    wgf runs [--waiting] [--json]        every run in the store; or only those waiting for
                                         a decision, with the step, gate and choices
    wgf pause <run-id> | cancel <run-id> neither imports a step module
    wgf test-core [--only CATEGORY] [--json] [--strict]
                                         the Core Acceptance Suite, by category; --strict
                                         fails (exit 4) when a category was skipped

The run commands are generated from the default workflow's step ids and group names, so a
step added to core/workflows/new-game.workflow.yaml is a command without touching this file.

A fresh single-step command (`wgf develop`) still creates a run of its own; when that run
stops for inputs it does not hold, wgf names the latest run that holds them
(`hint: wgf develop --run <run-id>`).

Exit status: 0 completed, 1 failed/blocked/cancelled or left its scope on a failure (or an
OS error, such as a full disk), 2 usage - including a flag the command would otherwise
ignore: --mock, --mock-plan, --hold-gates or --project with --resume or --run, --from with
--run, --note without --decision - 3 waiting for a decision or input (or paused).
`wgf status` exits with the same code for the run it shows, and 0 for one still RUNNING.
`wgf test-core --strict` exits 4 when a whole category was skipped (1 still means a failure).

Run as `python scripts/wgf.py ...` or via the `bin/wgf` shim. A relative
factory.storage.directory resolves against the repository root, so every working directory
finds the same store; `--store` resolves against the working directory, as typed.
"""

import argparse
import importlib
import io
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wgflib.workflow.api import (  # noqa: E402
    RunRequest, WorkflowAPI, missing_inputs, pending_decision)
from wgflib.workflow.config import load_config  # noqa: E402
from wgflib.workflow.definition import DefinitionError  # noqa: E402
from wgflib.workflow.engine import EngineError  # noqa: E402
from wgflib.workflow.model import RunStatus, StepOutcome, StepStatus  # noqa: E402
from wgflib.workflow.step import RegistryError  # noqa: E402
from wgflib.workflow.store import RunLocked, StoreError  # noqa: E402
from wgflib.yamllite import YamlError, load as load_yaml  # noqa: E402

EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_WAITING = 0, 1, 2, 3


class UsageError(Exception):
    """A command line wgf would not carry out as written: exit 2, nothing touched."""

_UNICODE = {
    StepStatus.SUCCESS: "✓", StepStatus.FAILED: "✗", StepStatus.RUNNING: "▶",
    StepStatus.WAITING: "⏸", StepStatus.BLOCKED: "■", StepStatus.SKIPPED: "–",
    StepStatus.PENDING: "○", "OUT": "·",
}
_ASCII = {
    StepStatus.SUCCESS: "+", StepStatus.FAILED: "x", StepStatus.RUNNING: ">",
    StepStatus.WAITING: "=", StepStatus.BLOCKED: "#", StepStatus.SKIPPED: "-",
    StepStatus.PENDING: "o", "OUT": ".",
}


def _symbols():
    encoding = (getattr(sys.stdout, "encoding", None) or "").lower()
    return _UNICODE if "utf" in encoding else _ASCII


# -- rendering ------------------------------------------------------------------------------


def _duration(seconds):
    if seconds is None:
        return "-"
    seconds = max(0, int(round(seconds)))
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m{seconds:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


def render_liveness(live):
    """The current (or last) step and whether anything is actually happening."""
    if not live or not live.get("step"):
        return [f"Liveness: {live['liveness']}"] if live else []
    step = (f"Step:     {live['step']}  attempt {live.get('attempt') or 0}, "
            f"visit {live.get('visit') or 0}  {live.get('status') or ''}").rstrip()
    lines = [step]
    detail = []
    if live.get("driver_pid"):
        detail.append(f"driver pid {live['driver_pid']}")
    if live.get("pid"):
        detail.append(f"child pid {live['pid']}")
    if live.get("last_event"):
        detail.append(f"last event {live['last_event']}")
    lines.append(f"Liveness: {live['liveness']}" + (f"  ({'; '.join(detail)})" if detail else ""))
    lines.append(f"Started:  {live.get('started_at') or '-'}   "
                 f"elapsed {_duration(live.get('elapsed_seconds'))}")
    lines.append(f"Activity: {live.get('last_activity_at') or '-'}   "
                 f"{_duration(live.get('idle_seconds'))} ago")
    if live["liveness"] == "hung":
        lines.append(f"          nothing for longer than {live['hung_after_seconds']}s "
                     f"(factory.execution.hung_after_seconds); the step may be stuck. "
                     f"`wgf cancel {live['run_id']}` terminates it.")
    elif live["liveness"] == "stale":
        lines.append("          RUNNING on disk but no live process holds the run: its driver "
                     "crashed. Resume it to continue from this step.")
    return lines


def render_status(state, definition, live=None):
    marks = _symbols()
    lines = [
        f"Workflow: {state.workflow_id} (v{state.workflow_version})",
        f"Run:      {state.run_id}",
    ]
    if state.project_id:
        lines.append(f"Project:  {state.project_id}")
    lines.append("")

    width = max(len(step_id) for step_id in definition.step_ids)
    for step_def in definition.steps:
        step = state.steps.get(step_def.id)
        in_scope = step_def.id in state.scope
        if step is None or (step.visits == 0 and step.status == StepStatus.PENDING):
            mark = marks[StepStatus.PENDING] if in_scope else marks["OUT"]
            detail = "" if in_scope else "not in this run's scope"
        else:
            mark = marks[step.status]
            notes = []
            if step.visits > 1:
                notes.append(f"visits {step.visits}")
            if step.attempts > 1:
                notes.append(f"attempt {step.attempts}")
            if step.status in (StepStatus.FAILED, StepStatus.BLOCKED) and step.error:
                notes.append(step.error)
            elif step.status in (StepStatus.WAITING, StepStatus.BLOCKED) and step.message:
                notes.append(step.message)
            detail = "; ".join(notes)
        cursor = "  <- next" if (state.cursor == step_def.id and state.status
                                 not in (RunStatus.RUNNING, RunStatus.COMPLETED)) else ""
        lines.append(f"{mark} {step_def.id:<{width}}  {detail}{cursor}".rstrip())

    lines.append("")
    lines.append(f"Status: {state.status}")
    if state.message:
        lines.append(f"        {state.message}")
    if state.exit and state.exit.get("next") not in (None, "$end"):
        lines.append(f"Next:   {state.exit['next']} (outside this run's scope; "
                     f"wgf {state.exit['next']} --run {state.run_id})")
    if live is not None:
        lines.append("")
        lines.extend(render_liveness(live))
    hint = _resume_hint(state, live, definition)
    if hint:
        lines.append(hint)
    return "\n".join(lines)


def _resume_hint(state, live=None, definition=None):
    command = f"wgf resume {state.run_id}"
    if live is not None and live.get("liveness") == "stale":
        return f"Resume: {command}   (its driver died)"
    if state.status == RunStatus.WAITING:
        pending = pending_decision(state, definition)
        if pending is not None:
            choices = "|".join(pending["choices"] or ["CHOICE"])
            gate = f"   (gate {pending['gate']})" if pending.get("gate") else ""
            return f"Decide: wgf decide {state.run_id} {choices} [--note TEXT]{gate}"
        return f"Resume: {command}"
    if state.status in (RunStatus.FAILED, RunStatus.BLOCKED, RunStatus.PAUSED):
        return f"Resume: {command}   (after fixing the cause)"
    return None


class Progress:
    """Prints one line per interesting event. Subscribed to the engine's event bus."""

    def __init__(self, stream, as_json=False):
        self.stream = stream
        self.as_json = as_json
        self.marks = _symbols()

    def __call__(self, record):
        if self.as_json:
            print(json.dumps(record, ensure_ascii=False, sort_keys=True), file=self.stream)
            return
        line = self.format(record)
        if line:
            print(line, file=self.stream, flush=True)

    def format(self, record):
        event, step = record["event"], record.get("step_id", "")
        data = record.get("data") or {}
        m = self.marks
        if event == "WORKFLOW_STARTED":
            return f"Run {record['run_id']}: {' -> '.join(data.get('scope', []))}"
        if event == "WORKFLOW_RESUMED":
            return f"Resuming {record['run_id']} (was {data.get('from_status', '?')})"
        if event == "STEP_STARTED":
            return f"{m[StepStatus.RUNNING]} {step}" + (
                f" (attempt {record['attempt']})" if record.get("attempt", 1) > 1 else "")
        if event == "STEP_COMPLETED":
            route = f" [{data['route']}]" if data.get("route") else ""
            return f"{m[StepStatus.SUCCESS]} {step}{route}  {record.get('duration_ms', 0)}ms"
        if event == "STEP_FAILED":
            retry = "  - will retry" if data.get("will_retry") else ""
            return f"{m[StepStatus.FAILED]} {step}: {record.get('error')}{retry}"
        if event == "STEP_RETRIED":
            return (f"  retry {step} attempt {record['attempt']}/{data.get('max_attempts')}"
                    f" after {data.get('delay_seconds', 0)}s")
        if event == "STEP_SKIPPED":
            return f"{m[StepStatus.SKIPPED]} {step} skipped: {data.get('reason')}"
        if event == "STEP_WAITING":
            return f"{m[StepStatus.WAITING]} {step}: {data.get('message')}"
        if event == "STEP_BLOCKED":
            return f"{m[StepStatus.BLOCKED]} {step}: {data.get('message')}"
        if event == "TRANSITION" and data.get("kind") == "goto" and data.get("route") not in (
                None, "success", "pass", "approve"):
            return f"  {step} --{data['route']}--> {data.get('to')}"
        return None


def render_logs(events, as_json):
    if as_json:
        return "\n".join(json.dumps(e, ensure_ascii=False, sort_keys=True) for e in events)
    lines = []
    for e in events:
        extras = []
        for key in ("level", "message", "attempt", "status", "duration_ms", "error"):
            if key in e:
                extras.append(f"{key}={e[key]}")
        if e.get("data"):
            extras.append(json.dumps(e["data"], ensure_ascii=False, sort_keys=True))
        lines.append(f"{e['ts']}  {e['event']:<19} {e.get('step_id', '-'):<16} {' '.join(extras)}")
    return "\n".join(lines)


def exit_code(state):
    if state.status == RunStatus.COMPLETED:
        outcome = (state.exit or {}).get("outcome")
        return EXIT_OK if outcome in (None, StepOutcome.SUCCESS) else EXIT_FAILED
    if state.status in (RunStatus.WAITING, RunStatus.PAUSED):
        return EXIT_WAITING
    return EXIT_FAILED


def status_exit_code(state):
    """`wgf status` mirrors the run it shows; a run still being driven has not failed."""
    if state.status in (RunStatus.RUNNING, RunStatus.PENDING):
        return EXIT_OK
    return exit_code(state)


# -- arguments ------------------------------------------------------------------------------


def _mock_plan(value):
    if value is None:
        return None
    if value.startswith("@"):
        with open(value[1:], encoding="utf-8") as handle:
            value = handle.read()
    try:
        return json.loads(value)
    except ValueError:
        try:
            return load_yaml(value)
        except YamlError as exc:
            raise argparse.ArgumentTypeError(f"--mock-plan is neither JSON nor YAML: {exc}")


def _common(parser):
    parser.add_argument("--store", metavar="DIR", help="run storage (default: factory.storage)")
    parser.add_argument("--config", metavar="PATH", help="factory config file")
    parser.add_argument("--workflow", metavar="ID|PATH", help="workflow definition")


def build_parser(commands):
    parser = argparse.ArgumentParser(
        prog="wgf", description="Run the Factory's workflows.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Run commands: " + ", ".join(commands),
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    for name in commands:
        run = sub.add_parser(name, help=f"run {name}")
        _common(run)
        run.add_argument("--mock", action="store_true",
                         help="use the placeholder step implementations")
        run.add_argument("--mock-plan", metavar="JSON|@FILE",
                         help='script mock outcomes, e.g. {"verify": ["fail", "pass"]}')
        run.add_argument("--hold-gates", action="store_true",
                         help="with --mock, stop at human checkpoints instead of approving")
        run.add_argument("--resume", metavar="RUN_ID", help="continue a stopped run")
        run.add_argument("--run", metavar="RUN_ID", dest="run_id",
                         help="execute this command's steps inside an existing run")
        run.add_argument("--from", metavar="STEP", dest="from_step",
                         help="start (or, with --resume, restart) at this step")
        run.add_argument("--force", action="store_true",
                         help="with --run, re-execute steps that already completed")
        run.add_argument("--decision", metavar="CHOICE",
                         help="with --resume, answer a waiting checkpoint")
        run.add_argument("--note", metavar="TEXT", help="rationale recorded with --decision")
        run.add_argument("--project", metavar="ID", help="project/title id for the run")
        run.add_argument("--json", action="store_true", help="print events as JSON lines")
        run.add_argument("--quiet", action="store_true", help="print only the final status")
        run.set_defaults(handler=cmd_run, scope=name)

    resume = sub.add_parser("resume", help="continue a stopped run")
    _common(resume)
    resume.add_argument("run", metavar="RUN_ID")
    resume.add_argument("--from", metavar="STEP", dest="from_step",
                        help="restart at this step")
    resume.add_argument("--decision", metavar="CHOICE", help="answer a waiting checkpoint")
    resume.add_argument("--note", metavar="TEXT", help="rationale recorded with --decision")
    resume.add_argument("--json", action="store_true", help="print events as JSON lines")
    resume.add_argument("--quiet", action="store_true", help="print only the final status")
    resume.set_defaults(handler=cmd_resume)

    decide = sub.add_parser("decide", help="answer a run waiting for a decision")
    _common(decide)
    decide.add_argument("run", metavar="RUN_ID")
    decide.add_argument("choice", metavar="CHOICE", help="e.g. approve or reject")
    decide.add_argument("--note", metavar="TEXT", help="rationale recorded with the decision")
    decide.add_argument("--json", action="store_true", help="print events as JSON lines")
    decide.add_argument("--quiet", action="store_true", help="print only the final status")
    decide.set_defaults(handler=cmd_decide)

    status = sub.add_parser("status", help="show a run (default: latest)")
    _common(status)
    status.add_argument("run", nargs="?")
    status.add_argument("--json", action="store_true")
    status.set_defaults(handler=cmd_status)

    logs = sub.add_parser("logs", help="show a run's events")
    _common(logs)
    logs.add_argument("run", nargs="?")
    logs.add_argument("--json", action="store_true")
    logs.add_argument("--step", metavar="STEP")
    logs.set_defaults(handler=cmd_logs)

    runs = sub.add_parser("runs", help="list runs")
    _common(runs)
    runs.add_argument("--waiting", action="store_true",
                      help="only runs waiting for a decision, with the step, gate and choices")
    runs.add_argument("--json", action="store_true")
    runs.set_defaults(handler=cmd_runs)

    core = sub.add_parser(
        "test-core", help="run the Core Acceptance Suite",
        description="Exit status: 0 nothing failed (skips are listed, and the summary says "
                    "INCOMPLETE), 1 a category FAILED or is MISSING, 4 with --strict: "
                    "a whole category was skipped. The release gate is "
                    "`WGF_GOLDEN=1 bin/wgf test-core --strict`.")
    core.add_argument("--only", action="append", metavar="CATEGORY",
                      help="run only this category (repeatable), e.g. WORKFLOW")
    core.add_argument("--strict", action="store_true",
                      help="exit 4 if any category is SKIP: every category must have run. "
                           "Tests skipped inside a PASS category (opt-in live checks) are "
                           "listed but do not fail it")
    core.add_argument("--json", action="store_true")
    core.set_defaults(handler=cmd_test_core)

    for name, handler in (("pause", cmd_pause), ("cancel", cmd_cancel)):
        control = sub.add_parser(name, help=f"{name} a run")
        _common(control)
        control.add_argument("run")
        control.set_defaults(handler=handler)
    return parser


def _api(args, subscribers=()):
    return WorkflowAPI(config_path=args.config, store_dir=args.store, workflow=args.workflow,
                       subscribers=subscribers)


# -- commands -------------------------------------------------------------------------------


# What only a new run takes. An existing run keeps the mocks, mock plan, gate policy and
# project it was started with; given with --resume or --run, these would be ignored.
_NEW_RUN_ONLY = (("mock", "--mock"), ("mock_plan", "--mock-plan"),
                 ("hold_gates", "--hold-gates"), ("project", "--project"))

_NOTE_NEEDS_DECISION = "--note is recorded with a decision; it needs --decision CHOICE"


def _refuse_ignored_flags(args):
    """Refuse a flag the command would otherwise silently ignore."""
    if args.decision and not args.resume:
        raise UsageError("--decision needs --resume <run-id> (or: wgf decide <run-id> CHOICE)")
    if args.note is not None and not args.decision:
        raise UsageError(_NOTE_NEEDS_DECISION)
    if args.resume and args.run_id:
        raise UsageError("--resume and --run are exclusive")
    if args.force and not args.run_id:
        raise UsageError("--force only applies with --run")
    if args.run_id and args.from_step:
        raise UsageError(f"--from does not apply with --run, which runs this command's own "
                         f"steps; to restart at a step: wgf resume {args.run_id} --from STEP")
    existing = args.resume or args.run_id
    given = [flag for attr, flag in _NEW_RUN_ONLY if getattr(args, attr)]
    if existing and given:
        raise UsageError(
            f"{', '.join(given)} only {'applies' if len(given) == 1 else 'apply'} to a new "
            f"run; {'--resume' if args.resume else '--run'} continues {existing} with the "
            f"settings it was started with")


def _drive(api, args, request):
    """Run `request` and print where the run ended. Returns the RunState."""
    state = api.run(request)
    if not args.json:
        definition = api.definition_for(state)
        print()
        print(render_status(state, definition))
        if state.status == RunStatus.COMPLETED and exit_code(state) == EXIT_OK:
            print("\nWorkflow completed successfully.")
    return state


def _missing_input_hint(api, args, state):
    """For a fresh slice that stopped because the run it created holds none of its inputs.

    Running a step on its own is legitimate - `wgf verify` against nothing upstream - so the
    run stands; but the person most likely meant it to run inside the run holding them.
    """
    if state.status not in (RunStatus.WAITING, RunStatus.BLOCKED):
        return None
    definition = api.definition_for(state)
    if args.scope == definition.id or pending_decision(state, definition) is not None:
        return None
    last = next((entry.get("outcome") for entry in reversed(state.trail)
                 if entry.get("step") == state.cursor), None)
    if last not in (StepOutcome.WAITING_FOR_INPUT, StepOutcome.BLOCKED):
        return None
    missing = missing_inputs(state, definition)
    if not missing:
        return None
    holder = api.latest_run_holding(missing, state.workflow_id, exclude=state.run_id)
    needs = f"{state.cursor} needs {', '.join(missing)}, which this new run does not hold"
    if holder is None:
        return (f"hint: {needs}, and no other run does either; produce them first, or run "
                f"it inside the run that will: wgf {args.scope} --run <run-id>")
    return (f"hint: {needs}; the latest run holding them is {holder.run_id}: "
            f"wgf {args.scope} --run {holder.run_id}")


def cmd_run(args):
    _refuse_ignored_flags(args)
    progress = Progress(sys.stdout, as_json=args.json)
    api = _api(args, subscribers=() if args.quiet else (progress,))
    request = RunRequest(
        scope=args.scope, mock=args.mock, mock_plan=_mock_plan(args.mock_plan),
        resume=args.resume, from_step=args.from_step, run_id=args.run_id, force=args.force,
        decision=args.decision, note=args.note, project_id=args.project,
        hold_gates=args.hold_gates,
    )
    state = _drive(api, args, request)
    if not (args.resume or args.run_id):
        hint = _missing_input_hint(api, args, state)
        if hint:
            print(hint, file=sys.stderr)
    return exit_code(state)


def cmd_resume(args):
    if args.note is not None and not args.decision:
        raise UsageError(_NOTE_NEEDS_DECISION)
    progress = Progress(sys.stdout, as_json=args.json)
    api = _api(args, subscribers=() if args.quiet else (progress,))
    request = RunRequest(resume=args.run, from_step=args.from_step,
                         decision=args.decision, note=args.note)
    return exit_code(_drive(api, args, request))


def cmd_decide(args):
    """`wgf resume RUN --decision CHOICE`, for a run that is waiting for one.

    The decision goes through the engine's resume like any other: the visit it answers, its
    DECISION_RECORDED event and the rule that only a person decides G4/G6/G7 are the
    engine's and the checkpoint's, not this command's. `decided_by` is default_decider()'s.
    """
    progress = Progress(sys.stdout, as_json=args.json)
    api = _api(args, subscribers=() if args.quiet else (progress,))
    state = api.store.load(args.run)
    step = state.steps.get(state.cursor) if state.cursor else None
    if state.status != RunStatus.WAITING or step is None or step.status != StepStatus.WAITING:
        where = f" at {state.cursor} ({step.status})" if step is not None else ""
        raise UsageError(f"run {args.run} is {state.status}{where}, not waiting for a "
                         f"decision; see wgf status {args.run}")
    pending = api.pending(state)
    if pending is None:
        raise UsageError(f"run {args.run} is waiting at {state.cursor} for input, not for a "
                         f"decision; provide it, then wgf resume {args.run}")
    if pending["choices"] and args.choice not in pending["choices"]:
        raise UsageError(f"{args.choice!r} is not a choice at {state.cursor}: "
                         f"{', '.join(pending['choices'])}")
    request = RunRequest(resume=args.run, decision=args.choice, note=args.note)
    return exit_code(_drive(api, args, request))


def cmd_status(args):
    api = _api(args)
    state, definition = api.status(args.run)
    if state is None:
        print(f"no runs in {api.store.workflows}")
        return EXIT_USAGE
    live = api.liveness(state)
    if args.json:
        # The persisted state, plus the derived liveness under a key RunState ignores.
        print(json.dumps(dict(state.to_dict(), liveness=live), indent=2, ensure_ascii=False))
    else:
        print(render_status(state, definition, live))
    return status_exit_code(state)


def _warn(problems):
    for problem in problems:
        text = problem[1] if isinstance(problem, tuple) else problem
        print(f"wgf: warning: {text}", file=sys.stderr)


def cmd_logs(args):
    api = _api(args)
    problems = []
    state, events = api.events(args.run, problems)
    if state is None:
        print(f"no runs in {api.store.workflows}")
        return EXIT_USAGE
    if args.step:
        events = [e for e in events if e.get("step_id") == args.step]
    print(render_logs(events, args.json))
    _warn(problems)
    return EXIT_OK


def _run_row(state, pending=None):
    return {"run_id": state.run_id, "status": state.status, "workflow_id": state.workflow_id,
            "project_id": state.project_id, "created_at": state.created_at,
            "updated_at": state.updated_at, "cursor": state.cursor, "waiting": pending}


def cmd_runs(args):
    problems = []
    api = _api(args)
    if args.waiting:
        found = api.waiting(problems)
        rows = [_run_row(state, pending) for state, pending in found]
    else:
        found = api.runs(problems)
        rows = [_run_row(state) for state in found]
    if args.json:
        print(json.dumps({"runs": rows, "unreadable": [
            {"run_id": run_id, "message": message} for run_id, message in problems]},
            indent=2, ensure_ascii=False))
    elif args.waiting:
        for row in rows:
            pending = row["waiting"]
            print(f"{row['run_id']:<40} {pending['step']:<18} {pending['gate'] or '-':<5} "
                  f"{'|'.join(pending['choices'] or []) or '-'}")
        if rows:
            print("\nDecide: wgf decide <run-id> <choice> [--note TEXT]")
        elif not problems:
            print("no runs waiting for a decision")
    else:
        for row in rows:
            print(f"{row['run_id']:<40} {row['status']:<10} {row['workflow_id']:<12} "
                  f"{row['created_at']}  {row['cursor'] or ''}")
        if not rows and not problems:
            print("no runs")
    if not args.json:
        for run_id, _message in problems:
            print(f"{run_id:<40} {'UNREADABLE':<10}")
    _warn(problems)
    return EXIT_OK


# -- the Core Acceptance Suite ----------------------------------------------------------------

TESTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tests")
PASS, FAIL, SKIP, MISSING = "PASS", "FAIL", "SKIP", "MISSING"
# test-core --strict only: nothing failed, but a whole category did not run. Distinct from
# EXIT_FAILED, so a gate can tell "broken" from "not all of it was proved here".
EXIT_INCOMPLETE = 4


def load_core_suite(tests_dir=TESTS_DIR):
    """The category -> [test module] mapping, from tests/core_suite.py (data only)."""
    if tests_dir not in sys.path:
        sys.path.insert(0, tests_dir)
    module = importlib.import_module("core_suite")
    return {name: list(modules) for name, modules in module.SUITE.items()}


def run_core_suite(suite, tests_dir=TESTS_DIR, only=None, stream=None):
    """Run each category's test modules. Returns one row per category:

        {"category", "result", "tests", "passed", "failed", "errors", "skipped",
         "missing": [module...], "details": [text...],
         "skips": [{"id": test id, "reason": skip reason}...]}

    MISSING - a named module does not exist (an incomplete suite never looks green);
    FAIL    - any failure or error, including a module that does not import;
    SKIP    - zero tests ran, or every test that ran was skipped;
    PASS    - otherwise. A PASS category can still hold skipped tests; `skips` names them,
              so a partial run is never mistaken for a full one.
    """
    wanted = [name.upper() for name in only] if only else None
    unknown = [name for name in (wanted or []) if name not in suite]
    if unknown:
        raise ValueError(f"unknown categories {', '.join(unknown)}; known: "
                         f"{', '.join(suite)}")
    if tests_dir not in sys.path:
        sys.path.insert(0, tests_dir)
    rows = []
    for category, modules in suite.items():
        if wanted and category not in wanted:
            continue
        row = {"category": category, "result": None, "tests": 0, "passed": 0, "failed": 0,
               "errors": 0, "skipped": 0, "missing": [], "details": [], "skips": []}
        loader = unittest.TestLoader()
        tests = unittest.TestSuite()
        for name in modules:
            if not os.path.exists(os.path.join(tests_dir, f"{name}.py")):
                row["missing"].append(name)
                continue
            tests.addTests(loader.loadTestsFromName(name))
        buffer = io.StringIO()
        result = unittest.TextTestRunner(stream=stream or buffer, verbosity=0).run(tests)
        row["tests"] = result.testsRun
        row["failed"] = len(result.failures) + len(result.unexpectedSuccesses)
        row["errors"] = len(result.errors)
        row["skipped"] = len(result.skipped)
        row["passed"] = max(0, result.testsRun - row["failed"] - row["errors"]
                            - row["skipped"] - len(result.expectedFailures))
        row["details"] = [f"{test.id()}\n{text}" for test, text in
                          result.failures + result.errors]
        # A class or module skipped in setUpClass/setUpModule is one entry, with its own id.
        row["skips"] = [{"id": test.id(), "reason": str(reason)}
                        for test, reason in result.skipped]
        if row["missing"]:
            row["result"] = MISSING
        elif row["failed"] or row["errors"]:
            row["result"] = FAIL
        elif row["tests"] == 0 or row["skipped"] >= row["tests"]:
            row["result"] = SKIP
        else:
            row["result"] = PASS
        rows.append(row)
    return rows


def core_completeness(rows):
    """What did not run: {"complete", "skipped_categories", "skipped_in_pass"}.

    Complete means no category is SKIP and no PASS category skipped a test. FAIL and MISSING
    are not about completeness; they fail the suite on their own."""
    skipped_categories = [r["category"] for r in rows if r["result"] == SKIP]
    skipped_in_pass = sum(len(r.get("skips") or ()) for r in rows if r["result"] == PASS)
    return {"complete": not skipped_categories and not skipped_in_pass,
            "skipped_categories": skipped_categories, "skipped_in_pass": skipped_in_pass}


def core_exit_code(rows, strict=False):
    """--strict fails on a SKIP category - a part of Core the run did not prove at all. A
    test skipped inside a PASS category is an opt-in check (a live agent, ajv, a real
    template release) whose category was otherwise proved; it is listed, never hidden, but
    requiring every opt-in would make the release gate depend on paid live agent runs."""
    if any(r["result"] in (FAIL, MISSING) for r in rows):
        return EXIT_FAILED
    if strict and core_completeness(rows)["skipped_categories"]:
        return EXIT_INCOMPLETE
    return EXIT_OK


def _core_summary(rows, strict):
    total = f"{sum(r['tests'] for r in rows)} tests"
    if any(r["result"] in (FAIL, MISSING) for r in rows):
        return f"Core Acceptance Suite: FAILED ({total})"
    state = core_completeness(rows)
    if state["complete"]:
        return f"Core Acceptance Suite: OK ({total})"
    parts = []
    if state["skipped_categories"]:
        parts.append("skipped: " + ", ".join(state["skipped_categories"]))
    if state["skipped_in_pass"]:
        parts.append(f"{state['skipped_in_pass']} "
                     f"test{'s' if state['skipped_in_pass'] != 1 else ''} skipped in PASS "
                     f"categories")
    detail = "; ".join(parts)
    if strict and state["skipped_categories"]:
        return f"Core Acceptance Suite: INCOMPLETE ({detail}; --strict; {total})"
    return f"Core Acceptance Suite: OK (INCOMPLETE \u2014 {detail}; {total})"


def render_core_skips(rows):
    """The skipped tests, per category, grouped by reason: what was not proved, and why."""
    lines = []
    for r in rows:
        if not r.get("skips"):
            continue
        by_reason = {}
        for skip in r["skips"]:
            by_reason.setdefault(skip["reason"], []).append(skip["id"])
        lines.append(f"[{r['category']}] {len(r['skips'])} skipped")
        for reason, ids in by_reason.items():
            lines.append(f"  {reason} ({len(ids)})")
            lines.extend(f"    {test_id}" for test_id in ids)
    return lines


def render_core_table(rows, strict=False):
    width = max([len(r["category"]) for r in rows] + [8])
    lines = [f"{'CATEGORY':<{width}}  RESULT   TESTS  PASS  FAIL  ERROR  SKIP",
             "-" * (width + 42)]
    for r in rows:
        line = (f"{r['category']:<{width}}  {r['result']:<7} {r['tests']:>6} {r['passed']:>5}"
                f" {r['failed']:>5} {r['errors']:>6} {r['skipped']:>5}")
        if r["missing"]:
            line += f"  missing: {', '.join(r['missing'])}"
        lines.append(line)
    skips = render_core_skips(rows)
    if skips:
        lines += ["", "Skipped tests, by category and reason:"] + skips
    lines.append("")
    lines.append(_core_summary(rows, strict))
    return "\n".join(lines)


def cmd_test_core(args):
    suite = load_core_suite()
    rows = run_core_suite(suite, only=args.only)
    strict = bool(getattr(args, "strict", False))
    code = core_exit_code(rows, strict)
    if args.json:
        print(json.dumps({"ok": code == EXIT_OK, "strict": strict, **core_completeness(rows),
                          "categories": rows}, indent=2, ensure_ascii=False))
    else:
        print(render_core_table(rows, strict))
        for row in rows:
            for detail in row["details"]:
                print(f"\n[{row['category']}] {detail}")
    return code


def cmd_pause(args):
    state = _api(args).pause(args.run)
    print(f"{args.run}: {'PAUSED' if state.status == 'PAUSED' else 'pause requested; it stops at its next step boundary'}")
    return EXIT_OK


def cmd_cancel(args):
    state = _api(args).cancel(args.run)
    print(f"{args.run}: {'cancel requested' if state.status == 'RUNNING' else state.status}")
    return EXIT_OK


# -- entry ----------------------------------------------------------------------------------


def _commands(argv):
    """Run commands, read from the workflow the invocation will use."""
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config")
    pre.add_argument("--workflow")
    known, _ = pre.parse_known_args(argv)
    api = WorkflowAPI(config=load_config(known.config), workflow=known.workflow,
                      store_dir=os.devnull)
    return api.definition().commands()


def main(argv=None, cli=False):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        commands = _commands(argv)
    except (DefinitionError, FileNotFoundError, YamlError) as exc:
        print(f"wgf: cannot load the workflow definition: {exc}", file=sys.stderr)
        return EXIT_USAGE
    parser = build_parser(commands)
    args = parser.parse_args(argv)
    if cli and getattr(args, "handler", None) is not cmd_test_core:
        # Orphans reparent to wgf, not init: a daemon that detaches and clears its
        # environment is still ended with its step. Not under test-core, whose tests
        # start children of their own in this process.
        from wgflib import procs as _procs
        _procs.install_subreaper()
    if not getattr(args, "handler", None):
        parser.print_help()
        return EXIT_USAGE
    try:
        return args.handler(args)
    except (UsageError, EngineError, RegistryError, StoreError, RunLocked, KeyError,
            ValueError, DefinitionError) as exc:
        message = exc.args[0] if isinstance(exc, KeyError) and exc.args else exc
        print(f"wgf: {message}", file=sys.stderr)
        return EXIT_USAGE
    except OSError as exc:
        # A full disk, a read-only store, a permission: the environment, not the command
        # line. One line, no traceback; the run is left as its last save recorded it.
        print(f"wgf: {exc}", file=sys.stderr)
        return EXIT_FAILED


if __name__ == "__main__":
    # SIGTERM/SIGHUP unwind through SystemExit, so every child tree a step owns is
    # terminated instead of being orphaned (wgflib/procs.py). The run itself is left
    # resumable: `wgf status` reports it stale and `wgf resume <run-id>` continues it.
    from wgflib import procs as _procs
    _procs.install_signal_cleanup()
    sys.exit(main(cli=True))
