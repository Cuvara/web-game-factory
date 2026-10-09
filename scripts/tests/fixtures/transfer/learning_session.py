"""One session of the K6.4 learning-transfer test, run in a process of its own.

    python learning_session.py make --session single|validated|circular --out FILE

Writes the runs of one session into the project's own run store (WGF_PROJECT_DIR/.factory,
the store `wgf` uses there) and their summary to --out; the test then runs the real
`wgf knowledge ingest` and `wgf knowledge promote` against that project, each in a process of
its own. The ledgers are made by the REAL triage step from playability reports the
playability step's own path judges over FIXTURE bot records, and visual-qa reports in the
visual-qa step's shape with a FIXTURE judge's scores (scripts/tests/learning_ledgers.py):

  single     one run: the objective never on screen FAILs start.objective on build A, the
             owner's visit fixes it on B, the gate passes it once - a single-run lesson
  validated  one run, three builds: A fails start.objective on desktop and on mobile, B and C
             pass both - reproduced on two scenarios; the specialist's candidate reported
             once per scenario
  circular   the single run, then only circular "validation": the same run's reports copied
             byte for byte into another run (the same report re-ingested), a later pass that
             replays the failing build (same-build), and a visual judge passing the fixed
             build and then re-reading that same build (self-agreement)

Not a test module.
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(os.path.dirname(HERE))
SCRIPTS = os.path.dirname(TESTS)
for _path in (SCRIPTS, TESTS):
    if _path not in sys.path:
        sys.path.insert(0, _path)

A, B, C = ("a" * 40, "b" * 40, "c" * 40)


def make(args):
    import learning_ledgers as ll
    from wgflib import paths
    from wgflib.workflow.api import WorkflowAPI
    store = WorkflowAPI().store
    work = os.path.join(paths.PROJECT, "work")
    runs = []

    def rounds(name, builds, producer="playability-report"):
        made = ll.Rounds(os.path.join(work, name))
        made.play(builds, producer)
        return made

    if args.session == "single":
        ll.store_run(store, "single-1", rounds("single-1", [(A, ll.blind()), (B, ll.well())]),
                     [ll.candidate(ll.OBJECTIVE)])
        runs = ["single-1"]
    elif args.session == "validated":
        made = rounds("validated-1", [(A, ll.blind()), (B, ll.well()), (C, ll.well())])
        ll.store_run(store, "validated-1", made, [[ll.candidate(ll.OBJECTIVE)],
                                                  [ll.candidate(ll.OBJECTIVE_MOBILE)]])
        runs = ["validated-1"]
    else:
        main = rounds("circular-1", [(A, ll.blind()), (B, ll.well()), (A, ll.well())])
        ll.store_run(store, "circular-1", main, [ll.candidate(ll.OBJECTIVE)])
        ll.store_run(store, "circular-copy", main, [ll.candidate(ll.OBJECTIVE)])
        judge = rounds("circular-judge", [(A, ll.judged(2, A, 1)), (B, ll.judged(4, B, 2)),
                                          (B, ll.judged(4, B, 3))], producer="visual-qa-report")
        ll.store_run(store, "circular-judge", judge, [ll.candidate(ll.ENVIRONMENT)])
        runs = ["circular-1", "circular-copy", "circular-judge"]
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump({"session": args.session, "runs": runs, "store": store.directory,
                   "project": paths.PROJECT, "argv": sys.argv,
                   "env": sorted(k for k in os.environ if k.startswith("WGF_"))}, handle)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    m = sub.add_parser("make")
    m.add_argument("--session", choices=("single", "validated", "circular"), required=True)
    m.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    return make(args)


if __name__ == "__main__":
    sys.exit(main())
