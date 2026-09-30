#!/usr/bin/env python3
"""Evaluate the guards on the transitions leaving an entity's current state.

Each guard answers GREEN, RED or UNKNOWN. UNKNOWN is not a failure and not a pass - it means
the question could not be decided from the data available, which is a blocker to report
rather than one to assume. Nothing here collapses the three into two.

Usage, from the web-game-factory repository root:

    python scripts/wgf-guard.py --title neon-drift
    python scripts/wgf-guard.py --title neon-drift --state prototype-review
    python scripts/wgf-guard.py --opportunity opp-001
    python scripts/wgf-guard.py --title neon-drift --guard inputs_fresh
    python scripts/wgf-guard.py --list

Exit code is 0 when every guard on at least one outgoing transition is GREEN - that is, when
something can legally happen next - and 1 otherwise.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wgflib.guards import GuardContext, evaluate_guard, known_guards  # noqa: E402
from wgflib.machine import MachineError, load_machine  # noqa: E402
from wgflib.workspace import (  # noqa: E402
    WorkspaceError,
    load_opportunity,
    load_portfolio_config,
    load_title,
)

SYMBOL = {"GREEN": "GREEN  ", "RED": "RED    ", "UNKNOWN": "UNKNOWN"}


def report(name, verdict, indent="    ", negated=False):
    """Print the verdict of the *check*, which for a negated guard is the inverse.

    Showing the underlying guard's colour next to `NOT guard` reads as the opposite of what
    the transition needs, which is precisely the mistake this whole module exists to avoid.
    """
    symbol = verdict.symbol
    if negated and verdict.value is not None:
        symbol = "RED" if verdict.value else "GREEN"
    print(f"{indent}{SYMBOL[symbol]} {'NOT ' if negated else ''}{name}")
    if verdict.reason:
        print(f"{indent}        {verdict.reason}")


def main():
    parser = argparse.ArgumentParser(description="Evaluate lifecycle guards.")
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--title", metavar="ID")
    target.add_argument("--opportunity", metavar="ID")
    parser.add_argument("--state", metavar="ID", help="override the entity's current state")
    parser.add_argument("--guard", metavar="NAME", help="evaluate a single guard")
    parser.add_argument("--game-repo", metavar="PATH", help="the title's game repository")
    parser.add_argument("--list", action="store_true", help="list computable guards and exit")
    args = parser.parse_args()

    if args.list:
        for name in known_guards():
            print(name)
        return 0

    if not args.title and not args.opportunity:
        parser.error("give --title or --opportunity")

    try:
        entity = load_title(args.title) if args.title else load_opportunity(args.opportunity)
        config = load_portfolio_config()
        machine = load_machine(entity.machine)
    except (WorkspaceError, MachineError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    context = GuardContext(entity, config=config, game_repo=args.game_repo)

    if args.guard:
        verdict = evaluate_guard(args.guard, context)
        report(args.guard, verdict, indent="")
        return 0 if verdict.value is True else 1

    state_id = args.state or entity.state["current_state"]
    try:
        transitions = machine.transitions_from(state_id)
    except MachineError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(f"{entity.machine}:{state_id}   {entity.id}")
    if machine.is_terminal(state_id):
        print("\nterminal state - nothing leaves it")
        return 0
    if not transitions:
        print("\nno transitions leave this state")
        return 1

    cache = {}
    passable = 0

    for transition in transitions:
        gate = f"  [gate {transition.gate}]" if transition.gate else ""
        print(f"\n  {transition.event} -> {transition.target}{gate}")

        checks = [(name, False) for name in transition.guards]
        checks += [(name, True) for name in transition.negated_guards]
        if not checks:
            print("    (no guards)")
            passable += 1
            continue

        clear = True
        for name, negated in checks:
            if name not in cache:
                cache[name] = evaluate_guard(name, context)
            verdict = cache[name]
            report(name, verdict, negated=negated)
            wanted = False if negated else True
            if verdict.value is not wanted:
                clear = False
        if clear:
            passable += 1

    print()
    print(f"transitions  {len(transitions)} available, {passable} with every guard satisfied")
    if passable == 0:
        print("\nBLOCKED - no transition has all of its guards satisfied")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
