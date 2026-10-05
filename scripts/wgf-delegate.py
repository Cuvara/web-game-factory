#!/usr/bin/env python3
"""Delegate one task to an agent working in its own Orca worktree; audit what worktrees hold.

    python3 scripts/wgf-delegate.py spawn --task-id T1 --name improve-3d-environment \\
        --title "3D environment pass" --spec-file task.md --repo ../my-game [--base main] \\
        [--run <orca-run>] [--agent claude] [--model opus] [--role level-designer]
    python3 scripts/wgf-delegate.py status <task-id|dispatch> [--json]
    python3 scripts/wgf-delegate.py audit --repo . [--run <orca-run>] [--base-ref origin/main] [--json]
    python3 scripts/wgf-delegate.py adopt --dispatch <ctx_...> --task-id T1 --title "..."
    python3 scripts/wgf-delegate.py ledger [--json]

`spawn` exits 0 only when Orca's receipt proves a new worktree, an agent terminal in it and
the task delivered, and the agent's turn started there. Otherwise it exits 1 having recorded
AGENT_SPAWN_FAILED (Orca started nothing) or AGENT_UNVERIFIED (a dispatch exists: the message
names it, and the remedy - adopt it or stop it). `status` derives a delegation's live state
from Orca and git and records the transition. Standard library only; see
scripts/wgf_delegate.py and docs/orca-delegation.md.
"""

import argparse
import json
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wgf_delegate  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(prog="wgf-delegate", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("spawn", help="create a worktree and start an agent on a task in it")
    s.add_argument("--task-id", required=True)
    s.add_argument("--name", required=True, help="worktree name (Orca branches <user>/<name>)")
    s.add_argument("--title", required=True)
    s.add_argument("--spec-file", required=True, help="the concrete task, as markdown")
    s.add_argument("--repo", required=True)
    s.add_argument("--base", default="main")
    s.add_argument("--run")
    s.add_argument("--agent", default="claude")
    s.add_argument("--model")
    s.add_argument("--role", help="the specialist role the agent plays, recorded")
    s.add_argument("--trust-workspace", action="store_true",
                   help="answer Claude Code's workspace-trust dialog (repositories you own only)")
    t = sub.add_parser("status", help="the live state of one delegation, recorded")
    t.add_argument("ident", help="task id or dispatch id")
    t.add_argument("--json", action="store_true")
    d = sub.add_parser("adopt", help="record a dispatch already running in its own worktree")
    d.add_argument("--dispatch", required=True)
    d.add_argument("--task-id", required=True)
    d.add_argument("--title", required=True)
    d.add_argument("--base", default="main")
    d.add_argument("--name")
    d.add_argument("--role")
    a = sub.add_parser("audit", help="classify every worktree of a repository")
    a.add_argument("--repo", default=".")
    a.add_argument("--run")
    a.add_argument("--base-ref", default="origin/main")
    a.add_argument("--json", action="store_true")
    l = sub.add_parser("ledger", help="print recorded delegations")
    l.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        if args.command == "spawn":
            spec = pathlib.Path(args.spec_file).read_text(encoding="utf-8")
            entry = wgf_delegate.spawn(args.task_id, args.title, spec, args.name, args.repo,
                                       base=args.base, agent=args.agent, run=args.run,
                                       model=args.model, role=args.role,
                                       trust_workspace=args.trust_workspace)
            print(json.dumps(dict(entry), indent=2))
            return 0
        if args.command == "status":
            report = wgf_delegate.status(args.ident)
            if args.json:
                print(json.dumps(report, indent=2))
            else:
                evidence = report.get("git") or {}
                held = (f"{len(evidence.get('commits') or [])} commit(s)"
                        + (", uncommitted changes" if evidence.get("dirty") else "")
                        if evidence.get("readable") else
                        f"git UNKNOWN: {evidence.get('reason')}" if evidence else "")
                print(f"{report['task_id']}  {report.get('dispatch')}  "
                      f"{report.get('previous')} -> {report['state']}"
                      + ("" if report["recorded"] else " (unchanged)"))
                print(f"  {report.get('reason')}" + (f"; {held}" if held else ""))
            return 0
        if args.command == "adopt":
            entry = wgf_delegate.adopt(args.dispatch, args.task_id, args.title, name=args.name,
                                       base=args.base, role=args.role)
            print(json.dumps(dict(entry), indent=2))
            return 0
        if args.command == "audit":
            rows = wgf_delegate.audit(args.repo, run=args.run, base_ref=args.base_ref)
            if args.json:
                print(json.dumps(rows, indent=2))
            else:
                for row in rows:
                    print(f"{row['class']:<18} {row['branch']:<44} {row['head']}  {row['path']}")
                    print(f"{'':<18} {row['reason']}"
                          + (f"  [task {row['task']}, {row['dispatch']}, {row['state']}]"
                             if row["task"] else ""))
            return 0
        entries = wgf_delegate.read_ledger()
        if args.json:
            print(json.dumps(entries, indent=2))
        else:
            for d in wgf_delegate.delegations(entries).values():
                print(f"{d.get('updated_at')}  {d['task_id']:<12} {str(d.get('state')):<18} "
                      f"{d.get('dispatch')}  {d.get('branch')}  {d.get('worktree')}")
        return 0
    except (wgf_delegate.DelegationError, OSError) as exc:
        print(f"wgf-delegate: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
