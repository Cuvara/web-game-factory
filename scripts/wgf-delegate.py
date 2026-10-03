#!/usr/bin/env python3
"""Delegate one task to an agent working in its own Orca worktree; audit what worktrees hold.

    python3 scripts/wgf-delegate.py spawn --task-id T1 --name improve-3d-environment \\
        --title "3D environment pass" --spec-file task.md --repo ../my-game [--base main] \\
        [--run <orca-run>] [--agent claude] [--model opus]
    python3 scripts/wgf-delegate.py audit --repo . [--run <orca-run>] [--base-ref origin/main] [--json]
    python3 scripts/wgf-delegate.py adopt --dispatch <ctx_...> --task-id T1 --title "..."
    python3 scripts/wgf-delegate.py ledger [--json]

`spawn` exits 0 only when Orca's receipt proves a new worktree, an agent terminal in it and
the task delivered (exit 1 otherwise, nothing recorded). Standard library only; see
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
    s.add_argument("--trust-workspace", action="store_true",
                   help="answer Claude Code's workspace-trust dialog (repositories you own only)")
    d = sub.add_parser("adopt", help="record a dispatch already running in its own worktree")
    d.add_argument("--dispatch", required=True)
    d.add_argument("--task-id", required=True)
    d.add_argument("--title", required=True)
    d.add_argument("--base", default="main")
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
                                       model=args.model,
                                       trust_workspace=args.trust_workspace)
            print(json.dumps(dict(entry), indent=2))
            return 0
        if args.command == "adopt":
            entry = wgf_delegate.adopt(args.dispatch, args.task_id, args.title, base=args.base)
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
                          + (f"  [task {row['task']}, {row['dispatch']}]" if row["task"] else ""))
            return 0
        entries = wgf_delegate.read_ledger()
        if args.json:
            print(json.dumps(entries, indent=2))
        else:
            for e in entries:
                print(f"{e.get('created_at')}  {e.get('task_id'):<12} {e.get('dispatch')}  "
                      f"{e.get('branch')}  {e.get('worktree')}")
        return 0
    except (wgf_delegate.DelegationError, OSError) as exc:
        print(f"wgf-delegate: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
