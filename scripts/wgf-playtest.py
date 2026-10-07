#!/usr/bin/env python3
"""wgf-playtest - a person files what they saw playing a build, as blocking quality findings.

    wgf-playtest.py file <run-id> FILE [--build COMMIT] [--note TEXT]
        FILE: a JSON list of quality-finding requests (the shape `wgf decide <run> iterate
        --findings` takes, core/artifacts/shared/quality-finding.schema.json#/$defs/request),
        or {"findings": [...], "measures": {"<finding id>": "<metric id>"}}: a finding that
        names a metric of core/reference/accepted-baseline.yaml closes when that metric passes
        on a newer build. --build: the commit played (default: the run's newest
        prototype-report's).
    wgf-playtest.py confirm <run-id> FINDING_ID [--note TEXT]
        a person confirms a playtest finding fixed: it closes on the next baseline-regression.
    wgf-playtest.py list <run-id> [--json]
        the run's playtest findings and their status.

The notes are stored in the run (`<run>/playtest/`, by content hash, docs/accepted-baseline.md)
and read by the run's baseline-regression step: an open finding of a blocking severity fails
the step - routed by triage to the specialist that owns it - and holds the quality gate. It
never closes on a newer build alone: only the metric it names passing on a newer build, or a
person's `confirm`. Refused from inside a Factory step's process tree: an agent does not file
or close a person's findings.

Exit: 0 done, 1 refused, 2 usage.
"""

import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wgf_baseline import playtest  # noqa: E402
from wgflib.workflow.api import WorkflowAPI, spawned_by_a_step  # noqa: E402


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] \
        + "Z"


def _run_dir(args):
    api = WorkflowAPI(config_path=args.config, store_dir=args.store)
    run_dir = api.store.run_dir(args.run)
    if not os.path.isfile(os.path.join(run_dir, "state.json")):
        raise SystemExit(f"wgf-playtest: no run {args.run} in {api.store.workflows}")
    return run_dir


def _newest_build(run_dir):
    with open(os.path.join(run_dir, "state.json"), encoding="utf-8") as handle:
        state = json.load(handle)
    best = None
    for versions in (state.get("artifacts") or {}).values():
        for entry in versions or []:
            if isinstance(entry, dict) and entry.get("type") == "prototype-report" and (
                    best is None or (entry.get("seq") or 0) > (best.get("seq") or 0)):
                best = entry
    if best is None:
        return None
    with open(os.path.join(run_dir, best["location"]), encoding="utf-8") as handle:
        return ((json.load(handle).get("build_ref") or {}).get("commit_sha"))


def _refuse_agent():
    if spawned_by_a_step():
        print("wgf-playtest: refused - this runs inside a Factory step's process tree; a "
              "person files and confirms playtest findings, from outside the run",
              file=sys.stderr)
        raise SystemExit(1)


def cmd_file(args):
    _refuse_agent()
    from wgf_triage.step import validate_requests
    run_dir = _run_dir(args)
    try:
        with open(args.file, "rb") as handle:
            raw = handle.read()
        data = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError) as exc:
        print(f"wgf-playtest: {args.file}: {exc}", file=sys.stderr)
        return 2
    requests = data.get("findings") if isinstance(data, dict) else data
    problems = validate_requests(requests)
    if problems:
        print(f"wgf-playtest: {args.file} is not a list of quality findings "
              "(core/artifacts/shared/quality-finding.schema.json#/$defs/request): "
              + "; ".join(problems[:6]), file=sys.stderr)
        return 2
    build = args.build or _newest_build(run_dir)
    if not build:
        print("wgf-playtest: no --build and the run holds no prototype-report: name the "
              "commit you played", file=sys.stderr)
        return 2
    act = playtest.file_notes(run_dir, raw, build=build, filed_at=_now(), filed_by="human",
                              note=args.note)
    print(f"filed {len(requests)} playtest finding(s) against {build[:12]}: {act['file']} "
          f"{act['sha256']}")
    return 0


def cmd_confirm(args):
    _refuse_agent()
    run_dir = _run_dir(args)
    known = {n["id"] for n in playtest.findings(run_dir, {}, None)}
    if args.finding not in known:
        print(f"wgf-playtest: {args.finding} is not a playtest finding of {args.run} "
              f"(known: {', '.join(sorted(known)) or 'none'})", file=sys.stderr)
        return 2
    playtest.confirm(run_dir, args.finding, build=_newest_build(run_dir),
                     confirmed_at=_now(), confirmed_by="human", note=args.note)
    print(f"confirmed {args.finding} fixed: it closes on the next baseline-regression")
    return 0


def cmd_list(args):
    run_dir = _run_dir(args)
    notes = playtest.findings(run_dir, {}, None)
    if args.json:
        print(json.dumps(notes, indent=2, sort_keys=True))
        return 0
    for note in notes:
        print(f"{note['id']}  {note['severity']:8} {note['status']:7} "
              f"{note['request'].get('summary')}")
    if not notes:
        print("no playtest findings")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="wgf-playtest.py", description=__doc__.split("\n")[0])
    parser.add_argument("--config", help="factory.yaml to read (default: the project's)")
    parser.add_argument("--store", help="the run store (default: factory.storage.directory)")
    sub = parser.add_subparsers(dest="command", required=True)
    filed = sub.add_parser("file", help="file playtest findings against a build")
    filed.add_argument("run")
    filed.add_argument("file")
    filed.add_argument("--build", metavar="COMMIT")
    filed.add_argument("--note", metavar="TEXT")
    filed.set_defaults(handler=cmd_file)
    confirmed = sub.add_parser("confirm", help="confirm a playtest finding fixed")
    confirmed.add_argument("run")
    confirmed.add_argument("finding")
    confirmed.add_argument("--note", metavar="TEXT")
    confirmed.set_defaults(handler=cmd_confirm)
    listed = sub.add_parser("list", help="the run's playtest findings")
    listed.add_argument("run")
    listed.add_argument("--json", action="store_true")
    listed.set_defaults(handler=cmd_list)
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except playtest.PlaytestError as exc:
        print(f"wgf-playtest: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
