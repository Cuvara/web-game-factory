#!/usr/bin/env python3
"""Run one golden run: the real new-game workflow for the 2D or the 3D golden game.

    python3 scripts/golden/run.py --game 2d|3d [--workdir DIR] [--keep] [--json]
                                  [--resume RUN --from STEP] [--no-browser]

Exit status: 0 when the run passed (every step at its expected outcome, a drafted release
manifest, the engine consistent, and the independent browser evidence passed), 1 otherwise.
The summary lands in <workdir>/evidence/golden-<game>.json; the work directory is removed
afterwards unless --keep or --workdir is given. See docs/golden-runs.md.
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from wgflib import procs  # noqa: E402

from golden import harness  # noqa: E402


class Progress:
    """Prints one line per finished step - a subscriber like the CLI's own."""

    def __init__(self, stream):
        self.stream = stream

    def __call__(self, record):
        event = record.get("event")
        if event in ("STEP_COMPLETED", "STEP_FAILED", "STEP_BLOCKED", "STEP_WAITING"):
            seconds = (record.get("duration_ms") or 0) / 1000
            message = ((record.get("data") or {}).get("message") or record.get("error")
                       or "")
            print(f"  {event[5:]:9} {record.get('step_id'):18} {seconds:7.1f}s  "
                  f"{str(message)[:110]}", file=self.stream, flush=True)
        elif event in ("WORKFLOW_COMPLETED", "WORKFLOW_FAILED", "WORKFLOW_BLOCKED",
                       "WORKFLOW_PAUSED", "WORKFLOW_CANCELLED"):
            print(f"  {event}", file=self.stream, flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run a golden new-game run.")
    parser.add_argument("--game", required=True, choices=["2d", "3d"])
    parser.add_argument("--workdir", help="work directory (kept); default: a fresh temp dir")
    parser.add_argument("--keep", action="store_true", help="keep the temp work directory")
    parser.add_argument("--json", action="store_true", help="print the summary as JSON")
    parser.add_argument("--resume", metavar="RUN", help="resume a run in --workdir")
    parser.add_argument("--from", dest="from_step", metavar="STEP")
    parser.add_argument("--no-browser", action="store_true",
                        help="skip the independent browser evidence (the run cannot pass)")
    args = parser.parse_args(argv)
    if args.resume and not args.workdir:
        parser.error("--resume needs the --workdir of the run")
    procs.install_signal_cleanup()

    stream = sys.stderr if args.json else sys.stdout
    run = harness.GoldenRun(args.game, workdir=args.workdir, keep=args.keep,
                            progress=Progress(stream), browser=not args.no_browser)
    print(f"golden {args.game}: {run.game.title_id} ({run.game.engine}) in {run.workdir}",
          file=stream, flush=True)
    try:
        summary = run.execute(resume=args.resume, from_step=args.from_step)
    finally:
        procs.terminate_all()
    ok = summary["passed"] and summary["browser_passed"]
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True, default=str))
    else:
        print(f"\nrun {summary['run_id']}: {summary['run_status']} in {summary['duration_s']}s",
              file=stream)
        for step in summary["steps"]:
            mark = "ok " if step["reached"] else "NO "
            print(f"  {mark}{step['step']:18} {step['status']:10} {step['duration_s']}s",
                  file=stream)
        print(f"engine consistent: {summary['engine']['consistent']}; release drafted: "
              f"{bool(summary['release'] and summary['release']['manifest_path'])}; browser: "
              f"{summary['browser_passed']}", file=stream)
        print(f"summary: {summary.get('summary_path')}", file=stream)
        print("PASS" if ok else "FAIL", file=stream)
    run.cleanup()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
