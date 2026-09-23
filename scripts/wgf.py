#!/usr/bin/env python3
"""wgf - run the Factory's workflows.

Every command that does work is a slice of one workflow definition, executed by one engine:

    wgf new-game [--mock]                the whole workflow
    wgf research | plan | init | assets | develop | sdk | verify | release [--mock]
                                         one step, or a group of steps (`plan`)
    wgf <cmd> --resume <run-id>          continue a run from where it stopped
    wgf <cmd> --resume <run-id> --decision approve
                                         answer a run waiting at a human checkpoint
    wgf <cmd> --run <run-id>             run that slice inside an existing run, reusing its
                                         artifacts; steps it already completed are skipped
    wgf new-game --from develop          start a run at a later step

    wgf status [run-id]                  where a run stands (default: the latest run)
    wgf logs [run-id] [--json]           its events, which are also its structured log
    wgf runs                             every run in the store
    wgf pause <run-id> | cancel <run-id>

The run commands are generated from the default workflow's step ids and group names, so a
step added to core/workflows/new-game.workflow.yaml is a command without touching this file.

Exit status: 0 completed, 1 failed/blocked/cancelled or left its scope on a failure,
2 usage, 3 waiting for a decision or input (or paused).

Run from the web-game-factory repository root, as `python scripts/wgf.py ...` or via the
`bin/wgf` shim.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wgflib.workflow.api import RunRequest, WorkflowAPI  # noqa: E402
from wgflib.workflow.config import load_config  # noqa: E402
from wgflib.workflow.definition import DefinitionError  # noqa: E402
from wgflib.workflow.engine import EngineError  # noqa: E402
from wgflib.workflow.model import RunStatus, StepOutcome, StepStatus  # noqa: E402
from wgflib.workflow.step import RegistryError  # noqa: E402
from wgflib.workflow.store import RunLocked, StoreError  # noqa: E402
from wgflib.yamllite import YamlError, load as load_yaml  # noqa: E402

EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_WAITING = 0, 1, 2, 3

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


def render_status(state, definition):
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
    hint = _resume_hint(state)
    if hint:
        lines.append(hint)
    return "\n".join(lines)


def _resume_hint(state):
    command = f"wgf {state.workflow_id} --resume {state.run_id}"
    if state.status == RunStatus.WAITING:
        step = state.steps.get(state.cursor)
        if step and step.status == StepStatus.WAITING:
            return f"Decide: {command} --decision approve|reject [--note TEXT]"
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
    runs.set_defaults(handler=cmd_runs)

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


def cmd_run(args):
    if args.decision and not args.resume:
        raise SystemExit("--decision needs --resume <run-id>")
    if args.resume and args.run_id:
        raise SystemExit("--resume and --run are exclusive")
    if args.force and not args.run_id:
        raise SystemExit("--force only applies with --run")

    progress = Progress(sys.stdout, as_json=args.json)
    api = _api(args, subscribers=() if args.quiet else (progress,))
    request = RunRequest(
        scope=args.scope, mock=args.mock, mock_plan=_mock_plan(args.mock_plan),
        resume=args.resume, from_step=args.from_step, run_id=args.run_id, force=args.force,
        decision=args.decision, note=args.note, project_id=args.project,
        hold_gates=args.hold_gates,
    )
    state = api.run(request)
    if not args.json:
        definition = api.definition_for(state)
        print()
        print(render_status(state, definition))
        if state.status == RunStatus.COMPLETED and exit_code(state) == EXIT_OK:
            print("\nWorkflow completed successfully.")
    return exit_code(state)


def cmd_status(args):
    api = _api(args)
    state, definition = api.status(args.run)
    if state is None:
        print(f"no runs in {api.store.workflows}")
        return EXIT_USAGE
    if args.json:
        print(json.dumps(state.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(render_status(state, definition))
    return EXIT_OK


def cmd_logs(args):
    api = _api(args)
    state, events = api.events(args.run)
    if state is None:
        print(f"no runs in {api.store.workflows}")
        return EXIT_USAGE
    if args.step:
        events = [e for e in events if e.get("step_id") == args.step]
    print(render_logs(events, args.json))
    return EXIT_OK


def cmd_runs(args):
    runs = _api(args).runs()
    for state in runs:
        print(f"{state.run_id:<40} {state.status:<10} {state.workflow_id:<12} "
              f"{state.created_at}  {state.cursor or ''}")
    if not runs:
        print("no runs")
    return EXIT_OK


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


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        commands = _commands(argv)
    except (DefinitionError, FileNotFoundError, YamlError) as exc:
        print(f"wgf: cannot load the workflow definition: {exc}", file=sys.stderr)
        return EXIT_USAGE
    parser = build_parser(commands)
    args = parser.parse_args(argv)
    if not getattr(args, "handler", None):
        parser.print_help()
        return EXIT_USAGE
    try:
        return args.handler(args)
    except (EngineError, RegistryError, StoreError, RunLocked, KeyError, ValueError,
            DefinitionError) as exc:
        message = exc.args[0] if isinstance(exc, KeyError) and exc.args else exc
        print(f"wgf: {message}", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
